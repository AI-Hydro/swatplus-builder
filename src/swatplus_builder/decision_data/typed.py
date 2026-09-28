"""Compile DecisionEpisodes into typed-decision training items.

System-One decision models (Jev, Laya) take a *state*, a typed *question*
and a bounded list of *options*, and learn a probability for each option.
This module turns the model-agnostic ``DecisionEpisode`` rows exported by
``swat audit episodes`` into that shape:

.. code-block:: json

    {"schema": "swatplus_builder.typed_decision/v1",
     "state": "<serialize_state text>",
     "question": {"type": "choice", "text": "...", "options": ["...", "..."]},
     "target": {"probabilities": [0.0, 1.0, ...], "kind": "hard"},
     "meta": {"episode_id": "...", "split": "train", ...}}

The field names follow the typed-decision primitives (state / question /
options / probability target), not any one trainer's file format; map them
onto the exact keys your fine-tuning notebook expects with a thin adapter.
The canonical record stays the DecisionEpisode, so this compilation can be
re-run whenever the target format or serializer version changes.

Guarantees:

* **No label leakage** — states pass through :func:`serialize_state`, which
  refuses hidden-label keys; latent fault labels are only ever targets.
* **Basin-disjoint splits** — :func:`assign_split` hashes the episode's
  ``split_group`` (the basin), so every episode of a basin lands in the same
  split and a model is always evaluated on unseen basins.
* **Bounded option sets** — at most ``max_options`` options; for calibration
  phases the promoted candidate, the best feasible alternatives and hard
  negatives (infeasible candidates) are kept deterministically.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from .state import DEFAULT_MAX_CHARS, STATE_SERIALIZER_VERSION, serialize_state

TYPED_DECISION_SCHEMA = "swatplus_builder.typed_decision/v1"
DEFAULT_MAX_OPTIONS = 16
FAULT_FAMILY_OPTIONS: tuple[str, ...] = (
    "forcing",
    "runoff",
    "soil_storage",
    "evapotranspiration",
    "subsurface",
    "routing",
    "snow",
)

_QUESTIONS: dict[str, str] = {
    "claim_tier_contract": "Which claim tier may this run's contract request?",
    "calibration_precheck": "Should gated diagnostic calibration run from this evidence state?",
    "effective_claim_tier": "Which claim tier does the completed evidence support?",
}
_PHASE_QUESTION = (
    "Calibration phase '{phase}': which evaluated candidate should be promoted "
    "(or none), given the phase objective and gates?"
)
_DIAGNOSIS_QUESTION = "What is the dominant cause of this model's error?"


def assign_split(
    split_group: str | None,
    *,
    fractions: tuple[float, float, float] = (0.7, 0.15, 0.15),
    salt: str = "swat-s1",
) -> str:
    """Deterministically map a split group (basin) to ``train``/``validation``/``test``."""
    if abs(sum(fractions) - 1.0) > 1e-9 or any(f < 0 for f in fractions):
        raise ValueError("fractions must be non-negative and sum to 1")
    digest = hashlib.sha256(f"{salt}:{split_group}".encode()).hexdigest()
    u = int(digest[:12], 16) / float(16**12)
    if u < fractions[0]:
        return "train"
    if u < fractions[0] + fractions[1]:
        return "validation"
    return "test"


def _describe_candidate(candidate_params: Mapping[str, Any], incoming: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for name in sorted(candidate_params):
        new = candidate_params.get(name)
        if new is None:
            continue
        old = incoming.get(name)
        if old is None:
            parts.append(f"{name}={new:.3g}")
        elif abs(float(new) - float(old)) > 1e-12:
            parts.append(f"{name} {float(old):.3g}->{float(new):.3g}")
    return "; ".join(parts) if parts else "keep current parameters"


def _phase_options(
    episode: Mapping[str, Any], max_options: int
) -> tuple[list[str], list[str], list[float | None], bool]:
    """Return (option ids, option texts, candidate scores, truncated) for a phase episode."""
    chosen = str(episode.get("chosen_action"))
    outcomes = (episode.get("outcome_vector") or {}).get("candidate_outcomes") or {}
    state = episode.get("state_before") or {}
    incoming = state.get("incoming_parameters") or {}
    ids = [str(a) for a in episode.get("candidate_actions") or []]
    evals = [i for i in ids if i != "no_promotion"]

    def score(i: str) -> float:
        s = (outcomes.get(i) or {}).get("phase_score")
        return float(s) if isinstance(s, (int, float)) and math.isfinite(s) else float("-inf")

    feasible = sorted((i for i in evals if (outcomes.get(i) or {}).get("feasible")), key=lambda i: (-score(i), i))
    infeasible = [i for i in evals if i not in feasible]
    keep: list[str] = []
    for i in [chosen, "no_promotion", *feasible, *infeasible]:
        if i in ids and i not in keep:
            keep.append(i)
    truncated = len(keep) > max_options
    keep = keep[:max_options]
    # Stable presentation order (option position must not leak the answer).
    keep.sort(key=lambda i: (i == "no_promotion", ids.index(i)))

    texts: list[str] = []
    candidate_params = {
        i: (episode.get("outcome_vector") or {}).get("candidate_parameters", {}).get(i) for i in keep
    }
    for i in keep:
        if i == "no_promotion":
            texts.append("promote no candidate (keep incoming parameters)")
            continue
        params = candidate_params.get(i) or {}
        texts.append(_describe_candidate(params, incoming) if params else i)
    return keep, texts, [None if i == "no_promotion" else score(i) for i in keep], truncated


def _target(
    ids: list[str],
    chosen: str,
    scores: list[float | None],
    *,
    soft_target: Literal["none", "softmax"],
    temperature: float,
) -> dict[str, Any]:
    if soft_target == "softmax" and any(s is not None and math.isfinite(s) for s in scores):
        finite = [s for s in scores if s is not None and math.isfinite(s)]
        top = max(finite)
        weights = [
            math.exp((s - top) / temperature) if s is not None and math.isfinite(s) else 0.0 for s in scores
        ]
        total = sum(weights)
        return {"kind": "softmax_phase_score", "temperature": temperature, "probabilities": [w / total for w in weights]}
    return {"kind": "hard", "probabilities": [1.0 if i == chosen else 0.0 for i in ids]}


def episode_to_typed_decisions(
    episode: Mapping[str, Any],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_options: int = DEFAULT_MAX_OPTIONS,
    soft_target: Literal["none", "softmax"] = "none",
    temperature: float = 0.05,
    fractions: tuple[float, float, float] = (0.7, 0.15, 0.15),
) -> list[dict[str, Any]]:
    """Compile one DecisionEpisode into zero or more typed-decision items.

    ``soft_target="softmax"`` spreads calibration-phase targets over feasible
    candidates by ``softmax(phase_score / temperature)``; this is a
    convenience, not the uncertainty-realization targets of the research
    design, and the item records which kind it used.
    """
    point = str(episode.get("decision_point") or "")
    chosen = str(episode.get("chosen_action"))
    serialized = serialize_state(episode.get("state_before") or {}, max_chars=max_chars)
    split = assign_split(episode.get("split_group"), fractions=fractions)
    base_meta = {
        "episode_id": episode.get("episode_id"),
        "basin_id": episode.get("basin_id"),
        "split_group": episode.get("split_group"),
        "split": split,
        "decision_point": point,
        "source": episode.get("source"),
        "decided_by": episode.get("decided_by"),
        "policy": episode.get("policy"),
        "state_serializer": STATE_SERIALIZER_VERSION,
        "state_dropped_keys": list(serialized.dropped_keys),
        "ledger_record_sha256": episode.get("ledger_record_sha256"),
        "builder_git_sha": episode.get("builder_git_sha"),
    }

    items: list[dict[str, Any]] = []
    if point.startswith("calibration_phase:"):
        ids, texts, scores, truncated = _phase_options(episode, max_options)
        if chosen not in ids:
            return []
        items.append(
            {
                "schema": TYPED_DECISION_SCHEMA,
                "state": serialized.text,
                "question": {"type": "choice", "text": _PHASE_QUESTION.format(phase=point.split(":", 1)[1]), "options": texts},
                "target": _target(ids, chosen, scores, soft_target=soft_target, temperature=temperature),
                "meta": {**base_meta, "option_ids": ids, "options_truncated": truncated},
            }
        )
    elif point in _QUESTIONS:
        ids = [str(a) for a in episode.get("candidate_actions") or []]
        if chosen not in ids or len(ids) > max_options:
            return []
        items.append(
            {
                "schema": TYPED_DECISION_SCHEMA,
                "state": serialized.text,
                "question": {"type": "choice", "text": _QUESTIONS[point], "options": ids},
                "target": {"kind": "hard", "probabilities": [1.0 if i == chosen else 0.0 for i in ids]},
                "meta": {**base_meta, "option_ids": ids, "options_truncated": False},
            }
        )

    latent = episode.get("latent_fault") or {}
    family = latent.get("family")
    if point == "effective_claim_tier" and family in FAULT_FAMILY_OPTIONS:
        # Diagnosis question: the input is the final evidence state, the
        # target is the injected (hidden) cause.
        options = list(FAULT_FAMILY_OPTIONS)
        items.append(
            {
                "schema": TYPED_DECISION_SCHEMA,
                "state": serialized.text,
                "question": {"type": "choice", "text": _DIAGNOSIS_QUESTION, "options": options},
                "target": {"kind": "latent_fault", "probabilities": [1.0 if o == family else 0.0 for o in options]},
                "meta": {
                    **base_meta,
                    "decision_point": "dominant_failure",
                    "option_ids": options,
                    "options_truncated": False,
                    "fault_manifest_sha256": latent.get("fault_manifest_sha256"),
                },
            }
        )
    return items


def compile_typed_decisions(episodes: Iterable[Mapping[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    """Compile many episodes; see :func:`episode_to_typed_decisions` for options."""
    out: list[dict[str, Any]] = []
    for episode in episodes:
        out.extend(episode_to_typed_decisions(episode, **kwargs))
    return out
