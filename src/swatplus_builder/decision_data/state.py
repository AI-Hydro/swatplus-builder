"""Compact, versioned, token-budgeted serialization of evidence states.

Decision encoders such as Laya accept a bounded context (512–1,024 tokens
including the question and options), so an evidence state must be rendered
into a short, *deterministic* text: the same state always produces the same
string, and a model trained on one serializer version is never silently fed
another.

Rendering rules (``STATE_SERIALIZER_VERSION``):

* nested mappings flatten to dotted keys (``incoming_metrics.nse``);
* floats keep 3 significant digits; booleans render as ``yes``/``no``;
  ``None`` and empty values are dropped;
* keys are ordered by :data:`KEY_PRIORITY` (most diagnostic first), then
  alphabetically;
* while the text exceeds ``max_chars``, the lowest-priority entries are
  dropped and listed in :attr:`SerializedState.dropped_keys`.

Keys that carry hidden labels (e.g. an injected fault) are refused outright:
leaking the answer into the input would invalidate any evaluation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

STATE_SERIALIZER_VERSION = "state-v1"

# Approximate budget: ~4 characters per token leaves room for question and
# options inside a 512-token context.
DEFAULT_MAX_CHARS = 1600

HIDDEN_LABEL_KEYS = frozenset(
    {"latent_fault", "latent_fault_family", "fault", "expected_symptoms", "fault_id"}
)

# Lower index = kept longer when trimming to budget.
KEY_PRIORITY: tuple[str, ...] = (
    "phase_order",
    "objective",
    "parameters_opened",
    "incoming_metrics",
    "baseline_metrics",
    "metrics",
    "physical_gates_status",
    "routing_flow_gates_status",
    "blocker_class",
    "calibration_success",
    "claim_tier_allowed",
    "requested_claim_tier",
    "model_family",
    "window_years",
    "warmup_years",
    "budget",
    "incoming_parameters",
)


@dataclass(frozen=True)
class SerializedState:
    text: str
    version: str = STATE_SERIALIZER_VERSION
    dropped_keys: tuple[str, ...] = field(default_factory=tuple)

    @property
    def truncated(self) -> bool:
        return bool(self.dropped_keys)


def _fmt_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value == 0:
            return "0"
        return f"{value:.3g}"
    text = str(value).strip()
    return text or None


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    if isinstance(value, Mapping):
        for key in sorted(value):
            _flatten(f"{prefix}.{key}" if prefix else str(key), value[key], out)
        return
    if isinstance(value, (list, tuple)):
        items = [s for s in (_fmt_scalar(v) for v in value) if s is not None]
        if items:
            out.append((prefix, ",".join(items)))
        return
    rendered = _fmt_scalar(value)
    if rendered is not None:
        out.append((prefix, rendered))


def _rank(key: str) -> tuple[int, str]:
    root = key.split(".", 1)[0]
    try:
        return (KEY_PRIORITY.index(root), key)
    except ValueError:
        return (len(KEY_PRIORITY), key)


def _find_hidden(value: Any, path: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, sub in value.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key) in HIDDEN_LABEL_KEYS:
                return here
            found = _find_hidden(sub, here)
            if found:
                return found
    return None


def serialize_state(state: Mapping[str, Any], *, max_chars: int = DEFAULT_MAX_CHARS) -> SerializedState:
    """Render ``state`` as ``key=value; …`` within ``max_chars``.

    Raises:
        ValueError: ``state`` contains a hidden-label key anywhere, or a single
            entry cannot fit in ``max_chars``.
    """
    hidden = _find_hidden(state)
    if hidden:
        raise ValueError(f"state contains hidden-label key {hidden!r}; refusing to serialize (label leakage)")

    pairs: list[tuple[str, str]] = []
    _flatten("", state, pairs)
    pairs.sort(key=lambda kv: _rank(kv[0]))

    dropped: list[str] = []
    while pairs:
        text = "; ".join(f"{k}={v}" for k, v in pairs)
        if len(text) <= max_chars:
            return SerializedState(text=text, dropped_keys=tuple(dropped))
        if len(pairs) == 1:
            raise ValueError(f"state entry {pairs[0][0]!r} alone exceeds max_chars={max_chars}")
        dropped.append(pairs.pop()[0])
    return SerializedState(text="", dropped_keys=tuple(dropped))
