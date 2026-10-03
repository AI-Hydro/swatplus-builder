"""Scientific contracts for opt-in unit-stable calibration objectives."""

import math

import pytest

from swatplus_builder.calibration.objective_policy import (
    ConstraintResidual,
    MetricContext,
    ObjectiveEvaluation,
    ObjectivePolicy,
)
from swatplus_builder.output.metrics import log_kge_v2, log_nse, nse, sqrt_nse

OBS = [0.1, 0.2, 0.5, 1, 2, 4, 8]
SIM = [0.15, 0.25, 0.4, 1.2, 1.8, 3.8, 7.5]


@pytest.mark.parametrize("factor", [1e-9, 1e-3, 1e3, 1e9])
def test_transformed_nse_and_policy_are_unit_invariant(factor):
    scaled_obs = [v * factor for v in OBS]
    scaled_sim = [v * factor for v in SIM]
    assert sqrt_nse(OBS, SIM) == pytest.approx(sqrt_nse(scaled_obs, scaled_sim), abs=1e-12)
    assert log_nse(OBS, SIM, epsilon=0.01) == pytest.approx(
        log_nse(scaled_obs, scaled_sim, epsilon=0.01 * factor), abs=1e-12,
    )
    original = ObjectivePolicy.fit(OBS, weights={"kge": 2, "log_nse": 1}, epsilon_fraction=0.01)
    converted = ObjectivePolicy.fit(scaled_obs, weights={"kge": 2, "log_nse": 1}, epsilon_fraction=0.01)
    assert original.evaluate(OBS, SIM).utility == pytest.approx(
        converted.evaluate(scaled_obs, scaled_sim).utility, abs=1e-12,
    )
    assert original.sha256 != converted.sha256  # Input/epsilon identities remain distinct.


def test_log_nse_matches_standard_definition_and_retains_zero_flows():
    observed, simulated, epsilon = [0, 0.2, 2, 4], [0.1, 0.3, 1.8, 4], 0.01
    expected = nse([math.log(v + epsilon) for v in observed],
                   [math.log(v + epsilon) for v in simulated])
    assert log_nse(observed, simulated, epsilon=epsilon) == pytest.approx(expected)
    assert sqrt_nse(observed, observed) == 1
    assert log_nse(observed, observed, epsilon=epsilon) == 1


@pytest.mark.parametrize("observed", [[0, 0], [1, 1]])
def test_constant_observations_are_explicitly_undefined(observed):
    assert math.isnan(sqrt_nse(observed, observed))
    assert math.isnan(log_nse(observed, observed, epsilon=0.01))
    policy = ObjectivePolicy.fit(observed, weights={"sqrt_nse": 1})
    evaluation = policy.evaluate(observed, observed)
    assert evaluation.status == "invalid"
    assert evaluation.utility is None
    assert not evaluation.feasible


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_invalid_discharge_is_not_clipped(bad):
    with pytest.raises(ValueError):
        sqrt_nse([0, 1], [bad, 1])
    with pytest.raises(ValueError):
        log_nse([0, 1], [bad, 1], epsilon=0.01)
    policy = ObjectivePolicy.fit([0, 1], weights={"sqrt_nse": 1})
    assert policy.evaluate([0, 1], [bad, 1]).status == "invalid"


@pytest.mark.parametrize("epsilon", [0, -1, float("nan"), float("inf")])
def test_invalid_offset_rejected(epsilon):
    with pytest.raises(ValueError):
        log_nse(OBS, SIM, epsilon=epsilon)


@pytest.mark.parametrize("weights", [{}, {"unknown": 1}, {"nse": -1}, {"nse": 0}, {"nse": float("nan")}])
def test_explicit_valid_weights_required(weights):
    with pytest.raises(ValueError):
        ObjectivePolicy.fit(OBS, weights=weights)


def test_log_policy_cannot_invent_scale_for_all_dry_training():
    with pytest.raises(ValueError, match="offset"):
        ObjectivePolicy.fit([0, 0], weights={"log_nse": 1}, epsilon_fraction=0.01)
    with pytest.raises(ValueError, match="explicit"):
        ObjectivePolicy.fit(OBS, weights={"log_nse": 1})


