"""Scoped numeric criteria, independent of workflow verification tiers.

Moriasi et al. (2015), doi:10.13031/trans.58.10715, watershed flow criteria.
These three numbers do not replace graphical/contextual performance assessment.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

REFERENCE_URL = "https://www.ars.usda.gov/research/publications/publication/?seqNo115=304597"


def _alignment_date(value: Any) -> date:
    """Accept an ISO date or midnight timestamp without discarding time."""
    text = str(value)
    if len(text) == 10:
        return date.fromisoformat(text)
    if len(text) < 19 or text[10] not in {"T", " "}:
        raise ValueError("Alignment date must be an ISO date or midnight timestamp.")
    timestamp = datetime.fromisoformat(text)
    if any((timestamp.hour, timestamp.minute, timestamp.second, timestamp.microsecond)):
        raise ValueError("Within-day timestamps do not establish daily alignment.")
    return timestamp.date()


def assess_streamflow_performance(
    metrics: Mapping[str, Any], *, timestep: str | None = None,
    period_start: str | None = None, period_end: str | None = None,
    evaluation_role: str | None = None, spatial_scale: str = "watershed",
) -> dict[str, Any]:
    """Evaluate complete, scoped metrics; never infer or change a claim tier.

    R² must be squared Pearson correlation from paired discharge values.
    The period and role must be supplied explicitly, including for calibration.
    """
    reasons: list[str] = []
    values: dict[str, float | None] = {}
    for key in ("r2", "nse", "pbias"):
        raw = metrics.get(key)
        try:
            value = float(raw) if raw is not None and not isinstance(raw, bool) else math.nan
        except (TypeError, ValueError, OverflowError):
            value = math.nan
        values[key] = value if math.isfinite(value) else None
        if values[key] is None:
            reasons.append(f"missing_or_nonfinite_{key}")
    if values["r2"] is not None and not 0 <= values["r2"] <= 1:
        reasons.append("invalid_r2_range")
    if values["nse"] is not None and values["nse"] > 1:
        reasons.append("invalid_nse_range")
    if timestep not in {"daily", "monthly", "annual"}:
        reasons.append("missing_or_unsupported_timestep")
    if spatial_scale != "watershed":
        reasons.append("unsupported_spatial_scale")
    if not isinstance(evaluation_role, str) or not evaluation_role.strip():
        reasons.append("missing_evaluation_role")
    try:
        start = date.fromisoformat(period_start or "")
        end = date.fromisoformat(period_end or "")
        if start > end:
            reasons.append("reversed_evaluation_period")
    except (TypeError, ValueError):
        reasons.append("missing_or_invalid_evaluation_period")
    checks = {
        "r2_gt_0_60": None if values["r2"] is None else values["r2"] > 0.60,
        "nse_gt_0_50": None if values["nse"] is None else values["nse"] > 0.50,
        "abs_pbias_le_15": None if values["pbias"] is None else abs(values["pbias"]) <= 15,
    }
    return {
        "schema_version": "moriasi_2015_streamflow_numeric_v1",
        "status": "not_evaluated" if reasons else ("met" if all(checks.values()) else "not_met"),
        "reference": {"doi": "10.13031/trans.58.10715", "url": REFERENCE_URL},
        "variable": "streamflow", "spatial_scale": spatial_scale,
        "timestep": timestep, "period_start": period_start, "period_end": period_end,
        "evaluation_role": evaluation_role,
        "metrics": values, "criteria": checks, "reasons": reasons,
        "r2_definition": "squared Pearson correlation of paired observed and simulated discharge",
        "assessment_scope": "numeric criteria only; graphical and contextual assessment still required",
    }


def assess_streamflow_series(
    obs: Sequence[float], sim: Sequence[float], *,
    dates: Sequence[str] | None = None, **scope: Any,
) -> dict[str, Any]:
    """Compute criteria from supplied pairs, without clipping or dropping values.

    Dates, when supplied, must match the explicit period, be unique, ordered,
    and align with every pair. Dates alone never establish an evaluation role.
    """
    reasons: list[str] = []
    metrics: dict[str, float] = {}
    try:
        observed, simulated = [float(v) for v in obs], [float(v) for v in sim]
        if len(observed) != len(simulated) or len(observed) < 2:
            reasons.append("insufficient_or_mismatched_pairs")
        elif any(not math.isfinite(v) or v < 0 for v in observed + simulated):
            reasons.append("invalid_discharge_pairs")
        else:
            mean_o = math.fsum(observed) / len(observed)
            mean_s = math.fsum(simulated) / len(simulated)
            var_o = math.fsum((v - mean_o) ** 2 for v in observed)
            var_s = math.fsum((v - mean_s) ** 2 for v in simulated)
            if var_o == 0 or var_s == 0 or mean_o == 0:
                reasons.append("undefined_streamflow_metrics")
            else:
                covariance = math.fsum((o - mean_o) * (s - mean_s) for o, s in zip(observed, simulated))
                metrics = {
                    "r2": min(1.0, covariance ** 2 / var_o / var_s),
                    "nse": 1 - math.fsum((o - s) ** 2 for o, s in zip(observed, simulated)) / var_o,
                    "pbias": 100 * math.fsum(s - o for o, s in zip(observed, simulated)) / math.fsum(observed),
                }
    except (TypeError, ValueError, OverflowError):
        observed = []
        reasons.append("invalid_discharge_pairs")
    if dates is not None:
        try:
            parsed = [_alignment_date(v) for v in dates]
            if (len(parsed) != len(observed) or not parsed or len(set(parsed)) != len(parsed)
                    or parsed != sorted(parsed)
                    or parsed[0].isoformat() != scope.get("period_start")
                    or parsed[-1].isoformat() != scope.get("period_end")):
                reasons.append("date_alignment_or_period_mismatch")
        except (TypeError, ValueError):
            reasons.append("invalid_alignment_dates")
    result = assess_streamflow_performance(metrics, **scope)
    result["n_pairs"] = len(observed)
    if reasons:
        result["status"] = "not_evaluated"
        result["reasons"] = reasons + result["reasons"]
    return result
