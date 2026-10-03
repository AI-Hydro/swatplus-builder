"""Offline budget, observation authority and constrained search contract checks."""

import importlib.util
import math

import pytest

from swatplus_builder.calibration.surrogate_optimizer import (
    ConstrainedGPOptimizer,
    ConstrainedObservation,
    SurrogateDependencyError,
    run_surrogate_search,
)


def optimizer(**kwargs):
    return ConstrainedGPOptimizer(
        {"x": (-2.0, 3.0), "y": (10.0, 20.0)},
        ("volume",),
        budget=kwargs.pop("budget", 4),
        initial_design_size=2,
        **kwargs,
    )


def observed(index, utility=1.0, residual=-0.1):
    return ConstrainedObservation(str(index), "success", utility, {"volume": residual})


def test_budget_charges_failed_runs_and_returns_measured_admissible_best():
    opt = optimizer(missing_dependency="random")
    first = opt.ask()
    opt.tell(first.proposal_id, observed(0, 2.0))
    second = opt.ask()
    opt.tell(second.proposal_id, observed(1, 100.0, residual=1.0))
    third = opt.ask()
    opt.tell(third.proposal_id, ConstrainedObservation("2", "timeout"))
    fourth = opt.ask()
    opt.tell(fourth.proposal_id, observed(3, 1.0))
    assert opt.best.proposal == first
    assert len(opt.observations) == opt.proposals_issued == 4
    with pytest.raises(StopIteration):
        opt.ask()


def test_pending_and_evaluation_identity_prevent_duplicate_observations():
    opt = optimizer()
    proposal = opt.ask()
    with pytest.raises(RuntimeError, match="pending"):
        opt.ask()
    with pytest.raises(ValueError, match="pending"):
        opt.tell(999, observed(0))
    opt.tell(proposal.proposal_id, observed(0))
    second = opt.ask()
    with pytest.raises(ValueError, match="reused"):
        opt.tell(second.proposal_id, observed(0))
    assert len(opt.observations) == 1


def test_missing_constraint_is_not_admissible_or_training_data():
    opt = optimizer()
    proposal = opt.ask()
    with pytest.raises(ValueError, match="every declared"):
        opt.tell(proposal.proposal_id, ConstrainedObservation("0", "success", 1.0, {}))
    assert opt.best is None
    assert opt.observations == ()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_targets_and_constraints_rejected(value):
    with pytest.raises(ValueError, match="finite utility"):
        observed(0, value)
    with pytest.raises(ValueError, match="residuals must be finite"):
        observed(0, residual=value)


def test_failed_run_cannot_become_penalty_training_target():
    with pytest.raises(ValueError, match="synthetic"):
        ConstrainedObservation("run", "failed", -1e6)


def test_normalization_and_readonly_candidate_records():
    opt = optimizer()
    assert opt.normalize({"x": 0.5, "y": 15.0}) == (0.5, 0.5)
    with pytest.raises(ValueError, match="outside bounds"):
        opt.normalize({"x": 4.0, "y": 15.0})
    proposal = opt.ask()
    with pytest.raises(TypeError):
        proposal.parameters["x"] = 9
    for key, (low, high) in opt.bounds.items():
        assert low <= proposal.parameters[key] <= high


def test_design_is_seeded_and_each_dimension_uses_distinct_strata():
    a, b = optimizer(seed=17), optimizer(seed=17)
    first, second = [], []
    for idx in range(2):
        p, q = a.ask(), b.ask()
        assert p.method == q.method == "initial_latin_design"
        first.append(a.normalize(p.parameters))
        second.append(b.normalize(q.parameters))
        a.tell(p.proposal_id, observed(idx))
        b.tell(q.proposal_id, observed(idx))
    assert first == second
    for dim in range(2):
        assert {int(row[dim] * 2) for row in first} == {0, 1}


def test_missing_dependency_does_not_consume_proposal_budget(monkeypatch):
    opt = optimizer()
    for idx in range(2):
        p = opt.ask()
        opt.tell(p.proposal_id, observed(idx))

    def missing(_):
        raise SurrogateDependencyError("optional botorch unavailable")

    monkeypatch.setattr(opt, "_gp_proposal", missing)
    with pytest.raises(SurrogateDependencyError):
        opt.ask()
    assert opt.proposals_issued == 2
    opt.missing_dependency = "random"
    proposal = opt.ask()
    assert proposal.method == "random_missing_gp_dependency"
    assert opt.proposals_issued == 3


def test_all_failed_data_uses_explicit_exploration_and_cannot_win():
    opt = optimizer()
    for idx in range(2):
        proposal = opt.ask()
        opt.tell(proposal.proposal_id, ConstrainedObservation(str(idx), "failed"))
    proposal = opt.ask()
    assert proposal.method == "random_insufficient_finite_observations"
    assert opt.best is None


def test_callback_search_uses_only_real_reported_observations():
    opt = optimizer(budget=2, missing_dependency="random")
    calls = []

    def evaluate(parameters):
        calls.append(dict(parameters))
        return observed(len(calls), -(parameters["x"] ** 2))

    winner = run_surrogate_search(opt, evaluate)
    assert len(calls) == 2
    assert dict(winner.proposal.parameters) in calls
    assert winner.observation.utility == max(r.observation.utility for r in opt.observations)


