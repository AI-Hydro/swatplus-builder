"""Opt-in serial constrained GP challenger; never substitutes predictions for runs.

The proposal budget counts ask/tell evaluations, including failed runs. Screening
and final verification must be reserved by the caller's workflow ledger. GP code
uses the documented BoTorch SCBO posterior-sampling API (v0.17.0 tutorial:
https://botorch.org/docs/v0.17.0/tutorials/scalable_constrained_bo).
"""

from __future__ import annotations

import math
import random
import time
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


class SurrogateDependencyError(RuntimeError):
    """The explicitly requested GP backend is unavailable."""


@dataclass(frozen=True)
class ConstrainedObservation:
    """An evaluator's measured utility and complete residuals (feasible <= 0)."""

    evaluation_id: str
    status: Literal["success", "failed", "timeout"]
    utility: float | None = None
    constraints: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ValueError("An engine evaluation ID is required")
        if self.status not in {"success", "failed", "timeout"}:
            raise ValueError("Unknown evaluation status")
        values = dict(self.constraints or {})
        if self.status == "success":
            if self.utility is None or not math.isfinite(self.utility):
                raise ValueError("Successful observations require finite utility")
            if not all(math.isfinite(v) for v in values.values()):
                raise ValueError("Constraint residuals must be finite")
        elif self.utility is not None or values:
            raise ValueError("Failed runs cannot supply synthetic numeric targets")
        object.__setattr__(self, "constraints", MappingProxyType(values))


@dataclass(frozen=True)
class SurrogateProposal:
    proposal_id: int
    parameters: Mapping[str, float]
    method: str


@dataclass(frozen=True)
class MeasuredCandidate:
    proposal: SurrogateProposal
    observation: ConstrainedObservation

    @property
    def admissible(self) -> bool:
        return self.observation.status == "success" and all(
            v <= 0 for v in self.observation.constraints.values()
        )


@dataclass(frozen=True)
class ProposalDiagnostics:
    proposal_id: int
    status: Literal["proposed", "error"]
    method: str
    total_seconds: float
    fit_seconds: float
    candidate_generation_seconds: float
    sampling_seconds: float
    finite_training_observations: int
    warnings: tuple[str, ...]
    error: str | None = None

    def to_json(self) -> dict:
        """Return JSON-safe primitives; not a serialized JSON string."""
        return {
            "proposal_id": self.proposal_id,
            "status": self.status,
            "method": self.method,
            "total_seconds": self.total_seconds,
            "fit_seconds": self.fit_seconds,
            "candidate_generation_seconds": self.candidate_generation_seconds,
            "sampling_seconds": self.sampling_seconds,
            "finite_training_observations": self.finite_training_observations,
            "warnings": list(self.warnings),
            "error": self.error,
        }


