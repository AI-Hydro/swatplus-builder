"""Flood-frequency distribution-fitting domain — governance generality demonstration.

This module is a second-domain toy that consumes ``swatplus_builder.governance``
without importing anything from ``swatplus_builder.workflows``.  It proves the
governance core is domain-agnostic: the same tier ladder, gate protocol, and
evidence-bundle contract work for a flood-frequency analysis task.

Gates operate on a *pre-computed* evidence payload dict (caller supplies L-moment
ratios, trend statistics, CI bounds, etc.; this layer only classifies them):

    values = {
        "station_id": "08158000",
        "n_years": 65,
        "trend_p_value": 0.12,
        "trend_slope_pct_per_decade": 2.1,
        "best_fit_distribution": "GEV",
        "distribution_fit_rmse": 0.031,
        "t100_estimate_m3s": 1240.0,
        "t100_ci_half_width_m3s": 210.0,
        "fitting_locked": True,
    }

    result = run_flood_frequency(values, claim_tier="research_grade")
    # result["effective_claim_tier"] → "research_grade" | "publication_grade" | ...

Tier mapping:
    exploratory      — data_adequacy gate passes (n_years ≥ MIN_RECORD_YEARS)
    diagnostic       — + stationarity gate passes (no significant trend)
    publication_grade — + distribution_fit gate passes (L-RMSE within threshold)
    research_grade   — + return_period gate passes (CI bounds narrow enough)
"""
from __future__ import annotations

from typing import Any

from swatplus_builder.governance.tiers import CLAIM_TIERS, tier_rank

# ---------------------------------------------------------------------------
# Thresholds (locked — do not adjust without a DECISIONS.md entry)
# ---------------------------------------------------------------------------

MIN_RECORD_YEARS: int = 20
STATIONARITY_P_THRESHOLD: float = 0.05
MAX_FIT_RMSE: float = 0.050
MAX_CI_RELATIVE_HALF_WIDTH: float = 0.50


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if value is not None:
            return float(value)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Gate functions (domain-specific; return {"passed": bool, "reason": str})
# ---------------------------------------------------------------------------

def data_adequacy_gate(values: dict[str, Any]) -> dict[str, Any]:
    """At least MIN_RECORD_YEARS of annual-maxima data required for L-moments."""
    n = _as_float(values.get("n_years"))
    if n is None:
        return {"passed": False, "reason": "n_years missing from evidence payload"}
    if n < MIN_RECORD_YEARS:
        return {
            "passed": False,
            "reason": (
                f"record length n_years={int(n)} < {MIN_RECORD_YEARS} "
                "required for reliable L-moment estimation"
            ),
        }
    return {"passed": True, "reason": f"record length n_years={int(n)} ≥ {MIN_RECORD_YEARS}"}


def stationarity_gate(values: dict[str, Any]) -> dict[str, Any]:
    """Mann-Kendall trend test must be non-significant at α = 0.05."""
    p = _as_float(values.get("trend_p_value"))
    if p is None:
        return {"passed": False, "reason": "trend_p_value missing; Mann-Kendall test result required"}
    if p < STATIONARITY_P_THRESHOLD:
        slope = _as_float(values.get("trend_slope_pct_per_decade"))
        slope_str = f" (slope {slope:+.1f} %/decade)" if slope is not None else ""
        return {
            "passed": False,
            "reason": (
                f"significant non-stationarity detected: Mann-Kendall p={p:.4f} < {STATIONARITY_P_THRESHOLD}"
                + slope_str
            ),
        }
    return {
        "passed": True,
        "reason": f"Mann-Kendall p={p:.4f} ≥ {STATIONARITY_P_THRESHOLD}; no significant trend",
    }


def distribution_fit_gate(values: dict[str, Any]) -> dict[str, Any]:
    """L-moment-diagram RMSE must be within MAX_FIT_RMSE."""
    dist = str(values.get("best_fit_distribution") or "").strip()
    if not dist:
        return {"passed": False, "reason": "best_fit_distribution missing from evidence payload"}
    rmse = _as_float(values.get("distribution_fit_rmse"))
    if rmse is None:
        return {"passed": False, "reason": "distribution_fit_rmse missing; L-moment diagram fit required"}
    if rmse > MAX_FIT_RMSE:
        return {
            "passed": False,
            "reason": (
                f"distribution fit RMSE={rmse:.4f} > {MAX_FIT_RMSE} "
                f"(best fit: {dist}); consider alternative distribution families"
            ),
        }
    return {
        "passed": True,
        "reason": f"distribution_fit_rmse={rmse:.4f} ≤ {MAX_FIT_RMSE}; best_fit_distribution={dist}",
    }


