from __future__ import annotations

from pathlib import Path
import json
import pytest

from scripts.audit_production_objective import (
    _pipeline_improvement_decision_request_ok,
    _row_et_diagnostics_ok,
    _row_hydrograph_ok,
    _row_skill_bound_aware_probe_order_ok,
    build_audit,
)
from scripts.run_objective_10basin import (
    main,
    summarize_evidence,
    summarize_existing_suite,
    write_outputs,
)


def test_benchmark_scripts_do_not_define_science_policy() -> None:
    scripts = [
        Path("scripts/benchmark_10_basin.py"),
        Path("scripts/benchmark_full_10basin.py"),
        Path("scripts/cal_5_basin.py"),
    ]
    forbidden = [
        "check_water_balance",
        "allowed_tiers",
        "patch_cn2",
        "calibrate_cn2",
        "research_grade\" if",
        "research' if",
        "low_skill_nonresearch",
        "metrics_unavailable",
        "urban_or_structural_limited",
    ]
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{script} must not define policy token {token!r}"


def test_objective_suite_reads_claims_from_workflow_evidence_only() -> None:
    text = Path("scripts/run_objective_10basin.py").read_text(encoding="utf-8")
    assert "run_usgs_workflow" in text
    assert 'claim_tier="research_grade"' in text
    assert "payload.get(\"effective_claim_tier\")" in text
    assert "build_terminal_scope_decision_request" in text
    assert "def _pipeline_plan_decision_request" not in text
    assert "allowed_tiers" not in text
    assert "low_skill_nonresearch" not in text


def test_production_objective_audit_uses_current_canonical_report() -> None:
    text = Path("scripts/audit_production_objective.py").read_text(encoding="utf-8")

    assert "objective_basin_validation_report.json" in text
    assert "OBJECTIVE_BASIN_VALIDATION_REPORT.md" in text
    assert "BENCHMARK_10_BASIN_FINAL_2026-05-12" not in text
    assert "benchmark_10_basin_final_2026-05-12" not in text
    assert "COMPLETION_AUDIT_2026-05-12" not in text


