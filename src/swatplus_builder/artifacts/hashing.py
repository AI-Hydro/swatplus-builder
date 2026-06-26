"""Deterministic content-hash utilities for run artifacts.

Content hash contract (Roadmap Appendix A):

    SHA256(canonical_json(config) || engine_version || builder_git_sha)
"""

from __future__ import annotations

import hashlib
import json

from .models import RunConfig


def canonical_config_json(config: RunConfig | dict[str, object]) -> bytes:
    """Return canonical UTF-8 JSON bytes for content hashing.

    Canonicalization rules:
    - sorted keys
    - no extra whitespace
    - UTF-8 encoding
    """
    payload: dict[str, object]
    if isinstance(config, RunConfig):
        payload = config.model_dump(mode="json")
    else:
        payload = RunConfig.model_validate(config).model_dump(mode="json")
    txt = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return txt.encode("utf-8")


def compute_content_hash(
    config: RunConfig | dict[str, object],
    *,
    engine_version: str,
    builder_git_sha: str,
) -> str:
    """Compute the Phase 3B content hash.

    ``engine_version`` values of ``"unknown"`` or ``""`` are treated as empty
    to avoid cache collisions between runs that both lack a verified engine
    version (two unknown-version runs are indistinguishable anyway).  When
    the engine version IS known, it is hashed verbatim so a version upgrade
    naturally yields a different hash and a cache miss.

    Failure modes:
    - Raises ``pydantic.ValidationError`` when ``config`` is invalid.
    """
    ev = engine_version.strip().lower()
    if ev in {"", "unknown"}:
        ev = ""
    h = hashlib.sha256()
    h.update(canonical_config_json(config))
    h.update(ev.encode("utf-8"))
    h.update(builder_git_sha.encode("utf-8"))
    return h.hexdigest()

