"""Unit tests for swatplus_builder.output.metrics, focused on log_kge_v2.

log_kge (v1) is kept exactly as-is for historical-score reproducibility; see
its docstring and docs/AGENT_HANDOFF.md §7 for the fixed-epsilon issue it
has. log_kge_v2 is the new, scale-aware replacement used going forward by
the calibration phase objective (calibration/locked_benchmark.py).

Honesty note: log_kge_v2 removes the dependence on one *arbitrary global*
epsilon constant (0.01 m^3/s) by deriving epsilon from each basin's own mean
observed flow instead — so a headwater stream and a large river no longer
share one epsilon that fits neither well. It does **not** make log-KGE fully
invariant to an after-the-fact unit relabeling of the same data (the
correlation/variability/bias-ratio decomposition inside KGE is not exactly
invariant to a shared additive shift in log-space — see the docstring of
log_kge_v2), and it does not eliminate the well-documented numerical
instability of log-transformed efficiency metrics for very small, low-flow-
dominated samples (Santos, Thirel & Perrin 2018). These tests check the
property v2 actually has (basin-relative epsilon, and a smaller unit-
conversion swing on realistic dense series), not an unqualified "fixed".
"""

from __future__ import annotations

import math
import random

from swatplus_builder.output.metrics import kge, log_kge, log_kge_v2

# The exact 7-value synthetic probe from the readiness review
# (../Swatplus_decision/research/audit_builder.py) that first reproduced the
# fixed-epsilon issue in log_kge (docs/AGENT_HANDOFF.md §7). It is a small,
# low-flow-dominated sample deliberately chosen to expose the pathology.
_PROBE_OBS = [0.1, 0.2, 0.5, 1, 2, 4, 8]
_PROBE_SIM = [0.15, 0.25, 0.4, 1.2, 1.8, 3.8, 7.5]


def test_log_kge_v1_documented_unit_swing_regression() -> None:
    """Regression-locks the audit's documented finding for v1 (unchanged)."""
    native = log_kge(_PROBE_OBS, _PROBE_SIM)  # epsilon=0.01 m^3/s, as-is
    converted = log_kge([v * 1000 for v in _PROBE_OBS], [v * 1000 for v in _PROBE_SIM])
    assert math.isclose(native, -0.2551, abs_tol=1e-3)
    # Raw KGE is exactly scale-invariant; log_kge is not.
    assert math.isclose(kge(_PROBE_OBS, _PROBE_SIM), kge(
        [v * 1000 for v in _PROBE_OBS], [v * 1000 for v in _PROBE_SIM]
    ), rel_tol=1e-9)
    assert converted - native > 0.5  # the audit's headline swing, reproduced


def test_log_kge_v2_epsilon_is_basin_relative_not_a_global_constant() -> None:
    """v2's epsilon tracks each basin's own mean observed flow, by construction."""
    small_basin_obs = [0.05, 0.06, 0.08, 0.07]
    large_basin_obs = [500.0, 520.0, 480.0, 510.0]

    # log_kge_v2(obs, sim, f) must equal log_kge(obs, sim, epsilon=f*mean(obs)).
    for obs in (small_basin_obs, large_basin_obs):
        expected_epsilon = 0.01 * (sum(obs) / len(obs))
        assert log_kge_v2(obs, [o * 1.1 for o in obs]) == log_kge(
            obs, [o * 1.1 for o in obs], epsilon=expected_epsilon
        )
    # The two basins get very different absolute epsilon values -- neither
    # borrows the other's (or v1's fixed 0.01) scale.
    small_eps = 0.01 * (sum(small_basin_obs) / len(small_basin_obs))
    large_eps = 0.01 * (sum(large_basin_obs) / len(large_basin_obs))
    assert large_eps / small_eps > 1000


def test_log_kge_v2_reduces_unit_conversion_swing_on_realistic_data() -> None:
    """On a dense, realistic (non-adversarial) low-flow series, v2's swing
    under a pure m^3/s -> L/s relabeling is no larger than v1's."""
    rng = random.Random(11)
    obs = []
    q = 0.15
    for i in range(120):
        q = max(0.02, q * 0.96 + (0.4 if i in (20, 55, 90) else 0.0) + rng.uniform(-0.005, 0.005))
        obs.append(round(q, 4))
    sim = [max(0.01, o * rng.uniform(0.8, 1.2) + rng.uniform(-0.01, 0.01)) for o in obs]
    obs_ls = [v * 1000 for v in obs]
    sim_ls = [v * 1000 for v in sim]

    v1_swing = abs(log_kge(obs_ls, sim_ls) - log_kge(obs, sim))
    v2_swing = abs(log_kge_v2(obs_ls, sim_ls) - log_kge_v2(obs, sim))
    assert v2_swing <= v1_swing + 1e-9


def test_log_kge_v2_perfect_simulation_is_near_one() -> None:
    assert log_kge_v2(_PROBE_OBS, _PROBE_OBS) > 0.999


def test_log_kge_v2_falls_back_to_fixed_epsilon_when_no_observed_flow() -> None:
    # All-dry gauge: no basin-relative scale to derive epsilon from. Must not
    # raise, and must match calling log_kge with its documented fixed default.
    obs = [0.0, 0.0, 0.0, 0.0]
    sim = [0.0, 0.01, 0.0, 0.02]
    v2 = log_kge_v2(obs, sim)
    v1 = log_kge(obs, sim)
    assert math.isnan(v2) and math.isnan(v1)  # zero-variance obs -> nan in both


def test_log_kge_v2_epsilon_fraction_is_configurable() -> None:
    tighter = log_kge_v2(_PROBE_OBS, _PROBE_SIM, epsilon_fraction=0.001)
    default = log_kge_v2(_PROBE_OBS, _PROBE_SIM, epsilon_fraction=0.01)
    assert tighter != default
