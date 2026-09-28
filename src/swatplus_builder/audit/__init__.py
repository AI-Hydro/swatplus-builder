"""Tamper-evident audit trail and decision-episode recording for workflow runs."""

from .decisions import (
    DECISION_EPISODE_SCHEMA,
    DECISIONS_FILENAME,
    EVENTS_FILENAME,
    RunAuditTrail,
    archive_previous_trail,
    environment_fingerprint,
    export_decision_episodes,
    file_sha256,
    verify_run_audit,
)
from .ledger import (
    GENESIS_SHA256,
    HashChainedLedger,
    LedgerVerification,
    canonical_json,
    iter_records,
    record_sha256,
    verify_ledger,
)

__all__ = [
    "DECISIONS_FILENAME",
    "DECISION_EPISODE_SCHEMA",
    "EVENTS_FILENAME",
    "GENESIS_SHA256",
    "HashChainedLedger",
    "LedgerVerification",
    "RunAuditTrail",
    "archive_previous_trail",
    "canonical_json",
    "environment_fingerprint",
    "export_decision_episodes",
    "file_sha256",
    "iter_records",
    "record_sha256",
    "verify_ledger",
    "verify_run_audit",
]
