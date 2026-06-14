"""Gate functions for claim governance — zero hydrology imports.

Each gate takes a ``values`` dict (the evidence payload) and returns
``{"passed": bool, "reason": str}``.  The sensitivity gate additionally
requires the caller to supply the set of governed parameters (so this module
remains domain-agnostic).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if value is not None:
            return float(value)
    except Exception:
        return None
    return None


def fresh_engine_gate(values: dict[str, Any]) -> dict[str, Any]:
    if values.get("fresh_engine_run") is not True:
        return {"passed": False, "reason": "fresh_engine_run is not true"}
    rc = values.get("engine_returncode")
    if rc is not None:
        try:
            if int(rc) != 0:
                return {"passed": False, "reason": f"engine_returncode={rc}"}
        except Exception:
            return {"passed": False, "reason": f"engine_returncode is not numeric: {rc}"}
    txt = values.get("txtinout_dir")
    if not txt or not Path(str(txt)).is_dir():
        return {"passed": False, "reason": "txtinout_dir missing for fresh output verification"}
    txt_path = Path(str(txt))
    sim_source = values.get("sim_source_file")
    candidates: list[Path]
    if sim_source:
        source_path = Path(str(sim_source))
        candidates = [source_path if source_path.is_absolute() else txt_path / source_path]
    else:
        candidates = [
            txt_path / "basin_sd_cha_day.txt",
            txt_path / "channel_sd_day.txt",
            txt_path / "channel_day.txt",
        ]
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return {"passed": True, "reason": f"fresh simulation output artifact exists: {candidate}"}
    return {"passed": False, "reason": "fresh simulation output artifact missing"}


def benchmark_lock_gate(values: dict[str, Any]) -> dict[str, Any]:
    path = values.get("benchmark_lock_path")
    if not path:
        return {"passed": False, "reason": "benchmark_lock_path missing"}
    lock = Path(str(path))
    if not lock.is_file():
        return {"passed": False, "reason": f"benchmark lock artifact missing: {lock}"}
    return {"passed": True, "reason": f"benchmark lock artifact exists: {lock}"}


def outlet_provenance_gate(values: dict[str, Any]) -> dict[str, Any]:
    path = values.get("outlet_provenance_path")
    if not path or not Path(str(path)).is_file():
        return {"passed": False, "reason": "outlet_provenance.json missing"}
    selected = values.get("selected_outlet_gis_id") or values.get("outlet_gis_id")
    if selected is None:
        return {"passed": False, "reason": "selected outlet GIS id missing from workflow evidence"}
    return {"passed": True, "reason": f"selected_outlet_gis_id={selected}"}


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
    if nse is None:
        failures.append("NSE missing")
    elif nse < 0.0:
        timing_documented = bool(values.get("timing_limitation_documented")) or bool(
            values.get("timing_limitation_basis")
        )
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


def soil_fidelity_gate(values: dict[str, Any]) -> dict[str, Any]:
    soil_mode = str(values.get("soil_mode") or "")
    provenance = str(values.get("soil_provenance_mode") or "")
    authoritative_provenance = {"gnatsgo_raster"}
    fallback_value = values.get("pct_fallback_soils")
    try:
        fallback = float(fallback_value)
    except (TypeError, ValueError):
        fallback = None
    if (
        soil_mode == "high_fidelity"
        and fallback is not None
        and fallback <= 0.0
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


def calibration_improvement_gate(values: dict[str, Any]) -> dict[str, Any]:
    if values.get("calibration_success") is not True and values.get(
        "calibration_locked_verification_succeeded"
    ) is not True:
        return {"passed": False, "reason": "locked calibration verification did not succeed"}

    provenance = values.get("calibration_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    basis = str(provenance.get("verification_improvement_basis") or "").strip().lower()
    if basis and basis != "none":
        return {"passed": True, "reason": f"verification_improvement_basis={basis}"}

    delta = values.get("calibration_delta_metrics")
    if not isinstance(delta, dict):
        delta = {}
    delta_nse = _as_float(delta.get("nse"))
    delta_kge = _as_float(delta.get("kge"))
    improved = any(v is not None and v > 0.0 for v in (delta_nse, delta_kge))
    if improved:
        parts = []
        if delta_nse is not None:
            parts.append(f"delta_nse={delta_nse:+.6f}")
        if delta_kge is not None:
            parts.append(f"delta_kge={delta_kge:+.6f}")
        return {"passed": True, "reason": ", ".join(parts)}

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
