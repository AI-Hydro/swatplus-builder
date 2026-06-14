"""USGS E2E workflow wrapper for agent-governed execution.

This lightweight implementation uses existing `orchestrate.run_pipeline` and
writes a canonical evidence summary JSON with claim/provenance fields.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..calibration.diagnostic_calibrator import run_diagnostic_calibration
from ..governance import (
    benchmark_lock_gate as _benchmark_lock_gate_impl,
)
from ..governance import (
    calibration_improvement_gate as _calibration_improvement_gate_impl,
)
from ..governance import (
    fresh_engine_gate as _fresh_engine_gate_impl,
)
from ..governance import (
    outlet_provenance_gate as _outlet_provenance_gate_impl,
)
from ..governance import (
    research_metric_gate as _research_metric_gate_impl,
)
from ..governance import (
    sensitivity_gate as _sensitivity_gate_impl,
)
from ..governance import (
    soil_fidelity_gate as _soil_fidelity_gate_impl,
)
from ..orchestrate import run_pipeline
from ..output.et_diagnostics import write_et_partition_diagnostics
from ..output.mass_diagnostics import write_mass_balance_diagnostics
from ..output.mass_trace import classify_terminal_scope_blocker
from ..output.volume_diagnostics import write_volume_bias_diagnostics
from ..params.governance import (
    FULL_MODE_CORE_PARAMETERS,
    FULL_MODE_EXTENDED_PARAMETERS,
    FULL_MODE_PARAMETER_GOVERNANCE,
    full_mode_extended_screen_rows,
    full_mode_screen_rows,
)

# SWAT+-specific sensitivity gate parameters (computed once at import time)
_SENSITIVITY_REQUIRED: frozenset[str] = frozenset(
    name for name in FULL_MODE_CORE_PARAMETERS
    if FULL_MODE_PARAMETER_GOVERNANCE[name].activity_class != "dead"
)
_SENSITIVITY_DEAD: frozenset[str] = frozenset(
    name for name in FULL_MODE_CORE_PARAMETERS
    if FULL_MODE_PARAMETER_GOVERNANCE[name].activity_class == "dead"
)


@dataclass
class RunUSGSWorkflowRequest:
    usgs_id: str
    out_dir: Path
    model_family: str = "full"
    start: str = "2000-01-01"
    end: str = "2019-12-31"
    warmup_years: int = 3
    claim_tier: str = "diagnostic"
    contract_status: str | None = None
    accepted_by: str | None = None
    contract_path: str | None = None
    calibrate: bool = True
    virtual_all_terminal_outlet: bool = False
    virtual_outlet_authority: str | None = None


@dataclass
class RunUSGSWorkflowResult:
    success: bool
    run_id: str
    artifact_dir: str
    evidence_summary_path: str
    blocker_class: str | None
    values: dict[str, Any]


def _provenance_hash(payload: dict[str, Any]) -> str:
    core = {
        "run_id": payload.get("run_id"),
        "usgs_id": payload.get("usgs_id"),
        "claim_tier": payload.get("claim_tier"),
        "effective_claim_tier": payload.get("effective_claim_tier"),
        "contract_status": payload.get("contract_status"),
        "accepted_by": payload.get("accepted_by"),
        "values": payload.get("values", {}),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip() or "unknown"
    except Exception:
        return "unknown"


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _compact_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _phase_from_calibration_error(error: str) -> str | None:
    marker = "during phase '"
    if marker not in error:
        return None
    tail = error.split(marker, 1)[1]
    if "'" not in tail:
        return None
    phase = tail.split("'", 1)[0].strip()
    return phase or None


def _promote_calibration_authority_values(
    values: dict[str, Any],
    calibration_provenance_payload: dict[str, Any],
) -> None:
    provenance = calibration_provenance_payload.get("provenance")
    if not isinstance(provenance, dict):
        return
    if "final_metrics_authority" in provenance:
        values["calibration_final_metrics_authority"] = provenance.get("final_metrics_authority")
    if "temporary_candidate_metrics_allowed_as_final" in provenance:
        values["temporary_candidate_metrics_allowed_as_final"] = bool(
            provenance.get("temporary_candidate_metrics_allowed_as_final")
        )
    if "locked_verification_succeeded" in provenance:
        values["calibration_locked_verification_succeeded"] = bool(
            provenance.get("locked_verification_succeeded")
        )
    if "locked_rerun_improved" in provenance:
        values["calibration_locked_rerun_improved"] = bool(provenance.get("locked_rerun_improved"))
    if "final_claim_gates_passed" in provenance:
        values["calibration_final_claim_gates_passed"] = bool(provenance.get("final_claim_gates_passed"))
    if "calibration_claim_status" in provenance:
        values["calibration_claim_status"] = _compact_str(provenance.get("calibration_claim_status"))

    error = str(provenance.get("error") or "")
    phases = calibration_provenance_payload.get("phases")
    failed_phase = None
    if isinstance(phases, list):
        failed_phase = next(
            (
                phase
                for phase in phases
                if isinstance(phase, dict)
                and str(phase.get("status") or "").lower() == "failed"
            ),
            None,
        )
    failure_phase = _phase_from_calibration_error(error)
    if failure_phase is None and isinstance(failed_phase, dict):
        failure_phase = _compact_str(failed_phase.get("phase"))
    failure_message = error or (
        _compact_str(failed_phase.get("message"))
        if isinstance(failed_phase, dict)
        else None
    )
    if failure_phase:
        values["calibration_failure_phase"] = failure_phase
    if failure_message:
        values["calibration_failure_message"] = failure_message
    if _compact_str(provenance.get("history_csv")):
        values["calibration_failure_history_csv"] = _compact_str(provenance.get("history_csv"))
    n_evaluations = provenance.get("n_evaluations")
    if isinstance(n_evaluations, int):
        values["calibration_failure_n_evaluations"] = n_evaluations
    promotion_gate = provenance.get("promotion_gate")
    if isinstance(promotion_gate, dict):
        values["calibration_failure_promotion_gate"] = promotion_gate


def _promote_terminal_scope_blocker_values(
    values: dict[str, Any],
    routing_gates_payload: dict[str, Any],
) -> str | None:
    virtual_gate = _virtual_all_terminal_scope_gate(values, routing_gates_payload)
    if virtual_gate.get("applicable"):
        values["virtual_outlet_scope_gate"] = virtual_gate
        if virtual_gate.get("passed"):
            values["terminal_scope_blocker"] = None
            values["virtual_outlet_scope_gate_status"] = "passed"
            return None
        blocker = _compact_str(virtual_gate.get("reason")) or "virtual_all_terminal_scope_not_authorized"
        values["terminal_scope_blocker"] = blocker
        values["terminal_scope_blocker_source"] = "virtual_outlet_scope_gate"
        values["virtual_outlet_scope_gate_status"] = "failed"
        return blocker

    blocker = _compact_str(values.get("terminal_scope_blocker"))
    if blocker:
        return blocker
    blocker = classify_terminal_scope_blocker(routing_gates_payload)
    if blocker:
        values["terminal_scope_blocker"] = blocker
        values["terminal_scope_blocker_source"] = "routing_flow_gates"
    else:
        values["terminal_scope_blocker"] = None
    return blocker


def _virtual_all_terminal_scope_authorized(
    values: dict[str, Any],
    routing_gates_payload: dict[str, Any],
) -> bool:
    gate = _virtual_all_terminal_scope_gate(values, routing_gates_payload)
    return bool(gate.get("applicable")) and bool(gate.get("passed"))


def _promote_terminal_hydrograph_scope_values(
    values: dict[str, Any],
    volume_diag_payload: dict[str, Any],
) -> dict[str, Any]:
    """Copy terminal hydrograph scope interpretation into workflow evidence."""

    promoted: dict[str, Any] = {}
    scope = volume_diag_payload.get("terminal_hydrograph_scope")
    if isinstance(scope, dict):
        values["terminal_hydrograph_scope"] = scope
        promoted["terminal_hydrograph_scope"] = scope
    decision = volume_diag_payload.get("terminal_scope_decision_request")
    if isinstance(decision, dict):
        values["terminal_scope_decision_request"] = decision
        promoted["terminal_scope_decision_request"] = decision
    post_aggregation = volume_diag_payload.get("post_aggregation_process_context")
    if isinstance(post_aggregation, dict) and post_aggregation.get("available") is True:
        values["post_aggregation_process_context"] = post_aggregation
        promoted["post_aggregation_process_context"] = post_aggregation
    scalar_keys = (
        "terminal_hydrograph_scope_class",
        "terminal_hydrograph_scope_claim_impact",
    )
    for key in scalar_keys:
        value = _compact_str(volume_diag_payload.get(key))
        if value:
            values[key] = value
            promoted[key] = value
    list_keys = (
        "terminal_hydrograph_scope_flags",
        "terminal_hydrograph_scope_recommended_focus",
    )
    for key in list_keys:
        raw = volume_diag_payload.get(key)
        items = [str(item) for item in raw if isinstance(item, str) and item] if isinstance(raw, list) else []
        if items:
            values[key] = items
            promoted[key] = items
    return promoted


def terminal_scope_blocked_claim(blocker: object) -> dict[str, str] | None:
    reason = _compact_str(blocker)
    if not reason:
        return None
    return {
        "claim": "terminal_scope_claim",
        "tier": "research_grade",
        "reason": reason,
    }


def _is_virtual_all_terminal_scope(values: dict[str, Any]) -> bool:
    return (
        str(values.get("outlet_scope") or "").lower() == "virtual_all_terminal"
        or str(values.get("outlet_policy") or "").lower() == "all_terminal_sum"
    )


def _virtual_all_terminal_scope_gate(
    values: dict[str, Any],
    routing_gates: dict[str, Any],
) -> dict[str, Any]:
    if not _is_virtual_all_terminal_scope(values):
        return {"applicable": False, "passed": True, "reason": "single_channel_scope"}

    blockers: list[str] = []
    if str(values.get("outlet_policy") or "").lower() != "all_terminal_sum":
        blockers.append("outlet_policy_must_be_all_terminal_sum")
    if str(values.get("outlet_scope") or "").lower() != "virtual_all_terminal":
        blockers.append("outlet_scope_must_be_virtual_all_terminal")
    if not _compact_str(values.get("virtual_outlet_authority")):
        blockers.append("virtual_outlet_authority_missing")
    if values.get("virtual_outlet_claim_authority") is not True:
        blockers.append("virtual_outlet_claim_authority_not_true")

    selected_ids = values.get("selected_outlet_gis_ids")
    if not isinstance(selected_ids, list) or not selected_ids:
        blockers.append("selected_outlet_gis_ids_missing")

    terminal_count = _as_float(routing_gates.get("terminal_outlet_count"))
    if terminal_count is None or terminal_count < 2:
        blockers.append("terminal_inventory_not_multi_terminal")

    overlap_count = _as_float(routing_gates.get("terminal_overlap_pair_count"))
    shared_area = _as_float(routing_gates.get("terminal_shared_upstream_area_km2"))
    if terminal_count is not None and terminal_count >= 2 and overlap_count is None and shared_area is None:
        blockers.append("terminal_topology_evidence_missing")
    if overlap_count is not None and overlap_count > 0:
        blockers.append("terminal_topology_overlap")
    if shared_area is not None and shared_area > 0.01:
        blockers.append("terminal_topology_overlap")

    all_routed_ratio = _as_float(routing_gates.get("all_terminal_routed_to_channel_closure_ratio"))
    all_mass_ratio = _as_float(routing_gates.get("all_terminal_mass_closure_ratio"))
    all_outflow = _as_float(routing_gates.get("all_terminal_outflow_m3"))
    if all_outflow is None or all_outflow <= 0:
        blockers.append("all_terminal_outflow_missing_or_zero")

    all_terminal_closes = (
        _ratio_in_range(all_routed_ratio, 0.7, 1.3)
        or _ratio_in_range(all_mass_ratio, 0.7, 1.3)
    )
    if not all_terminal_closes:
        blockers.append("all_terminal_routing_closure_not_passed")

    return {
        "applicable": True,
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "reason": "virtual all-terminal outlet scope passed" if not blockers else ",".join(blockers),
        "blockers": blockers,
        "authority": values.get("virtual_outlet_authority"),
        "selected_outlet_gis_ids": selected_ids if isinstance(selected_ids, list) else [],
        "terminal_outlet_count": int(terminal_count) if terminal_count is not None else None,
        "all_terminal_routed_to_channel_closure_ratio": all_routed_ratio,
        "all_terminal_mass_closure_ratio": all_mass_ratio,
        "all_terminal_outflow_m3": all_outflow,
    }


def _ratio_in_range(value: float | None, min_value: float, max_value: float) -> bool:
    return value is not None and min_value <= value <= max_value


def _claim_lists(
    *,
    requested_tier: str,
    allowed_tier: str,
    blocker: str | None,
    calibration_success: bool,
    policy_notes: list[str],
    values: dict[str, Any],
    physical_gates: dict[str, Any],
    routing_gates: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    allowed: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []

    allowed.append(
        {
            "claim": "workflow_execution_trace_available",
            "tier": "exploratory",
            "basis": "evidence_summary.json and run_manifest.json were written",
        }
    )
    if blocker is None:
        allowed.append(
            {
                "claim": "contract_policy_gate_passed",
                "tier": allowed_tier,
                "basis": "runtime contract policy did not block execution",
            }
        )
    else:
        blocked.append(
            {
                "claim": f"{requested_tier}_workflow_claim",
                "tier": requested_tier,
                "reason": blocker,
            }
        )

    fresh_gate = _fresh_engine_gate(values)
    if fresh_gate["passed"]:
        allowed.append(
            {
                "claim": "fresh_engine_output_used",
                "tier": "diagnostic",
                "basis": fresh_gate["reason"],
            }
        )
    else:
        blocked.append(
            {
                "claim": "fresh_output_claim",
                "tier": requested_tier,
                "reason": fresh_gate["reason"],
            }
        )

    benchmark_gate = _benchmark_lock_gate(values)
    if benchmark_gate["passed"]:
        allowed.append(
            {
                "claim": "locked_benchmark_available",
                "tier": "diagnostic",
                "basis": benchmark_gate["reason"],
            }
        )
    else:
        blocked.append(
            {
                "claim": "locked_benchmark_claim",
                "tier": requested_tier,
                "reason": benchmark_gate["reason"],
            }
        )

    outlet_gate = _outlet_provenance_gate(values)
    if outlet_gate["passed"]:
        allowed.append(
            {
                "claim": "outlet_provenance_verified",
                "tier": "research_grade",
                "basis": outlet_gate["reason"],
            }
        )
    else:
        blocked.append(
            {
                "claim": "outlet_provenance_verified",
                "tier": "research_grade",
                "reason": outlet_gate["reason"],
            }
        )

    physical_status = str(physical_gates.get("status") or "unknown")
    if physical_status == "passed":
        allowed.append(
            {
                "claim": "physical_gates_passed",
                "tier": allowed_tier,
                "basis": "physical_gates.json reports pass=true",
            }
        )
    else:
        blocked.append(
            {
                "claim": "physical_gate_claim",
                "tier": requested_tier,
                "reason": physical_status,
            }
        )

    routing_status = str(routing_gates.get("status") or "unknown")
    if routing_status == "passed":
        allowed.append(
            {
                "claim": "routing_flow_gate_passed",
                "tier": allowed_tier,
                "basis": "routing_flow_gates.json reports terminal/channel flow closure passed",
            }
        )
    else:
        blocked.append(
            {
                "claim": "routing_flow_gate_claim",
                "tier": requested_tier,
                "reason": routing_status,
            }
        )

    virtual_scope_gate = _virtual_all_terminal_scope_gate(values, routing_gates)
    if virtual_scope_gate.get("applicable"):
        if virtual_scope_gate.get("passed"):
            allowed.append(
                {
                    "claim": "virtual_all_terminal_outlet_scope_passed",
                    "tier": "research_grade",
                    "basis": str(virtual_scope_gate.get("reason")),
                }
            )
        else:
            blocked.append(
                {
                    "claim": "virtual_all_terminal_outlet_scope_passed",
                    "tier": "research_grade",
                    "reason": str(virtual_scope_gate.get("reason")),
                }
            )

    terminal_scope_blocker = values.get("terminal_scope_blocker")
    terminal_scope_claim = None
    if not _virtual_all_terminal_scope_authorized(values, routing_gates):
        terminal_scope_claim = terminal_scope_blocked_claim(terminal_scope_blocker)
    if terminal_scope_claim:
        blocked.append(terminal_scope_claim)

    metrics_gate = _research_metric_gate(values)
    if metrics_gate["passed"]:
        allowed.append(
            {
                "claim": "research_metric_thresholds_passed",
                "tier": "research_grade",
                "basis": metrics_gate["reason"],
            }
        )
    else:
        blocked.append(
            {
                "claim": "research_metric_thresholds_passed",
                "tier": "research_grade",
                "reason": metrics_gate["reason"],
            }
        )

    improvement_gate = _calibration_improvement_gate(values)
    if improvement_gate["passed"]:
        allowed.append(
            {
                "claim": "calibration_improvement_verified",
                "tier": "research_grade",
                "basis": improvement_gate["reason"],
            }
        )
    else:
        blocked.append(
            {
                "claim": "calibration_improvement_verified",
                "tier": "research_grade",
                "reason": improvement_gate["reason"],
            }
        )

    sensitivity_gate = _sensitivity_gate(values)
    if sensitivity_gate["passed"]:
        allowed.append(
            {
                "claim": "basin_specific_sensitivity_screen_passed",
                "tier": "research_grade",
                "basis": sensitivity_gate["reason"],
            }
        )
    else:
        blocked.append(
            {
                "claim": "basin_specific_sensitivity_screen_passed",
                "tier": "research_grade",
                "reason": sensitivity_gate["reason"],
            }
        )

    soil_gate = _soil_fidelity_gate(values)
    if soil_gate["passed"]:
        allowed.append(
            {
                "claim": "soil_fidelity_gate_passed",
                "tier": "research_grade",
                "basis": soil_gate["reason"],
            }
        )
    else:
        blocked.append(
            {
                "claim": "soil_fidelity_gate_passed",
                "tier": "research_grade",
                "reason": soil_gate["reason"],
            }
        )

    if policy_notes:
        blocked.append(
            {
                "claim": "higher_tier_time_window_claim",
                "tier": requested_tier,
                "reason": ",".join(policy_notes),
            }
        )

    if values.get("calibration_locked_verification_succeeded") is True:
        allowed.append(
            {
                "claim": "locked_calibration_verification_completed",
                "tier": "diagnostic",
                "basis": "locked calibrated TxtInOut was independently rerun and improved",
            }
        )
    if calibration_success:
        allowed.append(
            {
                "claim": "calibration_attempt_completed",
                "tier": allowed_tier,
                "basis": "calibration_provenance.json reports success=true",
            }
        )
    else:
        blocked.append(
            {
                "claim": "calibrated_model_skill_claim",
                "tier": requested_tier,
                "reason": (
                    str(values.get("calibration_claim_status"))
                    if values.get("calibration_claim_status")
                    else "calibration_not_successful_or_not_attempted"
                ),
            }
        )
    return allowed, blocked


def _effective_claim_tier(
    *,
    allowed_tier: str,
    blocker: str | None,
    calibration_success: bool,
    values: dict[str, Any],
    physical_gates: dict[str, Any],
    routing_gates: dict[str, Any],
) -> str:
    """Return the highest claim tier supported by the completed evidence."""
    if allowed_tier == "exploratory" or blocker is not None:
        return "exploratory"

    fresh = _fresh_engine_gate(values)["passed"]
    locked = _benchmark_lock_gate(values)["passed"]
    outlet = _outlet_provenance_gate(values)["passed"]
    physical = str(physical_gates.get("status") or "unknown") == "passed"
    routing = str(routing_gates.get("status") or "unknown") == "passed"
    virtual_scope = _virtual_all_terminal_scope_gate(values, routing_gates)
    virtual_scope_passed = (not virtual_scope.get("applicable")) or bool(virtual_scope.get("passed"))
    terminal_scope = (
        not bool(_compact_str(values.get("terminal_scope_blocker")))
        or (bool(virtual_scope.get("applicable")) and bool(virtual_scope.get("passed")))
    )
    if not (fresh and locked and outlet and physical and routing and terminal_scope and virtual_scope_passed):
        return "exploratory"

    if allowed_tier not in {"research_grade", "publication_grade"}:
        return "diagnostic"

    if not (
        calibration_success
        and _research_metric_gate(values)["passed"]
        and _calibration_improvement_gate(values)["passed"]
    ):
        return "diagnostic"

    # Calibration and metric gates passed — now check sensitivity + soil fidelity.
    # publication_grade requires calibration evidence only (no sensitivity/soil requirement).
    # research_grade additionally requires basin-specific sensitivity screen + soil fidelity.
    # (C3 decision — documented in DECISIONS.md)
    soil = _soil_fidelity_gate(values)
    if _sensitivity_gate(values)["passed"] and soil["passed"]:
        return "research_grade"
    return "publication_grade"


def _research_metric_gate(values: dict[str, Any]) -> dict[str, Any]:
    return _research_metric_gate_impl(values)


def _soil_fidelity_gate(values: dict[str, Any]) -> dict[str, Any]:
    return _soil_fidelity_gate_impl(values)


def _metadata_note_value(metadata: dict[str, Any], key: str) -> str | None:
    notes = metadata.get("notes")
    if not isinstance(notes, list):
        return None
    prefix = f"{key}="
    for note in notes:
        text = str(note)
        if text.startswith(prefix):
            value = text[len(prefix) :].strip()
            return value or None
    return None


def _promote_soil_provenance_from_metadata(values: dict[str, Any], run_dir: Path) -> None:
    metadata_path = values.get("metadata_path") or (run_dir / "metadata.json")
    try:
        metadata = json.loads(Path(str(metadata_path)).read_text(encoding="utf-8"))
    except Exception:
        return
    if not values.get("soil_mode") and metadata.get("soil_mode"):
        values["soil_mode"] = metadata.get("soil_mode")
    provenance = metadata.get("soil_provenance_mode") or _metadata_note_value(
        metadata, "soil_provenance_mode"
    )
    if not values.get("soil_provenance_mode") and provenance:
        values["soil_provenance_mode"] = provenance
    if values.get("pct_fallback_soils") is None and metadata.get("pct_fallback_soils") is not None:
        values["pct_fallback_soils"] = metadata.get("pct_fallback_soils")
    if values.get("soil_overlay_gap_fraction") is None and metadata.get("soil_overlay_gap_fraction") is not None:
        values["soil_overlay_gap_fraction"] = metadata.get("soil_overlay_gap_fraction")


def _fresh_engine_gate(values: dict[str, Any]) -> dict[str, Any]:
    return _fresh_engine_gate_impl(values)


def _calibration_improvement_gate(values: dict[str, Any]) -> dict[str, Any]:
    return _calibration_improvement_gate_impl(values)


def _benchmark_lock_gate(values: dict[str, Any]) -> dict[str, Any]:
    return _benchmark_lock_gate_impl(values)


def _outlet_provenance_gate(values: dict[str, Any]) -> dict[str, Any]:
    return _outlet_provenance_gate_impl(values)


def _sensitivity_gate(values: dict[str, Any]) -> dict[str, Any]:
    return _sensitivity_gate_impl(
        values,
        required_params=_SENSITIVITY_REQUIRED,
        dead_params=_SENSITIVITY_DEAD,
    )


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if value is not None:
            return float(value)
    except Exception:
        return None
    return None


_MIN_YEARS_DIAGNOSTIC = 5
_MIN_YEARS_RESEARCH = 10
_MIN_WARMUP_YEARS = 3


def _period_split(start: str, end: str) -> dict[str, str]:
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    if s > e:
        raise ValueError("start must be <= end")
    years = list(range(s.year, e.year + 1))
    split_idx = max(1, int(round(len(years) * 0.6)))
    split_idx = min(split_idx, len(years) - 1)
    cal_start, cal_end = years[0], years[split_idx - 1]
    val_start, val_end = years[split_idx], years[-1]
    return {
        "calibration_start": f"{cal_start}-01-01",
        "calibration_end": f"{cal_end}-12-31",
        "validation_start": f"{val_start}-01-01",
        "validation_end": f"{val_end}-12-31",
        "policy_split": "chronological_60_40",
    }


def _allowed_claim_tier(req: RunUSGSWorkflowRequest) -> tuple[str, str | None, list[str]]:
    requested_tier = (req.claim_tier or "diagnostic").strip().lower()
    tier = requested_tier
    notes: list[str] = []
    years = datetime.fromisoformat(req.end).year - datetime.fromisoformat(req.start).year + 1

    if requested_tier in {"research_grade", "publication_grade"}:
        if req.contract_status not in {"accepted", "executed"} or req.accepted_by not in {"user", "policy"}:
            return "diagnostic", "contract_policy_blocked", notes
        # enforce research-grade minimum window policy
        if years < _MIN_YEARS_RESEARCH or int(req.warmup_years) < _MIN_WARMUP_YEARS:
            notes.append("window_short_for_research")
            return "diagnostic", "contract_policy_blocked", notes
    elif years < _MIN_YEARS_DIAGNOSTIC or int(req.warmup_years) < _MIN_WARMUP_YEARS:
        notes.append("window_short_for_diagnostic")
        tier = "exploratory"
    return tier, None, notes


def _relock_virtual_all_terminal_benchmark(
    out: Path,
    values: dict[str, Any],
    request: RunUSGSWorkflowRequest,
) -> None:
    txt = Path(str(values.get("txtinout_dir") or ""))
    if not txt.is_dir():
        raise RuntimeError("virtual outlet relock requires txtinout_dir")
    obs_path = Path(str(values.get("observed_csv") or ""))
    obs_series = _load_observed_series_for_relock(obs_path)
    sim_source = _compact_str(values.get("sim_source_file"))
    if sim_source is None:
        sim_source_path = _find_sim_source_for_relock(txt)
        if sim_source_path is None:
            raise RuntimeError("virtual outlet relock requires a simulation source file")
        sim_source = sim_source_path.name
    from ..calibration.locked_benchmark import lock_benchmark

    lock = lock_benchmark(
        txtinout_dir=txt,
        obs_series=obs_series,
        out_dir=out,
        basin_id=f"usgs_{request.usgs_id}",
        outlet_gis_id=int(values.get("requested_outlet_gis_id") or 1),
        sim_source_file=sim_source,
        virtual_outlet_policy="all_terminal_sum",
        virtual_outlet_authority=str(request.virtual_outlet_authority),
    )
    metrics_path = Path(lock.benchmark_dir) / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    outlet_prov_path = Path(lock.benchmark_dir) / "outlet_provenance.json"
    outlet_prov = (
        json.loads(outlet_prov_path.read_text(encoding="utf-8"))
        if outlet_prov_path.exists()
        else {}
    )
    values.update(
        {
            "benchmark_lock_path": str(Path(lock.benchmark_dir) / "benchmark_lock.json"),
            "benchmark_dir": lock.benchmark_dir,
            "requested_outlet_gis_id": outlet_prov.get("requested_outlet_gis_id", 1),
            "selected_outlet_gis_id": lock.outlet_gis_id,
            "selected_outlet_gis_ids": lock.selected_outlet_gis_ids,
            "outlet_scope": lock.outlet_scope,
            "outlet_policy": lock.outlet_policy,
            "virtual_outlet_authority": lock.virtual_outlet_authority,
            "virtual_outlet_claim_authority": lock.virtual_outlet_claim_authority,
            "outlet_autodetected": outlet_prov.get("outlet_autodetected"),
            "outlet_selection_reason": outlet_prov.get("outlet_selection_reason"),
            "terminal_outlet_ids": outlet_prov.get("terminal_outlet_ids", []),
            "terminal_outlet_count": len(outlet_prov.get("terminal_outlet_ids", [])),
            "sim_source_file": lock.sim_source_file,
            "baseline_nse": lock.baseline_nse,
            "baseline_kge": lock.baseline_kge,
            "metrics": metrics,
        }
    )


def _load_observed_series_for_relock(obs_csv: Path):
    if not obs_csv.is_file():
        raise RuntimeError(f"virtual outlet relock observed_csv missing: {obs_csv}")
    import pandas as pd

    df = pd.read_csv(obs_csv, index_col=0, parse_dates=True)
    if df.empty:
        raise RuntimeError(f"virtual outlet relock observed_csv empty: {obs_csv}")
    column = "obs" if "obs" in df.columns else "discharge" if "discharge" in df.columns else df.columns[0]
    index = pd.to_datetime(df.index).normalize()
    series = pd.Series(df[column].astype(float).to_numpy(), index=index, name="obs")
    series = series.dropna()
    if series.empty:
        raise RuntimeError(f"virtual outlet relock observed_csv has no valid observed rows: {obs_csv}")
    return series


def _find_sim_source_for_relock(txt: Path) -> Path | None:
    for name in ("basin_sd_cha_day.txt", "channel_sd_day.txt", "channel_day.txt"):
        candidate = txt / name
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def run_usgs_workflow(request: RunUSGSWorkflowRequest) -> RunUSGSWorkflowResult:
    out = Path(request.out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_id = f"usgs_{request.usgs_id}_{request.start.replace('-', '')}_{request.end.replace('-', '')}"
    events_path = out / "events.jsonl"
    events: list[dict[str, Any]] = []

    def _event(stage: str, status: str, **extra: Any) -> None:
        rec = {
            "time": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "run_id": run_id,
            "usgs_id": request.usgs_id,
            "stage": stage,
            "status": status,
            **extra,
        }
        events.append(rec)
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    if events_path.exists():
        events_path.unlink()
    _event("workflow", "started", usgs_id=request.usgs_id, model_family=request.model_family)

    allowed_tier, blocker, policy_notes = _allowed_claim_tier(request)
    contract_blocker = blocker
    if request.virtual_all_terminal_outlet:
        authority = _compact_str(request.virtual_outlet_authority)
        if authority is None:
            blocker = "virtual_outlet_authority_required"
            contract_blocker = blocker
            policy_notes = [*policy_notes, "virtual_all_terminal_outlet_requires_authority"]
    split = _period_split(request.start, request.end)
    _event("contract_policy", "passed" if blocker is None else "blocked", allowed_tier=allowed_tier, blocker_class=blocker)

    values: dict[str, Any] = {
        "requested_claim_tier": request.claim_tier,
        "claim_tier_allowed": allowed_tier,
        "model_family": request.model_family,
        "warmup_years": int(request.warmup_years),
        "start": request.start,
        "end": request.end,
        "window_years": datetime.fromisoformat(request.end).year - datetime.fromisoformat(request.start).year + 1,
        "policy_notes": policy_notes,
        "contract_path": request.contract_path,
        "virtual_all_terminal_outlet_requested": bool(request.virtual_all_terminal_outlet),
        "virtual_outlet_authority": request.virtual_outlet_authority,
        **split,
    }
    success = False
    status_msg = ""

    if blocker is None:
        try:
            _event("pipeline", "started")
            summary = run_pipeline(
                usgs_id=request.usgs_id,
                outdir=out,
                start_date=request.start,
                end_date=request.end,
                threads=1,
                engine_timeout_s=3600.0,
                model_family=request.model_family,
                warmup_years=request.warmup_years,
                allow_diagnostic_fallbacks=True,
            )
            values.update(summary if isinstance(summary, dict) else {"pipeline_summary": str(summary)})
            _promote_soil_provenance_from_metadata(values, out)
            build_diagnostics = _extract_build_diagnostic_artifacts(values)
            if build_diagnostics:
                values["build_diagnostic_artifacts"] = build_diagnostics
            pipeline_status = str(values.get("status", "")).upper()
            success = pipeline_status == "SUCCESS"
            if success:
                if request.virtual_all_terminal_outlet:
                    _event("benchmark_lock", "relocking_virtual_all_terminal")
                    _relock_virtual_all_terminal_benchmark(out, values, request)
                    _event(
                        "benchmark_lock",
                        "completed",
                        outlet_scope=values.get("outlet_scope"),
                        artifact=values.get("benchmark_lock_path"),
                    )
                status_msg = "pipeline_completed"
                _event("pipeline", "completed")
            else:
                blocker = str(values.get("blocker_class") or "pipeline_blocked")
                if blocker == "soil_realism_gate_failed":
                    values["soil_mode"] = "not_verified"
                    values["soil_provenance_mode"] = "soil_realism_gate_failed"
                    values["pct_fallback_soils"] = None
                status_msg = "pipeline_blocked"
                _event("pipeline", "blocked", blocker_class=blocker)
        except Exception as exc:
            blocker = "pipeline_failed"
            values["error"] = str(exc)
            status_msg = "pipeline_failed"
            _event("pipeline", "failed", error=str(exc)[-500:])
    else:
        status_msg = "contract_policy_blocked"

    physical_gates_payload = _evaluate_physical_gates(values)
    baseline_physical_gates_payload = dict(physical_gates_payload)
    values["physical_gates_status"] = physical_gates_payload.get("status")
    routing_gates_payload = _evaluate_routing_flow_gate(out, values)
    baseline_routing_gates_payload = dict(routing_gates_payload)
    values["routing_flow_gates_status"] = routing_gates_payload.get("status")
    if routing_gates_payload.get("json_path"):
        values["routing_flow_trace_path"] = routing_gates_payload.get("json_path")
    if routing_gates_payload.get("markdown_path"):
        values["routing_flow_trace_md"] = routing_gates_payload.get("markdown_path")
    if routing_gates_payload.get("closure_status"):
        values["routing_flow_closure_status"] = routing_gates_payload.get("closure_status")

    # Calibration orchestration (only after successful build/run and physical gates).
    # We persist attempt/provenance even when eligibility blocks or phase scripts fail.
    parameter_screen_payload: dict[str, Any]
    calibration_provenance_payload: dict[str, Any]
    if success and request.calibrate:
        governed_params = list(FULL_MODE_CORE_PARAMETERS + FULL_MODE_EXTENDED_PARAMETERS)
        _event("parameter_screen", "started", parameters=governed_params)
        parameter_screen_payload = {
            "basin_id": request.usgs_id,
            "model_family": request.model_family,
            "warnings": [
                "Governance screen only; basin-specific sensitivity evidence is required before research_grade calibration claims"
            ],
            "parameters": full_mode_screen_rows() + full_mode_extended_screen_rows(),
        }
        reports_dir = out / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        sjson = reports_dir / "sensitivity_screen.json"
        smd = reports_dir / "sensitivity_screen.md"
        sjson.write_text(json.dumps(parameter_screen_payload, indent=2) + "\n", encoding="utf-8")
        smd.write_text(_render_parameter_screen_md(parameter_screen_payload), encoding="utf-8")
        values["sensitivity_screen_path"] = str(sjson)
        values["sensitivity_screen_md"] = str(smd)
        values.setdefault(
            "sensitivity_screen_activity_classes",
            {
                str(p["parameter"]): str(p["activity_class"])
                for p in parameter_screen_payload["parameters"]
            },
        )
        values.setdefault("sensitivity_screen_basis", "governance_default")
        _event("parameter_screen", "completed", artifact=str(sjson))
        calibration_allowed, block_reason, calibration_sequence = _calibration_precheck(
            physical_gates_payload,
            routing_gates_payload,
        )
        precheck_provenance = {
            "physical_gates_status": physical_gates_payload.get("status"),
            "physical_gates": physical_gates_payload,
            "routing_flow_gates_status": routing_gates_payload.get("status"),
            "routing_flow_gates": routing_gates_payload,
            "calibration_sequence": calibration_sequence,
        }
        values["calibration_precheck_sequence"] = calibration_sequence
        values["calibration_precheck_physical_gates_status"] = physical_gates_payload.get("status")
        values["calibration_precheck_routing_flow_gates_status"] = routing_gates_payload.get("status")
        if block_reason:
            values["calibration_precheck_block_reason"] = block_reason
        if not calibration_allowed:
            values["calibration_attempted"] = False
            values["calibration_success"] = False
            values["calibration_status"] = (
                "blocked_by_physical_gates"
                if block_reason == "physical_gates_not_passed"
                else "blocked_by_routing_flow_gates"
            )
            calibration_provenance_payload = {
                "status": values["calibration_status"],
                "success": False,
                "reason": block_reason,
                "claim_tier": allowed_tier,
                "provenance": precheck_provenance,
                "phases": [],
            }
            _event("calibration", "blocked", reason=block_reason)
        else:
            _event("calibration", "started", sequence=calibration_sequence)
            cal = run_diagnostic_calibration(
                out,
                claim_tier=allowed_tier,
                strict=True,
            )
            values["calibration_attempted"] = True
            values["calibration_success"] = bool(cal.success)
            cal_provenance = dict(cal.provenance)
            cal_precheck = dict(precheck_provenance)
            cal_precheck["reason"] = None
            cal_provenance["calibration_precheck"] = cal_precheck
            cal_provenance["calibration_sequence"] = calibration_sequence
            cal_provenance["calibration_precheck_physical_gates_status"] = physical_gates_payload.get("status")
            cal_provenance["calibration_precheck_routing_flow_gates_status"] = routing_gates_payload.get("status")
            values["calibration_provenance"] = cal_provenance
            values["calibration_phases"] = [asdict(p) for p in cal.phases]
            if cal.success:
                values["calibration_status"] = "done"
            elif cal_provenance.get("locked_verification_succeeded") is True:
                values["calibration_status"] = "verified_diagnostic_claim_blocked"
            else:
                values["calibration_status"] = "attempted_failed_or_blocked"
            verification_metrics = cal_provenance.get("verification_metrics")
            if isinstance(verification_metrics, dict):
                values.setdefault("baseline_metrics", values.get("metrics", {}))
                values["calibrated_metrics"] = verification_metrics
                values["metrics"] = verification_metrics
            locked_txtinout = cal_provenance.get("locked_calibrated_txtinout")
            if locked_txtinout and values.get("sim_source_file"):
                locked_txtinout_path = Path(str(locked_txtinout))
                locked_sim_source = locked_txtinout_path / str(values["sim_source_file"])
                if locked_sim_source.is_file():
                    values["sim_source_path"] = str(locked_sim_source)
                locked_alignment = locked_txtinout_path / "alignment_calibration.csv"
                if locked_alignment.is_file():
                    values["alignment_csv"] = str(locked_alignment)
            delta_metrics = cal_provenance.get("verification_delta_metrics")
            if isinstance(delta_metrics, dict):
                values["calibration_delta_metrics"] = delta_metrics
            final_physical_gates = cal_provenance.get("final_physical_gates")
            if isinstance(final_physical_gates, dict):
                values["baseline_physical_gates_status"] = baseline_physical_gates_payload.get("status")
                values["baseline_physical_gates"] = baseline_physical_gates_payload
                values["final_physical_gates"] = final_physical_gates
                physical_gates_payload = final_physical_gates
                values["physical_gates_status"] = final_physical_gates.get("status")
            final_routing_flow_gates = cal_provenance.get("final_routing_flow_gates")
            if isinstance(final_routing_flow_gates, dict):
                values["baseline_routing_flow_gates_status"] = baseline_routing_gates_payload.get("status")
                values["baseline_routing_flow_gates"] = baseline_routing_gates_payload
                values["final_routing_flow_gates"] = final_routing_flow_gates
                routing_gates_payload = final_routing_flow_gates
                values["routing_flow_gates_status"] = final_routing_flow_gates.get("status")
                if final_routing_flow_gates.get("closure_status"):
                    values["routing_flow_closure_status"] = final_routing_flow_gates.get("closure_status")
            hydrograph = cal_provenance.get("hydrograph_comparison")
            if isinstance(hydrograph, dict):
                values["hydrograph_comparison_status"] = hydrograph.get("status")
                if hydrograph.get("hydrograph_plot"):
                    values["hydrograph_comparison_plot"] = hydrograph.get("hydrograph_plot")
                if hydrograph.get("hydrograph_plot_pdf"):
                    values["hydrograph_comparison_plot_pdf"] = hydrograph.get("hydrograph_plot_pdf")
                if hydrograph.get("hydrograph_overlay_plot"):
                    values["hydrograph_observed_simulated_calibrated_plot"] = hydrograph.get("hydrograph_overlay_plot")
                if hydrograph.get("hydrograph_overlay_plot_pdf"):
                    values["hydrograph_observed_simulated_calibrated_plot_pdf"] = hydrograph.get(
                        "hydrograph_overlay_plot_pdf"
                    )
                if hydrograph.get("hydrograph_metrics_json"):
                    values["hydrograph_comparison_metrics"] = hydrograph.get("hydrograph_metrics_json")
            skill_diagnostics = cal_provenance.get("skill_diagnostics")
            if isinstance(skill_diagnostics, dict):
                values["skill_diagnostics_status"] = skill_diagnostics.get("status")
                if skill_diagnostics.get("skill_diagnostics_json"):
                    values["skill_diagnostics_json"] = skill_diagnostics.get("skill_diagnostics_json")
                if skill_diagnostics.get("skill_diagnostics_md"):
                    values["skill_diagnostics_md"] = skill_diagnostics.get("skill_diagnostics_md")
                if isinstance(skill_diagnostics.get("skill_probe_gap_parameters"), list):
                    values["skill_probe_gap_parameters"] = skill_diagnostics.get("skill_probe_gap_parameters")
                if isinstance(skill_diagnostics.get("skill_screened_dead_parameters"), list):
                    values["skill_screened_dead_parameters"] = skill_diagnostics.get(
                        "skill_screened_dead_parameters"
                    )
                if isinstance(skill_diagnostics.get("skill_unscreened_suggested_parameters"), list):
                    values["skill_unscreened_suggested_parameters"] = skill_diagnostics.get(
                        "skill_unscreened_suggested_parameters"
                    )
            if cal_provenance.get("timing_limitation_documented") is not None:
                values["timing_limitation_documented"] = bool(
                    cal_provenance.get("timing_limitation_documented")
                )
            if cal_provenance.get("timing_limitation_basis"):
                values["timing_limitation_basis"] = cal_provenance.get("timing_limitation_basis")
            if cal_provenance.get("sensitivity_screen_basis"):
                values["sensitivity_screen_basis"] = cal_provenance.get("sensitivity_screen_basis")
                values["sensitivity_screen_path"] = cal_provenance.get("sensitivity_screen_path")
                values["sensitivity_screen_md"] = cal_provenance.get("sensitivity_screen_md")
                values["sensitivity_screen_activity_classes"] = cal_provenance.get(
                    "sensitivity_screen_activity_classes",
                    values.get("sensitivity_screen_activity_classes"),
                )
                sensitivity_path = values.get("sensitivity_screen_path")
                if sensitivity_path and Path(str(sensitivity_path)).is_file():
                    try:
                        parameter_screen_payload = json.loads(Path(str(sensitivity_path)).read_text(encoding="utf-8"))
                        parameter_screen_payload["model_family"] = request.model_family
                    except Exception:
                        pass
            calibration_provenance_payload = {
                "status": values["calibration_status"],
                "success": bool(cal.success),
                "claim_tier": allowed_tier,
                "provenance": cal_provenance,
                "phases": [asdict(p) for p in cal.phases],
            }
            _event("calibration", "completed" if cal.success else "blocked_or_failed", success=bool(cal.success))
    else:
        values["calibration_attempted"] = False
        values["calibration_success"] = False
        values["calibration_status"] = "not_attempted"
        parameter_screen_payload = {
            "status": "not_run",
            "reason": "pipeline_not_successful" if not success else "calibration_disabled",
            "usgs_id": request.usgs_id,
            "parameters": [],
        }
        values["sensitivity_screen_basis"] = "not_run"
        calibration_provenance_payload = {
            "status": "not_attempted",
            "success": False,
            "reason": "pipeline_not_successful" if not success else "calibration_disabled",
            "claim_tier": allowed_tier,
            "provenance": {},
            "phases": [],
        }
        _event("parameter_screen", "not_run", reason=parameter_screen_payload["reason"])
        _event("calibration", "not_attempted", reason=calibration_provenance_payload["reason"])

    parameter_screen_path = _write_json(out / "parameter_screen.json", parameter_screen_payload)
    calibration_provenance_path = _write_json(out / "calibration_provenance.json", calibration_provenance_payload)
    values["parameter_screen_path"] = str(parameter_screen_path)
    values["calibration_provenance_path"] = str(calibration_provenance_path)
    _promote_calibration_authority_values(values, calibration_provenance_payload)

    physical_gates_path = _write_json(out / "physical_gates.json", physical_gates_payload)
    values["physical_gates_path"] = str(physical_gates_path)
    routing_gates_path = _write_json(out / "routing_flow_gates.json", routing_gates_payload)
    values["routing_flow_gates_path"] = str(routing_gates_path)
    terminal_scope_blocker = _promote_terminal_scope_blocker_values(values, routing_gates_payload)
    if terminal_scope_blocker:
        provenance = calibration_provenance_payload.setdefault("provenance", {})
        if isinstance(provenance, dict):
            provenance.setdefault("terminal_scope_blocker", terminal_scope_blocker)
            provenance.setdefault("terminal_scope_blocker_source", "routing_flow_gates")
            _write_json(calibration_provenance_path, calibration_provenance_payload)

    # Outlet provenance artifact (minimal, machine-readable pointer for auditability).
    outlet_keys = (
        "requested_outlet_gis_id",
        "selected_outlet_gis_id",
        "selected_outlet_gis_ids",
        "outlet_scope",
        "outlet_policy",
        "virtual_outlet_authority",
        "virtual_outlet_claim_authority",
        "outlet_autodetected",
        "outlet_selection_reason",
        "terminal_outlet_ids",
        "terminal_outlet_count",
    )
    outlet_prov = {"usgs_id": request.usgs_id, "run_id": run_id}
    for k in outlet_keys:
        if k in values:
            outlet_prov[k] = values[k]
    outlet_path = out / "outlet_provenance.json"
    outlet_path.write_text(json.dumps(outlet_prov, indent=2) + "\n", encoding="utf-8")
    values["outlet_provenance_path"] = str(outlet_path)

    volume_diag_payload: dict[str, Any] | None = None
    physical_context_updates = _annotate_parameter_screen_for_physical_context(
        parameter_screen_payload,
        physical_gates_payload,
    )
    if physical_context_updates:
        _write_json(parameter_screen_path, parameter_screen_payload)
        _merge_parameter_context_values(values, physical_context_updates)
        if values.get("sensitivity_screen_path"):
            _write_json(Path(values["sensitivity_screen_path"]), parameter_screen_payload)
        if values.get("sensitivity_screen_md"):
            Path(values["sensitivity_screen_md"]).write_text(
                _render_parameter_screen_md(parameter_screen_payload),
                encoding="utf-8",
            )
        if calibration_provenance_payload.get("status") == "blocked_by_physical_gates":
            provenance = calibration_provenance_payload.setdefault("provenance", {})
            provenance["sensitivity_screen_context_flags"] = values.get("sensitivity_screen_context_flags")
            provenance["sensitivity_screen_effective_activity_classes"] = values.get(
                "sensitivity_screen_effective_activity_classes"
                )
            _write_json(calibration_provenance_path, calibration_provenance_payload)

    et_diag_payload: dict[str, Any] | None = None
    current_physical_codes = set(physical_gates_payload.get("condition_codes") or [])
    if "ET_DOMINATED" in current_physical_codes:
        try:
            _event("et_partition_diagnostics", "started")
            gate_context = "final_locked" if values.get("final_physical_gates") else "baseline"
            et_diag_payload = write_et_partition_diagnostics(
                out,
                physical_gates=physical_gates_payload,
                values=values,
                gate_context=gate_context,
                physical_gates_source_path=values.get("physical_gates_path"),
            )
            values["et_partition_diagnostics_path"] = et_diag_payload.get("json_path")
            values["et_partition_diagnostics_md"] = et_diag_payload.get("markdown_path")
            values["et_partition_gate_context"] = et_diag_payload.get("gate_context")
            values["et_partition_diagnostic_flags"] = [
                str(f.get("code"))
                for f in et_diag_payload.get("diagnostic_flags", [])
                if isinstance(f, dict) and f.get("code")
            ]
            values["et_partition_next_actions"] = [
                str(action)
                for action in et_diag_payload.get("next_actions", [])
                if isinstance(action, str) and action
            ]
            if calibration_provenance_payload.get("status") == "blocked_by_physical_gates":
                provenance = calibration_provenance_payload.setdefault("provenance", {})
                provenance["et_partition_diagnostics_path"] = et_diag_payload.get("json_path")
                provenance["et_partition_diagnostic_flags"] = values.get("et_partition_diagnostic_flags")
                provenance["et_partition_next_actions"] = values.get("et_partition_next_actions")
                _write_json(calibration_provenance_path, calibration_provenance_payload)
            _event(
                "et_partition_diagnostics",
                "completed",
                artifact=et_diag_payload.get("json_path"),
            )
        except Exception as exc:
            values["et_partition_diagnostics_error"] = str(exc)
            _event("et_partition_diagnostics", "failed", error=str(exc)[-500:])

    mass_diag_payload: dict[str, Any] | None = None
    if "MASS_IMBALANCE" in current_physical_codes:
        try:
            _event("mass_balance_diagnostics", "started")
            gate_context = "final_locked" if values.get("final_physical_gates") else "baseline"
            mass_diag_payload = write_mass_balance_diagnostics(
                out,
                physical_gates=physical_gates_payload,
                values=values,
                gate_context=gate_context,
                physical_gates_source_path=values.get("physical_gates_path"),
            )
            values["mass_balance_diagnostics_path"] = mass_diag_payload.get("json_path")
            values["mass_balance_diagnostics_md"] = mass_diag_payload.get("markdown_path")
            values["mass_balance_gate_context"] = mass_diag_payload.get("gate_context")
            values["mass_balance_diagnostic_flags"] = [
                str(f.get("code"))
                for f in mass_diag_payload.get("diagnostic_flags", [])
                if isinstance(f, dict) and f.get("code")
            ]
            values["mass_balance_next_actions"] = [
                str(action)
                for action in mass_diag_payload.get("next_actions", [])
                if isinstance(action, str) and action
            ]
            if calibration_provenance_payload.get("status") == "blocked_by_physical_gates":
                provenance = calibration_provenance_payload.setdefault("provenance", {})
                provenance["mass_balance_diagnostics_path"] = mass_diag_payload.get("json_path")
                provenance["mass_balance_diagnostic_flags"] = values.get("mass_balance_diagnostic_flags")
                provenance["mass_balance_next_actions"] = values.get("mass_balance_next_actions")
                _write_json(calibration_provenance_path, calibration_provenance_payload)
            _event(
                "mass_balance_diagnostics",
                "completed",
                artifact=mass_diag_payload.get("json_path"),
            )
        except Exception as exc:
            values["mass_balance_diagnostics_error"] = str(exc)
            _event("mass_balance_diagnostics", "failed", error=str(exc)[-500:])

    if (
        baseline_physical_gates_payload.get("dominant_blocker") == "VOLUME_BIAS"
        or "VOLUME_BIAS" in set(baseline_physical_gates_payload.get("condition_codes") or [])
        or bool(_compact_str(values.get("terminal_scope_blocker")))
    ):
        try:
            _event("volume_bias_diagnostics", "started")
            volume_diag_payload = write_volume_bias_diagnostics(
                out,
                physical_gates=physical_gates_payload,
                values=values,
            )
            values["volume_bias_diagnostics_path"] = volume_diag_payload.get("json_path")
            values["volume_bias_diagnostics_md"] = volume_diag_payload.get("markdown_path")
            values["volume_bias_primary_issue"] = volume_diag_payload.get("primary_issue")
            volume_terminal_scope_blocker = volume_diag_payload.get("terminal_scope_blocker")
            if volume_terminal_scope_blocker and not _virtual_all_terminal_scope_authorized(
                values,
                routing_gates_payload,
            ):
                values["terminal_scope_blocker"] = volume_terminal_scope_blocker
                values["terminal_scope_blocker_source"] = "volume_bias_diagnostics"
            elif volume_terminal_scope_blocker:
                values["terminal_scope_blocker"] = None
                values["terminal_scope_blocker_source"] = "virtual_outlet_scope_gate"
            terminal_scope_updates = _promote_terminal_hydrograph_scope_values(
                values,
                volume_diag_payload,
            )
            context_updates = _annotate_parameter_screen_for_volume_context(
                parameter_screen_payload,
                volume_diag_payload,
            )
            if context_updates:
                _write_json(parameter_screen_path, parameter_screen_payload)
                _merge_parameter_context_values(values, context_updates)
                if values.get("sensitivity_screen_path"):
                    _write_json(Path(values["sensitivity_screen_path"]), parameter_screen_payload)
                if values.get("sensitivity_screen_md"):
                    Path(values["sensitivity_screen_md"]).write_text(
                        _render_parameter_screen_md(parameter_screen_payload),
                        encoding="utf-8",
                    )
            terminal_scope_blocker = _compact_str(values.get("terminal_scope_blocker"))
            if terminal_scope_updates or terminal_scope_blocker:
                provenance = calibration_provenance_payload.setdefault("provenance", {})
                if terminal_scope_blocker:
                    provenance["terminal_scope_blocker"] = terminal_scope_blocker
                    source = _compact_str(values.get("terminal_scope_blocker_source"))
                    if source:
                        provenance.setdefault("terminal_scope_blocker_source", source)
                provenance.update(terminal_scope_updates)
                _write_json(calibration_provenance_path, calibration_provenance_payload)
            if calibration_provenance_payload.get("status") == "blocked_by_physical_gates":
                provenance = calibration_provenance_payload.setdefault("provenance", {})
                provenance["volume_bias_diagnostics_path"] = volume_diag_payload.get("json_path")
                provenance["volume_bias_primary_issue"] = volume_diag_payload.get("primary_issue")
                if terminal_scope_blocker:
                    provenance["terminal_scope_blocker"] = terminal_scope_blocker
                provenance.update(terminal_scope_updates)
                provenance["volume_bias_diagnostic_flags"] = [
                    str(f.get("code"))
                    for f in volume_diag_payload.get("diagnostic_flags", [])
                    if isinstance(f, dict) and f.get("code")
                ]
                if context_updates:
                    provenance["sensitivity_screen_context_flags"] = values.get("sensitivity_screen_context_flags")
                    provenance["sensitivity_screen_effective_activity_classes"] = values.get(
                        "sensitivity_screen_effective_activity_classes"
                    )
                _write_json(calibration_provenance_path, calibration_provenance_payload)
            _event(
                "volume_bias_diagnostics",
                "completed",
                artifact=volume_diag_payload.get("json_path"),
                primary_issue=volume_diag_payload.get("primary_issue"),
                terminal_scope_blocker=volume_diag_payload.get("terminal_scope_blocker"),
                terminal_hydrograph_scope_class=volume_diag_payload.get(
                    "terminal_hydrograph_scope_class"
                ),
            )
        except Exception as exc:
            values["volume_bias_diagnostics_error"] = str(exc)
            _event("volume_bias_diagnostics", "failed", error=str(exc)[-500:])

    allowed_claims, blocked_claims = _claim_lists(
        requested_tier=request.claim_tier,
        allowed_tier=allowed_tier,
        blocker=blocker,
        calibration_success=bool(values.get("calibration_success")),
        policy_notes=policy_notes,
        values=values,
        physical_gates=physical_gates_payload,
        routing_gates=routing_gates_payload,
    )

    run_manifest_path = out / "run_manifest.json"
    values["run_manifest_path"] = str(run_manifest_path)
    effective_claim_tier = _effective_claim_tier(
        allowed_tier=allowed_tier,
        blocker=blocker,
        calibration_success=bool(values.get("calibration_success")),
        values=values,
        physical_gates=physical_gates_payload,
        routing_gates=routing_gates_payload,
    )
    values["effective_claim_tier"] = effective_claim_tier

    gates_passed = ["contract_policy"] if contract_blocker is None else []
    gates_failed = ["contract_policy"] if contract_blocker is not None else []
    physical_status = str(physical_gates_payload.get("status") or "unknown")
    if physical_status == "passed":
        gates_passed.append("physical_gates")
    elif physical_status == "failed":
        gates_failed.append("physical_gates")
    routing_status = str(routing_gates_payload.get("status") or "unknown")
    if routing_status == "passed":
        gates_passed.append("routing_flow")
    elif routing_status in {"failed", "warning", "not_run"}:
        gates_failed.append("routing_flow")
    if _fresh_engine_gate(values)["passed"]:
        gates_passed.append("fresh_engine_output")
    else:
        gates_failed.append("fresh_engine_output")
    if _benchmark_lock_gate(values)["passed"]:
        gates_passed.append("benchmark_lock")
    else:
        gates_failed.append("benchmark_lock")
    if _outlet_provenance_gate(values)["passed"]:
        gates_passed.append("outlet_provenance")
    else:
        gates_failed.append("outlet_provenance")
    if _sensitivity_gate(values)["passed"]:
        gates_passed.append("sensitivity_screen")
    else:
        gates_failed.append("sensitivity_screen")
    if _soil_fidelity_gate(values)["passed"]:
        gates_passed.append("soil_fidelity")
    else:
        gates_failed.append("soil_fidelity")
    if _calibration_improvement_gate(values)["passed"]:
        gates_passed.append("calibration_verification")
    elif values.get("calibration_attempted") or str(values.get("calibration_status") or "").startswith("blocked_by_"):
        gates_failed.append("calibration_verification")

    evidence_md_path = out / "EVIDENCE_SUMMARY.md"
    values["evidence_summary_md_path"] = str(evidence_md_path)

    payload = {
        "run_id": run_id,
        "usgs_id": request.usgs_id,
        "success": bool(success),
        "artifact_dir": str(out),
        "claim_tier": allowed_tier,
        "effective_claim_tier": effective_claim_tier,
        "contract_status": request.contract_status,
        "accepted_by": request.accepted_by,
        "gates_passed": gates_passed,
        "gates_failed": gates_failed,
        "blocker_class": blocker,
        "status": status_msg,
        "allowed_claims": allowed_claims,
        "blocked_claims": blocked_claims,
        "values": values,
    }
    payload["provenance_hash"] = _provenance_hash(payload)

    path = out / "evidence_summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    evidence_md_path.write_text(_render_evidence_summary_md(payload), encoding="utf-8")

    # Write schema-versioned evidence bundle alongside the legacy format.
    try:
        from ..evidence import write_evidence_v1
        write_evidence_v1(payload, out)
    except Exception:
        pass  # never let v1 write failure abort the run

    _event("workflow", "completed", success=bool(success), evidence_summary=str(path))
    manifest_payload = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_sha": _git_sha(),
        "request": asdict(request),
        "status": status_msg,
        "success": bool(success),
        "artifact_dir": str(out),
        "artifacts": {
            "evidence_summary": str(path),
            "evidence_summary_md": str(evidence_md_path),
            "outlet_provenance": str(outlet_path),
            "calibration_provenance": str(calibration_provenance_path),
            "parameter_screen": str(parameter_screen_path),
            "physical_gates": str(physical_gates_path),
            "routing_flow_gates": str(routing_gates_path),
            **(
                {"hydrograph_comparison_plot": str(values.get("hydrograph_comparison_plot"))}
                if values.get("hydrograph_comparison_plot")
                else {}
            ),
            **(
                {"hydrograph_comparison_plot_pdf": str(values.get("hydrograph_comparison_plot_pdf"))}
                if values.get("hydrograph_comparison_plot_pdf")
                else {}
            ),
            **(
                {
                    "hydrograph_observed_simulated_calibrated_plot": str(
                        values.get("hydrograph_observed_simulated_calibrated_plot")
                    )
                }
                if values.get("hydrograph_observed_simulated_calibrated_plot")
                else {}
            ),
            **(
                {
                    "hydrograph_observed_simulated_calibrated_plot_pdf": str(
                        values.get("hydrograph_observed_simulated_calibrated_plot_pdf")
                    )
                }
                if values.get("hydrograph_observed_simulated_calibrated_plot_pdf")
                else {}
            ),
            **(
                {"hydrograph_comparison_metrics": str(values.get("hydrograph_comparison_metrics"))}
                if values.get("hydrograph_comparison_metrics")
                else {}
            ),
            **(
                {"skill_diagnostics_json": str(values.get("skill_diagnostics_json"))}
                if values.get("skill_diagnostics_json")
                else {}
            ),
            **(
                {"skill_diagnostics_md": str(values.get("skill_diagnostics_md"))}
                if values.get("skill_diagnostics_md")
                else {}
            ),
            **(
                {"volume_bias_diagnostics": str(volume_diag_payload.get("json_path"))}
                if volume_diag_payload and volume_diag_payload.get("json_path")
                else {}
            ),
            **{
                f"build_{key}": str(path)
                for key, path in (values.get("build_diagnostic_artifacts") or {}).items()
            },
            "events": str(events_path),
        },
        "events_recorded": len(events),
    }
    _write_json(run_manifest_path, manifest_payload)

    return RunUSGSWorkflowResult(
        success=bool(success),
        run_id=run_id,
        artifact_dir=str(out),
        evidence_summary_path=str(path),
        blocker_class=blocker,
        values=values,
    )


def _extract_build_diagnostic_artifacts(values: dict[str, Any]) -> dict[str, str]:
    build = values.get("build")
    if not isinstance(build, dict):
        return {}
    artifacts = build.get("diagnostic_artifacts")
    if not isinstance(artifacts, dict):
        return {}
    out: dict[str, str] = {}
    for key, path in artifacts.items():
        if not key or not path:
            continue
        out[str(key)] = str(path)
    return out


def _render_evidence_summary_md(payload: dict[str, Any]) -> str:
    values = payload.get("values", {})
    if not isinstance(values, dict):
        values = {}
    lines = [
        "# Evidence Summary",
        "",
        f"- Run ID: `{payload.get('run_id')}`",
        f"- USGS ID: `{payload.get('usgs_id')}`",
        f"- Success: `{payload.get('success')}`",
        f"- Requested/allowed claim tier: `{payload.get('claim_tier')}`",
        f"- Effective claim tier: `{payload.get('effective_claim_tier')}`",
        f"- Blocker class: `{payload.get('blocker_class') or 'none'}`",
        f"- Contract status: `{payload.get('contract_status') or 'unspecified'}`",
        f"- Accepted by: `{payload.get('accepted_by') or 'unspecified'}`",
        "",
        "## Gates",
        "",
        f"- Passed: `{', '.join(payload.get('gates_passed') or []) or 'none'}`",
        f"- Failed: `{', '.join(payload.get('gates_failed') or []) or 'none'}`",
        f"- Physical gates: `{values.get('physical_gates_status') or 'unknown'}`",
        f"- Routing flow gates: `{values.get('routing_flow_gates_status') or 'unknown'}`",
        f"- Calibration status: `{values.get('calibration_status') or 'unknown'}`",
        "",
        "## Key Metrics",
        "",
    ]
    metrics = values.get("metrics")
    if isinstance(metrics, dict) and metrics:
        for key in ("kge", "nse", "pbias", "pbias_pct"):
            if key in metrics:
                lines.append(f"- {key.upper()}: `{metrics.get(key)}`")
    else:
        lines.append("- Metrics: `not_available`")

    lines += ["", "## Allowed Claims", ""]
    allowed = payload.get("allowed_claims") or []
    if allowed:
        lines += ["| Claim | Tier | Basis |", "|---|---|---|"]
        for claim in allowed:
            if isinstance(claim, dict):
                lines.append(
                    f"| `{claim.get('claim')}` | `{claim.get('tier', 'n/a')}` | {claim.get('basis', '')} |"
                )
    else:
        lines.append("- none")

    lines += ["", "## Blocked Claims", ""]
    blocked = payload.get("blocked_claims") or []
    if blocked:
        lines += ["| Claim | Tier | Reason |", "|---|---|---|"]
        for claim in blocked:
            if isinstance(claim, dict):
                lines.append(
                    f"| `{claim.get('claim')}` | `{claim.get('tier', 'n/a')}` | {claim.get('reason', '')} |"
                )
    else:
        lines.append("- none")

    lines += [
        "",
        "## Artifact Pointers",
        "",
        f"- JSON summary: `{Path(payload.get('artifact_dir', ''), 'evidence_summary.json')}`",
        f"- Run manifest: `{values.get('run_manifest_path') or 'not_written'}`",
        f"- Events: `{Path(payload.get('artifact_dir', ''), 'events.jsonl')}`",
    ]
    if values.get("hydrograph_comparison_plot"):
        lines.append(f"- Hydrograph comparison: `{values.get('hydrograph_comparison_plot')}`")
    if values.get("hydrograph_comparison_plot_pdf"):
        lines.append(f"- Hydrograph comparison PDF: `{values.get('hydrograph_comparison_plot_pdf')}`")
    if values.get("hydrograph_observed_simulated_calibrated_plot"):
        lines.append(
            "- Observed/simulated/calibrated hydrograph: "
            f"`{values.get('hydrograph_observed_simulated_calibrated_plot')}`"
        )
    if values.get("hydrograph_observed_simulated_calibrated_plot_pdf"):
        lines.append(
            "- Observed/simulated/calibrated hydrograph PDF: "
            f"`{values.get('hydrograph_observed_simulated_calibrated_plot_pdf')}`"
        )
    if values.get("hydrograph_comparison_metrics"):
        lines.append(f"- Hydrograph comparison metrics: `{values.get('hydrograph_comparison_metrics')}`")
    if values.get("skill_diagnostics_json"):
        lines.append(f"- Skill diagnostics JSON: `{values.get('skill_diagnostics_json')}`")
    if values.get("skill_diagnostics_md"):
        lines.append(f"- Skill diagnostics report: `{values.get('skill_diagnostics_md')}`")
    lines.append("")
    return "\n".join(lines)


def _render_parameter_screen_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Calibration Sensitivity Screen",
        "",
        f"- Basin: `{payload.get('basin_id') or 'n/a'}`",
        f"- Model family: `{payload.get('model_family') or 'n/a'}`",
        "",
        "| Parameter | Activity | Basin context | Target | Claim allowance |",
        "|---|---|---|---|---|",
    ]
    for row in payload.get("parameters", []):
        evidence = row.get("evidence", {}) if isinstance(row, dict) else {}
        context = row.get("basin_context", {}) if isinstance(row, dict) else {}
        effective = context.get("effective_activity_class") if isinstance(context, dict) else None
        context_text = f"`{effective}`" if effective else "`n/a`"
        target = f"{evidence.get('target_file', 'n/a')}:{evidence.get('target_column', 'n/a')}"
        lines.append(
            f"| `{row.get('parameter')}` | `{row.get('activity_class')}` | {context_text} | `{target}` | `{evidence.get('claim_tier_allowance', 'n/a')}` |"
        )
    warnings = payload.get("warnings") or []
    if warnings:
        lines += ["", "## Warnings"] + [f"- {w}" for w in warnings]
    return "\n".join(lines) + "\n"


def _annotate_parameter_screen_for_volume_context(
    payload: dict[str, Any],
    volume_diag: dict[str, Any],
) -> dict[str, Any]:
    """Add basin-context applicability without changing global governance."""
    flags = {str(f.get("code")) for f in volume_diag.get("diagnostic_flags", []) if isinstance(f, dict)}
    urban = volume_diag.get("urban_assumptions", {})
    if not isinstance(urban, dict):
        urban = {}
    context_flags: list[str] = []
    effective_classes: dict[str, str] = {}

    if "urban_curve_number_fixed_high" in flags:
        context_flags.append("cn2_runtime_cn_table_scope_required")
        for row in payload.get("parameters", []):
            if not isinstance(row, dict) or row.get("parameter") != "CN2":
                continue
            row["basin_context"] = {
                "effective_activity_class": "active",
                "reason": (
                    "This basin is dominated by urban HRUs whose runtime curve number is "
                    "selected by landuse.lum:cn2 from cntable.lum; the full-mode CN2 "
                    "bridge must include the referenced cntable.lum urban row."
                ),
                "urban_hru_fraction": urban.get("urban_hru_fraction"),
                "hru_weighted_urb_cn": urban.get("hru_weighted_urb_cn"),
                "recommended_next_action": (
                    "Verify the landuse.lum:cn2 -> cntable.lum urban curve-number "
                    "link during CN2 calibration."
                ),
            }
            effective_classes["CN2"] = "active"
            break

    if context_flags:
        warnings = payload.setdefault("warnings", [])
        warning = (
            "Basin-context screen: dominant runoff uses landuse.lum:cn2 -> cntable.lum; "
            "CN2 calibration must include referenced cntable.lum urban rows."
        )
        if warning not in warnings:
            warnings.append(warning)
    return {"flags": context_flags, "effective_activity_classes": effective_classes} if context_flags else {}


def _annotate_parameter_screen_for_physical_context(
    payload: dict[str, Any],
    physical_gates: dict[str, Any],
) -> dict[str, Any]:
    """Annotate parameter applicability for physical blockers without relaxing gates."""
    codes = {str(code) for code in physical_gates.get("condition_codes", [])}
    if "ET_DOMINATED" not in codes:
        return {}
    wb = physical_gates.get("wb") if isinstance(physical_gates.get("wb"), dict) else {}
    precip = _safe_float(wb.get("precip"))
    et = _safe_float(wb.get("et", wb.get("et_act")))
    pet = _safe_float(wb.get("pet"))
    esoil = _safe_float(wb.get("esoil"))
    eplant = _safe_float(wb.get("eplant"))
    et_to_precip = _ratio(et, precip)
    pet_to_precip = _ratio(pet, precip)
    esoil_to_et = _ratio(esoil, et)
    eplant_to_et = _ratio(eplant, et)

    targets = {
        "PET_CO": "Potential ET coefficient controls ET demand scaling and should be screened within documented range.",
        "ESCO": "Soil evaporation compensation controls depth distribution of soil evaporative demand.",
        "EPCO": "Plant uptake compensation controls plant water uptake depth and transpiration partitioning.",
    }
    effective_classes: dict[str, str] = {}
    for row in payload.get("parameters", []):
        if not isinstance(row, dict) or row.get("parameter") not in targets:
            continue
        name = str(row["parameter"])
        row["basin_context"] = {
            "effective_activity_class": "requires_basin_screen",
            "reason": targets[name],
            "et_to_precip": et_to_precip,
            "pet_to_precip": pet_to_precip,
            "esoil_to_et": esoil_to_et,
            "eplant_to_et": eplant_to_et,
            "recommended_next_action": (
                "Run a governed ET-partition sensitivity probe before calibration; "
                "do not treat streamflow metrics alone as ET realism evidence."
            ),
        }
        effective_classes[name] = "requires_basin_screen"

    warnings = payload.setdefault("warnings", [])
    warning = (
        "Basin-context screen: ET_DOMINATED physical gate requires PET_CO/ESCO/EPCO "
        "and ET partition diagnostics before calibration or research-grade claims."
    )
    if warning not in warnings:
        warnings.append(warning)
    return {
        "flags": ["et_dominated_pet_esco_epco_probe_required"],
        "effective_activity_classes": effective_classes,
    }


def _merge_parameter_context_values(values: dict[str, Any], updates: dict[str, Any]) -> None:
    flags = [
        str(flag)
        for flag in values.get("sensitivity_screen_context_flags", [])
        if isinstance(flag, str)
    ]
    for flag in updates.get("flags", []):
        if isinstance(flag, str) and flag not in flags:
            flags.append(flag)
    effective = values.get("sensitivity_screen_effective_activity_classes")
    if not isinstance(effective, dict):
        effective = {}
    for key, value in updates.get("effective_activity_classes", {}).items():
        effective[str(key)] = str(value)
    values["sensitivity_screen_context_flags"] = flags
    values["sensitivity_screen_effective_activity_classes"] = effective


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0.0):
        return None
    return float(num / den)


def _calibration_precheck(
    physical_gates: dict[str, Any],
    routing_gates: dict[str, Any],
) -> tuple[bool, str | None, str]:
    if bool(routing_gates.get("calibration_blocking", routing_gates.get("status") != "passed")):
        return False, "routing_flow_gates_not_passed", "blocked_before_volume_stage"

    physical_status = str(physical_gates.get("status") or "unknown")
    if physical_status == "passed":
        return True, None, "physical_gates_passed"

    condition_codes = {str(c) for c in physical_gates.get("condition_codes") or []}
    dominant = str(physical_gates.get("dominant_blocker") or "")
    calibratable_metric_codes = {"VOLUME_BIAS", "ET_DOMINATED", "NEGATIVE_SKILL", "BELOW_RESEARCH_SKILL"}
    calibration_blocking_physical_codes = {"ZERO_SURFACE_RUNOFF"}
    if condition_codes and not (condition_codes & calibration_blocking_physical_codes):
        has_calibration_target = bool(condition_codes & calibratable_metric_codes)
        mass_only = condition_codes == {"MASS_IMBALANCE"}
        if has_calibration_target and not mass_only:
            if dominant == "VOLUME_BIAS" or "VOLUME_BIAS" in condition_codes:
                return True, None, "volume_bias_repair_before_final_physical_gate"
            if dominant == "ET_DOMINATED" or "ET_DOMINATED" in condition_codes:
                return True, None, "et_partition_repair_before_final_physical_gate"
            return True, None, "metric_skill_repair_before_final_research_gate"

    return False, "physical_gates_not_passed", "blocked_before_volume_stage"


def _evaluate_physical_gates(values: dict[str, Any]) -> dict[str, Any]:
    txt = values.get("txtinout_dir")
    if not txt:
        return {
            "status": "not_run",
            "pass": False,
            "reason": "txtinout_dir_missing",
        }
    metrics = values.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    try:
        from ..full_mode.water_balance_gate import check_water_balance

        result = check_water_balance(
            txt,
            nse=_as_float(metrics.get("nse", values.get("baseline_nse"))),
            kge=_as_float(metrics.get("kge", values.get("baseline_kge"))),
            pbias=_as_float(metrics.get("pbias")),
        )
        return {
            "status": "passed" if result.get("pass") else "failed",
            **result,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "pass": False,
            "reason": str(exc),
            "blocked_tiers": {
                "diagnostic": [str(exc)],
                "research_grade": [str(exc)],
            },
        }


def _evaluate_routing_flow_gate(run_dir: Path, values: dict[str, Any]) -> dict[str, Any]:
    """Require generated basin water to reach routed terminal channel output."""
    txt = values.get("txtinout_dir")
    if not txt:
        return {
            "status": "not_run",
            "pass": False,
            "reason": "txtinout_dir_missing",
            "blocked_tiers": {
                "diagnostic": ["routing flow gate could not run because txtinout_dir is missing"],
                "research_grade": ["routing flow gate could not run because txtinout_dir is missing"],
            },
        }
    try:
        from ..output.mass_trace import trace_mass_balance

        report = trace_mass_balance(
            run_dir,
            basin_id=str(values.get("usgs_id") or values.get("basin_id") or "unknown"),
        )
    except Exception as exc:
        return {
            "status": "not_run",
            "pass": False,
            "reason": str(exc),
            "blocked_tiers": {
                "diagnostic": [f"routing flow gate could not run: {exc}"],
                "research_grade": [f"routing flow gate could not run: {exc}"],
            },
        }

    closure_status = str(report.closure_status)
    hard_blockers = {
        "fail_no_land_generation",
        "fail_outlet_selection",
        "fail_hru_to_channel",
        "fail_lte_transfer_scale",
        "fail_channel_entry",
        "insufficient_data",
    }
    calibration_blocking = closure_status in hard_blockers
    passed = closure_status == "pass"
    status = "passed" if passed else ("failed" if calibration_blocking else "warning")
    reason = "routing flow closure passed" if passed else f"routing flow closure status={closure_status}"
    flags = list(report.flags or [])
    terminal_trace: dict[str, Any] = {}
    if "multiple_terminal_outlets_present" in flags or _is_virtual_all_terminal_scope(values):
        try:
            from ..output.mass_trace import trace_terminal_inventory

            terminal_report = trace_terminal_inventory(
                run_dir,
                basin_id=str(values.get("usgs_id") or values.get("basin_id") or "unknown"),
                selected_outlet_gis_id=report.selected_outlet_gis_id,
                fetch_usgs_site_area=True,
            )
            terminal_trace = {
                "terminal_trace_path": str(run_dir / "reports" / "terminal_trace.json"),
                "terminal_trace_md": str(run_dir / "reports" / "terminal_trace.md"),
                "terminal_failure_class": terminal_report.failure_class,
                "terminal_inventory_count": len(terminal_report.terminal_inventory),
                "terminal_shared_upstream_area_km2": terminal_report.shared_upstream_area_km2,
                "terminal_overlap_pair_count": len(terminal_report.terminal_overlap_pairs),
                "terminal_overlap_pairs": [
                    row.model_dump()
                    for row in terminal_report.terminal_overlap_pairs[:10]
                ],
            }
        except Exception as exc:
            terminal_trace = {
                "terminal_trace_error": str(exc),
            }
    virtual_scope_payload = {
        "terminal_outlet_count": report.terminal_outlet_count,
        "terminal_overlap_pair_count": terminal_trace.get("terminal_overlap_pair_count"),
        "terminal_shared_upstream_area_km2": terminal_trace.get("terminal_shared_upstream_area_km2"),
        "all_terminal_routed_to_channel_closure_ratio": getattr(
            report, "all_terminal_routed_to_channel_closure_ratio", None
        ),
        "all_terminal_mass_closure_ratio": getattr(report, "all_terminal_mass_closure_ratio", None),
        "all_terminal_outflow_m3": report.all_terminal_outflow_m3,
    }
    virtual_scope_gate = _virtual_all_terminal_scope_gate(values, virtual_scope_payload)
    if virtual_scope_gate.get("applicable"):
        passed = bool(virtual_scope_gate.get("passed"))
        calibration_blocking = not passed
        status = "passed" if passed else "failed"
        reason = str(virtual_scope_gate.get("reason") or reason)
        closure_status = "pass" if passed else "fail_virtual_all_terminal_scope"

    condition_codes = (
        []
        if passed
        else list(virtual_scope_gate.get("blockers") or [closure_status])
        if virtual_scope_gate.get("applicable")
        else [closure_status]
    )
    payload = {
        "status": status,
        "pass": passed,
        "calibration_blocking": calibration_blocking,
        "research_grade_blocking": not passed,
        "reason": reason,
        "closure_status": closure_status,
        "flags": flags,
        "condition_codes": condition_codes,
        "selected_outlet_gis_id": report.selected_outlet_gis_id,
        "selected_outlet_is_terminal": report.selected_outlet_is_terminal,
        "terminal_outlet_count": report.terminal_outlet_count,
        "basin_wateryld_m3": report.basin_wateryld_m3,
        "basin_routed_to_channel_m3": getattr(report, "basin_routed_to_channel_m3", None),
        "routed_to_channel_closure_ratio": getattr(report, "routed_to_channel_closure_ratio", None),
        "all_terminal_routed_to_channel_closure_ratio": getattr(
            report, "all_terminal_routed_to_channel_closure_ratio", None
        ),
        "all_terminal_mass_closure_ratio": getattr(report, "all_terminal_mass_closure_ratio", None),
        "selected_terminal_fraction_of_all_terminal_flow": getattr(
            report, "selected_terminal_fraction_of_all_terminal_flow", None
        ),
        "closure_reference": getattr(report, "closure_reference", "basin_wateryld_m3"),
        "hru_wateryld_m3": report.hru_wateryld_m3,
        "ru_outflow_m3": report.ru_outflow_m3,
        "channel_inflow_m3": report.channel_inflow_m3,
        "terminal_outflow_m3": report.terminal_outflow_m3,
        "all_terminal_outflow_m3": report.all_terminal_outflow_m3,
        "mass_closure_ratio": report.mass_closure_ratio,
        "mass_trace_basin_wb_source_file": report.basin_wb_source_file,
        "mass_trace_basin_wb_row_count": report.basin_wb_row_count,
        "mass_trace_basin_wb_years": report.basin_wb_years,
        "mass_trace_channel_source_file": report.channel_source_file,
        "mass_trace_channel_row_count": report.channel_row_count,
        "mass_trace_channel_years": report.channel_years,
        "mass_trace_selected_channel_row_count": report.selected_channel_row_count,
        "mass_trace_selected_channel_years": report.selected_channel_years,
        "mass_trace_terminal_channel_row_count": report.terminal_channel_row_count,
        "mass_trace_terminal_channel_years": report.terminal_channel_years,
        "json_path": str(run_dir / "reports" / "mass_trace.json"),
        "markdown_path": str(run_dir / "reports" / "mass_trace.md"),
        "extended_diagnostics": {
            "ru_outflow_to_basin_wateryld_ratio": report.ru_outflow_to_basin_wateryld_ratio,
        },
        "blocked_tiers": {}
        if passed
        else {
            "research_grade": [reason],
        }
        if not calibration_blocking
        else {
            "diagnostic": [reason],
            "research_grade": [reason],
        },
        "recommended_next_action": _routing_flow_next_action(flags, passed=passed, calibration_blocking=calibration_blocking),
        **terminal_trace,
    }
    if virtual_scope_gate.get("applicable"):
        payload["virtual_outlet_scope_gate"] = virtual_scope_gate
        payload["virtual_outlet_scope_gate_status"] = virtual_scope_gate.get("status")
        payload["recommended_next_action"] = (
            "Proceed with same-scope virtual all-terminal calibration and final claim gates."
            if passed
            else "Repair or document virtual all-terminal topology/authority/closure before calibration claims."
        )
    return payload


def _routing_flow_next_action(flags: list[str], *, passed: bool, calibration_blocking: bool) -> str:
    if passed:
        return "No routing-flow action required."
    flag_set = set(flags)
    if "channel_inflow_exceeds_basin_wateryld" in flag_set:
        return (
            "Inspect routing-unit to channel transfer and SWAT+ output unit interpretation; "
            "selected-channel inflow exceeds basin water yield."
        )
    if "multiple_terminal_outlets_present" in flag_set:
        return "Review terminal outlet inventory and gauge-to-terminal selection before aggregating or claiming research-grade flow."
    if not calibration_blocking:
        return "Mass-closure mismatch is retained as a research-grade blocker; diagnostic calibration may proceed."
    return "Inspect HRU-to-channel transfer, terminal outlet selection, and channel routing before calibration."
