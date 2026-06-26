"""Auditable post-build subsurface prior correction for full-mode runs.

The SWAT+ Editor hydrology defaults are kept as the source prior.  This module
only applies a package-owned correction after a fresh engine run proves a large
water-yield deficit against observed runoff depth.  Every changed value is
recorded in a JSON sidecar before the workflow reruns the engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .water_balance_gate import _parse_basin_wb_aa

SECONDS_PER_DAY = 86_400.0

PROFILE_NAME = "humid_runoff_deficit_prior_v1"
TARGET_TOLERANCE = 0.15
MIN_OBSERVED_QP = 0.25
MAX_OBSERVED_QP = 0.75
MAX_ET_TO_PRECIP_FOR_PRIOR = 0.70
MIN_PERC_TO_PRECIP_FOR_PRIOR = 0.15

HYDROLOGY_PROFILE = {
    "perco": 0.75,
    "cn3_swf": 0.85,
    "latq_co": 0.08,
}

AQUIFER_PROFILE = {
    "alpha_bf": 0.08,
    "rchg_dp": 0.04,
    "flo_min": 2.0,
}


def apply_subsurface_prior_correction(
    run_dir: Path | str,
    txtinout_dir: Path | str,
    *,
    obs_series: pd.Series | None,
) -> dict[str, Any]:
    """Apply a conservative runoff-deficit prior correction if evidence requires it.

    The returned payload is also written to
    ``reports/subsurface_prior_correction.json``.  A status of ``applied`` means
    the caller must rerun the SWAT+ engine before scoring or locking the run.
    """

    run = Path(run_dir)
    txt = Path(txtinout_dir)
    report_path = run / "reports" / "subsurface_prior_correction.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    wb = _parse_basin_wb_aa(txt)
    payload: dict[str, Any] = {
        "status": "not_applied",
        "profile": PROFILE_NAME,
        "report_path": str(report_path),
        "source": "post_build_water_balance_reality_check",
        "water_balance_before": _water_balance_summary(wb),
        "target": {
            "basis": "observed_usgs_runoff_depth_over_delineated_area",
            "tolerance": TARGET_TOLERANCE,
            "min_observed_qp": MIN_OBSERVED_QP,
            "max_observed_qp": MAX_OBSERVED_QP,
            "max_et_to_precip_for_prior": MAX_ET_TO_PRECIP_FOR_PRIOR,
            "min_perc_to_precip_for_prior": MIN_PERC_TO_PRECIP_FOR_PRIOR,
        },
        "guardrails": [
            "no_gate_weakening",
            "editor_defaults_retained_as_prior",
            "changed_values_recorded_before_rerun",
            "fresh_engine_rerun_required_before_claims",
        ],
    }

    precip = _as_float(wb.get("precip"))
    wateryld = _as_float(wb.get("wateryld"))
    if precip is None or precip <= 0 or wateryld is None:
        payload["reason"] = "basin_wb_aa_missing_precip_or_wateryld"
        return _write_report(report_path, payload)

    observed = _observed_runoff_context(run, obs_series, precip)
    payload["observed_runoff"] = observed
    observed_qp = _as_float(observed.get("observed_runoff_to_precip"))
    modeled_qp = wateryld / precip
    et = _as_float(wb.get("et"))
    perc = _as_float(wb.get("perc"))
    et_qp = et / precip if et is not None else None
    perc_qp = perc / precip if perc is not None else None
    payload["modeled_wateryld_to_precip_before"] = modeled_qp
    profile_state = _current_profile_state(txt)
    payload["current_profile_state"] = profile_state

    if observed_qp is None:
        payload["reason"] = observed.get("reason", "observed_runoff_context_missing")
        return _write_report(report_path, payload)
    if not (MIN_OBSERVED_QP <= observed_qp <= MAX_OBSERVED_QP):
        payload["reason"] = f"observed_qp_outside_correction_guardrail={observed_qp:.3f}"
        return _write_report(report_path, payload)
    if modeled_qp + TARGET_TOLERANCE >= observed_qp:
        if profile_state.get("matches_profile"):
            payload["status"] = "already_applied"
            payload["reason"] = (
                f"{PROFILE_NAME} already present; modeled_wateryld_to_precip={modeled_qp:.3f} "
                f"within {TARGET_TOLERANCE:.2f} of observed_qp={observed_qp:.3f}"
            )
            payload["fresh_engine_rerun_required"] = False
            return _write_report(report_path, payload)
        payload["reason"] = (
            f"modeled_wateryld_to_precip={modeled_qp:.3f} within "
            f"{TARGET_TOLERANCE:.2f} of observed_qp={observed_qp:.3f}"
        )
        return _write_report(report_path, payload)
    if et_qp is not None and et_qp > MAX_ET_TO_PRECIP_FOR_PRIOR:
        payload["reason"] = (
            f"et_to_precip={et_qp:.3f} exceeds {MAX_ET_TO_PRECIP_FOR_PRIOR:.2f}; "
            "run ET/PET partition diagnostics before subsurface prior correction"
        )
        return _write_report(report_path, payload)
    if perc_qp is None or perc_qp < MIN_PERC_TO_PRECIP_FOR_PRIOR:
        perc_text = "missing" if perc_qp is None else f"{perc_qp:.3f}"
        payload["reason"] = (
            f"perc_to_precip={perc_text} below {MIN_PERC_TO_PRECIP_FOR_PRIOR:.2f}; "
            "subsurface prior correction requires evidence of excessive deep/percolation partition"
        )
        return _write_report(report_path, payload)

    hyd_changes = _rewrite_table_columns(txt / "hydrology.hyd", HYDROLOGY_PROFILE)
    aqu_changes = _rewrite_table_columns(txt / "aquifer.aqu", AQUIFER_PROFILE)
    payload.update(
        {
            "status": "applied",
            "reason": (
                f"modeled_wateryld_to_precip={modeled_qp:.3f} below "
                f"observed_qp={observed_qp:.3f} by more than {TARGET_TOLERANCE:.2f}"
            ),
            "fresh_engine_rerun_required": True,
            "parameter_changes": hyd_changes + aqu_changes,
        }
    )
    return _write_report(report_path, payload)


def finalize_subsurface_prior_correction(
    run_dir: Path | str,
    txtinout_dir: Path | str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Add post-rerun water-balance evidence to a correction payload."""

    run = Path(run_dir)
    txt = Path(txtinout_dir)
    report_path = Path(str(payload.get("report_path") or run / "reports" / "subsurface_prior_correction.json"))
    wb_after = _parse_basin_wb_aa(txt)
    payload = dict(payload)
    payload["water_balance_after"] = _water_balance_summary(wb_after)
    before = _as_float(payload.get("modeled_wateryld_to_precip_before"))
    after = _as_float(payload["water_balance_after"].get("wateryld_to_precip"))
    observed = payload.get("observed_runoff") if isinstance(payload.get("observed_runoff"), dict) else {}
    target = _as_float(observed.get("observed_runoff_to_precip")) if isinstance(observed, dict) else None
    if before is not None and after is not None and target is not None:
        payload["improvement"] = {
            "before_abs_error": abs(before - target),
            "after_abs_error": abs(after - target),
            "improved_toward_observed_qp": abs(after - target) < abs(before - target),
        }
        payload["status"] = (
            "applied_improved"
            if payload["improvement"]["improved_toward_observed_qp"]
            else "applied_not_improved"
        )
    return _write_report(report_path, payload)


