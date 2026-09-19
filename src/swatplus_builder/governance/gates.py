"""Gate functions for claim governance — zero hydrology imports.

Each gate takes a ``values`` dict (the evidence payload) and returns
``{"passed": bool, "reason": str}``.  The sensitivity gate additionally
requires the caller to supply the set of governed parameters (so this module
remains domain-agnostic).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from ..evidence.integrity import (
    input_configuration_fingerprint,
    read_object,
    verify_benchmark_artifacts,
    verify_digest,
)


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def fresh_engine_gate(values: dict[str, Any]) -> dict[str, Any]:
    if values.get("fresh_engine_run") is not True:
        return {"passed": False, "reason": "fresh_engine_run is not true"}
    if type(values.get("engine_returncode")) is not int or values["engine_returncode"] != 0:
        return {"passed": False, "reason": "successful engine_returncode missing"}
    txt = values.get("fresh_txtinout_dir") or values.get("txtinout_dir")
    if not txt:
        return {"passed": False, "reason": "txtinout_dir missing for fresh output verification"}
    try:
        root = Path(str(txt)).resolve()
        receipt = read_object(root / "engine_run_receipt.json")
        if (not values.get("engine_run_id") or receipt.get("run_id") != values["engine_run_id"]
                or type(receipt.get("returncode")) is not int or receipt["returncode"] != 0):
            raise ValueError("Engine run identity or completion mismatch")
        if receipt.get("schema_version") != "2.0":
            raise ValueError("Unsupported or legacy engine execution receipt")
        expected_input_sha = receipt.get("input_configuration_sha256")
        expected_input_count = receipt.get("input_configuration_file_count")
        actual_input_sha, actual_input_count = input_configuration_fingerprint(root)
        if actual_input_sha != expected_input_sha or actual_input_count != expected_input_count:
            raise ValueError("Engine inputs differ from the configuration sealed at execution")
        engine = receipt.get("engine")
        if not isinstance(engine, dict):
            raise ValueError("Engine identity missing from execution receipt")
        engine_path = engine.get("path")
        if not isinstance(engine_path, str) or not Path(engine_path).is_absolute():
            raise ValueError("Engine path missing from execution receipt")
        engine_sha = engine.get("sha256")
        if not isinstance(engine_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", engine_sha):
            raise ValueError("Engine digest missing from execution receipt")
        executable = Path(engine_path)
        if executable.is_file():
            verify_digest(executable, engine_sha)
        execution = receipt.get("execution")
        if (
            not isinstance(execution, dict)
            or type(execution.get("threads")) is not int
            or execution["threads"] < 1
            or type(execution.get("timeout_enforced")) is not bool
            or (
                execution["timeout_enforced"]
                and (
                    not isinstance(execution.get("timeout_s"), (int, float))
                    or isinstance(execution.get("timeout_s"), bool)
                    or not math.isfinite(float(execution["timeout_s"]))
                    or float(execution["timeout_s"]) <= 0
                )
            )
            or (not execution["timeout_enforced"] and execution.get("timeout_s") is not None)
        ):
            raise ValueError("Execution settings missing from engine receipt")
        files = receipt.get("files", {})
        verify_digest(root / "simulation.out", files.get("simulation.out"))
        if "Execution successfully completed" not in (root / "simulation.out").read_text():
            raise ValueError("Engine completion marker missing")
        source = values.get("sim_source_file")
        names = [str(source)] if source else ["basin_sd_cha_day.txt", "channel_sd_day.txt", "channel_day.txt"]
        for name in names:
            path = root / name
            if not path.resolve().is_relative_to(root):
                raise ValueError("Simulation source escapes execution directory")
            if name in files:
                if not path.is_file():
                    raise ValueError("fresh simulation output artifact missing")
                verify_digest(path, files[name])
                if path.stat().st_size > 0:
                    return {"passed": True, "reason": "simulation output matches verified engine run"}
        raise ValueError("Fresh simulation output artifact missing from execution receipt")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {"passed": False, "reason": str(exc)}


def benchmark_lock_gate(values: dict[str, Any]) -> dict[str, Any]:
    path = values.get("benchmark_lock_path")
    if not path:
        return {"passed": False, "reason": "benchmark_lock_path missing"}
    if not Path(str(path)).is_file():
        return {"passed": False, "reason": "benchmark lock artifact missing"}
    try:
        lock = verify_benchmark_artifacts(Path(str(path)))
        if values.get("txtinout_dir"):
            actual, _ = input_configuration_fingerprint(str(values["txtinout_dir"]))
            if actual != lock["input_configuration_sha256"]:
                raise ValueError("Benchmark input configuration has changed")
        selected = values.get("selected_outlet_gis_id", values.get("outlet_gis_id"))
        if selected is not None and selected != lock["outlet_gis_id"]:
            raise ValueError("Benchmark outlet differs from workflow outlet")
        return {"passed": True, "reason": "benchmark artifact hashes and outlet verified"}
    except (OSError, ValueError, TypeError) as exc:
        return {"passed": False, "reason": str(exc)}


def outlet_provenance_gate(values: dict[str, Any]) -> dict[str, Any]:
    selected = values.get("selected_outlet_gis_id") or values.get("outlet_gis_id")
    if selected is None:
        return {"passed": False, "reason": "selected outlet GIS id missing from workflow evidence"}
    try:
        path = Path(str(values.get("outlet_provenance_path") or ""))
        verify_digest(path, values.get("outlet_provenance_sha256"))
        provenance = read_object(path)
        if type(selected) is not int or selected <= 0 or provenance.get("selected_outlet_gis_id") != selected:
            raise ValueError("Selected outlet differs from provenance")
        if not values.get("workflow_run_id") or provenance.get("run_id") != values["workflow_run_id"]:
            raise ValueError("Outlet provenance run identity mismatch")
        return {"passed": True, "reason": f"selected_outlet_gis_id={selected}; run identity and hash verified"}
    except (OSError, ValueError, TypeError) as exc:
        return {"passed": False, "reason": str(exc)}


def research_metric_gate(values: dict[str, Any]) -> dict[str, Any]:
    metrics = values.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    nse = _as_float(metrics.get("nse", values.get("baseline_nse")))
    kge = _as_float(metrics.get("kge", values.get("baseline_kge")))
    pbias = _as_float(metrics.get("pbias", metrics.get("pbias_pct")))

    failures: list[str] = []
    if kge is None or kge < 0.40:
        failures.append(f"KGE {kge if kge is not None else 'missing'} < 0.40")
    if kge is not None and kge > 1.0:
        failures.append("KGE exceeds 1")
    if nse is None:
        failures.append("NSE missing")
    elif nse > 1.0:
        failures.append("NSE exceeds 1")
    elif nse < 0.0:
        exception = values.get("timing_limitation_exception")
        timing_documented = False
        if isinstance(exception, dict):
            basis = exception.get("basis")
            evidence_path = exception.get("supporting_artifact")
            try:
                if (
                    exception.get("authorized") is True
                    and exception.get("scope") == "negative_nse_with_kge"
                    and isinstance(basis, str)
                    and bool(basis.strip())
                    and evidence_path
                ):
                    verify_digest(
                        Path(str(evidence_path)),
                        exception.get("supporting_artifact_sha256"),
                    )
                    timing_documented = True
            except (OSError, ValueError, TypeError):
                timing_documented = False
        if not (kge is not None and kge >= 0.40 and timing_documented):
            failures.append(f"NSE {nse:.3f} < 0.00 without documented timing limitation")
    if pbias is None:
        failures.append("PBIAS missing")
    elif abs(pbias) > 30.0:
        failures.append(f"|PBIAS| {abs(pbias):.1f}% > 30%")

    return {
        "passed": not failures,
        "reason": "metrics pass research thresholds" if not failures else "; ".join(failures),
    }


def weather_fidelity_gate(values: dict[str, Any]) -> dict[str, Any]:
    flags = values.get("weather_coverage_flags")
    if not isinstance(flags, dict):
        return {"passed": False, "reason": "weather validation provenance missing"}
    if flags.get("calendar_validated") is not True:
        return {"passed": False, "reason": "weather calendar was not explicitly validated"}
    if flags.get("raw_values_validated") is not True:
        return {"passed": False, "reason": "weather raw values were not explicitly validated"}
    count = flags.get("imputation_count")
    if type(count) is not int or count < 0:
        return {"passed": False, "reason": "weather imputation count missing or invalid"}
    if count:
        return {
            "passed": False,
            "reason": f"weather forcing contains {count} declared imputed station-days",
        }
    return {"passed": True, "reason": "weather calendar and raw values validated; no imputation"}


def soil_fidelity_gate(values: dict[str, Any]) -> dict[str, Any]:
    soil_mode = str(values.get("soil_mode") or "")
    provenance = str(values.get("soil_provenance_mode") or "")
    authoritative_provenance = {"gnatsgo_raster"}
    fallback_value = values.get("pct_fallback_soils")
    fallback = _as_float(fallback_value)
    if (
        soil_mode == "high_fidelity"
        and fallback is not None
        and fallback == 0.0
        and provenance in authoritative_provenance
    ):
        reason = "soil_mode=high_fidelity"
        if provenance:
            reason += f"; soil_provenance_mode={provenance}"
        return {"passed": True, "reason": reason}
    fallback_reason = "n/a" if fallback is None else f"{fallback:.2%}"
    return {
        "passed": False,
        "reason": (
            f"soil provenance degraded: soil_mode={soil_mode}, "
            f"soil_provenance_mode={provenance or 'n/a'}, "
            f"pct_fallback_soils={fallback_reason}"
        ),
    }


def landuse_fidelity_gate(values: dict[str, Any]) -> dict[str, Any]:
    block = values.get("landuse_fidelity")
    if not isinstance(block, dict):
        return {"passed": False, "reason": "landuse_fidelity block missing"}

    status = str(block.get("status") or "")
    if status != "evaluated":
        return {"passed": False, "reason": f"landuse_fidelity status={status or 'missing'}"}

    hru_mode = str(block.get("hru_mode") or "")
    retention = _as_float(block.get("landuse_class_retention_fraction"))
    area_retention = _as_float(block.get("landuse_area_retention_fraction"))
    missing_area = _as_float(block.get("landuse_missing_area_fraction"))
    mismatch = _as_float(block.get("landuse_vintage_mismatch_years"))
    mismatch = abs(mismatch) if mismatch is not None else None

    failures: list[str] = []
    for name, number in (("landuse_class_retention_fraction", retention),
                         ("landuse_area_retention_fraction", area_retention),
                         ("landuse_missing_area_fraction", missing_area)):
        if block.get(name) is not None and (number is None or not 0.0 <= number <= 1.0):
            failures.append(f"{name} must be a finite fraction in [0, 1]")
    if hru_mode != "full_overlay":
        failures.append(f"hru_mode={hru_mode or 'missing'}")
    if retention is None:
        failures.append("landuse_class_retention_fraction missing")
    elif retention < 0.999:
        if area_retention is None:
            failures.append(f"landuse_class_retention_fraction={retention:.2f}")
        elif area_retention < 0.995:
            failures.append(
                f"landuse_class_retention_fraction={retention:.2f}; "
                f"landuse_area_retention_fraction={area_retention:.3f}"
            )
    if mismatch is None:
        failures.append("landuse_vintage_mismatch_years missing")
    elif mismatch > 5.0:
        failures.append(f"landuse_vintage_mismatch_years={mismatch:.1f}")

    if failures:
        return {
            "passed": False,
            "reason": "land-use fidelity degraded: " + "; ".join(failures),
        }
    reason_parts = [
        f"hru_mode={hru_mode}",
        f"landuse_class_retention_fraction={retention:.2f}",
    ]
    if missing_area is not None and retention is not None and retention < 0.999:
        reason_parts.append(f"landuse_missing_area_fraction={missing_area:.4f}")
    reason_parts.append(f"landuse_vintage_mismatch_years={mismatch:.1f}")
    return {
        "passed": True,
        "reason": "; ".join(reason_parts),
    }


def calibration_improvement_gate(values: dict[str, Any]) -> dict[str, Any]:
    if values.get("calibration_success") is not True and values.get(
        "calibration_locked_verification_succeeded"
    ) is not True:
        return {"passed": False, "reason": "locked calibration verification did not succeed"}

    provenance = values.get("calibration_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    baseline = values.get("baseline_metrics")
    verified = values.get("calibrated_metrics")
    if not isinstance(baseline, dict) or not isinstance(verified, dict):
        return {"passed": False, "reason": "designated baseline or verification metrics missing"}
    baseline_nse = _as_float(baseline.get("nse"))
    baseline_kge = _as_float(baseline.get("kge"))
    verified_nse = _as_float(verified.get("nse"))
    verified_kge = _as_float(verified.get("kge"))
    if None in (baseline_nse, baseline_kge, verified_nse, verified_kge):
        return {"passed": False, "reason": "designated improvement metrics are missing or non-finite"}
    delta_nse = verified_nse - baseline_nse
    delta_kge = verified_kge - baseline_kge
    nse_improved = delta_nse > 0.0
    kge_improved = delta_kge > 0.0
    computed_basis = (
        "nse_and_kge"
        if nse_improved and kge_improved
        else "nse"
        if nse_improved
        else "kge"
        if kge_improved
        else "none"
    )
    declared_raw = provenance.get("verification_improvement_basis")
    declared_basis = str(declared_raw).strip().lower() if declared_raw is not None else computed_basis
    if declared_basis != computed_basis:
        return {
            "passed": False,
            "reason": (
                f"declared verification_improvement_basis={declared_basis} "
                f"does not match recomputed basis={computed_basis}"
            ),
        }
    reported_delta = values.get("calibration_delta_metrics")
    if isinstance(reported_delta, dict):
        for key, computed in (("nse", delta_nse), ("kge", delta_kge)):
            reported = _as_float(reported_delta.get(key))
            if reported is None or not math.isclose(reported, computed, rel_tol=1e-9, abs_tol=1e-9):
                return {"passed": False, "reason": f"reported delta_{key} contradicts designated metrics"}
    if computed_basis != "none":
        return {
            "passed": True,
            "reason": (
                f"verification_improvement_basis={computed_basis}; "
                f"delta_nse={delta_nse:+.6f}, delta_kge={delta_kge:+.6f}"
            ),
        }

    return {
        "passed": False,
        "reason": "locked calibration did not record positive NSE or KGE improvement over baseline",
    }


def sensitivity_gate(
    values: dict[str, Any],
    *,
    required_params: frozenset[str],
    dead_params: frozenset[str],
) -> dict[str, Any]:
    """Check that a basin-specific sensitivity screen covers the governed parameter set.

    Args:
        values: evidence payload dict.
        required_params: parameter names that must appear in the screen
            (i.e. core governed params that are not classified as dead).
        dead_params: core governed params classified as dead — must be
            accounted for either as 'dead' in the screen or in blocked_parameters.
    """
    basis = str(values.get("sensitivity_screen_basis") or "")
    if basis != "basin_specific":
        return {
            "passed": False,
            "reason": f"sensitivity_screen_basis={basis or 'missing'}; basin_specific required for research_grade",
        }

    classes = values.get("sensitivity_screen_activity_classes")
    if not isinstance(classes, dict) or not classes:
        return {"passed": False, "reason": "sensitivity_screen_activity_classes missing"}

    normalized_classes = {str(name).upper(): str(activity) for name, activity in classes.items()}
    missing_core = sorted(required_params - set(normalized_classes))
    if missing_core:
        return {
            "passed": False,
            "reason": (
                "basin-specific sensitivity screen missing current governed core parameters: "
                + ", ".join(missing_core)
            ),
        }

    blocked_parameters: set[str] = set()
    for key in ("blocked_parameters", "calibration_blocked_parameters"):
        value = values.get(key)
        if isinstance(value, list):
            blocked_parameters.update(str(item).upper() for item in value)
    provenance = values.get("calibration_provenance")
    if isinstance(provenance, dict) and isinstance(provenance.get("blocked_parameters"), list):
        blocked_parameters.update(str(item).upper() for item in provenance["blocked_parameters"])
    unaccounted_dead = sorted(
        name
        for name in dead_params
        if normalized_classes.get(name) != "dead" and name not in blocked_parameters
    )
    if unaccounted_dead:
        return {
            "passed": False,
            "reason": (
                "dead or unsupported governed core parameters lack blocked/dead accounting: "
                + ", ".join(unaccounted_dead)
            ),
        }

    active_or_weak = {
        name
        for name, activity in normalized_classes.items()
        if str(activity) in {"active", "weak", "limited"}
    }
    if not active_or_weak:
        return {"passed": False, "reason": "no basin-sensitive calibration parameters found"}
    return {
        "passed": True,
        "reason": (
            "basin-specific sensitivity evidence covers current governed core set "
            f"and retained {len(active_or_weak)} active/weak/limited parameters"
        ),
    }
