"""Deterministic phased calibration orchestration.

Phases: volume -> baseflow -> peaks -> finetune.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..params.governance import calibration_eligible_full_mode_parameters


@dataclass
class PhaseRun:
    stage: int
    phase: str
    status: str
    message: str
    script: str


@dataclass
class DiagnosticCalibrationResult:
    success: bool
    phases: list[PhaseRun] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


def run_diagnostic_calibration(
    source_run: Path,
    *,
    claim_tier: str,
    strict: bool = True,
) -> DiagnosticCalibrationResult:
    source_run = Path(source_run).expanduser().resolve()
    reports = source_run / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    screen = source_run / "reports" / "sensitivity_screen.json"
    if strict and claim_tier != "exploratory" and screen.exists():
        data = json.loads(screen.read_text(encoding="utf-8"))
        governance_blocked = [
            p["parameter"] for p in data.get("parameters", []) if p.get("activity_class") == "dead"
        ]
    else:
        governance_blocked = []

    lock_path = source_run / "benchmark" / "benchmark_lock.json"
    txtinout = _find_txtinout(source_run)
    eligible_parameters = calibration_eligible_full_mode_parameters()

    if not lock_path.exists() or txtinout is None:
        missing = []
        if not lock_path.exists():
            missing.append("benchmark/benchmark_lock.json")
        if txtinout is None:
            missing.append("project/Scenarios/Default/TxtInOut")
        res = DiagnosticCalibrationResult(
            success=False,
            phases=[
                PhaseRun(
                    stage=0,
                    phase="locked_calibration_eligibility",
                    status="blocked",
                    message="locked calibration requires existing lock and prepared TxtInOut",
                    script="locked_benchmark",
                )
            ],
            provenance={
                "calibration_method": "locked_diagnostic_full_mode",
                "claim_tier": claim_tier,
                "strict": strict,
                "source_run": str(source_run),
                "blocked_parameters": governance_blocked,
                "eligible_parameters": eligible_parameters,
                "missing_artifacts": missing,
                "final_metrics_authority": "none",
                "temporary_candidate_metrics_allowed_as_final": False,
            },
        )
        _write_result(reports / "diagnostic_calibration.json", res)
        return res

    from .locked_benchmark import (
        calibrate_against_lock,
        screen_parameters_against_lock,
        verify_calibration,
    )
    from .real_engine import params_hash

    lock_context = _read_lock_context(lock_path)
    runs = [
        PhaseRun(1, "volume", "passed", "volume gate authority inherited from benchmark lock", "benchmark_lock"),
        PhaseRun(2, "sensitivity_screen", "pending", f"eligible parameters: {', '.join(eligible_parameters)}", "locked_benchmark"),
        PhaseRun(3, "baseflow_subsurface", "pending", "waiting for basin-specific sensitivity screen", "parameter_governance"),
        PhaseRun(4, "peaks_timing", "passed", "locked objective will rerun each candidate from fresh TxtInOut copy", "locked_benchmark"),
    ]
    try:
        sensitivity = screen_parameters_against_lock(
            lock=lock_path,
            base_txtinout=txtinout,
            out_dir=source_run / "calibration",
            parameters=eligible_parameters,
            parameter_mode="full",
        )
        sensitivity_classes = {
            str(row.get("parameter")): str(row.get("activity_class"))
            for row in sensitivity.parameters
        }
        screened_parameters = [
            name
            for name in eligible_parameters
            if sensitivity_classes.get(name) in {"active", "weak", "limited"}
        ]
        blocked_parameters = _screen_blocked_parameters(
            eligible_parameters,
            sensitivity_classes,
            governance_blocked,
        )
        runs[1] = PhaseRun(
            2,
            "sensitivity_screen",
            "passed" if screened_parameters else "blocked",
            (
                f"retained parameters: {', '.join(screened_parameters)}"
                if screened_parameters
                else "no basin-sensitive eligible calibration parameters"
            ),
            "locked_benchmark",
        )
        runs[2] = PhaseRun(
            3,
            "baseflow_subsurface",
            "passed" if screened_parameters else "blocked",
            (
                f"screened parameters: {', '.join(screened_parameters)}"
                if screened_parameters
                else "blocked by basin-specific sensitivity screen"
            ),
            "parameter_governance",
        )
        if not screened_parameters:
            raise RuntimeError("No basin-specific active/weak eligible parameters; calibration search blocked.")
        evidence = calibrate_against_lock(
            lock=lock_path,
            base_txtinout=txtinout,
            out_dir=source_run / "calibration",
            parameters=screened_parameters,
            parameter_mode="full",
        )
        best_solution = json.loads(Path(evidence.best_solution_json).read_text(encoding="utf-8"))
        verification = verify_calibration(
            lock=lock_path,
            best_solution_json=evidence.best_solution_json,
            base_txtinout=txtinout,
            out_dir=source_run / "calibration",
            parameter_mode="full",
        )
        best_hash = params_hash(evidence.best_parameters)
        verified_txt = Path(verification.verification_dir) / best_hash / "TxtInOut"
        locked_txt = source_run / "calibration" / "locked_calibrated_TxtInOut"
        if verified_txt.exists():
            if locked_txt.exists():
                shutil.rmtree(locked_txt)
            shutil.copytree(verified_txt, locked_txt)
        final_routing_flow_gates = _check_locked_txt_routing_flow(
            locked_txt,
            out_dir=source_run / "calibration" / "locked_calibrated_routing_flow",
            basin_id=lock_context.get("basin_id"),
            selected_outlet_gis_id=_safe_int(lock_context.get("outlet_gis_id")),
            outlet_scope=str(lock_context.get("outlet_scope") or ""),
            outlet_policy=str(lock_context.get("outlet_policy") or ""),
            selected_outlet_gis_ids=lock_context.get("selected_outlet_gis_ids"),
            virtual_outlet_authority=lock_context.get("virtual_outlet_authority"),
            virtual_outlet_claim_authority=lock_context.get("virtual_outlet_claim_authority") is True,
        )
        hydrograph_report = _write_locked_hydrograph_comparison(
            baseline_alignment_csv=source_run / "benchmark" / "alignment.csv",
            calibrated_alignment_csv=verified_txt / "alignment_calibration.csv",
            out_dir=source_run / "calibration" / "hydrograph_comparison",
        )
        skill_diagnostics = _write_locked_skill_diagnostics(
            calibrated_alignment_csv=verified_txt / "alignment_calibration.csv",
            out_dir=source_run / "calibration" / "skill_diagnostics",
            sensitivity_activity_classes=sensitivity_classes,
            calibrated_parameters=best_solution.get("parameters") if isinstance(best_solution, dict) else None,
        )
        timing_limitation = _documented_timing_limitation(
            skill_diagnostics,
            nse=verification.verified_nse,
            kge=verification.verified_kge,
            pbias=verification.verified_pbias,
        )
        final_physical_gates = _check_locked_txt_physical_gates(
            locked_txt,
            nse=verification.verified_nse,
            kge=verification.verified_kge,
            pbias=verification.verified_pbias,
            timing_limitation_documented=timing_limitation["documented"],
            timing_limitation_basis=timing_limitation["basis"],
        )
        final_gates_passed = bool(final_physical_gates.get("pass")) and not bool(
            final_routing_flow_gates.get("calibration_blocking", not final_routing_flow_gates.get("pass"))
        )
        locked_verification_succeeded = bool(verification.improved and locked_txt.exists())
        runs.append(
            PhaseRun(
                4,
                "kge_nse_finetune",
                "passed" if verification.improved and final_gates_passed else "failed",
                "final metrics come from independent locked rerun gated on locked TxtInOut physical and routing evidence",
                "verify_calibration",
            )
        )
        res = DiagnosticCalibrationResult(
            success=bool(verification.improved and locked_txt.exists() and final_gates_passed),
            phases=runs,
            provenance={
                "calibration_method": "locked_diagnostic_full_mode",
                "claim_tier": claim_tier,
                "strict": strict,
                "source_run": str(source_run),
                "blocked_parameters": blocked_parameters,
                "eligible_parameters": eligible_parameters,
                "screened_parameters": screened_parameters,
                "sensitivity_screen_basis": sensitivity.basis,
                "sensitivity_screen_path": sensitivity.json_path,
                "sensitivity_screen_md": sensitivity.markdown_path,
                "sensitivity_screen_activity_classes": sensitivity_classes,
                "fresh_candidate_outputs": True,
                "selection_policy": best_solution.get("selection_policy"),
                "calibration_protocol": best_solution.get("calibration_protocol", []),
                "history_csv": evidence.history_csv,
                "best_solution_json": evidence.best_solution_json,
                "verification_summary": verification.verification_summary_path,
                "verification_improvement_basis": verification.improvement_basis,
                "benchmark_metrics": {
                    "nse": verification.benchmark_nse,
                    "kge": verification.benchmark_kge,
                    "pbias": verification.benchmark_pbias,
                },
                "verification_metrics": {
                    "nse": verification.verified_nse,
                    "kge": verification.verified_kge,
                    "pbias": verification.verified_pbias,
                },
                "verification_delta_metrics": {
                    "nse": verification.delta_nse,
                    "kge": verification.delta_kge,
                    "pbias": (
                        None
                        if verification.benchmark_pbias is None or verification.verified_pbias is None
                        else verification.verified_pbias - verification.benchmark_pbias
                    ),
                },
                "locked_calibrated_txtinout": str(locked_txt) if locked_txt.exists() else None,
                "locked_verification_succeeded": locked_verification_succeeded,
                "locked_rerun_improved": bool(verification.improved),
                "final_claim_gates_passed": bool(final_gates_passed),
                "calibration_claim_status": (
                    "verified_and_claim_gates_passed"
                    if locked_verification_succeeded and final_gates_passed
                    else (
                        "verified_diagnostic_claim_blocked_by_final_gates"
                        if locked_verification_succeeded
                        else "verification_failed"
                    )
                ),
                "final_physical_gates": final_physical_gates,
                "final_routing_flow_gates": final_routing_flow_gates,
                "timing_limitation_documented": timing_limitation["documented"],
                "timing_limitation_basis": timing_limitation["basis"],
                "hydrograph_comparison": hydrograph_report,
                "skill_diagnostics": skill_diagnostics,
                "final_metrics_authority": "verification_summary.json",
                "temporary_candidate_metrics_allowed_as_final": False,
            },
        )
    except Exception as exc:
        error_context = exc.context if isinstance(getattr(exc, "context", None), dict) else {}
        history_csv = error_context.get("history_csv") if isinstance(error_context.get("history_csv"), str) else None
        n_evaluations = error_context.get("n_evaluations")
        if not isinstance(n_evaluations, int):
            n_evaluations = None
        promotion_gate = error_context.get("promotion_gate")
        if not isinstance(promotion_gate, (dict, str)):
            promotion_gate = None
        failure_phase = (
            str(error_context.get("phase"))
            if error_context.get("phase") is not None
            else None
        )
        runs.append(PhaseRun(4, "kge_nse_finetune", "failed", str(exc)[-400:], "locked_benchmark"))
        res = DiagnosticCalibrationResult(
            success=False,
            phases=runs,
            provenance={
                "calibration_method": "locked_diagnostic_full_mode",
                "claim_tier": claim_tier,
                "strict": strict,
                "source_run": str(source_run),
                "blocked_parameters": locals().get("blocked_parameters", governance_blocked),
                "eligible_parameters": eligible_parameters,
                "screened_parameters": locals().get("screened_parameters", []),
                "sensitivity_screen_basis": getattr(locals().get("sensitivity"), "basis", None),
                "sensitivity_screen_path": getattr(locals().get("sensitivity"), "json_path", None),
                "sensitivity_screen_md": getattr(locals().get("sensitivity"), "markdown_path", None),
                "sensitivity_screen_activity_classes": locals().get("sensitivity_classes", {}),
                "final_metrics_authority": "none",
                "temporary_candidate_metrics_allowed_as_final": False,
                "error": str(exc),
                "error_context": error_context,
                "history_csv": history_csv,
                "n_evaluations": n_evaluations,
                "promotion_gate": promotion_gate,
                "phase": failure_phase,
            },
        )
    _write_result(reports / "diagnostic_calibration.json", res)
    return res


def _find_txtinout(source_run: Path) -> Path | None:
    candidates = [
        source_run / "project" / "Scenarios" / "Default" / "TxtInOut",
        source_run / "Scenarios" / "Default" / "TxtInOut",
        source_run / "TxtInOut",
    ]
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "file.cio").exists():
            return candidate
    return None


def _write_locked_hydrograph_comparison(
    *,
    baseline_alignment_csv: Path,
    calibrated_alignment_csv: Path,
    out_dir: Path,
) -> dict[str, object]:
    if not baseline_alignment_csv.is_file():
        return {"status": "not_run", "reason": f"baseline alignment missing: {baseline_alignment_csv}"}
    if not calibrated_alignment_csv.is_file():
        return {"status": "not_run", "reason": f"calibrated alignment missing: {calibrated_alignment_csv}"}
    try:
        from .report import write_hydrograph_comparison_from_two_alignments

        artifacts = write_hydrograph_comparison_from_two_alignments(
            baseline_alignment_csv=baseline_alignment_csv,
            calibrated_alignment_csv=calibrated_alignment_csv,
            outdir=out_dir,
        )
        return {"status": "written", **artifacts}
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}


def _write_locked_skill_diagnostics(
    *,
    calibrated_alignment_csv: Path,
    out_dir: Path,
    sensitivity_activity_classes: dict[str, str] | None = None,
    calibrated_parameters: dict[str, float] | None = None,
) -> dict[str, object]:
    if not calibrated_alignment_csv.is_file():
        return {"status": "not_run", "reason": f"calibrated alignment missing: {calibrated_alignment_csv}"}
    try:
        from ..diagnostics import diagnose, write_diagnostics_json_report, write_diagnostics_report

        out_dir.mkdir(parents=True, exist_ok=True)
        diagnoses = diagnose(calibrated_alignment_csv)
        md_path = write_diagnostics_report(
            diagnoses,
            out_dir / "skill_diagnostics.md",
            title="Locked Calibration Skill Diagnostics",
        )
        json_path = write_diagnostics_json_report(
            diagnoses,
            out_dir / "skill_diagnostics.json",
            title="Locked Calibration Skill Diagnostics",
        )
        gap_payload = _annotate_skill_sensitivity_gaps(
            json_path,
            sensitivity_activity_classes or {},
        )
        bound_payload = _annotate_skill_parameter_bound_context(
            json_path,
            calibrated_parameters or {},
        )
        return {
            "status": "written",
            "skill_diagnostics_json": str(json_path),
            "skill_diagnostics_md": str(md_path),
            "diagnostic_count": len(diagnoses),
            "skill_probe_gap_parameters": gap_payload.get("skill_probe_gap_parameters", []),
            "skill_screened_dead_parameters": gap_payload.get("skill_screened_dead_parameters", []),
            "skill_unscreened_suggested_parameters": gap_payload.get(
                "skill_unscreened_suggested_parameters", []
            ),
            "skill_parameter_bound_hits": bound_payload.get("calibrated_parameter_bound_hits", {}),
        }
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}


def _annotate_skill_parameter_bound_context(
    diagnostics_json: Path,
    calibrated_parameters: dict[str, float],
) -> dict[str, object]:
    try:
        payload = json.loads(diagnostics_json.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        from ..params.registry import registry
    except Exception:
        registry = {}
    values = {
        str(name): float(value)
        for name, value in calibrated_parameters.items()
        if isinstance(value, (int, float))
    }
    bound_hits: dict[str, dict[str, object]] = {}
    for name, value in values.items():
        spec = registry.get(name)
        if spec is None:
            continue
        lo, hi = spec.range
        tolerance = max((float(hi) - float(lo)) * 0.02, 1e-9)
        boundary = None
        if value <= float(lo) + tolerance:
            boundary = "lower"
        elif value >= float(hi) - tolerance:
            boundary = "upper"
        if boundary:
            bound_hits[name] = {
                "value": value,
                "min": float(lo),
                "max": float(hi),
                "boundary": boundary,
            }

    for flag in payload.get("diagnostic_flags", []):
        if not isinstance(flag, dict):
            continue
        suggested = [
            str(param)
            for param in flag.get("suggested_parameters", [])
            if isinstance(param, str) and param
        ]
        tuned = [param for param in suggested if param in values]
        flag_hits = {param: bound_hits[param] for param in suggested if param in bound_hits}
        if not suggested and not flag_hits:
            continue
        all_tuned_at_bounds = bool(tuned) and len(flag_hits) == len(tuned)
        context = {
            "calibrated_values": {param: values[param] for param in tuned},
            "bound_hits": flag_hits,
            "untuned_suggested_parameters": [param for param in suggested if param not in values],
            "all_tuned_suggested_parameters_at_bounds": all_tuned_at_bounds,
        }
        flag["parameter_bound_context"] = context
        if all_tuned_at_bounds and context["untuned_suggested_parameters"]:
            parameter_text = ", ".join(tuned)
            untuned_text = ", ".join(str(param) for param in context["untuned_suggested_parameters"])
            flag["bound_aware_next_action"] = (
                f"Tuned suggested controls ({parameter_text}) are already at governed bounds in the locked "
                f"solution; run a basin-specific locked screen for untuned governed controls ({untuned_text}) "
                "and inspect routing/channel attenuation, precipitation forcing, and outlet/output scope "
                "before extending calibration."
            )
        elif all_tuned_at_bounds and not context["untuned_suggested_parameters"]:
            parameter_text = ", ".join(tuned)
            flag["bound_aware_next_action"] = (
                f"Suggested controls ({parameter_text}) are already at governed bounds in the locked solution; "
                "inspect routing/channel attenuation, precipitation forcing, and outlet/output scope "
                "before extending calibration."
            )

    payload["calibrated_parameter_values"] = values
    payload["calibrated_parameter_bound_hits"] = bound_hits
    payload["parameter_bound_claim_impact"] = (
        "diagnostic_only_until_bound-hit controls are structurally explained"
        if bound_hits
        else "none"
    )
    payload["next_actions"] = _bound_aware_next_actions(payload)
    _deprioritize_bound_exhausted_probes(payload, bound_hits)
    diagnostics_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _deprioritize_bound_exhausted_probes(
    payload: dict[str, object],
    bound_hits: dict[str, dict[str, object]],
) -> None:
    """Keep exhausted controls visible, but stop ranking them as the next probe."""

    if not bound_hits:
        return
    alternatives = payload.get("source_backed_alternatives")
    if not isinstance(alternatives, list):
        return
    annotated: list[tuple[int, bool, dict[str, object]]] = []
    for index, raw in enumerate(alternatives):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        params = [
            str(param)
            for param in row.get("parameters", [])
            if isinstance(param, str) and param
        ]
        exhausted = [param for param in params if param in bound_hits]
        available = [param for param in params if param not in bound_hits]
        if params:
            row["unexhausted_parameters"] = available
        if exhausted:
            row["bound_exhausted_parameters"] = exhausted
            row["bound_exhaustion_claim_impact"] = (
                "deprioritized_until_bound-hit controls are structurally explained"
            )
        all_params_exhausted = bool(params) and len(exhausted) == len(params)
        annotated.append((index, all_params_exhausted, row))
    if not annotated:
        return
    ordered = [row for _index, _all_exhausted, row in sorted(annotated, key=lambda item: (item[1], item[0]))]
    payload["source_backed_alternatives"] = ordered
    probes: list[dict[str, object]] = []
    for rank, alternative in enumerate(ordered, start=1):
        probes.append(
            {
                "rank": rank,
                "diagnostic": alternative.get("option"),
                "parameters": alternative.get("parameters", []),
                "blocked_parameters": alternative.get("blocked_parameters", []),
                "required_artifacts": alternative.get("required_artifacts", []),
                "claim_impact": alternative.get("claim_impact"),
                "bound_exhausted_parameters": alternative.get("bound_exhausted_parameters", []),
                "unexhausted_parameters": alternative.get("unexhausted_parameters", []),
                "bound_exhaustion_claim_impact": alternative.get("bound_exhaustion_claim_impact"),
            }
        )
    payload["recommended_probe_order"] = probes


def _bound_aware_next_actions(payload: dict[str, object]) -> list[str]:
    actions: list[str] = []
    for flag in payload.get("diagnostic_flags", []):
        if not isinstance(flag, dict):
            continue
        action = flag.get("bound_aware_next_action") or flag.get("suggested_action")
        if isinstance(action, str) and action and action not in actions:
            actions.append(action)
    return actions


def _annotate_skill_sensitivity_gaps(
    diagnostics_json: Path,
    sensitivity_activity_classes: dict[str, str],
) -> dict[str, object]:
    try:
        payload = json.loads(diagnostics_json.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    usable_classes = {"active", "weak", "limited", "requires_basin_screen"}
    suggested: list[str] = []
    for alt in payload.get("source_backed_alternatives", []):
        if not isinstance(alt, dict):
            continue
        params = alt.get("parameters")
        if not isinstance(params, list):
            continue
        suggested.extend(str(param) for param in params if isinstance(param, str) and param)
    suggested = list(dict.fromkeys(suggested))
    gaps = [
        param
        for param in suggested
        if str(sensitivity_activity_classes.get(param) or "") not in usable_classes
    ]
    gap_reasons = {
        param: str(sensitivity_activity_classes.get(param) or "not_screened")
        for param in gaps
    }
    screened_dead = [
        param
        for param in gaps
        if str(sensitivity_activity_classes.get(param) or "") == "dead"
    ]
    unscreened = [param for param in gaps if param not in sensitivity_activity_classes]
    usable = [
        param
        for param in suggested
        if str(sensitivity_activity_classes.get(param) or "") in usable_classes
    ]
    class_map = {
        str(k): str(v) for k, v in sensitivity_activity_classes.items()
    }
    for flag in payload.get("diagnostic_flags", []):
        if not isinstance(flag, dict):
            continue
        params = flag.get("suggested_parameters")
        if not isinstance(params, list):
            continue
        flag_params = [str(param) for param in params if isinstance(param, str) and param]
        if not flag_params:
            continue
        flag_gaps = [
            param
            for param in flag_params
            if str(sensitivity_activity_classes.get(param) or "") not in usable_classes
        ]
        flag["sensitivity_context"] = {
            "activity_classes": {
                param: str(sensitivity_activity_classes.get(param) or "not_screened")
                for param in flag_params
            },
            "usable_suggested_parameters": [
                param
                for param in flag_params
                if str(sensitivity_activity_classes.get(param) or "") in usable_classes
            ],
            "screened_dead_parameters": [
                param
                for param in flag_gaps
                if str(sensitivity_activity_classes.get(param) or "") == "dead"
            ],
            "unscreened_suggested_parameters": [
                param for param in flag_gaps if param not in sensitivity_activity_classes
            ],
            "gap_reasons": {
                param: str(sensitivity_activity_classes.get(param) or "not_screened")
                for param in flag_gaps
            },
            "claim_impact": (
                "diagnostic_only_until_screened_dead_or_unscreened_controls_are_explained"
                if flag_gaps
                else "suggested_controls_have_basin_specific_sensitivity_evidence"
            ),
        }
    payload["sensitivity_screen_activity_classes"] = class_map
    payload["skill_probe_gap_parameters"] = gaps
    payload["skill_probe_gap_reasons"] = gap_reasons
    payload["skill_screened_dead_parameters"] = screened_dead
    payload["skill_unscreened_suggested_parameters"] = unscreened
    payload["skill_usable_suggested_parameters"] = usable
    payload["skill_probe_gap_claim_impact"] = (
        "diagnostic_only_until_screened_dead_or_unscreened_suggested_controls_are_explained"
        if gaps
        else "none"
    )
    diagnostics_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _screen_blocked_parameters(
    eligible_parameters: list[str],
    sensitivity_classes: dict[str, str],
    governance_blocked: list[str],
) -> list[str]:
    usable_classes = {"active", "weak", "limited"}
    blocked = list(governance_blocked)
    for name in eligible_parameters:
        if sensitivity_classes.get(name) not in usable_classes:
            blocked.append(name)
    return list(dict.fromkeys(str(name) for name in blocked if name))


def _read_lock_context(lock_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_in_range(value: float | None, min_value: float, max_value: float) -> bool:
    return value is not None and min_value <= value <= max_value


def _is_virtual_all_terminal_scope(outlet_scope: object, outlet_policy: object) -> bool:
    return (
        str(outlet_scope or "").lower() == "virtual_all_terminal"
        or str(outlet_policy or "").lower() == "all_terminal_sum"
    )


def _virtual_all_terminal_scope_gate(
    *,
    outlet_scope: object,
    outlet_policy: object,
    selected_outlet_gis_ids: object,
    virtual_outlet_authority: object,
    virtual_outlet_claim_authority: bool,
    routing_payload: dict[str, object],
) -> dict[str, object]:
    if not _is_virtual_all_terminal_scope(outlet_scope, outlet_policy):
        return {"applicable": False, "passed": True, "reason": "single_channel_scope"}

    blockers: list[str] = []
    if str(outlet_policy or "").lower() != "all_terminal_sum":
        blockers.append("outlet_policy_must_be_all_terminal_sum")
    if str(outlet_scope or "").lower() != "virtual_all_terminal":
        blockers.append("outlet_scope_must_be_virtual_all_terminal")
    if not str(virtual_outlet_authority or "").strip():
        blockers.append("virtual_outlet_authority_missing")
    if virtual_outlet_claim_authority is not True:
        blockers.append("virtual_outlet_claim_authority_not_true")
    if not isinstance(selected_outlet_gis_ids, list) or not selected_outlet_gis_ids:
        blockers.append("selected_outlet_gis_ids_missing")

    terminal_count = _safe_float(routing_payload.get("terminal_outlet_count"))
    if terminal_count is None or terminal_count < 2:
        blockers.append("terminal_inventory_not_multi_terminal")

    overlap_count = _safe_float(routing_payload.get("terminal_overlap_pair_count"))
    shared_area = _safe_float(routing_payload.get("terminal_shared_upstream_area_km2"))
    if terminal_count is not None and terminal_count >= 2 and overlap_count is None and shared_area is None:
        blockers.append("terminal_topology_evidence_missing")
    if overlap_count is not None and overlap_count > 0:
        blockers.append("terminal_topology_overlap")
    if shared_area is not None and shared_area > 0.01:
        blockers.append("terminal_topology_overlap")

    all_routed_ratio = _safe_float(routing_payload.get("all_terminal_routed_to_channel_closure_ratio"))
    all_mass_ratio = _safe_float(routing_payload.get("all_terminal_mass_closure_ratio"))
    all_outflow = _safe_float(routing_payload.get("all_terminal_outflow_m3"))
    if all_outflow is None or all_outflow <= 0:
        blockers.append("all_terminal_outflow_missing_or_zero")
    if not (
        _ratio_in_range(all_routed_ratio, 0.7, 1.3)
        or _ratio_in_range(all_mass_ratio, 0.7, 1.3)
    ):
        blockers.append("all_terminal_routing_closure_not_passed")

    selected_ids = selected_outlet_gis_ids if isinstance(selected_outlet_gis_ids, list) else []
    return {
        "applicable": True,
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "reason": "virtual all-terminal outlet scope passed" if not blockers else ",".join(blockers),
        "blockers": blockers,
        "authority": virtual_outlet_authority,
        "selected_outlet_gis_ids": selected_ids,
        "terminal_outlet_count": int(terminal_count) if terminal_count is not None else None,
        "all_terminal_routed_to_channel_closure_ratio": all_routed_ratio,
        "all_terminal_mass_closure_ratio": all_mass_ratio,
        "all_terminal_outflow_m3": all_outflow,
    }


def _check_locked_txt_physical_gates(
    locked_txt: Path,
    *,
    nse: float | None,
    kge: float | None,
    pbias: float | None = None,
    timing_limitation_documented: bool = False,
    timing_limitation_basis: str | None = None,
) -> dict[str, object]:
    if not locked_txt.exists():
        return {"status": "failed", "pass": False, "reason": "locked_calibrated_txtinout_missing"}
    try:
        from ..full_mode.water_balance_gate import check_water_balance

        result = check_water_balance(
            locked_txt,
            nse=nse,
            kge=kge,
            pbias=pbias,
            timing_limitation_documented=timing_limitation_documented,
            timing_limitation_basis=timing_limitation_basis,
        )
        return {"status": "passed" if result.get("pass") else "failed", **result}
    except Exception as exc:
        return {"status": "failed", "pass": False, "reason": str(exc)}


def _documented_timing_limitation(
    skill_diagnostics: dict[str, Any],
    *,
    nse: float | None,
    kge: float | None,
    pbias: float | None,
) -> dict[str, object]:
    if nse is None or kge is None or nse >= 0.0 or kge < 0.40:
        return {"documented": False, "basis": None}
    if pbias is not None and abs(pbias) > 30.0:
        return {"documented": False, "basis": None}
    path = skill_diagnostics.get("skill_diagnostics_json")
    if not path:
        return {"documented": False, "basis": None}
    try:
        payload = json.loads(Path(str(path)).read_text(encoding="utf-8"))
    except Exception:
        return {"documented": False, "basis": None}
    flags = payload.get("diagnostic_flags")
    if not isinstance(flags, list):
        return {"documented": False, "basis": None}
    timing_symptoms: list[str] = []
    for flag in flags:
        if not isinstance(flag, dict):
            continue
        symptom = str(flag.get("symptom") or "")
        if "timing" in symptom.lower() or "peak lag" in symptom.lower():
            timing_symptoms.append(symptom)
    if not timing_symptoms:
        return {"documented": False, "basis": None}
    basis = (
        f"KGE={kge:.3f} passes the research minimum while NSE={nse:.3f} is negative; "
        f"skill diagnostics document timing limitation: {', '.join(timing_symptoms[:3])}."
    )
    return {"documented": True, "basis": basis}


def _check_locked_txt_routing_flow(
    locked_txt: Path,
    *,
    out_dir: Path,
    basin_id: str | None = None,
    selected_outlet_gis_id: int | None = None,
    outlet_scope: str | None = None,
    outlet_policy: str | None = None,
    selected_outlet_gis_ids: object = None,
    virtual_outlet_authority: object = None,
    virtual_outlet_claim_authority: bool = False,
) -> dict[str, object]:
    if not locked_txt.exists():
        return {"status": "failed", "pass": False, "reason": "locked_calibrated_txtinout_missing"}
    try:
        from ..output.mass_trace import trace_mass_balance

        report = trace_mass_balance(
            locked_txt,
            basin_id=basin_id or (locked_txt.parent.parent.name if locked_txt.parent else "unknown"),
            selected_outlet_gis_id=selected_outlet_gis_id,
            out_dir=out_dir,
        )
    except Exception as exc:
        return {"status": "failed", "pass": False, "reason": str(exc)}

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
    flags = list(report.flags or [])
    terminal_trace: dict[str, object] = {}
    if "multiple_terminal_outlets_present" in flags or _is_virtual_all_terminal_scope(outlet_scope, outlet_policy):
        try:
            from ..output.mass_trace import trace_terminal_inventory

            terminal_report = trace_terminal_inventory(
                locked_txt,
                basin_id=basin_id or (locked_txt.parent.parent.name if locked_txt.parent else "unknown"),
                selected_outlet_gis_id=report.selected_outlet_gis_id,
                out_dir=out_dir,
                fetch_usgs_site_area=True,
            )
            terminal_trace = {
                "terminal_trace_path": str(Path(out_dir) / "terminal_trace.json"),
                "terminal_trace_md": str(Path(out_dir) / "terminal_trace.md"),
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
            terminal_trace = {"terminal_trace_error": str(exc)}
    virtual_scope_payload: dict[str, object] = {
        "terminal_outlet_count": report.terminal_outlet_count,
        "terminal_overlap_pair_count": terminal_trace.get("terminal_overlap_pair_count"),
        "terminal_shared_upstream_area_km2": terminal_trace.get("terminal_shared_upstream_area_km2"),
        "all_terminal_routed_to_channel_closure_ratio": getattr(
            report, "all_terminal_routed_to_channel_closure_ratio", None
        ),
        "all_terminal_mass_closure_ratio": getattr(report, "all_terminal_mass_closure_ratio", None),
        "all_terminal_outflow_m3": report.all_terminal_outflow_m3,
    }
    virtual_scope_gate = _virtual_all_terminal_scope_gate(
        outlet_scope=outlet_scope,
        outlet_policy=outlet_policy,
        selected_outlet_gis_ids=selected_outlet_gis_ids,
        virtual_outlet_authority=virtual_outlet_authority,
        virtual_outlet_claim_authority=virtual_outlet_claim_authority,
        routing_payload=virtual_scope_payload,
    )
    reason = "routing flow closure passed" if passed else f"routing flow closure status={closure_status}"
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
    payload: dict[str, object] = {
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
        "ru_outflow_to_basin_wateryld_ratio": report.ru_outflow_to_basin_wateryld_ratio,
        "channel_inflow_m3": report.channel_inflow_m3,
        "terminal_outflow_m3": report.terminal_outflow_m3,
        "all_terminal_outflow_m3": report.all_terminal_outflow_m3,
        "mass_closure_ratio": report.mass_closure_ratio,
        "mass_trace_basin_wb_source_file": getattr(report, "basin_wb_source_file", None),
        "mass_trace_basin_wb_row_count": getattr(report, "basin_wb_row_count", None),
        "mass_trace_basin_wb_years": getattr(report, "basin_wb_years", []),
        "mass_trace_channel_source_file": getattr(report, "channel_source_file", None),
        "mass_trace_channel_row_count": getattr(report, "channel_row_count", None),
        "mass_trace_channel_years": getattr(report, "channel_years", []),
        "mass_trace_selected_channel_row_count": getattr(report, "selected_channel_row_count", None),
        "mass_trace_selected_channel_years": getattr(report, "selected_channel_years", []),
        "mass_trace_terminal_channel_row_count": getattr(report, "terminal_channel_row_count", None),
        "mass_trace_terminal_channel_years": getattr(report, "terminal_channel_years", []),
        "json_path": str(Path(out_dir) / "mass_trace.json"),
        "markdown_path": str(Path(out_dir) / "mass_trace.md"),
        "gate_json_path": str(Path(out_dir) / "routing_flow_gates.json"),
        "recommended_next_action": _routing_flow_next_action(
            flags,
            passed=passed,
            calibration_blocking=calibration_blocking,
        ),
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
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "routing_flow_gates.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def _routing_flow_next_action(flags: list[str], *, passed: bool, calibration_blocking: bool) -> str:
    if passed:
        return "No routing-flow action required."
    flag_set = set(flags)
    if "multiple_terminal_outlets_present" in flag_set:
        return "Review terminal outlet inventory and gauge-to-terminal selection before research-grade routing claims."
    if "channel_inflow_exceeds_basin_wateryld" in flag_set:
        return (
            "Inspect routing-unit to channel transfer and SWAT+ output unit interpretation; "
            "selected-channel inflow exceeds basin water yield."
        )
    if not calibration_blocking:
        return "Mass-closure mismatch is retained as a research-grade blocker; diagnostic calibration may proceed."
    return "Inspect HRU-to-channel transfer, terminal outlet selection, and channel routing before calibration."


def _write_result(path: Path, res: DiagnosticCalibrationResult) -> None:
    path.write_text(
        json.dumps(
            {"success": res.success, "phases": [asdict(p) for p in res.phases], "provenance": res.provenance},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