def test_production_objective_audit_reports_current_incomplete_status() -> None:
    audit = build_audit()
    checks = {row["requirement"]: row for row in audit["checks"]}

    assert audit["overall_status"] == "not_complete"
    assert checks["Canonical objective-suite validation report present"]["status"] == "implemented"
    assert checks["Objective report covers the requested basin suite"]["status"] == "implemented"
    assert checks["All objective rows retain valid evidence_summary.json pointers"]["status"] == "implemented"
    assert checks[
        "All objective rows retain machine-readable allowed and blocked claim names"
    ]["status"] == "implemented"
    assert checks["Objective report records generation metadata and evidence overrides"]["status"] == "implemented"
    assert checks["All objective rows have explicit routing-flow gate status"]["status"] == "implemented"
    assert checks["Non-research outcomes expose machine-readable primary blockers"]["status"] == "implemented"
    assert checks[
        "Non-research outcomes retain blocker domains and machine-readable action plans"
    ]["status"] == "implemented"
    assert checks[
        "Target hypothesis evaluation preserves gate policy and fewer-pass interpretation"
    ]["status"] == "implemented"
    assert checks[
        "Objective suite emits a machine-readable pipeline improvement plan"
    ]["status"] == "implemented"
    assert checks[
        "Pipeline improvement diagnostics are evidence-specific and process-context backed"
    ]["status"] == "implemented"
    assert checks["Calibration provenance exists for attempted or verified calibrations"]["status"] == "implemented"
    assert checks[
        "Basin-specific sensitivity screens exist for attempted or verified calibrations"
    ]["status"] == "implemented"
    assert checks[
        "Diagnostic calibration blocks KGE/NSE finetune until prior process gates pass"
    ]["status"] == "implemented"
    assert checks[
        "Research-grade rows retain current core-governance sensitivity coverage"
    ]["status"] == "implemented"
    assert checks[
        "Calibration delta metrics exist for attempted or verified calibrations"
    ]["status"] == "implemented"
    assert checks["Regressed locked calibrations retain regression blocker evidence"]["status"] == "implemented"
    assert checks[
        "Promotion-gate calibration failures retain phase and final-metric authority evidence"
    ]["status"] == "implemented"
    assert checks[
        "Failed or blocked calibration searches retain failure-phase evidence"
    ]["status"] == "implemented"
    assert checks[
        "Failed or blocked calibration searches retain history, best-parameter vector, bound context, and promotion-gate context"
    ]["status"] == "implemented"
    assert checks[
        "Failed or blocked calibration histories retain diagnostic skill-volume tradeoff frontier"
    ]["status"] == "implemented"
    assert checks[
        "Failed calibration histories with terminal candidate metrics surface diagnostic terminal-scope frontier evidence"
    ]["status"] == "implemented"
    assert checks[
        "Calibration bound-interaction screens remain diagnostic-only evidence"
    ]["status"] == "implemented"
    assert checks[
        "Failed calibration objective traces retain candidate physical blocker classifications"
    ]["status"] == "implemented"
    assert checks[
        "Failed calibration objective traces retain process-vs-claim gate classifications"
    ]["status"] == "implemented"
    assert checks["Volume-bias blockers retain diagnostic flags and next actions"]["status"] == "implemented"
    assert checks[
        "Terminal-scope volume blockers retain row-level selected-vs-all hydrograph diagnostics"
    ]["status"] == "implemented"
    assert checks[
        "Terminal-scope hydrograph diagnostics retain KGE component decomposition"
    ]["status"] == "implemented"
    assert checks[
        "Terminal-scope hydrograph diagnostics retain all-terminal aggregation validity context"
    ]["status"] == "implemented"
    assert checks[
        "Terminal-scope hydrograph diagnostics retain package-owned scope classification"
    ]["status"] == "implemented"
    assert checks[
        "Terminal-scope volume blockers retain machine-readable outlet-scope classification"
    ]["status"] == "implemented"
    assert checks[
        "Terminal-scope volume blockers prioritize outlet reconciliation before parameter screens"
    ]["status"] == "implemented"
    assert checks["Skill blockers retain hydrograph diagnostic flags and next actions"]["status"] == "implemented"
    assert checks["Skill blockers retain structured diagnostic evidence metrics"]["status"] == "implemented"
    assert checks["Skill blockers retain KGE component decomposition evidence"]["status"] == "implemented"
    assert checks[
        "Skill channel-routing attenuation blockers retain locked screen evidence"
    ]["status"] == "implemented"
    assert checks[
        "Skill channel-routing refinements retain verified locked-rerun evidence"
    ]["status"] == "implemented"
    assert checks["Skill diagnostics retain parameter-governance blockers"]["status"] == "implemented"
    assert checks[
        "Skill diagnostic suggested controls expose sensitivity-screen coverage gaps"
    ]["status"] == "implemented"
    assert checks[
        "Skill diagnostic suggested controls distinguish screened-dead from unscreened controls"
    ]["status"] == "implemented"
    assert checks["Skill diagnostics retain locked-parameter bound context"]["status"] == "implemented"
    assert checks[
        "Skill diagnostics deprioritize fully bound-exhausted probes"
    ]["status"] == "implemented"
    assert checks[
        "Superseded unsupported skill controls are marked by current bridge support"
    ]["status"] == "implemented"
    assert checks[
        "Attempted calibrations retain precheck gate sequence evidence"
    ]["status"] == "implemented"
    assert checks["Soil-realism blockers retain build diagnostic artifacts"]["status"] == "implemented"
    assert checks["Soil-realism blockers expose machine-readable next actions"]["status"] == "implemented"
    assert checks["Soil-fidelity blockers retain soil provenance fields"]["status"] == "implemented"
    assert checks["Failed or warning routing-flow rows retain closure diagnostics"]["status"] == "implemented"
    assert checks["Failed or warning routing-flow rows retain source coverage diagnostics"]["status"] == "implemented"
    assert checks["Routing-unit scale-suspect rows retain unit-semantics diagnostics"]["status"] == "implemented"
    assert checks[
        "Routed-to-channel semantic-ambiguity rows retain diagnostic ratios"
    ]["status"] == "implemented"
    assert checks["Routing gate artifact/status mismatches are explicit"]["status"] == "implemented"
    assert checks["Multi-terminal routing rows retain terminal inventory diagnostics"]["status"] == "implemented"
    assert checks[
        "Multi-terminal routing rows retain source-backed terminal area context"
    ]["status"] == "implemented"
    assert checks[
        "Multi-terminal routing rows retain official USGS drainage-area authority checks"
    ]["status"] == "implemented"
    assert checks[
        "Official-area matching multi-terminal rows retain diagnostic-only virtual outlet candidates"
    ]["status"] == "implemented"
    assert checks[
        "Multi-terminal routing rows retain gauge-coordinate terminal ranking context"
    ]["status"] == "implemented"
    assert checks[
        "Selected outlets that are not nearest gauge terminals prioritize outlet reconciliation"
    ]["status"] == "implemented"
    assert checks[
        "Selected outlets that are not nearest gauge terminals retain conflict classification"
    ]["status"] == "implemented"
    assert checks[
        "Not-nearest terminal diagnostics retain nearest-terminal hydrograph metrics"
    ]["status"] == "implemented"
    assert checks[
        "Post-aggregation terminal volume deficits retain process-diagnosis probes"
    ]["status"] == "implemented"
    assert checks[
        "Terminal-topology overlap blockers retain pairwise overlap diagnostics"
    ]["status"] == "implemented"
    assert checks["ET-dominated rows require ET parameter screen context"]["status"] == "implemented"
    assert checks["ET-dominated rows retain ET partition diagnostics"]["status"] == "implemented"
    assert checks["Build blockers expose machine-readable diagnostic artifacts"]["status"] == "implemented"
    assert checks["Volume-bias blockers retain observed-window forcing context"]["status"] == "implemented"
    assert (
        checks["Volume-bias forcing context classifies runoff-precipitation plausibility"]["status"]
        == "implemented"
    )
    assert (
        checks["High observed runoff fraction rows retain snow-storage/baseflow/area context"]["status"]
        == "implemented"
    )
    assert (
        checks["High observed runoff fraction rows classify snow/baseflow/yield gaps"]["status"]
        == "implemented"
    )
    assert checks[
        "Post-aggregation terminal volume deficits retain process context"
    ]["status"] == "implemented"
    assert checks[
        "Post-aggregation terminal volume deficits retain candidate explanations"
    ]["status"] == "implemented"
    assert checks[
        "Pipeline improvement diagnostic decisions preserve candidate explanations"
    ]["status"] == "implemented"
    assert checks[
        "Science blockers retain root explanatory evidence summary"
    ]["status"] == "implemented"
    assert (
        checks["Calibration histories expose machine-readable phase parameter coverage"]["status"]
        == "implemented"
    )
    assert checks["Research-grade target is scientifically met"]["status"] == "missing"
    assert audit["metrics"]["research_grade_count"] == 1
    assert audit["metrics"]["blocker_domain_action_rows"] == 10
    assert audit["metrics"]["required_blocker_domain_action_rows"] == 10
    assert audit["metrics"]["report_blocker_classification_ok"] is True
    assert audit["metrics"]["target_hypothesis_evaluation_ok"] is True
    assert audit["metrics"]["science_blocker_summary_ok"] is True
    assert audit["metrics"]["pipeline_improvement_plan_ok"] is True
    assert audit["metrics"]["pipeline_improvement_plan_domains"] == ["diagnostics", "provenance"]
    assert audit["metrics"]["pipeline_improvement_plan_basin_rows"] == 6
    assert audit["metrics"]["required_pipeline_improvement_plan_basin_rows"] == 6
    assert audit["metrics"]["pipeline_improvement_decision_request_rows"] == 6
    assert audit["metrics"]["pipeline_improvement_diagnostic_context_rows"] == 4
    assert audit["metrics"]["required_pipeline_improvement_diagnostic_context_rows"] == 4
    assert audit["metrics"]["pipeline_improvement_diagnostic_explanation_rows"] == 4
    assert audit["metrics"]["required_pipeline_improvement_diagnostic_explanation_rows"] == 4
    assert audit["metrics"]["pipeline_improvement_provenance_context_rows"] == 2
    assert audit["metrics"]["required_pipeline_improvement_provenance_context_rows"] == 2
    assert audit["metrics"]["claim_policy_name_rows"] == 11
    assert audit["metrics"]["hydrograph_rows"] == 5
    assert audit["metrics"]["calibration_rows"] == 5
    assert audit["metrics"]["calibration_provenance_rows"] == 5
    assert audit["metrics"]["sensitivity_screen_rows"] == 5
    assert audit["metrics"]["research_grade_core_sensitivity_rows"] == 1
    assert audit["metrics"]["required_research_grade_core_sensitivity_rows"] == 1
    assert audit["metrics"]["calibration_delta_rows"] == 5
    assert audit["metrics"]["calibration_regression_rows"] == 0
    assert audit["metrics"]["required_calibration_regression_rows"] == 0
    assert audit["metrics"]["promotion_gate_failure_rows"] == 5
    assert audit["metrics"]["required_promotion_gate_failure_rows"] == 5
    assert audit["metrics"]["failed_calibration_evidence_rows"] == 8
    assert audit["metrics"]["required_failed_calibration_rows"] == 8
    assert audit["metrics"]["failed_calibration_context_rows"] == 8
    assert audit["metrics"]["required_failed_calibration_context_rows"] == 8
    assert audit["metrics"]["calibration_phase_coverage_rows"] == 10
    assert audit["metrics"]["required_calibration_phase_coverage_rows"] == 10
    assert audit["metrics"]["failed_calibration_tradeoff_frontier_rows"] == 8
    assert audit["metrics"]["required_failed_calibration_tradeoff_frontier_rows"] == 8
    assert audit["metrics"]["failed_calibration_terminal_scope_history_rows"] == 0
    assert audit["metrics"]["required_failed_calibration_terminal_scope_history_rows"] == 0
    assert audit["metrics"]["failed_calibration_physical_trace_rows"] == 8
    assert audit["metrics"]["required_failed_calibration_physical_trace_rows"] == 8
    assert audit["metrics"]["failed_calibration_process_trace_rows"] == 8
    assert audit["metrics"]["required_failed_calibration_process_trace_rows"] == 8
    assert audit["metrics"]["calibration_precheck_rows"] == 11
    assert audit["metrics"]["required_calibration_precheck_rows"] == 11
    assert audit["metrics"]["volume_diagnostic_rows"] == 5
    assert audit["metrics"]["required_volume_diagnostic_rows"] == 5
    assert audit["metrics"]["terminal_hydrograph_scope_rows"] == 7
    assert audit["metrics"]["required_terminal_hydrograph_scope_rows"] == 7
    assert audit["metrics"]["terminal_hydrograph_kge_component_rows"] == 7
    assert audit["metrics"]["required_terminal_hydrograph_kge_component_rows"] == 7
    assert audit["metrics"]["terminal_hydrograph_aggregation_context_rows"] == 7
    assert audit["metrics"]["required_terminal_hydrograph_aggregation_context_rows"] == 7
    assert audit["metrics"]["terminal_hydrograph_scope_class_rows"] == 7
    assert audit["metrics"]["required_terminal_hydrograph_scope_class_rows"] == 7
    assert audit["metrics"]["terminal_scope_resolution_plan_rows"] == 7
    assert audit["metrics"]["required_terminal_scope_resolution_plan_rows"] == 7
    assert audit["metrics"]["terminal_scope_blocker_rows"] == 7
    assert audit["metrics"]["required_terminal_scope_blocker_rows"] == 7
    assert audit["metrics"]["routing_terminal_scope_blocker_rows"] == 5
    assert audit["metrics"]["required_routing_terminal_scope_blocker_rows"] == 5
    assert audit["metrics"]["terminal_scope_claim_blocked_rows"] == 8
    assert audit["metrics"]["required_terminal_scope_claim_rows"] == 8
    assert audit["metrics"]["terminal_scope_probe_priority_rows"] == 7
    assert audit["metrics"]["required_terminal_scope_probe_priority_rows"] == 7
    assert audit["metrics"]["skill_diagnostic_rows"] == 3
    assert audit["metrics"]["required_skill_diagnostic_rows"] == 3
    assert audit["metrics"]["skill_limitation_class_rows"] == 3
    assert audit["metrics"]["required_skill_limitation_class_rows"] == 3
    assert audit["metrics"]["skill_evidence_metrics_rows"] == 3
    assert audit["metrics"]["required_skill_evidence_metrics_rows"] == 3
    assert audit["metrics"]["skill_kge_component_rows"] == 3
    assert audit["metrics"]["required_skill_kge_component_rows"] == 3
    assert audit["metrics"]["skill_channel_screen_rows"] == 3
    assert audit["metrics"]["required_skill_channel_screen_rows"] == 3
    assert audit["metrics"]["skill_channel_refinement_rows"] == 0
    assert audit["metrics"]["required_skill_channel_refinement_rows"] == 0
    assert audit["metrics"]["calibration_bound_interaction_rows"] == 1
    assert audit["metrics"]["required_calibration_bound_interaction_rows"] == 1
    assert audit["metrics"]["skill_probe_gap_rows"] == 3
    assert audit["metrics"]["required_skill_probe_gap_rows"] == 3
    assert audit["metrics"]["skill_sensitivity_triage_rows"] == 1
    assert audit["metrics"]["required_skill_sensitivity_triage_rows"] == 1
    assert audit["metrics"]["skill_bound_context_rows"] == 3
    assert audit["metrics"]["required_skill_bound_context_rows"] == 3
    assert audit["metrics"]["skill_bound_aware_probe_rows"] == 3
    assert audit["metrics"]["required_skill_bound_aware_probe_rows"] == 3
    assert audit["metrics"]["skill_parameter_governance_rows"] == 0
    assert audit["metrics"]["required_skill_parameter_governance_rows"] == 0
    report = json.loads(Path("docs/objective_basin_validation_report.json").read_text(encoding="utf-8"))
    for row in report["rows"]:
        assert row["physical_gates_path"]
        assert Path(row["physical_gates_path"]).is_file()
    for row in report["rows"]:
        if row.get("primary_blocker") != "BELOW_RESEARCH_SKILL":
            continue
        assert row["skill_limitation_class"]
        assert row["skill_limitation_flags"]
        assert row["skill_limitation_claim_impact"] == "diagnostic_only_until_locked_skill_gates_pass"
        assert row["skill_limitation_dominant_kge_component"] in {"correlation", "variability", "bias"}
        diagnostics_path = row.get("skill_diagnostics_json")
        assert diagnostics_path
        diagnostics = json.loads(Path(diagnostics_path).read_text(encoding="utf-8"))
        suggested = {
            parameter
            for flag in diagnostics.get("diagnostic_flags", [])
            if isinstance(flag, dict)
            for parameter in flag.get("suggested_parameters", [])
        }
        assert "GW_DELAY" not in suggested
        assert "GWQMN" not in suggested
    assert audit["metrics"]["superseded_skill_parameter_rows"] == 0
    assert audit["metrics"]["required_superseded_skill_parameter_rows"] == 0
    assert audit["metrics"]["soil_realism_diagnostic_rows"] == 0
    assert audit["metrics"]["soil_realism_remediation_rows"] == 0
    assert audit["metrics"]["required_soil_realism_rows"] == 0
    assert audit["metrics"]["soil_fidelity_provenance_rows"] == audit["metrics"][
        "required_soil_fidelity_rows"
    ]
    assert audit["metrics"]["routing_diagnostic_rows"] == 6
    assert audit["metrics"]["routing_source_coverage_rows"] == 6
    assert audit["metrics"]["required_routing_diagnostic_rows"] == 6
    assert audit["metrics"]["routing_unit_semantics_rows"] == 6
    assert audit["metrics"]["required_routing_unit_semantics_rows"] == 6
    assert audit["metrics"]["routed_to_channel_semantics_rows"] == 0
    assert audit["metrics"]["required_routed_to_channel_semantics_rows"] == 0
    assert audit["metrics"]["routing_status_mismatch_rows"] == 0
    assert audit["metrics"]["required_routing_status_mismatch_rows"] == 0
    assert audit["metrics"]["terminal_inventory_rows"] == 8
    assert audit["metrics"]["required_terminal_inventory_rows"] == 8
    assert audit["metrics"]["terminal_area_context_rows"] == 8
    assert audit["metrics"]["required_terminal_area_context_rows"] == 8
    assert audit["metrics"]["terminal_area_scope_class_rows"] == 8
    assert audit["metrics"]["required_terminal_area_scope_class_rows"] == 8
    assert audit["metrics"]["terminal_authority_area_context_rows"] == 8
    assert audit["metrics"]["required_terminal_authority_area_context_rows"] == 8
    assert audit["metrics"]["terminal_virtual_outlet_candidate_rows"] == 8
    assert audit["metrics"]["required_terminal_virtual_outlet_candidate_rows"] == 8
    assert audit["metrics"]["terminal_gauge_context_rows"] == 8
    assert audit["metrics"]["required_terminal_gauge_context_rows"] == 8
    assert audit["metrics"]["not_nearest_terminal_probe_rows"] == 4
    assert audit["metrics"]["required_not_nearest_terminal_probe_rows"] == 4
    assert audit["metrics"]["terminal_outlet_conflict_class_rows"] == 4
    assert audit["metrics"]["required_terminal_outlet_conflict_class_rows"] == 4
    assert audit["metrics"]["nearest_terminal_hydrograph_rows"] == 3
    assert audit["metrics"]["required_nearest_terminal_hydrograph_rows"] == 3
    assert audit["metrics"]["post_aggregation_volume_deficit_rows"] == 4
    assert audit["metrics"]["required_post_aggregation_volume_deficit_rows"] == 4
    assert audit["metrics"]["post_aggregation_process_context_rows"] == 4
    assert audit["metrics"]["required_post_aggregation_process_context_rows"] == 4
    assert audit["metrics"]["post_aggregation_candidate_explanation_rows"] == 4
    assert audit["metrics"]["required_post_aggregation_candidate_explanation_rows"] == 4
    assert audit["metrics"]["volume_forcing_context_rows"] == 5
    assert audit["metrics"]["required_volume_forcing_context_rows"] == 5
    assert audit["metrics"]["volume_forcing_plausibility_rows"] == 5
    assert audit["metrics"]["required_volume_forcing_plausibility_rows"] == 5
    assert audit["metrics"]["high_runoff_demand_context_rows"] == 1
    assert audit["metrics"]["high_runoff_interpretation_rows"] == 1
    assert audit["metrics"]["required_high_runoff_demand_rows"] == 1
    high_runoff_rows = [
        row
        for row in report["rows"]
        if row.get("high_runoff_demand_context", {}).get("available") is True
    ]
    assert len(high_runoff_rows) == 1
    high_runoff_context = high_runoff_rows[0]["high_runoff_demand_context"]
    explanations = {
        item["hypothesis"]: item
        for item in high_runoff_context["candidate_explanations"]
    }
    assert explanations["precipitation_area_or_external_inflow_basis"]["status"] == (
        "area_matches_all_terminal_but_runoff_fraction_remains_high"
    )
    assert explanations["snow_storage_or_snowmelt_release"]["status"] == (
        "not_supported_by_current_swat_snow_terms"
    )
    assert explanations["groundwater_or_aquifer_release"]["status"] == (
        "not_supported_by_current_aquifer_release"
    )
    assert explanations["selected_terminal_scope"]["status"] == "selected_terminal_partial"
    assert "run_fresh_locked_rerun_after_high_runoff_repair" in high_runoff_context[
        "required_before_claim"
    ]
    high_runoff_parameters = {
        parameter
        for row in high_runoff_rows
        for alternative in row.get("volume_source_backed_alternatives", [])
        if alternative.get("option") == "audit_high_observed_runoff_fraction_context"
        for parameter in alternative.get("parameters", [])
    }
    assert "GW_DELAY" not in high_runoff_parameters
    assert {"SFTMP", "SMTMP", "LAT_TTIME", "ALPHA_BF", "RCHG_DP"}.issubset(
        high_runoff_parameters
    )
    row_02129000 = next(row for row in report["rows"] if row.get("basin") == "02129000")
    assert row_02129000["volume_bias_diagnostics_path"]
    assert row_02129000["terminal_scope_blocker"] == "outlet_scope_volume_mismatch"
    assert row_02129000["terminal_hydrograph_scope"]["available"] is True
    assert row_02129000["terminal_hydrograph_scope"]["selected_terminal"]["kge_components"]["method"] == (
        "kge_2009_components"
    )
    assert row_02129000["terminal_hydrograph_scope"]["all_terminal"]["kge_components"]["method"] == (
        "kge_2009_components"
    )
    assert row_02129000["terminal_hydrograph_scope"]["selected_outlet_is_nearest_terminal"] is False
    assert row_02129000["terminal_hydrograph_scope_class"] == (
        "selected_metric_passes_but_area_scope_partial"
    )
    assert "selected_terminal_scope_partial" in row_02129000["terminal_hydrograph_scope_flags"]
    assert row_02129000["terminal_hydrograph_scope_claim_impact"] == (
        "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
    )
    assert row_02129000["terminal_scope_resolution_plan"]["decision_type"] == (
        "selected_outlet_scope_authority_required"
    )
    assert row_02129000["terminal_scope_resolution_plan"]["next_experiment"] == (
        "confirm_selected_terminal_drainage_area_or_rebuild_claim_outlet"
    )
    assert row_02129000["terminal_scope_resolution_plan"]["fresh_locked_rerun_required"] is True
    assert row_02129000["terminal_scope_resolution_plan"][
        "temporary_terminal_metrics_allowed_as_final"
    ] is False
    assert row_02129000["terminal_scope_resolution_plan"]["all_terminal_metrics_claim_authority"] is False
    assert row_02129000["terminal_area_scope_class"] == "selected_terminal_partial_basin_all_terminal_matches"
    assert "selected_terminal_partial_nldi_area" in row_02129000["terminal_area_scope_flags"]
    assert row_02129000["usgs_site_drainage_area_km2"] == pytest.approx(17775.0884, rel=1e-6)
    assert row_02129000["terminal_authority_area_check"]["reference_area_source"] == (
        "usgs_site_drainage_area"
    )
    assert row_02129000["terminal_authority_area_check"]["class"] == (
        "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
    )
    assert "selected_terminal_partial_usgs_site_area" in row_02129000["terminal_authority_area_check"]["flags"]
    assert row_02129000["terminal_virtual_outlet_candidate"]["status"] == (
        "diagnostic_only_authority_required"
    )
    assert row_02129000["terminal_virtual_outlet_candidate"]["candidate_type"] == (
        "all_terminal_virtual_outlet"
    )
    assert row_02129000["terminal_virtual_outlet_candidate"]["claim_authority"] is False
    assert (
        row_02129000["terminal_virtual_outlet_candidate"][
            "temporary_terminal_metrics_allowed_as_final"
        ]
        is False
    )
    assert row_02129000["terminal_virtual_outlet_candidate"]["fresh_locked_rerun_required"] is True
    assert Path(row_02129000["terminal_virtual_outlet_candidate_path"]).is_file()
    assert row_02129000["terminal_outlet_conflict_class"] == (
        "selected_largest_terminal_not_nearest_minor_branch_conflict"
    )
    assert "selected_terminal_largest_flow" in row_02129000["terminal_outlet_conflict_flags"]
    assert row_02129000["terminal_outlet_conflict_claim_impact"] == (
        "terminal_scope_claim_blocked_until_hydrofabric_or_gauge_outlet_authority_resolves_conflict"
    )
    assert [
        probe.get("diagnostic")
        for probe in row_02129000.get("volume_recommended_probe_order", [])[:3]
    ] == [
        "audit_outlet_selection_against_terminal_inventory",
        "audit_selected_vs_nearest_terminal_hydrographs",
        "audit_selected_vs_all_terminal_hydrographs",
    ]
    assert audit["metrics"]["terminal_topology_overlap_rows"] == 0
    assert audit["metrics"]["required_terminal_topology_overlap_rows"] == 0
    assert audit["metrics"]["et_context_rows"] == 4
    assert audit["metrics"]["et_diagnostic_rows"] == 4
    assert audit["metrics"]["required_et_context_rows"] == 4
    assert audit["metrics"]["mass_balance_diagnostic_rows"] == 1
    assert audit["metrics"]["required_mass_balance_rows"] == 1
    assert audit["metrics"]["physical_gate_artifact_rows"] == 11
    assert audit["metrics"]["required_physical_gate_artifact_rows"] == 11
    row_01491000 = next(row for row in report["rows"] if row.get("basin") == "01491000")
    assert row_01491000["mass_balance_diagnostics_path"]
    assert Path(row_01491000["mass_balance_diagnostics_path"]).is_file()
    assert "mass_closure_residual_high" in row_01491000["mass_balance_diagnostic_flags"]
    assert row_01491000["mass_balance_recommended_probe_order"][0]["diagnostic"] == (
        "audit_basin_water_balance_closure_terms"
    )
    assert audit["metrics"]["routing_status_counts"] == {
        "passed": 5,
        "failed": 0,
        "warning": 6,
        "not_run": 0,
        "unknown": 0,
    }
    assert audit["metrics"]["primary_blocker_counts"] == {
        "BELOW_RESEARCH_SKILL": 3,
        "MASS_IMBALANCE": 1,
        "multi_terminal_volume_deficit": 4,
        "none": 1,
        "outlet_scope_volume_mismatch": 2,
    }
    row_03349000 = next(row for row in report["rows"] if row.get("basin") == "03349000")
    process_context = row_03349000["post_aggregation_process_context"]
    assert process_context["available"] is True
    assert process_context["status"] == "diagnostic_only_process_or_forcing_blocker"
    assert process_context["claim_authority"] is False
    assert process_context["temporary_metrics_allowed_as_final"] is False
    assert process_context["fresh_locked_rerun_required"] is True
    assert process_context["scope_class"] == "all_terminal_volume_deficit_persists_after_valid_aggregation"
    assert "soil_provenance_limited" in process_context["likely_process_domains"]
    assert "swat_water_yield_below_observed_runoff" in process_context["likely_process_domains"]
    process_explanations = {
        item["domain"]: item
        for item in process_context["candidate_explanations"]
    }
    assert process_explanations["soil_provenance_limited"]["status"] == "soil_provenance_degraded"
    assert process_explanations["swat_water_yield_below_observed_runoff"]["status"] == (
        "swat_water_yield_below_observed_runoff"
    )
    assert process_explanations["et_fraction_high"]["status"] == "et_fraction_high"
    assert process_explanations["subsurface_partition_low"]["status"] == "subsurface_partition_low"
    assert all(
        item["fresh_locked_rerun_required"]
        for item in process_context["candidate_explanations"]
    )
    assert "document_post_aggregation_volume_deficit_source" in process_context["required_before_claim"]
    assert checks[
        "Virtual all-terminal outlet rows retain machine-readable scope-gate evidence"
    ]["status"] == "implemented"
    assert audit["metrics"]["virtual_outlet_scope_gate_rows"] == 0
    assert audit["metrics"]["required_virtual_outlet_scope_rows"] == 0
    assert audit["implemented"] == 96
    assert audit["total"] == 97


