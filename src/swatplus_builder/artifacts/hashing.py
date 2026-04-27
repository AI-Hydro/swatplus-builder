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

    Failure modes:
    - Raises `pydantic.ValidationError` when `config` is invalid.
    """
    h = hashlib.sha256()
    h.update(canonical_config_json(config))
    h.update(engine_version.encode("utf-8"))
    h.update(builder_git_sha.encode("utf-8"))
    return h.hexdigest()

