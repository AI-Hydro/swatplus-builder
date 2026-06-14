#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import warnings
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from swatplus_builder.diagnostics import classify_skill_limitation
from swatplus_builder.evidence.migration import migrate_legacy_bundle
from swatplus_builder.output.mass_trace import (
    classify_terminal_area_scope,
    classify_terminal_authority_area,
    classify_terminal_outlet_conflict,
    classify_terminal_scope_blocker,
)
from swatplus_builder.output.volume_diagnostics import (
    build_terminal_scope_decision_request,
    build_terminal_scope_resolution_plan,
    classify_terminal_hydrograph_scope,
)
from swatplus_builder.params.registry import registry
from swatplus_builder.workflows.usgs_e2e import terminal_scope_blocked_claim

warnings.filterwarnings("ignore", category=FutureWarning, module=r"pygridmet(\.|$)")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"pygeoutils(\.|$)")

_SKILL_ONLY_GATE_CODES = {"NEGATIVE_SKILL", "BELOW_RESEARCH_SKILL"}

BASINS = [
    "02129000", "01547700", "03349000", "01654000", "01491000", "01013500",
    "03351500", "03353000", "01493500", "12031000", "09504500",
]

AREA_HINTS = {
    "02129000": 17780,
    "01547700": 445,
    "03349000": 920,
    "01654000": 62,
}

@dataclass
class Row:
    basin: str
    area_km2: float | None
    build: str
    warmup: str
    engine: str
    physical_gates: str
    routing_flow_gates: str
    routing_flow_gates_evidence_status: str | None
    routing_flow_gate_status_mismatch: bool
    routing_flow_closure_status: str | None
    routing_flow_closure_evidence_status: str | None
    routing_flow_closure_mismatch: bool
    calibration: str
    calibration_failure_phase: str | None
    calibration_failure_message: str | None
    calibration_failure_history_csv: str | None
    calibration_failure_n_evaluations: int | None
    calibration_failure_promotion_gate: dict[str, object]
    calibration_failure_volume_gate_pass_count: int | None
    calibration_failure_physical_gate_pass_count: int | None
    calibration_failure_process_gate_pass_count: int | None
    calibration_failure_best_phase: str | None
    calibration_failure_best_abs_pbias: float | None
    calibration_failure_best_pbias: float | None
    calibration_failure_best_kge: float | None
    calibration_failure_best_nse: float | None
    calibration_failure_best_parameters: dict[str, float]
    calibration_failure_best_parameter_bound_hits: dict[str, dict[str, object]]
    calibration_failure_best_parameter_bound_context: dict[str, object]
    calibration_bound_interaction_screen_json: str | None
    calibration_bound_interaction_candidate_count: int | None
    calibration_bound_interaction_best_label: str | None
    calibration_bound_interaction_best_parameters: dict[str, float]
    calibration_bound_interaction_best_metrics: dict[str, float]
    calibration_bound_interaction_claim_status: str | None
    calibration_failure_skill_volume_near_miss: bool
    calibration_failure_near_miss_phase: str | None
    calibration_failure_near_miss_pbias: float | None
    calibration_failure_near_miss_kge: float | None
    calibration_failure_near_miss_nse: float | None
    calibration_failure_near_miss_parameters: dict[str, float]
    calibration_failure_skill_tradeoff_frontier: dict[str, dict[str, object]]
    calibration_failure_physical_condition_code_counts: dict[str, int]
    calibration_failure_physical_dominant_blocker_counts: dict[str, int]
    calibration_failure_process_condition_code_counts: dict[str, int]
    calibration_phase_parameter_coverage: dict[str, list[str]]
    calibration_phase_evaluation_counts: dict[str, int]
    calibration_phase_order: dict[str, int]
    calibration_phase_volume_gate_pass_counts: dict[str, int]
    calibration_phase_physical_gate_pass_counts: dict[str, int]
    calibration_phase_process_gate_pass_counts: dict[str, int]
    calibration_final_metrics_authority: str | None
    temporary_candidate_metrics_allowed_as_final: bool | None
    calibration_precheck_sequence: str | None
    calibration_precheck_block_reason: str | None
    calibration_precheck_physical_gates_status: str | None
    calibration_precheck_routing_flow_gates_status: str | None
    kge: float | None
    nse: float | None
    pbias: float | None
    baseline_kge: float | None
    baseline_nse: float | None
    baseline_pbias: float | None
    delta_kge: float | None
    delta_nse: float | None
    delta_pbias: float | None
    tier: str
    blocker: str
    primary_blocker: str
    blocker_domain: str | None
    blocker_action_items: list[str]
    gates_passed: list[str]
    gates_failed: list[str]
    physical_condition_codes: list[str]
    physical_dominant_blocker: str | None
    soil_mode: str | None
    soil_provenance_mode: str | None
    pct_fallback_soils: float | None
    soil_overlay_gap_fraction: float | None
    build_message: str | None
    volume_bias_primary_issue: str | None
    sensitivity_context_flags: list[str]
    sensitivity_effective_classes: dict[str, str]
    sensitivity_screen_basis: str | None
    sensitivity_activity_classes: dict[str, str]
    evidence_summary_path: str
    run_config_path: str | None
    physical_gates_path: str | None
    routing_flow_gates_path: str | None
    outlet_scope: str | None
    outlet_policy: str | None
    selected_outlet_gis_ids: list[int]
    virtual_outlet_authority: str | None
    virtual_outlet_claim_authority: bool | None
    virtual_outlet_scope_gate: dict[str, object]
    virtual_outlet_scope_gate_status: str | None
    virtual_outlet_scope_gate_blockers: list[str]
    routing_flow_diagnostic_flags: list[str]
    routing_closure_reference: str | None
    basin_routed_to_channel_m3: float | None
    routed_to_channel_closure_ratio: float | None
    all_terminal_routed_to_channel_closure_ratio: float | None
    all_terminal_mass_closure_ratio: float | None
    selected_terminal_fraction_of_all_terminal_flow: float | None
    routing_source_backed_alternatives: list[dict[str, object]]
    routing_recommended_probe_order: list[dict[str, object]]
    terminal_trace_path: str | None
    terminal_failure_class: str | None
    missing_terminal_gis_ids: list[int]
    orphan_terminal_gis_ids: list[int]
    material_missing_terminal_gis_ids: list[int]
    missing_terminal_upstream_area_km2: float | None
    terminal_gauge_lat: float | None
    terminal_gauge_lon: float | None
    terminal_gauge_coordinate_source: str | None
    selected_outlet_distance_to_gauge_m: float | None
    nearest_terminal_gis_id: int | None
    selected_outlet_is_nearest_terminal: bool | None
    terminal_basin_nldi_area_km2: float | None
    terminal_delineated_area_km2: float | None
    selected_terminal_upstream_area_km2: float | None
    all_terminal_upstream_area_km2: float | None
    selected_terminal_fraction_of_nldi_area: float | None
    selected_terminal_fraction_of_usgs_site_area: float | None
    all_terminal_fraction_of_nldi_area: float | None
    all_terminal_fraction_of_usgs_site_area: float | None
    delineated_fraction_of_nldi_area: float | None
    selected_terminal_fraction_of_delineated_area: float | None
    all_terminal_fraction_of_delineated_area: float | None
    terminal_area_scope_class: str | None
    terminal_area_scope_flags: list[str]
    terminal_area_scope_claim_impact: str | None
    usgs_site_drainage_area_km2: float | None
    usgs_site_drainage_area_sqmi: float | None
    usgs_site_drainage_area_source: str | None
    terminal_authority_area_check: dict[str, object]
    terminal_virtual_outlet_candidate: dict[str, object]
    terminal_virtual_outlet_candidate_path: str | None
    terminal_outlet_conflict_class: str | None
    terminal_outlet_conflict_flags: list[str]
    terminal_outlet_conflict_claim_impact: str | None
    terminal_shared_upstream_area_km2: float | None
    terminal_overlap_pair_count: int
    terminal_overlap_pairs: list[dict[str, object]]
    calibration_provenance_path: str | None
    hydrograph_comparison_status: str | None
    hydrograph_comparison_plot: str | None
    hydrograph_comparison_plot_pdf: str | None
    hydrograph_observed_simulated_calibrated_plot: str | None
    hydrograph_observed_simulated_calibrated_plot_pdf: str | None
    hydrograph_comparison_metrics: str | None
    volume_bias_diagnostics_path: str | None
    weather_forcing_summary_path: str | None
    weather_forcing_summary: dict[str, object]
    high_runoff_demand_context: dict[str, object]
    volume_bias_diagnostic_flags: list[str]
    terminal_hydrograph_scope: dict[str, object]
    terminal_hydrograph_scope_class: str | None
    terminal_hydrograph_scope_flags: list[str]
    terminal_hydrograph_scope_recommended_focus: list[str]
    terminal_hydrograph_scope_claim_impact: str | None
    terminal_scope_resolution_plan: dict[str, object]
    post_aggregation_process_context: dict[str, object]
    terminal_scope_blocker: str | None
    volume_bias_next_actions: list[str]
    volume_source_backed_alternatives: list[dict[str, object]]
    volume_recommended_probe_order: list[dict[str, object]]
    et_partition_diagnostics_path: str | None
    et_partition_gate_context: str | None
    et_partition_diagnostic_flags: list[str]
    et_partition_next_actions: list[str]
    et_source_backed_alternatives: list[dict[str, object]]
    et_recommended_probe_order: list[dict[str, object]]
    mass_balance_diagnostics_path: str | None
    mass_balance_gate_context: str | None
    mass_balance_diagnostic_flags: list[str]
    mass_balance_next_actions: list[str]
    mass_balance_source_backed_alternatives: list[dict[str, object]]
    mass_balance_recommended_probe_order: list[dict[str, object]]
    skill_diagnostics_json: str | None
    skill_diagnostics_md: str | None
    skill_diagnostic_flags: list[str]
    skill_limitation_class: str | None
    skill_limitation_flags: list[str]
    skill_limitation_dominant_kge_component: str | None
    skill_limitation_recommended_focus: list[str]
    skill_limitation_claim_impact: str | None
    skill_evidence_metrics: list[dict[str, object]]
    skill_next_actions: list[str]
    skill_source_backed_alternatives: list[dict[str, object]]
    skill_recommended_probe_order: list[dict[str, object]]
    skill_probe_gap_parameters: list[str]
    skill_probe_gap_reasons: dict[str, str]
    skill_screened_dead_parameters: list[str]
    skill_unscreened_suggested_parameters: list[str]
    skill_usable_suggested_parameters: list[str]
    skill_channel_routing_screen_json: str | None
    skill_channel_routing_screen_md: str | None
    skill_channel_routing_activity_classes: dict[str, str]
    skill_channel_routing_effect_sizes: dict[str, float]
    skill_channel_routing_best_bounds: dict[str, dict[str, object]]
    skill_channel_routing_warnings: list[str]
    skill_channel_routing_calibration_verification_summary: str | None
    skill_channel_routing_calibration_best_solution_json: str | None
    skill_channel_routing_calibration_parameters: dict[str, float]
    skill_channel_routing_calibration_metrics: dict[str, float]
    skill_channel_routing_calibration_deltas: dict[str, float]
    skill_channel_routing_calibration_improved: bool | None
    calibrated_skill_parameter_values: dict[str, float]
    skill_parameter_bound_hits: dict[str, dict[str, object]]
    skill_parameter_bound_context: list[dict[str, object]]
    skill_parameter_bound_claim_impact: str | None
    unsupported_skill_parameters: list[str]
    superseded_unsupported_skill_parameters: list[str]
    blocked_skill_parameters: list[str]
    soil_next_actions: list[str]
    soil_source_backed_alternatives: list[dict[str, object]]
    soil_recommended_probe_order: list[dict[str, object]]
    build_diagnostic_artifacts: dict[str, str]
    allowed_claim_names: list[str]
    blocked_claim_names: list[str]
    claim_tier_matrix: dict[str, str]
    notes: str


