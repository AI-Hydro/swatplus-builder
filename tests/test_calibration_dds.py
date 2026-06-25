"""Unit tests for the DDS (Dynamically Dimensioned Search) calibration core.

These test the pure search algorithm in isolation, with a synthetic objective,
so they run without the SWAT+ engine. They verify the Tolson & Shoemaker (2007)
neighbourhood operator and that the volume-gate-first feasibility contract is
preserved (only feasible candidates can win).
"""

from __future__ import annotations

import math
import random

from swatplus_builder.calibration.locked_benchmark import (
    _dds_propose,
    _dds_search,
    _reflect_at_bounds,
)

# ---------------------------------------------------------------------------
# _reflect_at_bounds
# ---------------------------------------------------------------------------


def test_reflect_in_range_unchanged():
    assert _reflect_at_bounds(0.5, 0.0, 1.0) == 0.5


def test_reflect_below_lower_bound():
    # 0.0 - 0.2 = -0.2 -> reflect across 0.0 -> +0.2
    assert _reflect_at_bounds(-0.2, 0.0, 1.0) == 0.2


def test_reflect_above_upper_bound():
    # 1.0 + 0.3 = 1.3 -> reflect across 1.0 -> 0.7
    assert math.isclose(_reflect_at_bounds(1.3, 0.0, 1.0), 0.7)


def test_reflect_extreme_overshoot_clamps_to_opposite_bound():
    # huge negative reflects past hi -> clamped to hi
    assert _reflect_at_bounds(-100.0, 0.0, 1.0) == 1.0
    # huge positive reflects past lo -> clamped to lo
    assert _reflect_at_bounds(100.0, 0.0, 1.0) == 0.0


def test_reflect_degenerate_bounds():
    assert _reflect_at_bounds(5.0, 2.0, 2.0) == 2.0


# ---------------------------------------------------------------------------
# _dds_propose
# ---------------------------------------------------------------------------


def _bounds(names):
    return dict.fromkeys(names, (0.0, 1.0))


def test_propose_stays_in_bounds():
    rng = random.Random(1)
    names = ["a", "b", "c"]
    best = {"a": 0.5, "b": 0.5, "c": 0.5}
    for i in range(1, 200):
        cand = _dds_propose(
            best,
            phase_parameters=names,
            param_bounds=_bounds(names),
            iteration=i,
            n_iterations=200,
            rng=rng,
            r=0.5,  # large step to stress the reflection
        )
        for n in names:
            assert 0.0 <= cand[n] <= 1.0


def test_propose_perturbs_at_least_one_dimension():
    rng = random.Random(2)
    names = ["a", "b"]
    best = {"a": 0.3, "b": 0.7}
    # late iteration -> low inclusion probability, but at least one must change
    for _ in range(1, 50):
        cand = _dds_propose(
            best,
            phase_parameters=names,
            param_bounds=_bounds(names),
            iteration=49,
            n_iterations=50,
            rng=rng,
            r=0.2,
        )
        assert cand != best


def test_propose_preserves_non_phase_parameters():
    rng = random.Random(3)
    best = {"a": 0.3, "b": 0.7, "frozen": 0.9}
    cand = _dds_propose(
        best,
        phase_parameters=["a", "b"],
        param_bounds=_bounds(["a", "b"]),
        iteration=1,
        n_iterations=10,
        rng=rng,
        r=0.2,
    )
    assert cand["frozen"] == 0.9


def test_propose_selection_probability_decays():
    """Early iterations perturb more dimensions than late ones (statistically)."""
    names = [f"p{k}" for k in range(20)]
    best = dict.fromkeys(names, 0.5)
    bounds = _bounds(names)

    def count_changed(iteration, n_iter, seed):
        rng = random.Random(seed)
        cand = _dds_propose(
            best,
            phase_parameters=names,
            param_bounds=bounds,
            iteration=iteration,
            n_iterations=n_iter,
            rng=rng,
            r=0.2,
        )
        return sum(1 for n in names if cand[n] != best[n])

    early = sum(count_changed(1, 100, s) for s in range(30))
    late = sum(count_changed(99, 100, s) for s in range(30))
    assert early > late


# ---------------------------------------------------------------------------
# _dds_search — convergence + feasibility contract
# ---------------------------------------------------------------------------


def _make_bowl_objective(target, *, feasible_band=0.5):
    """Synthetic objective: NSE peaks at `target`. pbias encodes feasibility.

    pbias grows with distance from target; |pbias| <= 30 (the volume gate)
    holds only within `feasible_band` of the target.
    """

    def objective(point):
        x = point["x"]
        dist = abs(x - target)
        nse = 1.0 - dist  # higher near target
        # pbias scaled so it exits +-30 outside the feasible band
        pbias = (dist / feasible_band) * 30.0
        return {"nse": nse, "kge": nse, "pbias": pbias}

    return objective


def _volume_gate(metrics):
    pb = metrics.get("pbias")
    return isinstance(pb, (int, float)) and math.isfinite(pb) and abs(pb) <= 30.0


def _score(metrics):
    nse = metrics.get("nse", float("-inf"))
    return float(nse) if isinstance(nse, (int, float)) else float("-inf")


def test_dds_search_converges_better_than_seed():
    rng = random.Random(42)
    target = 0.8
    objective = _make_bowl_objective(target, feasible_band=0.9)
    calls = []

    def evaluate(point):
        m = objective(point)
        calls.append(point)
        return m

    best_params, best_metrics, best_score = _dds_search(
        evaluate=evaluate,
        score_fn=_score,
        feasible_fn=_volume_gate,
        phase_parameters=["x"],
        param_bounds={"x": (0.0, 1.0)},
        start_params={"x": 0.1},  # far from target
        budget=60,
        rng=rng,
        r=0.2,
    )
    assert best_params is not None
    # DDS should land much closer to the optimum than the seed at 0.1
    assert abs(best_params["x"] - target) < 0.1
    assert best_score > _score(objective({"x": 0.1}))
    assert len(calls) == 61  # seed + 60 iterations


def test_dds_search_returns_none_when_nothing_feasible():
    rng = random.Random(7)
    # Objective where pbias is always far outside the gate.
    def objective(point):
        return {"nse": 0.5, "kge": 0.5, "pbias": 200.0}

    best_params, best_metrics, best_score = _dds_search(
        evaluate=objective,
        score_fn=_score,
        feasible_fn=_volume_gate,
        phase_parameters=["x"],
        param_bounds={"x": (0.0, 1.0)},
        start_params={"x": 0.5},
        budget=20,
        rng=rng,
        r=0.2,
    )
    assert best_params is None
    assert best_score == float("-inf")


def test_dds_search_only_returns_feasible_winner():
    """An infeasible point with high NSE must never be returned as the winner."""
    rng = random.Random(11)

    def objective(point):
        x = point["x"]
        # Highest NSE at x=0 but that region is volume-gate-infeasible;
        # feasible region is x >= 0.5 with lower but valid NSE.
        if x < 0.5:
            return {"nse": 10.0, "kge": 10.0, "pbias": 99.0}  # great skill, fails gate
        return {"nse": 0.5, "kge": 0.5, "pbias": 5.0}  # modest skill, passes gate

    best_params, best_metrics, best_score = _dds_search(
        evaluate=objective,
        score_fn=_score,
        feasible_fn=_volume_gate,
        phase_parameters=["x"],
        param_bounds={"x": (0.0, 1.0)},
        start_params={"x": 0.7},
        budget=40,
        rng=rng,
        r=0.2,
    )
    assert best_params is not None
    assert _volume_gate(best_metrics)
    assert best_params["x"] >= 0.5
