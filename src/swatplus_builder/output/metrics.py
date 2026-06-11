"""Hydrological performance signatures and timeseries diagnostics.

All functions operate on plain Python sequences (``list[float]`` or
``tuple[float, ...]``) so they work without NumPy — an agent or CLI can call
them immediately after a SWAT+ run using only the ``SwatPlusRun.summary``
values, or with daily timeseries loaded from ``output.reader``.

Functions
---------
nse(obs, sim)
    Nash–Sutcliffe Efficiency [-∞, 1].
kge(obs, sim)
    Kling–Gupta Efficiency [-∞, 1].
baseflow_index(daily_q)
    Baseflow index via the 2-pass Lyne–Hollick digital filter.
flow_duration_curve_quantiles(daily_q, quantiles)
    Exceedance-probability–discharge pairs at the requested quantiles.

All functions return ``float | dict[str, float]`` and are safe to
serialize to JSON for MCP / agent use.
"""

from __future__ import annotations

import math
from typing import Sequence

__all__ = [
    "nse",
    "kge",
    "kge_components",
    "pbias",
    "baseflow_index",
    "flow_duration_curve_quantiles",
]


def nse(obs: Sequence[float], sim: Sequence[float]) -> float:
    """Nash–Sutcliffe Efficiency.

    NSE = 1 - Σ(obs - sim)² / Σ(obs - mean(obs))²

    Args:
        obs: Observed discharge timeseries (any unit, same as ``sim``).
        sim: Simulated discharge timeseries, aligned day-for-day with ``obs``.

    Returns:
        NSE ∈ (-∞, 1]. Returns ``float('nan')`` if ``obs`` has zero
        variance (all observations identical).

    Raises:
        ValueError: ``obs`` and ``sim`` have different lengths or are empty.
    """
    obs, sim = list(obs), list(sim)
    _check_lengths(obs, sim, "nse")
    obs_mean = _mean(obs)
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - obs_mean) ** 2 for o in obs)
    if ss_tot == 0.0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def kge(obs: Sequence[float], sim: Sequence[float]) -> float:
    """Kling–Gupta Efficiency (Gupta et al. 2009).

    KGE = 1 - √[(r−1)² + (α−1)² + (β−1)²]

    where:
      - r = Pearson correlation coefficient
      - α = σ_sim / σ_obs  (variability ratio)
      - β = μ_sim / μ_obs  (bias ratio)

    Args:
        obs: Observed timeseries.
        sim: Simulated timeseries, same length and temporal alignment.

    Returns:
        KGE ∈ (-∞, 1]. Returns ``float('nan')`` if ``obs`` or ``sim``
        has zero standard deviation.

    Raises:
        ValueError: Lengths differ or either sequence is empty.
    """
    obs, sim = list(obs), list(sim)
    _check_lengths(obs, sim, "kge")

    obs_mean = _mean(obs)
    sim_mean = _mean(sim)
    obs_std = _std(obs, obs_mean)
    sim_std = _std(sim, sim_mean)

    if obs_std == 0.0 or sim_std == 0.0:
        return float("nan")

    # Pearson r
    r = _pearson_r(obs, sim, obs_mean, sim_mean, obs_std, sim_std)
    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean if obs_mean != 0.0 else float("nan")
    if math.isnan(beta):
        return float("nan")

    return 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def kge_components(obs: Sequence[float], sim: Sequence[float]) -> dict[str, float]:
    """Return KGE and its correlation, variability, and bias components."""
    obs, sim = list(obs), list(sim)
    _check_lengths(obs, sim, "kge_components")

    obs_mean = _mean(obs)
    sim_mean = _mean(sim)
    obs_std = _std(obs, obs_mean)
    sim_std = _std(sim, sim_mean)

    if obs_std == 0.0 or sim_std == 0.0 or obs_mean == 0.0:
        nan = float("nan")
        return {
            "method": "kge_2009_components",
            "kge": nan,
            "r": nan,
            "alpha": nan,
            "beta": nan,
            "correlation_deficit": nan,
            "variability_deficit": nan,
            "bias_deficit": nan,
        }

    r = _pearson_r(obs, sim, obs_mean, sim_mean, obs_std, sim_std)
    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean
    kge_value = 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return {
        "method": "kge_2009_components",
        "kge": float(kge_value),
        "r": float(r),
        "alpha": float(alpha),
        "beta": float(beta),
        "correlation_deficit": float(abs(r - 1.0)),
        "variability_deficit": float(abs(alpha - 1.0)),
        "bias_deficit": float(abs(beta - 1.0)),
    }