def test_training_identity_and_precomputed_context_are_enforced():
    policy = ObjectivePolicy.fit(OBS, weights={"sqrt_nse": 1})
    assert policy.evaluate(OBS[:-1], SIM[:-1]).status == "invalid"
    assert policy.evaluate_metrics({"sqrt_nse": 1}, context=MetricContext("other", "other", None)).status == "invalid"
    assert policy.evaluate_metrics({}, context=policy.context).status == "invalid"
    assert policy.evaluate_metrics({"sqrt_nse": float("nan")}, context=policy.context).status == "invalid"
    assert policy.evaluate_metrics({"sqrt_nse": 0.9}, context=policy.context).utility == 0.9
    assert policy.sha256 == ObjectivePolicy.fit(OBS, weights={"sqrt_nse": 1}).sha256


def test_frozen_epsilon_required_for_precomputed_metrics():
    policy = ObjectivePolicy.fit(OBS, weights={"log_nse": 1}, epsilon_fraction=0.01)
    wrong = MetricContext(policy.sha256, policy.training_observation_sha256, policy.epsilon * 2)
    assert policy.evaluate_metrics({"log_nse": 1}, context=wrong).status == "invalid"


def test_constraints_are_separate_from_finite_utility():
    policy = ObjectivePolicy.fit(OBS, weights={"sqrt_nse": 1})
    violated = ConstraintResidual("user_process_policy", 0.1, "process_policy")
    evaluation = policy.evaluate(OBS, SIM, constraints=[violated])
    assert evaluation.status == "valid" and math.isfinite(evaluation.utility)
    assert not evaluation.feasible
    unresolved = ConstraintResidual("missing_et", None, "integrity")
    assert policy.evaluate(OBS, SIM, constraints=[unresolved]).status == "invalid"
    assert policy.evaluate(OBS, SIM, constraints=[violated, violated]).status == "invalid"
    with pytest.raises(ValueError):
        ConstraintResidual("invalid", float("nan"), "integrity")


def test_historical_log_kge_counterexample_remains_unchanged():
    # New policy does not rewrite the legacy score or its scientific history.
    assert log_kge_v2(OBS, SIM) == pytest.approx(-4.867350124, abs=1e-8)
    assert log_kge_v2([v * 1000 for v in OBS], [v * 1000 for v in SIM]) == pytest.approx(0.9216636305)


def test_log_nse_handles_finite_extreme_ratios_without_overflow():
    value = log_nse([0, 1e308, 1], [0, 1e307, 1], epsilon=1e-300)
    assert math.isfinite(value)


@pytest.mark.parametrize("observed,simulated", [([], []), ([0, 1], [1])])
def test_missing_or_misaligned_samples_rejected(observed, simulated):
    with pytest.raises(ValueError):
        sqrt_nse(observed, simulated)
    with pytest.raises(ValueError):
        log_nse(observed, simulated, epsilon=0.01)


def test_undefined_selected_metric_is_invalid_not_neutral():
    policy = ObjectivePolicy.fit(OBS, weights={"kge": 1, "sqrt_nse": 1})
    result = policy.evaluate(OBS, [1] * len(OBS))
    assert result.status == "invalid" and result.utility is None
    assert "non_finite_metric:kge" in result.reasons
    # A metric with zero weight is explicitly excluded, not required.
    policy = ObjectivePolicy.fit(OBS, weights={"kge": 0, "sqrt_nse": 1})
    assert policy.evaluate(OBS, [1] * len(OBS)).status == "valid"


def test_overflowing_total_weights_rejected():
    with pytest.raises(ValueError, match="Total objective weight"):
        ObjectivePolicy.fit(OBS, weights={"kge": 1e308, "sqrt_nse": 1e308})


def test_evaluation_components_are_copied_and_read_only():
    policy = ObjectivePolicy.fit(OBS, weights={"sqrt_nse": 1})
    source = {"sqrt_nse": 0.9}
    result = ObjectiveEvaluation("valid", 0.9, source, (), (), policy.context)
    source["sqrt_nse"] = float("nan")
    assert result.components["sqrt_nse"] == 0.9
    with pytest.raises(TypeError):
        result.components["sqrt_nse"] = float("nan")
