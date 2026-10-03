"""Opt-in, versioned objectives for exact calibration experiments.

No production objective or gate defaults are changed here. Weights and process
constraints belong to an explicit experiment. The training observation digest
and frozen log offset prevent accidental reuse of withheld or legacy metrics.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from ..output.metrics import kge, log_nse, nse, sqrt_nse

POLICY_VERSION = "training_transformed_nse_v1"
_METRICS = {"kge", "nse", "sqrt_nse", "log_nse"}


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _observations(values: Sequence[float]) -> tuple[float, ...]:
    try:
        result = tuple(float(v) for v in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Training observations must be finite nonnegative discharge.") from exc
    if not result or any(not math.isfinite(v) or v < 0 for v in result):
        raise ValueError("Training observations must be nonempty, finite and nonnegative.")
    return result


@dataclass(frozen=True)
class MetricContext:
    """Identity that an exact-output adapter must preserve with its metrics."""

    policy_sha256: str
    training_observation_sha256: str
    epsilon: float | None


@dataclass(frozen=True)
class ConstraintResidual:
    """A named constraint: residual <= 0 passes; None means unevaluated.

    Residual normalization/units must be chosen and documented by the caller.
    No ET/P, skill, or conservation thresholds are introduced by this type.
    """

    name: str
    residual: float | None
    kind: Literal["integrity", "process_policy"]

    def __post_init__(self) -> None:
        if not self.name or self.kind not in {"integrity", "process_policy"}:
            raise ValueError("A constraint needs a name and a recognized kind.")
        if self.residual is not None and not math.isfinite(self.residual):
            raise ValueError("Constraint residuals must be finite or explicitly unevaluated.")


@dataclass(frozen=True)
class ObjectiveEvaluation:
    status: Literal["valid", "invalid"]
    utility: float | None
    components: Mapping[str, float]
    constraints: tuple[ConstraintResidual, ...]
    reasons: tuple[str, ...]
    context: MetricContext

    def __post_init__(self) -> None:
        if self.status not in {"valid", "invalid"}:
            raise ValueError("Unknown objective evaluation status.")
        if self.status == "valid" and (
            self.utility is None or not math.isfinite(self.utility)
        ):
            raise ValueError("A valid objective must have a finite utility.")
        if self.status == "invalid" and self.utility is not None:
            raise ValueError("An invalid objective cannot carry a utility.")
        components = dict(self.components)
        if any(not math.isfinite(v) for v in components.values()):
            raise ValueError("Objective components must be finite.")
        object.__setattr__(self, "components", MappingProxyType(components))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "reasons", tuple(self.reasons))

    @property
    def feasible(self) -> bool:
        return self.status == "valid" and all(
            c.residual is not None and c.residual <= 0 for c in self.constraints
        )


@dataclass(frozen=True)
class ObjectivePolicy:
    """Explicit nonnegative weighted utility, fitted to training observations.

    Utility is sum(weight * metric) / sum(weight). There are no default metric
    weights. Only metrics with a positive weight are required. Calibration
    utilities are separate from claim gates and do not certify model adequacy.
    """

    weights: tuple[tuple[str, float], ...]
    training_observation_sha256: str
    training_sample_count: int
    epsilon_fraction: float | None
    epsilon: float | None
    version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        names = [name for name, _weight in self.weights]
        if (not names or len(set(names)) != len(names)
                or any(name not in _METRICS for name in names)):
            raise ValueError("Policy weights must have unique supported metric names.")
        if any(not math.isfinite(w) or w <= 0 for _, w in self.weights):
            raise ValueError("Stored metric weights must be finite and positive.")
        try:
            total_weight = math.fsum(w for _, w in self.weights)
        except OverflowError as exc:
            raise ValueError("Total objective weight must be finite.") from exc
        if not math.isfinite(total_weight):
            raise ValueError("Total objective weight must be finite.")
        if self.version != POLICY_VERSION or self.training_sample_count < 1:
            raise ValueError("Invalid objective version or training sample count.")
        if (len(self.training_observation_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.training_observation_sha256)):
            raise ValueError("Invalid training observation digest.")
        if "log_nse" in names:
            if (self.epsilon is None or self.epsilon_fraction is None
                    or not math.isfinite(self.epsilon) or self.epsilon <= 0
                    or not math.isfinite(self.epsilon_fraction) or self.epsilon_fraction <= 0):
                raise ValueError("Log-NSE needs a finite positive frozen training offset.")
        elif self.epsilon is not None or self.epsilon_fraction is not None:
            raise ValueError("An offset is only permitted with log-NSE.")

    @classmethod
    def fit(
        cls, observed_training: Sequence[float], *, weights: Mapping[str, float],
        epsilon_fraction: float | None = None,
    ) -> ObjectivePolicy:
        """Seal observations and derive epsilon without examining simulations.

        The caller must supply only aligned calibration-period observations.
        Temporal dates and other experiment inputs should also be sealed in the
        benchmark manifest. All-zero observations cannot define a log offset.
        """
        observed = _observations(observed_training)
        if any(name not in _METRICS for name in weights):
            raise ValueError("Unsupported objective metric.")
        converted = {name: float(weight) for name, weight in weights.items()}
        if any(not math.isfinite(w) or w < 0 for w in converted.values()):
            raise ValueError("Weights must be finite and nonnegative.")
        active = tuple(sorted((name, w) for name, w in converted.items() if w > 0))
        epsilon = None
        if any(name == "log_nse" for name, _ in active):
            if epsilon_fraction is None:
                raise ValueError("Supply an explicit epsilon_fraction for log-NSE.")
            epsilon_fraction = float(epsilon_fraction)
            if not math.isfinite(epsilon_fraction) or epsilon_fraction <= 0:
                raise ValueError("epsilon_fraction must be finite and positive.")
            # Dividing before summation avoids overflow for finite large flows.
            epsilon = epsilon_fraction * math.fsum(v / len(observed) for v in observed)
        elif epsilon_fraction is not None:
            raise ValueError("An epsilon_fraction without log-NSE is not used.")
        return cls(active, _digest(observed), len(observed), epsilon_fraction, epsilon)

    @property
    def sha256(self) -> str:
        return _digest({
            "version": self.version, "weights": self.weights,
            "training_observation_sha256": self.training_observation_sha256,
            "training_sample_count": self.training_sample_count,
            "epsilon_fraction": self.epsilon_fraction, "epsilon": self.epsilon,
        })

    @property
    def context(self) -> MetricContext:
        return MetricContext(self.sha256, self.training_observation_sha256, self.epsilon)

    def evaluate(
        self, observed_training: Sequence[float], simulated_training: Sequence[float], *,
        constraints: Sequence[ConstraintResidual] = (),
    ) -> ObjectiveEvaluation:
        """Score this exact training series; reject changed/withheld observations."""
        residuals = tuple(constraints)
        try:
            observed = _observations(observed_training)
            simulated = _observations(simulated_training)
            if _digest(observed) != self.training_observation_sha256:
                raise ValueError("observations_do_not_match_training_context")
            if len(simulated) != self.training_sample_count:
                raise ValueError("simulation_does_not_match_training_length")
            metrics: dict[str, float] = {}
            functions = {"nse": nse, "kge": kge, "sqrt_nse": sqrt_nse}
            for name, _ in self.weights:
                if name == "log_nse":
                    assert self.epsilon is not None
                    metrics[name] = log_nse(observed, simulated, epsilon=self.epsilon)
                else:
                    metrics[name] = functions[name](observed, simulated)
        except (ValueError, TypeError, OverflowError) as exc:
            return self._invalid((str(exc),), residuals)
        return self.evaluate_metrics(metrics, context=self.context, constraints=residuals)

    def evaluate_metrics(
        self, metrics: Mapping[str, float], *, context: MetricContext,
        constraints: Sequence[ConstraintResidual] = (),
    ) -> ObjectiveEvaluation:
        """Score precomputed exact metrics with their adapter-bound context.

        A caller must attest that log-NSE used this policy's exact frozen epsilon
        and observation alignment. Context identity is necessary, not proof of
        adapter correctness; it must be bound to the exact-output receipt. A
        legacy metric dictionary alone is intentionally insufficient.
        """
        residuals = tuple(constraints)
        if context != self.context:
            return self._invalid(("metric_context_mismatch",), residuals)
        if len({c.name for c in residuals}) != len(residuals):
            return self._invalid(("duplicate_constraint_names",), residuals)
        reasons = [f"unevaluated_constraint:{c.name}" for c in residuals if c.residual is None]
        components: dict[str, float] = {}
        for name, _weight in self.weights:
            try:
                value = float(metrics[name])
            except (KeyError, TypeError, ValueError, OverflowError):
                reasons.append(f"missing_or_invalid_metric:{name}")
                continue
            if not math.isfinite(value):
                reasons.append(f"non_finite_metric:{name}")
            else:
                components[name] = value
        if reasons:
            return self._invalid(tuple(reasons), residuals, components)
        total = math.fsum(weight for _, weight in self.weights)
        try:
            utility = math.fsum((weight / total) * components[name] for name, weight in self.weights)
        except OverflowError:
            return self._invalid(("non_finite_utility",), residuals, components)
        if not math.isfinite(utility):
            return self._invalid(("non_finite_utility",), residuals, components)
        return ObjectiveEvaluation("valid", utility, components, residuals, (), self.context)

    def _invalid(
        self, reasons: tuple[str, ...], constraints: tuple[ConstraintResidual, ...],
        components: dict[str, float] | None = None,
    ) -> ObjectiveEvaluation:
        return ObjectiveEvaluation("invalid", None, components or {}, constraints, reasons, self.context)
