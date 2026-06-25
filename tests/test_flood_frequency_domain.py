"""Tests for swatplus_builder.domains.flood_frequency — B4 second-domain toy.

Demonstrates that swatplus_builder.governance is domain-agnostic: the same
tier ladder powers a flood-frequency analysis domain without importing anything
from swatplus_builder.workflows.
"""
from __future__ import annotations

import pytest

from swatplus_builder.domains.flood_frequency import (
    MAX_CI_RELATIVE_HALF_WIDTH,
    MAX_FIT_RMSE,
    MIN_RECORD_YEARS,
    STATIONARITY_P_THRESHOLD,
    data_adequacy_gate,
    distribution_fit_gate,
    return_period_gate,
    run_flood_frequency,
    stationarity_gate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_pass_values() -> dict:
    """A payload that passes all 4 gates → research_grade."""
    return {
        "station_id": "08158000",
        "n_years": 65,
        "trend_p_value": 0.18,
        "trend_slope_pct_per_decade": 0.4,
        "best_fit_distribution": "GEV",
        "distribution_fit_rmse": 0.028,
        "t100_estimate_m3s": 1240.0,
        "t100_ci_half_width_m3s": 210.0,
        "fitting_locked": True,
    }


# ---------------------------------------------------------------------------
# data_adequacy_gate
# ---------------------------------------------------------------------------

def test_data_adequacy_passes_sufficient_record() -> None:
    result = data_adequacy_gate({"n_years": MIN_RECORD_YEARS})
    assert result["passed"] is True


def test_data_adequacy_passes_long_record() -> None:
    result = data_adequacy_gate({"n_years": 80})
    assert result["passed"] is True


def test_data_adequacy_fails_short_record() -> None:
    result = data_adequacy_gate({"n_years": MIN_RECORD_YEARS - 1})
    assert result["passed"] is False
    assert str(MIN_RECORD_YEARS) in result["reason"]


def test_data_adequacy_fails_missing() -> None:
    result = data_adequacy_gate({})
    assert result["passed"] is False
    assert "missing" in result["reason"]


def test_data_adequacy_fails_zero() -> None:
    result = data_adequacy_gate({"n_years": 0})
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# stationarity_gate
# ---------------------------------------------------------------------------

def test_stationarity_passes_non_significant() -> None:
    result = stationarity_gate({"trend_p_value": 0.20})
    assert result["passed"] is True


def test_stationarity_passes_boundary() -> None:
    result = stationarity_gate({"trend_p_value": STATIONARITY_P_THRESHOLD})
    assert result["passed"] is True


def test_stationarity_fails_significant_trend() -> None:
    result = stationarity_gate({"trend_p_value": 0.02})
    assert result["passed"] is False
    assert "p=" in result["reason"]


def test_stationarity_fails_missing_p_value() -> None:
    result = stationarity_gate({})
    assert result["passed"] is False
    assert "missing" in result["reason"]


def test_stationarity_reason_includes_slope_when_present() -> None:
    result = stationarity_gate({"trend_p_value": 0.01, "trend_slope_pct_per_decade": 5.2})
    assert result["passed"] is False
    assert "5.2" in result["reason"]


# ---------------------------------------------------------------------------
# distribution_fit_gate
# ---------------------------------------------------------------------------

def test_distribution_fit_passes_low_rmse() -> None:
    result = distribution_fit_gate({"best_fit_distribution": "GEV", "distribution_fit_rmse": 0.020})
    assert result["passed"] is True


def test_distribution_fit_passes_at_threshold() -> None:
    result = distribution_fit_gate({"best_fit_distribution": "LP3", "distribution_fit_rmse": MAX_FIT_RMSE})
    assert result["passed"] is True


def test_distribution_fit_fails_high_rmse() -> None:
    result = distribution_fit_gate({"best_fit_distribution": "GEV", "distribution_fit_rmse": 0.080})
    assert result["passed"] is False
    assert "RMSE" in result["reason"]


def test_distribution_fit_fails_missing_distribution() -> None:
    result = distribution_fit_gate({"distribution_fit_rmse": 0.020})
    assert result["passed"] is False
    assert "missing" in result["reason"]


def test_distribution_fit_fails_missing_rmse() -> None:
    result = distribution_fit_gate({"best_fit_distribution": "GEV"})
    assert result["passed"] is False
    assert "missing" in result["reason"]


# ---------------------------------------------------------------------------
# return_period_gate
# ---------------------------------------------------------------------------

def test_return_period_passes_narrow_ci() -> None:
    result = return_period_gate({
        "t100_estimate_m3s": 1000.0,
        "t100_ci_half_width_m3s": 200.0,
        "fitting_locked": True,
    })
    assert result["passed"] is True


def test_return_period_passes_at_relative_threshold() -> None:
    estimate = 1000.0
    half_width = estimate * MAX_CI_RELATIVE_HALF_WIDTH
    result = return_period_gate({
        "t100_estimate_m3s": estimate,
        "t100_ci_half_width_m3s": half_width,
        "fitting_locked": True,
    })
    assert result["passed"] is True


def test_return_period_fails_wide_ci() -> None:
    result = return_period_gate({
        "t100_estimate_m3s": 1000.0,
        "t100_ci_half_width_m3s": 600.0,
        "fitting_locked": True,
    })
    assert result["passed"] is False
    assert "relative" in result["reason"]


def test_return_period_fails_unlocked_fitting() -> None:
    result = return_period_gate({
        "t100_estimate_m3s": 1000.0,
        "t100_ci_half_width_m3s": 100.0,
        "fitting_locked": False,
    })
    assert result["passed"] is False
    assert "fitting_locked" in result["reason"]


def test_return_period_fails_missing_estimate() -> None:
    result = return_period_gate({"t100_ci_half_width_m3s": 100.0, "fitting_locked": True})
    assert result["passed"] is False
    assert "missing" in result["reason"]


def test_return_period_fails_missing_ci() -> None:
    result = return_period_gate({"t100_estimate_m3s": 1000.0, "fitting_locked": True})
    assert result["passed"] is False
    assert "missing" in result["reason"]


def test_return_period_fails_zero_estimate() -> None:
    result = return_period_gate({
        "t100_estimate_m3s": 0.0,
        "t100_ci_half_width_m3s": 100.0,
        "fitting_locked": True,
    })
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# run_flood_frequency — tier outcomes
# ---------------------------------------------------------------------------

def test_run_research_grade_all_gates_pass() -> None:
    result = run_flood_frequency(_full_pass_values(), claim_tier="research_grade")
    assert result["effective_claim_tier"] == "research_grade"
    assert result["claim_met"] is True
    assert result["gates_failed"] == []
    assert result["station_id"] == "08158000"


def test_run_publication_grade_return_period_fails() -> None:
    values = _full_pass_values()
    values["t100_ci_half_width_m3s"] = 900.0
    result = run_flood_frequency(values, claim_tier="research_grade")
    assert result["effective_claim_tier"] == "publication_grade"
    assert result["claim_met"] is False
    assert "return_period" in result["gates_failed"]


def test_run_diagnostic_distribution_fit_fails() -> None:
    values = _full_pass_values()
    values["distribution_fit_rmse"] = 0.09
    result = run_flood_frequency(values, claim_tier="research_grade")
    # data_adequacy + stationarity pass, distribution_fit fails → diagnostic
    assert result["effective_claim_tier"] == "diagnostic"
    assert result["claim_met"] is False
    assert "distribution_fit" in result["gates_failed"]


def test_run_exploratory_stationarity_fails() -> None:
    values = _full_pass_values()
    values["trend_p_value"] = 0.003
    result = run_flood_frequency(values, claim_tier="research_grade")
    # stationarity fails → tier stops at exploratory (data_adequacy passed)
    assert result["effective_claim_tier"] == "exploratory"
    assert result["claim_met"] is False
    assert "stationarity" in result["gates_failed"]


def test_run_exploratory_only_data_adequacy_passes() -> None:
    result = run_flood_frequency({"n_years": 25}, claim_tier="research_grade")
    assert result["effective_claim_tier"] == "exploratory"
    assert "data_adequacy" in result["gates_passed"]
    assert "stationarity" in result["gates_failed"]


def test_run_blocked_insufficient_data() -> None:
    result = run_flood_frequency({"n_years": 5}, claim_tier="exploratory")
    assert result["effective_claim_tier"] == "blocked"
    assert result["claim_met"] is False
    assert len(result["blocked_claims"]) > 0


def test_run_claim_met_when_effective_exceeds_claimed() -> None:
    result = run_flood_frequency(_full_pass_values(), claim_tier="diagnostic")
    assert result["claim_met"] is True
    assert result["effective_claim_tier"] == "research_grade"


def test_run_invalid_claim_tier_raises() -> None:
    with pytest.raises(ValueError, match="claim_tier"):
        run_flood_frequency(_full_pass_values(), claim_tier="unknown_tier")


def test_run_gate_details_present_for_all_gates() -> None:
    result = run_flood_frequency(_full_pass_values())
    for gate in ("data_adequacy", "stationarity", "distribution_fit", "return_period"):
        assert gate in result["gate_details"]
        assert "passed" in result["gate_details"][gate]
        assert "reason" in result["gate_details"][gate]


# ---------------------------------------------------------------------------
# Generality: governance module is the only swatplus import
# ---------------------------------------------------------------------------

def test_flood_frequency_only_imports_governance_not_workflows() -> None:
    """Prove the domain module doesn't import from swatplus_builder.workflows."""
    from pathlib import Path

    import swatplus_builder.domains.flood_frequency as ff_mod
    src = Path(ff_mod.__file__).read_text(encoding="utf-8")
    import_lines = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    import_block = "\n".join(import_lines)
    assert "workflows" not in import_block, (
        "flood_frequency domain imports from workflows — violates governance-core separation:\n"
        + import_block
    )
    assert "swatplus_builder.governance" in import_block, (
        "flood_frequency domain must import from swatplus_builder.governance"
    )
