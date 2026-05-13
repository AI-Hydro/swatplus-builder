"""USGS E2E workflow wrapper for agent-governed execution.

This lightweight implementation uses existing `orchestrate.run_pipeline` and
writes a canonical evidence summary JSON with claim/provenance fields.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import SwatBuilderExternalError
from ..orchestrate import run_pipeline
from ..calibration.sensitivity_screen import screen_from_parameter_list, write_screen_artifacts
from ..calibration.diagnostic_calibrator import run_diagnostic_calibration


@dataclass
class RunUSGSWorkflowRequest:
    usgs_id: str
    out_dir: Path
    start: str = "2000-01-01"
    end: str = "2019-12-31"
    warmup_years: int = 2
    claim_tier: str = "diagnostic"
    contract_status: str | None = None
    accepted_by: str | None = None
    calibrate: bool = True


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
        "contract_status": payload.get("contract_status"),
        "accepted_by": payload.get("accepted_by"),
        "values": payload.get("values", {}),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode("utf-8")).hexdigest()


_MIN_YEARS_DIAGNOSTIC = 5
_MIN_YEARS_RESEARCH = 10
_MIN_WARMUP_YEARS = 2


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


def run_usgs_workflow(request: RunUSGSWorkflowRequest) -> RunUSGSWorkflowResult:
    out = Path(request.out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    allowed_tier, blocker, policy_notes = _allowed_claim_tier(request)
    run_id = f"usgs_{request.usgs_id}_{request.start.replace('-', '')}_{request.end.replace('-', '')}"
    split = _period_split(request.start, request.end)

    values: dict[str, Any] = {
        "requested_claim_tier": request.claim_tier,
        "claim_tier_allowed": allowed_tier,
        "warmup_years": int(request.warmup_years),
        "start": request.start,
        "end": request.end,
        "window_years": datetime.fromisoformat(request.end).year - datetime.fromisoformat(request.start).year + 1,
        "policy_notes": policy_notes,
        **split,
    }
    success = False
    status_msg = ""

    if blocker is None:
        try:
            summary = run_pipeline(
                usgs_id=request.usgs_id,
                outdir=out,
                threads=1,
                engine_timeout_s=3600.0,
            )
            values.update(summary if isinstance(summary, dict) else {"pipeline_summary": str(summary)})
            success = True
            status_msg = "pipeline_completed"
        except Exception as exc:
            blocker = "pipeline_failed"
            values["error"] = str(exc)
            status_msg = "pipeline_failed"
    else:
        status_msg = "contract_policy_blocked"

    # Calibration orchestration (only after successful build/run).
    # We persist attempt/provenance even when eligibility blocks or phase scripts fail.
    if success and request.calibrate:
        core_params = ["CN2", "ALPHA_BF", "SOL_K", "ESCO", "SURLAG"]
        screen = screen_from_parameter_list(core_params, basin_id=request.usgs_id)
        sjson, smd = write_screen_artifacts(screen, out / "reports")
        values["sensitivity_screen_path"] = str(sjson)
        values["sensitivity_screen_md"] = str(smd)
        values["sensitivity_screen_activity_classes"] = {
            p.parameter: p.activity_class for p in screen.parameters
        }
        cal = run_diagnostic_calibration(
            out,
            claim_tier=allowed_tier,
            strict=True,
        )
        values["calibration_attempted"] = True
        values["calibration_success"] = bool(cal.success)
        values["calibration_provenance"] = cal.provenance
        values["calibration_phases"] = [asdict(p) for p in cal.phases]
        values["calibration_status"] = "done" if cal.success else "attempted_failed_or_blocked"
    else:
        values["calibration_attempted"] = False
        values["calibration_success"] = False
        values["calibration_status"] = "not_attempted"

    # Outlet provenance artifact (minimal, machine-readable pointer for auditability).
    outlet_keys = (
        "requested_outlet_gis_id",
        "selected_outlet_gis_id",
        "outlet_autodetected",
        "outlet_selection_reason",
    )
    outlet_prov = {"usgs_id": request.usgs_id, "run_id": run_id}
    for k in outlet_keys:
        if k in values:
            outlet_prov[k] = values[k]
    outlet_path = out / "outlet_provenance.json"
    outlet_path.write_text(json.dumps(outlet_prov, indent=2) + "\n", encoding="utf-8")
    values["outlet_provenance_path"] = str(outlet_path)

    payload = {
        "run_id": run_id,
        "usgs_id": request.usgs_id,
        "success": bool(success),
        "artifact_dir": str(out),
        "claim_tier": allowed_tier,
        "contract_status": request.contract_status,
        "accepted_by": request.accepted_by,
        "gates_passed": ["contract_policy"] if blocker is None else [],
        "gates_failed": ["contract_policy"] if blocker is not None else [],
        "blocker_class": blocker,
        "status": status_msg,
        "values": values,
    }
    payload["provenance_hash"] = _provenance_hash(payload)

    path = out / "evidence_summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return RunUSGSWorkflowResult(
        success=bool(success),
        run_id=run_id,
        artifact_dir=str(out),
        evidence_summary_path=str(path),
        blocker_class=blocker,
        values=values,
    )