def test_skill_bound_aware_probe_order_allows_partially_exhausted_controls() -> None:
    row = {
        "skill_recommended_probe_order": [
            {
                "diagnostic": "screen_channel_routing_attenuation_controls",
                "parameters": ["CH_N2", "CH_K2"],
                "bound_exhausted_parameters": ["CH_K2"],
                "unexhausted_parameters": ["CH_N2"],
                "bound_exhaustion_claim_impact": "deprioritized_until_bound-hit controls are structurally explained",
            },
            {
                "diagnostic": "rebalance_runoff_and_et_partition",
                "parameters": ["CN2"],
                "bound_exhausted_parameters": [],
                "unexhausted_parameters": ["CN2"],
                "bound_exhaustion_claim_impact": None,
            },
            {
                "diagnostic": "audit_surface_runoff_lag_and_peak_timing",
                "parameters": ["SURLAG"],
                "bound_exhausted_parameters": ["SURLAG"],
                "unexhausted_parameters": [],
                "bound_exhaustion_claim_impact": "deprioritized_until_bound-hit controls are structurally explained",
            },
        ]
    }

    assert _row_skill_bound_aware_probe_order_ok(row)


def test_skill_bound_aware_probe_order_rejects_fully_exhausted_first_probe() -> None:
    row = {
        "skill_recommended_probe_order": [
            {
                "diagnostic": "audit_surface_runoff_lag_and_peak_timing",
                "parameters": ["SURLAG"],
                "bound_exhausted_parameters": ["SURLAG"],
                "unexhausted_parameters": [],
                "bound_exhaustion_claim_impact": "deprioritized_until_bound-hit controls are structurally explained",
            },
            {
                "diagnostic": "rebalance_runoff_and_et_partition",
                "parameters": ["CN2"],
                "bound_exhausted_parameters": [],
                "unexhausted_parameters": ["CN2"],
                "bound_exhaustion_claim_impact": None,
            },
        ]
    }

    assert not _row_skill_bound_aware_probe_order_ok(row)


def test_objective_report_exposes_non_research_blocker_domain_classification() -> None:
    report = json.loads(Path("docs/objective_basin_validation_report.json").read_text(encoding="utf-8"))
    classification = report["non_research_blocker_classification"]
    target_eval = report["target_hypothesis_evaluation"]
    science_summary = report["science_blocker_summary"]
    improvement_plan = report["pipeline_improvement_plan"]
    assert set(classification["domain_counts"]) == {
        "engineering",
        "diagnostics",
        "calibration",
        "provenance",
        "parameter_support",
        "science",
    }
    assert classification["domain_counts"]["science"] == 4
    assert classification["domain_counts"]["engineering"] == 0
    assert classification["domain_counts"]["diagnostics"] == 4
    assert classification["domain_counts"]["provenance"] == 2
    assert classification["unclassified_blockers"] == []
    assert target_eval["target_research_grade_count"] == 7
    assert target_eval["observed_research_grade_count"] == report["research_grade_count"] == 1
    assert target_eval["status"] == "not_supported_by_current_evidence"
    assert target_eval["gate_weakening_permitted"] is False
    assert target_eval["metrics_alone_grant_research_grade"] is False
    assert target_eval["blocker_domain_counts"] == classification["domain_counts"]
    assert target_eval["pipeline_improvement_required_domains"] == ["diagnostics", "provenance"]
    assert target_eval["science_blocker_count"] == 4
    assert science_summary["status"] == "active_science_blockers"
    assert science_summary["science_blocker_count"] == 4
    assert science_summary["domain_count"] == classification["domain_counts"]["science"] == 4
    assert science_summary["gate_weakening_permitted"] is False
    assert science_summary["metrics_alone_grant_research_grade"] is False
    assert science_summary["primary_blocker_counts"] == {
        "BELOW_RESEARCH_SKILL": 3,
        "MASS_IMBALANCE": 1,
    }
    skill_item = next(
        item for item in science_summary["items"] if item["primary_blocker"] == "BELOW_RESEARCH_SKILL"
    )
    assert skill_item["pipeline_improvement_domain"] is False
    assert skill_item["basins"] == ["01493500", "01547700", "01654000"]
    skill_basin_item = next(item for item in skill_item["basin_items"] if item["basin"] == "01493500")
    assert skill_basin_item["evidence_type"] == "skill_limitation"
    assert skill_basin_item["classification"] == "snow_timing_and_peak_response"
    assert skill_basin_item["claim_authority"] is False
    assert skill_basin_item["diagnostics_path"]
    mass_item = next(
        item for item in science_summary["items"] if item["primary_blocker"] == "MASS_IMBALANCE"
    )
    mass_basin_item = mass_item["basin_items"][0]
    assert mass_basin_item["basin"] == "01491000"
    assert mass_basin_item["evidence_type"] == "mass_balance_diagnostics"
    assert mass_basin_item["first_probe"] == "audit_basin_water_balance_closure_terms"
    assert improvement_plan["version"] == 1
    assert improvement_plan["status"] == "active_non_science_pipeline_gaps"
    assert improvement_plan["domains"] == target_eval["pipeline_improvement_required_domains"]
    assert improvement_plan["gate_weakening_permitted"] is False
    assert improvement_plan["temporary_metrics_allowed_as_final"] is False
    assert [item["domain"] for item in improvement_plan["items"]] == ["diagnostics", "provenance"]
    diagnostics_item = improvement_plan["items"][0]
    assert diagnostics_item["basins"] == ["03349000", "03353000", "09504500", "12031000"]
    assert diagnostics_item["primary_blocker_counts"] == {"multi_terminal_volume_deficit": 4}
    assert [item["basin"] for item in diagnostics_item["basin_items"]] == diagnostics_item["basins"]
    assert "post_aggregation_process_context" in diagnostics_item["source_evidence_fields"]
    assert any("Volume source alternative" in item for item in diagnostics_item["representative_actions"])
    row_03349000_plan = next(item for item in diagnostics_item["basin_items"] if item["basin"] == "03349000")
    assert row_03349000_plan["next_experiment"] == (
        "diagnose_weather_et_runoff_subsurface_deficit_after_terminal_scope"
    )
    assert row_03349000_plan["claim_authority"] is False
    assert row_03349000_plan["temporary_metrics_allowed_as_final"] is False
    assert row_03349000_plan["fresh_locked_rerun_required_before_claim"] is True
    assert Path(row_03349000_plan["evidence_artifacts"]["evidence_summary"]).is_file()
    assert Path(row_03349000_plan["evidence_artifacts"]["terminal_trace"]).is_file()
    assert row_03349000_plan["first_routing_probe"]["diagnostic"] == (
        "audit_terminal_inventory_and_aggregation"
    )
    assert row_03349000_plan["decision_request"]["status"] == "diagnostic_only"
    assert row_03349000_plan["decision_request"]["recommended_option"] == (
        "repair_soil_provenance_before_parameter_attribution"
    )
    assert "soil_provenance_limited" in row_03349000_plan["decision_request"][
        "likely_process_domains"
    ]
    plan_explanations = {
        item["domain"]: item
        for item in row_03349000_plan["decision_request"]["candidate_explanations"]
    }
    assert plan_explanations["soil_provenance_limited"]["status"] == "soil_provenance_degraded"
    assert plan_explanations["swat_water_yield_below_observed_runoff"]["status"] == (
        "swat_water_yield_below_observed_runoff"
    )
    assert all(
        item["fresh_locked_rerun_required"]
        for item in row_03349000_plan["decision_request"]["candidate_explanations"]
    )
    assert {
        option["id"] for option in row_03349000_plan["decision_request"]["options"]
    } == {
        "repair_soil_provenance_before_parameter_attribution",
        "screen_pet_and_et_partition_controls",
        "screen_subsurface_partition_controls_after_soil_provenance",
        "diagnose_post_aggregation_water_balance_deficit",
        "run_source_backed_diagnostic",
        "retain_exploratory_science_blocker",
    }
    provenance_item = improvement_plan["items"][1]
    assert provenance_item["basins"] == ["01013500", "02129000"]
    assert provenance_item["primary_blocker_counts"] == {"outlet_scope_volume_mismatch": 2}
    assert [item["basin"] for item in provenance_item["basin_items"]] == provenance_item["basins"]
    assert "terminal_authority_area_check" in provenance_item["source_evidence_fields"]
    assert "terminal_virtual_outlet_candidate" in provenance_item["source_evidence_fields"]
    row_02129000_plan = next(item for item in provenance_item["basin_items"] if item["basin"] == "02129000")
    assert row_02129000_plan["next_experiment"] == (
        "confirm_selected_terminal_drainage_area_or_rebuild_claim_outlet"
    )
    assert row_02129000_plan["first_volume_probe"]["diagnostic"] == (
        "audit_outlet_selection_against_terminal_inventory"
    )
    assert Path(row_02129000_plan["evidence_artifacts"]["routing_flow_gates"]).is_file()
    assert row_02129000_plan["decision_request"]["status"] == "needs_input"
    assert row_02129000_plan["decision_request"]["question_id"] == (
        "02129000_outlet_scope_authority"
    )
    assert row_02129000_plan["decision_request"]["accepted_by_required"] == "user_or_policy"
    assert row_02129000_plan["decision_request"]["recommended_option"] == (
        "authorize_virtual_all_terminal_outlet"
    )
    assert {
        option["id"] for option in row_02129000_plan["decision_request"]["options"]
    } == {
        "confirm_selected_terminal_authority",
        "authorize_virtual_all_terminal_outlet",
        "retain_exploratory_until_outlet_rebuilt",
    }
    virtual_option = next(
        option
        for option in row_02129000_plan["decision_request"]["options"]
        if option["id"] == "authorize_virtual_all_terminal_outlet"
    )
    assert "virtual_outlet_authority" in virtual_option["requires"]
    outlet_evidence = row_02129000_plan["decision_request"]["outlet_scope_evidence"]
    assert outlet_evidence["reference_area_source"] == "usgs_site_drainage_area"
    assert outlet_evidence["authority_area_class"] == (
        "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
    )
    assert outlet_evidence["selected_fraction_of_authority_area"] < 0.90
    assert 0.90 <= outlet_evidence["all_terminal_fraction_of_authority_area"] <= 1.10
    assert outlet_evidence["virtual_all_terminal_candidate_supported"] is True
    assert outlet_evidence["virtual_candidate_status"] == "diagnostic_only_authority_required"
    assert outlet_evidence["all_terminal_aggregation_valid"] is True
    assert outlet_evidence["virtual_terminal_gis_ids"]
    assert {
        "selected_terminal_partial_authoritative_area",
        "all_terminal_matches_authoritative_area",
        "virtual_all_terminal_candidate_available",
    }.issubset(set(outlet_evidence["evidence_flags"]))
    assert {
        "document_gauge_outlet_is_represented_by_all_terminal_aggregation",
        "make_virtual_outlet_selection_explicit_in_outlet_provenance",
        "relock_benchmark_against_virtual_all_terminal_outlet",
        "rerun_clean_locked_txtinout_before_reporting_metrics",
    }.issubset(set(outlet_evidence["required_before_claim"]))
    for item in improvement_plan["items"]:
        assert "rerun a fresh locked TxtInOut after the selected blocker is repaired" in item[
            "required_before_claim"
        ]
        assert item["claim_impact"] == "diagnostic_or_provenance_plan_only_until_fresh_locked_gates_pass"
    non_research = [row for row in report["rows"] if row["tier"] != "research_grade"]
    assert len(non_research) == 10
    for row in non_research:
        assert row["blocker_domain"] in classification["domain_counts"]
        assert row["blocker_action_items"]
    row_02129000 = next(row for row in report["rows"] if row["basin"] == "02129000")
    assert row_02129000["blocker_domain"] == "provenance"
    assert any("Routing source alternative" in item for item in row_02129000["blocker_action_items"])
    row_01547700 = next(row for row in report["rows"] if row["basin"] == "01547700")
    phase_coverage = row_01547700["calibration_phase_parameter_coverage"]
    assert set(phase_coverage) == {
        "volume",
        "baseflow_subsurface",
        "peaks_timing",
        "kge_nse_finetune",
    }
    assert {"CH_N2", "CH_K2"}.issubset(set(phase_coverage["peaks_timing"]))
    assert row_01547700["calibration_phase_order"] == {
        "volume": 1,
        "baseflow_subsurface": 2,
        "peaks_timing": 3,
        "kge_nse_finetune": 4,
    }