def summarize_evidence(basin: str, evidence_summary_path: Path, *, area_km2: float | None = None) -> Row:
    payload = json.loads(evidence_summary_path.read_text(encoding="utf-8"))
    values = payload.get("values", {}) if isinstance(payload.get("values"), dict) else {}
    success = bool(payload.get("success"))
    blocker = str(payload.get("blocker_class") or "none")
    allowed_claims = payload.get("allowed_claims") if isinstance(payload.get("allowed_claims"), list) else []
    blocked_claims = payload.get("blocked_claims") if isinstance(payload.get("blocked_claims"), list) else []

    build = "pass" if success else "fail"
    warmup = "pass" if int(values.get("warmup_years", 0)) > 0 else "none"
    engine = "pass" if bool(values.get("fresh_engine_run")) else ("classified_failed" if not success else "unknown")
    physical_gates = str(values.get("physical_gates_status") or "unknown")
    routing_flow_gates_evidence_status = _str_or_none(values.get("routing_flow_gates_status"))
    routing_flow_gates = str(routing_flow_gates_evidence_status or "unknown")
    routing_flow_closure_evidence_status = _str_or_none(values.get("routing_flow_closure_status"))
    routing_flow_closure_status = routing_flow_closure_evidence_status
    cal_attempted = bool(values.get("calibration_attempted"))
    cal_success = bool(values.get("calibration_success"))
    calibration_provenance = (
        values.get("calibration_provenance")
        if isinstance(values.get("calibration_provenance"), dict)
        else {}
    )
    if not calibration_provenance and values.get("calibration_provenance_path"):
        calibration_payload = _read_json(Path(str(values.get("calibration_provenance_path"))))
        calibration_provenance = (
            calibration_payload.get("provenance")
            if isinstance(calibration_payload.get("provenance"), dict)
            else {}
        )
    calibration_error = str(calibration_provenance.get("error") or "")
    if cal_success:
        calibration = "done"
    elif "No calibration candidate passed the volume gate" in calibration_error:
        calibration = "blocked_by_volume_gate"
    elif "No calibration candidate passed the promotion gates" in calibration_error:
        calibration = "blocked_by_promotion_gate"
    elif cal_attempted:
        calibration = "attempted"
    else:
        calibration = str(values.get("calibration_status") or "blocked")
    calibration_phases = [
        phase
        for phase in values.get("calibration_phases", [])
        if isinstance(phase, dict)
    ]
    failed_phase = next(
        (
            phase
            for phase in calibration_phases
            if str(phase.get("status") or "").lower() == "failed"
        ),
        None,
    )
    calibration_failure_phase = _str_or_none(values.get("calibration_failure_phase"))
    if calibration_failure_phase is None:
        calibration_failure_phase = _phase_from_calibration_error(calibration_error)
    if calibration_failure_phase is None and failed_phase:
        calibration_failure_phase = _str_or_none(failed_phase.get("phase"))
    calibration_failure_message = _str_or_none(values.get("calibration_failure_message")) or calibration_error or (
        _str_or_none(failed_phase.get("message"))
        if failed_phase
        else None
    )
    calibration_failure_history_csv = _str_or_none(
        values.get("calibration_failure_history_csv")
        or calibration_provenance.get("history_csv")
    )
    calibration_failure_n_evaluations_raw = (
        values.get("calibration_failure_n_evaluations")
        if values.get("calibration_failure_n_evaluations") is not None
        else calibration_provenance.get("n_evaluations")
    )
    calibration_failure_n_evaluations = (
        int(calibration_failure_n_evaluations_raw)
        if isinstance(calibration_failure_n_evaluations_raw, int)
        else None
    )
    calibration_failure_promotion_gate_raw = values.get("calibration_failure_promotion_gate")
    if not isinstance(calibration_failure_promotion_gate_raw, dict):
        calibration_failure_promotion_gate_raw = calibration_provenance.get("promotion_gate")
    calibration_failure_promotion_gate = (
        calibration_failure_promotion_gate_raw
        if isinstance(calibration_failure_promotion_gate_raw, dict)
        else {}
    )
    (
        calibration_failure_history_csv,
        calibration_failure_n_evaluations,
        calibration_failure_promotion_gate,
    ) = _backfill_calibration_failure_context(
        calibration=calibration,
        history_csv=calibration_failure_history_csv,
        n_evaluations=calibration_failure_n_evaluations,
        promotion_gate=calibration_failure_promotion_gate,
        calibration_provenance=calibration_provenance,
        calibration_provenance_path=_str_or_none(values.get("calibration_provenance_path")),
    )
    calibration_failure_history_summary = _history_csv_failure_summary(
        calibration_failure_history_csv,
        evidence_summary_path=evidence_summary_path,
    )
    temporary_allowed = values.get(
        "temporary_candidate_metrics_allowed_as_final",
        calibration_provenance.get("temporary_candidate_metrics_allowed_as_final"),
    )
    final_metrics_authority = _str_or_none(
        values.get(
            "calibration_final_metrics_authority",
            calibration_provenance.get("final_metrics_authority"),
        )
    )

    metrics = values.get("metrics") if isinstance(values.get("metrics"), dict) else {}
    kge = _num(metrics.get("kge", values.get("baseline_kge")))
    nse = _num(metrics.get("nse", values.get("baseline_nse")))
    pbias = _num(metrics.get("pbias", metrics.get("pbias_pct")))
    baseline_metrics = values.get("baseline_metrics") if isinstance(values.get("baseline_metrics"), dict) else {}
    delta_metrics = values.get("calibration_delta_metrics") if isinstance(values.get("calibration_delta_metrics"), dict) else {}
    baseline_kge = _num(baseline_metrics.get("kge", values.get("baseline_kge")))
    baseline_nse = _num(baseline_metrics.get("nse", values.get("baseline_nse")))
    baseline_pbias = _num(baseline_metrics.get("pbias", baseline_metrics.get("pbias_pct")))
    delta_kge = _num(delta_metrics.get("kge"))
    delta_nse = _num(delta_metrics.get("nse"))
    delta_pbias = _num(delta_metrics.get("pbias"))
    blocked_names = [str(c.get("claim", "blocked_claim")) for c in blocked_claims if isinstance(c, dict)]
    allowed_names = [str(c.get("claim", "allowed_claim")) for c in allowed_claims if isinstance(c, dict)]
    notes = "; ".join(
        [
            f"blocked_claims={','.join(blocked_names) if blocked_names else 'none'}",
            f"allowed_claims={','.join(allowed_names) if allowed_names else 'none'}",
        ]
    )
    tier = str(payload.get("effective_claim_tier") or "unknown")
    gates_passed = [str(g) for g in payload.get("gates_passed", []) if isinstance(g, str)]
    gates_failed = [str(g) for g in payload.get("gates_failed", []) if isinstance(g, str)]
    context_flags = [
        str(f) for f in values.get("sensitivity_screen_context_flags", []) if isinstance(f, str)
    ]
    effective_classes = values.get("sensitivity_screen_effective_activity_classes")
    if not isinstance(effective_classes, dict):
        effective_classes = {}
    activity_classes = values.get("sensitivity_screen_activity_classes")
    if not isinstance(activity_classes, dict):
        activity_classes = {}
    if activity_classes:
        merged_effective_classes = dict(activity_classes)
        merged_effective_classes.update(effective_classes)
        effective_classes = merged_effective_classes
    physical_payload = _read_json(Path(str(values.get("physical_gates_path", ""))))
    condition_codes = [
        str(code)
        for code in physical_payload.get("condition_codes", [])
        if isinstance(code, str)
    ]
    physical_dominant_blocker = _str_or_none(physical_payload.get("dominant_blocker"))
    if "ET_DOMINATED" in condition_codes:
        if "et_dominated_pet_esco_epco_probe_required" not in context_flags:
            context_flags.append("et_dominated_pet_esco_epco_probe_required")
        for name in ("PET_CO", "ESCO", "EPCO"):
            effective_classes[name] = "requires_basin_screen"
    run_config_path = evidence_summary_path.parent / "run_config.json"
    run_config = _read_json(run_config_path)
    build_payload = run_config.get("build") if isinstance(run_config.get("build"), dict) else {}
    build_diagnostics = values.get("build_diagnostic_artifacts")
    if not isinstance(build_diagnostics, dict):
        build_diagnostics = build_payload.get("diagnostic_artifacts")
    if not isinstance(build_diagnostics, dict):
        build_diagnostics = {}
    build_diagnostics = {str(k): str(v) for k, v in build_diagnostics.items() if k and v}
    build_diagnostics.update(_discover_build_diagnostics(evidence_summary_path.parent, build_diagnostics))
    soil_actions, soil_alternatives, soil_probe_order = _soil_diagnostic_evidence(build_diagnostics)
    run_metadata = _read_json(evidence_summary_path.parent / "metadata.json")
    soil_mode = _str_or_none(values.get("soil_mode") or run_metadata.get("soil_mode"))
    soil_provenance_mode = _str_or_none(
        values.get("soil_provenance_mode")
        or run_metadata.get("soil_provenance_mode")
        or _metadata_note_value(run_metadata, "soil_provenance_mode")
    )
    pct_fallback_soils = _num(values.get("pct_fallback_soils", run_metadata.get("pct_fallback_soils")))
    soil_overlay_gap_fraction = _num(
        values.get("soil_overlay_gap_fraction", run_metadata.get("soil_overlay_gap_fraction"))
    )
    if not success and blocker == "soil_realism_gate_failed":
        if soil_mode in {None, "high_fidelity"}:
            soil_mode = "not_verified"
        if soil_provenance_mode is None:
            soil_provenance_mode = "soil_realism_gate_failed"
        if "soil_fidelity" not in gates_failed:
            gates_failed.append("soil_fidelity")
        gates_passed = [gate for gate in gates_passed if gate != "soil_fidelity"]
        policy_notes = values.get("policy_notes")
        if not policy_notes and "contract_policy" in gates_failed:
            gates_failed = [gate for gate in gates_failed if gate != "contract_policy"]
            if "contract_policy" not in gates_passed:
                gates_passed.append("contract_policy")
    if not _soil_fidelity_fields_pass(soil_mode, soil_provenance_mode, pct_fallback_soils):
        if "soil_fidelity" not in gates_failed:
            gates_failed.append("soil_fidelity")
        gates_passed = [gate for gate in gates_passed if gate != "soil_fidelity"]
        if tier == "research_grade":
            tier = "exploratory"
    if soil_overlay_gap_fraction is None and build_diagnostics.get("overlay_repair_report"):
        overlay_payload = _read_json(Path(build_diagnostics["overlay_repair_report"]))
        soil_overlay_gap_fraction = _num(overlay_payload.get("soil_gap_fraction"))
    hydrograph_overlay_plot = _str_or_none(values.get("hydrograph_observed_simulated_calibrated_plot"))
    if hydrograph_overlay_plot is None:
        hydrograph_overlay_plot = _sibling_hydrograph_overlay(values.get("hydrograph_comparison_plot"), ".png")
    hydrograph_overlay_plot_pdf = _str_or_none(values.get("hydrograph_observed_simulated_calibrated_plot_pdf"))
    if hydrograph_overlay_plot_pdf is None:
        hydrograph_overlay_plot_pdf = _sibling_hydrograph_overlay(values.get("hydrograph_comparison_plot_pdf"), ".pdf")
    volume_bias_diagnostics_path = _str_or_none(values.get("volume_bias_diagnostics_path"))
    if volume_bias_diagnostics_path is None:
        candidate = evidence_summary_path.parent / "reports" / "volume_bias_diagnostics.json"
        volume_bias_diagnostics_path = str(candidate) if candidate.is_file() else None
    volume_diag = _read_json(Path(volume_bias_diagnostics_path)) if volume_bias_diagnostics_path else {}
    volume_flags = [
        str(flag.get("code"))
        for flag in volume_diag.get("diagnostic_flags", [])
        if isinstance(flag, dict) and flag.get("code")
    ]
    volume_actions = [
        str(action)
        for action in volume_diag.get("next_actions", [])
        if isinstance(action, str) and action
    ]
    terminal_hydrograph_scope = (
        volume_diag.get("terminal_hydrograph_scope")
        if isinstance(volume_diag.get("terminal_hydrograph_scope"), dict)
        else (
            values.get("terminal_hydrograph_scope")
            if isinstance(values.get("terminal_hydrograph_scope"), dict)
            else {}
        )
    )
    terminal_scope_blocker = _str_or_none(
        values.get("terminal_scope_blocker")
        if values.get("terminal_scope_blocker") is not None
        else volume_diag.get("terminal_scope_blocker")
    )
    preliminary_routing_payload = values.get("final_routing_flow_gates")
    preliminary_routing_flow_gates_path = _str_or_none(values.get("routing_flow_gates_path"))
    if not isinstance(preliminary_routing_payload, dict) or not preliminary_routing_payload:
        preliminary_routing_payload = (
            _read_json(Path(preliminary_routing_flow_gates_path))
            if preliminary_routing_flow_gates_path
            else {}
        )
    if terminal_scope_blocker is None and isinstance(preliminary_routing_payload, dict):
        terminal_scope_blocker = classify_terminal_scope_blocker(preliminary_routing_payload)
    terminal_hydrograph_scope_classification = {
        "class": _str_or_none(volume_diag.get("terminal_hydrograph_scope_class")),
        "flags": [
            str(flag)
            for flag in volume_diag.get("terminal_hydrograph_scope_flags", [])
            if isinstance(flag, str) and flag
        ],
        "recommended_focus": [
            str(item)
            for item in volume_diag.get("terminal_hydrograph_scope_recommended_focus", [])
            if isinstance(item, str) and item
        ],
        "claim_impact": _str_or_none(volume_diag.get("terminal_hydrograph_scope_claim_impact")),
    }
    if terminal_hydrograph_scope and not terminal_hydrograph_scope_classification["class"]:
        terminal_hydrograph_scope_classification = classify_terminal_hydrograph_scope(
            terminal_hydrograph_scope,
            volume_flags,
        )
    terminal_scope_resolution_plan = (
        volume_diag.get("terminal_scope_resolution_plan")
        if isinstance(volume_diag.get("terminal_scope_resolution_plan"), dict)
        else build_terminal_scope_resolution_plan(
            terminal_hydrograph_scope,
            terminal_hydrograph_scope_classification,
            terminal_scope_blocker=terminal_scope_blocker,
        )
    )
    post_aggregation_process_context = (
        values.get("post_aggregation_process_context")
        if isinstance(values.get("post_aggregation_process_context"), dict)
        else (
            volume_diag.get("post_aggregation_process_context")
            if isinstance(volume_diag.get("post_aggregation_process_context"), dict)
            else {}
        )
    )
    volume_alternatives = [
        alt
        for alt in volume_diag.get("source_backed_alternatives", [])
        if isinstance(alt, dict)
    ]
    volume_probe_order = [
        probe
        for probe in volume_diag.get("recommended_probe_order", [])
        if isinstance(probe, dict)
    ]
    weather_forcing_summary = (
        volume_diag.get("weather_forcing_summary")
        if isinstance(volume_diag.get("weather_forcing_summary"), dict)
        else {}
    )
    weather_forcing_summary_path = _str_or_none(volume_diag.get("weather_forcing_summary_path"))
    high_runoff_demand_context = (
        volume_diag.get("high_runoff_demand_context")
        if isinstance(volume_diag.get("high_runoff_demand_context"), dict)
        else {}
    )
    volume_diagnostics_active = (
        "VOLUME_BIAS" in condition_codes
        or physical_dominant_blocker == "VOLUME_BIAS"
        or terminal_scope_blocker is not None
    )
    if not volume_diagnostics_active:
        volume_bias_diagnostics_path = None
        volume_flags = []
        terminal_hydrograph_scope = {}
        terminal_hydrograph_scope_classification = {
            "class": None,
            "flags": [],
            "recommended_focus": [],
            "claim_impact": None,
        }
        terminal_scope_blocker = None
        terminal_scope_resolution_plan = {
            "available": False,
            "status": "not_applicable",
            "diagnostic_only": True,
            "required_before_promotion": [],
            "fresh_locked_rerun_required": True,
            "temporary_terminal_metrics_allowed_as_final": False,
        }
        volume_actions = []
        volume_alternatives = []
        volume_probe_order = []
        weather_forcing_summary = {}
        weather_forcing_summary_path = None
        high_runoff_demand_context = {}
    volume_bias_primary_issue = (
        _str_or_none(values.get("volume_bias_primary_issue"))
        if volume_diagnostics_active
        else None
    )
    et_diagnostics_required = "ET_DOMINATED" in condition_codes
    et_partition_diagnostics_path = (
        _str_or_none(values.get("et_partition_diagnostics_path")) if et_diagnostics_required else None
    )
    if et_diagnostics_required and et_partition_diagnostics_path is None:
        candidate = evidence_summary_path.parent / "reports" / "et_partition_diagnostics.json"
        et_partition_diagnostics_path = str(candidate) if candidate.is_file() else None
    et_diag = _read_json(Path(et_partition_diagnostics_path)) if et_partition_diagnostics_path else {}
    et_flags = [
        str(flag.get("code"))
        for flag in et_diag.get("diagnostic_flags", [])
        if isinstance(flag, dict) and flag.get("code")
    ]
    if et_diagnostics_required and not et_flags:
        et_flags = [
            str(flag)
            for flag in values.get("et_partition_diagnostic_flags", [])
            if isinstance(flag, str) and flag
        ]
    et_actions = [
        str(action)
        for action in (
            et_diag.get("next_actions", values.get("et_partition_next_actions", []))
            if et_diagnostics_required
            else []
        )
        if isinstance(action, str) and action
    ]
    et_alternatives = [
        alt
        for alt in et_diag.get("source_backed_alternatives", [])
        if isinstance(alt, dict)
    ]
    et_probe_order = [
        probe
        for probe in et_diag.get("recommended_probe_order", [])
        if isinstance(probe, dict)
    ]
    mass_diagnostics_required = "MASS_IMBALANCE" in condition_codes
    mass_balance_diagnostics_path = (
        _str_or_none(values.get("mass_balance_diagnostics_path")) if mass_diagnostics_required else None
    )
    if mass_diagnostics_required and mass_balance_diagnostics_path is None:
        candidate = evidence_summary_path.parent / "reports" / "mass_balance_diagnostics.json"
        mass_balance_diagnostics_path = str(candidate) if candidate.is_file() else None
    mass_diag = _read_json(Path(mass_balance_diagnostics_path)) if mass_balance_diagnostics_path else {}
    mass_flags = [
        str(flag.get("code"))
        for flag in mass_diag.get("diagnostic_flags", [])
        if isinstance(flag, dict) and flag.get("code")
    ]
    if mass_diagnostics_required and not mass_flags:
        mass_flags = [
            str(flag)
            for flag in values.get("mass_balance_diagnostic_flags", [])
            if isinstance(flag, str) and flag
        ]
    mass_actions = [
        str(action)
        for action in (
            mass_diag.get("next_actions", values.get("mass_balance_next_actions", []))
            if mass_diagnostics_required
            else []
        )
        if isinstance(action, str) and action
    ]
    mass_alternatives = [
        alt
        for alt in mass_diag.get("source_backed_alternatives", [])
        if isinstance(alt, dict)
    ]
    mass_probe_order = [
        probe
        for probe in mass_diag.get("recommended_probe_order", [])
        if isinstance(probe, dict)
    ]
    mass_balance_gate_context = (
        _str_or_none(mass_diag.get("gate_context"))
        or (_str_or_none(values.get("mass_balance_gate_context")) if mass_diagnostics_required else None)
    )
    skill_diagnostics_json = _str_or_none(values.get("skill_diagnostics_json"))
    if skill_diagnostics_json is None:
        skill_diagnostics_json = _sibling_skill_diagnostics(evidence_summary_path.parent, ".json")
    skill_diagnostics_md = _str_or_none(values.get("skill_diagnostics_md"))
    if skill_diagnostics_md is None:
        skill_diagnostics_md = _sibling_skill_diagnostics(evidence_summary_path.parent, ".md")
    skill_diag = _read_json(Path(skill_diagnostics_json)) if skill_diagnostics_json else {}
    skill_flags = [
        str(flag.get("symptom"))
        for flag in skill_diag.get("diagnostic_flags", [])
        if isinstance(flag, dict) and flag.get("symptom")
    ]
    skill_evidence_metrics = [
        metrics
        for flag in skill_diag.get("diagnostic_flags", [])
        if isinstance(flag, dict)
        and isinstance((metrics := flag.get("evidence_metrics")), dict)
        and metrics
    ]
    skill_diagnostic_payload = [
        flag
        for flag in skill_diag.get("diagnostic_flags", [])
        if isinstance(flag, dict)
    ]
    skill_limitation = (
        skill_diag.get("skill_limitation")
        if isinstance(skill_diag.get("skill_limitation"), dict)
        else classify_skill_limitation(skill_diagnostic_payload)
        if skill_diagnostic_payload
        else {}
    )
    skill_limitation_flags = [
        str(flag)
        for flag in skill_limitation.get("flags", [])
        if isinstance(flag, str) and flag
    ]
    skill_limitation_focus = [
        str(item)
        for item in skill_limitation.get("recommended_focus", [])
        if isinstance(item, str) and item
    ]
    skill_actions = [
        str(action)
        for action in skill_diag.get("next_actions", [])
        if isinstance(action, str) and action
    ]
    skill_alternatives = [
        alt
        for alt in skill_diag.get("source_backed_alternatives", [])
        if isinstance(alt, dict)
    ]
    skill_suggested_parameters = _suggested_parameters_from_alternatives(skill_alternatives)
    skill_probe_order = [
        probe
        for probe in skill_diag.get("recommended_probe_order", [])
        if isinstance(probe, dict)
    ]
    raw_skill_gaps = skill_diag.get("skill_probe_gap_parameters")
    skill_probe_gap_parameters = (
        [str(param) for param in raw_skill_gaps if isinstance(param, str)]
        if isinstance(raw_skill_gaps, list)
        else _skill_probe_gap_parameters(skill_alternatives, effective_classes)
    )
    skill_sensitivity_classes = (
        {
            str(parameter): str(activity)
            for parameter, activity in skill_diag.get("sensitivity_screen_activity_classes", {}).items()
        }
        if isinstance(skill_diag.get("sensitivity_screen_activity_classes"), dict)
        else {str(parameter): str(activity) for parameter, activity in effective_classes.items()}
    )
    skill_probe_gap_reasons = _skill_gap_reasons(
        skill_probe_gap_parameters,
        skill_sensitivity_classes,
    )
    raw_screened_dead = skill_diag.get("skill_screened_dead_parameters")
    skill_screened_dead_parameters = (
        [str(parameter) for parameter in raw_screened_dead if isinstance(parameter, str)]
        if isinstance(raw_screened_dead, list)
        else [
            parameter
            for parameter in skill_probe_gap_parameters
            if skill_sensitivity_classes.get(parameter) == "dead"
        ]
    )
    raw_unscreened = skill_diag.get("skill_unscreened_suggested_parameters")
    skill_unscreened_suggested_parameters = (
        [str(parameter) for parameter in raw_unscreened if isinstance(parameter, str)]
        if isinstance(raw_unscreened, list)
        else [
            parameter
            for parameter in skill_probe_gap_parameters
            if parameter not in skill_sensitivity_classes
        ]
    )
    raw_usable = skill_diag.get("skill_usable_suggested_parameters")
    skill_usable_suggested_parameters = (
        [str(parameter) for parameter in raw_usable if isinstance(parameter, str)]
        if isinstance(raw_usable, list)
        else [
            parameter
            for parameter in skill_suggested_parameters
            if (activity := skill_sensitivity_classes.get(parameter))
            if activity in {"active", "weak", "limited", "requires_basin_screen"}
        ]
    )
    skill_channel_routing_screen_json = _str_or_none(
        values.get("skill_channel_routing_screen_json")
    ) or _sibling_channel_routing_screen(evidence_summary_path.parent, ".json")
    skill_channel_routing_screen_md = _str_or_none(
        values.get("skill_channel_routing_screen_md")
    ) or _sibling_channel_routing_screen(evidence_summary_path.parent, ".md")
    if not skill_channel_routing_screen_json:
        general_screen_json = _str_or_none(
            values.get("sensitivity_screen_path")
        ) or _sibling_locked_sensitivity_screen(evidence_summary_path.parent, ".json")
        general_screen_payload = _read_json(Path(general_screen_json)) if general_screen_json else {}
        general_channel_classes, _, _, _ = _parse_channel_routing_screen(general_screen_payload)
        if general_channel_classes:
            skill_channel_routing_screen_json = general_screen_json
            skill_channel_routing_screen_md = _str_or_none(
                values.get("sensitivity_screen_md")
            ) or _sibling_locked_sensitivity_screen(evidence_summary_path.parent, ".md")
    channel_screen_payload = (
        _read_json(Path(skill_channel_routing_screen_json))
        if skill_channel_routing_screen_json
        else {}
    )
    (
        skill_channel_routing_activity_classes,
        skill_channel_routing_effect_sizes,
        skill_channel_routing_best_bounds,
        skill_channel_routing_warnings,
    ) = _parse_channel_routing_screen(channel_screen_payload)
    if skill_channel_routing_activity_classes:
        merged_skill_sensitivity_classes = {
            **skill_sensitivity_classes,
            **skill_channel_routing_activity_classes,
        }
        skill_probe_gap_reasons = _skill_gap_reasons(
            skill_probe_gap_parameters,
            merged_skill_sensitivity_classes,
        )
        skill_screened_dead_parameters = [
            parameter
            for parameter in skill_probe_gap_parameters
            if merged_skill_sensitivity_classes.get(parameter) == "dead"
        ]
        skill_unscreened_suggested_parameters = [
            parameter
            for parameter in skill_probe_gap_parameters
            if parameter not in merged_skill_sensitivity_classes
        ]
        skill_usable_suggested_parameters = [
            parameter
            for parameter in skill_suggested_parameters
            if merged_skill_sensitivity_classes.get(parameter)
            in {"active", "weak", "limited", "requires_basin_screen"}
        ]
    skill_channel_routing_calibration_verification_summary = _str_or_none(
        values.get("skill_channel_routing_calibration_verification_summary")
    ) or _sibling_channel_routing_calibration_verification(evidence_summary_path.parent)
    skill_channel_routing_calibration_best_solution_json = _str_or_none(
        values.get("skill_channel_routing_calibration_best_solution_json")
    ) or _sibling_channel_routing_calibration_best_solution(evidence_summary_path.parent)
    channel_calibration_summary = (
        _read_json(Path(skill_channel_routing_calibration_verification_summary))
        if skill_channel_routing_calibration_verification_summary
        else {}
    )
    channel_calibration_best = (
        _read_json(Path(skill_channel_routing_calibration_best_solution_json))
        if skill_channel_routing_calibration_best_solution_json
        else {}
    )
    (
        skill_channel_routing_calibration_parameters,
        skill_channel_routing_calibration_metrics,
        skill_channel_routing_calibration_deltas,
        skill_channel_routing_calibration_improved,
    ) = _parse_channel_routing_calibration(
        channel_calibration_summary,
        channel_calibration_best,
    )
    calibration_failure_best_parameters = _float_dict(
        calibration_failure_history_summary.get("best_parameters")
    )
    (
        calibration_failure_best_parameter_bound_hits,
        calibration_failure_best_parameter_bound_context,
    ) = _parameter_bound_context(calibration_failure_best_parameters)
    calibration_bound_interaction_screen_json = _str_or_none(
        values.get("calibration_bound_interaction_screen_json")
    ) or _sibling_bound_interaction_screen(evidence_summary_path.parent)
    bound_interaction_payload = (
        _read_json(Path(calibration_bound_interaction_screen_json))
        if calibration_bound_interaction_screen_json
        else {}
    )
    (
        calibration_bound_interaction_candidate_count,
        calibration_bound_interaction_best_label,
        calibration_bound_interaction_best_parameters,
        calibration_bound_interaction_best_metrics,
        calibration_bound_interaction_claim_status,
    ) = _parse_bound_interaction_screen(bound_interaction_payload)
    calibrated_skill_parameter_values = _float_dict(skill_diag.get("calibrated_parameter_values"))
    raw_skill_bound_hits = skill_diag.get("calibrated_parameter_bound_hits")
    skill_parameter_bound_hits = (
        {
            str(param): hit
            for param, hit in raw_skill_bound_hits.items()
            if isinstance(hit, dict)
        }
        if isinstance(raw_skill_bound_hits, dict)
        else {}
    )
    skill_parameter_bound_context = [
        context
        for flag in skill_diag.get("diagnostic_flags", [])
        if isinstance(flag, dict)
        and isinstance((context := flag.get("parameter_bound_context")), dict)
    ]
    skill_parameter_bound_claim_impact = _str_or_none(
        skill_diag.get("parameter_bound_claim_impact")
    )
    unsupported_skill_parameters, blocked_skill_parameters = _skill_parameter_governance(skill_diag)
    superseded_unsupported_skill_parameters = _superseded_unsupported_skill_parameters(unsupported_skill_parameters)
    skill_diagnostics_active = bool({"BELOW_RESEARCH_SKILL", "NEGATIVE_SKILL"} & set(condition_codes)) or blocker in {
        "BELOW_RESEARCH_SKILL",
        "NEGATIVE_SKILL",
    }
    if not skill_diagnostics_active:
        skill_diagnostics_json = None
        skill_diagnostics_md = None
        skill_flags = []
        skill_limitation = {}
        skill_limitation_flags = []
        skill_limitation_focus = []
        skill_evidence_metrics = []
        skill_actions = []
        skill_alternatives = []
        skill_probe_order = []
        skill_probe_gap_parameters = []
        skill_probe_gap_reasons = {}
        skill_screened_dead_parameters = []
        skill_unscreened_suggested_parameters = []
        skill_usable_suggested_parameters = []
        skill_channel_routing_screen_json = None
        skill_channel_routing_screen_md = None
        skill_channel_routing_activity_classes = {}
        skill_channel_routing_effect_sizes = {}
        skill_channel_routing_best_bounds = {}
        skill_channel_routing_warnings = []
        skill_channel_routing_calibration_verification_summary = None
        skill_channel_routing_calibration_best_solution_json = None
        skill_channel_routing_calibration_parameters = {}
        skill_channel_routing_calibration_metrics = {}
        skill_channel_routing_calibration_deltas = {}
        skill_channel_routing_calibration_improved = None
        calibrated_skill_parameter_values = {}
        skill_parameter_bound_hits = {}
        skill_parameter_bound_context = []
        skill_parameter_bound_claim_impact = None
        unsupported_skill_parameters = []
        superseded_unsupported_skill_parameters = []
        blocked_skill_parameters = []
    routing_flow_gates_path = _str_or_none(values.get("routing_flow_gates_path"))
    routing_payload = _read_json(Path(routing_flow_gates_path)) if routing_flow_gates_path else {}
    final_routing_payload = values.get("final_routing_flow_gates")
    if isinstance(final_routing_payload, dict) and final_routing_payload:
        routing_payload = final_routing_payload
        routing_flow_gates_path = (
            _str_or_none(final_routing_payload.get("gate_json_path"))
            or _str_or_none(final_routing_payload.get("json_path"))
            or routing_flow_gates_path
        )
    if terminal_scope_blocker is None:
        terminal_scope_blocker = classify_terminal_scope_blocker(routing_payload)
    terminal_scope_claim = terminal_scope_blocked_claim(terminal_scope_blocker)
    if terminal_scope_claim and str(terminal_scope_claim["claim"]) not in set(blocked_names):
        blocked_names.append(str(terminal_scope_claim["claim"]))
        notes = "; ".join(
            [
                f"blocked_claims={','.join(blocked_names) if blocked_names else 'none'}",
                f"allowed_claims={','.join(allowed_names) if allowed_names else 'none'}",
            ]
        )
    if terminal_scope_claim and tier == "research_grade":
        tier = "exploratory"
        if "terminal_scope" not in gates_failed:
            gates_failed.append("terminal_scope")
        gates_passed = [gate for gate in gates_passed if gate != "terminal_scope"]
        notes = "; ".join(
            [
                notes,
                "current_policy_normalized_tier=exploratory",
                "normalization_reason=terminal_scope_claim_blocked",
            ]
        )
    terminal_trace_path = _str_or_none(routing_payload.get("terminal_trace_path"))
    terminal_payload = _read_json(Path(terminal_trace_path)) if terminal_trace_path else {}
    artifact_routing_status = _str_or_none(routing_payload.get("status"))
    artifact_closure_status = _str_or_none(routing_payload.get("closure_status"))
    if artifact_routing_status:
        routing_flow_gates = artifact_routing_status
    if artifact_closure_status:
        routing_flow_closure_status = artifact_closure_status
    if routing_flow_gates == "passed":
        if "routing_flow" not in gates_passed:
            gates_passed.append("routing_flow")
        gates_failed = [gate for gate in gates_failed if gate != "routing_flow"]
    elif routing_flow_gates in {"failed", "warning", "not_run"}:
        if "routing_flow" not in gates_failed:
            gates_failed.append("routing_flow")
        gates_passed = [gate for gate in gates_passed if gate != "routing_flow"]
    routing_flow_gate_status_mismatch = (
        bool(artifact_routing_status)
        and bool(routing_flow_gates_evidence_status)
        and artifact_routing_status != routing_flow_gates_evidence_status
    )
    routing_flow_closure_mismatch = (
        bool(artifact_closure_status)
        and bool(routing_flow_closure_evidence_status)
        and artifact_closure_status != routing_flow_closure_evidence_status
    )
    virtual_outlet_scope_gate = values.get("virtual_outlet_scope_gate")
    if not isinstance(virtual_outlet_scope_gate, dict):
        virtual_outlet_scope_gate = routing_payload.get("virtual_outlet_scope_gate")
    if not isinstance(virtual_outlet_scope_gate, dict):
        virtual_outlet_scope_gate = {}
    virtual_outlet_scope_gate_status = _str_or_none(
        values.get("virtual_outlet_scope_gate_status")
        or routing_payload.get("virtual_outlet_scope_gate_status")
        or virtual_outlet_scope_gate.get("status")
    )
    virtual_outlet_scope_gate_blockers = [
        str(item)
        for item in virtual_outlet_scope_gate.get("blockers", [])
        if isinstance(item, str) and item
    ]
    routing_flags = _routing_diagnostic_flags(routing_payload)
    routing_trace = _read_json(Path(str(routing_payload.get("json_path")))) if routing_payload.get("json_path") else {}
    routing_alternatives = [
        alt
        for alt in routing_trace.get("source_backed_alternatives", [])
        if isinstance(alt, dict)
    ]
    routing_probe_order = [
        probe
        for probe in routing_trace.get("recommended_probe_order", [])
        if isinstance(probe, dict)
    ]
    routing_diagnostics_active = routing_flow_gates in {"failed", "warning"} or terminal_scope_blocker is not None
    terminal_failure_class = _str_or_none(routing_payload.get("terminal_failure_class"))
    if not routing_diagnostics_active:
        routing_flags = []
        routing_alternatives = []
        routing_probe_order = []
        terminal_trace_path = None
        terminal_payload = {}
        terminal_failure_class = None
    calibration_precheck = _calibration_precheck_summary(
        values,
        calibration_provenance,
        physical_payload,
        routing_payload,
        calibration,
    )
    terminal_inventory = _dict_list(terminal_payload.get("terminal_inventory"))
    selected_outlet_gis_id = _safe_int_or_none(
        values.get("selected_outlet_gis_id") or terminal_payload.get("selected_outlet_gis_id")
    )
    nearest_terminal_gis_id = None
    selected_outlet_is_nearest_terminal = None
    selected_terminal_row: dict[str, object] | None = None
    nearest_terminal_row: dict[str, object] | None = None
    for terminal_row in terminal_inventory:
        terminal_gis_id = _safe_int_or_none(terminal_row.get("terminal_gis_id"))
        is_nearest = terminal_row.get("is_nearest_terminal") is True
        is_selected = terminal_row.get("is_selected_evaluation_outlet") is True
        if is_nearest:
            nearest_terminal_gis_id = terminal_gis_id
            nearest_terminal_row = terminal_row
        if selected_outlet_gis_id is not None and terminal_gis_id == selected_outlet_gis_id:
            selected_outlet_is_nearest_terminal = is_nearest
            selected_terminal_row = terminal_row
        elif selected_terminal_row is None and is_selected:
            selected_terminal_row = terminal_row
    routing_alternatives = _merge_ranked_items(
        _dict_list(terminal_payload.get("source_backed_alternatives")),
        routing_alternatives,
        key="option",
    )
    routing_probe_order = _merge_ranked_items(
        _dict_list(terminal_payload.get("recommended_probe_order")),
        routing_probe_order,
        key="diagnostic",
    )
    terminal_area_scope = {
        "class": _str_or_none(terminal_payload.get("terminal_area_scope_class")),
        "flags": [
            str(flag)
            for flag in terminal_payload.get("terminal_area_scope_flags", [])
            if isinstance(flag, str) and flag
        ],
        "claim_impact": _str_or_none(terminal_payload.get("terminal_area_scope_claim_impact")),
    }
    if not terminal_area_scope["class"] and terminal_payload:
        terminal_area_scope = classify_terminal_area_scope(
            selected_terminal_fraction_of_nldi_area=terminal_payload.get(
                "selected_terminal_fraction_of_nldi_area"
            ),
            all_terminal_fraction_of_nldi_area=terminal_payload.get(
                "all_terminal_fraction_of_nldi_area"
            ),
            selected_terminal_fraction_of_delineated_area=terminal_payload.get(
                "selected_terminal_fraction_of_delineated_area"
            ),
            all_terminal_fraction_of_delineated_area=terminal_payload.get(
                "all_terminal_fraction_of_delineated_area"
            ),
        )
    terminal_authority_area_check = terminal_payload.get("terminal_authority_area_check")
    if not isinstance(terminal_authority_area_check, dict) or not terminal_authority_area_check.get("class"):
        terminal_authority_area_check = classify_terminal_authority_area(
            selected_terminal_fraction_of_usgs_site_area=terminal_payload.get(
                "selected_terminal_fraction_of_usgs_site_area"
            ),
            all_terminal_fraction_of_usgs_site_area=terminal_payload.get(
                "all_terminal_fraction_of_usgs_site_area"
            ),
            selected_terminal_fraction_of_nldi_area=terminal_payload.get(
                "selected_terminal_fraction_of_nldi_area"
            ),
            all_terminal_fraction_of_nldi_area=terminal_payload.get(
                "all_terminal_fraction_of_nldi_area"
            ),
        )
    terminal_outlet_conflict = {
        "class": _str_or_none(terminal_payload.get("terminal_outlet_conflict_class")),
        "flags": [
            str(flag)
            for flag in terminal_payload.get("terminal_outlet_conflict_flags", [])
            if isinstance(flag, str) and flag
        ],
        "claim_impact": _str_or_none(terminal_payload.get("terminal_outlet_conflict_claim_impact")),
    }
    if not terminal_outlet_conflict["class"] and terminal_payload:
        terminal_outlet_conflict = classify_terminal_outlet_conflict(
            selected_row=selected_terminal_row,
            nearest_row=nearest_terminal_row,
            gauge_coordinate_source=terminal_payload.get("gauge_coordinate_source"),
        )

    row = Row(
        basin=basin,
        area_km2=area_km2,
        build=build,
        warmup=warmup,
        engine=engine,
        physical_gates=physical_gates,
        routing_flow_gates=routing_flow_gates,
        routing_flow_gates_evidence_status=routing_flow_gates_evidence_status,
        routing_flow_gate_status_mismatch=routing_flow_gate_status_mismatch,
        routing_flow_closure_status=routing_flow_closure_status,
        routing_flow_closure_evidence_status=routing_flow_closure_evidence_status,
        routing_flow_closure_mismatch=routing_flow_closure_mismatch,
        calibration=calibration,
        calibration_failure_phase=calibration_failure_phase,
        calibration_failure_message=calibration_failure_message,
        calibration_failure_history_csv=calibration_failure_history_csv,
        calibration_failure_n_evaluations=calibration_failure_n_evaluations,
        calibration_failure_promotion_gate=calibration_failure_promotion_gate,
        calibration_failure_volume_gate_pass_count=_safe_int_or_none(
            calibration_failure_history_summary.get("volume_gate_pass_count")
        ),
        calibration_failure_physical_gate_pass_count=_safe_int_or_none(
            calibration_failure_history_summary.get("physical_gate_pass_count")
        ),
        calibration_failure_process_gate_pass_count=_safe_int_or_none(
            calibration_failure_history_summary.get("process_gate_pass_count")
        ),
        calibration_failure_best_phase=_str_or_none(calibration_failure_history_summary.get("best_phase")),
        calibration_failure_best_abs_pbias=_num(calibration_failure_history_summary.get("best_abs_pbias")),
        calibration_failure_best_pbias=_num(calibration_failure_history_summary.get("best_pbias")),
        calibration_failure_best_kge=_num(calibration_failure_history_summary.get("best_kge")),
        calibration_failure_best_nse=_num(calibration_failure_history_summary.get("best_nse")),
        calibration_failure_best_parameters=calibration_failure_best_parameters,
        calibration_failure_best_parameter_bound_hits=calibration_failure_best_parameter_bound_hits,
        calibration_failure_best_parameter_bound_context=calibration_failure_best_parameter_bound_context,
        calibration_bound_interaction_screen_json=calibration_bound_interaction_screen_json,
        calibration_bound_interaction_candidate_count=calibration_bound_interaction_candidate_count,
        calibration_bound_interaction_best_label=calibration_bound_interaction_best_label,
        calibration_bound_interaction_best_parameters=calibration_bound_interaction_best_parameters,
        calibration_bound_interaction_best_metrics=calibration_bound_interaction_best_metrics,
        calibration_bound_interaction_claim_status=calibration_bound_interaction_claim_status,
        calibration_failure_skill_volume_near_miss=bool(
            calibration_failure_history_summary.get("skill_volume_near_miss")
        ),
        calibration_failure_near_miss_phase=_str_or_none(
            calibration_failure_history_summary.get("near_miss_phase")
        ),
        calibration_failure_near_miss_pbias=_num(calibration_failure_history_summary.get("near_miss_pbias")),
        calibration_failure_near_miss_kge=_num(calibration_failure_history_summary.get("near_miss_kge")),
        calibration_failure_near_miss_nse=_num(calibration_failure_history_summary.get("near_miss_nse")),
        calibration_failure_near_miss_parameters=_float_dict(
            calibration_failure_history_summary.get("near_miss_parameters")
        ),
        calibration_failure_skill_tradeoff_frontier=_history_frontier_dict(
            calibration_failure_history_summary.get("skill_tradeoff_frontier")
        ),
        calibration_failure_physical_condition_code_counts=_int_count_dict(
            calibration_failure_history_summary.get("physical_condition_code_counts")
        ),
        calibration_failure_physical_dominant_blocker_counts=_int_count_dict(
            calibration_failure_history_summary.get("physical_dominant_blocker_counts")
        ),
        calibration_failure_process_condition_code_counts=_int_count_dict(
            calibration_failure_history_summary.get("process_condition_code_counts")
        ),
        calibration_phase_parameter_coverage=_str_list_dict(
            calibration_failure_history_summary.get("phase_parameter_coverage")
        ),
        calibration_phase_evaluation_counts=_int_count_dict(
            calibration_failure_history_summary.get("phase_evaluation_counts")
        ),
        calibration_phase_order=_int_count_dict(
            calibration_failure_history_summary.get("phase_order")
        ),
        calibration_phase_volume_gate_pass_counts=_int_count_dict(
            calibration_failure_history_summary.get("phase_volume_gate_pass_counts")
        ),
        calibration_phase_physical_gate_pass_counts=_int_count_dict(
            calibration_failure_history_summary.get("phase_physical_gate_pass_counts")
        ),
        calibration_phase_process_gate_pass_counts=_int_count_dict(
            calibration_failure_history_summary.get("phase_process_gate_pass_counts")
        ),
        calibration_final_metrics_authority=final_metrics_authority,
        temporary_candidate_metrics_allowed_as_final=(
            temporary_allowed if isinstance(temporary_allowed, bool) else None
        ),
        calibration_precheck_sequence=calibration_precheck.get("sequence"),
        calibration_precheck_block_reason=calibration_precheck.get("block_reason"),
        calibration_precheck_physical_gates_status=calibration_precheck.get("physical_gates_status"),
        calibration_precheck_routing_flow_gates_status=calibration_precheck.get("routing_flow_gates_status"),
        kge=kge,
        nse=nse,
        pbias=pbias,
        baseline_kge=baseline_kge,
        baseline_nse=baseline_nse,
        baseline_pbias=baseline_pbias,
        delta_kge=delta_kge,
        delta_nse=delta_nse,
        delta_pbias=delta_pbias,
        tier=tier,
        blocker=blocker,
        primary_blocker="none",
        blocker_domain=None,
        blocker_action_items=[],
        gates_passed=gates_passed,
        gates_failed=gates_failed,
        physical_condition_codes=condition_codes,
        physical_dominant_blocker=physical_dominant_blocker,
        soil_mode=soil_mode,
        soil_provenance_mode=soil_provenance_mode,
        pct_fallback_soils=pct_fallback_soils,
        soil_overlay_gap_fraction=soil_overlay_gap_fraction,
        build_message=_str_or_none(build_payload.get("message")),
        volume_bias_primary_issue=volume_bias_primary_issue,
        sensitivity_context_flags=context_flags,
        sensitivity_effective_classes={str(k): str(v) for k, v in effective_classes.items()},
        sensitivity_screen_basis=_str_or_none(values.get("sensitivity_screen_basis")),
        sensitivity_activity_classes={str(k): str(v) for k, v in activity_classes.items()},
        evidence_summary_path=str(evidence_summary_path),
        run_config_path=str(run_config_path) if run_config_path.exists() else None,
        physical_gates_path=_str_or_none(values.get("physical_gates_path")),
        routing_flow_gates_path=routing_flow_gates_path,
        outlet_scope=_str_or_none(values.get("outlet_scope")),
        outlet_policy=_str_or_none(values.get("outlet_policy")),
        selected_outlet_gis_ids=_int_list(values.get("selected_outlet_gis_ids")),
        virtual_outlet_authority=_str_or_none(values.get("virtual_outlet_authority")),
        virtual_outlet_claim_authority=(
            bool(values.get("virtual_outlet_claim_authority"))
            if values.get("virtual_outlet_claim_authority") is not None
            else None
        ),
        virtual_outlet_scope_gate={
            str(k): v for k, v in virtual_outlet_scope_gate.items()
        },
        virtual_outlet_scope_gate_status=virtual_outlet_scope_gate_status,
        virtual_outlet_scope_gate_blockers=virtual_outlet_scope_gate_blockers,
        routing_flow_diagnostic_flags=routing_flags,
        routing_closure_reference=_str_or_none(routing_payload.get("closure_reference")),
        basin_routed_to_channel_m3=_num(routing_payload.get("basin_routed_to_channel_m3")),
        routed_to_channel_closure_ratio=_num(routing_payload.get("routed_to_channel_closure_ratio")),
        all_terminal_routed_to_channel_closure_ratio=_num(
            routing_payload.get("all_terminal_routed_to_channel_closure_ratio")
        ),
        all_terminal_mass_closure_ratio=_num(routing_payload.get("all_terminal_mass_closure_ratio")),
        selected_terminal_fraction_of_all_terminal_flow=_num(
            routing_payload.get("selected_terminal_fraction_of_all_terminal_flow")
        ),
        routing_source_backed_alternatives=routing_alternatives,
        routing_recommended_probe_order=routing_probe_order,
        terminal_trace_path=terminal_trace_path,
        terminal_failure_class=terminal_failure_class,
        missing_terminal_gis_ids=_int_list(terminal_payload.get("missing_terminal_gis_ids")),
        orphan_terminal_gis_ids=_int_list(terminal_payload.get("orphan_terminal_gis_ids")),
        material_missing_terminal_gis_ids=_int_list(terminal_payload.get("material_missing_terminal_gis_ids")),
        missing_terminal_upstream_area_km2=_num(terminal_payload.get("missing_terminal_upstream_area_km2")),
        terminal_gauge_lat=_num(terminal_payload.get("gauge_lat")),
        terminal_gauge_lon=_num(terminal_payload.get("gauge_lon")),
        terminal_gauge_coordinate_source=_str_or_none(terminal_payload.get("gauge_coordinate_source")),
        selected_outlet_distance_to_gauge_m=_num(terminal_payload.get("selected_outlet_distance_to_gauge_m")),
        nearest_terminal_gis_id=nearest_terminal_gis_id,
        selected_outlet_is_nearest_terminal=selected_outlet_is_nearest_terminal,
        terminal_basin_nldi_area_km2=_num(terminal_payload.get("basin_nldi_area_km2")),
        terminal_delineated_area_km2=_num(terminal_payload.get("delineated_area_km2")),
        selected_terminal_upstream_area_km2=_num(terminal_payload.get("selected_terminal_upstream_area_km2")),
        all_terminal_upstream_area_km2=_num(terminal_payload.get("all_terminal_upstream_area_km2")),
        selected_terminal_fraction_of_nldi_area=_num(
            terminal_payload.get("selected_terminal_fraction_of_nldi_area")
        ),
        selected_terminal_fraction_of_usgs_site_area=_num(
            terminal_payload.get("selected_terminal_fraction_of_usgs_site_area")
        ),
        all_terminal_fraction_of_nldi_area=_num(terminal_payload.get("all_terminal_fraction_of_nldi_area")),
        all_terminal_fraction_of_usgs_site_area=_num(
            terminal_payload.get("all_terminal_fraction_of_usgs_site_area")
        ),
        delineated_fraction_of_nldi_area=_num(terminal_payload.get("delineated_fraction_of_nldi_area")),
        selected_terminal_fraction_of_delineated_area=_num(
            terminal_payload.get("selected_terminal_fraction_of_delineated_area")
        ),
        all_terminal_fraction_of_delineated_area=_num(
            terminal_payload.get("all_terminal_fraction_of_delineated_area")
        ),
        terminal_area_scope_class=_str_or_none(terminal_area_scope.get("class")),
        terminal_area_scope_flags=[
            str(flag)
            for flag in terminal_area_scope.get("flags", [])
            if isinstance(flag, str) and flag
        ],
        terminal_area_scope_claim_impact=_str_or_none(terminal_area_scope.get("claim_impact")),
        usgs_site_drainage_area_km2=_num(terminal_payload.get("usgs_site_drainage_area_km2")),
        usgs_site_drainage_area_sqmi=_num(terminal_payload.get("usgs_site_drainage_area_sqmi")),
        usgs_site_drainage_area_source=_str_or_none(
            terminal_payload.get("usgs_site_drainage_area_source")
        ),
        terminal_authority_area_check={
            str(k): v for k, v in terminal_authority_area_check.items()
        },
        terminal_virtual_outlet_candidate={
            str(k): v
            for k, v in (
                terminal_payload.get("terminal_virtual_outlet_candidate")
                if isinstance(terminal_payload.get("terminal_virtual_outlet_candidate"), dict)
                else {}
            ).items()
        },
        terminal_virtual_outlet_candidate_path=_str_or_none(
            terminal_payload.get("terminal_virtual_outlet_candidate_path")
        ),
        terminal_outlet_conflict_class=_str_or_none(terminal_outlet_conflict.get("class")),
        terminal_outlet_conflict_flags=[
            str(flag)
            for flag in terminal_outlet_conflict.get("flags", [])
            if isinstance(flag, str) and flag
        ],
        terminal_outlet_conflict_claim_impact=_str_or_none(
            terminal_outlet_conflict.get("claim_impact")
        ),
        terminal_shared_upstream_area_km2=_num(terminal_payload.get("shared_upstream_area_km2")),
        terminal_overlap_pair_count=len(_dict_list(terminal_payload.get("terminal_overlap_pairs"))),
        terminal_overlap_pairs=_dict_list(terminal_payload.get("terminal_overlap_pairs")),
        calibration_provenance_path=_str_or_none(values.get("calibration_provenance_path")),
        hydrograph_comparison_status=_str_or_none(values.get("hydrograph_comparison_status")),
        hydrograph_comparison_plot=_str_or_none(values.get("hydrograph_comparison_plot")),
        hydrograph_comparison_plot_pdf=_str_or_none(values.get("hydrograph_comparison_plot_pdf")),
        hydrograph_observed_simulated_calibrated_plot=hydrograph_overlay_plot,
        hydrograph_observed_simulated_calibrated_plot_pdf=hydrograph_overlay_plot_pdf,
        hydrograph_comparison_metrics=_str_or_none(values.get("hydrograph_comparison_metrics")),
        volume_bias_diagnostics_path=volume_bias_diagnostics_path,
        weather_forcing_summary_path=weather_forcing_summary_path,
        weather_forcing_summary=weather_forcing_summary,
        high_runoff_demand_context=high_runoff_demand_context,
        volume_bias_diagnostic_flags=volume_flags,
        terminal_hydrograph_scope=terminal_hydrograph_scope,
        terminal_hydrograph_scope_class=_str_or_none(
            terminal_hydrograph_scope_classification.get("class")
        ),
        terminal_hydrograph_scope_flags=[
            str(flag)
            for flag in terminal_hydrograph_scope_classification.get("flags", [])
            if isinstance(flag, str) and flag
        ],
        terminal_hydrograph_scope_recommended_focus=[
            str(item)
            for item in terminal_hydrograph_scope_classification.get("recommended_focus", [])
            if isinstance(item, str) and item
        ],
        terminal_hydrograph_scope_claim_impact=_str_or_none(
            terminal_hydrograph_scope_classification.get("claim_impact")
        ),
        terminal_scope_resolution_plan=terminal_scope_resolution_plan,
        post_aggregation_process_context=post_aggregation_process_context,
        terminal_scope_blocker=terminal_scope_blocker,
        volume_bias_next_actions=volume_actions,
        volume_source_backed_alternatives=volume_alternatives,
        volume_recommended_probe_order=volume_probe_order,
        et_partition_diagnostics_path=et_partition_diagnostics_path,
        et_partition_gate_context=_str_or_none(et_diag.get("gate_context")),
        et_partition_diagnostic_flags=et_flags,
        et_partition_next_actions=et_actions,
        et_source_backed_alternatives=et_alternatives,
        et_recommended_probe_order=et_probe_order,
        mass_balance_diagnostics_path=mass_balance_diagnostics_path,
        mass_balance_gate_context=mass_balance_gate_context,
        mass_balance_diagnostic_flags=mass_flags,
        mass_balance_next_actions=mass_actions,
        mass_balance_source_backed_alternatives=mass_alternatives,
        mass_balance_recommended_probe_order=mass_probe_order,
        skill_diagnostics_json=skill_diagnostics_json,
        skill_diagnostics_md=skill_diagnostics_md,
        skill_diagnostic_flags=skill_flags,
        skill_limitation_class=_str_or_none(skill_limitation.get("class")),
        skill_limitation_flags=skill_limitation_flags,
        skill_limitation_dominant_kge_component=_str_or_none(
            skill_limitation.get("dominant_kge_component")
        ),
        skill_limitation_recommended_focus=skill_limitation_focus,
        skill_limitation_claim_impact=_str_or_none(skill_limitation.get("claim_impact")),
        skill_evidence_metrics=skill_evidence_metrics,
        skill_next_actions=skill_actions,
        skill_source_backed_alternatives=skill_alternatives,
        skill_recommended_probe_order=skill_probe_order,
        skill_probe_gap_parameters=skill_probe_gap_parameters,
        skill_probe_gap_reasons=skill_probe_gap_reasons,
        skill_screened_dead_parameters=skill_screened_dead_parameters,
        skill_unscreened_suggested_parameters=skill_unscreened_suggested_parameters,
        skill_usable_suggested_parameters=skill_usable_suggested_parameters,
        skill_channel_routing_screen_json=skill_channel_routing_screen_json,
        skill_channel_routing_screen_md=skill_channel_routing_screen_md,
        skill_channel_routing_activity_classes=skill_channel_routing_activity_classes,
        skill_channel_routing_effect_sizes=skill_channel_routing_effect_sizes,
        skill_channel_routing_best_bounds=skill_channel_routing_best_bounds,
        skill_channel_routing_warnings=skill_channel_routing_warnings,
        skill_channel_routing_calibration_verification_summary=(
            skill_channel_routing_calibration_verification_summary
        ),
        skill_channel_routing_calibration_best_solution_json=(
            skill_channel_routing_calibration_best_solution_json
        ),
        skill_channel_routing_calibration_parameters=skill_channel_routing_calibration_parameters,
        skill_channel_routing_calibration_metrics=skill_channel_routing_calibration_metrics,
        skill_channel_routing_calibration_deltas=skill_channel_routing_calibration_deltas,
        skill_channel_routing_calibration_improved=skill_channel_routing_calibration_improved,
        calibrated_skill_parameter_values=calibrated_skill_parameter_values,
        skill_parameter_bound_hits=skill_parameter_bound_hits,
        skill_parameter_bound_context=skill_parameter_bound_context,
        skill_parameter_bound_claim_impact=skill_parameter_bound_claim_impact,
        unsupported_skill_parameters=unsupported_skill_parameters,
        superseded_unsupported_skill_parameters=superseded_unsupported_skill_parameters,
        blocked_skill_parameters=blocked_skill_parameters,
        soil_next_actions=soil_actions,
        soil_source_backed_alternatives=soil_alternatives,
        soil_recommended_probe_order=soil_probe_order,
        build_diagnostic_artifacts=build_diagnostics,
        allowed_claim_names=allowed_names,
        blocked_claim_names=blocked_names,
        claim_tier_matrix=_compute_claim_tier_matrix(payload),
        notes=notes or "none",
    )
    row.primary_blocker = _primary_blocker(row)
    return row