def pbias(obs: Sequence[float], sim: Sequence[float]) -> float:
    """Percent bias of simulated flow relative to observed flow.

    Positive values indicate simulated volume is higher than observed volume.
    """
    obs, sim = list(obs), list(sim)
    _check_lengths(obs, sim, "pbias")
    obs_sum = sum(obs)
    if obs_sum == 0.0:
        return float("nan")
    return 100.0 * (sum(sim) - obs_sum) / obs_sum


def baseflow_index(daily_q: Sequence[float], alpha: float = 0.925) -> float:
    """Baseflow index via the Lyne–Hollick recursive digital filter.

    Two forward passes of the standard 1-parameter filter:

        q_fast[t] = α·q_fast[t-1] + 0.5·(1+α)·(Q[t] - Q[t-1])
        q_base[t] = Q[t] - max(q_fast[t], 0)

    Args:
        daily_q: Daily total streamflow timeseries (m³/s or mm/day; same
            unit throughout).
        alpha: Filter parameter controlling the proportion of quickflow
            separated. Typical values 0.9–0.975. Default 0.925 follows
            the WMS baseflow separation convention.

    Returns:
        Baseflow index ∈ [0, 1]: total baseflow / total streamflow.
        Returns ``float('nan')`` if total streamflow is zero.

    Raises:
        ValueError: ``daily_q`` is empty.
    """
    Q = list(daily_q)
    if not Q:
        raise ValueError("baseflow_index: daily_q must not be empty")

    def _one_pass(q: list[float]) -> list[float]:
        qf = [0.0] * len(q)
        for t in range(1, len(q)):
            qf[t] = alpha * qf[t - 1] + 0.5 * (1 + alpha) * (q[t] - q[t - 1])
        return [max(q[t] - max(qf[t], 0.0), 0.0) for t in range(len(q))]

    # Forward pass
    bf1 = _one_pass(Q)
    # Reverse pass for two-pass symmetry
    bf2 = list(reversed(_one_pass(list(reversed(bf1)))))

    total_q = sum(Q)
    total_bf = sum(bf2)
    if total_q == 0.0:
        return float("nan")
    return min(1.0, total_bf / total_q)


def flow_duration_curve_quantiles(
    daily_q: Sequence[float],
    quantiles: Sequence[float] = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95),
) -> dict[str, float]:
    """Compute flow exceedance values at the requested probability quantiles.

    A flow duration curve (FDC) maps exceedance probability P to the flow
    exceeded P-fraction of the time. This function returns the specific
    discharge values at the caller-supplied exceedance probabilities.

    Args:
        daily_q: Daily streamflow timeseries (any consistent unit).
        quantiles: Exceedance probabilities in (0, 1). Default is a
            seven-point characterisation used in HESS and Hydrol. Earth
            Syst. Sci. papers (Q5 through Q95).

    Returns:
        Dict ``{"Q{int(p*100)}": discharge_value}`` — e.g.
        ``{"Q5": 12.3, "Q50": 3.1, "Q95": 0.4}``.

    Raises:
        ValueError: ``daily_q`` is empty or any quantile is outside (0, 1).
    """
    Q = sorted(daily_q, reverse=True)
    n = len(Q)
    if n == 0:
        raise ValueError("flow_duration_curve_quantiles: daily_q must not be empty")
    for p in quantiles:
        if not (0.0 < p < 1.0):
            raise ValueError(
                f"flow_duration_curve_quantiles: quantile {p} must be in (0, 1)"
            )
    result: dict[str, float] = {}
    for p in quantiles:
        # Linear interpolation on the sorted descending array
        idx_f = p * (n - 1)
        lo = int(idx_f)
        hi = min(lo + 1, n - 1)
        frac = idx_f - lo
        value = Q[lo] * (1 - frac) + Q[hi] * frac
        key = f"Q{int(round(p * 100))}"
        result[key] = float(value)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_lengths(obs: list, sim: list, fn: str) -> None:
    if len(obs) != len(sim):
        raise ValueError(
            f"{fn}: obs (len={len(obs)}) and sim (len={len(sim)}) must have the same length"
        )
    if len(obs) == 0:
        raise ValueError(f"{fn}: obs and sim must not be empty")


def _mean(seq: list[float]) -> float:
    return sum(seq) / len(seq)


def _std(seq: list[float], mean: float) -> float:
    return math.sqrt(sum((x - mean) ** 2 for x in seq) / len(seq))


def _pearson_r(
    obs: list[float],
    sim: list[float],
    obs_mean: float,
    sim_mean: float,
    obs_std: float,
    sim_std: float,
) -> float:
    n = len(obs)
    cov = sum((obs[i] - obs_mean) * (sim[i] - sim_mean) for i in range(n)) / n
    return cov / (obs_std * sim_std)