def test_pipeline_improvement_diagnostic_decisions_require_process_context() -> None:
    entry = {"domain": "diagnostics", "basin": "03353000"}
    generic_decision = {
        "status": "diagnostic_only",
        "question_id": None,
        "decision_type": "process_or_forcing_diagnostic_selection",
        "question": "Inspect retained evidence before rerun.",
        "options": [
            {
                "id": "run_source_backed_diagnostic",
                "label": "Run source-backed diagnostic",
                "claim_impact": "diagnostic only",
                "fresh_locked_rerun_required": True,
            },
            {
                "id": "retain_exploratory_science_blocker",
                "label": "Retain exploratory blocker",
                "claim_impact": "no claim promotion",
                "fresh_locked_rerun_required": False,
            },
        ],
        "recommended_option": "run_source_backed_diagnostic",
        "accepted_by_required": "agent_or_policy",
        "claim_impact": "diagnostic_plan_only_until_package_repair_and_fresh_locked_gates_pass",
    }

    assert not _pipeline_improvement_decision_request_ok(generic_decision, entry)


def test_objective_report_prioritizes_terminal_scope_before_parameter_screens() -> None:
    report = json.loads(Path("docs/objective_basin_validation_report.json").read_text(encoding="utf-8"))
    rows = [
        row
        for row in report["rows"]
        if row.get("primary_blocker") in {
            "multi_terminal_volume_deficit",
            "outlet_scope_volume_mismatch",
            "terminal_topology_overlap",
        }
    ]

    assert {row["basin"] for row in rows} == {
        "03349000",
        "01013500",
        "02129000",
        "03353000",
        "12031000",
        "09504500",
    }
    for row in rows:
        diagnostics = [probe.get("diagnostic") for probe in row.get("volume_recommended_probe_order", [])]
        routing_diagnostics = [probe.get("diagnostic") for probe in row.get("routing_recommended_probe_order", [])]
        if diagnostics:
            assert diagnostics[0] == "audit_outlet_selection_against_terminal_inventory"
            assert "audit_selected_vs_all_terminal_hydrographs" in diagnostics[:3]
            if row.get("primary_blocker") == "terminal_topology_overlap":
                assert diagnostics[1] == "audit_terminal_topology_overlap_before_aggregation"
        else:
            expected_first = (
                "audit_selected_terminal_against_nearest_gauge_terminal"
                if row.get("selected_outlet_is_nearest_terminal") is False
                else "audit_terminal_inventory_and_aggregation"
            )
            assert routing_diagnostics[0] == expected_first
            assert "audit_terminal_inventory_and_aggregation" in routing_diagnostics[:2]