def run_suite(
    out_root: Path,
    *,
    resume_existing: bool = False,
    evidence_overrides: dict[str, Path] | None = None,
) -> list[Row]:
    from swatplus_builder.workflows.usgs_e2e import RunUSGSWorkflowRequest, run_usgs_workflow

    evidence_overrides = evidence_overrides or {}
    rows: list[Row] = []
    for basin in BASINS:
        if basin in evidence_overrides:
            rows.append(
                summarize_evidence(
                    basin,
                    evidence_overrides[basin],
                    area_km2=AREA_HINTS.get(basin),
                )
            )
            continue
        bdir = out_root / basin
        evidence_summary_path = bdir / "evidence_summary.json"
        if resume_existing and evidence_summary_path.exists():
            rows.append(summarize_evidence(basin, evidence_summary_path, area_km2=AREA_HINTS.get(basin)))
            continue
        req = RunUSGSWorkflowRequest(
            usgs_id=basin,
            out_dir=bdir,
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="policy",
            calibrate=True,
        )
        res = run_usgs_workflow(req)
        rows.append(summarize_evidence(basin, Path(res.evidence_summary_path), area_km2=AREA_HINTS.get(basin)))
    return rows


def summarize_existing_suite(
    out_root: Path,
    *,
    evidence_overrides: dict[str, Path] | None = None,
) -> list[Row]:
    evidence_overrides = evidence_overrides or {}
    rows: list[Row] = []
    for basin in BASINS:
        evidence_summary_path = evidence_overrides.get(
            basin,
            out_root / basin / "evidence_summary.json",
        )
        if not evidence_summary_path.exists():
            raise FileNotFoundError(
                f"Missing evidence summary for basin {basin}: {evidence_summary_path}"
            )
        rows.append(
            summarize_evidence(
                basin,
                evidence_summary_path,
                area_km2=AREA_HINTS.get(basin),
            )
        )
    return rows


