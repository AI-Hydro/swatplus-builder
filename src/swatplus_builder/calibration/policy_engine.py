"""Exact-output adapter for an explicitly fitted training objective.

The calendar, observation values and log offset are frozen before simulation.
Engine receipts attest output-file identity, not hydrologic adequacy. No gate
thresholds or continuous process residuals are invented by this adapter.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from .objective_policy import ConstraintResidual, ObjectiveEvaluation, ObjectivePolicy


def _hash(payload: Any) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _calendar(index: pd.Index) -> tuple[str, ...]:
    if not isinstance(index, pd.DatetimeIndex) or index.empty or index.hasnans:
        raise ValueError("missing_or_invalid_training_calendar")
    if index.tz is not None:
        raise ValueError("timezone_aware_calendar_requires_explicit_conversion")
    dates = index.normalize()
    if dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError("training_calendar_must_be_unique_and_ordered")
    return tuple(d.isoformat() for d in dates)


@dataclass(frozen=True)
class ExactOutputEvaluation:
    objective: ObjectiveEvaluation
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    def to_payload(self) -> dict[str, Any]:
        obj = self.objective
        return {
            "status": obj.status, "utility": obj.utility, "feasible": obj.feasible,
            "components": dict(obj.components), "reasons": list(obj.reasons),
            "constraints": [dict(name=c.name, residual=c.residual, kind=c.kind) for c in obj.constraints],
            "context": dict(policy_sha256=obj.context.policy_sha256,
                            training_observation_sha256=obj.context.training_observation_sha256,
                            epsilon=obj.context.epsilon),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class ExactOutputPolicyAdapter:
    policy: ObjectivePolicy
    training_calendar: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "training_calendar", tuple(self.training_calendar))
        if not self.training_calendar or _calendar(pd.DatetimeIndex(self.training_calendar)) != self.training_calendar:
            raise ValueError("invalid_frozen_training_calendar")
        if len(self.training_calendar) != self.policy.training_sample_count:
            raise ValueError("training_calendar_length_mismatch")

    @classmethod
    def bind(cls, policy: ObjectivePolicy, training_series: pd.Series) -> ExactOutputPolicyAdapter:
        calendar = _calendar(training_series.index)
        fitted = ObjectivePolicy.fit(training_series.tolist(), weights=dict(policy.weights),
                                     epsilon_fraction=policy.epsilon_fraction)
        if fitted.sha256 != policy.sha256:
            raise ValueError("observations_do_not_match_training_context")
        return cls(policy, calendar)

    @property
    def sha256(self) -> str:
        return _hash(dict(schema="exact_output_policy_v1", policy_sha256=self.policy.sha256,
                          training_calendar=self.training_calendar))

    def evaluate(self, aligned: pd.DataFrame, *, source_path: Path,
                 receipt_path: Path, constraints: Sequence[ConstraintResidual] = ()) -> ExactOutputEvaluation:
        provenance: dict[str, Any] = dict(adapter_sha256=self.sha256,
                                          training_calendar_sha256=_hash(self.training_calendar),
                                          source_file=source_path.name)
        reasons: list[str] = []
        try:
            actual_calendar = _calendar(aligned.index)
            provenance["scored_calendar_sha256"] = _hash(actual_calendar)
            provenance["scored_sample_count"] = len(actual_calendar)
            if actual_calendar != self.training_calendar:
                reasons.append("scored_calendar_does_not_match_training")
            if not {"obs", "sim"}.issubset(aligned.columns):
                reasons.append("missing_aligned_flow_columns")
            else:
                # This digest documents actual scored values, not the expected context.
                provenance["scored_observation_sha256"] = _hash(tuple(float(v) for v in aligned["obs"]))
                provenance["scored_simulation_sha256"] = _hash(tuple(float(v) for v in aligned["sim"]))
        except (ValueError, TypeError, OverflowError) as exc:
            reasons.append(str(exc))
        try:
            source_hash = sha256(source_path.read_bytes()).hexdigest()
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)
            provenance["source_sha256"] = source_hash
            provenance["engine_receipt_sha256"] = sha256(receipt_bytes).hexdigest()
            provenance["engine_run_id"] = receipt.get("run_id")
            provenance["receipt_input_configuration_sha256"] = receipt.get("input_configuration_sha256")
            engine = receipt.get("engine", {})
            provenance["receipt_engine_sha256"] = engine.get("sha256")
            identity_hashes = (receipt.get("input_configuration_sha256"), engine.get("sha256"))
            if (receipt.get("schema_version") != "2.0" or not isinstance(receipt.get("run_id"), str)
                    or not receipt.get("run_id") or any(
                        not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h)
                        for h in identity_hashes)):
                reasons.append("missing_or_invalid_engine_receipt_identity")
            if type(receipt.get("returncode")) is not int or receipt.get("returncode") != 0 or receipt.get("files", {}).get(source_path.name) != source_hash:
                reasons.append("source_not_sealed_by_successful_engine_receipt")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            reasons.append(f"missing_or_invalid_output_receipt:{type(exc).__name__}")
        if reasons:
            objective = ObjectiveEvaluation("invalid", None, {}, tuple(constraints), tuple(reasons), self.policy.context)
        else:
            objective = self.policy.evaluate(aligned["obs"].tolist(), aligned["sim"].tolist(), constraints=constraints)
        return ExactOutputEvaluation(objective, provenance)


def calibration_process_proxy(value: Any) -> ConstraintResidual:
    """Explicit signed categorical gate proxy; unknown remains unevaluated."""
    residual = None
    if isinstance(value, bool):
        residual = -1.0 if value else 1.0
    return ConstraintResidual("reported_calibration_process_gate_proxy", residual, "process_policy")