@pytest.mark.skipif(
    importlib.util.find_spec("botorch") is None or importlib.util.find_spec("gpytorch") is None,
    reason="Optional GP packages are absent; no packages installed by this test",
)
def test_real_botorch_proposal_is_bounded_distinct_and_does_not_authorize_a_result():
    opt = optimizer(candidate_pool_size=16)
    for idx in range(2):
        proposal = opt.ask()
        opt.tell(proposal.proposal_id, observed(idx, utility=float(idx), residual=0.5 - idx))
    previous = opt.best
    proposal = opt.ask()
    assert proposal.method == "constrained_gp_thompson"
    diagnostics = opt.proposal_diagnostics[-1]
    assert diagnostics.status == "proposed"
    assert diagnostics.fit_seconds > 0
    assert diagnostics.sampling_seconds > 0
    assert diagnostics.candidate_generation_seconds > 0
    assert (
        diagnostics.total_seconds
        >= diagnostics.fit_seconds
        + diagnostics.sampling_seconds
        + diagnostics.candidate_generation_seconds
    )
    assert diagnostics.finite_training_observations == 2
    assert opt.best == previous
    assert all(lo <= proposal.parameters[n] <= hi for n, (lo, hi) in opt.bounds.items())
    assert all(dict(proposal.parameters) != dict(r.proposal.parameters) for r in opt.observations)


def test_shared_design_is_exact_and_rejects_duplicates():
    points = [{"x": -1.0, "y": 12.0}, {"x": 2.0, "y": 18.0}]
    opt = optimizer(initial_points=points)
    for index, expected in enumerate(points):
        proposal = opt.ask()
        assert dict(proposal.parameters) == expected
        assert proposal.method == "initial_shared_design"
        opt.tell(proposal.proposal_id, observed(index))
    with pytest.raises(ValueError, match="distinct"):
        optimizer(initial_points=[points[0], points[0]])


def test_real_lazy_import_reports_optional_backend_absence(monkeypatch):
    import builtins

    opt = optimizer()
    for index in range(2):
        proposal = opt.ask()
        opt.tell(proposal.proposal_id, observed(index))
    original = builtins.__import__

    def without_botorch(name, *args, **kwargs):
        if name.startswith("botorch"):
            raise ImportError("blocked optional package")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_botorch)
    with pytest.raises(SurrogateDependencyError, match="no packages are installed"):
        opt.ask()
    assert opt.proposals_issued == 2


def test_callback_runner_preflights_missing_gp_before_spending_engine_calls(monkeypatch):
    import builtins

    opt = optimizer()
    calls = []
    original = builtins.__import__

    def without_botorch(name, *args, **kwargs):
        if name.startswith("botorch"):
            raise ImportError("blocked optional package")
        return original(name, *args, **kwargs)

    def evaluate(parameters):
        calls.append(parameters)
        return observed(len(calls))

    monkeypatch.setattr(builtins, "__import__", without_botorch)
    with pytest.raises(SurrogateDependencyError):
        run_surrogate_search(opt, evaluate)
    assert calls == []
    assert opt.proposals_issued == 0


@pytest.mark.parametrize("name", ["budget", "initial_design_size", "candidate_pool_size"])
@pytest.mark.parametrize("value", [True, False, 1.5])
def test_fractional_or_boolean_allocation_sizes_rejected(name, value):
    options = {"budget": 4, "initial_design_size": 2, "candidate_pool_size": 16}
    options[name] = value
    with pytest.raises(ValueError, match="must be an integer"):
        ConstrainedGPOptimizer({"x": (0.0, 1.0)}, ("volume",), **options)


def test_proposal_diagnostics_capture_warnings_and_callback_without_changing_points(monkeypatch):
    import json
    import warnings

    callbacks = []
    first = optimizer(diagnostics_callback=callbacks.append)
    second = optimizer()

    def proposal(measured):
        warnings.warn("fit diagnostic", RuntimeWarning, stacklevel=2)
        return (0.25, 0.75)

    for opt in (first, second):
        for index in range(2):
            p = opt.ask()
            opt.tell(p.proposal_id, observed(index))
        monkeypatch.setattr(opt, "_gp_proposal", proposal)
    p, q = first.ask(), second.ask()
    assert dict(p.parameters) == dict(q.parameters)
    assert len(callbacks) == 3
    diagnostics = callbacks[-1]
    assert diagnostics.warnings == ("RuntimeWarning: fit diagnostic",)
    assert diagnostics.total_seconds >= 0
    assert json.loads(json.dumps(diagnostics.to_json()))["method"] == p.method
    assert first.proposal_diagnostics[-1] == diagnostics


def test_failed_proposal_diagnostics_persist_and_respect_warning_error_policy(monkeypatch):
    import warnings

    opt = optimizer()
    for index in range(2):
        p = opt.ask()
        opt.tell(p.proposal_id, observed(index))

    def broken(measured):
        warnings.warn("strict numerical warning", RuntimeWarning, stacklevel=2)
        return (0.25, 0.75)

    monkeypatch.setattr(opt, "_gp_proposal", broken)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with pytest.raises(RuntimeWarning, match="strict numerical"):
            opt.ask()
    assert opt.proposals_issued == 2
    diagnostics = opt.proposal_diagnostics[-1]
    assert diagnostics.status == "error"
    assert "RuntimeWarning" in diagnostics.error
    assert opt.best is not None


def test_checkpoint_export_preserves_failed_cost_and_pending_authority():
    import json

    opt = optimizer()
    first = opt.ask()
    opt.tell(first.proposal_id, ConstrainedObservation("failed-engine", "failed"))
    pending = opt.ask()
    state = json.loads(json.dumps(opt.export_state(), allow_nan=False))
    assert state["proposals_issued"] == 2
    assert state["pending"]["proposal_id"] == pending.proposal_id
    assert state["observations"][0]["observation"]["status"] == "failed"
    assert state["observations"][0]["observation"]["utility"] is None
    assert len(state["proposal_diagnostics"]) == 2
    state["settings"]["bounds"]["x"][0] = 999
    assert opt.bounds["x"][0] == -2.0
    assert opt.best is None
