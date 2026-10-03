"""Hard DDS request budgets include seed evaluations and preserve legacy replay."""

import json
import random
from pathlib import Path

import pandas as pd
import pytest

from swatplus_builder.calibration.locked_benchmark import (
    BenchmarkLock,
    _dds_search,
    calibrate_against_lock,
)


def _make_lock_and_alignment(tmp_path):
    benchmark = tmp_path / "benchmark"
    benchmark.mkdir()
    dates = pd.date_range("2010-01-01", periods=120)
    pd.DataFrame(
        {
            "obs": [float(i % 5 + 1) for i in range(120)],
            "sim": [float(i % 5 + 1.1) for i in range(120)],
        },
        index=dates,
    ).to_csv(benchmark / "alignment.csv")
    return BenchmarkLock(
        basin_id="budget_test",
        locked_at_utc="2026-10-02T00:00:00+00:00",
        alignment_sha256="x",
        metrics_sha256="y",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0,
        baseline_kge=0,
        benchmark_dir=str(benchmark),
    ), benchmark


@pytest.mark.parametrize("budget", [0, 1, 2, 7])
@pytest.mark.parametrize("feasible", [True, False])
def test_total_budget_caps_calls_including_failed_feasibility(budget, feasible):
    calls = []

    def evaluate(point):
        calls.append(point)
        return {"nse": 0.5, "pbias": 0.0 if feasible else 100.0}

    best, _, _ = _dds_search(
        evaluate=evaluate,
        score_fn=lambda m: m["nse"],
        feasible_fn=lambda m: abs(m["pbias"]) <= 30,
        phase_parameters=["x"],
        param_bounds={"x": (0, 1)},
        start_params={"x": 0.5},
        budget=budget,
        rng=random.Random(42),
        budget_is_total=True,
    )
    assert len(calls) == budget
    assert (best is not None) == (feasible and budget > 0)


def test_zero_budget_preserves_already_evaluated_incumbent():
    incumbent = ({"x": 0.5}, {"nse": 0.8}, 0.8)

    def forbidden(_):
        pytest.fail("Zero remaining budget must not launch a seed")

    assert (
        _dds_search(
            evaluate=forbidden,
            score_fn=lambda m: m["nse"],
            feasible_fn=lambda m: True,
            phase_parameters=["x"],
            param_bounds={"x": (0, 1)},
            start_params={},
            budget=0,
            rng=random.Random(42),
            initial_best=incumbent,
            budget_is_total=True,
        )
        == incumbent
    )


def test_legacy_seed_allocation_is_unchanged():
    calls = []
    _dds_search(
        evaluate=lambda p: calls.append(p) or {"nse": 0.5},
        score_fn=lambda m: m["nse"],
        feasible_fn=lambda m: True,
        phase_parameters=["x"],
        param_bounds={"x": (0, 1)},
        start_params={},
        budget=3,
        rng=random.Random(42),
    )
    assert len(calls) == 4


@pytest.mark.parametrize("method", ["dds", "grid"])
def test_locked_search_caps_anchors_and_search_requests(monkeypatch, tmp_path, method):
    lock, _ = _make_lock_and_alignment(tmp_path)
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    calls = []

    def factory(**kwargs):
        def evaluate(point):
            calls.append(point)
            return {"nse": 0.6, "kge": 0.5, "pbias": 10.0}

        return evaluate

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", factory)
    monkeypatch.setattr(
        "swatplus_builder.calibration.locked_benchmark._sensitivity_guided_anchor_points",
        lambda *a, **kw: [{"CN2": float(x)} for x in range(50, 58)],
    )
    result = calibrate_against_lock(
        lock,
        txt,
        tmp_path / "cal",
        parameters=["CN2"],
        n_evaluations=2,
        calibration_phases=[{"phase": "volume", "parameters": ["CN2"], "budget": 2}],
        search_method=method,
        hard_search_budget=True,
    )
    assert len(calls) == 2
    payload = json.loads(Path(result.best_solution_json).read_text())
    assert payload["search_budget_policy"] == "hard_objective_requests_v1"


def test_hard_budget_rejects_overallocated_phases_before_evaluation(monkeypatch, tmp_path):
    lock, _ = _make_lock_and_alignment(tmp_path)
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    calls = []
    monkeypatch.setattr(
        "swatplus_builder.calibration.real_engine.make_real_objective",
        lambda **kw: lambda p: calls.append(p),
    )
    with pytest.raises(ValueError, match="Phase budgets"):
        calibrate_against_lock(
            lock,
            txt,
            tmp_path / "cal",
            parameters=["CN2"],
            n_evaluations=1,
            calibration_phases=[{"phase": "volume", "parameters": ["CN2"], "budget": 2}],
            hard_search_budget=True,
        )
    assert not calls


@pytest.mark.parametrize("phase_budget", [-1, 0, 1.5, True])
def test_hard_budget_rejects_invalid_explicit_phase_budget(tmp_path, phase_budget):
    with pytest.raises(ValueError, match="Phase budgets"):
        calibrate_against_lock(
            "unused_lock",
            "unused_inputs",
            tmp_path,
            n_evaluations=10,
            calibration_phases=[{"phase": "volume", "budget": phase_budget}],
            hard_search_budget=True,
        )


def test_nonfinite_skill_cannot_win_with_finite_volume_bias(monkeypatch, tmp_path):
    from swatplus_builder.errors import SwatBuilderPipelineError

    lock, _ = _make_lock_and_alignment(tmp_path)
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    monkeypatch.setattr(
        "swatplus_builder.calibration.real_engine.make_real_objective",
        lambda **kw: lambda point: {"nse": float("nan"), "kge": 0.8, "pbias": 0.0},
    )
    with pytest.raises(SwatBuilderPipelineError):
        calibrate_against_lock(
            lock,
            txt,
            tmp_path / "cal",
            parameters=["CN2"],
            n_evaluations=2,
            calibration_phases=[{"phase": "volume", "parameters": ["CN2"], "budget": 2}],
            hard_search_budget=True,
        )
    assert not (tmp_path / "cal/calibration_reports_locked/best_solution.json").exists()
