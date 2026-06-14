"""Tests for evidence bundle schema v1 and legacy migration shim.

All tests are pure-Python (no engine, no network, no filesystem beyond
tmp_path).  They validate:
  1. Pydantic model construction and round-trip serialisation.
  2. Migration of a minimal legacy bundle.
  3. Migration of a realistic legacy bundle with gates, claims, values.
  4. DiagnosticFinding extraction from known values keys.
  5. write_evidence_v1 writes a parseable file.
"""

from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.evidence import (
    ClaimRecord,
    EvidenceBundleV1,
    GateResult,
    migrate_legacy_bundle,
    write_evidence_v1,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_legacy() -> dict:
    """Smallest valid legacy evidence_summary.json."""
    return {
        "run_id": "run_abc",
        "usgs_id": "01234567",
        "success": True,
        "artifact_dir": "/data/01234567",
        "claim_tier": "exploratory",
        "effective_claim_tier": "exploratory",
        "contract_status": "executed",
        "accepted_by": "user",
        "gates_passed": [],
        "gates_failed": [],
        "allowed_claims": [],
        "blocked_claims": [],
        "blocker_class": None,
        "values": {},
    }


def _full_legacy() -> dict:
    return {
        "run_id": "run_def",
        "usgs_id": "02177000",
        "success": True,
        "artifact_dir": "/data/02177000",
        "claim_tier": "research_grade",
        "effective_claim_tier": "research_grade",
        "contract_status": "executed",
        "accepted_by": "user",
        "gates_passed": [
            "contract_policy",
            "physical_gates",
            "fresh_engine_output",
            "benchmark_lock",
            "outlet_provenance",
            "sensitivity_screen",
            "calibration_verification",
        ],
        "gates_failed": ["routing_flow"],
        "allowed_claims": [
            {
                "claim": "workflow_execution_trace_available",
                "tier": "exploratory",
                "basis": "evidence_summary.json written",
            },
            {
                "claim": "fresh_engine_output_used",
                "tier": "diagnostic",
                "basis": "fresh output artifact exists",
            },
        ],
        "blocked_claims": [
            {
                "claim": "research_metric_thresholds_passed",
                "tier": "research_grade",
                "reason": "routing_flow gate failed",
            }
        ],
        "blocker_class": "routing_scope",
        "provenance_hash": "abc123",
        "values": {
            "terminal_scope_blocker": "multi_terminal_emission",
            "calibration_error": None,
        },
    }


# ---------------------------------------------------------------------------
# Schema model tests
# ---------------------------------------------------------------------------


def test_evidence_bundle_v1_schema_version():
    bundle = EvidenceBundleV1(
        run_id="r1",
        basin_id="01234567",
        generated_at="2026-06-13T00:00:00Z",
        requested_claim_tier="exploratory",
        allowed_claim_tier="exploratory",
        effective_claim_tier="exploratory",
        contract_status="executed",
        accepted_by="user",
        success=True,
        artifact_dir="/tmp",
    )
    assert bundle.schema_version == "1.0"


def test_evidence_bundle_v1_round_trip():
    bundle = EvidenceBundleV1(
        run_id="r2",
        basin_id="02177000",
        generated_at="2026-06-13T00:00:00Z",
        requested_claim_tier="research_grade",
        allowed_claim_tier="research_grade",
        effective_claim_tier="research_grade",
        contract_status="executed",
        accepted_by="user",
        success=True,
        artifact_dir="/data/02177000",
        gate_table=[GateResult(gate_id="fresh_engine_output", status="passed", reason="fresh output exists")],
        claims=[
            ClaimRecord(
                claim_id="02177000.fresh_engine_output_used",
                assertion_type="readiness",
                scope="02177000",
                claim_tier="diagnostic",
                confidence_class="gated",
                status="allowed",
            )
        ],
        diagnostics=[],
        provenance_hash="xyz",
    )
    serialised = bundle.model_dump_json()
    reloaded = EvidenceBundleV1.model_validate_json(serialised)
    assert reloaded.schema_version == "1.0"
    assert reloaded.basin_id == "02177000"
    assert reloaded.gate_table[0].gate_id == "fresh_engine_output"
    assert reloaded.claims[0].claim_id == "02177000.fresh_engine_output_used"


def test_claim_record_defaults():
    cr = ClaimRecord(
        claim_id="01234567.workflow_execution_trace_available",
        assertion_type="readiness",
        scope="01234567",
        claim_tier="exploratory",
        confidence_class="gated",
        status="allowed",
    )
    assert cr.required_gates == []
    assert cr.supporting_artifacts == []
    assert cr.provenance_chain == []
    assert cr.reason is None


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


def test_migrate_minimal_legacy():
    bundle = migrate_legacy_bundle(_minimal_legacy())
    assert bundle.schema_version == "1.0"
    assert bundle.run_id == "run_abc"
    assert bundle.basin_id == "01234567"
    assert bundle.success is True
    assert bundle.gate_table == []
    assert bundle.claims == []
    assert bundle.diagnostics == []


def test_migrate_full_legacy_gate_table():
    bundle = migrate_legacy_bundle(_full_legacy())
    gate_ids = {g.gate_id for g in bundle.gate_table}
    passed = {g.gate_id for g in bundle.gate_table if g.status == "passed"}
    failed = {g.gate_id for g in bundle.gate_table if g.status == "failed"}
    assert "contract_policy" in passed
    assert "routing_flow" in failed
    assert "fresh_engine_output" in gate_ids


def test_migrate_full_legacy_claim_count():
    bundle = migrate_legacy_bundle(_full_legacy())
    allowed = [c for c in bundle.claims if c.status == "allowed"]
    blocked = [c for c in bundle.claims if c.status == "blocked"]
    assert len(allowed) == 2
    assert len(blocked) == 1


def test_migrate_full_legacy_claim_fields():
    bundle = migrate_legacy_bundle(_full_legacy())
    fresh_claim = next(c for c in bundle.claims if "fresh_engine_output" in c.claim_id)
    assert fresh_claim.claim_tier == "diagnostic"
    assert fresh_claim.confidence_class == "gated"
    assert fresh_claim.status == "allowed"
    # required_gates should be inferred for known claim names
    assert "fresh_engine_output" in fresh_claim.required_gates


def test_migrate_full_legacy_blocked_claim():
    bundle = migrate_legacy_bundle(_full_legacy())
    blocked = [c for c in bundle.claims if c.status == "blocked"]
    assert len(blocked) == 1
    assert blocked[0].confidence_class == "unverified"
    assert blocked[0].reason is not None


def test_migrate_extracts_diagnostic_finding():
    legacy = _full_legacy()
    legacy["values"]["terminal_scope_blocker"] = "multi_terminal_emission"
    bundle = migrate_legacy_bundle(legacy)
    finding_ids = [f.finding_id for f in bundle.diagnostics]
    assert any("terminal_scope_blocker" in fid for fid in finding_ids)
    scope_finding = next(f for f in bundle.diagnostics if "terminal_scope_blocker" in f.finding_id)
    assert scope_finding.severity == "warning"
    assert scope_finding.domain == "routing"


def test_migrate_skips_none_diagnostic_values():
    legacy = _minimal_legacy()
    legacy["values"]["calibration_error"] = None  # must be skipped
    bundle = migrate_legacy_bundle(legacy)
    assert not any("calibration_error" in f.finding_id for f in bundle.diagnostics)


def test_migrate_blocker_domain_mapped():
    bundle = migrate_legacy_bundle(_full_legacy())
    assert bundle.blocker_domain == "routing_scope"


def test_migrate_provenance_hash_preserved():
    bundle = migrate_legacy_bundle(_full_legacy())
    assert bundle.provenance_hash == "abc123"


def test_migrate_claim_tier_fields():
    bundle = migrate_legacy_bundle(_full_legacy())
    assert bundle.allowed_claim_tier == "research_grade"
    assert bundle.effective_claim_tier == "research_grade"


# ---------------------------------------------------------------------------
# write_evidence_v1 integration test
# ---------------------------------------------------------------------------


def test_write_evidence_v1_produces_parseable_file(tmp_path: Path):
    write_evidence_v1(_full_legacy(), tmp_path)
    v1_path = tmp_path / "evidence_v1.json"
    assert v1_path.exists()
    raw = json.loads(v1_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1.0"
    assert raw["basin_id"] == "02177000"
    # Round-trip via Pydantic
    bundle = EvidenceBundleV1.model_validate(raw)
    assert bundle.success is True
    assert len(bundle.gate_table) == 8  # 7 passed + 1 failed


def test_write_evidence_v1_overwrites_on_second_call(tmp_path: Path):
    write_evidence_v1(_minimal_legacy(), tmp_path)
    write_evidence_v1(_full_legacy(), tmp_path)
    raw = json.loads((tmp_path / "evidence_v1.json").read_text(encoding="utf-8"))
    assert raw["basin_id"] == "02177000"  # second write wins