def test_objective_summary_derives_terminal_scope_blocker_from_routing_scope(tmp_path: Path) -> None:
    routing_gates = tmp_path / "routing_flow_gates.json"
    routing_gates.write_text(
        json.dumps(
            {
                "status": "warning",
                "closure_status": "fail_mass_closure",
                "flags": [
                    "multiple_terminal_outlets_present",
                    "selected_terminal_partial_of_all_terminal_flow",
                    "all_terminal_routed_to_channel_reference_matches",
                ],
                "selected_terminal_fraction_of_all_terminal_flow": 0.52,
                "all_terminal_routed_to_channel_closure_ratio": 1.01,
                "terminal_outlet_count": 4,
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence_summary.json"
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "gates_passed": ["contract_policy", "fresh_engine_output", "benchmark_lock"],
                "gates_failed": ["physical_gates", "routing_flow"],
                "values": {
                    "fresh_engine_run": True,
                    "warmup_years": 3,
                    "physical_gates_status": "failed",
                    "physical_condition_codes": ["BELOW_RESEARCH_SKILL"],
                    "physical_dominant_blocker": "BELOW_RESEARCH_SKILL",
                    "routing_flow_gates_status": "warning",
                    "routing_flow_closure_status": "fail_mass_closure",
                    "routing_flow_gates_path": str(routing_gates),
                    "metrics": {"kge": 0.1, "nse": 0.02, "pbias": -8.0},
                },
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("01654000", evidence)

    assert row.terminal_scope_blocker == "outlet_scope_volume_mismatch"
    assert row.routing_flow_diagnostic_flags == [
        "multiple_terminal_outlets_present",
        "selected_terminal_partial_of_all_terminal_flow",
        "all_terminal_routed_to_channel_reference_matches",
    ]


def test_objective_summary_promotes_virtual_outlet_scope_gate(tmp_path: Path) -> None:
    routing_gates = tmp_path / "routing_flow_gates.json"
    routing_gates.write_text(
        json.dumps(
            {
                "status": "passed",
                "closure_status": "pass",
                "terminal_outlet_count": 2,
                "all_terminal_routed_to_channel_closure_ratio": 1.0,
                "all_terminal_mass_closure_ratio": 1.0,
                "all_terminal_outflow_m3": 100.0,
                "virtual_outlet_scope_gate": {
                    "applicable": True,
                    "status": "passed",
                    "passed": True,
                    "reason": "virtual all-terminal outlet scope passed",
                    "blockers": [],
                    "selected_outlet_gis_ids": [7, 8],
                },
                "virtual_outlet_scope_gate_status": "passed",
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence_summary.json"
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "diagnostic",
                "gates_passed": ["contract_policy", "fresh_engine_output", "benchmark_lock", "routing_flow"],
                "gates_failed": [],
                "values": {
                    "fresh_engine_run": True,
                    "warmup_years": 3,
                    "outlet_scope": "virtual_all_terminal",
                    "outlet_policy": "all_terminal_sum",
                    "selected_outlet_gis_ids": [7, 8],
                    "virtual_outlet_authority": "official_site_area_matches_all_terminal_candidate",
                    "virtual_outlet_claim_authority": True,
                    "virtual_outlet_scope_gate_status": "passed",
                    "routing_flow_gates_status": "passed",
                    "routing_flow_closure_status": "pass",
                    "routing_flow_gates_path": str(routing_gates),
                    "metrics": {"kge": 0.45, "nse": 0.1, "pbias": 10.0},
                },
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("01013500", evidence)

    assert row.outlet_scope == "virtual_all_terminal"
    assert row.outlet_policy == "all_terminal_sum"
    assert row.selected_outlet_gis_ids == [7, 8]
    assert row.virtual_outlet_authority == "official_site_area_matches_all_terminal_candidate"
    assert row.virtual_outlet_claim_authority is True
    assert row.virtual_outlet_scope_gate_status == "passed"
    assert row.virtual_outlet_scope_gate["passed"] is True
    assert row.virtual_outlet_scope_gate_blockers == []


def test_objective_suite_help_does_not_launch_workflows(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "summarize-existing" in help_text
    assert "resume-existing" in help_text
    assert "evidence-override" in help_text


def test_objective_suite_classifies_promotion_gate_failures_as_blocked(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "gates_passed": ["contract_policy", "fresh_engine_output", "benchmark_lock"],
                "gates_failed": ["physical_gates", "calibration_verification"],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "physical_gates_status": "failed",
                    "routing_flow_gates_status": "passed",
                    "routing_flow_closure_status": "pass",
                    "calibration_attempted": True,
                    "calibration_success": False,
                    "calibration_status": "attempted_failed_or_blocked",
                    "calibration_phases": [
                        {"phase": "volume", "status": "passed", "message": "volume ok"},
                        {
                            "phase": "kge_nse_finetune",
                            "status": "failed",
                            "message": (
                                "No calibration candidate passed the promotion gates "
                                "during phase 'kge_nse_finetune'."
                            ),
                        },
                    ],
                    "calibration_provenance": {
                        "final_metrics_authority": "none",
                        "temporary_candidate_metrics_allowed_as_final": False,
                        "history_csv": "calibration/calibration_reports_locked/history.csv",
                        "n_evaluations": 12,
                        "promotion_gate": {"nse": 0.0, "kge": 0.4, "pbias_abs_pct": 30.0},
                        "error": (
                            "No calibration candidate passed the promotion gates "
                            "during phase 'kge_nse_finetune'."
                        )
                    },
                    "metrics": {"kge": 0.1, "nse": -0.09, "pbias": -31.0},
                },
            }
        ),
        encoding="utf-8",
    )
    history = tmp_path / "calibration" / "calibration_reports_locked" / "history.csv"
    history.parent.mkdir(parents=True)
    history.write_text(
        "eval_idx,phase,phase_order,phase_parameters,metric_nse,metric_kge,metric_pbias,"
        "volume_gate_passed,physical_gate_passed,"
        "metric_selected_terminal_fraction_of_all_terminal_flow,metric_selected_terminal_nse,"
        "metric_selected_terminal_kge,metric_selected_terminal_pbias,metric_all_terminal_nse,"
        "metric_all_terminal_kge,metric_all_terminal_pbias,metric_all_terminal_volume_gate_passes_diagnostic,"
        "calibration_process_gate_passed,calibration_process_condition_codes,"
        "physical_gate_condition_codes,physical_gate_dominant_blocker,param_CN2,param_ESCO\n"
        "0,volume,1,\"CN2,ESCO\",-0.20,0.10,-45.0,False,False,0.40,-0.20,0.10,-45.0,-0.10,0.20,-25.0,True,False,VOLUME_BIAS,VOLUME_BIAS,VOLUME_BIAS,75,0.95\n"
        "1,kge_nse_finetune,4,\"CN2,ESCO\",0.05,0.30,-12.5,True,False,0.42,0.05,0.30,-12.5,0.20,0.45,-5.0,True,True,,BELOW_RESEARCH_SKILL,BELOW_RESEARCH_SKILL,98,0.01\n",
        encoding="utf-8",
    )

    row = summarize_evidence("01491000", evidence)

    assert row.calibration == "blocked_by_promotion_gate"
    assert row.calibration_failure_phase == "kge_nse_finetune"
    assert row.calibration_final_metrics_authority == "none"
    assert row.temporary_candidate_metrics_allowed_as_final is False
    assert "promotion gates" in str(row.calibration_failure_message)
    assert row.calibration_failure_history_csv == "calibration/calibration_reports_locked/history.csv"
    assert row.calibration_failure_n_evaluations == 12
    assert row.calibration_failure_promotion_gate == {"nse": 0.0, "kge": 0.4, "pbias_abs_pct": 30.0}
    assert row.calibration_failure_volume_gate_pass_count == 1
    assert row.calibration_failure_physical_gate_pass_count == 0
    assert row.calibration_failure_process_gate_pass_count == 1
    assert row.calibration_failure_best_phase == "kge_nse_finetune"
    assert row.calibration_failure_best_abs_pbias == 12.5
    assert row.calibration_failure_best_pbias == -12.5
    assert row.calibration_failure_best_kge == 0.30
    assert row.calibration_failure_best_nse == 0.05
    assert row.calibration_failure_best_parameters == {"CN2": 98.0, "ESCO": 0.01}
    assert set(row.calibration_failure_skill_tradeoff_frontier) == {
        "best_abs_pbias",
        "best_kge",
        "best_nse",
    }
    assert row.calibration_failure_skill_tradeoff_frontier["best_abs_pbias"]["metrics"] == {
        "kge": 0.30,
        "nse": 0.05,
        "pbias": -12.5,
    }
    assert row.calibration_failure_skill_tradeoff_frontier["best_abs_pbias"]["diagnostic_only"] is True
    assert row.calibration_failure_skill_tradeoff_frontier["best_abs_pbias"]["parameters"] == {
        "CN2": 98.0,
        "ESCO": 0.01,
    }
    terminal_scope = row.calibration_failure_skill_tradeoff_frontier["best_abs_pbias"][
        "terminal_scope_metrics"
    ]
    assert terminal_scope["selected_terminal_fraction_of_all_terminal_flow"] == 0.42
    assert terminal_scope["selected_terminal"]["pbias"] == -12.5
    assert terminal_scope["all_terminal"]["pbias"] == -5.0
    assert terminal_scope["all_terminal"]["volume_gate_passes_diagnostic"] is True
    assert terminal_scope["claim_impact"] == "diagnostic_only_not_final_claim_evidence"
    assert row.calibration_failure_best_parameter_bound_hits["CN2"]["boundary"] == "upper"
    assert row.calibration_failure_best_parameter_bound_hits["ESCO"]["boundary"] == "lower"
    assert row.calibration_failure_best_parameter_bound_context["all_known_parameters_at_bounds"] is True
    assert row.calibration_failure_physical_condition_code_counts == {
        "VOLUME_BIAS": 1,
        "BELOW_RESEARCH_SKILL": 1,
    }
    assert row.calibration_failure_physical_dominant_blocker_counts == {
        "VOLUME_BIAS": 1,
        "BELOW_RESEARCH_SKILL": 1,
    }
    assert row.calibration_failure_process_condition_code_counts == {
        "VOLUME_BIAS": 1,
    }
    assert row.calibration_phase_parameter_coverage == {
        "kge_nse_finetune": ["CN2", "ESCO"],
        "volume": ["CN2", "ESCO"],
    }
    assert row.calibration_phase_evaluation_counts == {
        "volume": 1,
        "kge_nse_finetune": 1,
    }
    assert row.calibration_phase_order == {"volume": 1, "kge_nse_finetune": 4}
    assert row.calibration_phase_volume_gate_pass_counts == {"kge_nse_finetune": 1}
    assert row.calibration_phase_physical_gate_pass_counts == {}
    assert row.calibration_phase_process_gate_pass_counts == {"kge_nse_finetune": 1}

    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    write_outputs([row], report_md, report_json)
    report_text = report_md.read_text(encoding="utf-8")
    assert "Calibration search: phase=kge_nse_finetune" in report_text
    assert "temporary_candidate_metrics_allowed_as_final=False" in report_text
    assert "calibration history summary" in report_text
    assert "calibration phase coverage" in report_text
    assert "calibration best failed parameters" in report_text
    assert "calibration best failed parameter bound hits" in report_text
    assert "calibration skill/volume tradeoff frontier" in report_text
    assert "process-pass candidates `1`" in report_text
    assert "calibration candidate process blockers" in report_text


def test_objective_suite_surfaces_skill_volume_near_miss_candidates(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "gates_passed": ["contract_policy", "fresh_engine_output", "benchmark_lock"],
                "gates_failed": ["physical_gates", "calibration_verification"],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "physical_gates_status": "failed",
                    "routing_flow_gates_status": "warning",
                    "routing_flow_closure_status": "fail_mass_closure",
                    "calibration_attempted": True,
                    "calibration_success": False,
                    "calibration_status": "attempted_failed_or_blocked",
                    "calibration_provenance": {
                        "final_metrics_authority": "none",
                        "temporary_candidate_metrics_allowed_as_final": False,
                        "history_csv": "calibration/calibration_reports_locked/history.csv",
                        "n_evaluations": 4,
                        "promotion_gate": {"nse": 0.0, "kge": 0.4, "pbias_abs_pct": 30.0},
                        "error": "No calibration candidate passed the promotion gates during phase 'volume'.",
                    },
                    "metrics": {"kge": -0.01, "nse": 0.12, "pbias": -69.8},
                },
            }
        ),
        encoding="utf-8",
    )
    history = tmp_path / "calibration" / "calibration_reports_locked" / "history.csv"
    history.parent.mkdir(parents=True)
    history.write_text(
        "eval_idx,phase,metric_nse,metric_kge,metric_pbias,volume_gate_passed,physical_gate_passed,"
        "param_CN2,param_SURLAG,param_ESCO\n"
        "0,volume,0.20,0.30,-45.0,False,False,75,4,0.95\n"
        "1,volume,0.48,0.42,-34.5,False,False,98,24,0.01\n"
        "2,kge_nse_finetune,0.10,0.45,-50.0,False,False,80,12,0.2\n",
        encoding="utf-8",
    )

    row = summarize_evidence("03353000", evidence)

    assert row.calibration_failure_skill_volume_near_miss is True
    assert row.calibration_failure_near_miss_phase == "volume"
    assert row.calibration_failure_near_miss_kge == 0.42
    assert row.calibration_failure_near_miss_nse == 0.48
    assert row.calibration_failure_near_miss_pbias == -34.5
    assert row.calibration_failure_near_miss_parameters == {
        "CN2": 98.0,
        "SURLAG": 24.0,
        "ESCO": 0.01,
    }
    assert row.calibration_failure_best_parameters == {
        "CN2": 98.0,
        "SURLAG": 24.0,
        "ESCO": 0.01,
    }
    assert row.calibration_failure_best_parameter_bound_hits["CN2"]["boundary"] == "upper"
    assert row.calibration_failure_best_parameter_bound_hits["SURLAG"]["boundary"] == "upper"
    assert row.calibration_failure_best_parameter_bound_hits["ESCO"]["boundary"] == "lower"
    assert row.calibration_failure_skill_tradeoff_frontier["best_kge"]["metrics"] == {
        "kge": 0.45,
        "nse": 0.10,
        "pbias": -50.0,
    }
    assert row.calibration_failure_skill_tradeoff_frontier["best_nse"]["metrics"] == {
        "kge": 0.42,
        "nse": 0.48,
        "pbias": -34.5,
    }
    assert row.calibration_failure_skill_tradeoff_frontier["best_abs_pbias"]["metrics"] == {
        "kge": 0.42,
        "nse": 0.48,
        "pbias": -34.5,
    }

    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    write_outputs([row], report_md, report_json)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["rows"][0]["calibration_failure_skill_volume_near_miss"] is True
    assert set(report["rows"][0]["calibration_failure_skill_tradeoff_frontier"]) == {
        "best_abs_pbias",
        "best_kge",
        "best_nse",
    }
    report_text = report_md.read_text(encoding="utf-8")
    assert "calibration near-miss candidate" in report_text
    assert "calibration skill/volume tradeoff frontier" in report_text
    assert "Calibration near miss: candidate met KGE/NSE skill thresholds" in report_text
    assert "Calibration tradeoff frontier" in report_text


def test_objective_suite_summary_preserves_gate_and_diagnostic_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    physical_gates.write_text(
        json.dumps(
            {
                "status": "failed",
                "condition_codes": ["VOLUME_BIAS", "ET_DOMINATED", "NEGATIVE_SKILL"],
                "dominant_blocker": "VOLUME_BIAS",
            }
        ),
        encoding="utf-8",
    )
    volume_diag = tmp_path / "reports" / "volume_bias_diagnostics.json"
    volume_diag.parent.mkdir(parents=True)
    volume_diag.write_text(
        json.dumps(
            {
                "diagnostic_flags": [
                    {"code": "simulated_volume_excess", "evidence": "PBIAS=78.2%"},
                    {"code": "surface_runoff_partition_high", "evidence": "surq/P=0.7"},
                ],
                "next_actions": ["Audit runoff generation before calibration."],
                "source_backed_alternatives": [
                    {
                        "option": "audit_curve_number_and_landuse_soil_mapping",
                        "parameters": ["CN2"],
                        "claim_impact": "diagnostic_only",
                    }
                ],
                "recommended_probe_order": [
                    {
                        "diagnostic": "audit_curve_number_and_landuse_soil_mapping",
                        "parameters": ["CN2"],
                    }
                ],
                "terminal_hydrograph_scope": {
                    "available": True,
                    "diagnostic_only": True,
                    "claim_impact": (
                        "outlet_and_routing_claims_remain_blocked_until_selected_terminal_scope_is_explained"
                    ),
                    "observed_path": str(tmp_path / "outputs" / "obs_q.csv"),
                    "sim_source_path": str(tmp_path / "channel_sd_day.txt"),
                    "terminal_ids": [1, 3],
                    "selected_outlet_gis_id": 1,
                    "selected_terminal": {
                        "available": True,
                        "n_days": 365,
                        "pbias_pct": -60.0,
                        "nse": -0.1,
                        "kge": 0.2,
                        "sim_to_obs_volume_ratio": 0.4,
                    },
                    "all_terminal": {
                        "available": True,
                        "n_days": 365,
                        "pbias_pct": -12.0,
                        "nse": -0.2,
                        "kge": 0.1,
                        "sim_to_obs_volume_ratio": 0.88,
                    },
                    "pbias_abs_improvement_pct_points": 48.0,
                },
                "terminal_scope_blocker": "outlet_scope_volume_mismatch",
                "post_aggregation_process_context": {
                    "available": True,
                    "status": "sidecar_fallback_should_not_override_values",
                    "claim_authority": False,
                    "likely_process_domains": ["sidecar_fallback"],
                    "recommended_focus": ["Use evidence_summary values first."],
                },
            }
        ),
        encoding="utf-8",
    )
    et_diag = tmp_path / "reports" / "et_partition_diagnostics.json"
    et_diag.write_text(
        json.dumps(
            {
                "diagnostic_flags": [
                    {"code": "et_to_precip_high", "evidence": "ET/P=0.78"},
                    {"code": "soil_evaporation_dominates_et", "evidence": "Esoil/ET=0.73"},
                ],
                "next_actions": ["Run a basin-specific PET_CO/ESCO/EPCO sensitivity probe."],
                "source_backed_alternatives": [
                    {
                        "option": "audit_pet_forcing_or_pet_method",
                        "parameters": ["PET_CO"],
                        "claim_impact": "diagnostic_only",
                    },
                    {
                        "option": "screen_soil_evaporation_compensation",
                        "parameters": ["ESCO"],
                        "claim_impact": "diagnostic_only",
                    },
                ],
                "recommended_probe_order": [
                    {"parameters": ["PET_CO"], "basis": "audit_pet_forcing_or_pet_method"},
                    {"parameters": ["ESCO"], "basis": "screen_soil_evaporation_compensation"},
                ],
            }
        ),
        encoding="utf-8",
    )
    routing_gates = tmp_path / "routing_flow_gates.json"
    terminal_trace = tmp_path / "reports" / "routing" / "terminal_trace.json"
    terminal_trace.parent.mkdir(parents=True)
    terminal_trace.write_text(
        json.dumps(
            {
                "failure_class": "generated_topology_mismatch",
                "missing_terminal_gis_ids": [3],
                "orphan_terminal_gis_ids": [3],
                "material_missing_terminal_gis_ids": [],
                "missing_terminal_upstream_area_km2": 0.0,
                "basin_nldi_area_km2": 100.0,
                "delineated_area_km2": 90.0,
                "selected_terminal_upstream_area_km2": 40.0,
                "all_terminal_upstream_area_km2": 90.0,
                "selected_terminal_fraction_of_nldi_area": 0.40,
                "all_terminal_fraction_of_nldi_area": 0.90,
                "delineated_fraction_of_nldi_area": 0.90,
                "selected_terminal_fraction_of_delineated_area": 0.4444444444,
                "all_terminal_fraction_of_delineated_area": 1.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mass_trace = tmp_path / "reports" / "routing" / "mass_trace.json"
    mass_trace.write_text(
        json.dumps(
            {
                "flags": ["terminal_outflow_not_consistent_with_basin_wateryld"],
                "source_backed_alternatives": [
                    {
                        "option": "audit_terminal_inventory_and_aggregation",
                        "required_artifacts": ["routing_graph.graphml", "chandeg.con"],
                        "claim_impact": "research_grade_blocked",
                    }
                ],
                "recommended_probe_order": [
                    {
                        "diagnostic": "audit_terminal_inventory_and_aggregation",
                        "required_artifacts": ["routing_graph.graphml", "chandeg.con"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    routing_gates.write_text(
        json.dumps(
            {
                "closure_status": "fail_hru_to_channel",
                "flags": ["terminal_outflow_not_consistent_with_basin_wateryld"],
                "json_path": str(mass_trace),
                "terminal_trace_path": str(terminal_trace),
                "terminal_failure_class": "generated_topology_mismatch",
                "routed_to_channel_closure_ratio": 0.83,
                "all_terminal_routed_to_channel_closure_ratio": 0.97,
                "all_terminal_mass_closure_ratio": 1.94,
                "selected_terminal_fraction_of_all_terminal_flow": 0.42,
            }
        ),
        encoding="utf-8",
    )
    run_config = tmp_path / "run_config.json"
    run_config.write_text(
        json.dumps(
            {
                "build": {
                    "success": False,
                    "message": "Soil realism gate failed: 100% fallback soils.",
                }
            }
        ),
        encoding="utf-8",
    )
    hydrograph_dir = tmp_path / "calibration" / "hydrograph_comparison"
    hydrograph_dir.mkdir(parents=True)
    hydrograph_plot = hydrograph_dir / "hydrograph_calibrated_vs_observed.png"
    hydrograph_plot_pdf = hydrograph_dir / "hydrograph_calibrated_vs_observed.pdf"
    hydrograph_overlay_plot = hydrograph_dir / "hydrograph_observed_simulated_calibrated.png"
    hydrograph_overlay_plot_pdf = hydrograph_dir / "hydrograph_observed_simulated_calibrated.pdf"
    hydrograph_metrics = hydrograph_dir / "hydrograph_comparison_metrics.json"
    hydrograph_plot.write_bytes(b"png")
    hydrograph_plot_pdf.write_bytes(b"pdf")
    hydrograph_overlay_plot.write_bytes(b"png")
    hydrograph_overlay_plot_pdf.write_bytes(b"pdf")
    hydrograph_metrics.write_text('{"calibrated_kge":0.4}\n', encoding="utf-8")
    skill_dir = tmp_path / "calibration" / "skill_diagnostics"
    skill_dir.mkdir(parents=True)
    skill_json = skill_dir / "skill_diagnostics.json"
    skill_md = skill_dir / "skill_diagnostics.md"
    channel_screen_dir = tmp_path / "calibration" / "channel_routing_screen" / "sensitivity_screen_locked"
    channel_screen_dir.mkdir(parents=True)
    channel_screen_json = channel_screen_dir / "sensitivity_screen.json"
    channel_screen_md = channel_screen_dir / "sensitivity_screen.md"
    channel_calibration_dir = tmp_path / "calibration" / "channel_routing_calibration"
    channel_calibration_reports = channel_calibration_dir / "calibration_reports_locked"
    channel_calibration_reports.mkdir(parents=True)
    channel_calibration_verification = channel_calibration_dir / "verification_summary.json"
    channel_calibration_best = channel_calibration_reports / "best_solution.json"
    skill_json.write_text(
        json.dumps(
            {
                "diagnostic_flags": [
                    {
                        "symptom": "Snow timing mismatch",
                        "evidence_metrics": {
                            "method": "annual_peak_local_window",
                            "median_lag_days": 2.0,
                            "event_count": 8,
                        },
                        "parameter_governance": {
                            "unsupported_parameters": ["SFTMP", "SMTMP"],
                            "blocked_parameters": [],
                        },
                    },
                    {
                        "symptom": "Groundwater recession mismatch",
                        "evidence_metrics": {
                            "method": "observed_top_decile_days",
                            "top_decile_sim_obs_flow_ratio": 0.42,
                            "top_decile_day_count": 36,
                        },
                        "parameter_bound_context": {
                            "calibrated_values": {"LAT_TTIME": 60.0},
                            "bound_hits": {
                                "LAT_TTIME": {
                                    "value": 60.0,
                                    "min": 0.0,
                                    "max": 60.0,
                                    "boundary": "upper",
                                }
                            },
                            "untuned_suggested_parameters": [],
                            "all_tuned_suggested_parameters_at_bounds": True,
                        },
                        "parameter_governance": {
                            "unsupported_parameters": [],
                            "blocked_parameters": ["GWQMN"],
                        },
                    },
                ],
                "next_actions": [
                    "Unsupported process-control blocker: do not tune SFTMP, SMTMP."
                ],
                "source_backed_alternatives": [
                    {
                        "option": "replace_legacy_gw_delay_advice_with_supported_alpha_and_partition_controls",
                        "parameters": ["ALPHA_BF", "LATQ_CO", "PERCO", "RCHG_DP"],
                        "blocked_parameters": ["GW_DELAY"],
                        "claim_impact": "do not tune GW_DELAY in current full-mode bridge",
                    }
                ],
                "recommended_probe_order": [
                    {
                        "rank": 1,
                        "diagnostic": "replace_legacy_gw_delay_advice_with_supported_alpha_and_partition_controls",
                        "parameters": ["ALPHA_BF", "LATQ_CO", "PERCO", "RCHG_DP"],
                        "blocked_parameters": ["GW_DELAY"],
                    }
                ],
                "calibrated_parameter_values": {"LAT_TTIME": 60.0},
                "calibrated_parameter_bound_hits": {
                    "LAT_TTIME": {
                        "value": 60.0,
                        "min": 0.0,
                        "max": 60.0,
                        "boundary": "upper",
                    }
                },
                "parameter_bound_claim_impact": (
                    "diagnostic_only_until_bound-hit controls are structurally explained"
                ),
            }
        ),
        encoding="utf-8",
    )
    skill_md.write_text("# Skill diagnostics\n", encoding="utf-8")
    channel_screen_json.write_text(
        json.dumps(
            {
                "basin_id": "01654000",
                "basis": "basin_specific",
                "parameters": [
                    {
                        "parameter": "CH_N2",
                        "activity_class": "weak",
                        "evidence": {
                            "effect_size": 0.0027,
                            "best_score_bound": "lower",
                            "best_score_value": 0.014,
                            "best_score_delta": 0.001,
                            "tested": True,
                        },
                    },
                    {
                        "parameter": "CH_K2",
                        "activity_class": "dead",
                        "evidence": {
                            "effect_size": 0.0,
                            "best_score_bound": "upper",
                            "best_score_value": 500.0,
                            "best_score_delta": 0.0,
                            "tested": True,
                        },
                    },
                ],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    channel_screen_md.write_text("# Locked Sensitivity Screen\n", encoding="utf-8")
    channel_calibration_verification.write_text(
        json.dumps(
            {
                "verified_nse": 0.03224760515404368,
                "verified_kge": 0.07447705993949605,
                "verified_pbias": -8.814999848382264,
                "delta_nse": 0.0014744570396475476,
                "delta_kge": 0.004936885876811181,
                "improved": True,
                "fresh_outputs": True,
            }
        ),
        encoding="utf-8",
    )
    channel_calibration_best.write_text(
        json.dumps({"parameters": {"CH_K2": 0.0}}),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "blocker_class": None,
                "gates_passed": ["contract_policy", "fresh_engine_output", "benchmark_lock"],
                "gates_failed": ["physical_gates", "calibration_verification"],
                "allowed_claims": [{"claim": "workflow_execution_trace_available"}],
                "blocked_claims": [{"claim": "physical_gate_claim"}],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "physical_gates_status": "failed",
                    "routing_flow_gates_status": "failed",
                    "routing_flow_closure_status": "fail_hru_to_channel",
                    "routing_flow_gates_path": str(routing_gates),
                    "calibration_attempted": False,
                    "calibration_success": False,
                    "calibration_status": "blocked_by_physical_gates",
                    "physical_gates_path": str(physical_gates),
                    "metrics": {"kge": -0.1, "nse": -0.4, "pbias": 78.2},
                    "baseline_metrics": {"kge": -0.2, "nse": -0.5, "pbias": 88.2},
                    "calibration_delta_metrics": {"kge": 0.1, "nse": 0.1, "pbias": -10.0},
                    "volume_bias_primary_issue": "simulated_volume_excess",
                    "sensitivity_screen_basis": "basin_specific",
                    "sensitivity_screen_activity_classes": {"CN2": "active", "PERCO": "weak"},
                    "sensitivity_screen_context_flags": ["cn2_runtime_cn_table_scope_required"],
                    "sensitivity_screen_effective_activity_classes": {"CN2": "active"},
                    "soil_mode": "fallback",
                    "soil_provenance_mode": "diagnostic_constant",
                    "pct_fallback_soils": 1.0,
                    "soil_overlay_gap_fraction": 0.75,
                    "calibration_provenance_path": "calibration_provenance.json",
                    "hydrograph_comparison_status": "written",
                    "hydrograph_comparison_plot": str(hydrograph_plot),
                    "hydrograph_comparison_plot_pdf": str(hydrograph_plot_pdf),
                    "hydrograph_observed_simulated_calibrated_plot": str(hydrograph_overlay_plot),
                    "hydrograph_observed_simulated_calibrated_plot_pdf": str(hydrograph_overlay_plot_pdf),
                    "hydrograph_comparison_metrics": str(hydrograph_metrics),
                    "volume_bias_diagnostics_path": str(volume_diag),
                    "et_partition_diagnostics_path": str(et_diag),
                    "post_aggregation_process_context": {
                        "available": True,
                        "status": "diagnostic_only_process_or_forcing_blocker",
                        "claim_authority": False,
                        "temporary_metrics_allowed_as_final": False,
                        "fresh_locked_rerun_required": True,
                        "likely_process_domains": ["swat_water_yield_below_observed_runoff"],
                        "recommended_focus": [
                            "Use process context only to choose the next locked rerun."
                        ],
                    },
                    "build_diagnostic_artifacts": {
                        "overlay_repair_report": "reports/overlay_repair/overlay_repair_report.json"
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("01654000", evidence, area_km2=62.0)

    assert row.tier == "exploratory"
    assert row.physical_gates == "failed"
    assert row.routing_flow_gates == "failed"
    assert row.routing_flow_closure_status == "fail_hru_to_channel"
    assert row.routing_flow_gates_path == str(routing_gates)
    assert row.routing_flow_diagnostic_flags == ["terminal_outflow_not_consistent_with_basin_wateryld"]
    assert row.routed_to_channel_closure_ratio == 0.83
    assert row.all_terminal_routed_to_channel_closure_ratio == 0.97
    assert row.all_terminal_mass_closure_ratio == 1.94
    assert row.selected_terminal_fraction_of_all_terminal_flow == 0.42
    assert row.routing_source_backed_alternatives[0]["option"] == "audit_terminal_inventory_and_aggregation"
    assert row.routing_recommended_probe_order[0]["diagnostic"] == "audit_terminal_inventory_and_aggregation"
    assert row.terminal_trace_path == str(terminal_trace)
    assert row.terminal_failure_class == "generated_topology_mismatch"
    assert row.missing_terminal_gis_ids == [3]
    assert row.orphan_terminal_gis_ids == [3]
    assert row.material_missing_terminal_gis_ids == []
    assert row.missing_terminal_upstream_area_km2 == 0.0
    assert row.terminal_basin_nldi_area_km2 == 100.0
    assert row.terminal_delineated_area_km2 == 90.0
    assert row.selected_terminal_upstream_area_km2 == 40.0
    assert row.all_terminal_upstream_area_km2 == 90.0
    assert row.selected_terminal_fraction_of_nldi_area == 0.40
    assert row.all_terminal_fraction_of_nldi_area == 0.90
    assert row.delineated_fraction_of_nldi_area == 0.90
    assert row.selected_terminal_fraction_of_delineated_area == 0.4444444444
    assert row.all_terminal_fraction_of_delineated_area == 1.0
    assert row.calibration == "blocked_by_physical_gates"
    assert row.pbias == 78.2
    assert row.baseline_pbias == 88.2
    assert row.delta_kge == 0.1
    assert row.delta_nse == 0.1
    assert row.delta_pbias == -10.0
    assert row.gates_failed == [
        "physical_gates",
        "calibration_verification",
        "soil_fidelity",
        "routing_flow",
    ]
    assert row.physical_condition_codes == ["VOLUME_BIAS", "ET_DOMINATED", "NEGATIVE_SKILL"]
    assert row.physical_dominant_blocker == "VOLUME_BIAS"
    assert row.soil_mode == "fallback"
    assert row.soil_provenance_mode == "diagnostic_constant"
    assert row.pct_fallback_soils == 1.0
    assert row.soil_overlay_gap_fraction == 0.75
    assert row.primary_blocker == "simulated_volume_excess"
    assert row.build_message == "Soil realism gate failed: 100% fallback soils."
    assert row.run_config_path == str(run_config)
    assert row.volume_bias_primary_issue == "simulated_volume_excess"
    assert row.volume_bias_diagnostic_flags == [
        "simulated_volume_excess",
        "surface_runoff_partition_high",
    ]
    assert row.volume_bias_next_actions == ["Audit runoff generation before calibration."]
    assert row.volume_source_backed_alternatives[0]["option"] == "audit_curve_number_and_landuse_soil_mapping"
    assert row.volume_recommended_probe_order[0]["diagnostic"] == "audit_curve_number_and_landuse_soil_mapping"
    assert row.terminal_hydrograph_scope["diagnostic_only"] is True
    assert row.terminal_hydrograph_scope["selected_terminal"]["pbias_pct"] == -60.0
    assert row.terminal_hydrograph_scope["all_terminal"]["pbias_pct"] == -12.0
    assert row.terminal_scope_blocker == "outlet_scope_volume_mismatch"
    assert row.post_aggregation_process_context["status"] == (
        "diagnostic_only_process_or_forcing_blocker"
    )
    assert row.post_aggregation_process_context["claim_authority"] is False
    assert row.post_aggregation_process_context["temporary_metrics_allowed_as_final"] is False
    assert row.post_aggregation_process_context["fresh_locked_rerun_required"] is True
    assert row.post_aggregation_process_context["likely_process_domains"] == [
        "swat_water_yield_below_observed_runoff"
    ]
    assert row.allowed_claim_names == ["workflow_execution_trace_available"]
    assert row.blocked_claim_names == ["physical_gate_claim", "terminal_scope_claim"]
    assert row.et_partition_diagnostic_flags == [
        "et_to_precip_high",
        "soil_evaporation_dominates_et",
    ]
    assert row.et_partition_next_actions == ["Run a basin-specific PET_CO/ESCO/EPCO sensitivity probe."]
    assert row.et_source_backed_alternatives[0]["option"] == "audit_pet_forcing_or_pet_method"
    assert row.et_recommended_probe_order[0]["parameters"] == ["PET_CO"]
    assert row.sensitivity_screen_basis == "basin_specific"
    assert row.sensitivity_activity_classes == {"CN2": "active", "PERCO": "weak"}
    assert row.sensitivity_effective_classes == {
        "CN2": "active",
        "PERCO": "weak",
        "PET_CO": "requires_basin_screen",
        "ESCO": "requires_basin_screen",
        "EPCO": "requires_basin_screen",
    }
    assert row.hydrograph_comparison_status == "written"
    assert row.hydrograph_comparison_plot == str(hydrograph_plot)
    assert row.hydrograph_comparison_plot_pdf == str(hydrograph_plot_pdf)
    assert row.hydrograph_observed_simulated_calibrated_plot == str(hydrograph_overlay_plot)
    assert row.hydrograph_observed_simulated_calibrated_plot_pdf == str(hydrograph_overlay_plot_pdf)
    assert row.hydrograph_comparison_metrics == str(hydrograph_metrics)
    assert row.skill_diagnostics_json == str(skill_json)
    assert row.skill_diagnostics_md == str(skill_md)
    assert row.skill_diagnostic_flags == ["Snow timing mismatch", "Groundwater recession mismatch"]
    assert row.skill_evidence_metrics == [
        {
            "method": "annual_peak_local_window",
            "median_lag_days": 2.0,
            "event_count": 8,
        },
        {
            "method": "observed_top_decile_days",
            "top_decile_sim_obs_flow_ratio": 0.42,
            "top_decile_day_count": 36,
        },
    ]
    assert row.skill_next_actions == [
        "Unsupported process-control blocker: do not tune SFTMP, SMTMP."
    ]
    assert row.skill_source_backed_alternatives[0]["option"] == (
        "replace_legacy_gw_delay_advice_with_supported_alpha_and_partition_controls"
    )
    assert row.skill_recommended_probe_order[0]["diagnostic"] == (
        "replace_legacy_gw_delay_advice_with_supported_alpha_and_partition_controls"
    )
    assert row.skill_probe_gap_reasons == {
        "ALPHA_BF": "not_screened",
        "LATQ_CO": "not_screened",
        "RCHG_DP": "not_screened",
    }
    assert row.skill_screened_dead_parameters == []
    assert row.skill_unscreened_suggested_parameters == [
        "ALPHA_BF",
        "LATQ_CO",
        "RCHG_DP",
    ]
    assert row.skill_channel_routing_screen_json == str(channel_screen_json)
    assert row.skill_channel_routing_screen_md == str(channel_screen_md)
    assert row.skill_channel_routing_activity_classes == {"CH_N2": "weak", "CH_K2": "dead"}
    assert row.skill_channel_routing_effect_sizes == {"CH_N2": 0.0027, "CH_K2": 0.0}
    assert row.skill_channel_routing_best_bounds["CH_N2"] == {
        "bound": "lower",
        "value": 0.014,
        "score_delta": 0.001,
    }
    assert row.skill_channel_routing_calibration_verification_summary == str(channel_calibration_verification)
    assert row.skill_channel_routing_calibration_best_solution_json == str(channel_calibration_best)
    assert row.skill_channel_routing_calibration_parameters == {"CH_K2": 0.0}
    assert row.skill_channel_routing_calibration_metrics == {
        "nse": 0.03224760515404368,
        "kge": 0.07447705993949605,
        "pbias": -8.814999848382264,
    }
    assert row.skill_channel_routing_calibration_deltas == {
        "nse": 0.0014744570396475476,
        "kge": 0.004936885876811181,
    }
    assert row.skill_channel_routing_calibration_improved is True
    assert row.calibrated_skill_parameter_values == {"LAT_TTIME": 60.0}
    assert row.skill_parameter_bound_hits["LAT_TTIME"]["boundary"] == "upper"
    assert row.skill_parameter_bound_context[0]["all_tuned_suggested_parameters_at_bounds"] is True
    assert row.skill_parameter_bound_claim_impact == (
        "diagnostic_only_until_bound-hit controls are structurally explained"
    )
    assert row.unsupported_skill_parameters == ["SFTMP", "SMTMP"]
    assert row.superseded_unsupported_skill_parameters == ["SFTMP", "SMTMP"]
    assert row.blocked_skill_parameters == ["GWQMN"]
    assert row.build_diagnostic_artifacts == {
        "overlay_repair_report": "reports/overlay_repair/overlay_repair_report.json"
    }

    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    write_outputs([row], report_md, report_json)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["generation"] == {}
    assert report["rows"][0]["hydrograph_comparison_plot"] == str(hydrograph_plot)
    assert report["rows"][0]["hydrograph_observed_simulated_calibrated_plot"] == str(hydrograph_overlay_plot)
    assert report["rows"][0]["soil_mode"] == "fallback"
    assert report["rows"][0]["pct_fallback_soils"] == 1.0
    assert report["rows"][0]["et_partition_diagnostics_path"] == str(et_diag)
    assert report["rows"][0]["volume_source_backed_alternatives"][0]["option"] == (
        "audit_curve_number_and_landuse_soil_mapping"
    )
    assert report["rows"][0]["volume_recommended_probe_order"][0]["diagnostic"] == (
        "audit_curve_number_and_landuse_soil_mapping"
    )
    assert report["rows"][0]["terminal_hydrograph_scope"]["pbias_abs_improvement_pct_points"] == 48.0
    assert report["rows"][0]["terminal_scope_blocker"] == "outlet_scope_volume_mismatch"
    assert report["rows"][0]["post_aggregation_process_context"]["status"] == (
        "diagnostic_only_process_or_forcing_blocker"
    )
    assert report["rows"][0]["post_aggregation_process_context"]["likely_process_domains"] == [
        "swat_water_yield_below_observed_runoff"
    ]
    assert report["rows"][0]["allowed_claim_names"] == ["workflow_execution_trace_available"]
    assert report["rows"][0]["blocked_claim_names"] == ["physical_gate_claim", "terminal_scope_claim"]
    assert report["rows"][0]["et_source_backed_alternatives"][0]["option"] == "audit_pet_forcing_or_pet_method"
    assert report["rows"][0]["et_recommended_probe_order"][0]["parameters"] == ["PET_CO"]
    assert report["rows"][0]["terminal_trace_path"] == str(terminal_trace)
    assert report["rows"][0]["orphan_terminal_gis_ids"] == [3]
    assert report["rows"][0]["material_missing_terminal_gis_ids"] == []
    assert report["rows"][0]["all_terminal_routed_to_channel_closure_ratio"] == 0.97
    assert report["rows"][0]["selected_terminal_fraction_of_all_terminal_flow"] == 0.42
    assert report["rows"][0]["terminal_basin_nldi_area_km2"] == 100.0
    assert report["rows"][0]["selected_terminal_fraction_of_nldi_area"] == 0.40
    assert report["rows"][0]["all_terminal_fraction_of_delineated_area"] == 1.0
    assert report["rows"][0]["routing_source_backed_alternatives"][0]["option"] == (
        "audit_terminal_inventory_and_aggregation"
    )
    assert report["rows"][0]["routing_recommended_probe_order"][0]["diagnostic"] == (
        "audit_terminal_inventory_and_aggregation"
    )
    assert report["rows"][0]["unsupported_skill_parameters"] == ["SFTMP", "SMTMP"]
    assert report["rows"][0]["superseded_unsupported_skill_parameters"] == ["SFTMP", "SMTMP"]
    assert report["rows"][0]["blocked_skill_parameters"] == ["GWQMN"]
    assert report["rows"][0]["skill_evidence_metrics"][0]["method"] == "annual_peak_local_window"
    assert report["rows"][0]["skill_evidence_metrics"][1]["top_decile_sim_obs_flow_ratio"] == 0.42
    assert report["rows"][0]["skill_parameter_bound_hits"]["LAT_TTIME"]["boundary"] == "upper"
    assert report["rows"][0]["skill_source_backed_alternatives"][0]["option"] == (
        "replace_legacy_gw_delay_advice_with_supported_alpha_and_partition_controls"
    )
    assert report["rows"][0]["skill_unscreened_suggested_parameters"] == [
        "ALPHA_BF",
        "LATQ_CO",
        "RCHG_DP",
    ]
    assert report["rows"][0]["skill_recommended_probe_order"][0]["diagnostic"] == (
        "replace_legacy_gw_delay_advice_with_supported_alpha_and_partition_controls"
    )
    assert report["rows"][0]["skill_channel_routing_activity_classes"] == {
        "CH_N2": "weak",
        "CH_K2": "dead",
    }
    assert report["rows"][0]["skill_channel_routing_best_bounds"]["CH_K2"]["value"] == 500.0
    assert report["rows"][0]["skill_channel_routing_calibration_metrics"]["kge"] == 0.07447705993949605
    assert report["rows"][0]["skill_channel_routing_calibration_improved"] is True
    report_text = report_md.read_text(encoding="utf-8")
    assert "hydrograph plot" in report_text
    assert "soil provenance" in report_text
    assert "ET partition flags" in report_text
    assert "ET source-backed alternatives" in report_text
    assert "ET recommended probe order" in report_text
    assert "superseded unsupported skill parameters" in report_text
    assert "skill source-backed alternatives" in report_text
    assert "skill recommended probe order" in report_text
    assert "skill unscreened suggested parameters" in report_text
    assert "skill channel-routing verified refinement" in report_text
    assert "Historical superseded diagnostic: Unsupported process-control blocker" in report_text
    assert "volume-bias flags" in report_text
    assert "volume source-backed alternatives" in report_text
    assert "volume recommended probe order" in report_text
    assert "routing source-backed alternatives" in report_text
    assert "routing recommended probe order" in report_text
    assert "terminal inventory" in report_text
    assert "unsupported skill parameters" in report_text
    assert "blocked skill parameters" in report_text
    assert "## Action Plan" in report_text
    assert "Routing closure:" in report_text
    assert "Volume bias:" in report_text
    assert "Parameter governance: unsupported skill controls=SFTMP, SMTMP." in report_text

    row.volume_bias_primary_issue = None
    write_outputs([row], report_md, report_json)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["rows"][0]["primary_blocker"] == "VOLUME_BIAS"
    report_text = report_md.read_text(encoding="utf-8")
    assert "VOLUME_BIAS" in report_text
    assert "| none |" not in report_text

    row.volume_bias_primary_issue = "simulated_volume_excess"
    row.physical_condition_codes = ["BELOW_RESEARCH_SKILL"]
    row.physical_dominant_blocker = "BELOW_RESEARCH_SKILL"
    write_outputs([row], report_md, report_json)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["rows"][0]["primary_blocker"] == "BELOW_RESEARCH_SKILL"

    row.delta_kge = -0.1
    row.delta_nse = -0.1
    row.calibration = "attempted"
    write_outputs([row], report_md, report_json)
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["rows"][0]["primary_blocker"] == "calibration_regressed"


def test_objective_suite_summary_ignores_stale_et_artifact_when_gate_clears(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    physical_gates.write_text(
        json.dumps({"status": "passed", "condition_codes": [], "dominant_blocker": None}),
        encoding="utf-8",
    )
    stale_et = tmp_path / "reports" / "et_partition_diagnostics.json"
    stale_et.parent.mkdir(parents=True)
    stale_et.write_text(
        json.dumps(
            {
                "gate_context": "baseline",
                "diagnostic_flags": [{"code": "et_to_precip_high"}],
                "next_actions": ["stale"],
                "source_backed_alternatives": [{"option": "stale"}],
                "recommended_probe_order": [{"parameters": ["PET_CO"]}],
            }
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "gates_passed": ["physical_gates"],
                "gates_failed": ["routing_flow"],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "soil_mode": "high_fidelity",
                    "soil_provenance_mode": "gnatsgo_raster",
                    "pct_fallback_soils": 0.0,
                    "physical_gates_status": "passed",
                    "routing_flow_gates_status": "warning",
                    "calibration_status": "done",
                    "physical_gates_path": str(physical_gates),
                    "metrics": {"kge": 0.51, "nse": 0.21, "pbias": 14.4},
                    "baseline_metrics": {"kge": 0.26, "nse": 0.04, "pbias": -39.8},
                    "calibration_delta_metrics": {"kge": 0.25, "nse": 0.17, "pbias": 54.2},
                    "et_partition_diagnostic_flags": ["stale_value"],
                    "et_partition_next_actions": ["stale value"],
                },
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("03351500", evidence)

    assert row.physical_condition_codes == []
    assert row.et_partition_diagnostics_path is None
    assert row.et_partition_diagnostic_flags == []
    assert row.et_partition_next_actions == []


def test_objective_suite_primary_blocker_prefers_terminal_failure_class(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    routing_gates = tmp_path / "routing_flow_gates.json"
    physical_gates.write_text(
        json.dumps({"status": "passed", "condition_codes": [], "dominant_blocker": None}),
        encoding="utf-8",
    )
    routing_gates.write_text(
        json.dumps(
            {
                "status": "warning",
                "closure_status": "fail_mass_closure",
                "flags": ["multiple_terminal_outlets_present"],
                "terminal_trace_path": str(tmp_path / "terminal_trace.json"),
                "terminal_failure_class": "generated_topology_mismatch",
            }
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "gates_passed": ["physical_gates"],
                "gates_failed": ["routing_flow"],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "soil_mode": "high_fidelity",
                    "soil_provenance_mode": "gnatsgo_raster",
                    "pct_fallback_soils": 0.0,
                    "physical_gates_status": "passed",
                    "routing_flow_gates_status": "warning",
                    "routing_flow_closure_status": "fail_mass_closure",
                    "routing_flow_gates_path": str(routing_gates),
                    "calibration_status": "done",
                    "physical_gates_path": str(physical_gates),
                    "metrics": {"kge": 0.51, "nse": 0.21, "pbias": 14.4},
                    "baseline_metrics": {"kge": 0.26, "nse": 0.04, "pbias": -39.8},
                    "calibration_delta_metrics": {"kge": 0.25, "nse": 0.17, "pbias": 54.2},
                },
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("03351500", evidence)

    assert row.routing_flow_closure_status == "fail_mass_closure"
    assert row.terminal_failure_class == "generated_topology_mismatch"
    assert row.primary_blocker == "generated_topology_mismatch"


def test_objective_suite_suppresses_inactive_routing_diagnostics(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    routing_gates = tmp_path / "routing_flow_gates.json"
    trace = tmp_path / "routing_trace.json"
    terminal_trace = tmp_path / "terminal_trace.json"
    physical_gates.write_text(
        json.dumps({"status": "passed", "condition_codes": [], "dominant_blocker": None}),
        encoding="utf-8",
    )
    trace.write_text(
        json.dumps(
            {
                "source_backed_alternatives": [{"option": "historical_routing_probe"}],
                "recommended_probe_order": [{"diagnostic": "historical_routing_probe"}],
            }
        ),
        encoding="utf-8",
    )
    terminal_trace.write_text('{"missing_terminal_gis_ids":[3]}\n', encoding="utf-8")
    routing_gates.write_text(
        json.dumps(
            {
                "status": "passed",
                "closure_status": "pass",
                "json_path": str(trace),
                "flags": ["multiple_terminal_outlets_present"],
                "terminal_trace_path": str(terminal_trace),
                "terminal_failure_class": "generated_topology_mismatch",
            }
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "research_grade",
                "blocker_class": None,
                "gates_passed": ["physical_gates", "routing_flow"],
                "gates_failed": [],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "soil_mode": "high_fidelity",
                    "soil_provenance_mode": "gnatsgo_raster",
                    "pct_fallback_soils": 0.0,
                    "physical_gates_status": "passed",
                    "routing_flow_gates_status": "passed",
                    "routing_flow_closure_status": "pass",
                    "routing_flow_gates_path": str(routing_gates),
                    "calibration_status": "done",
                    "physical_gates_path": str(physical_gates),
                    "metrics": {"kge": 0.51, "nse": 0.21, "pbias": 14.4},
                    "baseline_metrics": {"kge": 0.26, "nse": 0.04, "pbias": -39.8},
                    "calibration_delta_metrics": {"kge": 0.25, "nse": 0.17, "pbias": 54.2},
                },
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("03351500", evidence)

    assert row.routing_flow_gates == "passed"
    assert row.routing_flow_closure_status == "pass"
    assert row.routing_flow_diagnostic_flags == []
    assert row.routing_source_backed_alternatives == []
    assert row.routing_recommended_probe_order == []
    assert row.terminal_trace_path is None
    assert row.terminal_failure_class is None
    assert row.primary_blocker == "none"


def test_objective_suite_infers_legacy_calibration_precheck_from_package_policy(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    routing_gates = tmp_path / "routing_flow_gates.json"
    physical_gates.write_text(
        json.dumps(
            {
                "status": "failed",
                "condition_codes": ["MASS_IMBALANCE", "VOLUME_BIAS", "ET_DOMINATED"],
                "dominant_blocker": "MASS_IMBALANCE",
            }
        ),
        encoding="utf-8",
    )
    routing_gates.write_text(
        json.dumps({"status": "passed", "closure_status": "pass"}),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "blocker_class": None,
                "gates_passed": ["routing_flow"],
                "gates_failed": ["physical_gates", "calibration_verification"],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "physical_gates_status": "failed",
                    "physical_gates_path": str(physical_gates),
                    "routing_flow_gates_status": "passed",
                    "routing_flow_closure_status": "pass",
                    "routing_flow_gates_path": str(routing_gates),
                    "calibration_attempted": True,
                    "calibration_success": False,
                    "calibration_status": "attempted_failed_or_blocked",
                    "calibration_provenance": {"error": "calibration attempted"},
                    "metrics": {"kge": 0.2, "nse": -0.1, "pbias": -40.0},
                },
                "allowed_claims": [],
                "blocked_claims": [],
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("01491000", evidence)

    assert row.calibration_precheck_sequence == "volume_bias_repair_before_final_physical_gate"
    assert row.calibration_precheck_block_reason is None
    assert row.calibration_precheck_physical_gates_status == "failed"
    assert row.calibration_precheck_routing_flow_gates_status == "passed"

    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    write_outputs([row], report_md, report_json)

    rendered = report_md.read_text(encoding="utf-8")
    assert "calibration precheck" in rendered
    assert "volume_bias_repair_before_final_physical_gate" in rendered


def test_objective_suite_reads_blocked_calibration_precheck_from_provenance_file(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    routing_gates = tmp_path / "routing_flow_gates.json"
    calibration_provenance = tmp_path / "calibration_provenance.json"
    physical_gates.write_text(
        json.dumps(
            {
                "status": "failed",
                "condition_codes": ["ZERO_SURFACE_RUNOFF"],
                "dominant_blocker": "ZERO_SURFACE_RUNOFF",
            }
        ),
        encoding="utf-8",
    )
    routing_gates.write_text(
        json.dumps({"status": "passed", "closure_status": "pass"}),
        encoding="utf-8",
    )
    calibration_provenance.write_text(
        json.dumps(
            {
                "status": "blocked_by_physical_gates",
                "success": False,
                "reason": "physical_gates_not_passed",
                "provenance": {
                    "physical_gates_status": "failed",
                    "routing_flow_gates_status": "passed",
                    "calibration_sequence": "blocked_before_volume_stage",
                },
                "phases": [],
            }
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "exploratory",
                "blocker_class": None,
                "gates_passed": ["routing_flow"],
                "gates_failed": ["physical_gates"],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "physical_gates_status": "failed",
                    "physical_gates_path": str(physical_gates),
                    "routing_flow_gates_status": "passed",
                    "routing_flow_gates_path": str(routing_gates),
                    "calibration_attempted": False,
                    "calibration_success": False,
                    "calibration_status": "blocked_by_physical_gates",
                    "calibration_provenance_path": str(calibration_provenance),
                    "metrics": {"kge": 0.5, "nse": 0.2, "pbias": 5.0},
                },
                "allowed_claims": [],
                "blocked_claims": [],
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("01654000", evidence)

    assert row.calibration == "blocked_by_physical_gates"
    assert row.calibration_precheck_sequence == "blocked_before_volume_stage"
    assert row.calibration_precheck_block_reason is None
    assert row.calibration_precheck_physical_gates_status == "failed"
    assert row.calibration_precheck_routing_flow_gates_status == "passed"


def test_production_objective_audit_validates_hydrograph_artifacts(tmp_path: Path) -> None:
    plot = tmp_path / "hydrograph.png"
    metrics = tmp_path / "hydrograph_metrics.json"
    plot.write_bytes(b"png")
    metrics.write_text('{"kge":0.7}\n', encoding="utf-8")

    assert _row_hydrograph_ok(
        {
            "calibration": "attempted",
            "hydrograph_comparison_plot": str(plot),
            "hydrograph_comparison_metrics": str(metrics),
            "notes": "no keyword needed",
        }
    )
    assert not _row_hydrograph_ok(
        {
            "calibration": "done",
            "hydrograph_comparison_plot": str(plot),
            "hydrograph_comparison_metrics": str(tmp_path / "missing.json"),
        }
    )


def test_production_objective_audit_validates_et_gate_context(tmp_path: Path) -> None:
    et_diag = tmp_path / "et_partition_diagnostics.json"
    et_diag.write_text(
        json.dumps(
            {
                "gate_context": "final_locked",
                "diagnostic_flags": [{"code": "et_to_precip_high"}],
                "next_actions": ["Run PET_CO/ESCO/EPCO probe."],
                "source_backed_alternatives": [{"option": "audit_pet_forcing_or_pet_method"}],
                "recommended_probe_order": [{"parameters": ["PET_CO"]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    row = {
        "physical_condition_codes": ["ET_DOMINATED"],
        "et_partition_diagnostics_path": str(et_diag),
        "et_partition_gate_context": "final_locked",
        "et_partition_diagnostic_flags": ["et_to_precip_high"],
        "et_partition_next_actions": ["Run PET_CO/ESCO/EPCO probe."],
    }

    assert _row_et_diagnostics_ok(row)
    row["et_partition_gate_context"] = "baseline"
    assert not _row_et_diagnostics_ok(row)


def test_objective_suite_discovers_legacy_build_diagnostic_reports(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    overlay_report = tmp_path / "reports" / "overlay_repair" / "overlay_repair_report.json"
    overlay_report.parent.mkdir(parents=True)
    overlay_report.write_text('{"reason":"categorical_overlay_gap_too_large"}\n', encoding="utf-8")
    soil_realism = tmp_path / "reports" / "soil_realism_diagnostics.json"
    soil_realism.write_text(
        json.dumps(
            {
                "source_backed_alternatives": [
                    {
                        "option": "recover_gnatsgo_raster_plus_sda_horizons",
                        "required_artifacts": ["raw/mukey.tif"],
                    }
                ],
                "next_actions": ["Recover authoritative soils before claim promotion."],
                "recommended_probe_order": [
                    {
                        "diagnostic": "recover_gnatsgo_raster_plus_sda_horizons",
                        "required_artifacts": ["raw/mukey.tif"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": False,
                "effective_claim_tier": "exploratory",
                "blocker_class": "hru_overlay_realism_failed",
                "gates_failed": ["fresh_engine_output"],
                "values": {
                    "warmup_years": 3,
                    "calibration_attempted": False,
                    "calibration_success": False,
                    "calibration_status": "not_attempted",
                },
                "allowed_claims": [],
                "blocked_claims": [],
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("01013500", evidence)

    assert row.build_diagnostic_artifacts == {
        "overlay_repair_report": str(overlay_report),
        "soil_realism_diagnostics": str(soil_realism),
    }
    assert row.soil_next_actions == ["Recover authoritative soils before claim promotion."]
    assert row.soil_source_backed_alternatives[0]["option"] == "recover_gnatsgo_raster_plus_sda_horizons"
    assert row.soil_recommended_probe_order[0]["diagnostic"] == "recover_gnatsgo_raster_plus_sda_horizons"


def test_objective_suite_normalizes_legacy_soil_realism_blocker_metadata(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    soil_realism = tmp_path / "reports" / "soil_realism_diagnostics.json"
    soil_realism.parent.mkdir(parents=True)
    soil_realism.write_text(
        json.dumps(
            {
                "blocker_class": "soil_realism_gate_failed",
                "next_actions": ["Inspect soil acquisition provenance."],
                "source_backed_alternatives": [
                    {"option": "recover_gnatsgo_raster_plus_sda_horizons"}
                ],
                "recommended_probe_order": [
                    {"diagnostic": "recover_gnatsgo_raster_plus_sda_horizons"}
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": False,
                "effective_claim_tier": "exploratory",
                "blocker_class": "soil_realism_gate_failed",
                "gates_passed": [],
                "gates_failed": ["contract_policy", "routing_flow", "sensitivity_screen"],
                "values": {
                    "warmup_years": 3,
                    "soil_mode": "high_fidelity",
                    "calibration_attempted": False,
                    "calibration_success": False,
                    "calibration_status": "not_attempted",
                },
                "allowed_claims": [],
                "blocked_claims": [],
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("02129000", evidence)

    assert row.soil_mode == "not_verified"
    assert row.soil_provenance_mode == "soil_realism_gate_failed"
    assert "contract_policy" in row.gates_passed
    assert "contract_policy" not in row.gates_failed
    assert "soil_fidelity" in row.gates_failed
    assert row.primary_blocker == "soil_realism_gate_failed"
    assert row.soil_next_actions == ["Inspect soil acquisition provenance."]


def test_objective_suite_suppresses_superseded_volume_diagnostics_when_final_gate_passes(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    volume_diag = tmp_path / "reports" / "volume_bias_diagnostics.json"
    volume_diag.parent.mkdir(parents=True)
    physical_gates.write_text(
        json.dumps(
            {
                "status": "passed",
                "condition_codes": [],
                "dominant_blocker": None,
            }
        ),
        encoding="utf-8",
    )
    volume_diag.write_text(
        json.dumps(
            {
                "primary_issue": "simulated_volume_deficit",
                "diagnostic_flags": [{"code": "simulated_volume_deficit"}],
                "next_actions": ["Historical baseline-only action."],
                "source_backed_alternatives": [{"option": "historical_volume_probe"}],
                "recommended_probe_order": [{"diagnostic": "historical_volume_probe"}],
            }
        ),
        encoding="utf-8",
    )
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "research_grade",
                "blocker_class": None,
                "gates_passed": ["physical_gates"],
                "gates_failed": [],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "soil_mode": "high_fidelity",
                    "soil_provenance_mode": "gnatsgo_raster",
                    "pct_fallback_soils": 0.0,
                    "physical_gates_status": "passed",
                    "physical_gates_path": str(physical_gates),
                    "volume_bias_diagnostics_path": str(volume_diag),
                    "volume_bias_primary_issue": "simulated_volume_deficit",
                    "calibration_attempted": True,
                    "calibration_success": True,
                    "calibration_status": "done",
                    "metrics": {"kge": 0.55, "nse": 0.2, "pbias": 2.0},
                },
                "allowed_claims": [],
                "blocked_claims": [],
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("12031000", evidence)

    assert row.volume_bias_diagnostics_path is None
    assert row.volume_bias_primary_issue is None
    assert row.volume_bias_diagnostic_flags == []
    assert row.volume_bias_next_actions == []
    assert row.volume_source_backed_alternatives == []
    assert row.volume_recommended_probe_order == []
    assert row.primary_blocker == "none"


def test_objective_suite_suppresses_inactive_skill_diagnostics(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_summary.json"
    physical_gates = tmp_path / "physical_gates.json"
    skill_dir = tmp_path / "calibration" / "skill_diagnostics"
    skill_json = skill_dir / "skill_diagnostics.json"
    skill_md = skill_dir / "skill_diagnostics.md"
    skill_dir.mkdir(parents=True)
    physical_gates.write_text(
        json.dumps(
            {
                "status": "passed",
                "condition_codes": [],
                "dominant_blocker": None,
            }
        ),
        encoding="utf-8",
    )
    skill_json.write_text(
        json.dumps(
            {
                "diagnostic_flags": [{"symptom": "Historical timing symptom"}],
                "next_actions": ["Historical skill action."],
                "source_backed_alternatives": [
                    {"option": "historical_skill_probe", "parameters": ["SURLAG"]}
                ],
                "recommended_probe_order": [{"diagnostic": "historical_skill_probe"}],
            }
        ),
        encoding="utf-8",
    )
    skill_md.write_text("# Historical skill diagnostics\n", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "success": True,
                "effective_claim_tier": "research_grade",
                "blocker_class": None,
                "gates_passed": ["physical_gates"],
                "gates_failed": [],
                "values": {
                    "warmup_years": 3,
                    "fresh_engine_run": True,
                    "soil_mode": "high_fidelity",
                    "soil_provenance_mode": "gnatsgo_raster",
                    "pct_fallback_soils": 0.0,
                    "physical_gates_status": "passed",
                    "physical_gates_path": str(physical_gates),
                    "calibration_attempted": True,
                    "calibration_success": True,
                    "calibration_status": "done",
                    "metrics": {"kge": 0.55, "nse": 0.2, "pbias": 2.0},
                },
                "allowed_claims": [],
                "blocked_claims": [],
            }
        ),
        encoding="utf-8",
    )

    row = summarize_evidence("12031000", evidence)

    assert row.skill_diagnostics_json is None
    assert row.skill_diagnostics_md is None
    assert row.skill_diagnostic_flags == []
    assert row.skill_evidence_metrics == []
    assert row.skill_next_actions == []
    assert row.skill_source_backed_alternatives == []
    assert row.skill_recommended_probe_order == []
    assert row.skill_probe_gap_parameters == []
    assert row.skill_channel_routing_screen_json is None
    assert row.skill_channel_routing_screen_md is None
    assert row.skill_channel_routing_activity_classes == {}
    assert row.skill_channel_routing_effect_sizes == {}
    assert row.skill_channel_routing_best_bounds == {}
    assert row.skill_channel_routing_calibration_verification_summary is None
    assert row.skill_channel_routing_calibration_best_solution_json is None
    assert row.skill_channel_routing_calibration_parameters == {}
    assert row.skill_channel_routing_calibration_metrics == {}
    assert row.skill_channel_routing_calibration_deltas == {}
    assert row.skill_channel_routing_calibration_improved is None
    assert row.primary_blocker == "none"


def test_objective_suite_uses_explicit_evidence_override(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    override_dir = tmp_path / "override_01547700"
    canonical_dir = canonical_root / "01547700"
    canonical_dir.mkdir(parents=True)
    override_dir.mkdir()

    def _write_evidence(path: Path, tier: str) -> None:
        values = {
            "warmup_years": 3,
            "fresh_engine_run": True,
            "calibration_status": "not_attempted",
        }
        if tier == "research_grade":
            values.update(
                {
                    "soil_mode": "high_fidelity",
                    "soil_provenance_mode": "gnatsgo_raster",
                    "pct_fallback_soils": 0.0,
                }
            )
        path.write_text(
            json.dumps(
                {
                    "success": True,
                    "effective_claim_tier": tier,
                    "blocker_class": None,
                    "values": values,
                    "allowed_claims": [],
                    "blocked_claims": [],
                }
            ),
            encoding="utf-8",
        )

    _write_evidence(canonical_dir / "evidence_summary.json", "exploratory")
    _write_evidence(override_dir / "evidence_summary.json", "research_grade")
    for basin in [
        "02129000",
        "03349000",
        "01654000",
        "01491000",
        "01013500",
        "03351500",
        "03353000",
        "01493500",
        "12031000",
        "09504500",
    ]:
        basin_dir = canonical_root / basin
        basin_dir.mkdir(parents=True)
        _write_evidence(basin_dir / "evidence_summary.json", "exploratory")

    rows = summarize_existing_suite(
        canonical_root,
        evidence_overrides={"01547700": override_dir / "evidence_summary.json"},
    )

    row_by_basin = {row.basin: row for row in rows}
    assert row_by_basin["01547700"].tier == "research_grade"
    assert row_by_basin["01547700"].evidence_summary_path == str(
        (override_dir / "evidence_summary.json").resolve()
    )


def test_objective_suite_report_records_generation_metadata(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    for basin in [
        "02129000",
        "01547700",
        "03349000",
        "01654000",
        "01491000",
        "01013500",
        "03351500",
        "03353000",
        "01493500",
        "12031000",
        "09504500",
    ]:
        basin_dir = evidence_root / basin
        basin_dir.mkdir(parents=True)
        (basin_dir / "evidence_summary.json").write_text(
            json.dumps(
                {
                    "success": True,
                    "effective_claim_tier": "exploratory",
                    "blocker_class": None,
                    "values": {
                        "warmup_years": 3,
                        "fresh_engine_run": True,
                        "calibration_status": "not_attempted",
                    },
                    "allowed_claims": [],
                    "blocked_claims": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    main(
        [
            "--out-root",
            str(evidence_root),
            "--summarize-existing",
            "--report-md",
            str(report_md),
            "--report-json",
            str(report_json),
            "--evidence-override",
            f"01547700={evidence_root / '01547700' / 'evidence_summary.json'}",
        ]
    )

    report = json.loads(report_json.read_text(encoding="utf-8"))
    generation = report["generation"]
    assert generation["out_root"] == str(evidence_root.resolve())
    assert generation["summarize_existing"] is True
    assert generation["resume_existing"] is False
    assert generation["report_md"] == str(report_md.resolve())
    assert generation["report_json"] == str(report_json.resolve())
    assert generation["evidence_overrides"] == {
        "01547700": str((evidence_root / "01547700" / "evidence_summary.json").resolve())
    }