class ConstrainedGPOptimizer:
    """Seeded ask/tell search with small initial design and one pending proposal.

    Utility is maximized. Missing optional dependencies raise by default;
    ``missing_dependency='random'`` permits an explicitly labeled random arm.
    This is a single-region GP challenger, not a full SCBO implementation.
    """

    def __init__(
        self,
        bounds: Mapping[str, tuple[float, float]],
        constraint_names: tuple[str, ...],
        *,
        budget: int,
        initial_design_size: int = 8,
        seed: int = 42,
        candidate_pool_size: int = 256,
        missing_dependency: Literal["raise", "random"] = "raise",
        initial_points: Sequence[Mapping[str, float]] | None = None,
        diagnostics_callback: Callable[[ProposalDiagnostics], None] | None = None,
    ) -> None:
        for name, value in (
            ("budget", budget),
            ("initial_design_size", initial_design_size),
            ("candidate_pool_size", candidate_pool_size),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer, not a boolean or fraction")
        if not bounds or any(not math.isfinite(v) for pair in bounds.values() for v in pair):
            raise ValueError("Finite nonempty bounds are required")
        if any(lo >= hi for lo, hi in bounds.values()):
            raise ValueError("Every lower bound must be below its upper bound")
        if (
            not constraint_names
            or not all(n.strip() for n in constraint_names)
            or len(set(constraint_names)) != len(constraint_names)
        ):
            raise ValueError("Declare distinct required constraint names")
        if budget < 1 or not 1 <= initial_design_size <= budget:
            raise ValueError("Initial design must fit the positive proposal budget")
        if candidate_pool_size < 2:
            raise ValueError("Candidate pool must contain at least two points")
        if missing_dependency not in {"raise", "random"}:
            raise ValueError("Unknown missing dependency policy")
        self.names = tuple(sorted(bounds))
        self.bounds = MappingProxyType(dict(bounds))
        self.constraint_names = constraint_names
        self.budget = budget
        self.seed = seed
        self.candidate_pool_size = candidate_pool_size
        self.missing_dependency = missing_dependency
        self._rng = random.Random(seed)
        self._design = self._latin_design(initial_design_size)
        self._initial_method = "initial_latin_design"
        if initial_points is not None:
            self._initial_method = "initial_shared_design"
            if len(initial_points) != initial_design_size:
                raise ValueError("Shared initial points must match initial_design_size")
            self._design = [self.normalize(p) for p in initial_points]
            if len(set(self._design)) != len(self._design):
                raise ValueError("Shared initial points must be distinct")
        self._records: list[MeasuredCandidate] = []
        self._pending: SurrogateProposal | None = None
        self._issued = 0
        self.trust_region_length = 0.8
        self._successes = 0
        self._failures = 0
        self.diagnostics_callback = diagnostics_callback
        self._diagnostics: list[ProposalDiagnostics] = []
        self._active_timings: dict[str, float] = {}

    def _latin_design(self, size: int) -> list[tuple[float, ...]]:
        columns = []
        for _ in self.names:
            strata = list(range(size))
            self._rng.shuffle(strata)
            columns.append([(j + self._rng.random()) / size for j in strata])
        return [tuple(col[i] for col in columns) for i in range(size)]

    def normalize(self, parameters: Mapping[str, float]) -> tuple[float, ...]:
        if set(parameters) != set(self.names):
            raise ValueError("Parameter keys must match the search bounds")
        values = []
        for name in self.names:
            value = parameters[name]
            lo, hi = self.bounds[name]
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"Parameter {name} is non-finite or outside bounds")
            values.append((value - lo) / (hi - lo))
        return tuple(values)

    def _parameters(self, unit: tuple[float, ...]) -> Mapping[str, float]:
        return MappingProxyType(
            {
                n: self.bounds[n][0] + u * (self.bounds[n][1] - self.bounds[n][0])
                for n, u in zip(self.names, unit, strict=True)
            }
        )

    @property
    def observations(self) -> tuple[MeasuredCandidate, ...]:
        return tuple(self._records)

    @property
    def proposals_issued(self) -> int:
        return self._issued

    @property
    def best(self) -> MeasuredCandidate | None:
        valid = [r for r in self._records if r.admissible]
        return max(valid, key=lambda r: r.observation.utility) if valid else None

    @property
    def proposal_diagnostics(self) -> tuple[ProposalDiagnostics, ...]:
        return tuple(self._diagnostics)

    def ask(self) -> SurrogateProposal:
        if self._pending is not None:
            raise RuntimeError("Tell the pending evaluation before asking again")
        if self._issued >= self.budget:
            raise StopIteration("Proposal budget exhausted")
        proposal_id = self._issued
        started = time.perf_counter()
        self._active_timings = {"fit": 0.0, "generation": 0.0, "sampling": 0.0}
        proposal = None
        error = None
        with warnings.catch_warnings(record=True) as captured:
            try:
                proposal = self._ask()
                return proposal
            except BaseException as exc:
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                diagnostics = ProposalDiagnostics(
                    proposal_id=proposal_id,
                    status="proposed" if proposal is not None else "error",
                    method=proposal.method if proposal is not None else "proposal_error",
                    total_seconds=time.perf_counter() - started,
                    fit_seconds=self._active_timings["fit"],
                    candidate_generation_seconds=self._active_timings["generation"],
                    sampling_seconds=self._active_timings["sampling"],
                    finite_training_observations=sum(
                        r.observation.status == "success" for r in self._records
                    ),
                    warnings=tuple(f"{w.category.__name__}: {w.message}" for w in captured),
                    error=error,
                )
                self._diagnostics.append(diagnostics)
                if self.diagnostics_callback is not None:
                    self.diagnostics_callback(diagnostics)

    def _ask(self) -> SurrogateProposal:
        if self._pending is not None:
            raise RuntimeError("Tell the pending evaluation before asking again")
        if self._issued >= self.budget:
            raise StopIteration("Proposal budget exhausted")
        if self._issued < len(self._design):
            unit = self._design[self._issued]
            method = self._initial_method
        else:
            measured = [r for r in self._records if r.observation.status == "success"]
            if len(measured) < 2:
                unit = self._random_unique()
                method = "random_insufficient_finite_observations"
            else:
                try:
                    unit = self._gp_proposal(measured)
                    method = "constrained_gp_thompson"
                except SurrogateDependencyError:
                    if self.missing_dependency == "raise":
                        raise
                    unit = self._random_unique()
                    method = "random_missing_gp_dependency"
        parameters = self._parameters(unit)
        self.normalize(parameters)
        proposal = SurrogateProposal(self._issued, parameters, method)
        self._pending = proposal
        self._issued += 1
        return proposal

    def export_state(self) -> dict:
        """Export JSON-safe search state for the caller's sealed-context checkpoint.

        This is not a standalone resume authorization: the caller must bind the
        snapshot to immutable engine/input/objective context and resolve any
        pending invocation before replay. GP models are refitted from measured
        observations; they are not serialized here.
        """

        def proposal_json(proposal):
            return {
                "proposal_id": proposal.proposal_id,
                "parameters": dict(proposal.parameters),
                "method": proposal.method,
            }

        rng = self._rng.getstate()
        return {
            "schema_version": 1,
            "settings": {
                "bounds": {n: list(pair) for n, pair in self.bounds.items()},
                "constraint_names": list(self.constraint_names),
                "budget": self.budget,
                "seed": self.seed,
                "candidate_pool_size": self.candidate_pool_size,
                "missing_dependency": self.missing_dependency,
            },
            "initial_method": self._initial_method,
            "initial_normalized_design": [list(point) for point in self._design],
            "proposals_issued": self._issued,
            "pending": proposal_json(self._pending) if self._pending is not None else None,
            "rng_state": [rng[0], list(rng[1]), rng[2]],
            "trust_region": {
                "length": self.trust_region_length,
                "successes": self._successes,
                "failures": self._failures,
            },
            "observations": [
                {
                    "proposal": proposal_json(r.proposal),
                    "observation": {
                        "evaluation_id": r.observation.evaluation_id,
                        "status": r.observation.status,
                        "utility": r.observation.utility,
                        "constraints": dict(r.observation.constraints),
                    },
                }
                for r in self._records
            ],
            "proposal_diagnostics": [d.to_json() for d in self._diagnostics],
        }

    def _random_unique(self) -> tuple[float, ...]:
        used = {self.normalize(r.proposal.parameters) for r in self._records}
        for _ in range(100):
            point = tuple(self._rng.random() for _ in self.names)
            if point not in used:
                return point
        raise RuntimeError("Unable to generate a distinct candidate")

    def tell(self, proposal_id: int, observation: ConstrainedObservation) -> None:
        if self._pending is None or self._pending.proposal_id != proposal_id:
            raise ValueError("Observation does not match the pending proposal")
        if any(r.observation.evaluation_id == observation.evaluation_id for r in self._records):
            raise ValueError("An engine evaluation ID cannot be reused")
        if observation.status == "success" and set(observation.constraints) != set(
            self.constraint_names
        ):
            raise ValueError("Successful observations must supply every declared constraint")
        previous = self.best
        record = MeasuredCandidate(self._pending, observation)
        self._records.append(record)
        self._pending = None
        improved = record.admissible and (
            previous is None or observation.utility > previous.observation.utility
        )
        if improved:
            self._successes += 1
            self._failures = 0
        else:
            self._successes = 0
            self._failures += 1
        if self._successes >= 3:
            self.trust_region_length = min(1.6, self.trust_region_length * 2)
            self._successes = 0
        elif self._failures >= max(4, len(self.names)):
            self.trust_region_length /= 2
            self._failures = 0
            if self.trust_region_length < 0.5**7:
                self.trust_region_length = 0.8

    @staticmethod
    def check_dependencies() -> None:
        """Validate an explicitly requested GP backend before spending engine calls."""
        try:
            import botorch
            import gpytorch
            import torch
        except ImportError as exc:
            raise SurrogateDependencyError(
                "Constrained GP proposals require optional torch, botorch and gpytorch; "
                "no packages are installed automatically"
            ) from exc
        # Access modules to avoid suppressing unused-import checks.
        _ = (botorch.__version__, gpytorch.__version__, torch.__version__)

    def _gp_proposal(self, measured: list[MeasuredCandidate]) -> tuple[float, ...]:
        try:
            import torch
            from botorch.fit import fit_gpytorch_mll
            from botorch.generation.sampling import ConstrainedMaxPosteriorSampling
            from botorch.models import ModelListGP, SingleTaskGP
            from botorch.models.transforms.outcome import Standardize
            from gpytorch.kernels import MaternKernel, ScaleKernel
            from gpytorch.mlls import ExactMarginalLogLikelihood
        except ImportError as exc:
            raise SurrogateDependencyError(
                "Constrained GP proposals require optional torch, botorch and gpytorch; "
                "no packages are installed automatically"
            ) from exc
        # Preserve process RNG state and isolate the reproducible CPU backend seed.
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(self.seed + self._issued)
            x = torch.tensor(
                [self.normalize(r.proposal.parameters) for r in measured], dtype=torch.double
            )
            y = torch.tensor([[r.observation.utility] for r in measured], dtype=torch.double)
            c = torch.tensor(
                [[r.observation.constraints[n] for n in self.constraint_names] for r in measured],
                dtype=torch.double,
            )

            def fit(values):
                fit_started = time.perf_counter()
                # Shared lengthscale avoids fitting d independent scales from a tiny design.
                model = SingleTaskGP(
                    x,
                    values,
                    train_Yvar=torch.full_like(values, 1e-6),
                    covar_module=ScaleKernel(MaternKernel(nu=2.5)),
                    outcome_transform=Standardize(m=1),
                )
                try:
                    fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
                finally:
                    self._active_timings["fit"] += time.perf_counter() - fit_started
                return model

            objective = fit(y)
            constraints = ModelListGP(*(fit(c[:, i : i + 1]) for i in range(c.shape[1])))
            generation_started = time.perf_counter()
            if self.best is not None:
                center = torch.tensor(
                    self.normalize(self.best.proposal.parameters), dtype=torch.double
                )
            else:
                center = x[c.clamp(min=0).sum(dim=-1).argmin()]
            lo = (center - self.trust_region_length / 2).clamp(0, 1)
            hi = (center + self.trust_region_length / 2).clamp(0, 1)
            pool = lo + (hi - lo) * torch.rand(
                self.candidate_pool_size, len(self.names), dtype=torch.double
            )
            # Reserve global exploration candidates even when the incumbent's region is small.
            pool[: max(1, self.candidate_pool_size // 10)] = torch.rand(
                max(1, self.candidate_pool_size // 10), len(self.names), dtype=torch.double
            )
            distance = torch.cdist(pool, x).min(dim=1).values
            pool = pool[distance > 1e-10]
            if not len(pool):
                raise RuntimeError("All GP candidates duplicate measured points")
            self._active_timings["generation"] += time.perf_counter() - generation_started
            sampling_started = time.perf_counter()
            sampling = ConstrainedMaxPosteriorSampling(
                model=objective,
                constraint_model=constraints,
                replacement=False,
            )
            try:
                with torch.no_grad():
                    point = sampling(pool, num_samples=1).squeeze(0)
            finally:
                self._active_timings["sampling"] += time.perf_counter() - sampling_started
            return tuple(float(v) for v in point.tolist())


def run_surrogate_search(
    optimizer: ConstrainedGPOptimizer,
    evaluate: Callable[[Mapping[str, float]], ConstrainedObservation],
) -> MeasuredCandidate | None:
    """Run only the callback's actual observations; unexpected evaluator errors propagate."""
    if optimizer.missing_dependency == "raise":
        optimizer.check_dependencies()
    while optimizer.proposals_issued < optimizer.budget:
        proposal = optimizer.ask()
        optimizer.tell(proposal.proposal_id, evaluate(proposal.parameters))
    return optimizer.best
