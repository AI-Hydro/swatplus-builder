"""Pydantic models for evidence bundle schema v1.

These models implement the formal claim model from
``docs/SCIENTIFIC_CLAIM_GOVERNANCE.md``.  The ``schema_version`` field
on :class:`EvidenceBundleV1` is the machine-readable authority: any code
that reads an evidence bundle must check this field before interpreting
the remaining structure.

No new top-level ``values`` keys are allowed after v1.  Incident-specific
fields belong under :attr:`EvidenceBundleV1.diagnostics`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClaimRecord(BaseModel):
    """One scientific claim — the 6-tuple model from the governance doc.

    The six structural components (``claim_id``, ``assertion_type``,
    ``scope``, ``claim_tier``, ``confidence_class``, ``status``) plus
    the evidence fields (``required_gates``, ``supporting_artifacts``,
    ``provenance_chain``).
    """

    claim_id: str
    assertion_type: str
    scope: str
    claim_tier: str
    confidence_class: str
    required_gates: list[str] = Field(default_factory=list)
    supporting_artifacts: list[str] = Field(default_factory=list)
    provenance_chain: list[str] = Field(default_factory=list)
    status: str
    reason: str | None = None


class GateResult(BaseModel):
    """Result of one governance gate evaluation."""

    gate_id: str
    status: str
    reason: str
    artifact_path: str | None = None


class DiagnosticFinding(BaseModel):
    """One structured incident — replaces ad-hoc top-level ``values`` keys."""

    finding_id: str
    domain: str
    severity: str
    message: str
    artifact_path: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class EvidenceBundleV1(BaseModel):
    """Schema-versioned evidence bundle produced by one workflow run.

    Required core fields
    --------------------
    - Identity: ``schema_version``, ``run_id``, ``basin_id``,
      ``generated_at``.
    - Contract: ``requested_claim_tier``, ``allowed_claim_tier``,
      ``effective_claim_tier``, ``contract_status``, ``accepted_by``.
    - Outcome: ``success``, ``artifact_dir``, ``blocker_domain``.
    - Evidence: ``gate_table``, ``claims``, ``diagnostics``.
    - Provenance: ``provenance_hash``.

    No new top-level keys are added after v1; use
    :attr:`diagnostics` for incident-specific findings.
    """

    schema_version: str = "1.0"

    # --- Run identity ---
    run_id: str
    basin_id: str
    generated_at: str
    git_sha: str | None = None

    # --- Contract ---
    requested_claim_tier: str
    allowed_claim_tier: str
    effective_claim_tier: str
    contract_status: str
    accepted_by: str

    # --- Outcome ---
    success: bool
    artifact_dir: str
    blocker_domain: str | None = None

    # --- Evidence ---
    gate_table: list[GateResult] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    diagnostics: list[DiagnosticFinding] = Field(default_factory=list)

    # --- Provenance ---
    provenance_hash: str | None = None
