"""Typed run-artifact schemas and hashing helpers.

Phase 3B introduces a canonical artifact contract under ``runs/<content_hash>/``.
This package defines the typed JSON payloads and deterministic hash utilities
that power content-addressed caching.
"""

from .hashing import canonical_config_json, compute_content_hash
from .models import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    ArtifactQuery,
    ArtifactRecord,
    ArtifactSummary,
    OutletMetadata,
    RunConfig,
)
from .store import ArtifactStore, LocalArtifactStore

__all__ = [
    "ArtifactMetadata",
    "ArtifactQuery",
    "ArtifactMetrics",
    "ArtifactProvenance",
    "ArtifactRecord",
    "ArtifactSummary",
    "ArtifactStore",
    "LocalArtifactStore",
    "OutletMetadata",
    "RunConfig",
    "canonical_config_json",
    "compute_content_hash",
]
