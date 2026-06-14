"""Migration shim: legacy evidence_summary.json → EvidenceBundleV1.

The legacy payload is a flat dict with:
- ``gates_passed`` / ``gates_failed``: flat lists of gate name strings.
- ``allowed_claims`` / ``blocked_claims``: lists of 3-key dicts
  ``{claim, tier, basis/reason}``.
- ``values``: a catch-all dict with hundreds of loose keys.

``migrate_legacy_bundle`` converts that to a structured v1 bundle.
The conversion is best-effort for fields not present in the legacy
format (e.g. ``required_gates``, ``supporting_artifacts``); callers
should not treat those as authoritative.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schema import ClaimRecord, DiagnosticFinding, EvidenceBundleV1, GateResult

# ---------------------------------------------------------------------------
# Gate → reason mapping (best-effort for legacy bundles)
# ---------------------------------------------------------------------------

_GATE_REASONS: dict[str, str] = {
    "contract_policy": "runtime contract policy gate",
    "physical_gates": "physical sensibility checks (mass closure, BFI, volume bias)",
    "routing_flow": "terminal and channel routing flow gate",
    "fresh_engine_output": "fresh non-empty SWAT+ output artifact required",
    "benchmark_lock": "locked baseline metrics artifact required",
    "outlet_provenance": "outlet strict-pinned with provenance",
    "sensitivity_screen": "basin-specific sensitivity screen",
    "soil_fidelity": "soil profiles from authoritative source",
    "calibration_verification": "best solution independently reproduced",
}


def _gate_reason(gate_id: str, *, passed: bool) -> str:
    base = _GATE_REASONS.get(gate_id, gate_id)
    return f"{base} — {'passed' if passed else 'failed'}"


# ---------------------------------------------------------------------------
# Claim-name → assertion_type heuristic
# ---------------------------------------------------------------------------

_ASSERTION_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"nse|kge|pbias|metric|skill|improvement", "metric"),
    (r"provenance|sha|hash|soil|boundary|outlet", "provenance"),
    (r"comparison|baseline|benchmark|delta", "comparison"),
    (r"trace|execution|workflow|success|built", "readiness"),
    (r"claim", "readiness"),
]


def _infer_assertion_type(claim_name: str) -> str:
    lower = claim_name.lower()
    for pattern, atype in _ASSERTION_TYPE_PATTERNS:
        if re.search(pattern, lower):
            return atype
    return "readiness"


# ---------------------------------------------------------------------------
# Legacy claim dict → ClaimRecord
# ---------------------------------------------------------------------------

_CLAIM_GATE_MAP: dict[str, list[str]] = {
    "fresh_engine_output_used": ["fresh_engine_output"],
    "fresh_output_claim": ["fresh_engine_output"],
    "locked_benchmark_available": ["benchmark_lock"],
    "locked_benchmark_claim": ["benchmark_lock"],
    "outlet_provenance_verified": ["outlet_provenance"],
    "calibration_verification_passed": ["calibration_verification"],
    "research_metric_thresholds_passed": ["physical_gates", "routing_flow"],
    "soil_fidelity_verified": ["soil_fidelity"],
    "sensitivity_screen_completed": ["sensitivity_screen"],
    "contract_policy_gate_passed": ["contract_policy"],
    "workflow_execution_trace_available": [],
}


def _legacy_claim_to_record(
    d: dict[str, Any],
    *,
    basin_id: str,
    status: str,
) -> ClaimRecord:
    claim_name = str(d.get("claim") or d.get("claim_id") or "unknown")
    tier = str(d.get("tier") or d.get("claim_tier") or "exploratory")
    basis_or_reason = str(d.get("basis") or d.get("reason") or "")
    required_gates = _CLAIM_GATE_MAP.get(claim_name, [])
    confidence = "gated" if status == "allowed" else "unverified"
    return ClaimRecord(
        claim_id=f"{basin_id}.{claim_name}",
        assertion_type=_infer_assertion_type(claim_name),
        scope=basin_id,
        claim_tier=tier,
        confidence_class=confidence,
        required_gates=required_gates,
        supporting_artifacts=[],
        provenance_chain=[],
        status=status,
        reason=basis_or_reason if basis_or_reason else None,
    )


# ---------------------------------------------------------------------------
# Values → DiagnosticFinding extraction
# ---------------------------------------------------------------------------

_DIAGNOSTIC_KEYS: dict[str, tuple[str, str]] = {
    "volume_bias_diagnostics_error": ("calibration", "error"),
    "calibration_error": ("calibration", "error"),
    "weather_error": ("weather", "error"),
    "delineation_error": ("delineation", "error"),
    "routing_gates_error": ("routing", "error"),
    "physical_gates_error": ("physical", "error"),
    "terminal_scope_blocker": ("routing", "warning"),
    "outlet_autodetect_warning": ("provenance", "warning"),
    "lte_suitability_class": ("calibration", "info"),
    "volume_bias_diagnostics_warning": ("calibration", "warning"),
}


def _extract_diagnostics(values: dict[str, Any], basin_id: str) -> list[DiagnosticFinding]:
    findings: list[DiagnosticFinding] = []
    for key, (domain, severity) in _DIAGNOSTIC_KEYS.items():
        val = values.get(key)
        if val is None:
            continue
        message = str(val)
        if not message:
            continue
        findings.append(
            DiagnosticFinding(
                finding_id=f"{basin_id}.{key}",
                domain=domain,
                severity=severity,
                message=message,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def migrate_legacy_bundle(payload: dict[str, Any]) -> EvidenceBundleV1:
    """Convert a legacy ``evidence_summary.json`` dict to :class:`EvidenceBundleV1`.

    Handles both the current format (``gates_passed``/``gates_failed``) and
    older snapshots that may lack some keys.  Missing fields get safe defaults.
    """
    basin_id = str(payload.get("usgs_id") or payload.get("basin_id") or "unknown")
    values: dict[str, Any] = payload.get("values") or {}

    # --- Gate table ---
    gate_table: list[GateResult] = []
    for gid in payload.get("gates_passed") or []:
        gate_table.append(
            GateResult(
                gate_id=str(gid),
                status="passed",
                reason=_gate_reason(str(gid), passed=True),
            )
        )
    for gid in payload.get("gates_failed") or []:
        gate_table.append(
            GateResult(
                gate_id=str(gid),
                status="failed",
                reason=_gate_reason(str(gid), passed=False),
            )
        )

    # --- Claims ---
    claims: list[ClaimRecord] = []
    for d in payload.get("allowed_claims") or []:
        claims.append(_legacy_claim_to_record(d, basin_id=basin_id, status="allowed"))
    for d in payload.get("blocked_claims") or []:
        claims.append(_legacy_claim_to_record(d, basin_id=basin_id, status="blocked"))

    # --- Diagnostics ---
    diagnostics = _extract_diagnostics(values, basin_id)

    return EvidenceBundleV1(
        run_id=str(payload.get("run_id") or ""),
        basin_id=basin_id,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        git_sha=str(values.get("git_sha") or payload.get("git_sha") or "") or None,
        requested_claim_tier=str(payload.get("requested_claim_tier") or payload.get("claim_tier") or "exploratory"),
        allowed_claim_tier=str(payload.get("claim_tier") or "exploratory"),
        effective_claim_tier=str(payload.get("effective_claim_tier") or "exploratory"),
        contract_status=str(payload.get("contract_status") or "executed"),
        accepted_by=str(payload.get("accepted_by") or "unknown"),
        success=bool(payload.get("success")),
        artifact_dir=str(payload.get("artifact_dir") or ""),
        blocker_domain=str(payload.get("blocker_class") or "") or None,
        gate_table=gate_table,
        claims=claims,
        diagnostics=diagnostics,
        provenance_hash=str(payload.get("provenance_hash") or "") or None,
    )


def write_evidence_v1(payload: dict[str, Any], out_dir: Path | str) -> Path:
    """Migrate ``payload`` to v1 and write ``evidence_v1.json`` in ``out_dir``.

    Called as a side-effect of the main workflow run (does not replace the
    existing ``evidence_summary.json``).  Returns the path written.
    """
    bundle = migrate_legacy_bundle(payload)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "evidence_v1.json"
    path.write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
