"""Typed run-artifact schemas and hashing helpers.

Phase 3B introduces a canonical artifact contract under ``runs/<content_hash>/``.
This package defines the typed JSON payloads and deterministic hash utilities
that power content-addressed caching.
"""

from .models import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    OutletMetadata,
    RunConfig,
)
from .hashing import canonical_config_json, compute_content_hash

__all__ = [
    "ArtifactMetadata",
    "ArtifactMetrics",
    "ArtifactProvenance",
    "OutletMetadata",
    "RunConfig",
    "canonical_config_json",
    "compute_content_hash",
]

