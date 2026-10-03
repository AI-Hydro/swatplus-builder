"""Pilot adapter and attributed/physical budgets; no engines or GP fitting."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from swatplus_builder.calibration.surrogate_optimizer import ConstrainedGPOptimizer

_SPEC = importlib.util.spec_from_file_location(
    "calibration_optimizer_pilot",
    Path(__file__).parents[1] / "scripts/research/calibration_optimizer_pilot.py",
)
pilot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pilot)


def values(**overrides):
    return {"nse": 0.4, "kge": 0.6, "pbias": 5.0, "calibration_process_gate_passed": 1, **overrides}


@pytest.mark.parametrize("key", ["nse", "kge", "pbias", "calibration_process_gate_passed"])
def test_missing_required_observation_is_invalid(key):
    metrics = values()
    metrics.pop(key)
    assert pilot.measured_observation("run", metrics).status == "failed"
    assert not pilot.feasible(metrics)


@pytest.mark.parametrize("key", ["nse", "kge", "pbias"])
def test_nonfinite_observation_not_a_numeric_penalty(key):
    result = pilot.measured_observation("run", values(**{key: math.nan}))
    assert result.status == "failed"
    assert result.utility is None
    assert dict(result.constraints) == {}


def test_explicit_false_process_and_volume_violation_retain_finite_utility():
    result = pilot.measured_observation(
        "run", values(pbias=40.0, calibration_process_gate_passed=0)
    )
    assert result.status == "success"
    assert result.utility == 0.6
    assert result.constraints["volume"] > 0
    assert result.constraints["calibration_process"] > 0
    assert not pilot.feasible(values(calibration_process_gate_passed=0))
    assert not pilot.feasible(values(pbias=40.0))


def mock_gp(monkeypatch):
    bounds = {"PET_CO": (0.8, 1.2), "PERCO": (0.01, 1.0)}
    points = [
        {"PET_CO": 1.2, "PERCO": 1.0},
        {"PET_CO": 0.9, "PERCO": 0.2575},
        {"PET_CO": 1.1, "PERCO": 0.7525},
    ]
    gp = ConstrainedGPOptimizer(
        bounds, pilot.CONSTRAINTS, budget=6, initial_design_size=3, initial_points=points
    )
    monkeypatch.setattr(gp, "check_dependencies", lambda: None)
    monkeypatch.setattr(gp, "_gp_proposal", lambda measured: (0.1 + gp.proposals_issued / 10, 0.4))
    return bounds, points, gp


def test_budget_and_fresh_final_attribution(monkeypatch):
    bounds, points, gp = mock_gp(monkeypatch)
    calls = []

    def evaluate(parameters, label):
        calls.append((parameters, label))
        return values(kge=0.8 - parameters["PERCO"] * 0.1)

    report = pilot.run_comparison(evaluate, bounds, points, gp=gp)
    assert len(calls) == report["actual_physical_calls"] == 11
    assert report["attributed_calls"] == 14
    assert [label for _, label in calls[:3]] == ["shared_0", "shared_1", "shared_2"]
    assert len({label for _, label in calls}) == 11
    for arm in report["arms"].values():
        assert len(arm["search_evaluation_ids"]) == 6
        assert arm["attributed_calls"] == 7
        assert arm["fresh_final_matches_search"]
        assert arm["verification_status"] == "fresh_training_reproduced"


def test_fresh_mismatch_is_reported_without_claiming_verified(monkeypatch):
    bounds, points, gp = mock_gp(monkeypatch)

    def evaluate(parameters, label):
        return values(kge=0.6 + (0.05 if label == "gp_fresh_final" else 0))

    report = pilot.run_comparison(evaluate, bounds, points, gp=gp)
    assert not report["arms"]["gp"]["fresh_final_matches_search"]
    assert report["arms"]["gp"]["verification_status"] == "verification_failed"
    assert report["arms"]["gp"]["fresh_minus_search"]["kge"] == pytest.approx(0.05)


def test_known_failures_charge_budget_and_no_feasible_candidate_skips_final(monkeypatch):
    bounds, points, gp = mock_gp(monkeypatch)

    def evaluate(parameters, label):
        raise TimeoutError("simulator timed out")

    report = pilot.run_comparison(evaluate, bounds, points, gp=gp)
    assert report["actual_physical_calls"] == 9
    assert report["attributed_calls"] == 12
    assert all(record["status"] == "failed" for record in report["physical_calls"])
    assert all(a["verification_status"] == "not_reached" for a in report["arms"].values())


def test_unexpected_adapter_error_is_persisted_and_propagates(monkeypatch):
    bounds, points, gp = mock_gp(monkeypatch)
    snapshots = []

    def evaluate(parameters, label):
        raise TypeError("adapter bug")

    with pytest.raises(TypeError, match="adapter bug"):
        pilot.run_comparison(evaluate, bounds, points, gp=gp, checkpoint=snapshots.append)
    assert snapshots[-1]["physical_calls"][0]["status"] == "adapter_error"
    assert len(snapshots[-1]["physical_calls"]) == 1


def test_process_proxy_signed_encoding_preserves_observed_gate():
    passing = pilot.measured_observation("pass", values(calibration_process_gate_passed=1))
    failing = pilot.measured_observation("fail", values(calibration_process_gate_passed=0))
    assert passing.constraints["calibration_process"] == -1.0
    assert failing.constraints["calibration_process"] == 1.0
    assert pilot.feasible(values(calibration_process_gate_passed=1))
    assert not pilot.feasible(values(calibration_process_gate_passed=0))
