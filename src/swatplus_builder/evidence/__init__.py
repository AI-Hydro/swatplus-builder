"""Evidence schema v1 — Pydantic-owned structured evidence bundles.

The canonical output of a SWAT+ workflow run is an *evidence bundle*:
a self-describing artifact that records which scientific claims are
allowed or blocked, the gate results that determine those statuses, and
structured diagnostic findings.

Schema version ``"1.0"`` (this module) introduces:
- Typed :class:`ClaimRecord` implementing the 6-tuple claim model from
  ``docs/SCIENTIFIC_CLAIM_GOVERNANCE.md``.
- Typed :class:`GateResult` replacing the flat ``gates_passed``/
  ``gates_failed`` lists.
- Typed :class:`DiagnosticFinding` for incident-specific messages,
  replacing ad-hoc ``values`` top-level keys.
- A :func:`~swatplus_builder.evidence.migration.migrate_legacy_bundle`
  shim that converts legacy ``evidence_summary.json`` dicts to v1.

Public API
----------
- :class:`EvidenceBundleV1`
- :class:`ClaimRecord`
- :class:`GateResult`
- :class:`DiagnosticFinding`
- :func:`~swatplus_builder.evidence.migration.migrate_legacy_bundle`
- :func:`~swatplus_builder.evidence.migration.write_evidence_v1`
"""

from .schema import ClaimRecord, DiagnosticFinding, EvidenceBundleV1, GateResult
from .migration import migrate_legacy_bundle, write_evidence_v1

__all__ = [
    "ClaimRecord",
    "DiagnosticFinding",
    "EvidenceBundleV1",
    "GateResult",
    "migrate_legacy_bundle",
    "write_evidence_v1",
]