def return_period_gate(values: dict[str, Any]) -> dict[str, Any]:
    """100-year return period CI half-width must be ≤ MAX_CI_RELATIVE_HALF_WIDTH × estimate."""
    estimate = _as_float(values.get("t100_estimate_m3s"))
    half_width = _as_float(values.get("t100_ci_half_width_m3s"))
    if estimate is None:
        return {"passed": False, "reason": "t100_estimate_m3s missing; 100-yr return period required"}
    if half_width is None:
        return {"passed": False, "reason": "t100_ci_half_width_m3s missing; CI bounds required"}
    if estimate <= 0.0:
        return {"passed": False, "reason": f"t100_estimate_m3s={estimate} must be positive"}
    relative = half_width / estimate
    if relative > MAX_CI_RELATIVE_HALF_WIDTH:
        return {
            "passed": False,
            "reason": (
                f"100-yr CI relative half-width {relative:.2f} > {MAX_CI_RELATIVE_HALF_WIDTH}; "
                f"estimate={estimate:.1f} m³/s, half_width={half_width:.1f} m³/s"
            ),
        }
    if not values.get("fitting_locked"):
        return {
            "passed": False,
            "reason": "fitting_locked is not True; parameters must be frozen before CI computation",
        }
    return {
        "passed": True,
        "reason": (
            f"100-yr estimate={estimate:.1f} m³/s, CI half-width={half_width:.1f} m³/s "
            f"(relative={relative:.2f} ≤ {MAX_CI_RELATIVE_HALF_WIDTH})"
        ),
    }


# ---------------------------------------------------------------------------
# Tier logic
# ---------------------------------------------------------------------------

_GATE_ORDER: list[tuple[str, Any]] = [
    ("data_adequacy", data_adequacy_gate),
    ("stationarity", stationarity_gate),
    ("distribution_fit", distribution_fit_gate),
    ("return_period", return_period_gate),
]

_TIER_SEQUENCE: list[tuple[str, str]] = [
    ("data_adequacy", "exploratory"),
    ("stationarity", "diagnostic"),
    ("distribution_fit", "publication_grade"),
    ("return_period", "research_grade"),
]


def _effective_tier(values: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return (effective_tier, gate_results_by_name)."""
    gate_results: dict[str, dict[str, Any]] = {
        name: fn(values) for name, fn in _GATE_ORDER
    }
    tier = "blocked"
    for gate_name, candidate_tier in _TIER_SEQUENCE:
        if gate_results[gate_name]["passed"]:
            tier = candidate_tier
        else:
            break
    return tier, gate_results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_flood_frequency(
    values: dict[str, Any],
    *,
    claim_tier: str = "research_grade",
) -> dict[str, Any]:
    """Evaluate a pre-computed flood-frequency evidence payload and return a claim bundle.

    Args:
        values: Pre-computed evidence dict (see module docstring for schema).
        claim_tier: The tier the caller is asserting (used to classify blockers).

    Returns:
        Evidence bundle dict with keys:
            station_id, effective_claim_tier, claimed_tier, gates_passed,
            gates_failed, blocked_claims, allowed_claims, gate_details.
    """
    if claim_tier not in CLAIM_TIERS:
        raise ValueError(f"claim_tier must be one of {CLAIM_TIERS}; got {claim_tier!r}")

    effective, gate_results = _effective_tier(values)
    claimed_rank = tier_rank(claim_tier)
    effective_rank = tier_rank(effective)

    gates_passed = [name for name, res in gate_results.items() if res["passed"]]
    gates_failed = [name for name, res in gate_results.items() if not res["passed"]]

    blocked_claims: list[dict[str, Any]] = []
    allowed_claims: list[dict[str, Any]] = []

    gate_to_claims = {
        "data_adequacy": [
            ("adequate_record_length", "readiness"),
        ],
        "stationarity": [
            ("flood_series_stationary", "provenance"),
        ],
        "distribution_fit": [
            ("distribution_adequately_fits_data", "comparison"),
        ],
        "return_period": [
            ("return_period_estimate_bounded", "metric"),
            ("fitting_parameters_locked", "readiness"),
        ],
    }

    for gate_name, claims in gate_to_claims.items():
        gate_passed = gate_results[gate_name]["passed"]
        gate_reason = gate_results[gate_name]["reason"]
        for claim_name, assertion_type in claims:
            if gate_passed and effective_rank >= tier_rank("exploratory"):
                allowed_claims.append({
                    "claim": claim_name,
                    "assertion_type": assertion_type,
                    "status": "allowed",
                    "reason": gate_reason,
                })
            else:
                blocked_claims.append({
                    "claim": claim_name,
                    "assertion_type": assertion_type,
                    "status": "blocked",
                    "reason": gate_reason,
                })

    return {
        "station_id": values.get("station_id"),
        "effective_claim_tier": effective,
        "claimed_tier": claim_tier,
        "claim_met": effective_rank >= claimed_rank,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "blocked_claims": blocked_claims,
        "allowed_claims": allowed_claims,
        "gate_details": gate_results,
    }