def _parse_evidence_overrides(values: Sequence[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(
                f"Invalid --evidence-override {value!r}; expected BASIN=path/to/evidence_summary.json"
            )
        basin, raw_path = value.split("=", 1)
        basin = basin.strip()
        if basin not in BASINS:
            raise ValueError(f"Invalid --evidence-override basin {basin!r}; expected one of {', '.join(BASINS)}")
        path = Path(raw_path).expanduser().resolve()
        overrides[basin] = path
    return overrides


def write_outputs(
    rows: list[Row],
    out_md: Path,
    out_json: Path,
    *,
    generation_metadata: dict[str, object] | None = None,
) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    for row in rows:
        row.primary_blocker = _primary_blocker(row)
        row.blocker_domain = None if row.tier == "research_grade" else _blocker_domain(row.primary_blocker)
        row.blocker_action_items = [] if row.tier == "research_grade" else _row_action_items(row)

    blocker_classification = _non_research_blocker_classification(rows)
    target_hypothesis = _target_hypothesis_evaluation(rows, blocker_classification)
    improvement_plan = _pipeline_improvement_plan(rows, target_hypothesis)
    science_summary = _science_blocker_summary(rows, blocker_classification)
    claim_matrix_summary = _claim_tier_matrix_summary(rows)
    data = {
        "date": date.today().isoformat(),
        "basin_count": len(rows),
        "research_grade_count": sum(1 for r in rows if r.tier == "research_grade"),
        "claim_tier_matrix_summary": claim_matrix_summary,
        "non_research_blocker_classification": blocker_classification,
        "target_hypothesis_evaluation": target_hypothesis,
        "science_blocker_summary": science_summary,
        "pipeline_improvement_plan": improvement_plan,
        "generation": generation_metadata or {},
        "rows": [asdict(r) for r in rows],
    }
    out_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    claim_types = claim_matrix_summary["claim_types"]
    lines = [
        "# Objective Basin Validation Report",
        "",
        f"- Date: `{data['date']}`",
        f"- Basins: `{len(rows)}`",
        f"- Research-grade outcomes: `{data['research_grade_count']}`",
        "",
        "## Per-Claim Tier Matrix",
        "",
        "Achieved tier per claim class (highest tier where all claims of that class are unblocked).",
        "",
        "| Basin | " + " | ".join(claim_types) + " |",
        "|---" + ("|---" * len(claim_types)) + "|",
    ] + [
        "| " + r.basin + " | " + " | ".join(r.claim_tier_matrix.get(ct, "—") for ct in claim_types) + " |"
        for r in rows
    ] + [
        "",
        "**Summary (basins at each tier per claim class)**",
        "",
        "| Claim class | " + " | ".join(sorted(_TIER_RANK, key=lambda t: -_TIER_RANK[t])) + " |",
        "|---" + ("|---" * len(_TIER_RANK)) + "|",
    ] + [
        "| " + ct + " | "
        + " | ".join(
            str(claim_matrix_summary["counts"][ct].get(tier, 0))
            for tier in sorted(_TIER_RANK, key=lambda t: -_TIER_RANK[t])
        ) + " |"
        for ct in claim_types
    ] + [
        "",
        "## Non-Research Classification",
        "",
        (
            "- Domain counts: "
            + ", ".join(
                f"`{name}={count}`"
                for name, count in blocker_classification["domain_counts"].items()
            )
        ),
        f"- Unclassified blockers: `{', '.join(blocker_classification['unclassified_blockers']) or 'none'}`",
        (
            "- Target hypothesis: "
            f"`{target_hypothesis['status']}`; observed "
            f"`{target_hypothesis['observed_research_grade_count']}` / "
            f"`{target_hypothesis['target_research_grade_count']}`; "
            f"gate weakening permitted=`{target_hypothesis['gate_weakening_permitted']}`"
        ),
        (
            "- Pipeline improvement plan: "
            f"`{improvement_plan['status']}`; domains="
            f"`{', '.join(improvement_plan['domains']) or 'none'}`; "
            f"temporary metrics as final=`{improvement_plan['temporary_metrics_allowed_as_final']}`"
        ),
        (
            "- Science blocker summary: "
            f"`{science_summary['status']}`; blockers="
            f"`{', '.join(f'{k}={v}' for k, v in science_summary['primary_blocker_counts'].items()) or 'none'}`; "
            f"gate weakening permitted=`{science_summary['gate_weakening_permitted']}`"
        ),
        "",
        "| Basin | Area | Build | Engine | Physical | Routing | Calibration | KGE | NSE | PBIAS | ΔKGE | ΔNSE | ΔPBIAS | Soil | Sensitivity | Tier | Gates failed | Primary blocker |",
        "|---|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|",
    ]
    for r in rows:
        area = "n/a" if r.area_km2 is None else f"{r.area_km2:g}"
        kge = "n/a" if r.kge is None else f"{r.kge:.3f}"
        nse = "n/a" if r.nse is None else f"{r.nse:.3f}"
        pbias = "n/a" if r.pbias is None else f"{r.pbias:.1f}"
        dkge = "n/a" if r.delta_kge is None else f"{r.delta_kge:+.3f}"
        dnse = "n/a" if r.delta_nse is None else f"{r.delta_nse:+.3f}"
        dpbias = "n/a" if r.delta_pbias is None else f"{r.delta_pbias:+.1f}"
        soil = _soil_summary(r)
        sensitivity = r.sensitivity_screen_basis or "unknown"
        failed = ",".join(r.gates_failed) if r.gates_failed else "none"
        primary = r.primary_blocker or _primary_blocker(r)
        routing = (
            r.routing_flow_gates
            if not r.routing_flow_closure_status
            else f"{r.routing_flow_gates}:{r.routing_flow_closure_status}"
        )
        lines.append(
            f"| {r.basin} | {area} | {r.build} | {r.engine} | {r.physical_gates} | {routing} | {r.calibration} | {kge} | {nse} | {pbias} | {dkge} | {dnse} | {dpbias} | {soil} | {sensitivity} | {r.tier} | {failed} | {primary} |"
        )
    lines += [
        "",
        "## Pipeline Improvement Plan",
        "",
    ]
    if improvement_plan["items"]:
        for item in improvement_plan["items"]:
            blockers = ", ".join(
                f"{name}={count}"
                for name, count in item["primary_blocker_counts"].items()
            )
            lines.append(
                f"- `{item['domain']}`: {item['basin_count']} basin(s); "
                f"blockers `{blockers}`; next experiment `{item['next_experiment']}`"
            )
            for basin_item in item.get("basin_items", []):
                artifacts = basin_item.get("evidence_artifacts", {})
                artifact_keys = (
                    ", ".join(sorted(artifacts))
                    if isinstance(artifacts, dict) and artifacts
                    else "none"
                )
                decision = basin_item.get("decision_request", {})
                decision_status = (
                    decision.get("status")
                    if isinstance(decision, dict)
                    else "unknown"
                )
                lines.append(
                    f"  - `{basin_item.get('basin')}`: "
                    f"`{basin_item.get('next_experiment')}`; "
                    f"decision `{decision_status}`; evidence `{artifact_keys}`"
                )
    else:
        lines.append("- No non-science pipeline-improvement domains are active in current evidence.")
    lines += [
        "",
        "## Science Blocker Summary",
        "",
    ]
    if science_summary["items"]:
        for item in science_summary["items"]:
            lines.append(
                f"- `{item['primary_blocker']}`: {item['basin_count']} basin(s); "
                f"evidence `{', '.join(item['source_evidence_fields']) or 'none'}`; "
                f"claim impact `{item['claim_impact']}`"
            )
            for basin_item in item.get("basin_items", []):
                lines.append(
                    f"  - `{basin_item.get('basin')}`: "
                    f"`{basin_item.get('evidence_type')}`; "
                    f"class `{basin_item.get('classification') or 'n/a'}`; "
                    f"first probe `{basin_item.get('first_probe') or 'n/a'}`"
                )
    else:
        lines.append("- No science blockers are active in current evidence.")
    lines += [
        "",
        "## Evidence",
        "",
    ]
    for r in rows:
        lines.append(f"- `{r.basin}`: `{r.evidence_summary_path}`")
        if r.hydrograph_comparison_plot:
            lines.append(f"  - hydrograph plot: `{r.hydrograph_comparison_plot}`")
        if r.hydrograph_comparison_plot_pdf:
            lines.append(f"  - hydrograph pdf: `{r.hydrograph_comparison_plot_pdf}`")
        if r.hydrograph_observed_simulated_calibrated_plot:
            lines.append(
                "  - observed/simulated/calibrated hydrograph: "
                f"`{r.hydrograph_observed_simulated_calibrated_plot}`"
            )
        if r.hydrograph_observed_simulated_calibrated_plot_pdf:
            lines.append(
                "  - observed/simulated/calibrated hydrograph pdf: "
                f"`{r.hydrograph_observed_simulated_calibrated_plot_pdf}`"
            )
        if r.hydrograph_comparison_metrics:
            lines.append(f"  - hydrograph metrics: `{r.hydrograph_comparison_metrics}`")
        if r.routing_flow_gates_path:
            lines.append(f"  - routing-flow gates: `{r.routing_flow_gates_path}`")
        if r.routing_flow_gate_status_mismatch or r.routing_flow_closure_mismatch:
            lines.append(
                "  - routing evidence mismatch: "
                f"evidence_summary status `{r.routing_flow_gates_evidence_status}`/"
                f"`{r.routing_flow_closure_evidence_status}`, gate artifact "
                f"`{r.routing_flow_gates}`/`{r.routing_flow_closure_status}`"
            )
        if r.routing_flow_diagnostic_flags:
            lines.append(f"  - routing-flow flags: `{', '.join(r.routing_flow_diagnostic_flags)}`")
        if r.routing_closure_reference:
            routed_ratio = (
                "n/a"
                if r.routed_to_channel_closure_ratio is None
                else f"{r.routed_to_channel_closure_ratio:.3f}"
            )
            all_terminal_routed_ratio = (
                "n/a"
                if r.all_terminal_routed_to_channel_closure_ratio is None
                else f"{r.all_terminal_routed_to_channel_closure_ratio:.3f}"
            )
            selected_share = (
                "n/a"
                if r.selected_terminal_fraction_of_all_terminal_flow is None
                else f"{r.selected_terminal_fraction_of_all_terminal_flow:.3f}"
            )
            lines.append(
                "  - routing closure reference: "
                f"`{r.routing_closure_reference}`; selected/routed-to-channel ratio `{routed_ratio}`; "
                f"all-terminal/routed-to-channel ratio `{all_terminal_routed_ratio}`; "
                f"selected/all-terminal share `{selected_share}`"
            )
        if r.routing_source_backed_alternatives:
            options = [
                str(alt.get("option"))
                for alt in r.routing_source_backed_alternatives
                if isinstance(alt, dict) and alt.get("option")
            ]
            if options:
                lines.append(f"  - routing source-backed alternatives: `{', '.join(options)}`")
        if r.routing_recommended_probe_order:
            probes = [
                str(probe.get("diagnostic"))
                for probe in r.routing_recommended_probe_order
                if isinstance(probe, dict) and probe.get("diagnostic")
            ]
            if probes:
                lines.append(f"  - routing recommended probe order: `{', '.join(probes)}`")
        if r.terminal_trace_path:
            lines.append(f"  - terminal inventory: `{r.terminal_trace_path}`")
        if r.terminal_failure_class:
            lines.append(f"  - terminal failure class: `{r.terminal_failure_class}`")
        if r.terminal_gauge_coordinate_source:
            lines.append(
                "  - terminal gauge coordinate source: "
                f"`{r.terminal_gauge_coordinate_source}`; nearest terminal "
                f"`{r.nearest_terminal_gis_id if r.nearest_terminal_gis_id is not None else 'n/a'}`; "
                f"selected outlet nearest=`{r.selected_outlet_is_nearest_terminal}`; "
                f"selected distance `{_fmt_optional(r.selected_outlet_distance_to_gauge_m)}` m"
            )
        if r.terminal_overlap_pair_count:
            worst = r.terminal_overlap_pairs[0] if r.terminal_overlap_pairs else {}
            lines.append(
                "  - terminal overlap pairs: "
                f"`{r.terminal_overlap_pair_count}`; worst pair "
                f"`{worst.get('terminal_a_gis_id', 'n/a')}-{worst.get('terminal_b_gis_id', 'n/a')}` "
                f"shared area `{_fmt_optional(_num(worst.get('shared_upstream_area_km2')))}` km2"
            )
        if r.selected_terminal_fraction_of_nldi_area is not None or r.all_terminal_fraction_of_nldi_area is not None:
            selected_area_fraction = (
                "n/a"
                if r.selected_terminal_fraction_of_nldi_area is None
                else f"{r.selected_terminal_fraction_of_nldi_area:.3f}"
            )
            all_area_fraction = (
                "n/a"
                if r.all_terminal_fraction_of_nldi_area is None
                else f"{r.all_terminal_fraction_of_nldi_area:.3f}"
            )
            lines.append(
                "  - terminal area fractions: "
                f"selected/NLDI `{selected_area_fraction}`; all-terminal/NLDI `{all_area_fraction}`"
            )
        if (
            r.usgs_site_drainage_area_km2 is not None
            or r.selected_terminal_fraction_of_usgs_site_area is not None
            or r.all_terminal_fraction_of_usgs_site_area is not None
        ):
            selected_usgs_fraction = (
                "n/a"
                if r.selected_terminal_fraction_of_usgs_site_area is None
                else f"{r.selected_terminal_fraction_of_usgs_site_area:.3f}"
            )
            all_usgs_fraction = (
                "n/a"
                if r.all_terminal_fraction_of_usgs_site_area is None
                else f"{r.all_terminal_fraction_of_usgs_site_area:.3f}"
            )
            authority_class = r.terminal_authority_area_check.get("class", "n/a")
            lines.append(
                "  - USGS site drainage-area check: "
                f"area `{_fmt_optional(r.usgs_site_drainage_area_km2)}` km2; "
                f"selected/USGS `{selected_usgs_fraction}`; all-terminal/USGS `{all_usgs_fraction}`; "
                f"class `{authority_class}`"
            )
        if r.terminal_virtual_outlet_candidate:
            candidate = r.terminal_virtual_outlet_candidate
            lines.append(
                "  - terminal virtual outlet candidate: "
                f"status `{candidate.get('status', 'n/a')}`; "
                f"claim_authority `{candidate.get('claim_authority', 'n/a')}`; "
                f"fresh locked rerun `{candidate.get('fresh_locked_rerun_required', 'n/a')}`"
            )
        if r.terminal_area_scope_class:
            lines.append(
                "  - terminal area-scope class: "
                f"`{r.terminal_area_scope_class}`; flags "
                f"`{', '.join(r.terminal_area_scope_flags) or 'none'}`"
            )
        if r.terminal_outlet_conflict_class:
            lines.append(
                "  - terminal outlet conflict class: "
                f"`{r.terminal_outlet_conflict_class}`; flags "
                f"`{', '.join(r.terminal_outlet_conflict_flags) or 'none'}`"
            )
        if r.missing_terminal_gis_ids or r.orphan_terminal_gis_ids or r.material_missing_terminal_gis_ids:
            lines.append(
                "  - terminal missing/orphan IDs: "
                f"missing=`{','.join(str(v) for v in r.missing_terminal_gis_ids) or 'none'}`, "
                f"orphan=`{','.join(str(v) for v in r.orphan_terminal_gis_ids) or 'none'}`, "
                f"material_missing=`{','.join(str(v) for v in r.material_missing_terminal_gis_ids) or 'none'}`"
            )
        if r.soil_mode or r.pct_fallback_soils is not None or r.soil_overlay_gap_fraction is not None:
            lines.append(f"  - soil provenance: `{_soil_summary(r)}`")
        if r.calibration_failure_phase:
            lines.append(f"  - calibration failure phase: `{r.calibration_failure_phase}`")
        if r.calibration_failure_message:
            lines.append(f"  - calibration failure message: {r.calibration_failure_message}")
        if r.calibration_failure_history_csv:
            lines.append(f"  - calibration history csv: `{r.calibration_failure_history_csv}`")
        if r.calibration_phase_parameter_coverage:
            phase_parts = []
            for phase in sorted(
                r.calibration_phase_parameter_coverage,
                key=lambda item: (
                    r.calibration_phase_order.get(item, 999),
                    item,
                ),
            ):
                params = ",".join(r.calibration_phase_parameter_coverage.get(phase) or [])
                count = r.calibration_phase_evaluation_counts.get(phase)
                suffix = "" if count is None else f" ({count} evals)"
                phase_parts.append(f"{phase}={params or 'none'}{suffix}")
            lines.append(
                "  - calibration phase coverage: "
                f"`{'; '.join(phase_parts)}`"
            )
        if r.calibration_failure_n_evaluations is not None:
            lines.append(f"  - calibration failure evaluations: `{r.calibration_failure_n_evaluations}`")
        if r.calibration_failure_best_abs_pbias is not None:
            volume_count = (
                "n/a"
                if r.calibration_failure_volume_gate_pass_count is None
                else str(r.calibration_failure_volume_gate_pass_count)
            )
            physical_count = (
                "n/a"
                if r.calibration_failure_physical_gate_pass_count is None
                else str(r.calibration_failure_physical_gate_pass_count)
            )
            process_count = (
                "n/a"
                if r.calibration_failure_process_gate_pass_count is None
                else str(r.calibration_failure_process_gate_pass_count)
            )
            lines.append(
                "  - calibration history summary: "
                f"best phase `{r.calibration_failure_best_phase or 'unknown'}`, "
                f"best |PBIAS| `{r.calibration_failure_best_abs_pbias:.3f}`, "
                f"volume-pass candidates `{volume_count}`, physical-pass candidates `{physical_count}`, "
                f"process-pass candidates `{process_count}`"
            )
        if r.calibration_failure_best_parameters:
            best_params = ", ".join(
                f"{name}={value:g}"
                for name, value in sorted(r.calibration_failure_best_parameters.items())
            )
            label = (
                "calibration best parameters"
                if r.calibration == "done"
                else "calibration best failed parameters"
            )
            lines.append(f"  - {label}: `{best_params}`")
        if r.calibration_failure_best_parameter_bound_hits:
            hits = ", ".join(
                f"{name}={hit.get('boundary')}:{hit.get('value')}"
                for name, hit in sorted(r.calibration_failure_best_parameter_bound_hits.items())
            )
            label = (
                "calibration best parameter bound hits"
                if r.calibration == "done"
                else "calibration best failed parameter bound hits"
            )
            lines.append(f"  - {label}: `{hits}`")
        if r.calibration_bound_interaction_screen_json:
            lines.append(
                "  - calibration bound-interaction screen json: "
                f"`{r.calibration_bound_interaction_screen_json}`"
            )
        if r.calibration_bound_interaction_best_metrics:
            params = ", ".join(
                f"{name}={value:g}"
                for name, value in sorted(r.calibration_bound_interaction_best_parameters.items())
            ) or "none"
            metrics = ", ".join(
                f"{name}={value:.6f}"
                for name, value in sorted(r.calibration_bound_interaction_best_metrics.items())
            )
            lines.append(
                "  - calibration bound-interaction best candidate: "
                f"`{r.calibration_bound_interaction_best_label or 'unknown'}`; "
                f"parameters `{params}`; metrics `{metrics}`"
            )
        if r.calibration_failure_skill_volume_near_miss:
            params = (
                "none"
                if not r.calibration_failure_near_miss_parameters
                else ", ".join(
                    f"{name}={value:g}"
                    for name, value in sorted(r.calibration_failure_near_miss_parameters.items())
                )
            )
            lines.append(
                "  - calibration near-miss candidate: "
                f"phase `{r.calibration_failure_near_miss_phase or 'unknown'}`, "
                f"KGE `{_fmt_optional(r.calibration_failure_near_miss_kge)}`, "
                f"NSE `{_fmt_optional(r.calibration_failure_near_miss_nse)}`, "
                f"PBIAS `{_fmt_optional(r.calibration_failure_near_miss_pbias)}`, "
                f"parameters `{params}`; diagnostic only, not final evidence"
            )
        if r.calibration_failure_skill_tradeoff_frontier:
            frontier_parts = []
            for label, item in sorted(r.calibration_failure_skill_tradeoff_frontier.items()):
                metrics = item.get("metrics") if isinstance(item, dict) else None
                phase = item.get("phase") if isinstance(item, dict) else None
                if isinstance(metrics, dict):
                    frontier_parts.append(
                        f"{label}:phase={phase or 'unknown'},"
                        f"KGE={_fmt_optional(_num(metrics.get('kge')))},"
                        f"NSE={_fmt_optional(_num(metrics.get('nse')))},"
                        f"PBIAS={_fmt_optional(_num(metrics.get('pbias')))}"
                    )
            if frontier_parts:
                lines.append(
                    "  - calibration skill/volume tradeoff frontier: "
                    f"`{'; '.join(frontier_parts)}`; diagnostic only, not final evidence"
                )
        if r.calibration_failure_physical_condition_code_counts:
            lines.append(
                "  - calibration candidate physical blockers: "
                f"`{json.dumps(r.calibration_failure_physical_condition_code_counts, sort_keys=True)}`"
            )
        if r.calibration_failure_process_condition_code_counts:
            lines.append(
                "  - calibration candidate process blockers: "
                f"`{json.dumps(r.calibration_failure_process_condition_code_counts, sort_keys=True)}`"
            )
        if r.calibration_failure_promotion_gate:
            lines.append(
                "  - calibration failure promotion gate: "
                f"`{json.dumps(r.calibration_failure_promotion_gate, sort_keys=True)}`"
            )
        if r.calibration_final_metrics_authority is not None:
            lines.append(
                "  - calibration final metrics authority: "
                f"`{r.calibration_final_metrics_authority}`"
            )
        if r.temporary_candidate_metrics_allowed_as_final is not None:
            lines.append(
                "  - temporary candidate metrics allowed as final: "
                f"`{r.temporary_candidate_metrics_allowed_as_final}`"
            )
        if r.calibration_precheck_sequence:
            lines.append(
                "  - calibration precheck: "
                f"sequence=`{r.calibration_precheck_sequence}`, "
                f"physical=`{r.calibration_precheck_physical_gates_status or 'unknown'}`, "
                f"routing=`{r.calibration_precheck_routing_flow_gates_status or 'unknown'}`, "
                f"block_reason=`{r.calibration_precheck_block_reason or 'none'}`"
            )
        if r.volume_bias_diagnostics_path:
            lines.append(f"  - volume-bias diagnostics: `{r.volume_bias_diagnostics_path}`")
        if r.weather_forcing_summary_path:
            precip = (
                r.weather_forcing_summary.get("precipitation")
                if isinstance(r.weather_forcing_summary, dict)
                else {}
            )
            observed = (
                r.weather_forcing_summary.get("observed_runoff")
                if isinstance(r.weather_forcing_summary, dict)
                else {}
            )
            if not isinstance(precip, dict):
                precip = {}
            if not isinstance(observed, dict):
                observed = {}
            lines.append(
                "  - weather forcing summary: "
                f"`{r.weather_forcing_summary_path}`; "
                f"stations=`{precip.get('station_count', 'n/a')}`, "
                f"mean_areal_precip_mm=`{_fmt_optional(_num(precip.get('mean_areal_total_precip_mm')))}`, "
                f"overlap_precip_mm=`{_fmt_optional(_num(observed.get('precip_overlap_total_mm')))}`, "
                f"qobs_to_overlap_precip=`{_fmt_optional(_num(observed.get('observed_runoff_to_overlap_precip_ratio')))}`, "
                f"qobs_precip_class=`{observed.get('runoff_precip_ratio_class', 'n/a')}`"
            )
        if r.volume_bias_diagnostic_flags:
            lines.append(f"  - volume-bias flags: `{', '.join(r.volume_bias_diagnostic_flags)}`")
        if r.high_runoff_demand_context.get("available") is True:
            lines.append(
                "  - high runoff-demand context: "
                f"qobs_to_precip=`{_fmt_optional(_num(r.high_runoff_demand_context.get('observed_runoff_to_overlap_precip_ratio')))}`, "
                f"swat_wateryld_to_precip=`{_fmt_optional(_num(r.high_runoff_demand_context.get('swat_net_wateryld_to_precip')))}`, "
                f"snowfall_to_precip=`{_fmt_optional(_num(r.high_runoff_demand_context.get('swat_snowfall_to_precip')))}`, "
                f"snowmelt_to_precip=`{_fmt_optional(_num(r.high_runoff_demand_context.get('swat_snowmelt_to_precip')))}`, "
                f"aquifer_flow_mean_mm=`{_fmt_optional(_num(r.high_runoff_demand_context.get('aquifer_flow_mean_mm')))}`, "
                f"aquifer_recharge_mean_mm=`{_fmt_optional(_num(r.high_runoff_demand_context.get('aquifer_recharge_mean_mm')))}`, "
                f"area_ratio=`{_fmt_optional(_num(r.high_runoff_demand_context.get('observed_area_to_all_terminal_area_ratio')))}`, "
                f"probe=`{r.high_runoff_demand_context.get('recommended_probe', 'n/a')}`"
            )
            interpretation_flags = r.high_runoff_demand_context.get("interpretation_flags")
            if isinstance(interpretation_flags, list):
                flag_names = [
                    str(flag.get("code"))
                    for flag in interpretation_flags
                    if isinstance(flag, dict) and flag.get("code")
                ]
                if flag_names:
                    lines.append(f"  - high runoff-demand flags: `{', '.join(flag_names)}`")
            explanations = r.high_runoff_demand_context.get("candidate_explanations")
            if isinstance(explanations, list):
                explanation_bits = [
                    f"{item.get('hypothesis')}={item.get('status')}"
                    for item in explanations
                    if isinstance(item, dict) and item.get("hypothesis") and item.get("status")
                ]
                if explanation_bits:
                    lines.append(
                        "  - high runoff-demand candidate explanations: "
                        f"`{', '.join(str(bit) for bit in explanation_bits)}`"
                    )
        if r.terminal_hydrograph_scope.get("available") is True:
            selected_metrics = r.terminal_hydrograph_scope.get("selected_terminal")
            all_metrics = r.terminal_hydrograph_scope.get("all_terminal")
            if isinstance(selected_metrics, dict) and isinstance(all_metrics, dict):
                selected_pbias = _fmt_optional(_num(selected_metrics.get("pbias_pct")))
                all_pbias = _fmt_optional(_num(all_metrics.get("pbias_pct")))
                selected_nse = _fmt_optional(_num(selected_metrics.get("nse")))
                all_nse = _fmt_optional(_num(all_metrics.get("nse")))
                lines.append(
                    "  - terminal hydrograph scope: "
                    f"selected PBIAS/NSE `{selected_pbias}/{selected_nse}`; "
                    f"all-terminal PBIAS/NSE `{all_pbias}/{all_nse}`; "
                    f"diagnostic_only=`{r.terminal_hydrograph_scope.get('diagnostic_only')}`"
                )
            if r.terminal_hydrograph_scope_class:
                lines.append(
                    "  - terminal hydrograph scope class: "
                    f"`{r.terminal_hydrograph_scope_class}`; flags "
                    f"`{', '.join(r.terminal_hydrograph_scope_flags) or 'none'}`; focus "
                    f"`{', '.join(r.terminal_hydrograph_scope_recommended_focus) or 'none'}`"
                )
            if r.terminal_scope_resolution_plan.get("available") is True:
                lines.append(
                    "  - terminal scope resolution plan: "
                    f"`{r.terminal_scope_resolution_plan.get('decision_type')}`; next "
                    f"`{r.terminal_scope_resolution_plan.get('next_experiment')}`; "
                    "fresh_locked_rerun_required="
                    f"`{r.terminal_scope_resolution_plan.get('fresh_locked_rerun_required')}`"
                )
            if r.post_aggregation_process_context.get("available") is True:
                domains = r.post_aggregation_process_context.get("likely_process_domains")
                focus = r.post_aggregation_process_context.get("recommended_focus")
                explanations = r.post_aggregation_process_context.get("candidate_explanations")
                domain_text = ", ".join(str(item) for item in domains) if isinstance(domains, list) else "none"
                focus_text = ", ".join(str(item) for item in focus) if isinstance(focus, list) else "none"
                explanation_text = (
                    ", ".join(
                        str(item.get("domain"))
                        for item in explanations
                        if isinstance(item, dict) and item.get("domain")
                    )
                    if isinstance(explanations, list)
                    else "none"
                )
                lines.append(
                    "  - post-aggregation process context: "
                    f"status `{r.post_aggregation_process_context.get('status')}`; "
                    f"domains `{domain_text or 'none'}`; focus `{focus_text or 'none'}`; "
                    f"candidate explanations `{explanation_text or 'none'}`; "
                    "claim_authority="
                    f"`{r.post_aggregation_process_context.get('claim_authority')}`"
                )
        if r.terminal_scope_blocker:
            lines.append(f"  - terminal-scope blocker: `{r.terminal_scope_blocker}`")
        if r.volume_bias_next_actions:
            lines.append(f"  - volume-bias next actions: {'; '.join(r.volume_bias_next_actions)}")
        if r.volume_source_backed_alternatives:
            options = [
                str(alt.get("option"))
                for alt in r.volume_source_backed_alternatives
                if isinstance(alt, dict) and alt.get("option")
            ]
            if options:
                lines.append(f"  - volume source-backed alternatives: `{', '.join(options)}`")
        if r.volume_recommended_probe_order:
            probes = [
                str(probe.get("diagnostic"))
                for probe in r.volume_recommended_probe_order
                if isinstance(probe, dict) and probe.get("diagnostic")
            ]
            if probes:
                lines.append(f"  - volume recommended probe order: `{', '.join(probes)}`")
        if r.et_partition_diagnostics_path:
            lines.append(f"  - ET partition diagnostics: `{r.et_partition_diagnostics_path}`")
        if r.et_partition_gate_context:
            lines.append(f"  - ET partition gate context: `{r.et_partition_gate_context}`")
        if r.et_partition_diagnostic_flags:
            lines.append(f"  - ET partition flags: `{', '.join(r.et_partition_diagnostic_flags)}`")
        if r.et_partition_next_actions:
            lines.append(f"  - ET partition next actions: {'; '.join(r.et_partition_next_actions)}")
        if r.et_source_backed_alternatives:
            options = [
                str(alt.get("option"))
                for alt in r.et_source_backed_alternatives
                if isinstance(alt, dict) and alt.get("option")
            ]
            if options:
                lines.append(f"  - ET source-backed alternatives: `{', '.join(options)}`")
        if r.et_recommended_probe_order:
            probes = []
            for probe in r.et_recommended_probe_order:
                params = probe.get("parameters") if isinstance(probe, dict) else None
                if isinstance(params, list) and params:
                    probes.append("+".join(str(p) for p in params))
            if probes:
                lines.append(f"  - ET recommended probe order: `{', '.join(probes)}`")
        if r.mass_balance_diagnostics_path:
            lines.append(f"  - mass-balance diagnostics: `{r.mass_balance_diagnostics_path}`")
        if r.mass_balance_gate_context:
            lines.append(f"  - mass-balance gate context: `{r.mass_balance_gate_context}`")
        if r.mass_balance_diagnostic_flags:
            lines.append(f"  - mass-balance flags: `{', '.join(r.mass_balance_diagnostic_flags)}`")
        if r.mass_balance_next_actions:
            lines.append(f"  - mass-balance next actions: {'; '.join(r.mass_balance_next_actions)}")
        if r.mass_balance_source_backed_alternatives:
            options = [
                str(alt.get("option"))
                for alt in r.mass_balance_source_backed_alternatives
                if isinstance(alt, dict) and alt.get("option")
            ]
            if options:
                lines.append(f"  - mass-balance source-backed alternatives: `{', '.join(options)}`")
        if r.mass_balance_recommended_probe_order:
            probes = [
                str(probe.get("diagnostic"))
                for probe in r.mass_balance_recommended_probe_order
                if isinstance(probe, dict) and probe.get("diagnostic")
            ]
            if probes:
                lines.append(f"  - mass-balance recommended probe order: `{', '.join(probes)}`")
        if r.skill_diagnostics_json:
            lines.append(f"  - skill diagnostics json: `{r.skill_diagnostics_json}`")
        if r.skill_diagnostics_md:
            lines.append(f"  - skill diagnostics report: `{r.skill_diagnostics_md}`")
        if r.skill_diagnostic_flags:
            lines.append(f"  - skill diagnostic flags: `{', '.join(r.skill_diagnostic_flags)}`")
        if r.skill_limitation_class:
            focus = ", ".join(r.skill_limitation_recommended_focus) or "n/a"
            lines.append(
                "  - skill limitation class: "
                f"`{r.skill_limitation_class}`; dominant KGE component "
                f"`{r.skill_limitation_dominant_kge_component or 'n/a'}`; focus `{focus}`"
            )
        if r.skill_next_actions:
            lines.append(
                "  - skill next actions: "
                f"{'; '.join(_render_skill_next_actions(r.skill_next_actions, r.superseded_unsupported_skill_parameters))}"
            )
        if r.skill_source_backed_alternatives:
            options = [
                str(alt.get("option"))
                for alt in r.skill_source_backed_alternatives
                if isinstance(alt, dict) and alt.get("option")
            ]
            if options:
                lines.append(f"  - skill source-backed alternatives: `{', '.join(options)}`")
        if r.skill_recommended_probe_order:
            probes = [
                str(probe.get("diagnostic"))
                for probe in r.skill_recommended_probe_order
                if isinstance(probe, dict) and probe.get("diagnostic")
            ]
            if probes:
                lines.append(f"  - skill recommended probe order: `{', '.join(probes)}`")
        if r.skill_probe_gap_parameters:
            lines.append(
                "  - skill probe gap parameters: "
                f"`{', '.join(r.skill_probe_gap_parameters)}`"
            )
        if r.skill_screened_dead_parameters:
            lines.append(
                "  - skill screened-dead suggested parameters: "
                f"`{', '.join(r.skill_screened_dead_parameters)}`"
            )
        if r.skill_unscreened_suggested_parameters:
            lines.append(
                "  - skill unscreened suggested parameters: "
                f"`{', '.join(r.skill_unscreened_suggested_parameters)}`"
            )
        if r.skill_channel_routing_screen_json:
            lines.append(f"  - skill channel-routing screen json: `{r.skill_channel_routing_screen_json}`")
        if r.skill_channel_routing_activity_classes:
            classes = ", ".join(
                f"{parameter}={activity}"
                for parameter, activity in sorted(r.skill_channel_routing_activity_classes.items())
            )
            lines.append(f"  - skill channel-routing activity: `{classes}`")
        if r.skill_channel_routing_effect_sizes:
            effects = ", ".join(
                f"{parameter}={effect:.6f}"
                for parameter, effect in sorted(r.skill_channel_routing_effect_sizes.items())
            )
            lines.append(f"  - skill channel-routing effect sizes: `{effects}`")
        if r.skill_channel_routing_best_bounds:
            bounds = ", ".join(
                f"{parameter}={context.get('bound')}:{context.get('value')}"
                for parameter, context in sorted(r.skill_channel_routing_best_bounds.items())
            )
            lines.append(f"  - skill channel-routing best bounds: `{bounds}`")
        if r.skill_channel_routing_calibration_verification_summary:
            lines.append(
                "  - skill channel-routing verified refinement: "
                f"`{r.skill_channel_routing_calibration_verification_summary}`"
            )
        if r.skill_channel_routing_calibration_parameters:
            params = ", ".join(
                f"{parameter}={value:g}"
                for parameter, value in sorted(r.skill_channel_routing_calibration_parameters.items())
            )
            lines.append(f"  - skill channel-routing verified parameters: `{params}`")
        if r.skill_channel_routing_calibration_metrics:
            metrics = ", ".join(
                f"{metric}={value:.6f}"
                for metric, value in sorted(r.skill_channel_routing_calibration_metrics.items())
            )
            lines.append(f"  - skill channel-routing verified metrics: `{metrics}`")
        if r.skill_channel_routing_calibration_deltas:
            deltas = ", ".join(
                f"{metric}={value:.6f}"
                for metric, value in sorted(r.skill_channel_routing_calibration_deltas.items())
            )
            lines.append(f"  - skill channel-routing verified deltas: `{deltas}`")
        if r.unsupported_skill_parameters:
            lines.append(f"  - unsupported skill parameters: `{', '.join(r.unsupported_skill_parameters)}`")
        if r.superseded_unsupported_skill_parameters:
            lines.append(
                "  - superseded unsupported skill parameters: "
                f"`{', '.join(r.superseded_unsupported_skill_parameters)}`"
            )
        if r.blocked_skill_parameters:
            lines.append(f"  - blocked skill parameters: `{', '.join(r.blocked_skill_parameters)}`")
        for name, path in sorted(r.build_diagnostic_artifacts.items()):
            lines.append(f"  - build `{name}`: `{path}`")
        if r.soil_next_actions:
            lines.append(f"  - soil next actions: {'; '.join(r.soil_next_actions)}")
        if r.soil_source_backed_alternatives:
            options = [
                str(alt.get("option"))
                for alt in r.soil_source_backed_alternatives
                if isinstance(alt, dict) and alt.get("option")
            ]
            if options:
                lines.append(f"  - soil source-backed alternatives: `{', '.join(options)}`")
        if r.soil_recommended_probe_order:
            probes = [
                str(probe.get("diagnostic"))
                for probe in r.soil_recommended_probe_order
                if isinstance(probe, dict) and probe.get("diagnostic")
            ]
            if probes:
                lines.append(f"  - soil recommended probe order: `{', '.join(probes)}`")
    lines += [
        "",
        "## Action Plan",
        "",
    ]
    for r in rows:
        if r.tier == "research_grade":
            continue
        actions = _row_action_items(r)
        lines.append(f"- `{r.basin}` primary blocker `{r.primary_blocker or _primary_blocker(r)}`")
        if actions:
            for action in actions:
                lines.append(f"  - {action}")
        else:
            lines.append("  - No diagnostic action item was available in the current evidence bundle.")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _num(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _fmt_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _safe_int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _int_count_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for key, count in value.items():
        parsed = _safe_int_or_none(count)
        if parsed is None:
            continue
        out[str(key)] = parsed
    return out


def _str_list_dict(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, items in value.items():
        if not isinstance(items, list):
            continue
        clean = sorted({str(item).strip() for item in items if str(item).strip()})
        if clean:
            out[str(key)] = clean
    return out


def _float_dict(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, item in value.items():
        parsed = _num(item)
        if parsed is None:
            continue
        out[str(key)] = parsed
    return out


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _merge_ranked_items(
    preferred: list[dict[str, object]],
    existing: list[dict[str, object]],
    *,
    key: str,
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in [*preferred, *existing]:
        name = item.get(key)
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        copied = dict(item)
        copied["rank"] = len(merged) + 1
        merged.append(copied)
    return merged


def _primary_blocker(row: Row) -> str:
    if row.tier == "research_grade" and not row.gates_failed and str(row.blocker) in {"none", ""}:
        return "none"
    calibration_regression = _calibration_regression_blocker(row)
    volume_issue = row.volume_bias_primary_issue
    if volume_issue == "simulated_volume_deficit" and row.terminal_scope_blocker:
        volume_issue = row.terminal_scope_blocker
    volume_issue = (
        volume_issue
        if "VOLUME_BIAS" in set(row.physical_condition_codes)
        else None
    )
    for value in (
        volume_issue,
        calibration_regression,
        row.physical_dominant_blocker,
        row.terminal_scope_blocker,
        row.terminal_failure_class if row.routing_flow_gates in {"failed", "warning"} else None,
        row.routing_flow_closure_status,
        row.blocker if row.blocker == "soil_realism_gate_failed" else None,
        "soil_fidelity" if "soil_fidelity" in row.gates_failed else None,
        row.blocker,
    ):
        if value and str(value) not in {"none", "null", "unknown"}:
            return str(value)
    if row.gates_failed:
        return row.gates_failed[0]
    return "none"


def _calibration_regression_blocker(row: Row) -> str | None:
    if row.calibration not in {"attempted", "done", "verified"}:
        return None
    deltas = [row.delta_kge, row.delta_nse]
    if all(delta is not None and delta <= 0.0 for delta in deltas):
        return "calibration_regressed"
    return None


def _soil_summary(row: Row) -> str:
    parts: list[str] = []
    if row.soil_mode:
        parts.append(row.soil_mode)
    if row.soil_provenance_mode:
        parts.append(f"provenance={row.soil_provenance_mode}")
    if row.pct_fallback_soils is not None:
        parts.append(f"fallback={row.pct_fallback_soils:.1%}")
    if row.soil_overlay_gap_fraction is not None:
        parts.append(f"soil_gap={row.soil_overlay_gap_fraction:.1%}")
    return "; ".join(parts) if parts else "unknown"


def _row_action_items(row: Row) -> list[str]:
    actions: list[str] = []
    if row.calibration in {"attempted", "blocked_by_volume_gate", "blocked_by_promotion_gate"}:
        if row.calibration_failure_phase or row.calibration_failure_message:
            phase = row.calibration_failure_phase or "unknown"
            message = row.calibration_failure_message or "no failure message recorded"
            authority = row.calibration_final_metrics_authority or "unknown"
            candidate_guard = row.temporary_candidate_metrics_allowed_as_final
            actions.append(
                "Calibration search: "
                f"phase={phase}; reason={message}; final_metrics_authority={authority}; "
                f"temporary_candidate_metrics_allowed_as_final={candidate_guard}."
            )
        if row.calibration_failure_skill_volume_near_miss:
            params = (
                "none"
                if not row.calibration_failure_near_miss_parameters
                else ", ".join(
                    f"{name}={value:g}"
                    for name, value in sorted(row.calibration_failure_near_miss_parameters.items())
                )
            )
            kge = "n/a" if row.calibration_failure_near_miss_kge is None else f"{row.calibration_failure_near_miss_kge:.3f}"
            nse = "n/a" if row.calibration_failure_near_miss_nse is None else f"{row.calibration_failure_near_miss_nse:.3f}"
            pbias = (
                "n/a"
                if row.calibration_failure_near_miss_pbias is None
                else f"{row.calibration_failure_near_miss_pbias:.1f}%"
            )
            actions.append(
                "Calibration near miss: candidate met KGE/NSE skill thresholds but failed the hard volume gate "
                f"(KGE={kge}, NSE={nse}, PBIAS={pbias}, phase={row.calibration_failure_near_miss_phase or 'unknown'}, "
                f"parameters={params}); keep as diagnostic-only evidence."
            )
        elif row.calibration_failure_best_parameters:
            params = ", ".join(
                f"{name}={value:g}"
                for name, value in sorted(row.calibration_failure_best_parameters.items())
            )
            actions.append(
                "Calibration failed-candidate context: "
                f"best failed parameters={params}; use as diagnostic evidence only."
            )
        if row.calibration_failure_skill_tradeoff_frontier:
            parts = []
            for label, item in sorted(row.calibration_failure_skill_tradeoff_frontier.items()):
                metrics = item.get("metrics") if isinstance(item, dict) else None
                if not isinstance(metrics, dict):
                    continue
                kge = "n/a" if metrics.get("kge") is None else f"{float(metrics['kge']):.3f}"
                nse = "n/a" if metrics.get("nse") is None else f"{float(metrics['nse']):.3f}"
                pbias = "n/a" if metrics.get("pbias") is None else f"{float(metrics['pbias']):.1f}%"
                parts.append(f"{label} KGE={kge}, NSE={nse}, PBIAS={pbias}")
            if parts:
                actions.append(
                    "Calibration tradeoff frontier: "
                    f"{'; '.join(parts)}; diagnostic-only evidence from the candidate history."
                )
        if row.calibration_failure_best_parameter_bound_hits:
            hits = ", ".join(
                f"{name}={hit.get('boundary')}"
                for name, hit in sorted(row.calibration_failure_best_parameter_bound_hits.items())
            )
            actions.append(
                "Calibration failed-candidate bounds: "
                f"best failed candidate has governed bound hits={hits}."
            )
        if row.calibration_bound_interaction_best_metrics:
            metrics = row.calibration_bound_interaction_best_metrics
            kge = "n/a" if "kge" not in metrics else f"{metrics['kge']:.3f}"
            nse = "n/a" if "nse" not in metrics else f"{metrics['nse']:.3f}"
            pbias = "n/a" if "pbias" not in metrics else f"{metrics['pbias']:.1f}%"
            actions.append(
                "Calibration bound-interaction screen: "
                f"best={row.calibration_bound_interaction_best_label or 'unknown'}; "
                f"KGE={kge}, NSE={nse}, PBIAS={pbias}; "
                f"claim_status={row.calibration_bound_interaction_claim_status or 'unknown'}."
            )
    if row.routing_flow_diagnostic_flags:
        actions.append(
            "Routing closure: "
            f"{row.routing_flow_closure_status or row.routing_flow_gates}; "
            f"flags={', '.join(row.routing_flow_diagnostic_flags)}."
        )
    for alt in row.routing_source_backed_alternatives[:3]:
        option = alt.get("option")
        impact = alt.get("claim_impact")
        artifacts = alt.get("required_artifacts")
        if not option:
            continue
        artifact_text = ", ".join(str(a) for a in artifacts) if isinstance(artifacts, list) and artifacts else "n/a"
        actions.append(f"Routing source alternative: {option}; artifacts={artifact_text}; impact={impact}.")
    if row.terminal_failure_class:
        actions.append(f"Terminal inventory: failure_class={row.terminal_failure_class}.")
    if row.volume_bias_next_actions:
        for alt in row.volume_source_backed_alternatives[:3]:
            option = alt.get("option")
            impact = alt.get("claim_impact")
            params = alt.get("parameters")
            if not option:
                continue
            param_text = ", ".join(str(p) for p in params) if isinstance(params, list) and params else "no parameters"
            actions.append(f"Volume source alternative: {option} ({param_text}); impact={impact}.")
        actions.extend(f"Volume bias: {action}" for action in row.volume_bias_next_actions[:3])
    if row.skill_next_actions:
        for alt in row.skill_source_backed_alternatives[:3]:
            option = alt.get("option")
            impact = alt.get("claim_impact")
            params = alt.get("parameters")
            blocked = alt.get("blocked_parameters")
            if not option:
                continue
            param_text = ", ".join(str(p) for p in params) if isinstance(params, list) and params else "no parameters"
            blocked_text = (
                f"; blocked={', '.join(str(p) for p in blocked)}"
                if isinstance(blocked, list) and blocked
                else ""
            )
            actions.append(f"Skill source alternative: {option} ({param_text}{blocked_text}); impact={impact}.")
        actions.extend(
            f"Skill diagnostics: {action}"
            for action in _render_skill_next_actions(
                row.skill_next_actions[:3],
                row.superseded_unsupported_skill_parameters,
            )
        )
    if row.skill_probe_gap_parameters:
        actions.append(
            "Skill screen coverage: governed suggested controls not retained by basin-specific screen="
            f"{', '.join(row.skill_probe_gap_parameters)}."
        )
    if row.skill_screened_dead_parameters:
        actions.append(
            "Skill sensitivity triage: do not keep retesting screened-dead suggested controls without new "
            f"process evidence ({', '.join(row.skill_screened_dead_parameters)})."
        )
    if row.skill_unscreened_suggested_parameters:
        actions.append(
            "Skill sensitivity triage: run locked basin-specific screens for unscreened suggested controls="
            f"{', '.join(row.skill_unscreened_suggested_parameters)}."
        )
    if row.skill_channel_routing_activity_classes:
        activity_text = ", ".join(
            f"{parameter}={activity}"
            for parameter, activity in sorted(row.skill_channel_routing_activity_classes.items())
        )
        effect_text = ", ".join(
            f"{parameter}={effect:.6f}"
            for parameter, effect in sorted(row.skill_channel_routing_effect_sizes.items())
        )
        actions.append(
            "Skill channel-routing locked screen: "
            f"{activity_text}; effect_size={effect_text or 'n/a'}."
        )
    if row.skill_channel_routing_best_bounds:
        bound_text = ", ".join(
            f"{parameter}={context.get('bound')}:{context.get('value')}"
            for parameter, context in sorted(row.skill_channel_routing_best_bounds.items())
        )
        actions.append(f"Skill channel-routing direction: best locked-screen bounds={bound_text}.")
    if row.skill_channel_routing_calibration_verification_summary:
        metric_text = ", ".join(
            f"{metric}={value:.6f}"
            for metric, value in sorted(row.skill_channel_routing_calibration_metrics.items())
        )
        delta_text = ", ".join(
            f"{metric}={value:.6f}"
            for metric, value in sorted(row.skill_channel_routing_calibration_deltas.items())
        )
        actions.append(
            "Skill channel-routing refinement: verified locked rerun retained "
            f"({metric_text or 'no metrics'}; delta={delta_text or 'n/a'}; "
            f"improved={row.skill_channel_routing_calibration_improved})."
        )
    if row.unsupported_skill_parameters:
        actions.append(
            "Parameter governance: unsupported skill controls="
            f"{', '.join(row.unsupported_skill_parameters)}."
        )
    if row.superseded_unsupported_skill_parameters:
        actions.append(
            "Parameter governance: historical unsupported controls now have bridge support="
            f"{', '.join(row.superseded_unsupported_skill_parameters)}; refresh calibration evidence before treating "
            "older diagnostics as current blockers."
        )
    if row.blocked_skill_parameters:
        actions.append(
            "Parameter governance: blocked skill controls="
            f"{', '.join(row.blocked_skill_parameters)}."
        )
    if row.primary_blocker == "calibration_regressed":
        dkge = "n/a" if row.delta_kge is None else f"{row.delta_kge:+.3f}"
        dnse = "n/a" if row.delta_nse is None else f"{row.delta_nse:+.3f}"
        actions.append(
            "Calibration verification: locked calibrated rerun regressed against baseline "
            f"(delta_kge={dkge}, delta_nse={dnse})."
        )
    if row.primary_blocker == "soil_realism_gate_failed" or "soil_fidelity" in row.gates_failed:
        actions.append(f"Soil fidelity: provenance={_soil_summary(row)}.")
        for action in row.soil_next_actions[:3]:
            actions.append(f"Soil next action: {action}")
        for alt in row.soil_source_backed_alternatives[:3]:
            option = alt.get("option")
            impact = alt.get("claim_impact")
            artifacts = alt.get("required_artifacts")
            if not option:
                continue
            artifact_text = ", ".join(str(a) for a in artifacts) if isinstance(artifacts, list) and artifacts else "n/a"
            actions.append(f"Soil source alternative: {option}; artifacts={artifact_text}; impact={impact}.")
        if row.build_diagnostic_artifacts:
            keys = ", ".join(sorted(row.build_diagnostic_artifacts))
            actions.append(f"Soil fidelity: review retained build diagnostics ({keys}) before research-grade claims.")
        elif row.build_message:
            actions.append(f"Soil fidelity: {row.build_message}")
    if row.primary_blocker == "ET_DOMINATED" or "ET_DOMINATED" in row.physical_condition_codes:
        for alt in row.et_source_backed_alternatives[:3]:
            option = alt.get("option")
            impact = alt.get("claim_impact")
            params = alt.get("parameters")
            if not option:
                continue
            param_text = ", ".join(str(p) for p in params) if isinstance(params, list) and params else "no parameters"
            actions.append(f"ET source alternative: {option} ({param_text}); impact={impact}.")
        if row.et_partition_next_actions:
            actions.extend(f"ET partition: {action}" for action in row.et_partition_next_actions[:3])
        else:
            actions.append(
                "ET partition: audit PET/ET controls, soil water, vegetation/management, and forcing before calibration."
            )
    return _dedupe(actions)


_ASSERTION_TYPE_ORDER = ("readiness", "provenance", "comparison", "metric")


def _claim_tier_matrix_summary(rows: list[Row]) -> dict[str, object]:
    """Aggregate per-basin claim_tier_matrix into a suite-level summary."""
    all_types: set[str] = set()
    for r in rows:
        all_types.update(r.claim_tier_matrix)
    claim_types = sorted(
        all_types,
        key=lambda t: list(_ASSERTION_TYPE_ORDER).index(t) if t in _ASSERTION_TYPE_ORDER else 99,
    )
    counts: dict[str, dict[str, int]] = {ct: {} for ct in claim_types}
    for r in rows:
        for ct in claim_types:
            tier = r.claim_tier_matrix.get(ct, "blocked")
            counts[ct][tier] = counts[ct].get(tier, 0) + 1
    return {
        "claim_types": claim_types,
        "counts": counts,
        "research_grade_claims": {
            ct: counts[ct].get("research_grade", 0) for ct in claim_types
        },
    }


def _non_research_blocker_classification(rows: list[Row]) -> dict[str, object]:
    domain_counts = {
        "engineering": 0,
        "diagnostics": 0,
        "calibration": 0,
        "provenance": 0,
        "parameter_support": 0,
        "science": 0,
    }
    blocker_to_domain: dict[str, str] = {}
    for row in rows:
        if row.tier == "research_grade":
            continue
        blocker = row.primary_blocker or _primary_blocker(row)
        domain = _blocker_domain(blocker)
        if domain is None:
            continue
        domain_counts[domain] += 1
        blocker_to_domain[str(blocker)] = domain
    unclassified = sorted(
        {
            str(row.primary_blocker or _primary_blocker(row))
            for row in rows
            if row.tier != "research_grade"
            and _blocker_domain(row.primary_blocker or _primary_blocker(row)) is None
        }
    )
    return {
        "domain_counts": domain_counts,
        "blocker_to_domain": dict(sorted(blocker_to_domain.items())),
        "unclassified_blockers": unclassified,
    }


def _target_hypothesis_evaluation(
    rows: list[Row],
    blocker_classification: dict[str, object],
    *,
    target_count: int = 7,
) -> dict[str, object]:
    research_grade_count = sum(1 for row in rows if row.tier == "research_grade")
    domain_counts = blocker_classification.get("domain_counts")
    if not isinstance(domain_counts, dict):
        domain_counts = {}
    improvement_domains = [
        domain
        for domain in ("engineering", "diagnostics", "calibration", "provenance", "parameter_support")
        if int(domain_counts.get(domain, 0) or 0) > 0
    ]
    scientific_blockers = int(domain_counts.get("science", 0) or 0)
    unclassified = blocker_classification.get("unclassified_blockers")
    if not isinstance(unclassified, list):
        unclassified = []
    status = (
        "met_without_gate_weakening"
        if research_grade_count >= target_count
        else "not_supported_by_current_evidence"
    )
    return {
        "target_research_grade_count": target_count,
        "observed_research_grade_count": research_grade_count,
        "status": status,
        "gate_weakening_permitted": False,
        "metrics_alone_grant_research_grade": False,
        "unclassified_blockers": unclassified,
        "blocker_domain_counts": dict(domain_counts),
        "pipeline_improvement_required_domains": improvement_domains,
        "science_blocker_count": scientific_blockers,
        "interpretation": (
            "Current evidence does not support the >=7 research-grade target; "
            "retain exploratory tiers and improve only blocker domains that are "
            "engineering, diagnostics, calibration, provenance, or parameter-support gaps."
            if research_grade_count < target_count
            else "Current evidence supports the target under existing gates."
        ),
    }


def _science_blocker_summary(
    rows: list[Row],
    blocker_classification: dict[str, object],
) -> dict[str, object]:
    science_rows = [
        row
        for row in rows
        if row.tier != "research_grade"
        and _blocker_domain(row.primary_blocker or _primary_blocker(row)) == "science"
    ]
    blocker_counts: dict[str, int] = {}
    for row in science_rows:
        blocker = str(row.primary_blocker or _primary_blocker(row))
        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
    items: list[dict[str, object]] = []
    for blocker in sorted(blocker_counts):
        blocker_rows = [
            row
            for row in science_rows
            if str(row.primary_blocker or _primary_blocker(row)) == blocker
        ]
        evidence_fields: set[str] = set()
        basin_items: list[dict[str, object]] = []
        for row in blocker_rows:
            basin_item = _science_blocker_basin_item(row, blocker)
            basin_items.append(basin_item)
            evidence_fields.update(str(field) for field in basin_item.get("source_evidence_fields", []))
        items.append(
            {
                "primary_blocker": blocker,
                "basin_count": len(blocker_rows),
                "basins": sorted(row.basin for row in blocker_rows),
                "source_evidence_fields": sorted(evidence_fields),
                "basin_items": basin_items,
                "claim_authority": False,
                "pipeline_improvement_domain": False,
                "gate_weakening_permitted": False,
                "claim_impact": (
                    "science_blocker_documents_why_target_is_not_supported_without_gate_weakening"
                ),
            }
        )
    return {
        "version": 1,
        "status": "active_science_blockers" if science_rows else "no_science_blockers",
        "generated_from": "non_research_blocker_classification",
        "science_blocker_count": len(science_rows),
        "primary_blocker_counts": dict(sorted(blocker_counts.items())),
        "domain_count": int(
            (blocker_classification.get("domain_counts") or {}).get("science", 0)
        )
        if isinstance(blocker_classification.get("domain_counts"), dict)
        else len(science_rows),
        "gate_weakening_permitted": False,
        "metrics_alone_grant_research_grade": False,
        "items": items,
    }


def _science_blocker_basin_item(row: Row, blocker: str) -> dict[str, object]:
    base = {
        "basin": row.basin,
        "primary_blocker": blocker,
        "gates_failed": row.gates_failed,
        "physical_condition_codes": row.physical_condition_codes,
        "physical_dominant_blocker": row.physical_dominant_blocker,
        "blocked_claim_names": row.blocked_claim_names,
        "claim_authority": False,
    }
    if blocker in {"BELOW_RESEARCH_SKILL", "NEGATIVE_SKILL"}:
        first_probe = row.skill_recommended_probe_order[0] if row.skill_recommended_probe_order else {}
        base.update(
            {
                "evidence_type": "skill_limitation",
                "classification": row.skill_limitation_class,
                "flags": row.skill_limitation_flags,
                "dominant_kge_component": row.skill_limitation_dominant_kge_component,
                "recommended_focus": row.skill_limitation_recommended_focus,
                "claim_impact": row.skill_limitation_claim_impact,
                "diagnostics_path": row.skill_diagnostics_json,
                "first_probe": first_probe.get("diagnostic") if isinstance(first_probe, dict) else None,
                "source_evidence_fields": [
                    "skill_diagnostics",
                    "skill_limitation_class",
                    "skill_recommended_probe_order",
                    "physical_condition_codes",
                    "blocked_claim_names",
                ],
            }
        )
    elif blocker == "MASS_IMBALANCE":
        first_probe = row.mass_balance_recommended_probe_order[0] if row.mass_balance_recommended_probe_order else {}
        base.update(
            {
                "evidence_type": "mass_balance_diagnostics",
                "classification": row.mass_balance_gate_context,
                "flags": row.mass_balance_diagnostic_flags,
                "recommended_focus": row.mass_balance_next_actions,
                "claim_impact": "research_grade_blocked_until_mass_closure_is_explained",
                "diagnostics_path": row.mass_balance_diagnostics_path,
                "first_probe": first_probe.get("diagnostic") if isinstance(first_probe, dict) else None,
                "source_evidence_fields": [
                    "mass_balance_diagnostics",
                    "mass_balance_recommended_probe_order",
                    "physical_condition_codes",
                    "blocked_claim_names",
                ],
            }
        )
    else:
        base.update(
            {
                "evidence_type": "science_blocker",
                "classification": blocker,
                "flags": [],
                "recommended_focus": row.blocker_action_items,
                "claim_impact": "research_grade_blocked_by_current_science_evidence",
                "diagnostics_path": None,
                "first_probe": None,
                "source_evidence_fields": ["physical_condition_codes", "blocked_claim_names"],
            }
        )
    return base


_PIPELINE_DOMAIN_NEXT_EXPERIMENTS = {
    "engineering": "repair package build/topology mechanics before any calibration rerun",
    "diagnostics": "run source-backed process, forcing, routing, or outlet-scope diagnostics before new calibration",
    "calibration": "repair locked calibration behavior and rerun clean promoted verification",
    "provenance": "resolve outlet, soil, or authority provenance and rerun the canonical locked workflow",
    "parameter_support": "add governed parameter support, screen it basin-specifically, and verify locked effects",
}


def _pipeline_improvement_plan(
    rows: list[Row],
    target_hypothesis: dict[str, object],
) -> dict[str, object]:
    domains = target_hypothesis.get("pipeline_improvement_required_domains")
    if not isinstance(domains, list):
        domains = []
    plan_items: list[dict[str, object]] = []
    for rank, domain in enumerate(domains, start=1):
        if not isinstance(domain, str):
            continue
        domain_rows = sorted(
            (
                row
                for row in rows
                if row.tier != "research_grade" and row.blocker_domain == domain
            ),
            key=lambda row: row.basin,
        )
        if not domain_rows:
            continue
        blocker_counts: dict[str, int] = {}
        evidence_fields: set[str] = set()
        representative_actions: list[str] = []
        for row in domain_rows:
            blocker = row.primary_blocker or _primary_blocker(row)
            blocker_counts[str(blocker)] = blocker_counts.get(str(blocker), 0) + 1
            representative_actions.extend(row.blocker_action_items)
            evidence_fields.update(_row_improvement_evidence_fields(row, domain))
        basin_items = [_pipeline_improvement_basin_item(row, domain) for row in domain_rows]
        plan_items.append(
            {
                "rank": rank,
                "domain": domain,
                "basin_count": len(domain_rows),
                "basins": sorted(row.basin for row in domain_rows),
                "primary_blocker_counts": dict(sorted(blocker_counts.items())),
                "next_experiment": _PIPELINE_DOMAIN_NEXT_EXPERIMENTS.get(
                    domain,
                    "classify blocker before rerun",
                ),
                "representative_actions": _dedupe(representative_actions)[:8],
                "source_evidence_fields": sorted(evidence_fields),
                "basin_items": basin_items,
                "required_before_claim": [
                    "select a package-owned diagnostic or provenance experiment",
                    "preserve diagnostic metrics as non-authoritative evidence",
                    "rerun a fresh locked TxtInOut after the selected blocker is repaired",
                    "pass physical, routing, sensitivity, calibration, metric, and contract gates",
                ],
                "claim_impact": "diagnostic_or_provenance_plan_only_until_fresh_locked_gates_pass",
            }
        )
    status = (
        "active_non_science_pipeline_gaps"
        if plan_items
        else "no_non_science_pipeline_gaps_classified"
    )
    return {
        "version": 1,
        "status": status,
        "generated_from": "non_research_blocker_classification",
        "target_status": target_hypothesis.get("status"),
        "domains": [item["domain"] for item in plan_items],
        "gate_weakening_permitted": False,
        "temporary_metrics_allowed_as_final": False,
        "items": plan_items,
    }


def _pipeline_improvement_basin_item(row: Row, domain: str) -> dict[str, object]:
    routing_probe = row.routing_recommended_probe_order[0] if row.routing_recommended_probe_order else {}
    volume_probe = row.volume_recommended_probe_order[0] if row.volume_recommended_probe_order else {}
    next_experiment = _str_or_none(row.terminal_scope_resolution_plan.get("next_experiment"))
    if not next_experiment:
        next_experiment = _str_or_none(routing_probe.get("diagnostic") or volume_probe.get("diagnostic"))
    return {
        "basin": row.basin,
        "domain": domain,
        "primary_blocker": row.primary_blocker or _primary_blocker(row),
        "next_experiment": next_experiment or "classify_blocker_before_rerun",
        "terminal_scope_class": row.terminal_hydrograph_scope_class,
        "post_aggregation_status": _str_or_none(row.post_aggregation_process_context.get("status")),
        "first_routing_probe": _probe_summary(routing_probe),
        "first_volume_probe": _probe_summary(volume_probe),
        "decision_request": build_terminal_scope_decision_request(
            basin_id=row.basin,
            blocker_domain=domain,
            terminal_scope_resolution_plan=row.terminal_scope_resolution_plan,
            post_aggregation_process_context=row.post_aggregation_process_context,
            terminal_scope_provenance_context={
                "terminal_authority_area_check": row.terminal_authority_area_check,
                "terminal_virtual_outlet_candidate": row.terminal_virtual_outlet_candidate,
                "terminal_outlet_conflict": {
                    "class": row.terminal_outlet_conflict_class,
                    "flags": row.terminal_outlet_conflict_flags,
                    "claim_impact": row.terminal_outlet_conflict_claim_impact,
                },
                "terminal_area_scope": {
                    "class": row.terminal_area_scope_class,
                    "flags": row.terminal_area_scope_flags,
                    "claim_impact": row.terminal_area_scope_claim_impact,
                },
            },
        ),
        "evidence_artifacts": _pipeline_plan_evidence_artifacts(row),
        "source_evidence_fields": _row_improvement_evidence_fields(row, domain),
        "claim_authority": False,
        "temporary_metrics_allowed_as_final": False,
        "fresh_locked_rerun_required_before_claim": True,
    }


def _probe_summary(probe: dict[str, object]) -> dict[str, object]:
    if not probe:
        return {}
    return {
        "diagnostic": _str_or_none(probe.get("diagnostic") or probe.get("option")),
        "fresh_output_required": bool(probe.get("fresh_output_required")),
        "claim_impact": _str_or_none(probe.get("claim_impact")),
        "required_artifacts": [
            str(path)
            for path in probe.get("required_artifacts", [])
            if isinstance(path, str) and path
        ]
        if isinstance(probe.get("required_artifacts"), list)
        else [],
    }


def _pipeline_plan_evidence_artifacts(row: Row) -> dict[str, str]:
    artifacts = {
        "evidence_summary": row.evidence_summary_path,
        "physical_gates": row.physical_gates_path,
        "routing_flow_gates": row.routing_flow_gates_path,
        "terminal_trace": row.terminal_trace_path,
        "volume_bias_diagnostics": row.volume_bias_diagnostics_path,
        "weather_forcing_summary": row.weather_forcing_summary_path,
        "calibration_provenance": row.calibration_provenance_path,
    }
    return {key: value for key, value in artifacts.items() if value}


def _row_improvement_evidence_fields(row: Row, domain: str) -> list[str]:
    fields: list[str] = []
    if row.routing_source_backed_alternatives:
        fields.append("routing_source_backed_alternatives")
    if row.routing_recommended_probe_order:
        fields.append("routing_recommended_probe_order")
    if row.volume_source_backed_alternatives:
        fields.append("volume_source_backed_alternatives")
    if row.volume_recommended_probe_order:
        fields.append("volume_recommended_probe_order")
    if row.terminal_scope_resolution_plan:
        fields.append("terminal_scope_resolution_plan")
    if row.terminal_virtual_outlet_candidate:
        fields.append("terminal_virtual_outlet_candidate")
    if row.post_aggregation_process_context:
        fields.append("post_aggregation_process_context")
    if row.high_runoff_demand_context:
        fields.append("high_runoff_demand_context")
    if domain == "provenance" and row.terminal_authority_area_check:
        fields.append("terminal_authority_area_check")
    if domain == "diagnostics":
        if row.et_source_backed_alternatives or row.et_recommended_probe_order:
            fields.append("et_partition_diagnostics")
        if row.mass_balance_source_backed_alternatives or row.mass_balance_recommended_probe_order:
            fields.append("mass_balance_diagnostics")
    return fields


def _blocker_domain(blocker: str | None) -> str | None:
    if blocker is None:
        return None
    name = str(blocker)
    if name in {"soil_realism_gate_failed", "soil_fidelity"}:
        return "provenance"
    if name in {"generated_topology_mismatch", "terminal_topology_overlap"}:
        return "engineering"
    if name in {"calibration_regressed"}:
        return "calibration"
    if name in {"outlet_scope_volume_mismatch"}:
        return "provenance"
    if name in {"multi_terminal_volume_deficit"}:
        return "diagnostics"
    if name in {
        "BELOW_RESEARCH_SKILL",
        "NEGATIVE_SKILL",
        "ET_DOMINATED",
        "MASS_IMBALANCE",
        "simulated_volume_deficit",
    }:
        return "science"
    if name.startswith("simulated_volume_"):
        return "science"
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _render_skill_next_actions(actions: list[str], superseded_parameters: list[str]) -> list[str]:
    if not superseded_parameters:
        return actions
    rendered: list[str] = []
    for action in actions:
        if any(name in action for name in superseded_parameters):
            rendered.append(f"Historical superseded diagnostic: {action}")
        else:
            rendered.append(action)
    return rendered


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


_TIER_RANK: dict[str, int] = {
    "research_grade": 3,
    "publication_grade": 2,
    "exploratory": 1,
    "blocked": 0,
}


def _compute_claim_tier_matrix(payload: dict) -> dict[str, str]:
    """Return assertion_type → achieved tier for each claim class in the bundle.

    The achieved tier for a class is the highest tier where at least one claim
    is "allowed" AND no claim of that class is "blocked" at that same tier.
    Falls back to "blocked" if no tier is fully cleared.
    """
    try:
        bundle = migrate_legacy_bundle(payload)
    except Exception:
        return {}

    from collections import defaultdict
    allowed_at: dict[str, set[str]] = defaultdict(set)
    blocked_at: dict[str, set[str]] = defaultdict(set)
    for claim in bundle.claims:
        atype = claim.assertion_type
        if claim.status == "allowed":
            allowed_at[atype].add(claim.claim_tier)
        else:
            blocked_at[atype].add(claim.claim_tier)

    all_types = sorted(set(allowed_at) | set(blocked_at))
    matrix: dict[str, str] = {}
    for atype in all_types:
        cleared = allowed_at[atype] - blocked_at[atype]
        if not cleared:
            matrix[atype] = "blocked"
        else:
            best = max(cleared, key=lambda t: _TIER_RANK.get(t, 0))
            matrix[atype] = best
    return matrix


def _metadata_note_value(metadata: dict, key: str) -> str | None:
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


def _soil_fidelity_fields_pass(
    soil_mode: str | None,
    soil_provenance_mode: str | None,
    pct_fallback_soils: float | None,
) -> bool:
    return (
        soil_mode == "high_fidelity"
        and soil_provenance_mode == "gnatsgo_raster"
        and pct_fallback_soils is not None
        and pct_fallback_soils <= 0.0
    )


def _phase_from_calibration_error(error: str) -> str | None:
    marker = "during phase '"
    if marker not in error:
        return None
    tail = error.split(marker, 1)[1]
    if "'" not in tail:
        return None
    phase = tail.split("'", 1)[0].strip()
    return phase or None


def _sibling_hydrograph_overlay(value: object, suffix: str) -> str | None:
    if not value:
        return None
    candidate = Path(str(value)).with_name(f"hydrograph_observed_simulated_calibrated{suffix}")
    return str(candidate) if candidate.exists() else None


def _sibling_skill_diagnostics(run_dir: Path, suffix: str) -> str | None:
    candidate = run_dir / "calibration" / "skill_diagnostics" / f"skill_diagnostics{suffix}"
    return str(candidate) if candidate.exists() else None


def _sibling_channel_routing_screen(run_dir: Path, suffix: str) -> str | None:
    candidate = (
        run_dir
        / "calibration"
        / "channel_routing_screen"
        / "sensitivity_screen_locked"
        / f"sensitivity_screen{suffix}"
    )
    return str(candidate) if candidate.exists() else None


def _sibling_locked_sensitivity_screen(run_dir: Path, suffix: str) -> str | None:
    candidate = (
        run_dir
        / "calibration"
        / "sensitivity_screen_locked"
        / f"sensitivity_screen{suffix}"
    )
    return str(candidate) if candidate.exists() else None


def _sibling_channel_routing_calibration_verification(run_dir: Path) -> str | None:
    candidate = run_dir / "calibration" / "channel_routing_calibration" / "verification_summary.json"
    return str(candidate) if candidate.exists() else None


def _sibling_channel_routing_calibration_best_solution(run_dir: Path) -> str | None:
    candidate = (
        run_dir
        / "calibration"
        / "channel_routing_calibration"
        / "calibration_reports_locked"
        / "best_solution.json"
    )
    return str(candidate) if candidate.exists() else None


def _sibling_bound_interaction_screen(run_dir: Path) -> str | None:
    candidate = run_dir / "calibration" / "bound_interaction_screen" / "bound_interaction_screen.json"
    return str(candidate) if candidate.exists() else None


def _parse_bound_interaction_screen(
    payload: dict,
) -> tuple[int | None, str | None, dict[str, float], dict[str, float], str | None]:
    count = _safe_int_or_none(payload.get("candidate_count"))
    best = payload.get("best_by_abs_pbias")
    if not isinstance(best, dict):
        return count, None, {}, {}, _str_or_none(payload.get("claim_status"))
    params = _float_dict(best.get("parameters"))
    raw_metrics = best.get("metrics")
    metrics = _float_dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    return (
        count,
        _str_or_none(best.get("label")),
        params,
        {k: v for k, v in metrics.items() if k in {"nse", "kge", "pbias", "physical_gate_passed", "calibration_process_gate_passed"}},
        _str_or_none(payload.get("claim_status")),
    )


def _parse_channel_routing_screen(
    payload: dict,
) -> tuple[dict[str, str], dict[str, float], dict[str, dict[str, object]], list[str]]:
    classes: dict[str, str] = {}
    effects: dict[str, float] = {}
    best_bounds: dict[str, dict[str, object]] = {}
    warnings = [
        str(warning)
        for warning in payload.get("warnings", [])
        if isinstance(warning, str) and warning
    ]
    rows = payload.get("parameters", [])
    if not isinstance(rows, list):
        return classes, effects, best_bounds, warnings
    for row in rows:
        if not isinstance(row, dict):
            continue
        parameter = row.get("parameter")
        if parameter not in {"CH_N2", "CH_K2"}:
            continue
        activity = row.get("activity_class")
        if isinstance(activity, str) and activity:
            classes[str(parameter)] = activity
        evidence = row.get("evidence")
        if isinstance(evidence, dict):
            effect = _num(evidence.get("effect_size"))
            if effect is not None:
                effects[str(parameter)] = effect
            best_bound = _str_or_none(evidence.get("best_score_bound"))
            best_value = _num(evidence.get("best_score_value"))
            best_delta = _num(evidence.get("best_score_delta"))
            if best_bound is not None or best_value is not None or best_delta is not None:
                best_bounds[str(parameter)] = {
                    "bound": best_bound,
                    "value": best_value,
                    "score_delta": best_delta,
                }
    return classes, effects, best_bounds, warnings


def _parse_channel_routing_calibration(
    verification: dict,
    best_solution: dict,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], bool | None]:
    parameters: dict[str, float] = {}
    raw_parameters = best_solution.get("parameters")
    if isinstance(raw_parameters, dict):
        parameters = {
            str(parameter): value
            for parameter, raw_value in raw_parameters.items()
            if parameter in {"CH_N2", "CH_K2"} and (value := _num(raw_value)) is not None
        }

    metrics: dict[str, float] = {}
    for key in ("verified_nse", "verified_kge", "verified_pbias"):
        value = _num(verification.get(key))
        if value is not None:
            metrics[key.removeprefix("verified_")] = value

    deltas: dict[str, float] = {}
    for key in ("delta_nse", "delta_kge"):
        value = _num(verification.get(key))
        if value is not None:
            deltas[key.removeprefix("delta_")] = value

    improved = verification.get("improved")
    return parameters, metrics, deltas, improved if isinstance(improved, bool) else None


def _skill_parameter_governance(skill_diag: dict) -> tuple[list[str], list[str]]:
    unsupported: list[str] = []
    blocked: list[str] = []
    flags = skill_diag.get("diagnostic_flags", [])
    if not isinstance(flags, list):
        return unsupported, blocked
    for flag in flags:
        if not isinstance(flag, dict):
            continue
        governance = flag.get("parameter_governance")
        if not isinstance(governance, dict):
            continue
        unsupported.extend(
            str(name)
            for name in governance.get("unsupported_parameters", [])
            if isinstance(name, str) and name
        )
        blocked.extend(
            str(name)
            for name in governance.get("blocked_parameters", [])
            if isinstance(name, str) and name
        )
    return _dedupe(unsupported), _dedupe(blocked)


def _skill_probe_gap_parameters(
    alternatives: list[dict[str, object]],
    effective_classes: dict[str, object],
) -> list[str]:
    usable_classes = {"active", "weak", "limited", "requires_basin_screen"}
    suggested = _suggested_parameters_from_alternatives(alternatives)
    gaps = [
        param
        for param in _dedupe(suggested)
        if str(effective_classes.get(param) or "") not in usable_classes
    ]
    return gaps


def _suggested_parameters_from_alternatives(alternatives: list[dict[str, object]]) -> list[str]:
    suggested: list[str] = []
    for alt in alternatives:
        params = alt.get("parameters")
        if not isinstance(params, list):
            continue
        suggested.extend(str(param) for param in params if isinstance(param, str) and param)
    return _dedupe(suggested)


def _skill_gap_reasons(
    gaps: list[str],
    activity_classes: dict[str, str],
) -> dict[str, str]:
    return {
        str(parameter): str(activity_classes.get(parameter) or "not_screened")
        for parameter in gaps
    }


def _superseded_unsupported_skill_parameters(parameters: list[str]) -> list[str]:
    if not parameters:
        return []
    try:
        from swatplus_builder.full_mode.parameter_bridge import WRITERS
    except Exception:
        return []
    governed = set(WRITERS)
    return [name for name in parameters if name in governed]


def _calibration_precheck_summary(
    values: dict,
    calibration_provenance: dict,
    physical_payload: dict,
    routing_payload: dict,
    calibration: str,
) -> dict[str, str | None]:
    precheck = calibration_provenance.get("calibration_precheck")
    if not isinstance(precheck, dict):
        precheck = {}
    sequence = _str_or_none(
        values.get("calibration_precheck_sequence")
        or precheck.get("calibration_sequence")
        or precheck.get("sequence")
        or calibration_provenance.get("calibration_sequence")
    )
    block_reason = _str_or_none(
        values.get("calibration_precheck_block_reason")
        or precheck.get("reason")
        or calibration_provenance.get("calibration_precheck_block_reason")
    )
    physical_status = _str_or_none(
        values.get("calibration_precheck_physical_gates_status")
        or precheck.get("physical_gates_status")
        or calibration_provenance.get("physical_gates_status")
        or calibration_provenance.get("calibration_precheck_physical_gates_status")
    )
    routing_status = _str_or_none(
        values.get("calibration_precheck_routing_flow_gates_status")
        or precheck.get("routing_flow_gates_status")
        or calibration_provenance.get("routing_flow_gates_status")
        or calibration_provenance.get("calibration_precheck_routing_flow_gates_status")
    )
    infer_physical_payload = dict(physical_payload)
    if infer_physical_payload.get("status") is None:
        infer_physical_payload["status"] = (
            values.get("physical_gates_status")
            or values.get("calibration_precheck_physical_gates_status")
            or physical_status
        )
    infer_routing_payload = dict(routing_payload)
    if infer_routing_payload.get("status") is None:
        infer_routing_payload["status"] = (
            values.get("routing_flow_gates_status")
            or values.get("calibration_precheck_routing_flow_gates_status")
            or routing_status
        )
    if sequence is None and calibration in {
        "attempted",
        "done",
        "verified",
        "blocked_by_volume_gate",
        "blocked_by_promotion_gate",
        "blocked_by_physical_gates",
        "blocked_by_routing_flow_gates",
    }:
        inferred = _package_calibration_precheck(infer_physical_payload, infer_routing_payload)
        sequence = inferred.get("sequence")
        block_reason = block_reason or inferred.get("block_reason")
        physical_status = physical_status or inferred.get("physical_gates_status")
        routing_status = routing_status or inferred.get("routing_flow_gates_status")
    return {
        "sequence": sequence,
        "block_reason": block_reason,
        "physical_gates_status": physical_status,
        "routing_flow_gates_status": routing_status,
    }


def _package_calibration_precheck(physical_payload: dict, routing_payload: dict) -> dict[str, str | None]:
    routing_status = str(routing_payload.get("status") or "unknown")
    routing_blocking = bool(routing_payload.get("calibration_blocking", routing_status != "passed"))
    physical_status = str(physical_payload.get("status") or "unknown")
    reason: str | None = None
    sequence = "blocked_before_volume_stage"

    if routing_blocking:
        reason = "routing_flow_gates_not_passed"
    elif physical_status == "passed":
        sequence = "physical_gates_passed"
    else:
        condition_codes = {str(c) for c in physical_payload.get("condition_codes") or []}
        dominant = str(physical_payload.get("dominant_blocker") or "")
        calibratable_metric_codes = {"VOLUME_BIAS", "ET_DOMINATED", "NEGATIVE_SKILL", "BELOW_RESEARCH_SKILL"}
        calibration_blocking_physical_codes = {"ZERO_SURFACE_RUNOFF"}
        has_target = bool(condition_codes & calibratable_metric_codes)
        mass_only = condition_codes == {"MASS_IMBALANCE"}
        if condition_codes and not (condition_codes & calibration_blocking_physical_codes) and has_target and not mass_only:
            if dominant == "VOLUME_BIAS" or "VOLUME_BIAS" in condition_codes:
                sequence = "volume_bias_repair_before_final_physical_gate"
            elif dominant == "ET_DOMINATED" or "ET_DOMINATED" in condition_codes:
                sequence = "et_partition_repair_before_final_physical_gate"
            else:
                sequence = "metric_skill_repair_before_final_research_gate"
        else:
            reason = "physical_gates_not_passed"
    return {
        "sequence": _str_or_none(sequence),
        "block_reason": _str_or_none(reason),
        "physical_gates_status": _str_or_none(physical_payload.get("status")),
        "routing_flow_gates_status": _str_or_none(routing_payload.get("status")),
    }


def _routing_diagnostic_flags(routing_payload: dict) -> list[str]:
    flags = [
        str(flag)
        for flag in routing_payload.get("flags", [])
        if isinstance(flag, str) and flag
    ]
    trace_path = _str_or_none(routing_payload.get("json_path"))
    if trace_path:
        trace = _read_json(Path(trace_path))
        flags.extend(str(flag) for flag in trace.get("flags", []) if isinstance(flag, str) and flag)
    return _dedupe(flags)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _backfill_calibration_failure_context(
    *,
    calibration: str,
    history_csv: str | None,
    n_evaluations: int | None,
    promotion_gate: dict[str, object],
    calibration_provenance: dict,
    calibration_provenance_path: str | None,
) -> tuple[str | None, int | None, dict[str, object]]:
    if calibration not in {"attempted", "blocked_by_volume_gate", "blocked_by_promotion_gate"}:
        return history_csv, n_evaluations, promotion_gate
    out_history = history_csv
    out_n_eval = n_evaluations
    out_gate = dict(promotion_gate)
    if out_history is None:
        best_solution = calibration_provenance.get("best_solution_json")
        if isinstance(best_solution, str) and best_solution:
            candidate = Path(best_solution).with_name("history.csv")
            if candidate.is_file():
                out_history = str(candidate)
    if out_history is None and calibration_provenance_path:
        candidate = Path(calibration_provenance_path).parent / "calibration" / "calibration_reports_locked" / "history.csv"
        if candidate.is_file():
            out_history = str(candidate)
    if out_n_eval is None and out_history:
        out_n_eval = _history_csv_evaluation_count(Path(out_history))
    if not out_gate:
        out_gate = {"kge": 0.4, "nse": 0.0, "pbias_abs_pct": 30.0}
    return out_history, out_n_eval, out_gate


def _history_csv_evaluation_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
    except Exception:
        return None
    if not rows:
        return 0
    return max(len(rows) - 1, 0)


def _history_csv_failure_summary(
    history_csv: str | None,
    *,
    evidence_summary_path: Path,
) -> dict[str, object]:
    path = _resolve_report_path(history_csv, evidence_summary_path=evidence_summary_path)
    if path is None or not path.is_file():
        return {}
    best: dict[str, object] | None = None
    best_abs = float("inf")
    volume_pass_count = 0
    physical_pass_count = 0
    process_pass_count: int | None = None
    process_evidence_seen = False
    condition_counts: dict[str, int] = {}
    dominant_counts: dict[str, int] = {}
    process_condition_counts: dict[str, int] = {}
    phase_parameter_coverage: dict[str, set[str]] = {}
    phase_evaluation_counts: dict[str, int] = {}
    phase_order: dict[str, int] = {}
    phase_volume_gate_pass_counts: dict[str, int] = {}
    phase_physical_gate_pass_counts: dict[str, int] = {}
    phase_process_gate_pass_counts: dict[str, int] = {}
    near_miss: dict[str, object] | None = None
    near_miss_score = float("-inf")
    frontier_rows: dict[str, dict[str, object]] = {}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                phase = str(row.get("phase") or "unknown").strip() or "unknown"
                phase_evaluation_counts[phase] = phase_evaluation_counts.get(phase, 0) + 1
                parsed_order = _safe_int_or_none(row.get("phase_order"))
                if parsed_order is not None:
                    phase_order[phase] = min(parsed_order, phase_order.get(phase, parsed_order))
                params = [
                    param.strip()
                    for param in str(row.get("phase_parameters") or "").split(",")
                    if param.strip()
                ]
                if not params:
                    params = sorted(_history_row_parameters(row))
                phase_parameter_coverage.setdefault(phase, set()).update(params)
                if _csv_bool(row.get("volume_gate_passed")):
                    volume_pass_count += 1
                    phase_volume_gate_pass_counts[phase] = phase_volume_gate_pass_counts.get(phase, 0) + 1
                if _csv_bool(row.get("physical_gate_passed")):
                    physical_pass_count += 1
                    phase_physical_gate_pass_counts[phase] = phase_physical_gate_pass_counts.get(phase, 0) + 1
                if "calibration_process_gate_passed" in row:
                    process_evidence_seen = True
                    if process_pass_count is None:
                        process_pass_count = 0
                    if _csv_bool(row.get("calibration_process_gate_passed")):
                        process_pass_count += 1
                        phase_process_gate_pass_counts[phase] = (
                            phase_process_gate_pass_counts.get(phase, 0) + 1
                        )
                if "calibration_process_condition_codes" in row:
                    process_evidence_seen = True
                    _increment_codes(process_condition_counts, str(row.get("calibration_process_condition_codes") or ""))
                _increment_codes(condition_counts, str(row.get("physical_gate_condition_codes") or ""))
                dominant = str(row.get("physical_gate_dominant_blocker") or "").strip()
                if dominant:
                    dominant_counts[dominant] = dominant_counts.get(dominant, 0) + 1
                pbias = _num(row.get("metric_pbias"))
                if pbias is None:
                    continue
                near_score = _skill_volume_near_miss_score(row)
                if near_score is not None and near_score > near_miss_score:
                    near_miss_score = near_score
                    near_miss = row
                _update_skill_tradeoff_frontier(frontier_rows, row)
                abs_pbias = abs(pbias)
                if abs_pbias < best_abs:
                    best_abs = abs_pbias
                    best = row
    except Exception:
        return {}
    if not condition_counts and not dominant_counts:
        trace_condition_counts, trace_dominant_counts = _objective_trace_physical_counts(path.with_name("objective_runs"))
        condition_counts = trace_condition_counts
        dominant_counts = trace_dominant_counts
    if not process_evidence_seen and not process_condition_counts:
        trace_process_pass_count, trace_process_counts = _objective_trace_process_counts(path.with_name("objective_runs"))
        if trace_process_pass_count is not None:
            process_pass_count = trace_process_pass_count
            process_evidence_seen = True
        process_condition_counts = trace_process_counts
    if best is None:
        return {
            "volume_gate_pass_count": volume_pass_count,
            "physical_gate_pass_count": physical_pass_count,
            "process_gate_pass_count": process_pass_count,
            "phase_parameter_coverage": _phase_parameter_coverage_summary(phase_parameter_coverage),
            "phase_evaluation_counts": phase_evaluation_counts,
            "phase_order": phase_order,
            "phase_volume_gate_pass_counts": phase_volume_gate_pass_counts,
            "phase_physical_gate_pass_counts": phase_physical_gate_pass_counts,
            "phase_process_gate_pass_counts": phase_process_gate_pass_counts,
            "physical_condition_code_counts": condition_counts,
            "physical_dominant_blocker_counts": dominant_counts,
            "process_condition_code_counts": process_condition_counts,
            "skill_tradeoff_frontier": _skill_tradeoff_frontier_summary(frontier_rows),
            **_near_miss_summary(near_miss),
        }
    return {
        "volume_gate_pass_count": volume_pass_count,
        "physical_gate_pass_count": physical_pass_count,
        "process_gate_pass_count": process_pass_count,
        "best_phase": _str_or_none(best.get("phase")),
        "best_abs_pbias": best_abs,
        "best_pbias": _num(best.get("metric_pbias")),
        "best_kge": _num(best.get("metric_kge")),
        "best_nse": _num(best.get("metric_nse")),
        "best_parameters": _history_row_parameters(best),
        "phase_parameter_coverage": _phase_parameter_coverage_summary(phase_parameter_coverage),
        "phase_evaluation_counts": phase_evaluation_counts,
        "phase_order": phase_order,
        "phase_volume_gate_pass_counts": phase_volume_gate_pass_counts,
        "phase_physical_gate_pass_counts": phase_physical_gate_pass_counts,
        "phase_process_gate_pass_counts": phase_process_gate_pass_counts,
        "physical_condition_code_counts": condition_counts,
        "physical_dominant_blocker_counts": dominant_counts,
        "process_condition_code_counts": process_condition_counts,
        "skill_tradeoff_frontier": _skill_tradeoff_frontier_summary(frontier_rows),
        **_near_miss_summary(near_miss),
    }


def _phase_parameter_coverage_summary(
    coverage: dict[str, set[str]],
) -> dict[str, list[str]]:
    return {
        phase: sorted(params)
        for phase, params in sorted(coverage.items())
        if params
    }


def _update_skill_tradeoff_frontier(
    frontier_rows: dict[str, dict[str, object]],
    row: dict[str, object],
) -> None:
    kge = _num(row.get("metric_kge"))
    nse = _num(row.get("metric_nse"))
    pbias = _num(row.get("metric_pbias"))
    if kge is None and nse is None and pbias is None:
        return
    if kge is not None:
        current = frontier_rows.get("best_kge")
        current_kge = None if current is None else _num(current.get("metric_kge"))
        if current is None or current_kge is None or kge > current_kge:
            frontier_rows["best_kge"] = row
    if nse is not None:
        current = frontier_rows.get("best_nse")
        current_nse = None if current is None else _num(current.get("metric_nse"))
        if current is None or current_nse is None or nse > current_nse:
            frontier_rows["best_nse"] = row
    if pbias is not None:
        current = frontier_rows.get("best_abs_pbias")
        current_pbias = None if current is None else _num(current.get("metric_pbias"))
        if current is None or current_pbias is None or abs(pbias) < abs(current_pbias):
            frontier_rows["best_abs_pbias"] = row


def _skill_tradeoff_frontier_summary(
    frontier_rows: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        label: _history_frontier_item(row)
        for label, row in sorted(frontier_rows.items())
        if _history_frontier_item(row)
    }


def _history_frontier_item(row: dict[str, object]) -> dict[str, object]:
    metrics = {
        "kge": _num(row.get("metric_kge")),
        "nse": _num(row.get("metric_nse")),
        "pbias": _num(row.get("metric_pbias")),
    }
    if all(value is None for value in metrics.values()):
        return {}
    item: dict[str, object] = {
        "phase": _str_or_none(row.get("phase")),
        "metrics": metrics,
        "volume_gate_passed": _csv_bool(row.get("volume_gate_passed")),
        "physical_gate_passed": _csv_bool(row.get("physical_gate_passed")),
        "calibration_process_gate_passed": (
            _csv_bool(row.get("calibration_process_gate_passed"))
            if "calibration_process_gate_passed" in row
            else None
        ),
        "physical_gate_condition_codes": str(row.get("physical_gate_condition_codes") or ""),
        "physical_gate_dominant_blocker": _str_or_none(row.get("physical_gate_dominant_blocker")),
        "calibration_process_condition_codes": str(row.get("calibration_process_condition_codes") or ""),
        "parameters": _history_row_parameters(row),
        "diagnostic_only": True,
    }
    terminal_scope = _history_terminal_scope_metrics(row)
    if terminal_scope:
        item["terminal_scope_metrics"] = terminal_scope
    return item


def _history_terminal_scope_metrics(row: dict[str, object]) -> dict[str, object]:
    selected_fraction = _num(row.get("metric_selected_terminal_fraction_of_all_terminal_flow"))
    selected = {
        "nse": _num(row.get("metric_selected_terminal_nse")),
        "kge": _num(row.get("metric_selected_terminal_kge")),
        "pbias": _num(row.get("metric_selected_terminal_pbias")),
    }
    all_terminal = {
        "nse": _num(row.get("metric_all_terminal_nse")),
        "kge": _num(row.get("metric_all_terminal_kge")),
        "pbias": _num(row.get("metric_all_terminal_pbias")),
        "volume_gate_passes_diagnostic": _csv_bool_or_none(
            row.get("metric_all_terminal_volume_gate_passes_diagnostic")
        ),
    }
    if selected_fraction is None and all(value is None for value in selected.values()) and all(
        all_terminal.get(name) is None for name in ("nse", "kge", "pbias")
    ):
        return {}
    return {
        "selected_terminal_fraction_of_all_terminal_flow": selected_fraction,
        "selected_terminal": selected,
        "all_terminal": all_terminal,
        "claim_impact": "diagnostic_only_not_final_claim_evidence",
    }


def _history_frontier_dict(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, object]] = {}
    for label, item in value.items():
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics")
        if not isinstance(metrics, dict):
            continue
        parsed_metrics = {
            "kge": _num(metrics.get("kge")),
            "nse": _num(metrics.get("nse")),
            "pbias": _num(metrics.get("pbias")),
        }
        if all(metric is None for metric in parsed_metrics.values()):
            continue
        params = _float_dict(item.get("parameters"))
        parsed: dict[str, object] = {
            "phase": _str_or_none(item.get("phase")),
            "metrics": parsed_metrics,
            "volume_gate_passed": bool(item.get("volume_gate_passed")),
            "physical_gate_passed": bool(item.get("physical_gate_passed")),
            "calibration_process_gate_passed": (
                bool(item.get("calibration_process_gate_passed"))
                if item.get("calibration_process_gate_passed") is not None
                else None
            ),
            "physical_gate_condition_codes": str(item.get("physical_gate_condition_codes") or ""),
            "physical_gate_dominant_blocker": _str_or_none(item.get("physical_gate_dominant_blocker")),
            "calibration_process_condition_codes": str(item.get("calibration_process_condition_codes") or ""),
            "parameters": params,
            "diagnostic_only": item.get("diagnostic_only") is True,
        }
        terminal_scope = item.get("terminal_scope_metrics")
        if isinstance(terminal_scope, dict):
            parsed_terminal = _history_terminal_scope_frontier_dict(terminal_scope)
            if parsed_terminal:
                parsed["terminal_scope_metrics"] = parsed_terminal
        out[str(label)] = parsed
    return out


def _history_terminal_scope_frontier_dict(value: dict[str, object]) -> dict[str, object]:
    selected = value.get("selected_terminal")
    all_terminal = value.get("all_terminal")
    parsed = {
        "selected_terminal_fraction_of_all_terminal_flow": _num(
            value.get("selected_terminal_fraction_of_all_terminal_flow")
        ),
        "selected_terminal": {
            "nse": _num(selected.get("nse")) if isinstance(selected, dict) else None,
            "kge": _num(selected.get("kge")) if isinstance(selected, dict) else None,
            "pbias": _num(selected.get("pbias")) if isinstance(selected, dict) else None,
        },
        "all_terminal": {
            "nse": _num(all_terminal.get("nse")) if isinstance(all_terminal, dict) else None,
            "kge": _num(all_terminal.get("kge")) if isinstance(all_terminal, dict) else None,
            "pbias": _num(all_terminal.get("pbias")) if isinstance(all_terminal, dict) else None,
            "volume_gate_passes_diagnostic": (
                bool(all_terminal.get("volume_gate_passes_diagnostic"))
                if isinstance(all_terminal, dict)
                and all_terminal.get("volume_gate_passes_diagnostic") is not None
                else None
            ),
        },
        "claim_impact": _str_or_none(value.get("claim_impact")),
    }
    if parsed["selected_terminal_fraction_of_all_terminal_flow"] is None and all(
        metric is None
        for section in ("selected_terminal", "all_terminal")
        for key, metric in parsed[section].items()
        if key != "volume_gate_passes_diagnostic"
    ):
        return {}
    return parsed


def _history_row_parameters(row: dict[str, object]) -> dict[str, float]:
    params: dict[str, float] = {}
    for key, value in row.items():
        if not str(key).startswith("param_"):
            continue
        parsed = _num(value)
        if parsed is not None:
            params[str(key).removeprefix("param_")] = parsed
    return params


def _parameter_bound_context(
    parameters: dict[str, float],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    hits: dict[str, dict[str, object]] = {}
    evaluated: dict[str, dict[str, object]] = {}
    unknown: list[str] = []
    for name, value in sorted(parameters.items()):
        spec = registry.get(name)
        if spec is None:
            unknown.append(name)
            evaluated[name] = {"value": value, "known": False}
            continue
        lo, hi = spec.range
        tolerance = max(1e-9, abs(hi - lo) * 1e-7)
        boundary: str | None = None
        if abs(value - lo) <= tolerance:
            boundary = "lower"
        elif abs(value - hi) <= tolerance:
            boundary = "upper"
        item: dict[str, object] = {
            "value": value,
            "min": float(lo),
            "max": float(hi),
            "boundary": boundary,
            "known": True,
            "at_bound": boundary is not None,
        }
        evaluated[name] = item
        if boundary is not None:
            hits[name] = item
    known = [item for item in evaluated.values() if item.get("known")]
    context: dict[str, object] = {
        "evaluated_parameters": evaluated,
        "unknown_parameters": unknown,
        "bound_hit_parameters": sorted(hits),
        "all_known_parameters_at_bounds": bool(known)
        and all(bool(item.get("at_bound")) for item in known),
    }
    return hits, context


def _skill_volume_near_miss_score(row: dict[str, str]) -> float | None:
    nse = _num(row.get("metric_nse"))
    kge = _num(row.get("metric_kge"))
    pbias = _num(row.get("metric_pbias"))
    if nse is None or kge is None or pbias is None:
        return None
    abs_pbias = abs(pbias)
    if nse < 0.0 or kge < 0.4:
        return None
    if not (30.0 < abs_pbias <= 40.0):
        return None
    if _csv_bool(row.get("volume_gate_passed")):
        return None
    return kge + 0.2 * nse - (abs_pbias - 30.0) / 30.0


def _near_miss_summary(row: dict[str, str] | None) -> dict[str, object]:
    if row is None:
        return {
            "skill_volume_near_miss": False,
            "near_miss_parameters": {},
        }
    params: dict[str, float] = {}
    for key, value in row.items():
        if not key.startswith("param_"):
            continue
        parsed = _num(value)
        if parsed is None:
            continue
        params[key.removeprefix("param_")] = parsed
    return {
        "skill_volume_near_miss": True,
        "near_miss_phase": _str_or_none(row.get("phase")),
        "near_miss_pbias": _num(row.get("metric_pbias")),
        "near_miss_kge": _num(row.get("metric_kge")),
        "near_miss_nse": _num(row.get("metric_nse")),
        "near_miss_parameters": params,
    }


def _resolve_report_path(path_text: str | None, *, evidence_summary_path: Path) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text)
    if path.is_absolute():
        return path
    candidate = evidence_summary_path.parent / path
    if candidate.exists():
        return candidate
    return path


def _csv_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def _csv_bool_or_none(value: object) -> bool | None:
    text = str(value).strip().lower()
    if text in {"", "none", "nan", "null"}:
        return None
    if text in {"1", "1.0", "true", "yes", "y"}:
        return True
    if text in {"0", "0.0", "false", "no", "n"}:
        return False
    return None


def _increment_codes(counts: dict[str, int], raw: str) -> None:
    for code in raw.replace(";", ",").split(","):
        code = code.strip()
        if code:
            counts[code] = counts.get(code, 0) + 1


def _objective_trace_physical_counts(trace_dir: Path) -> tuple[dict[str, int], dict[str, int]]:
    condition_counts: dict[str, int] = {}
    dominant_counts: dict[str, int] = {}
    if not trace_dir.is_dir():
        return condition_counts, dominant_counts
    for trace in trace_dir.glob("*_objective_trace.json"):
        payload = _read_json(trace)
        gate = payload.get("candidate_physical_gate")
        if not isinstance(gate, dict):
            continue
        codes = gate.get("condition_codes")
        if isinstance(codes, list):
            for code in codes:
                text = str(code).strip()
                if text:
                    condition_counts[text] = condition_counts.get(text, 0) + 1
        dominant = str(gate.get("dominant_blocker") or "").strip()
        if dominant:
            dominant_counts[dominant] = dominant_counts.get(dominant, 0) + 1
    return condition_counts, dominant_counts


def _objective_trace_process_counts(trace_dir: Path) -> tuple[int | None, dict[str, int]]:
    process_pass_count: int | None = None
    process_condition_counts: dict[str, int] = {}
    if not trace_dir.is_dir():
        return process_pass_count, process_condition_counts
    for trace in trace_dir.glob("*_objective_trace.json"):
        payload = _read_json(trace)
        gate = payload.get("candidate_physical_gate")
        if not isinstance(gate, dict):
            continue
        inferred_process_codes: list[str] | None = None
        if "calibration_process_gate_pass" in gate:
            if process_pass_count is None:
                process_pass_count = 0
            if bool(gate.get("calibration_process_gate_pass")):
                process_pass_count += 1
        elif isinstance(gate.get("condition_codes"), list):
            inferred_process_codes = [
                str(code).strip()
                for code in gate.get("condition_codes", [])
                if str(code).strip() and str(code).strip() not in _SKILL_ONLY_GATE_CODES
            ]
            if process_pass_count is None:
                process_pass_count = 0
            if not inferred_process_codes:
                process_pass_count += 1
        codes = gate.get("calibration_process_condition_codes")
        if not isinstance(codes, list) and inferred_process_codes is not None:
            codes = inferred_process_codes
        if isinstance(codes, list):
            for code in codes:
                text = str(code).strip()
                if text:
                    process_condition_counts[text] = process_condition_counts.get(text, 0) + 1
    return process_pass_count, process_condition_counts


def _discover_build_diagnostics(run_dir: Path, existing: dict[str, str]) -> dict[str, str]:
    candidates = {
        "overlay_repair_report": run_dir / "reports" / "overlay_repair" / "overlay_repair_report.json",
        "soil_acquisition_report": run_dir / "reports" / "soil_acquisition_report.json",
        "soil_realism_diagnostics": run_dir / "reports" / "soil_realism_diagnostics.json",
        "soil_report": run_dir / "reports" / "soil_report.json",
    }
    return {
        key: str(path)
        for key, path in candidates.items()
        if key not in existing and path.is_file()
    }


def _soil_diagnostic_evidence(
    build_diagnostics: dict[str, str],
) -> tuple[list[str], list[dict[str, object]], list[dict[str, object]]]:
    actions: list[str] = []
    alternatives: list[dict[str, object]] = []
    probe_order: list[dict[str, object]] = []
    for key in ("soil_realism_diagnostics", "soil_acquisition_report", "soil_report"):
        path = build_diagnostics.get(key)
        if not path:
            continue
        payload = _read_json(Path(path))
        if not actions and isinstance(payload.get("next_actions"), list):
            actions = [
                str(action)
                for action in payload.get("next_actions", [])
                if isinstance(action, str) and action
            ]
        if not alternatives and isinstance(payload.get("source_backed_alternatives"), list):
            alternatives = [
                alt
                for alt in payload.get("source_backed_alternatives", [])
                if isinstance(alt, dict)
            ]
        if not probe_order and isinstance(payload.get("recommended_probe_order"), list):
            probe_order = [
                probe
                for probe in payload.get("recommended_probe_order", [])
                if isinstance(probe, dict)
            ]
    return actions, alternatives, probe_order


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run or summarize the canonical objective basin validation suite. "
            "By default this runs every basin; use --summarize-existing to "
            "regenerate reports from existing evidence without launching workflows."
        )
    )
    parser.add_argument(
        "--out-root",
        default="swatplus_runs/objective_10basin",
        help="Root directory containing or receiving per-basin workflow artifacts.",
    )
    parser.add_argument(
        "--report-md",
        default="docs/OBJECTIVE_BASIN_VALIDATION_REPORT.md",
        help="Markdown validation report path.",
    )
    parser.add_argument(
        "--report-json",
        default="docs/objective_basin_validation_report.json",
        help="Machine-readable validation report path.",
    )
    parser.add_argument(
        "--summarize-existing",
        action="store_true",
        help="Do not run workflows; summarize existing per-basin evidence artifacts.",
    )
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Reuse existing per-basin evidence summaries and run only missing basins.",
    )
    parser.add_argument(
        "--evidence-override",
        action="append",
        default=[],
        metavar="BASIN=PATH",
        help=(
            "Use a specific evidence_summary.json for one basin when regenerating "
            "the objective report from fresher reruns outside --out-root. May be repeated."
        ),
    )
    return parser.parse_args(argv)


def _generation_metadata(
    args: argparse.Namespace,
    run_root: Path,
    evidence_overrides: dict[str, Path],
) -> dict[str, object]:
    return {
        "out_root": str(run_root),
        "summarize_existing": bool(args.summarize_existing),
        "resume_existing": bool(args.resume_existing),
        "report_md": str(Path(args.report_md).resolve()),
        "report_json": str(Path(args.report_json).resolve()),
        "evidence_overrides": {
            basin: str(path)
            for basin, path in sorted(evidence_overrides.items())
        },
    }


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    run_root = Path(args.out_root).resolve()
    evidence_overrides = _parse_evidence_overrides(args.evidence_override)
    rows = (
        summarize_existing_suite(run_root, evidence_overrides=evidence_overrides)
        if args.summarize_existing
        else run_suite(
            run_root,
            resume_existing=bool(args.resume_existing),
            evidence_overrides=evidence_overrides,
        )
    )
    write_outputs(
        rows,
        Path(args.report_md),
        Path(args.report_json),
        generation_metadata=_generation_metadata(args, run_root, evidence_overrides),
    )
    print(json.dumps({"rows": len(rows), "run_root": str(run_root)}, indent=2))


if __name__ == "__main__":
    main()