def _observed_runoff_context(
    run_dir: Path,
    obs_series: pd.Series | None,
    precip_mm: float,
) -> dict[str, Any]:
    area = _delineated_area_km2(run_dir)
    if area is None:
        return {"available": False, "reason": "delineated_area_km2_missing"}
    if obs_series is None or obs_series.empty:
        return {"available": False, "reason": "observed_series_missing", "area_km2": area}
    obs = pd.to_numeric(obs_series, errors="coerce").dropna()
    if obs.empty:
        return {"available": False, "reason": "observed_series_empty", "area_km2": area}
    total_m3 = float(obs.sum()) * SECONDS_PER_DAY
    depth_mm_total = total_m3 / (float(area) * 1_000_000.0) * 1000.0
    years = max(float(len(obs)) / 365.25, 1e-9)
    annual_depth = depth_mm_total / years
    return {
        "available": True,
        "area_km2": area,
        "n_days": int(len(obs)),
        "observed_runoff_depth_mm": annual_depth,
        "observed_runoff_to_precip": annual_depth / precip_mm if precip_mm > 0 else None,
    }


def _delineated_area_km2(run_dir: Path) -> float | None:
    path = run_dir / "delin" / "validation_result.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _as_float(data.get("delineated_area_km2"))


def _water_balance_summary(wb: dict[str, float]) -> dict[str, float | None]:
    precip = _as_float(wb.get("precip"))

    def ratio(key: str) -> float | None:
        value = _as_float(wb.get(key))
        return value / precip if precip and value is not None else None

    return {
        "precip_mm": precip,
        "et_mm": _as_float(wb.get("et")),
        "surq_gen_mm": _as_float(wb.get("surq_gen", wb.get("surq"))),
        "latq_mm": _as_float(wb.get("latq")),
        "perc_mm": _as_float(wb.get("perc")),
        "wateryld_mm": _as_float(wb.get("wateryld")),
        "et_to_precip": ratio("et"),
        "surq_to_precip": ratio("surq_gen"),
        "latq_to_precip": ratio("latq"),
        "perc_to_precip": ratio("perc"),
        "wateryld_to_precip": ratio("wateryld"),
    }


def _rewrite_table_columns(path: Path, targets: dict[str, float]) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        raise ValueError(f"{path.name} is too short to patch")
    header = lines[1].split()
    index = {name: i for i, name in enumerate(header)}
    missing = sorted(set(targets) - set(index))
    if missing:
        raise ValueError(f"{path.name} missing columns: {', '.join(missing)}")

    changes: list[dict[str, Any]] = []
    out = lines[:2]
    for row_number, line in enumerate(lines[2:], start=3):
        if not line.strip():
            out.append(line)
            continue
        parts = line.split()
        row_name = parts[0] if parts else f"row_{row_number}"
        for column, new_value in targets.items():
            col_idx = index[column]
            if col_idx >= len(parts):
                raise ValueError(f"{path.name} row {row_number} missing {column}")
            old_value = _as_float(parts[col_idx])
            parts[col_idx] = f"{float(new_value):.5f}"
            changes.append(
                {
                    "file": path.name,
                    "row": row_name,
                    "column": column,
                    "old_value": old_value,
                    "new_value": float(new_value),
                }
            )
        out.append(" ".join(parts))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changes


def _current_profile_state(txt: Path) -> dict[str, Any]:
    hyd = _table_columns_match(txt / "hydrology.hyd", HYDROLOGY_PROFILE)
    aqu = _table_columns_match(txt / "aquifer.aqu", AQUIFER_PROFILE)
    return {
        "profile": PROFILE_NAME,
        "hydrology_matches": hyd.get("matches"),
        "aquifer_matches": aqu.get("matches"),
        "matches_profile": bool(hyd.get("matches") and aqu.get("matches")),
        "hydrology_mismatch_count": hyd.get("mismatch_count"),
        "aquifer_mismatch_count": aqu.get("mismatch_count"),
    }


def _table_columns_match(path: Path, targets: dict[str, float]) -> dict[str, Any]:
    if not path.is_file():
        return {"matches": False, "reason": "file_missing", "mismatch_count": None}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        return {"matches": False, "reason": "file_too_short", "mismatch_count": None}
    header = lines[1].split()
    index = {name: i for i, name in enumerate(header)}
    missing = sorted(set(targets) - set(index))
    if missing:
        return {
            "matches": False,
            "reason": f"missing_columns={','.join(missing)}",
            "mismatch_count": None,
        }
    mismatch_count = 0
    row_count = 0
    for line in lines[2:]:
        if not line.strip():
            continue
        row_count += 1
        parts = line.split()
        for column, expected in targets.items():
            col_idx = index[column]
            if col_idx >= len(parts):
                mismatch_count += 1
                continue
            actual = _as_float(parts[col_idx])
            if actual is None or abs(actual - float(expected)) > 1e-6:
                mismatch_count += 1
    return {
        "matches": mismatch_count == 0 and row_count > 0,
        "mismatch_count": mismatch_count,
        "row_count": row_count,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if value is not None:
            return float(value)
    except Exception:
        return None
    return None
