#!/usr/bin/env python3
from __future__ import annotations

import json
import csv
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from swatplus_builder.params.governance import FULL_MODE_CORE_PARAMETERS, FULL_MODE_PARAMETER_GOVERNANCE

OBJECTIVE_REPORT_JSON = ROOT / "docs" / "objective_basin_validation_report.json"
OBJECTIVE_REPORT_MD = ROOT / "docs" / "OBJECTIVE_BASIN_VALIDATION_REPORT.md"
SKILL_ONLY_GATE_CODES = {"NEGATIVE_SKILL", "BELOW_RESEARCH_SKILL"}
OVERLAY_REPAIR_REPORT = (
    ROOT
    / "demo_runs"
    / "post_overlay_repair_01013500_network"
    / "reports"
    / "overlay_repair"
    / "overlay_repair_report.json"
)
REQUIRED_BASINS = {
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
}


@dataclass
class Check:
    requirement: str
    status: str
    evidence: str


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _contains(rel: str, needle: str) -> bool:
    p = ROOT / rel
    if not p.exists() or not p.is_file():
        return False
    try:
        return needle in p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def _cli_workflow_registered() -> bool:
    p = ROOT / "src" / "swatplus_builder" / "cli.py"
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8", errors="ignore")
    return (
        "workflow_app = typer.Typer" in text
        and 'app.add_typer(workflow_app, name="workflow")' in text
        and '@workflow_app.command("negotiate")' in text
        and '@workflow_app.command("run")' in text
        and "--model-family" in text
        and "--contract-status" in text
        and "--accepted-by" in text
    )


def _load_objective_report() -> dict[str, Any] | None:
    if not OBJECTIVE_REPORT_JSON.exists():
        return None
    try:
        return json.loads(OBJECTIVE_REPORT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_overlay_repair_report() -> dict[str, Any] | None:
    if not OVERLAY_REPAIR_REPORT.exists():
        return None
    try:
        return json.loads(OVERLAY_REPAIR_REPORT.read_text(encoding="utf-8"))
    except Exception:
        return None


def _path_exists(value: object) -> bool:
    if not value:
        return False
    return Path(str(value)).exists()


def _load_json_path(value: object) -> dict[str, Any]:
    if not value:
        return {}
    path = Path(str(value))
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _row_claim_policy_names_ok(row: dict[str, Any]) -> bool:
    allowed = row.get("allowed_claim_names")
    blocked = row.get("blocked_claim_names")
    return (
        isinstance(allowed, list)
        and bool(allowed)
        and all(isinstance(name, str) and name for name in allowed)
        and isinstance(blocked, list)
        and all(isinstance(name, str) and name for name in blocked)
    )


_BLOCKER_DOMAINS = {
    "engineering",
    "diagnostics",
    "calibration",
    "provenance",
    "parameter_support",
    "science",
}


def _non_research_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("tier") or "") != "research_grade"]


def _row_blocker_domain_action_plan_ok(row: dict[str, Any]) -> bool:
    domain = row.get("blocker_domain")
    actions = row.get("blocker_action_items")
    return (
        isinstance(domain, str)
        and domain in _BLOCKER_DOMAINS
        and isinstance(actions, list)
        and bool(actions)
        and all(isinstance(action, str) and action for action in actions)
    )


def _report_blocker_classification_ok(report: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    classification = report.get("non_research_blocker_classification")
    if not isinstance(classification, dict):
        return False
    counts = classification.get("domain_counts")
    if not isinstance(counts, dict) or set(counts) != _BLOCKER_DOMAINS:
        return False
    if any(not isinstance(value, int) or value < 0 for value in counts.values()):
        return False
    non_research = _non_research_rows(rows)
    if sum(counts.values()) != len(non_research):
        return False
    if classification.get("unclassified_blockers") != []:
        return False
    for row in non_research:
        domain = row.get("blocker_domain")
        if domain not in _BLOCKER_DOMAINS:
            return False
    row_counts = {domain: 0 for domain in _BLOCKER_DOMAINS}
    for row in non_research:
        row_counts[str(row["blocker_domain"])] += 1
    return row_counts == counts


def _target_hypothesis_evaluation_ok(report: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    evaluation = report.get("target_hypothesis_evaluation")
    classification = report.get("non_research_blocker_classification")
    if not isinstance(evaluation, dict) or not isinstance(classification, dict):
        return False
    observed = sum(1 for row in rows if str(row.get("tier") or "") == "research_grade")
    target = evaluation.get("target_research_grade_count")
    if target != 7 or evaluation.get("observed_research_grade_count") != observed:
        return False
    expected_status = "met_without_gate_weakening" if observed >= 7 else "not_supported_by_current_evidence"
    if evaluation.get("status") != expected_status:
        return False
    if evaluation.get("gate_weakening_permitted") is not False:
        return False
    if evaluation.get("metrics_alone_grant_research_grade") is not False:
        return False
    if evaluation.get("unclassified_blockers") != classification.get("unclassified_blockers"):
        return False
    domain_counts = classification.get("domain_counts")
    if not isinstance(domain_counts, dict) or evaluation.get("blocker_domain_counts") != domain_counts:
        return False
    improvement_domains = evaluation.get("pipeline_improvement_required_domains")
    if not isinstance(improvement_domains, list):
        return False
    allowed = {"engineering", "diagnostics", "calibration", "provenance", "parameter_support"}
    expected_domains = [
        domain
        for domain in ("engineering", "diagnostics", "calibration", "provenance", "parameter_support")
        if int(domain_counts.get(domain, 0) or 0) > 0
    ]
    if improvement_domains != expected_domains or not set(improvement_domains).issubset(allowed):
        return False
    science_count = domain_counts.get("science")
    return evaluation.get("science_blocker_count") == science_count and isinstance(
        evaluation.get("interpretation"), str
    ) and bool(evaluation.get("interpretation"))


def _science_blocker_summary_ok(report: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    summary = report.get("science_blocker_summary")
    classification = report.get("non_research_blocker_classification")
    if not isinstance(summary, dict) or not isinstance(classification, dict):
        return False
    science_rows = [
        row
        for row in rows
        if str(row.get("tier") or "") != "research_grade"
        and row.get("blocker_domain") == "science"
    ]
    expected_counts: dict[str, int] = {}
    for row in science_rows:
        blocker = str(row.get("primary_blocker") or "")
        if not blocker:
            return False
        expected_counts[blocker] = expected_counts.get(blocker, 0) + 1
    if summary.get("version") != 1:
        return False
    if summary.get("generated_from") != "non_research_blocker_classification":
        return False
    expected_status = "active_science_blockers" if science_rows else "no_science_blockers"
    if summary.get("status") != expected_status:
        return False
    if summary.get("science_blocker_count") != len(science_rows):
        return False
    domain_counts = classification.get("domain_counts")
    if not isinstance(domain_counts, dict):
        return False
    if summary.get("domain_count") != domain_counts.get("science"):
        return False
    if summary.get("primary_blocker_counts") != dict(sorted(expected_counts.items())):
        return False
    if summary.get("gate_weakening_permitted") is not False:
        return False
    if summary.get("metrics_alone_grant_research_grade") is not False:
        return False
    items = summary.get("items")
    if not isinstance(items, list):
        return False
    basin_items: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            return False
        blocker = item.get("primary_blocker")
        if not isinstance(blocker, str) or blocker not in expected_counts:
            return False
        if item.get("basin_count") != expected_counts[blocker]:
            return False
        if item.get("claim_authority") is not False:
            return False
        if item.get("pipeline_improvement_domain") is not False:
            return False
        if item.get("gate_weakening_permitted") is not False:
            return False
        source_fields = item.get("source_evidence_fields")
        if not isinstance(source_fields, list) or not source_fields:
            return False
        item_basin_items = item.get("basin_items")
        if not isinstance(item_basin_items, list):
            return False
        for basin_item in item_basin_items:
            if not isinstance(basin_item, dict):
                return False
            basin = basin_item.get("basin")
            if not isinstance(basin, str) or not basin:
                return False
            basin_items[basin] = basin_item
    if set(basin_items) != {str(row.get("basin")) for row in science_rows}:
        return False
    for row in science_rows:
        basin = str(row.get("basin"))
        blocker = str(row.get("primary_blocker") or "")
        item = basin_items[basin]
        if item.get("primary_blocker") != blocker or item.get("claim_authority") is not False:
            return False
        if not isinstance(item.get("blocked_claim_names"), list) or not item.get("blocked_claim_names"):
            return False
        if blocker in {"BELOW_RESEARCH_SKILL", "NEGATIVE_SKILL"}:
            if item.get("evidence_type") != "skill_limitation":
                return False
            if item.get("classification") != row.get("skill_limitation_class"):
                return False
            if not isinstance(item.get("flags"), list) or not item.get("flags"):
                return False
            if not isinstance(item.get("recommended_focus"), list) or not item.get("recommended_focus"):
                return False
            if item.get("claim_impact") != row.get("skill_limitation_claim_impact"):
                return False
            if not _path_exists(item.get("diagnostics_path")):
                return False
        elif blocker == "MASS_IMBALANCE":
            if item.get("evidence_type") != "mass_balance_diagnostics":
                return False
            if not isinstance(item.get("flags"), list) or "mass_closure_residual_high" not in item.get("flags", []):
                return False
            if item.get("first_probe") != "audit_basin_water_balance_closure_terms":
                return False
            if not _path_exists(item.get("diagnostics_path")):
                return False
        else:
            return False
    return True


def _pipeline_improvement_plan_ok(report: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    plan = report.get("pipeline_improvement_plan")
    evaluation = report.get("target_hypothesis_evaluation")
    if not isinstance(plan, dict) or not isinstance(evaluation, dict):
        return False
    expected_domains = evaluation.get("pipeline_improvement_required_domains")
    if not isinstance(expected_domains, list):
        return False
    expected_domains = [domain for domain in expected_domains if isinstance(domain, str)]
    if plan.get("version") != 1:
        return False
    if plan.get("generated_from") != "non_research_blocker_classification":
        return False
    if plan.get("target_status") != evaluation.get("status"):
        return False
    if plan.get("gate_weakening_permitted") is not False:
        return False
    if plan.get("temporary_metrics_allowed_as_final") is not False:
        return False
    items = plan.get("items")
    if not isinstance(items, list):
        return False
    if plan.get("domains") != [item.get("domain") for item in items]:
        return False
    if [item.get("domain") for item in items] != expected_domains:
        return False
    expected_status = (
        "active_non_science_pipeline_gaps"
        if expected_domains
        else "no_non_science_pipeline_gaps_classified"
    )
    if plan.get("status") != expected_status:
        return False
    by_domain: dict[str, list[dict[str, Any]]] = {domain: [] for domain in expected_domains}
    for row in _non_research_rows(rows):
        domain = row.get("blocker_domain")
        if domain in by_domain:
            by_domain[str(domain)].append(row)
    for index, item in enumerate(items, start=1):
        domain = item.get("domain")
        domain_rows = by_domain.get(str(domain))
        if domain_rows is None:
            return False
        basins = item.get("basins")
        if item.get("rank") != index:
            return False
        if item.get("basin_count") != len(domain_rows):
            return False
        if basins != sorted(str(row.get("basin")) for row in domain_rows):
            return False
        blocker_counts: dict[str, int] = {}
        for row in domain_rows:
            blocker = str(row.get("primary_blocker") or row.get("blocker") or "")
            if not blocker:
                return False
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        if item.get("primary_blocker_counts") != dict(sorted(blocker_counts.items())):
            return False
        for field in ("next_experiment", "claim_impact"):
            if not isinstance(item.get(field), str) or not item.get(field):
                return False
        for field in ("representative_actions", "source_evidence_fields", "required_before_claim"):
            values = item.get(field)
            if not isinstance(values, list) or not values:
                return False
            if not all(isinstance(value, str) and value for value in values):
                return False
        if "rerun a fresh locked TxtInOut after the selected blocker is repaired" not in item.get(
            "required_before_claim",
            [],
        ):
            return False
        basin_items = item.get("basin_items")
        if not isinstance(basin_items, list) or len(basin_items) != len(domain_rows):
            return False
        if [entry.get("basin") for entry in basin_items] != basins:
            return False
        rows_by_basin = {str(row.get("basin")): row for row in domain_rows}
        for entry in basin_items:
            if not _pipeline_improvement_basin_item_ok(entry, rows_by_basin):
                return False
    return True


def _pipeline_improvement_basin_item_ok(
    entry: object,
    rows_by_basin: dict[str, dict[str, Any]],
) -> bool:
    if not isinstance(entry, dict):
        return False
    basin = entry.get("basin")
    if not isinstance(basin, str) or basin not in rows_by_basin:
        return False
    row = rows_by_basin[basin]
    if entry.get("domain") != row.get("blocker_domain"):
        return False
    if entry.get("primary_blocker") != row.get("primary_blocker"):
        return False
    if not isinstance(entry.get("next_experiment"), str) or not entry.get("next_experiment"):
        return False
    if entry.get("claim_authority") is not False:
        return False
    if entry.get("temporary_metrics_allowed_as_final") is not False:
        return False
    if entry.get("fresh_locked_rerun_required_before_claim") is not True:
        return False
    artifacts = entry.get("evidence_artifacts")
    if not isinstance(artifacts, dict):
        return False
    if artifacts.get("evidence_summary") != row.get("evidence_summary_path"):
        return False
    if not _path_exists(artifacts.get("evidence_summary")):
        return False
    if not any(
        _path_exists(artifacts.get(key))
        for key in ("routing_flow_gates", "terminal_trace", "volume_bias_diagnostics")
    ):
        return False
    fields = entry.get("source_evidence_fields")
    if not isinstance(fields, list) or not fields:
        return False
    if not all(isinstance(field, str) and field for field in fields):
        return False
    decision = entry.get("decision_request")
    if not _pipeline_improvement_decision_request_ok(decision, entry):
        return False
    for probe_key in ("first_routing_probe", "first_volume_probe"):
        probe = entry.get(probe_key)
        if not isinstance(probe, dict):
            return False
        if probe:
            if not isinstance(probe.get("diagnostic"), str) or not probe.get("diagnostic"):
                return False
            if not isinstance(probe.get("claim_impact"), str) or not probe.get("claim_impact"):
                return False
            if not isinstance(probe.get("fresh_output_required"), bool):
                return False
            artifacts_required = probe.get("required_artifacts")
            if not isinstance(artifacts_required, list):
                return False
            if not all(isinstance(path, str) and path for path in artifacts_required):
                return False
    return True


def _pipeline_improvement_decision_request_ok(
    decision: object,
    entry: dict[str, Any],
) -> bool:
    if not isinstance(decision, dict):
        return False
    domain = entry.get("domain")
    status = decision.get("status")
    if domain == "provenance":
        if status != "needs_input":
            return False
        if not isinstance(decision.get("question_id"), str) or not decision.get("question_id"):
            return False
        if str(entry.get("basin")) not in str(decision.get("question_id")):
            return False
        if decision.get("accepted_by_required") != "user_or_policy":
            return False
        option_ids_required = {
            "confirm_selected_terminal_authority",
            "authorize_virtual_all_terminal_outlet",
            "retain_exploratory_until_outlet_rebuilt",
        }
    else:
        if status != "diagnostic_only":
            return False
        if decision.get("question_id") is not None:
            return False
        if decision.get("accepted_by_required") != "agent_or_policy":
            return False
        option_ids_required = {
            "run_source_backed_diagnostic",
            "retain_exploratory_science_blocker",
        }
    for field in ("decision_type", "question", "recommended_option", "claim_impact"):
        if not isinstance(decision.get(field), str) or not decision.get(field):
            return False
    options = decision.get("options")
    if not isinstance(options, list) or not options:
        return False
    seen_ids = set()
    for option in options:
        if not isinstance(option, dict):
            return False
        option_id = option.get("id")
        if not isinstance(option_id, str) or not option_id:
            return False
        seen_ids.add(option_id)
        for field in ("label", "claim_impact"):
            if not isinstance(option.get(field), str) or not option.get(field):
                return False
        if not isinstance(option.get("fresh_locked_rerun_required"), bool):
            return False
    if not option_ids_required.issubset(seen_ids):
        return False
    if domain == "provenance" and not _provenance_decision_context_ok(decision):
        return False
    if domain == "diagnostics" and not _diagnostic_decision_context_ok(decision, seen_ids):
        return False
    return decision.get("recommended_option") in seen_ids


def _provenance_decision_context_ok(decision: dict[str, Any]) -> bool:
    evidence = decision.get("outlet_scope_evidence")
    if not isinstance(evidence, dict) or evidence.get("available") is not True:
        return False
    if evidence.get("reference_area_source") != "usgs_site_drainage_area":
        return False
    if evidence.get("authority_area_class") != "selected_terminal_partial_basin_all_terminal_matches_authoritative_area":
        return False
    for key in ("selected_fraction_of_authority_area", "all_terminal_fraction_of_authority_area"):
        if not isinstance(evidence.get(key), (int, float)):
            return False
    if float(evidence["selected_fraction_of_authority_area"]) >= 0.90:
        return False
    if not 0.90 <= float(evidence["all_terminal_fraction_of_authority_area"]) <= 1.10:
        return False
    if evidence.get("virtual_all_terminal_candidate_supported") is not True:
        return False
    if evidence.get("virtual_candidate_status") != "diagnostic_only_authority_required":
        return False
    if evidence.get("all_terminal_aggregation_valid") is not True:
        return False
    terminal_ids = evidence.get("virtual_terminal_gis_ids")
    if not isinstance(terminal_ids, list) or not terminal_ids:
        return False
    flags = evidence.get("evidence_flags")
    if not isinstance(flags, list) or not {
        "selected_terminal_partial_authoritative_area",
        "all_terminal_matches_authoritative_area",
        "virtual_all_terminal_candidate_available",
    }.issubset(set(flags)):
        return False
    required = evidence.get("required_before_claim")
    if not isinstance(required, list) or not {
        "document_gauge_outlet_is_represented_by_all_terminal_aggregation",
        "make_virtual_outlet_selection_explicit_in_outlet_provenance",
        "relock_benchmark_against_virtual_all_terminal_outlet",
        "rerun_clean_locked_txtinout_before_reporting_metrics",
    }.issubset(set(required)):
        return False
    return decision.get("recommended_option") == "authorize_virtual_all_terminal_outlet"


def _diagnostic_decision_context_ok(
    decision: dict[str, Any],
    seen_option_ids: set[str],
) -> bool:
    likely_domains_raw = decision.get("likely_process_domains")
    recommended_focus_raw = decision.get("recommended_focus")
    if not isinstance(likely_domains_raw, list) or not likely_domains_raw:
        return False
    if not isinstance(recommended_focus_raw, list) or not recommended_focus_raw:
        return False
    likely_domains = [
        str(domain)
        for domain in likely_domains_raw
        if isinstance(domain, str) and domain
    ]
    recommended_focus = [
        str(focus)
        for focus in recommended_focus_raw
        if isinstance(focus, str) and focus
    ]
    if len(likely_domains) != len(likely_domains_raw):
        return False
    if len(recommended_focus) != len(recommended_focus_raw):
        return False
    if not _diagnostic_decision_candidate_explanations_ok(decision, likely_domains):
        return False
    expected_options: list[str] = []
    if "soil_provenance_limited" in likely_domains:
        expected_options.append("repair_soil_provenance_before_parameter_attribution")
    if "forcing_or_area_high_runoff_demand" in likely_domains:
        expected_options.append("audit_high_observed_runoff_fraction_context")
    if "et_fraction_high" in likely_domains:
        expected_options.append("screen_pet_and_et_partition_controls")
    if "subsurface_partition_low" in likely_domains:
        expected_options.extend(
            [
                "screen_subsurface_partition_controls_after_soil_provenance",
                "screen_subsurface_partition_controls_with_retained_soil_provenance",
            ]
        )
    if "swat_water_yield_below_observed_runoff" in likely_domains:
        expected_options.append("diagnose_post_aggregation_water_balance_deficit")
    if not expected_options:
        return False
    if not any(option_id in seen_option_ids for option_id in expected_options):
        return False
    recommended = decision.get("recommended_option")
    if recommended in {"run_source_backed_diagnostic", "retain_exploratory_science_blocker"}:
        return False
    priority = [
        ("soil_provenance_limited", "repair_soil_provenance_before_parameter_attribution"),
        ("forcing_or_area_high_runoff_demand", "audit_high_observed_runoff_fraction_context"),
        ("et_fraction_high", "screen_pet_and_et_partition_controls"),
        ("subsurface_partition_low", None),
        ("swat_water_yield_below_observed_runoff", "diagnose_post_aggregation_water_balance_deficit"),
    ]
    for domain, option_id in priority:
        if domain not in likely_domains:
            continue
        if option_id is None:
            return str(recommended).startswith("screen_subsurface_partition_controls_")
        return recommended == option_id
    return False


def _diagnostic_decision_candidate_explanations_ok(
    decision: dict[str, Any],
    likely_domains: list[str],
) -> bool:
    explanations = decision.get("candidate_explanations")
    if not isinstance(explanations, list) or not explanations:
        return False
    explained_domains: set[str] = set()
    for item in explanations:
        if not isinstance(item, dict):
            return False
        domain = item.get("domain")
        if not isinstance(domain, str) or not domain:
            return False
        explained_domains.add(domain)
        for field in ("status", "evidence", "next_action", "claim_impact"):
            if not isinstance(item.get(field), str) or not item.get(field):
                return False
        if item.get("fresh_locked_rerun_required") is not True:
            return False
    return set(likely_domains).issubset(explained_domains)


def _pipeline_improvement_diagnostic_context_rows(report: dict[str, Any]) -> tuple[int, int]:
    plan = report.get("pipeline_improvement_plan")
    if not isinstance(plan, dict):
        return 0, 0
    rows = [
        basin_item
        for item in plan.get("items", [])
        if isinstance(item, dict) and item.get("domain") == "diagnostics"
        for basin_item in item.get("basin_items", [])
        if isinstance(basin_item, dict)
    ]
    ok = sum(
        1
        for basin_item in rows
        if _pipeline_improvement_decision_request_ok(
            basin_item.get("decision_request"),
            basin_item,
        )
    )
    return ok, len(rows)


def _pipeline_improvement_diagnostic_explanation_rows(report: dict[str, Any]) -> tuple[int, int]:
    plan = report.get("pipeline_improvement_plan")
    if not isinstance(plan, dict):
        return 0, 0
    rows = [
        basin_item
        for item in plan.get("items", [])
        if isinstance(item, dict) and item.get("domain") == "diagnostics"
        for basin_item in item.get("basin_items", [])
        if isinstance(basin_item, dict)
    ]
    ok = 0
    for basin_item in rows:
        decision = basin_item.get("decision_request")
        if not isinstance(decision, dict):
            continue
        likely_domains = [
            str(domain)
            for domain in decision.get("likely_process_domains", [])
            if isinstance(domain, str) and domain
        ]
        if likely_domains and _diagnostic_decision_candidate_explanations_ok(decision, likely_domains):
            ok += 1
    return ok, len(rows)


def _pipeline_improvement_provenance_context_rows(report: dict[str, Any]) -> tuple[int, int]:
    plan = report.get("pipeline_improvement_plan")
    if not isinstance(plan, dict):
        return 0, 0
    rows = [
        basin_item
        for item in plan.get("items", [])
        if isinstance(item, dict) and item.get("domain") == "provenance"
        for basin_item in item.get("basin_items", [])
        if isinstance(basin_item, dict)
    ]
    ok = sum(
        1
        for basin_item in rows
        if _pipeline_improvement_decision_request_ok(
            basin_item.get("decision_request"),
            basin_item,
        )
    )
    return ok, len(rows)


def _row_physical_gate_artifact_ok(row: dict[str, Any]) -> bool:
    payload = _load_json_path(row.get("physical_gates_path"))
    if not payload or not _path_exists(row.get("physical_gates_path")):
        return False
    row_status = str(row.get("physical_gates") or "")
    payload_status = str(payload.get("status") or "")
    if row_status != payload_status:
        return False
    row_codes_raw = row.get("physical_condition_codes")
    row_codes = [str(code) for code in row_codes_raw] if isinstance(row_codes_raw, list) else []
    payload_codes_raw = payload.get("condition_codes")
    payload_codes = [str(code) for code in payload_codes_raw] if isinstance(payload_codes_raw, list) else []
    if sorted(row_codes) != sorted(payload_codes):
        return False
    if payload_status == "passed":
        return payload.get("pass") is True and not payload_codes
    if payload_status == "failed":
        dominant = payload.get("dominant_blocker")
        return payload.get("pass") is False and bool(payload_codes) and str(dominant or "") in payload_codes
    return payload_status in {"not_run", "warning"} and payload.get("pass") is False


def _row_hydrograph_ok(row: dict[str, Any]) -> bool:
    if str(row.get("calibration")) not in {"attempted", "done", "verified"}:
        return False
    has_plot = _path_exists(row.get("hydrograph_comparison_plot")) or _path_exists(
        row.get("hydrograph_comparison_plot_pdf")
    ) or _path_exists(
        row.get("hydrograph_observed_simulated_calibrated_plot")
    ) or _path_exists(
        row.get("hydrograph_observed_simulated_calibrated_plot_pdf")
    )
    has_metrics = _path_exists(row.get("hydrograph_comparison_metrics"))
    return has_plot and has_metrics


def _row_calibration_provenance_ok(row: dict[str, Any]) -> bool:
    if str(row.get("calibration")) not in {"attempted", "done", "verified"}:
        return False
    return _path_exists(row.get("calibration_provenance_path"))


def _row_sensitivity_screen_ok(row: dict[str, Any]) -> bool:
    if str(row.get("calibration")) not in {"attempted", "done", "verified"}:
        return False
    if str(row.get("sensitivity_screen_basis") or "") != "basin_specific":
        return False
    classes = row.get("sensitivity_activity_classes")
    return isinstance(classes, dict) and bool(classes)


def _research_grade_core_sensitivity_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("tier") or "") == "research_grade"]


def _row_research_grade_core_sensitivity_ok(row: dict[str, Any]) -> bool:
    if str(row.get("tier") or "") != "research_grade":
        return False
    if str(row.get("sensitivity_screen_basis") or "") != "basin_specific":
        return False
    classes = row.get("sensitivity_effective_classes")
    if not isinstance(classes, dict) or not classes:
        classes = row.get("sensitivity_activity_classes")
    if not isinstance(classes, dict) or not classes:
        return False
    normalized_classes = {str(name).upper(): str(activity) for name, activity in classes.items()}
    required_core = {
        name
        for name in FULL_MODE_CORE_PARAMETERS
        if FULL_MODE_PARAMETER_GOVERNANCE[name].activity_class != "dead"
    }
    dead_core = {
        name
        for name in FULL_MODE_CORE_PARAMETERS
        if FULL_MODE_PARAMETER_GOVERNANCE[name].activity_class == "dead"
    }
    if required_core - set(normalized_classes):
        return False
    provenance_payload = _load_json_path(row.get("calibration_provenance_path"))
    provenance = provenance_payload.get("provenance")
    blocked_parameters: set[str] = set()
    if isinstance(provenance, dict) and isinstance(provenance.get("blocked_parameters"), list):
        blocked_parameters.update(str(item).upper() for item in provenance["blocked_parameters"])
    for name in dead_core:
        if normalized_classes.get(name) == "dead" or name in blocked_parameters:
            continue
        return False
    return any(
        str(activity) in {"active", "weak", "limited"}
        for activity in normalized_classes.values()
    )


def _row_calibration_delta_ok(row: dict[str, Any]) -> bool:
    if str(row.get("calibration")) not in {"attempted", "done", "verified"}:
        return False
    required = (
        "baseline_kge",
        "baseline_nse",
        "baseline_pbias",
        "kge",
        "nse",
        "pbias",
        "delta_kge",
        "delta_nse",
        "delta_pbias",
    )
    return all(isinstance(row.get(key), (int, float)) for key in required)


def _row_calibration_regression_ok(row: dict[str, Any]) -> bool:
    if str(row.get("primary_blocker") or "") != "calibration_regressed":
        return False
    delta_kge = row.get("delta_kge")
    delta_nse = row.get("delta_nse")
    return (
        str(row.get("calibration")) in {"attempted", "done", "verified"}
        and isinstance(delta_kge, (int, float))
        and isinstance(delta_nse, (int, float))
        and float(delta_kge) <= 0.0
        and float(delta_nse) <= 0.0
        and _path_exists(row.get("calibration_provenance_path"))
    )


def _calibration_regression_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = []
    for row in rows:
        delta_kge = row.get("delta_kge")
        delta_nse = row.get("delta_nse")
        if (
            str(row.get("calibration")) in {"attempted", "done", "verified"}
            and isinstance(delta_kge, (int, float))
            and isinstance(delta_nse, (int, float))
            and float(delta_kge) <= 0.0
            and float(delta_nse) <= 0.0
        ):
            required.append(row)
    return required


def _promotion_gate_failure_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("calibration") or "") == "blocked_by_promotion_gate"
    ]


def _row_promotion_gate_failure_ok(row: dict[str, Any]) -> bool:
    message = str(row.get("calibration_failure_message") or "")
    return (
        str(row.get("calibration") or "") == "blocked_by_promotion_gate"
        and bool(row.get("calibration_failure_phase"))
        and "promotion gates" in message
        and str(row.get("calibration_final_metrics_authority") or "") == "none"
        and row.get("temporary_candidate_metrics_allowed_as_final") is False
        and _path_exists(row.get("calibration_provenance_path"))
    )


def _failed_calibration_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("calibration") or "")
        in {"attempted", "blocked_by_volume_gate", "blocked_by_promotion_gate"}
    ]


def _failed_calibration_context_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("calibration") or "")
        in {"attempted", "blocked_by_volume_gate", "blocked_by_promotion_gate"}
    ]


def _row_failed_calibration_context_ok(row: dict[str, Any]) -> bool:
    calibration = str(row.get("calibration") or "")
    if calibration not in {"attempted", "blocked_by_volume_gate", "blocked_by_promotion_gate"}:
        return False
    history_csv = row.get("calibration_failure_history_csv")
    n_evaluations = row.get("calibration_failure_n_evaluations")
    promotion_gate = row.get("calibration_failure_promotion_gate")
    volume_pass_count = row.get("calibration_failure_volume_gate_pass_count")
    physical_pass_count = row.get("calibration_failure_physical_gate_pass_count")
    best_abs_pbias = row.get("calibration_failure_best_abs_pbias")
    best_parameters = row.get("calibration_failure_best_parameters")
    best_bound_context = row.get("calibration_failure_best_parameter_bound_context")
    physical_codes = row.get("calibration_failure_physical_condition_code_counts")
    dominant_counts = row.get("calibration_failure_physical_dominant_blocker_counts")
    return (
        isinstance(history_csv, str)
        and bool(history_csv)
        and isinstance(n_evaluations, int)
        and n_evaluations >= 0
        and isinstance(promotion_gate, dict)
        and bool(promotion_gate)
        and isinstance(volume_pass_count, int)
        and volume_pass_count >= 0
        and isinstance(physical_pass_count, int)
        and physical_pass_count >= 0
        and isinstance(best_abs_pbias, (int, float))
        and float(best_abs_pbias) >= 0
        and bool(row.get("calibration_failure_best_phase"))
        and isinstance(best_parameters, dict)
        and bool(best_parameters)
        and isinstance(best_bound_context, dict)
        and isinstance(best_bound_context.get("evaluated_parameters"), dict)
        and set(best_parameters).issubset(set(best_bound_context.get("evaluated_parameters", {})))
        and isinstance(physical_codes, dict)
        and isinstance(dominant_counts, dict)
    )


def _calibration_phase_coverage_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("calibration_failure_history_csv"), str)
        and bool(row.get("calibration_failure_history_csv"))
    ]


def _row_calibration_phase_coverage_ok(row: dict[str, Any]) -> bool:
    expected = _history_phase_coverage_summary(row.get("calibration_failure_history_csv"))
    if not expected:
        return False
    return (
        row.get("calibration_phase_parameter_coverage") == expected["parameter_coverage"]
        and row.get("calibration_phase_evaluation_counts") == expected["evaluation_counts"]
        and row.get("calibration_phase_order") == expected["phase_order"]
        and row.get("calibration_phase_volume_gate_pass_counts")
        == expected["volume_gate_pass_counts"]
        and row.get("calibration_phase_physical_gate_pass_counts")
        == expected["physical_gate_pass_counts"]
        and row.get("calibration_phase_process_gate_pass_counts")
        == expected["process_gate_pass_counts"]
    )


def _history_phase_coverage_summary(history_csv: object) -> dict[str, dict[str, Any]]:
    if not isinstance(history_csv, str) or not history_csv:
        return {}
    history_path = Path(history_csv)
    if not history_path.is_absolute():
        history_path = ROOT / history_path
    if not history_path.is_file():
        return {}
    parameter_coverage: dict[str, set[str]] = {}
    evaluation_counts: dict[str, int] = {}
    phase_order: dict[str, int] = {}
    volume_pass_counts: dict[str, int] = {}
    physical_pass_counts: dict[str, int] = {}
    process_pass_counts: dict[str, int] = {}
    try:
        with history_path.open(encoding="utf-8", newline="") as handle:
            for history_row in csv.DictReader(handle):
                phase = str(history_row.get("phase") or "unknown").strip() or "unknown"
                evaluation_counts[phase] = evaluation_counts.get(phase, 0) + 1
                order = _safe_int_or_none(history_row.get("phase_order"))
                if order is not None:
                    phase_order[phase] = min(order, phase_order.get(phase, order))
                parameters = [
                    param.strip()
                    for param in str(history_row.get("phase_parameters") or "").split(",")
                    if param.strip()
                ]
                if not parameters:
                    parameters = sorted(
                        key.removeprefix("param_")
                        for key, value in history_row.items()
                        if key.startswith("param_") and str(value).strip()
                    )
                parameter_coverage.setdefault(phase, set()).update(parameters)
                if _csv_bool(history_row.get("volume_gate_passed")):
                    volume_pass_counts[phase] = volume_pass_counts.get(phase, 0) + 1
                if _csv_bool(history_row.get("physical_gate_passed")):
                    physical_pass_counts[phase] = physical_pass_counts.get(phase, 0) + 1
                if _csv_bool(history_row.get("calibration_process_gate_passed")):
                    process_pass_counts[phase] = process_pass_counts.get(phase, 0) + 1
    except Exception:
        return {}
    if not evaluation_counts:
        return {}
    return {
        "parameter_coverage": {
            phase: sorted(parameters)
            for phase, parameters in sorted(parameter_coverage.items())
            if parameters
        },
        "evaluation_counts": evaluation_counts,
        "phase_order": phase_order,
        "volume_gate_pass_counts": volume_pass_counts,
        "physical_gate_pass_counts": physical_pass_counts,
        "process_gate_pass_counts": process_pass_counts,
    }


def _safe_int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _csv_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def _row_failed_calibration_tradeoff_frontier_ok(row: dict[str, Any]) -> bool:
    if str(row.get("calibration") or "") not in {
        "attempted",
        "blocked_by_volume_gate",
        "blocked_by_promotion_gate",
    }:
        return False
    frontier = row.get("calibration_failure_skill_tradeoff_frontier")
    if not isinstance(frontier, dict):
        return False
    required = {"best_abs_pbias", "best_kge", "best_nse"}
    if not required.issubset(set(frontier)):
        return False
    for label in required:
        item = frontier.get(label)
        if not isinstance(item, dict):
            return False
        metrics = item.get("metrics")
        params = item.get("parameters")
        if not isinstance(metrics, dict) or not isinstance(params, dict) or not params:
            return False
        if not any(isinstance(metrics.get(name), (int, float)) for name in ("kge", "nse", "pbias")):
            return False
        if item.get("diagnostic_only") is not True:
            return False
        if not isinstance(item.get("volume_gate_passed"), bool):
            return False
        if not isinstance(item.get("physical_gate_passed"), bool):
            return False
    return True


_TERMINAL_SCOPE_CANDIDATE_HISTORY_FIELDS = {
    "metric_selected_terminal_fraction_of_all_terminal_flow",
    "metric_selected_terminal_nse",
    "metric_selected_terminal_kge",
    "metric_selected_terminal_pbias",
    "metric_all_terminal_nse",
    "metric_all_terminal_kge",
    "metric_all_terminal_pbias",
    "metric_all_terminal_volume_gate_passes_diagnostic",
}


def _failed_calibration_terminal_scope_history_required_rows(
    rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        row
        for row in _failed_calibration_context_required_rows(rows)
        if _history_has_terminal_scope_candidate_metrics(row.get("calibration_failure_history_csv"))
    ]


def _history_has_terminal_scope_candidate_metrics(history_csv: object) -> bool:
    if not isinstance(history_csv, str) or not history_csv:
        return False
    history_path = Path(history_csv)
    if not history_path.is_absolute():
        history_path = ROOT / history_path
    if not history_path.is_file():
        return False
    try:
        with history_path.open(encoding="utf-8", newline="") as handle:
            fields = set(csv.DictReader(handle).fieldnames or [])
    except Exception:
        return False
    return _TERMINAL_SCOPE_CANDIDATE_HISTORY_FIELDS.issubset(fields)


def _row_failed_calibration_terminal_scope_history_ok(row: dict[str, Any]) -> bool:
    frontier = row.get("calibration_failure_skill_tradeoff_frontier")
    if not isinstance(frontier, dict) or not frontier:
        return False
    for item in frontier.values():
        if not isinstance(item, dict):
            continue
        terminal = item.get("terminal_scope_metrics")
        if not isinstance(terminal, dict):
            continue
        selected = terminal.get("selected_terminal")
        all_terminal = terminal.get("all_terminal")
        if not isinstance(selected, dict) or not isinstance(all_terminal, dict):
            continue
        if terminal.get("claim_impact") != "diagnostic_only_not_final_claim_evidence":
            continue
        if not isinstance(terminal.get("selected_terminal_fraction_of_all_terminal_flow"), (int, float)):
            continue
        if not any(isinstance(selected.get(name), (int, float)) for name in ("nse", "kge", "pbias")):
            continue
        if not any(isinstance(all_terminal.get(name), (int, float)) for name in ("nse", "kge", "pbias")):
            continue
        if not isinstance(all_terminal.get("volume_gate_passes_diagnostic"), bool):
            continue
        return True
    return False


def _calibration_bound_interaction_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("calibration_bound_interaction_screen_json")
    ]


def _row_calibration_bound_interaction_ok(row: dict[str, Any]) -> bool:
    metrics = row.get("calibration_bound_interaction_best_metrics")
    parameters = row.get("calibration_bound_interaction_best_parameters")
    count = row.get("calibration_bound_interaction_candidate_count")
    return (
        _path_exists(row.get("calibration_bound_interaction_screen_json"))
        and isinstance(count, int)
        and count > 0
        and isinstance(row.get("calibration_bound_interaction_best_label"), str)
        and isinstance(parameters, dict)
        and bool(parameters)
        and isinstance(metrics, dict)
        and all(isinstance(metrics.get(name), (int, float)) for name in ("nse", "kge", "pbias"))
        and str(row.get("calibration_bound_interaction_claim_status") or "").startswith("diagnostic_only")
    )


def _failed_calibration_physical_trace_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in _failed_calibration_context_required_rows(rows)
        if _history_objective_trace_has_candidate_physical_gate(row.get("calibration_failure_history_csv"))
    ]


def _failed_calibration_process_trace_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in _failed_calibration_context_required_rows(rows)
        if _history_has_candidate_process_gate(row.get("calibration_failure_history_csv"))
    ]


def _row_failed_calibration_physical_trace_ok(row: dict[str, Any]) -> bool:
    condition_counts = row.get("calibration_failure_physical_condition_code_counts")
    dominant_counts = row.get("calibration_failure_physical_dominant_blocker_counts")
    return (
        isinstance(condition_counts, dict)
        and bool(condition_counts)
        and isinstance(dominant_counts, dict)
        and bool(dominant_counts)
    )


def _row_failed_calibration_process_trace_ok(row: dict[str, Any]) -> bool:
    process_pass_count = row.get("calibration_failure_process_gate_pass_count")
    process_counts = row.get("calibration_failure_process_condition_code_counts")
    return (
        isinstance(process_pass_count, int)
        and process_pass_count >= 0
        and isinstance(process_counts, dict)
    )


def _history_objective_trace_has_candidate_physical_gate(history_csv: object) -> bool:
    if not isinstance(history_csv, str) or not history_csv:
        return False
    history_path = Path(history_csv)
    if not history_path.is_absolute():
        history_path = REPO_ROOT / history_path
    trace_dir = history_path.with_name("objective_runs")
    if not trace_dir.is_dir():
        return False
    for trace in trace_dir.glob("*_objective_trace.json"):
        payload = _load_json_path(str(trace))
        if isinstance(payload.get("candidate_physical_gate"), dict):
            return True
    return False


def _history_has_candidate_process_gate(history_csv: object) -> bool:
    if not isinstance(history_csv, str) or not history_csv:
        return False
    history_path = Path(history_csv)
    if not history_path.is_absolute():
        history_path = REPO_ROOT / history_path
    if history_path.is_file():
        try:
            with history_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = set(reader.fieldnames or [])
        except Exception:
            fields = set()
        if {
            "calibration_process_gate_passed",
            "calibration_process_condition_codes",
        } & fields:
            return True
    trace_dir = history_path.with_name("objective_runs")
    if not trace_dir.is_dir():
        return False
    for trace in trace_dir.glob("*_objective_trace.json"):
        payload = _load_json_path(str(trace))
        gate = payload.get("candidate_physical_gate")
        if not isinstance(gate, dict):
            continue
        if (
            "calibration_process_gate_pass" in gate
            or "calibration_process_condition_codes" in gate
            or isinstance(gate.get("condition_codes"), list)
        ):
            return True
    return False


def _row_failed_calibration_evidence_ok(row: dict[str, Any]) -> bool:
    calibration = str(row.get("calibration") or "")
    authority = str(row.get("calibration_final_metrics_authority") or "")
    authority_ok = bool(authority)
    if calibration in {"blocked_by_volume_gate", "blocked_by_promotion_gate"}:
        authority_ok = authority == "none"
    return (
        calibration in {"attempted", "blocked_by_volume_gate", "blocked_by_promotion_gate"}
        and bool(row.get("calibration_failure_phase"))
        and bool(row.get("calibration_failure_message"))
        and authority_ok
        and row.get("temporary_candidate_metrics_allowed_as_final") is False
        and _path_exists(row.get("calibration_provenance_path"))
    )


def _calibration_precheck_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("calibration") or "")
        in {
            "attempted",
            "done",
            "verified",
            "blocked_by_volume_gate",
            "blocked_by_promotion_gate",
            "blocked_by_physical_gates",
            "blocked_by_routing_flow_gates",
        }
    ]


def _row_calibration_precheck_ok(row: dict[str, Any]) -> bool:
    calibration = str(row.get("calibration") or "")
    sequence = str(row.get("calibration_precheck_sequence") or "")
    physical_status = str(row.get("calibration_precheck_physical_gates_status") or "")
    routing_status = str(row.get("calibration_precheck_routing_flow_gates_status") or "")
    if calibration not in {
        "attempted",
        "done",
        "verified",
        "blocked_by_volume_gate",
        "blocked_by_promotion_gate",
        "blocked_by_physical_gates",
        "blocked_by_routing_flow_gates",
    }:
        return False
    return (
        bool(sequence)
        and sequence != "unknown"
        and physical_status in {"passed", "failed", "warning", "not_run", "unknown"}
        and routing_status in {"passed", "failed", "warning", "not_run", "unknown"}
    )


def _row_volume_diagnostics_ok(row: dict[str, Any]) -> bool:
    primary = str(row.get("primary_blocker") or "")
    codes = row.get("physical_condition_codes")
    needs_volume_diagnostics = primary.startswith("simulated_volume_") or (
        isinstance(codes, list) and "VOLUME_BIAS" in codes
    )
    if not needs_volume_diagnostics:
        return False
    flags = row.get("volume_bias_diagnostic_flags")
    actions = row.get("volume_bias_next_actions")
    payload = _load_json_path(row.get("volume_bias_diagnostics_path"))
    alternatives = payload.get("source_backed_alternatives")
    probe_order = payload.get("recommended_probe_order")
    return (
        _path_exists(row.get("volume_bias_diagnostics_path"))
        and isinstance(flags, list)
        and bool(flags)
        and isinstance(actions, list)
        and bool(actions)
        and isinstance(alternatives, list)
        and bool(alternatives)
        and isinstance(probe_order, list)
        and bool(probe_order)
    )


def _volume_diagnostic_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = []
    for row in rows:
        primary = str(row.get("primary_blocker") or "")
        codes = row.get("physical_condition_codes")
        if primary.startswith("simulated_volume_") or (isinstance(codes, list) and "VOLUME_BIAS" in codes):
            required.append(row)
    return required


def _terminal_hydrograph_scope_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required_flags = {
        "selected_terminal_partial_of_all_terminal_flow",
        "all_terminal_routed_to_channel_reference_matches",
        "all_terminal_hydrograph_volume_closer",
        "all_terminal_hydrograph_volume_gate_passes_diagnostic",
        "all_terminal_hydrograph_aggregation_not_claim_valid",
        "all_terminal_hydrograph_volume_better_skill_worse",
        "all_terminal_hydrograph_skill_limited_after_volume_correction",
    }
    return [
        row
        for row in rows
        if isinstance(row.get("volume_bias_diagnostic_flags"), list)
        and bool(required_flags & set(row.get("volume_bias_diagnostic_flags", [])))
    ]


def _row_terminal_hydrograph_scope_ok(row: dict[str, Any]) -> bool:
    scope = row.get("terminal_hydrograph_scope")
    if not isinstance(scope, dict):
        return False
    selected = scope.get("selected_terminal")
    all_terminal = scope.get("all_terminal")
    if not isinstance(selected, dict) or not isinstance(all_terminal, dict):
        return False

    def metrics_ok(metrics: dict[str, Any]) -> bool:
        return (
            metrics.get("available") is True
            and isinstance(metrics.get("n_days"), int)
            and metrics.get("n_days", 0) > 0
            and isinstance(metrics.get("pbias_pct"), (int, float))
            and isinstance(metrics.get("nse"), (int, float))
            and isinstance(metrics.get("kge"), (int, float))
            and isinstance(metrics.get("sim_to_obs_volume_ratio"), (int, float))
        )

    return (
        scope.get("available") is True
        and scope.get("diagnostic_only") is True
        and scope.get("claim_impact")
        == "outlet_and_routing_claims_remain_blocked_until_selected_terminal_scope_is_explained"
        and isinstance(scope.get("terminal_ids"), list)
        and len(scope.get("terminal_ids") or []) >= 2
        and isinstance(scope.get("selected_outlet_gis_id"), int)
        and isinstance(scope.get("pbias_abs_improvement_pct_points"), (int, float))
        and metrics_ok(selected)
        and metrics_ok(all_terminal)
    )


def _row_terminal_hydrograph_kge_component_ok(row: dict[str, Any]) -> bool:
    scope = row.get("terminal_hydrograph_scope")
    if not isinstance(scope, dict):
        return False
    selected = scope.get("selected_terminal")
    all_terminal = scope.get("all_terminal")
    if not isinstance(selected, dict) or not isinstance(all_terminal, dict):
        return False

    def components_ok(metrics: dict[str, Any]) -> bool:
        components = metrics.get("kge_components")
        dominant = metrics.get("kge_dominant_deficit")
        if not isinstance(components, dict):
            return False
        required = {
            "method",
            "kge",
            "r",
            "alpha",
            "beta",
            "correlation_deficit",
            "variability_deficit",
            "bias_deficit",
        }
        return (
            required.issubset(components)
            and components.get("method") == "kge_2009_components"
            and (dominant in {"correlation", "variability", "bias"} or dominant is None)
        )

    return components_ok(selected) and components_ok(all_terminal)


def _row_terminal_hydrograph_aggregation_context_ok(row: dict[str, Any]) -> bool:
    scope = row.get("terminal_hydrograph_scope")
    if not isinstance(scope, dict):
        return False
    return (
        isinstance(scope.get("all_terminal_aggregation_valid"), bool)
        and isinstance(scope.get("all_terminal_aggregation_reason"), str)
        and bool(scope.get("all_terminal_aggregation_reason"))
        and isinstance(scope.get("terminal_failure_class"), str)
        and bool(scope.get("terminal_failure_class"))
        and isinstance(scope.get("shared_upstream_area_km2"), (int, float))
    )


def _row_terminal_hydrograph_scope_class_ok(row: dict[str, Any]) -> bool:
    cls = row.get("terminal_hydrograph_scope_class")
    flags = row.get("terminal_hydrograph_scope_flags")
    focus = row.get("terminal_hydrograph_scope_recommended_focus")
    impact = row.get("terminal_hydrograph_scope_claim_impact")
    if cls not in {
        "selected_metric_passes_but_area_scope_partial",
        "all_terminal_volume_corrected_but_skill_limited",
        "all_terminal_volume_corrected_but_outlet_scope_unresolved",
        "all_terminal_volume_deficit_persists_after_valid_aggregation",
        "all_terminal_volume_improves_but_gate_unresolved",
        "nearest_terminal_volume_corrected_but_outlet_scope_unresolved",
        "terminal_topology_overlap_invalidates_aggregation",
        "terminal_hydrograph_scope_unresolved",
    }:
        return False
    return (
        isinstance(flags, list)
        and bool(flags)
        and isinstance(focus, list)
        and bool(focus)
        and impact == "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
    )


def _row_terminal_scope_resolution_plan_ok(row: dict[str, Any]) -> bool:
    plan = row.get("terminal_scope_resolution_plan")
    if not isinstance(plan, dict):
        return False
    selected = plan.get("selected_terminal")
    all_terminal = plan.get("all_terminal")
    required = plan.get("required_before_promotion")
    decision = plan.get("decision_type")
    next_experiment = plan.get("next_experiment")
    if not isinstance(selected, dict) or not isinstance(all_terminal, dict):
        return False
    allowed_decisions = {
        "selected_outlet_scope_authority_required",
        "all_terminal_volume_diagnostic_not_claim_authority",
        "post_aggregation_process_deficit",
        "all_terminal_volume_improves_but_still_not_claim_authority",
        "nearest_terminal_candidate_requires_authority",
        "terminal_topology_repair_required",
        "terminal_scope_unresolved",
    }
    return (
        plan.get("available") is True
        and plan.get("status") == "blocked_until_resolved"
        and plan.get("diagnostic_only") is True
        and plan.get("terminal_scope_blocker") in {
            "outlet_scope_volume_mismatch",
            "multi_terminal_volume_deficit",
            "terminal_topology_overlap",
        }
        and plan.get("scope_class") == row.get("terminal_hydrograph_scope_class")
        and decision in allowed_decisions
        and isinstance(next_experiment, str)
        and bool(next_experiment)
        and isinstance(required, list)
        and "keep_all_terminal_and_nearest_metrics_diagnostic_only" in required
        and plan.get("fresh_locked_rerun_required") is True
        and plan.get("temporary_terminal_metrics_allowed_as_final") is False
        and plan.get("all_terminal_metrics_claim_authority") is False
        and plan.get("nearest_terminal_metrics_claim_authority") is False
        and isinstance(selected.get("pbias_pct"), (int, float))
        and isinstance(all_terminal.get("pbias_pct"), (int, float))
    )


def _nearest_terminal_hydrograph_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("terminal_hydrograph_scope"), dict)
        and isinstance(row["terminal_hydrograph_scope"].get("nearest_terminal"), dict)
    ]


def _row_nearest_terminal_hydrograph_ok(row: dict[str, Any]) -> bool:
    scope = row.get("terminal_hydrograph_scope")
    if not isinstance(scope, dict):
        return False
    nearest = scope.get("nearest_terminal")
    if not isinstance(nearest, dict):
        return False
    for key in ("pbias_pct", "nse", "kge"):
        if not isinstance(nearest.get(key), (int, float)):
            return False
    if not isinstance(scope.get("nearest_vs_selected_pbias_abs_improvement_pct_points"), (int, float)):
        return False
    probes = row.get("volume_recommended_probe_order")
    if not isinstance(probes, list):
        return False
    return any(
        isinstance(probe, dict)
        and probe.get("diagnostic") == "audit_selected_vs_nearest_terminal_hydrographs"
        for probe in probes
    )


def _post_aggregation_volume_deficit_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = []
    for row in rows:
        if row.get("primary_blocker") != "multi_terminal_volume_deficit":
            continue
        scope = row.get("terminal_hydrograph_scope")
        if not isinstance(scope, dict) or scope.get("all_terminal_aggregation_valid") is False:
            continue
        selected = scope.get("selected_terminal")
        all_terminal = scope.get("all_terminal")
        if not isinstance(selected, dict) or not isinstance(all_terminal, dict):
            continue
        selected_pbias = selected.get("pbias_pct")
        all_pbias = all_terminal.get("pbias_pct")
        if not isinstance(selected_pbias, (int, float)) or not isinstance(all_pbias, (int, float)):
            continue
        if abs(float(all_pbias)) > 30.0 and abs(float(all_pbias)) < abs(float(selected_pbias)):
            required.append(row)
    return required


def _row_post_aggregation_volume_deficit_ok(row: dict[str, Any]) -> bool:
    flags = row.get("volume_bias_diagnostic_flags")
    if not isinstance(flags, list) or "all_terminal_hydrograph_volume_deficit_persists" not in flags:
        return False
    probes = row.get("volume_recommended_probe_order")
    alternatives = row.get("volume_source_backed_alternatives")
    if not isinstance(probes, list) or not isinstance(alternatives, list):
        return False
    if not _row_volume_forcing_context_ok(row):
        return False
    has_probe = any(
        isinstance(probe, dict)
        and probe.get("diagnostic") == "diagnose_post_aggregation_water_balance_deficit"
        and probe.get("fresh_output_required") is True
        for probe in probes
    )
    has_alternative = any(
        isinstance(alt, dict)
        and alt.get("option") == "diagnose_post_aggregation_water_balance_deficit"
        and alt.get("fresh_output_required") is True
        and isinstance(alt.get("parameters"), list)
        and bool(alt.get("parameters"))
        for alt in alternatives
    )
    return has_probe and has_alternative


def _row_post_aggregation_process_context_ok(row: dict[str, Any]) -> bool:
    context = row.get("post_aggregation_process_context")
    if not isinstance(context, dict):
        return False
    domains = context.get("likely_process_domains")
    focus = context.get("recommended_focus")
    required = context.get("required_before_claim")
    return (
        context.get("available") is True
        and context.get("status") == "diagnostic_only_process_or_forcing_blocker"
        and context.get("claim_authority") is False
        and context.get("temporary_metrics_allowed_as_final") is False
        and context.get("fresh_locked_rerun_required") is True
        and context.get("scope_class") == "all_terminal_volume_deficit_persists_after_valid_aggregation"
        and isinstance(context.get("all_terminal_pbias_pct"), (int, float))
        and isinstance(context.get("swat_net_wateryld_to_precip"), (int, float))
        and isinstance(domains, list)
        and bool(domains)
        and isinstance(focus, list)
        and bool(focus)
        and isinstance(required, list)
        and "document_post_aggregation_volume_deficit_source" in required
    )


def _row_post_aggregation_candidate_explanations_ok(row: dict[str, Any]) -> bool:
    context = row.get("post_aggregation_process_context")
    if not isinstance(context, dict) or context.get("available") is not True:
        return False
    domains = context.get("likely_process_domains")
    explanations = context.get("candidate_explanations")
    if not isinstance(domains, list) or not domains:
        return False
    if not isinstance(explanations, list) or not explanations:
        return False
    explained_domains: set[str] = set()
    for item in explanations:
        if not isinstance(item, dict):
            return False
        domain = item.get("domain")
        if not isinstance(domain, str) or not domain:
            return False
        explained_domains.add(domain)
        for field in ("status", "evidence", "next_action", "claim_impact"):
            if not isinstance(item.get(field), str) or not item.get(field):
                return False
        if item.get("fresh_locked_rerun_required") is not True:
            return False
    return set(str(domain) for domain in domains).issubset(explained_domains)


def _row_volume_forcing_context_ok(row: dict[str, Any]) -> bool:
    weather_path = row.get("weather_forcing_summary_path")
    weather = row.get("weather_forcing_summary")
    if not _path_exists(weather_path) or not isinstance(weather, dict):
        return False
    precipitation = weather.get("precipitation")
    if (
        not isinstance(precipitation, dict)
        or precipitation.get("available") is not True
        or not isinstance(precipitation.get("station_count"), int)
        or precipitation.get("station_count", 0) <= 0
        or not isinstance(precipitation.get("mean_areal_total_precip_mm"), (int, float))
    ):
        return False
    observed = weather.get("observed_runoff")
    return (
        isinstance(observed, dict)
        and observed.get("available") is True
        and isinstance(observed.get("observed_runoff_depth_mm"), (int, float))
        and isinstance(observed.get("precip_overlap_total_mm"), (int, float))
        and isinstance(observed.get("observed_runoff_to_overlap_precip_ratio"), (int, float))
    )


def _row_volume_forcing_plausibility_ok(row: dict[str, Any]) -> bool:
    weather = row.get("weather_forcing_summary")
    if not isinstance(weather, dict):
        return False
    observed = weather.get("observed_runoff")
    if not isinstance(observed, dict):
        return False
    ratio_class = observed.get("runoff_precip_ratio_class")
    claim_impact = observed.get("runoff_precip_ratio_claim_impact")
    rationale = observed.get("runoff_precip_ratio_rationale")
    return (
        ratio_class
        in {
            "observed_runoff_exceeds_precipitation",
            "high_observed_runoff_fraction",
            "very_low_observed_runoff_fraction",
            "ordinary_observed_runoff_fraction",
        }
        and isinstance(claim_impact, str)
        and bool(claim_impact)
        and isinstance(rationale, str)
        and bool(rationale)
    )


def _high_runoff_demand_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = []
    for row in _volume_diagnostic_required_rows(rows):
        weather = row.get("weather_forcing_summary")
        if not isinstance(weather, dict):
            continue
        observed = weather.get("observed_runoff")
        if isinstance(observed, dict) and observed.get("runoff_precip_ratio_class") == "high_observed_runoff_fraction":
            required.append(row)
    return required


def _row_high_runoff_demand_context_ok(row: dict[str, Any]) -> bool:
    context = row.get("high_runoff_demand_context")
    if not isinstance(context, dict) or context.get("available") is not True:
        return False
    required_numeric = {
        "observed_runoff_to_overlap_precip_ratio",
        "observed_runoff_depth_mm",
        "precip_overlap_total_mm",
        "observed_area_km2",
        "swat_net_wateryld_to_precip",
        "swat_surface_runoff_to_precip",
        "swat_lateral_flow_to_precip",
        "swat_percolation_to_precip",
        "swat_et_to_precip",
        "swat_snowfall_to_precip",
        "swat_snowmelt_to_precip",
        "swat_snowpack_to_precip",
        "swat_snowfall_mm",
        "swat_snowmelt_mm",
        "swat_snowpack_mm",
        "swat_soil_water_change_mm",
        "swat_lagged_lateral_flow_mm",
        "swat_groundwater_soil_flow_mm",
        "aquifer_flow_mean_mm",
        "aquifer_flow_max_mm",
        "aquifer_storage_mean_mm",
        "aquifer_recharge_mean_mm",
        "aquifer_revap_mean_mm",
        "selected_terminal_fraction_of_all_terminal_flow",
        "all_terminal_upstream_area_km2",
        "observed_area_to_all_terminal_area_ratio",
    }
    return (
        context.get("runoff_precip_ratio_class") == "high_observed_runoff_fraction"
        and context.get("aquifer_context_available") is True
        and all(isinstance(context.get(key), (int, float)) for key in required_numeric)
        and context.get("recommended_probe") == "audit_high_observed_runoff_fraction_context"
        and isinstance(context.get("claim_impact"), str)
        and bool(context.get("claim_impact"))
        and isinstance(context.get("rationale"), str)
        and bool(context.get("rationale"))
    )


def _row_high_runoff_interpretation_ok(row: dict[str, Any]) -> bool:
    context = row.get("high_runoff_demand_context")
    if not isinstance(context, dict) or context.get("available") is not True:
        return False
    flags = context.get("interpretation_flags")
    if not isinstance(flags, list):
        return False
    codes = {flag.get("code") for flag in flags if isinstance(flag, dict)}
    required = {
        "swat_water_yield_far_below_observed_runoff_fraction",
        "snow_storage_not_explaining_high_runoff_demand",
        "aquifer_release_absent_for_high_runoff_demand",
        "selected_terminal_partial_during_high_runoff_demand",
    }
    candidate_explanations = context.get("candidate_explanations")
    if not isinstance(candidate_explanations, list) or len(candidate_explanations) < 5:
        return False
    hypotheses = {
        item.get("hypothesis")
        for item in candidate_explanations
        if isinstance(item, dict)
    }
    required_hypotheses = {
        "precipitation_area_or_external_inflow_basis",
        "snow_storage_or_snowmelt_release",
        "groundwater_or_aquifer_release",
        "selected_terminal_scope",
        "model_water_yield_deficit",
    }
    required_before_claim = context.get("required_before_claim")
    if not isinstance(required_before_claim, list) or not {
        "retain_high_runoff_context_as_diagnostic_only",
        "audit_precipitation_area_snow_storage_aquifer_and_external_inflow_before_parameter_attribution",
        "run_fresh_locked_rerun_after_high_runoff_repair",
    }.issubset(set(required_before_claim)):
        return False
    return (
        required.issubset(codes)
        and required_hypotheses.issubset(hypotheses)
        and all(
        isinstance(flag.get("evidence"), str) and bool(flag.get("evidence"))
        for flag in flags
        if isinstance(flag, dict) and flag.get("code") in required
        )
        and all(
            isinstance(item.get("status"), str)
            and bool(item.get("status"))
            and isinstance(item.get("next_action"), str)
            and bool(item.get("next_action"))
            and isinstance(item.get("claim_impact"), str)
            and bool(item.get("claim_impact"))
            and isinstance(item.get("fresh_locked_rerun_required"), bool)
            for item in candidate_explanations
            if isinstance(item, dict) and item.get("hypothesis") in required_hypotheses
        )
    )


def _row_terminal_scope_blocker_ok(row: dict[str, Any]) -> bool:
    return row.get("terminal_scope_blocker") in {
        "outlet_scope_volume_mismatch",
        "multi_terminal_volume_deficit",
        "terminal_topology_overlap",
    }


def _terminal_scope_claim_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _row_terminal_scope_blocker_ok(row)]


def _row_terminal_scope_claim_blocked_ok(row: dict[str, Any]) -> bool:
    blocked = row.get("blocked_claim_names")
    return isinstance(blocked, list) and "terminal_scope_claim" in {str(name) for name in blocked}


def _virtual_outlet_scope_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if (
            str(row.get("outlet_scope") or "") == "virtual_all_terminal"
            or str(row.get("outlet_policy") or "") == "all_terminal_sum"
            or (
                isinstance(row.get("virtual_outlet_scope_gate"), dict)
                and bool(row.get("virtual_outlet_scope_gate"))
            )
        )
    ]


def _row_virtual_outlet_scope_gate_ok(row: dict[str, Any]) -> bool:
    gate = row.get("virtual_outlet_scope_gate")
    blockers = row.get("virtual_outlet_scope_gate_blockers")
    selected_ids = row.get("selected_outlet_gis_ids")
    status = row.get("virtual_outlet_scope_gate_status")
    if not isinstance(gate, dict) or gate.get("applicable") is not True:
        return False
    if status not in {"passed", "failed"} or gate.get("status") != status:
        return False
    if row.get("outlet_scope") != "virtual_all_terminal":
        return False
    if row.get("outlet_policy") != "all_terminal_sum":
        return False
    if not isinstance(selected_ids, list) or not selected_ids:
        return False
    if not isinstance(blockers, list):
        return False
    gate_blockers = gate.get("blockers")
    if isinstance(gate_blockers, list) and blockers != [str(item) for item in gate_blockers if isinstance(item, str)]:
        return False
    if status == "passed":
        return gate.get("passed") is True and not blockers
    return gate.get("passed") is False and bool(blockers)


def _routing_terminal_scope_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required_flags = {
        "selected_terminal_partial_of_all_terminal_flow",
        "all_terminal_routed_to_channel_reference_matches",
    }
    return [
        row
        for row in rows
        if str(row.get("routing_flow_gates") or "") in {"failed", "warning"}
        and isinstance(row.get("routing_flow_diagnostic_flags"), list)
        and bool(required_flags & set(row.get("routing_flow_diagnostic_flags", [])))
    ]


def _row_terminal_scope_probe_priority_ok(row: dict[str, Any]) -> bool:
    probes = row.get("volume_recommended_probe_order")
    if not isinstance(probes, list) or len(probes) < 2:
        return False
    diagnostics = [
        probe.get("diagnostic") if isinstance(probe, dict) else None
        for probe in probes
    ]
    terminal_diagnostics = {
        "audit_outlet_selection_against_terminal_inventory",
        "audit_selected_vs_nearest_terminal_hydrographs",
        "audit_terminal_topology_overlap_before_aggregation",
        "audit_selected_vs_all_terminal_hydrographs",
    }
    if diagnostics[0] != "audit_outlet_selection_against_terminal_inventory":
        return False
    if "audit_selected_vs_all_terminal_hydrographs" not in diagnostics:
        return False
    first_non_terminal_idx = next(
        (idx for idx, diagnostic in enumerate(diagnostics) if diagnostic not in terminal_diagnostics),
        len(diagnostics),
    )
    selected_idx = diagnostics.index("audit_selected_vs_all_terminal_hydrographs")
    if selected_idx >= first_non_terminal_idx:
        return False
    if row.get("terminal_scope_blocker") == "terminal_topology_overlap":
        if "audit_terminal_topology_overlap_before_aggregation" not in diagnostics:
            return False
        topology_idx = diagnostics.index("audit_terminal_topology_overlap_before_aggregation")
        if topology_idx >= selected_idx:
            return False
    return True


def _row_skill_diagnostics_ok(row: dict[str, Any]) -> bool:
    primary = str(row.get("primary_blocker") or "")
    codes = row.get("physical_condition_codes")
    calibration = str(row.get("calibration") or "")
    needs_skill_diagnostics = primary in {"BELOW_RESEARCH_SKILL", "NEGATIVE_SKILL"} or (
        calibration in {"attempted", "done", "verified"}
        and isinstance(codes, list)
        and bool({"BELOW_RESEARCH_SKILL", "NEGATIVE_SKILL"} & set(codes))
    )
    if not needs_skill_diagnostics:
        return False
    flags = row.get("skill_diagnostic_flags")
    actions = row.get("skill_next_actions")
    alternatives = row.get("skill_source_backed_alternatives")
    probe_order = row.get("skill_recommended_probe_order")
    return (
        _path_exists(row.get("skill_diagnostics_json"))
        and _path_exists(row.get("skill_diagnostics_md"))
        and isinstance(flags, list)
        and bool(flags)
        and isinstance(actions, list)
        and bool(actions)
        and isinstance(alternatives, list)
        and bool(alternatives)
        and isinstance(probe_order, list)
        and bool(probe_order)
    )


def _row_skill_limitation_class_ok(row: dict[str, Any]) -> bool:
    cls = row.get("skill_limitation_class")
    flags = row.get("skill_limitation_flags")
    impact = row.get("skill_limitation_claim_impact")
    focus = row.get("skill_limitation_recommended_focus")
    component = row.get("skill_limitation_dominant_kge_component")
    evidence_metrics = row.get("skill_evidence_metrics")
    if not isinstance(cls, str) or not cls:
        return False
    if not isinstance(flags, list) or not flags or not all(isinstance(flag, str) and flag for flag in flags):
        return False
    if not isinstance(impact, str) or not impact:
        return False
    if not isinstance(focus, list) or not all(isinstance(item, str) and item for item in focus):
        return False
    if not isinstance(evidence_metrics, list) or not any(
        isinstance(metric, dict) and metric.get("method") == "kge_2009_components"
        for metric in evidence_metrics
    ):
        return False
    if "kge_dominant_correlation_deficit" in flags:
        if "snow_timing_mismatch" in flags and (
            "peak_timing_lag" in flags or "high_flow_peak_attenuation" in flags
        ):
            return component == "correlation" and cls == "snow_timing_and_peak_response"
        return component == "correlation" and cls in {
            "correlation_timing_peak_attenuation",
            "mixed_skill_limitation",
        }
    if "kge_dominant_variability_deficit" in flags:
        return component == "variability"
    if "kge_dominant_bias_deficit" in flags:
        return component == "bias"
    return cls != "no_rule_based_skill_limitation"


def _row_skill_parameter_governance_ok(row: dict[str, Any]) -> bool:
    required = _skill_parameter_governance_required(row)
    if not required:
        return False
    unsupported = row.get("unsupported_skill_parameters")
    blocked = row.get("blocked_skill_parameters")
    return (
        isinstance(unsupported, list)
        and isinstance(blocked, list)
        and set(required["unsupported"]).issubset({str(value) for value in unsupported})
        and set(required["blocked"]).issubset({str(value) for value in blocked})
    )


def _skill_parameter_governance_required(row: dict[str, Any]) -> dict[str, list[str]]:
    payload = _load_json_path(row.get("skill_diagnostics_json"))
    flags = payload.get("diagnostic_flags")
    if not isinstance(flags, list):
        return {"unsupported": [], "blocked": []}
    unsupported: list[str] = []
    blocked: list[str] = []
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
    return {"unsupported": sorted(set(unsupported)), "blocked": sorted(set(blocked))}


def _skill_parameter_governance_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if any(_skill_parameter_governance_required(row).values())
    ]


def _current_bridge_supported_parameters() -> set[str]:
    try:
        from swatplus_builder.full_mode.parameter_bridge import WRITERS
    except Exception:
        return set()
    return {str(name) for name in WRITERS}


def _superseded_skill_parameter_required(row: dict[str, Any]) -> list[str]:
    required = _skill_parameter_governance_required(row)
    row_unsupported = row.get("unsupported_skill_parameters")
    unsupported = set(required["unsupported"])
    if isinstance(row_unsupported, list):
        unsupported.update(str(name) for name in row_unsupported if isinstance(name, str) and name)
    supported = _current_bridge_supported_parameters()
    return sorted(name for name in unsupported if name in supported)


def _superseded_skill_parameter_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _superseded_skill_parameter_required(row)]


def _row_superseded_skill_parameter_ok(row: dict[str, Any]) -> bool:
    expected = set(_superseded_skill_parameter_required(row))
    actual = row.get("superseded_unsupported_skill_parameters")
    return isinstance(actual, list) and expected.issubset({str(value) for value in actual})


def _skill_diagnostic_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = []
    for row in rows:
        primary = str(row.get("primary_blocker") or "")
        codes = row.get("physical_condition_codes")
        calibration = str(row.get("calibration") or "")
        if primary in {"BELOW_RESEARCH_SKILL", "NEGATIVE_SKILL"} or (
            calibration in {"attempted", "done", "verified"}
            and isinstance(codes, list)
            and bool({"BELOW_RESEARCH_SKILL", "NEGATIVE_SKILL"} & set(codes))
        ):
            required.append(row)
    return required


def _skill_probe_gap_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("skill_source_backed_alternatives"), list)
        and bool(row.get("skill_source_backed_alternatives"))
    ]


def _row_skill_probe_gap_ok(row: dict[str, Any]) -> bool:
    gaps = row.get("skill_probe_gap_parameters")
    effective = row.get("sensitivity_effective_classes")
    if not isinstance(gaps, list) or not isinstance(effective, dict):
        return False
    suggested: list[str] = []
    for alt in row.get("skill_source_backed_alternatives", []):
        if not isinstance(alt, dict):
            continue
        params = alt.get("parameters")
        if isinstance(params, list):
            suggested.extend(str(param) for param in params if isinstance(param, str) and param)
    usable = {"active", "weak", "limited", "requires_basin_screen"}
    expected = [
        param
        for param in dict.fromkeys(suggested)
        if str(effective.get(param) or "") not in usable
    ]
    return expected == [str(param) for param in gaps]


def _skill_sensitivity_triage_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("skill_probe_gap_parameters"), list)
        and bool(row.get("skill_probe_gap_parameters"))
    ]


def _row_skill_sensitivity_triage_ok(row: dict[str, Any]) -> bool:
    gaps = row.get("skill_probe_gap_parameters")
    reasons = row.get("skill_probe_gap_reasons")
    screened_dead = row.get("skill_screened_dead_parameters")
    unscreened = row.get("skill_unscreened_suggested_parameters")
    classes = row.get("sensitivity_effective_classes")
    channel_classes = row.get("skill_channel_routing_activity_classes")
    if not (
        isinstance(gaps, list)
        and isinstance(reasons, dict)
        and isinstance(screened_dead, list)
        and isinstance(unscreened, list)
        and isinstance(classes, dict)
    ):
        return False
    merged_classes = {str(k): str(v) for k, v in classes.items()}
    if isinstance(channel_classes, dict):
        merged_classes.update({str(k): str(v) for k, v in channel_classes.items()})
    gap_names = [str(param) for param in gaps]
    expected_reasons = {
        param: str(merged_classes.get(param) or "not_screened")
        for param in gap_names
    }
    expected_dead = [param for param in gap_names if merged_classes.get(param) == "dead"]
    expected_unscreened = [param for param in gap_names if param not in merged_classes]
    return (
        expected_reasons == {str(k): str(v) for k, v in reasons.items()}
        and expected_dead == [str(param) for param in screened_dead]
        and expected_unscreened == [str(param) for param in unscreened]
    )


def _skill_evidence_metrics_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    for row in _skill_diagnostic_required_rows(rows):
        payload = _load_json_path(row.get("skill_diagnostics_json"))
        flags = payload.get("diagnostic_flags")
        if not isinstance(flags, list):
            continue
        if any(
            isinstance(flag, dict)
            and isinstance(flag.get("evidence_metrics"), dict)
            and bool(flag.get("evidence_metrics"))
            for flag in flags
        ):
            required.append(row)
    return required


def _row_skill_evidence_metrics_ok(row: dict[str, Any]) -> bool:
    payload = _load_json_path(row.get("skill_diagnostics_json"))
    flags = payload.get("diagnostic_flags")
    if not isinstance(flags, list):
        return False
    expected = [
        flag.get("evidence_metrics")
        for flag in flags
        if isinstance(flag, dict)
        and isinstance(flag.get("evidence_metrics"), dict)
        and bool(flag.get("evidence_metrics"))
    ]
    row_metrics = row.get("skill_evidence_metrics")
    return (
        bool(expected)
        and isinstance(row_metrics, list)
        and all(metric in row_metrics for metric in expected)
    )


def _skill_kge_component_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _skill_diagnostic_required_rows(rows)


def _row_skill_kge_component_ok(row: dict[str, Any]) -> bool:
    payload = _load_json_path(row.get("skill_diagnostics_json"))
    flags = payload.get("diagnostic_flags")
    if not isinstance(flags, list):
        return False
    component_metrics = [
        flag.get("evidence_metrics")
        for flag in flags
        if isinstance(flag, dict)
        and isinstance(flag.get("evidence_metrics"), dict)
        and flag.get("evidence_metrics", {}).get("method") == "kge_2009_components"
    ]
    row_metrics = row.get("skill_evidence_metrics")
    required_keys = {"kge", "r", "alpha", "beta", "correlation_deficit", "variability_deficit", "bias_deficit"}
    return (
        len(component_metrics) == 1
        and required_keys.issubset(component_metrics[0])
        and isinstance(row_metrics, list)
        and component_metrics[0] in row_metrics
    )


def _skill_channel_screen_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    for row in _skill_diagnostic_required_rows(rows):
        alternatives = row.get("skill_source_backed_alternatives")
        gaps = row.get("skill_probe_gap_parameters")
        has_channel_alternative = (
            isinstance(alternatives, list)
            and any(
                isinstance(alt, dict)
                and alt.get("option") == "screen_channel_routing_attenuation_controls"
                for alt in alternatives
            )
        )
        has_channel_gap = isinstance(gaps, list) and bool({"CH_N2", "CH_K2"} & {str(g) for g in gaps})
        if has_channel_alternative or has_channel_gap:
            required.append(row)
    return required


def _row_skill_channel_screen_ok(row: dict[str, Any]) -> bool:
    classes = row.get("skill_channel_routing_activity_classes")
    effects = row.get("skill_channel_routing_effect_sizes")
    bounds = row.get("skill_channel_routing_best_bounds")
    return (
        _path_exists(row.get("skill_channel_routing_screen_json"))
        and _path_exists(row.get("skill_channel_routing_screen_md"))
        and isinstance(classes, dict)
        and {"CH_N2", "CH_K2"}.issubset({str(key) for key in classes})
        and all(str(classes.get(param)) in {"active", "weak", "dead", "not_tested", "limited"} for param in ("CH_N2", "CH_K2"))
        and isinstance(effects, dict)
        and all(isinstance(effects.get(param), (int, float)) for param in ("CH_N2", "CH_K2"))
        and isinstance(bounds, dict)
        and all(isinstance(bounds.get(param), dict) for param in ("CH_N2", "CH_K2"))
    )


def _skill_channel_refinement_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("skill_channel_routing_calibration_verification_summary")
        or row.get("skill_channel_routing_calibration_best_solution_json")
    ]


def _row_skill_channel_refinement_ok(row: dict[str, Any]) -> bool:
    parameters = row.get("skill_channel_routing_calibration_parameters")
    metrics = row.get("skill_channel_routing_calibration_metrics")
    deltas = row.get("skill_channel_routing_calibration_deltas")
    improved = row.get("skill_channel_routing_calibration_improved")
    return (
        _path_exists(row.get("skill_channel_routing_calibration_verification_summary"))
        and _path_exists(row.get("skill_channel_routing_calibration_best_solution_json"))
        and isinstance(parameters, dict)
        and bool({"CH_N2", "CH_K2"} & {str(key) for key in parameters})
        and isinstance(metrics, dict)
        and all(isinstance(metrics.get(metric), (int, float)) for metric in ("nse", "kge", "pbias"))
        and isinstance(deltas, dict)
        and all(isinstance(deltas.get(metric), (int, float)) for metric in ("nse", "kge"))
        and isinstance(improved, bool)
    )


def _skill_bound_context_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    for row in _skill_diagnostic_required_rows(rows):
        payload = _load_json_path(row.get("skill_diagnostics_json"))
        bound_hits = payload.get("calibrated_parameter_bound_hits")
        if isinstance(bound_hits, dict) and bound_hits:
            required.append(row)
    return required


def _row_skill_bound_context_ok(row: dict[str, Any]) -> bool:
    payload = _load_json_path(row.get("skill_diagnostics_json"))
    expected_hits = payload.get("calibrated_parameter_bound_hits")
    expected_values = payload.get("calibrated_parameter_values")
    expected_impact = payload.get("parameter_bound_claim_impact")
    if not isinstance(expected_hits, dict) or not expected_hits:
        return False
    row_hits = row.get("skill_parameter_bound_hits")
    row_values = row.get("calibrated_skill_parameter_values")
    row_context = row.get("skill_parameter_bound_context")
    row_impact = row.get("skill_parameter_bound_claim_impact")
    return (
        isinstance(row_hits, dict)
        and bool(row_hits)
        and set(expected_hits).issubset(set(row_hits))
        and isinstance(row_values, dict)
        and isinstance(expected_values, dict)
        and set(expected_values).issubset(set(row_values))
        and isinstance(row_context, list)
        and bool(row_context)
        and row_impact == expected_impact
    )


def _skill_bound_aware_probe_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _skill_bound_context_required_rows(rows)


def _row_skill_bound_aware_probe_order_ok(row: dict[str, Any]) -> bool:
    probes = row.get("skill_recommended_probe_order")
    if not isinstance(probes, list) or not probes:
        return False
    first = probes[0]
    if not isinstance(first, dict):
        return False

    def exhausted(probe: dict[str, Any]) -> list[str]:
        values = probe.get("bound_exhausted_parameters")
        return [str(value) for value in values] if isinstance(values, list) else []

    def parameters(probe: dict[str, Any]) -> list[str]:
        values = probe.get("parameters")
        return [str(value) for value in values] if isinstance(values, list) else []

    def unexhausted(probe: dict[str, Any]) -> list[str]:
        values = probe.get("unexhausted_parameters")
        return [str(value) for value in values] if isinstance(values, list) else []

    def fully_exhausted(probe: dict[str, Any]) -> bool:
        return bool(exhausted(probe)) and not unexhausted(probe)

    seen_fully_exhausted = False
    for probe in probes:
        if not isinstance(probe, dict):
            return False
        if seen_fully_exhausted and parameters(probe) and not fully_exhausted(probe):
            return False
        if exhausted(probe):
            impact = probe.get("bound_exhaustion_claim_impact")
            if not isinstance(impact, str) or not impact:
                return False
            if not isinstance(probe.get("unexhausted_parameters"), list):
                return False
        if fully_exhausted(probe):
            seen_fully_exhausted = True
    return True


def _row_soil_realism_diagnostics_ok(row: dict[str, Any]) -> bool:
    if str(row.get("primary_blocker") or "") != "soil_realism_gate_failed":
        return False
    artifacts = row.get("build_diagnostic_artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return False
    soil_keys = {
        "overlay_repair_report",
        "soil_acquisition_report",
        "soil_realism_diagnostics",
        "soil_report",
    }
    for key, path in artifacts.items():
        if key not in soil_keys or not _path_exists(path):
            continue
        payload = _load_json_path(path)
        priority = payload.get("source_priority")
        alternatives = payload.get("source_backed_alternatives")
        probe_order = payload.get("recommended_probe_order")
        if (
            isinstance(priority, list)
            and any(
                isinstance(item, dict) and item.get("source") == "gNATSGO_raster_plus_SDA_horizons"
                for item in priority
            )
            and any(isinstance(item, dict) and item.get("source") == "SoilGrids_v2_coarse" for item in priority)
            and any(
                isinstance(item, dict) and item.get("source") == "synthetic_minimal_soils"
                for item in priority
            )
            and isinstance(alternatives, list)
            and any(
                isinstance(item, dict) and item.get("option") == "recover_gnatsgo_raster_plus_sda_horizons"
                for item in alternatives
            )
            and any(
                isinstance(item, dict) and item.get("option") == "use_soilgrids_v2_coarse_gap_fill"
                for item in alternatives
            )
            and any(
                isinstance(item, dict)
                and item.get("option") == "allow_synthetic_or_constant_soils_for_engine_diagnostics_only"
                for item in alternatives
            )
            and isinstance(probe_order, list)
            and bool(probe_order)
        ):
            return True
    return False


def _row_soil_realism_remediation_ok(row: dict[str, Any]) -> bool:
    if str(row.get("primary_blocker") or "") != "soil_realism_gate_failed":
        return False
    actions = row.get("soil_next_actions")
    alternatives = row.get("soil_source_backed_alternatives")
    probe_order = row.get("soil_recommended_probe_order")
    if not (
        isinstance(actions, list)
        and any(isinstance(item, str) and item.strip() for item in actions)
        and isinstance(alternatives, list)
        and isinstance(probe_order, list)
        and probe_order
    ):
        return False
    options = {
        str(item.get("option"))
        for item in alternatives
        if isinstance(item, dict) and item.get("option")
    }
    return {
        "recover_gnatsgo_raster_plus_sda_horizons",
        "use_soilgrids_v2_coarse_gap_fill",
        "allow_synthetic_or_constant_soils_for_engine_diagnostics_only",
    }.issubset(options)


def _row_soil_fidelity_provenance_ok(row: dict[str, Any]) -> bool:
    gates_failed = row.get("gates_failed")
    if not isinstance(gates_failed, list) or "soil_fidelity" not in gates_failed:
        return False
    if str(row.get("primary_blocker") or "") == "soil_realism_gate_failed":
        return (
            row.get("soil_mode") == "not_verified"
            and row.get("soil_provenance_mode") == "soil_realism_gate_failed"
            and isinstance(row.get("build_diagnostic_artifacts"), dict)
            and bool(row.get("build_diagnostic_artifacts"))
        )
    fallback = row.get("pct_fallback_soils")
    artifacts = row.get("build_diagnostic_artifacts")
    has_soil_report = (
        isinstance(artifacts, dict)
        and "soil_report" in artifacts
        and _path_exists(artifacts.get("soil_report"))
    )
    soil_report = _load_json_path(artifacts.get("soil_report") if isinstance(artifacts, dict) else None)
    priority = soil_report.get("source_priority")
    source_priority_ok = (
        isinstance(priority, list)
        and any(isinstance(row, dict) and row.get("source") == "gNATSGO_raster_plus_SDA_horizons" for row in priority)
        and any(isinstance(row, dict) and row.get("source") == "SoilGrids_v2_coarse" for row in priority)
        and any(isinstance(row, dict) and row.get("source") == "synthetic_minimal_soils" for row in priority)
    )
    return (
        bool(row.get("soil_mode"))
        and isinstance(fallback, (int, float))
        and 0.0 <= float(fallback) <= 1.0
        and has_soil_report
        and source_priority_ok
    )


def _soil_fidelity_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("gates_failed"), list) and "soil_fidelity" in row.get("gates_failed", [])
    ]


def _row_routing_diagnostics_ok(row: dict[str, Any]) -> bool:
    status = str(row.get("routing_flow_gates") or "")
    if status not in {"failed", "warning"}:
        return False
    flags = row.get("routing_flow_diagnostic_flags")
    payload = _load_json_path(row.get("routing_flow_gates_path"))
    trace = _load_json_path(payload.get("json_path"))
    alternatives = trace.get("source_backed_alternatives")
    probe_order = trace.get("recommended_probe_order")
    return (
        _path_exists(row.get("routing_flow_gates_path"))
        and bool(row.get("routing_flow_closure_status"))
        and isinstance(flags, list)
        and bool(flags)
        and isinstance(alternatives, list)
        and bool(alternatives)
        and isinstance(probe_order, list)
        and bool(probe_order)
    )


def _row_routing_source_coverage_ok(row: dict[str, Any]) -> bool:
    status = str(row.get("routing_flow_gates") or "")
    if status not in {"failed", "warning"}:
        return False
    payload = _load_json_path(row.get("routing_flow_gates_path"))
    basin_rows = payload.get("mass_trace_basin_wb_row_count")
    channel_rows = payload.get("mass_trace_channel_row_count")
    selected_rows = payload.get("mass_trace_selected_channel_row_count")
    terminal_rows = payload.get("mass_trace_terminal_channel_row_count")
    basin_years = payload.get("mass_trace_basin_wb_years")
    channel_years = payload.get("mass_trace_channel_years")
    return (
        isinstance(basin_rows, int)
        and basin_rows > 0
        and isinstance(channel_rows, int)
        and channel_rows > 0
        and isinstance(selected_rows, int)
        and selected_rows > 0
        and isinstance(terminal_rows, int)
        and terminal_rows > 0
        and isinstance(basin_years, list)
        and bool(basin_years)
        and isinstance(channel_years, list)
        and bool(channel_years)
    )


def _routing_unit_semantics_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("routing_flow_diagnostic_flags"), list)
        and "routing_unit_outflow_unit_semantics_suspect" in row.get("routing_flow_diagnostic_flags", [])
    ]


def _row_routing_unit_semantics_ok(row: dict[str, Any]) -> bool:
    payload = _load_json_path(row.get("routing_flow_gates_path"))
    trace = _load_json_path(payload.get("json_path"))
    flags = trace.get("flags")
    ratio = trace.get("ru_outflow_to_basin_wateryld_ratio")
    return (
        isinstance(flags, list)
        and "routing_unit_outflow_unit_semantics_suspect" in flags
        and isinstance(ratio, (int, float))
        and float(ratio) > 1000.0
    )


def _row_terminal_inventory_ok(row: dict[str, Any]) -> bool:
    flags = row.get("routing_flow_diagnostic_flags")
    if not isinstance(flags, list) or "multiple_terminal_outlets_present" not in flags:
        return False
    payload = _load_json_path(row.get("terminal_trace_path"))
    missing = payload.get("missing_terminal_gis_ids")
    has_missing = isinstance(missing, list) and bool(missing)
    if has_missing:
        if not isinstance(row.get("orphan_terminal_gis_ids"), list):
            return False
        if not isinstance(row.get("material_missing_terminal_gis_ids"), list):
            return False
        if not isinstance(row.get("missing_terminal_upstream_area_km2"), (int, float)):
            return False
    return _path_exists(row.get("terminal_trace_path")) and bool(row.get("terminal_failure_class"))


def _terminal_inventory_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("routing_flow_diagnostic_flags"), list)
        and "multiple_terminal_outlets_present" in row.get("routing_flow_diagnostic_flags", [])
    ]


def _row_terminal_area_context_ok(row: dict[str, Any]) -> bool:
    required = [
        "terminal_basin_nldi_area_km2",
        "terminal_delineated_area_km2",
        "selected_terminal_upstream_area_km2",
        "all_terminal_upstream_area_km2",
        "selected_terminal_fraction_of_nldi_area",
        "all_terminal_fraction_of_nldi_area",
        "delineated_fraction_of_nldi_area",
        "selected_terminal_fraction_of_delineated_area",
        "all_terminal_fraction_of_delineated_area",
    ]
    for key in required:
        value = row.get(key)
        if not isinstance(value, (int, float)):
            return False
        if float(value) <= 0:
            return False
    selected_area = float(row["selected_terminal_upstream_area_km2"])
    all_area = float(row["all_terminal_upstream_area_km2"])
    return selected_area <= all_area


def _row_terminal_area_scope_class_ok(row: dict[str, Any]) -> bool:
    cls = row.get("terminal_area_scope_class")
    flags = row.get("terminal_area_scope_flags")
    impact = row.get("terminal_area_scope_claim_impact")
    if not isinstance(cls, str) or not cls:
        return False
    if not isinstance(flags, list) or not all(isinstance(flag, str) and flag for flag in flags):
        return False
    if not isinstance(impact, str) or not impact:
        return False
    selected_nldi = row.get("selected_terminal_fraction_of_nldi_area")
    all_nldi = row.get("all_terminal_fraction_of_nldi_area")
    if not isinstance(selected_nldi, (int, float)) or not isinstance(all_nldi, (int, float)):
        return cls == "terminal_area_context_incomplete"
    if float(selected_nldi) < 0.90 and float(all_nldi) >= 0.90:
        return (
            cls == "selected_terminal_partial_basin_all_terminal_matches"
            and "selected_terminal_partial_nldi_area" in flags
            and "all_terminal_matches_nldi_area" in flags
        )
    if float(selected_nldi) < 0.90 and float(all_nldi) < 0.90:
        return (
            cls == "selected_and_all_terminal_area_deficit"
            and "selected_terminal_partial_nldi_area" in flags
            and "all_terminal_nldi_area_deficit" in flags
        )
    if float(selected_nldi) >= 0.90 and float(all_nldi) >= 0.90:
        return cls == "selected_terminal_area_matches_basin"
    return cls == "terminal_area_scope_ambiguous"


def _row_terminal_authority_area_context_ok(row: dict[str, Any]) -> bool:
    check = row.get("terminal_authority_area_check")
    if not isinstance(check, dict):
        return False
    if check.get("available") is not True:
        return False
    if check.get("reference_area_source") != "usgs_site_drainage_area":
        return False
    cls = check.get("class")
    flags = check.get("flags")
    impact = check.get("claim_impact")
    if not isinstance(cls, str) or not cls:
        return False
    if not isinstance(flags, list) or not all(isinstance(flag, str) and flag for flag in flags):
        return False
    if not isinstance(impact, str) or not impact:
        return False
    for key in (
        "usgs_site_drainage_area_km2",
        "usgs_site_drainage_area_sqmi",
        "selected_terminal_fraction_of_usgs_site_area",
        "all_terminal_fraction_of_usgs_site_area",
    ):
        value = row.get(key)
        if not isinstance(value, (int, float)) or float(value) <= 0:
            return False
    selected = float(row["selected_terminal_fraction_of_usgs_site_area"])
    all_terminal = float(row["all_terminal_fraction_of_usgs_site_area"])
    if abs(float(check.get("selected_fraction", -1.0)) - selected) > 1e-9:
        return False
    if abs(float(check.get("all_terminal_fraction", -1.0)) - all_terminal) > 1e-9:
        return False
    if selected < 0.90 and all_terminal >= 0.90:
        return (
            cls == "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
            and "selected_terminal_partial_usgs_site_area" in flags
            and "all_terminal_matches_usgs_site_area" in flags
        )
    if selected >= 0.90:
        return cls == "selected_terminal_matches_authoritative_area"
    return cls == "selected_and_all_terminal_authoritative_area_deficit"


def _terminal_virtual_outlet_candidate_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    for row in _terminal_inventory_required_rows(rows):
        check = row.get("terminal_authority_area_check")
        if (
            isinstance(check, dict)
            and check.get("class") == "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
        ):
            required.append(row)
    return required


def _row_terminal_virtual_outlet_candidate_ok(row: dict[str, Any]) -> bool:
    candidate = row.get("terminal_virtual_outlet_candidate")
    if not isinstance(candidate, dict):
        return False
    if candidate.get("available") is not True:
        return False
    if candidate.get("status") != "diagnostic_only_authority_required":
        return False
    if candidate.get("candidate_type") != "all_terminal_virtual_outlet":
        return False
    if candidate.get("claim_authority") is not False:
        return False
    if candidate.get("temporary_terminal_metrics_allowed_as_final") is not False:
        return False
    if candidate.get("fresh_locked_rerun_required") is not True:
        return False
    terminal_ids = candidate.get("terminal_gis_ids")
    if not isinstance(terminal_ids, list) or len(terminal_ids) < 2:
        return False
    required = candidate.get("required_before_claim")
    if not isinstance(required, list):
        return False
    for item in (
        "make_virtual_outlet_selection_explicit_in_outlet_provenance",
        "relock_benchmark_against_virtual_all_terminal_outlet",
        "rerun_clean_locked_txtinout_before_reporting_metrics",
    ):
        if item not in required:
            return False
    path = row.get("terminal_virtual_outlet_candidate_path")
    return _path_exists(path)


def _row_terminal_gauge_context_ok(row: dict[str, Any]) -> bool:
    source = row.get("terminal_gauge_coordinate_source")
    if not isinstance(source, str) or not source:
        return False
    if not isinstance(row.get("terminal_gauge_lat"), (int, float)):
        return False
    if not isinstance(row.get("terminal_gauge_lon"), (int, float)):
        return False
    if not isinstance(row.get("selected_outlet_distance_to_gauge_m"), (int, float)):
        return False
    if not isinstance(row.get("nearest_terminal_gis_id"), int):
        return False
    if not isinstance(row.get("selected_outlet_is_nearest_terminal"), bool):
        return False
    payload = _load_json_path(row.get("terminal_trace_path"))
    if payload.get("gauge_coordinate_source") != source:
        return False
    inventory = payload.get("terminal_inventory")
    if not isinstance(inventory, list) or not inventory:
        return False
    nearest = [item for item in inventory if isinstance(item, dict) and item.get("is_nearest_terminal") is True]
    if len(nearest) != 1:
        return False
    return any(
        isinstance(item, dict) and isinstance(item.get("distance_to_usgs_outlet_m"), (int, float))
        for item in inventory
    )


def _not_nearest_terminal_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("terminal_gauge_coordinate_source"), str)
        and row.get("selected_outlet_is_nearest_terminal") is False
    ]


def _row_not_nearest_terminal_probe_ok(row: dict[str, Any]) -> bool:
    alternatives = row.get("routing_source_backed_alternatives")
    probes = row.get("routing_recommended_probe_order")
    if not isinstance(alternatives, list) or not isinstance(probes, list) or not probes:
        return False
    expected = "audit_selected_terminal_against_nearest_gauge_terminal"
    if probes[0].get("diagnostic") != expected:
        return False
    if not any(isinstance(alt, dict) and alt.get("option") == expected for alt in alternatives):
        return False
    return isinstance(row.get("nearest_terminal_gis_id"), int) and isinstance(
        row.get("selected_outlet_distance_to_gauge_m"), (int, float)
    )


def _row_terminal_outlet_conflict_class_ok(row: dict[str, Any]) -> bool:
    cls = row.get("terminal_outlet_conflict_class")
    flags = row.get("terminal_outlet_conflict_flags")
    impact = row.get("terminal_outlet_conflict_claim_impact")
    if cls not in {
        "selected_terminal_missing",
        "nearest_terminal_context_missing",
        "selected_terminal_is_nearest_gauge_terminal",
        "selected_largest_terminal_not_nearest_minor_branch_conflict",
        "selected_largest_terminal_not_nearest_gauge_terminal",
        "selected_terminal_not_nearest_and_not_dominant",
    }:
        return False
    if not isinstance(flags, list) or not all(isinstance(flag, str) and flag for flag in flags):
        return False
    if not isinstance(impact, str) or not impact:
        return False
    if row.get("selected_outlet_is_nearest_terminal") is False:
        return (
            cls
            in {
                "selected_largest_terminal_not_nearest_minor_branch_conflict",
                "selected_largest_terminal_not_nearest_gauge_terminal",
                "selected_terminal_not_nearest_and_not_dominant",
            }
            and "selected_terminal_not_nearest_gauge_terminal" in flags
            and impact.startswith("terminal_scope_claim_blocked_until_")
        )
    return True


def _terminal_topology_overlap_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("terminal_scope_blocker") or row.get("primary_blocker") or "")
        == "terminal_topology_overlap"
    ]


def _row_terminal_topology_overlap_ok(row: dict[str, Any]) -> bool:
    pairs = row.get("terminal_overlap_pairs")
    shared_area = row.get("terminal_shared_upstream_area_km2")
    pair_count = row.get("terminal_overlap_pair_count")
    if not isinstance(shared_area, (int, float)) or float(shared_area) <= 0:
        return False
    if not isinstance(pair_count, int) or pair_count <= 0:
        return False
    if not isinstance(pairs, list) or len(pairs) != pair_count:
        return False
    first = pairs[0]
    if not isinstance(first, dict):
        return False
    return (
        isinstance(first.get("terminal_a_gis_id"), int)
        and isinstance(first.get("terminal_b_gis_id"), int)
        and isinstance(first.get("shared_upstream_area_km2"), (int, float))
        and float(first.get("shared_upstream_area_km2")) > 0
        and isinstance(first.get("shared_channel_count"), int)
        and first.get("shared_channel_count") > 0
        and isinstance(first.get("shared_channel_ids"), list)
    )


def _routed_to_channel_semantics_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("routing_flow_diagnostic_flags"), list)
        and "routed_to_channel_reference_matches_terminal" in row.get("routing_flow_diagnostic_flags", [])
    ]


def _row_routed_to_channel_semantics_ok(row: dict[str, Any]) -> bool:
    ratio = row.get("routed_to_channel_closure_ratio")
    reference = row.get("routing_closure_reference")
    payload = _load_json_path(row.get("routing_flow_gates_path"))
    trace = _load_json_path(payload.get("json_path"))
    trace_ratio = trace.get("routed_to_channel_closure_ratio")
    trace_routed_m3 = trace.get("basin_routed_to_channel_m3")
    flags = trace.get("flags")
    alternatives = trace.get("source_backed_alternatives")
    return (
        reference == "basin_wateryld_m3"
        and isinstance(ratio, (int, float))
        and isinstance(trace_ratio, (int, float))
        and isinstance(trace_routed_m3, (int, float))
        and isinstance(flags, list)
        and "routed_to_channel_reference_matches_terminal" in flags
        and isinstance(alternatives, list)
        and any(
            isinstance(item, dict)
            and item.get("option") == "audit_basin_wateryld_vs_routed_to_channel_semantics"
            for item in alternatives
        )
    )


def _routing_status_mismatch_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("routing_flow_gate_status_mismatch") is True
        or row.get("routing_flow_closure_mismatch") is True
    ]


def _row_routing_status_mismatch_ok(row: dict[str, Any]) -> bool:
    if not _path_exists(row.get("routing_flow_gates_path")):
        return False
    payload = _load_json_path(row.get("routing_flow_gates_path"))
    artifact_status = payload.get("status")
    artifact_closure = payload.get("closure_status")
    evidence_status = row.get("routing_flow_gates_evidence_status")
    evidence_closure = row.get("routing_flow_closure_evidence_status")
    status_mismatch = bool(artifact_status and evidence_status and artifact_status != evidence_status)
    closure_mismatch = bool(artifact_closure and evidence_closure and artifact_closure != evidence_closure)
    return (
        row.get("routing_flow_gate_status_mismatch") is status_mismatch
        and row.get("routing_flow_closure_mismatch") is closure_mismatch
    )


def _routing_diagnostic_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("routing_flow_gates") or "") in {"failed", "warning"}]


def _row_et_context_ok(row: dict[str, Any]) -> bool:
    codes = row.get("physical_condition_codes")
    if not isinstance(codes, list) or "ET_DOMINATED" not in codes:
        return False
    flags = row.get("sensitivity_context_flags")
    effective = row.get("sensitivity_effective_classes")
    return (
        isinstance(flags, list)
        and "et_dominated_pet_esco_epco_probe_required" in flags
        and isinstance(effective, dict)
        and all(effective.get(name) == "requires_basin_screen" for name in ("PET_CO", "ESCO", "EPCO"))
    )


def _row_et_diagnostics_ok(row: dict[str, Any]) -> bool:
    codes = row.get("physical_condition_codes")
    if not isinstance(codes, list) or "ET_DOMINATED" not in codes:
        return False
    flags = row.get("et_partition_diagnostic_flags")
    actions = row.get("et_partition_next_actions")
    payload = _load_json_path(row.get("et_partition_diagnostics_path"))
    alternatives = payload.get("source_backed_alternatives")
    probe_order = payload.get("recommended_probe_order")
    gate_context = payload.get("gate_context")
    row_gate_context = row.get("et_partition_gate_context")
    return (
        _path_exists(row.get("et_partition_diagnostics_path"))
        and isinstance(flags, list)
        and bool(flags)
        and isinstance(actions, list)
        and bool(actions)
        and isinstance(alternatives, list)
        and bool(alternatives)
        and isinstance(probe_order, list)
        and bool(probe_order)
        and gate_context in {"baseline", "final_locked"}
        and row_gate_context == gate_context
    )


def _et_context_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("physical_condition_codes"), list)
        and "ET_DOMINATED" in row.get("physical_condition_codes", [])
    ]


def _mass_balance_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("physical_condition_codes"), list)
        and "MASS_IMBALANCE" in row.get("physical_condition_codes", [])
    ]


def _row_mass_balance_diagnostics_ok(row: dict[str, Any]) -> bool:
    flags = row.get("mass_balance_diagnostic_flags")
    actions = row.get("mass_balance_next_actions")
    payload = _load_json_path(row.get("mass_balance_diagnostics_path"))
    alternatives = payload.get("source_backed_alternatives")
    probe_order = payload.get("recommended_probe_order")
    wb = payload.get("water_balance")
    gate_context = payload.get("gate_context")
    row_gate_context = row.get("mass_balance_gate_context")
    return (
        _path_exists(row.get("mass_balance_diagnostics_path"))
        and isinstance(flags, list)
        and "mass_closure_residual_high" in flags
        and isinstance(actions, list)
        and bool(actions)
        and isinstance(alternatives, list)
        and any(
            isinstance(alt, dict)
            and alt.get("option") == "audit_basin_water_balance_closure_terms"
            for alt in alternatives
        )
        and isinstance(probe_order, list)
        and bool(probe_order)
        and isinstance(wb, dict)
        and isinstance(wb.get("closure_residual_abs_pct_of_precip"), (int, float))
        and gate_context in {"baseline", "final_locked"}
        and row_gate_context == gate_context
    )


def _soil_realism_required_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("primary_blocker") or "") == "soil_realism_gate_failed"]


def _objective_rows(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = (report or {}).get("rows", [])
    return [row for row in rows if isinstance(row, dict)]


def _routing_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "warning": 0, "not_run": 0, "unknown": 0}
    for row in rows:
        status = str(row.get("routing_flow_gates") or "unknown")
        if status not in counts:
            status = "unknown"
        counts[status] += 1
    return counts


def _primary_blocker_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        blocker = str(row.get("primary_blocker") or "unknown")
        counts[blocker] = counts.get(blocker, 0) + 1
    return dict(sorted(counts.items()))


def _generation_metadata_ok(report: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[bool, str]:
    generation = report.get("generation")
    if not isinstance(generation, dict):
        return False, "generation metadata missing"
    required = {"out_root", "summarize_existing", "resume_existing", "report_md", "report_json", "evidence_overrides"}
    missing = sorted(required - set(generation))
    if missing:
        return False, f"missing_generation_keys={missing}"
    overrides = generation.get("evidence_overrides")
    if not isinstance(overrides, dict):
        return False, "evidence_overrides missing or not an object"
    override_count = len(overrides)
    row_paths = {
        str(row.get("evidence_summary_path"))
        for row in rows
        if row.get("evidence_summary_path")
    }
    override_paths = {str(path) for path in overrides.values() if path}
    missing_override_paths = sorted(override_paths - row_paths)
    if missing_override_paths:
        return False, f"override_paths_not_in_rows={len(missing_override_paths)}"
    return True, f"generation_keys={sorted(required)}; override_count={override_count}"


def _append_static_checks(checks: list[Check]) -> None:
    checks.append(
        Check(
            "Workflow contract runtime exists",
            "implemented" if _exists("src/swatplus_builder/workflows/usgs_e2e.py") else "missing",
            "src/swatplus_builder/workflows/usgs_e2e.py",
        )
    )
    checks.append(
        Check(
            "Canonical workflow CLI supports negotiate/run with contract metadata",
            "implemented" if _cli_workflow_registered() else "missing",
            "src/swatplus_builder/cli.py workflow_app",
        )
    )
    checks.append(
        Check(
            "Full-mode warmup module exists",
            "implemented" if _exists("src/swatplus_builder/full_mode/warmup.py") else "missing",
            "src/swatplus_builder/full_mode/warmup.py",
        )
    )
    checks.append(
        Check(
            "Solver stale-output guards exist",
            "implemented" if _contains("src/swatplus_builder/run/swatplus.py", "def clean_and_run_solver") else "missing",
            "src/swatplus_builder/run/swatplus.py:def clean_and_run_solver",
        )
    )
    checks.append(
        Check(
            "Sensitivity screen module exists",
            "implemented" if _exists("src/swatplus_builder/calibration/sensitivity_screen.py") else "missing",
            "src/swatplus_builder/calibration/sensitivity_screen.py",
        )
    )
    checks.append(
        Check(
            "Locked diagnostic calibrator promotes and verifies calibrated TxtInOut",
            (
                "implemented"
                if (
                    _contains("src/swatplus_builder/calibration/diagnostic_calibrator.py", "locked_calibrated_TxtInOut")
                    and _contains("src/swatplus_builder/calibration/diagnostic_calibrator.py", "verify_calibration")
                    and _contains(
                        "src/swatplus_builder/calibration/diagnostic_calibrator.py",
                        "temporary_candidate_metrics_allowed_as_final",
                    )
                )
                else "missing"
            ),
            "src/swatplus_builder/calibration/diagnostic_calibrator.py",
        )
    )
    checks.append(
        Check(
            "Diagnostic calibration blocks KGE/NSE finetune until prior process gates pass",
            (
                "implemented"
                if (
                    _contains(
                        "src/swatplus_builder/calibration/locked_benchmark.py",
                        "blocked_preceding_process_gate",
                    )
                    and _contains(
                        "src/swatplus_builder/calibration/locked_benchmark.py",
                        "prior abs(pbias) <= 30 candidate must pass calibration process gates",
                    )
                    and _contains(
                        "tests/test_locked_benchmark.py",
                        "test_kge_nse_phase_requires_prior_process_gate_when_available",
                    )
                )
                else "missing"
            ),
            "src/swatplus_builder/calibration/locked_benchmark.py; tests/test_locked_benchmark.py",
        )
    )
    checks.append(
        Check(
            "Unified full-mode parameter governance covers the required ten parameters",
            (
                "implemented"
                if all(
                    _contains("src/swatplus_builder/params/governance.py", name)
                    and _contains("docs/CALIBRATION_PARAMETER_REGISTRY.md", name)
                    for name in [
                        "CN2",
                        "PERCO",
                        "LATQ_CO",
                        "PET_CO",
                        "ESCO",
                        "EPCO",
                        "SURLAG",
                        "ALPHA_BF",
                        "RCHG_DP",
                        "GW_DELAY",
                    ]
                )
                else "missing"
            ),
            "src/swatplus_builder/params/governance.py; docs/CALIBRATION_PARAMETER_REGISTRY.md",
        )
    )
    checks.append(
        Check(
            "Runtime claim governance enforces fresh output, benchmark, outlet, physical, routing, sensitivity, calibration, and metric gates",
            (
                "implemented"
                if all(
                    _contains("src/swatplus_builder/workflows/usgs_e2e.py", token)
                    for token in [
                        "_fresh_engine_gate",
                        "_benchmark_lock_gate",
                        "_outlet_provenance_gate",
                        "_sensitivity_gate",
                        "routing_flow",
                        "calibration_improvement_verified",
                        "research_metric_thresholds_passed",
                    ]
                )
                else "missing"
            ),
            "src/swatplus_builder/workflows/usgs_e2e.py",
        )
    )
    overlay_report = _load_overlay_repair_report()
    overlay_report_ok = (
        isinstance(overlay_report, dict)
        and overlay_report.get("reason") == "categorical_overlay_gap_too_large"
        and isinstance(overlay_report.get("soil_gap_fraction"), (int, float))
    )
    checks.append(
        Check(
            "Build blockers expose machine-readable diagnostic artifacts",
            (
                "implemented"
                if (
                    _contains("src/swatplus_builder/workflows/full_build.py", "diagnostic_artifacts")
                    and _contains("src/swatplus_builder/workflows/full_build.py", "overlay_repair_report.json")
                    and _contains("src/swatplus_builder/workflows/full_build.py", "soil_acquisition_report.json")
                    and _contains("tests/test_full_build.py", "test_build_full_model_promotes_overlay_repair_report_on_failure")
                    and _contains("tests/test_full_build.py", "test_build_full_model_promotes_soil_acquisition_report_on_failure")
                    and _contains("tests/test_orchestrate.py", "diagnostic_artifacts")
                    and _contains("src/swatplus_builder/workflows/usgs_e2e.py", "build_diagnostic_artifacts")
                    and _contains("src/swatplus_builder/workflows/usgs_e2e.py", "build_{key}")
                    and _contains("tests/test_workflow_usgs_e2e.py", "test_workflow_promotes_build_diagnostic_artifacts_to_evidence")
                    and overlay_report_ok
                )
                else "missing"
            ),
            (
                "src/swatplus_builder/workflows/full_build.py; "
                "tests/test_full_build.py; tests/test_orchestrate.py; "
                "demo_runs/post_overlay_repair_01013500_network/reports/overlay_repair/overlay_repair_report.json"
            ),
        )
    )
    checks.append(
        Check(
            "Pipeline research-grade audit doc present",
            "implemented" if _exists("docs/PIPELINE_RESEARCH_GRADE_AUDIT.md") else "missing",
            "docs/PIPELINE_RESEARCH_GRADE_AUDIT.md",
        )
    )
    checks.append(
        Check(
            "Canonical objective-suite validation report present",
            "implemented" if OBJECTIVE_REPORT_JSON.exists() and OBJECTIVE_REPORT_MD.exists() else "missing",
            "docs/objective_basin_validation_report.json; docs/OBJECTIVE_BASIN_VALIDATION_REPORT.md",
        )
    )


def _append_objective_report_checks(checks: list[Check], report: dict[str, Any] | None) -> None:
    if not report or not isinstance(report.get("rows"), list):
        checks.append(
            Check(
                "Objective report covers the requested basin suite",
                "missing",
                "docs/objective_basin_validation_report.json missing or malformed",
            )
        )
        checks.append(
            Check(
                "Research-grade target is scientifically met",
                "missing",
                "docs/objective_basin_validation_report.json missing or malformed",
            )
        )
        return

    rows = report["rows"]
    basins = {str(r.get("basin")) for r in rows}
    research_grade = sum(1 for r in rows if str(r.get("tier")) == "research_grade")
    unknown_rows = sum(
        1
        for r in rows
        if str(r.get("build")) == "unknown" or str(r.get("engine")) == "unknown"
    )
    non_research = [r for r in rows if str(r.get("tier")) != "research_grade"]
    blocker_domain_action_rows = sum(
        1 for r in non_research if _row_blocker_domain_action_plan_ok(r)
    )
    report_blocker_classification_ok = _report_blocker_classification_ok(report, rows)
    target_hypothesis_evaluation_ok = _target_hypothesis_evaluation_ok(report, rows)
    science_blocker_summary_ok = _science_blocker_summary_ok(report, rows)
    pipeline_improvement_plan_ok = _pipeline_improvement_plan_ok(report, rows)
    (
        pipeline_improvement_diagnostic_context_rows,
        required_pipeline_improvement_diagnostic_context_rows,
    ) = _pipeline_improvement_diagnostic_context_rows(report)
    (
        pipeline_improvement_diagnostic_explanation_rows,
        required_pipeline_improvement_diagnostic_explanation_rows,
    ) = _pipeline_improvement_diagnostic_explanation_rows(report)
    (
        pipeline_improvement_provenance_context_rows,
        required_pipeline_improvement_provenance_context_rows,
    ) = _pipeline_improvement_provenance_context_rows(report)
    weak_primary_blockers = sum(
        1
        for r in non_research
        if str(r.get("primary_blocker") or "none") in {"", "none", "unknown", "unclassified"}
    )
    unclassified_non_research = sum(
        1
        for r in non_research
        if str(r.get("primary_blocker") or "none") in {"", "none", "unknown", "unclassified"}
        and str(r.get("blocker") or "none") in {"", "none", "unknown", "unclassified"}
        and not r.get("gates_failed")
    )
    evidence_pointer_rows = sum(
        1
        for r in rows
        if Path(str(r.get("evidence_summary_path") or "")).exists()
    )
    physical_gate_artifact_rows = sum(1 for r in rows if _row_physical_gate_artifact_ok(r))
    claim_policy_name_rows = sum(1 for r in rows if _row_claim_policy_names_ok(r))
    rows_with_metrics = sum(
        1
        for r in rows
        if isinstance(r.get("kge"), (int, float)) and isinstance(r.get("nse"), (int, float))
    )
    seeded_rows = sum(1 for r in rows if "metrics_seeded:" in str(r.get("notes") or ""))
    calibration_rows = sum(
        1
        for r in rows
        if str(r.get("calibration")) in {"attempted", "done", "verified"}
    )
    hydrograph_rows = sum(1 for r in rows if _row_hydrograph_ok(r))
    calibration_provenance_rows = sum(1 for r in rows if _row_calibration_provenance_ok(r))
    sensitivity_screen_rows = sum(1 for r in rows if _row_sensitivity_screen_ok(r))
    research_grade_core_sensitivity_required_rows = _research_grade_core_sensitivity_required_rows(rows)
    research_grade_core_sensitivity_rows = sum(
        1
        for r in research_grade_core_sensitivity_required_rows
        if _row_research_grade_core_sensitivity_ok(r)
    )
    calibration_delta_rows = sum(1 for r in rows if _row_calibration_delta_ok(r))
    calibration_regression_required_rows = _calibration_regression_required_rows(rows)
    calibration_regression_rows = sum(
        1 for r in calibration_regression_required_rows if _row_calibration_regression_ok(r)
    )
    promotion_gate_failure_required_rows = _promotion_gate_failure_required_rows(rows)
    promotion_gate_failure_rows = sum(
        1 for r in promotion_gate_failure_required_rows if _row_promotion_gate_failure_ok(r)
    )
    failed_calibration_required_rows = _failed_calibration_required_rows(rows)
    failed_calibration_evidence_rows = sum(
        1 for r in failed_calibration_required_rows if _row_failed_calibration_evidence_ok(r)
    )
    failed_calibration_context_required_rows = _failed_calibration_context_required_rows(rows)
    failed_calibration_context_rows = sum(
        1 for r in failed_calibration_context_required_rows if _row_failed_calibration_context_ok(r)
    )
    calibration_phase_coverage_required_rows = _calibration_phase_coverage_required_rows(rows)
    calibration_phase_coverage_rows = sum(
        1
        for r in calibration_phase_coverage_required_rows
        if _row_calibration_phase_coverage_ok(r)
    )
    failed_calibration_tradeoff_frontier_rows = sum(
        1
        for r in failed_calibration_context_required_rows
        if _row_failed_calibration_tradeoff_frontier_ok(r)
    )
    failed_calibration_terminal_scope_history_required_rows = (
        _failed_calibration_terminal_scope_history_required_rows(rows)
    )
    failed_calibration_terminal_scope_history_rows = sum(
        1
        for r in failed_calibration_terminal_scope_history_required_rows
        if _row_failed_calibration_terminal_scope_history_ok(r)
    )
    calibration_bound_interaction_required_rows = _calibration_bound_interaction_required_rows(rows)
    calibration_bound_interaction_rows = sum(
        1
        for r in calibration_bound_interaction_required_rows
        if _row_calibration_bound_interaction_ok(r)
    )
    failed_calibration_physical_trace_required_rows = _failed_calibration_physical_trace_required_rows(rows)
    failed_calibration_physical_trace_rows = sum(
        1
        for r in failed_calibration_physical_trace_required_rows
        if _row_failed_calibration_physical_trace_ok(r)
    )
    failed_calibration_process_trace_required_rows = _failed_calibration_process_trace_required_rows(rows)
    failed_calibration_process_trace_rows = sum(
        1
        for r in failed_calibration_process_trace_required_rows
        if _row_failed_calibration_process_trace_ok(r)
    )
    calibration_precheck_required_rows = _calibration_precheck_required_rows(rows)
    calibration_precheck_rows = sum(
        1 for r in calibration_precheck_required_rows if _row_calibration_precheck_ok(r)
    )
    volume_diagnostic_required_rows = _volume_diagnostic_required_rows(rows)
    volume_diagnostic_rows = sum(1 for r in volume_diagnostic_required_rows if _row_volume_diagnostics_ok(r))
    terminal_hydrograph_scope_required_rows = _terminal_hydrograph_scope_required_rows(rows)
    terminal_hydrograph_scope_rows = sum(
        1 for r in terminal_hydrograph_scope_required_rows if _row_terminal_hydrograph_scope_ok(r)
    )
    terminal_hydrograph_kge_component_rows = sum(
        1
        for r in terminal_hydrograph_scope_required_rows
        if _row_terminal_hydrograph_kge_component_ok(r)
    )
    terminal_hydrograph_aggregation_context_rows = sum(
        1
        for r in terminal_hydrograph_scope_required_rows
        if _row_terminal_hydrograph_aggregation_context_ok(r)
    )
    terminal_hydrograph_scope_class_rows = sum(
        1
        for r in terminal_hydrograph_scope_required_rows
        if _row_terminal_hydrograph_scope_class_ok(r)
    )
    terminal_scope_resolution_plan_rows = sum(
        1
        for r in terminal_hydrograph_scope_required_rows
        if _row_terminal_scope_resolution_plan_ok(r)
    )
    nearest_terminal_hydrograph_required_rows = _nearest_terminal_hydrograph_required_rows(rows)
    nearest_terminal_hydrograph_rows = sum(
        1
        for r in nearest_terminal_hydrograph_required_rows
        if _row_nearest_terminal_hydrograph_ok(r)
    )
    post_aggregation_volume_deficit_required_rows = _post_aggregation_volume_deficit_required_rows(rows)
    post_aggregation_volume_deficit_rows = sum(
        1
        for r in post_aggregation_volume_deficit_required_rows
        if _row_post_aggregation_volume_deficit_ok(r)
    )
    post_aggregation_process_context_rows = sum(
        1
        for r in post_aggregation_volume_deficit_required_rows
        if _row_post_aggregation_process_context_ok(r)
    )
    post_aggregation_candidate_explanation_rows = sum(
        1
        for r in post_aggregation_volume_deficit_required_rows
        if _row_post_aggregation_candidate_explanations_ok(r)
    )
    volume_forcing_context_required_rows = _volume_diagnostic_required_rows(rows)
    volume_forcing_context_rows = sum(
        1 for r in volume_forcing_context_required_rows if _row_volume_forcing_context_ok(r)
    )
    volume_forcing_plausibility_rows = sum(
        1
        for r in volume_forcing_context_required_rows
        if _row_volume_forcing_plausibility_ok(r)
    )
    high_runoff_demand_required_rows = _high_runoff_demand_required_rows(rows)
    high_runoff_demand_context_rows = sum(
        1 for r in high_runoff_demand_required_rows if _row_high_runoff_demand_context_ok(r)
    )
    high_runoff_interpretation_rows = sum(
        1 for r in high_runoff_demand_required_rows if _row_high_runoff_interpretation_ok(r)
    )
    terminal_scope_blocker_rows = sum(
        1 for r in terminal_hydrograph_scope_required_rows if _row_terminal_scope_blocker_ok(r)
    )
    routing_terminal_scope_required_rows = _routing_terminal_scope_required_rows(rows)
    routing_terminal_scope_blocker_rows = sum(
        1 for r in routing_terminal_scope_required_rows if _row_terminal_scope_blocker_ok(r)
    )
    terminal_scope_claim_required_rows = _terminal_scope_claim_required_rows(rows)
    terminal_scope_claim_blocked_rows = sum(
        1 for r in terminal_scope_claim_required_rows if _row_terminal_scope_claim_blocked_ok(r)
    )
    virtual_outlet_scope_required_rows = _virtual_outlet_scope_required_rows(rows)
    virtual_outlet_scope_gate_rows = sum(
        1 for r in virtual_outlet_scope_required_rows if _row_virtual_outlet_scope_gate_ok(r)
    )
    terminal_scope_probe_priority_rows = sum(
        1
        for r in terminal_hydrograph_scope_required_rows
        if _row_terminal_scope_probe_priority_ok(r)
    )
    skill_diagnostic_required_rows = _skill_diagnostic_required_rows(rows)
    skill_diagnostic_rows = sum(1 for r in skill_diagnostic_required_rows if _row_skill_diagnostics_ok(r))
    skill_limitation_class_rows = sum(
        1 for r in skill_diagnostic_required_rows if _row_skill_limitation_class_ok(r)
    )
    skill_evidence_metrics_required_rows = _skill_evidence_metrics_required_rows(rows)
    skill_evidence_metrics_rows = sum(
        1 for r in skill_evidence_metrics_required_rows if _row_skill_evidence_metrics_ok(r)
    )
    skill_kge_component_required_rows = _skill_kge_component_required_rows(rows)
    skill_kge_component_rows = sum(
        1 for r in skill_kge_component_required_rows if _row_skill_kge_component_ok(r)
    )
    skill_channel_screen_required_rows = _skill_channel_screen_required_rows(rows)
    skill_channel_screen_rows = sum(
        1 for r in skill_channel_screen_required_rows if _row_skill_channel_screen_ok(r)
    )
    skill_channel_refinement_required_rows = _skill_channel_refinement_required_rows(rows)
    skill_channel_refinement_rows = sum(
        1 for r in skill_channel_refinement_required_rows if _row_skill_channel_refinement_ok(r)
    )
    skill_probe_gap_required_rows = _skill_probe_gap_required_rows(rows)
    skill_probe_gap_rows = sum(1 for r in skill_probe_gap_required_rows if _row_skill_probe_gap_ok(r))
    skill_sensitivity_triage_required_rows = _skill_sensitivity_triage_required_rows(rows)
    skill_sensitivity_triage_rows = sum(
        1
        for r in skill_sensitivity_triage_required_rows
        if _row_skill_sensitivity_triage_ok(r)
    )
    skill_bound_context_required_rows = _skill_bound_context_required_rows(rows)
    skill_bound_context_rows = sum(
        1 for r in skill_bound_context_required_rows if _row_skill_bound_context_ok(r)
    )
    skill_bound_aware_probe_required_rows = _skill_bound_aware_probe_required_rows(rows)
    skill_bound_aware_probe_rows = sum(
        1
        for r in skill_bound_aware_probe_required_rows
        if _row_skill_bound_aware_probe_order_ok(r)
    )
    skill_parameter_governance_required_rows = _skill_parameter_governance_required_rows(rows)
    skill_parameter_governance_rows = sum(
        1 for r in skill_parameter_governance_required_rows if _row_skill_parameter_governance_ok(r)
    )
    superseded_skill_parameter_required_rows = _superseded_skill_parameter_required_rows(rows)
    superseded_skill_parameter_rows = sum(
        1 for r in superseded_skill_parameter_required_rows if _row_superseded_skill_parameter_ok(r)
    )
    soil_realism_required_rows = _soil_realism_required_rows(rows)
    soil_realism_diagnostic_rows = sum(
        1 for r in soil_realism_required_rows if _row_soil_realism_diagnostics_ok(r)
    )
    soil_realism_remediation_rows = sum(
        1 for r in soil_realism_required_rows if _row_soil_realism_remediation_ok(r)
    )
    soil_fidelity_required_rows = _soil_fidelity_required_rows(rows)
    soil_fidelity_provenance_rows = sum(
        1 for r in soil_fidelity_required_rows if _row_soil_fidelity_provenance_ok(r)
    )
    routing_diagnostic_required_rows = _routing_diagnostic_required_rows(rows)
    routing_diagnostic_rows = sum(1 for r in routing_diagnostic_required_rows if _row_routing_diagnostics_ok(r))
    routing_coverage_rows = sum(1 for r in routing_diagnostic_required_rows if _row_routing_source_coverage_ok(r))
    routing_unit_semantics_required_rows = _routing_unit_semantics_required_rows(rows)
    routing_unit_semantics_rows = sum(
        1 for r in routing_unit_semantics_required_rows if _row_routing_unit_semantics_ok(r)
    )
    routed_to_channel_required_rows = _routed_to_channel_semantics_required_rows(rows)
    routed_to_channel_semantics_rows = sum(
        1 for r in routed_to_channel_required_rows if _row_routed_to_channel_semantics_ok(r)
    )
    routing_status_mismatch_required_rows = _routing_status_mismatch_required_rows(rows)
    routing_status_mismatch_rows = sum(
        1 for r in routing_status_mismatch_required_rows if _row_routing_status_mismatch_ok(r)
    )
    terminal_inventory_required_rows = _terminal_inventory_required_rows(rows)
    terminal_inventory_rows = sum(1 for r in terminal_inventory_required_rows if _row_terminal_inventory_ok(r))
    terminal_area_context_rows = sum(
        1 for r in terminal_inventory_required_rows if _row_terminal_area_context_ok(r)
    )
    terminal_area_scope_class_rows = sum(
        1 for r in terminal_inventory_required_rows if _row_terminal_area_scope_class_ok(r)
    )
    terminal_authority_area_context_rows = sum(
        1 for r in terminal_inventory_required_rows if _row_terminal_authority_area_context_ok(r)
    )
    terminal_virtual_outlet_candidate_required_rows = _terminal_virtual_outlet_candidate_required_rows(rows)
    terminal_virtual_outlet_candidate_rows = sum(
        1
        for r in terminal_virtual_outlet_candidate_required_rows
        if _row_terminal_virtual_outlet_candidate_ok(r)
    )
    terminal_gauge_context_rows = sum(
        1 for r in terminal_inventory_required_rows if _row_terminal_gauge_context_ok(r)
    )
    not_nearest_terminal_required_rows = _not_nearest_terminal_required_rows(rows)
    not_nearest_terminal_probe_rows = sum(
        1 for r in not_nearest_terminal_required_rows if _row_not_nearest_terminal_probe_ok(r)
    )
    terminal_outlet_conflict_class_rows = sum(
        1
        for r in not_nearest_terminal_required_rows
        if _row_terminal_outlet_conflict_class_ok(r)
    )
    terminal_topology_overlap_required_rows = _terminal_topology_overlap_required_rows(rows)
    terminal_topology_overlap_rows = sum(
        1
        for r in terminal_topology_overlap_required_rows
        if _row_terminal_topology_overlap_ok(r)
    )
    et_context_required_rows = _et_context_required_rows(rows)
    et_context_rows = sum(1 for r in et_context_required_rows if _row_et_context_ok(r))
    et_diagnostic_rows = sum(1 for r in et_context_required_rows if _row_et_diagnostics_ok(r))
    mass_balance_required_rows = _mass_balance_required_rows(rows)
    mass_balance_diagnostic_rows = sum(
        1 for r in mass_balance_required_rows if _row_mass_balance_diagnostics_ok(r)
    )
    generation_ok, generation_evidence = _generation_metadata_ok(report, rows)
    routing_counts = _routing_status_counts(rows)

    checks.append(
        Check(
            "Objective report covers the requested basin suite",
            "implemented" if REQUIRED_BASINS.issubset(basins) else "missing",
            f"basin_count={len(rows)}; missing={sorted(REQUIRED_BASINS - basins)}",
        )
    )
    checks.append(
        Check(
            "All basins have concrete build/engine evidence (no unknown rows)",
            "implemented" if unknown_rows == 0 else "missing",
            f"unknown_rows={unknown_rows}",
        )
    )
    checks.append(
        Check(
            "All objective rows have explicit routing-flow gate status",
            "implemented" if routing_counts.get("unknown", 0) == 0 else "missing",
            f"routing_status_counts={routing_counts}",
        )
    )
    checks.append(
        Check(
            "All objective rows retain valid evidence_summary.json pointers",
            "implemented" if evidence_pointer_rows == len(rows) else "missing",
            f"evidence_pointer_rows={evidence_pointer_rows}/{len(rows)}",
        )
    )
    checks.append(
        Check(
            "All objective rows retain consistent package physical-gate artifacts",
            "implemented" if physical_gate_artifact_rows == len(rows) else "missing",
            f"physical_gate_artifact_rows={physical_gate_artifact_rows}/{len(rows)}",
        )
    )
    checks.append(
        Check(
            "All objective rows retain machine-readable allowed and blocked claim names",
            "implemented" if claim_policy_name_rows == len(rows) else "missing",
            f"claim_policy_name_rows={claim_policy_name_rows}/{len(rows)}",
        )
    )
    checks.append(
        Check(
            "Objective report records generation metadata and evidence overrides",
            "implemented" if generation_ok else "missing",
            generation_evidence,
        )
    )
    checks.append(
        Check(
            "Physics metrics emitted (KGE/NSE) for benchmark evidence",
            "implemented" if rows_with_metrics >= 1 else "missing",
            f"rows_with_metrics={rows_with_metrics}",
        )
    )
    checks.append(
        Check(
            "Non-research outcomes expose machine-readable primary blockers",
            "implemented" if weak_primary_blockers == 0 and unclassified_non_research == 0 else "missing",
            (
                f"weak_primary_blockers={weak_primary_blockers}; "
                f"unclassified_non_research={unclassified_non_research}"
            ),
        )
    )
    checks.append(
        Check(
            "Non-research outcomes retain blocker domains and machine-readable action plans",
            (
                "implemented"
                if report_blocker_classification_ok and blocker_domain_action_rows == len(non_research)
                else "missing"
            ),
            (
                f"blocker_domain_action_rows={blocker_domain_action_rows}; "
                f"required_non_research_rows={len(non_research)}; "
                f"report_blocker_classification_ok={report_blocker_classification_ok}"
            ),
        )
    )
    checks.append(
        Check(
            "Target hypothesis evaluation preserves gate policy and fewer-pass interpretation",
            "implemented" if target_hypothesis_evaluation_ok else "missing",
            (
                f"target_hypothesis_evaluation_ok={target_hypothesis_evaluation_ok}; "
                f"research_grade_count={research_grade}; target=7"
            ),
        )
    )
    checks.append(
        Check(
            "Science blockers retain root explanatory evidence summary",
            "implemented" if science_blocker_summary_ok else "missing",
            f"science_blocker_summary_ok={science_blocker_summary_ok}",
        )
    )
    checks.append(
        Check(
            "Objective suite emits a machine-readable pipeline improvement plan",
            "implemented" if pipeline_improvement_plan_ok else "missing",
            (
                f"pipeline_improvement_plan_ok={pipeline_improvement_plan_ok}; "
                "source=non_research_blocker_classification"
            ),
        )
    )
    checks.append(
        Check(
            "Pipeline improvement diagnostics are evidence-specific and process-context backed",
            (
                "implemented"
                if pipeline_improvement_diagnostic_context_rows
                == required_pipeline_improvement_diagnostic_context_rows
                else "missing"
            ),
            (
                f"pipeline_improvement_diagnostic_context_rows="
                f"{pipeline_improvement_diagnostic_context_rows}; "
                f"required_pipeline_improvement_diagnostic_context_rows="
                f"{required_pipeline_improvement_diagnostic_context_rows}"
            ),
        )
    )
    checks.append(
        Check(
            "Pipeline improvement diagnostic decisions preserve candidate explanations",
            (
                "implemented"
                if pipeline_improvement_diagnostic_explanation_rows
                == required_pipeline_improvement_diagnostic_explanation_rows
                else "missing"
            ),
            (
                f"pipeline_improvement_diagnostic_explanation_rows="
                f"{pipeline_improvement_diagnostic_explanation_rows}; "
                f"required_pipeline_improvement_diagnostic_explanation_rows="
                f"{required_pipeline_improvement_diagnostic_explanation_rows}"
            ),
        )
    )
    checks.append(
        Check(
            "Pipeline improvement provenance decisions are outlet-scope-evidence backed",
            (
                "implemented"
                if pipeline_improvement_provenance_context_rows
                == required_pipeline_improvement_provenance_context_rows
                else "missing"
            ),
            (
                f"pipeline_improvement_provenance_context_rows="
                f"{pipeline_improvement_provenance_context_rows}; "
                f"required_pipeline_improvement_provenance_context_rows="
                f"{required_pipeline_improvement_provenance_context_rows}"
            ),
        )
    )
    checks.append(
        Check(
            "Research-grade target is scientifically met",
            "implemented" if research_grade >= 7 else "missing",
            f"research_grade_count={research_grade}; target=>=7 only if defensible",
        )
    )
    checks.append(
        Check(
            "Locked calibration hydrograph comparison exists for attempted or verified calibrations",
            "implemented" if hydrograph_rows == calibration_rows else "missing",
            (
                f"hydrograph_rows={hydrograph_rows}; "
                f"calibration_rows={calibration_rows}; "
                f"research_grade_count={research_grade}"
            ),
        )
    )
    checks.append(
        Check(
            "Calibration provenance exists for attempted or verified calibrations",
            "implemented" if calibration_provenance_rows == calibration_rows else "missing",
            (
                f"calibration_provenance_rows={calibration_provenance_rows}; "
                f"calibration_rows={calibration_rows}"
            ),
        )
    )
    checks.append(
        Check(
            "Basin-specific sensitivity screens exist for attempted or verified calibrations",
            "implemented" if sensitivity_screen_rows == calibration_rows else "missing",
            (
                f"sensitivity_screen_rows={sensitivity_screen_rows}; "
                f"calibration_rows={calibration_rows}"
            ),
        )
    )
    checks.append(
        Check(
            "Research-grade rows retain current core-governance sensitivity coverage",
            (
                "implemented"
                if research_grade_core_sensitivity_rows
                == len(research_grade_core_sensitivity_required_rows)
                else "missing"
            ),
            (
                f"research_grade_core_sensitivity_rows={research_grade_core_sensitivity_rows}; "
                f"required_research_grade_core_sensitivity_rows="
                f"{len(research_grade_core_sensitivity_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Calibration delta metrics exist for attempted or verified calibrations",
            "implemented" if calibration_delta_rows == calibration_rows else "missing",
            (
                f"calibration_delta_rows={calibration_delta_rows}; "
                f"calibration_rows={calibration_rows}"
            ),
        )
    )
    checks.append(
        Check(
            "Regressed locked calibrations retain regression blocker evidence",
            (
                "implemented"
                if calibration_regression_rows == len(calibration_regression_required_rows)
                else "missing"
            ),
            (
                f"calibration_regression_rows={calibration_regression_rows}; "
                f"required_calibration_regression_rows={len(calibration_regression_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Promotion-gate calibration failures retain phase and final-metric authority evidence",
            (
                "implemented"
                if promotion_gate_failure_rows == len(promotion_gate_failure_required_rows)
                else "missing"
            ),
            (
                f"promotion_gate_failure_rows={promotion_gate_failure_rows}; "
                f"required_promotion_gate_failure_rows={len(promotion_gate_failure_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed or blocked calibration searches retain failure-phase evidence",
            (
                "implemented"
                if failed_calibration_evidence_rows == len(failed_calibration_required_rows)
                else "missing"
            ),
            (
                f"failed_calibration_evidence_rows={failed_calibration_evidence_rows}; "
                f"required_failed_calibration_rows={len(failed_calibration_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed or blocked calibration searches retain history, best-parameter vector, bound context, and promotion-gate context",
            (
                "implemented"
                if failed_calibration_context_rows == len(failed_calibration_context_required_rows)
                else "missing"
            ),
            (
                f"failed_calibration_context_rows={failed_calibration_context_rows}; "
                f"required_failed_calibration_context_rows={len(failed_calibration_context_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Calibration histories expose machine-readable phase parameter coverage",
            (
                "implemented"
                if calibration_phase_coverage_rows == len(calibration_phase_coverage_required_rows)
                else "missing"
            ),
            (
                f"calibration_phase_coverage_rows={calibration_phase_coverage_rows}; "
                f"required_calibration_phase_coverage_rows={len(calibration_phase_coverage_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed or blocked calibration histories retain diagnostic skill-volume tradeoff frontier",
            (
                "implemented"
                if failed_calibration_tradeoff_frontier_rows == len(failed_calibration_context_required_rows)
                else "missing"
            ),
            (
                f"failed_calibration_tradeoff_frontier_rows={failed_calibration_tradeoff_frontier_rows}; "
                "required_failed_calibration_tradeoff_frontier_rows="
                f"{len(failed_calibration_context_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed calibration histories with terminal candidate metrics surface diagnostic terminal-scope frontier evidence",
            (
                "implemented"
                if failed_calibration_terminal_scope_history_rows
                == len(failed_calibration_terminal_scope_history_required_rows)
                else "missing"
            ),
            (
                "failed_calibration_terminal_scope_history_rows="
                f"{failed_calibration_terminal_scope_history_rows}; "
                "required_failed_calibration_terminal_scope_history_rows="
                f"{len(failed_calibration_terminal_scope_history_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Calibration bound-interaction screens remain diagnostic-only evidence",
            (
                "implemented"
                if calibration_bound_interaction_rows == len(calibration_bound_interaction_required_rows)
                else "missing"
            ),
            (
                f"calibration_bound_interaction_rows={calibration_bound_interaction_rows}; "
                f"required_calibration_bound_interaction_rows={len(calibration_bound_interaction_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed calibration objective traces retain candidate physical blocker classifications",
            (
                "implemented"
                if failed_calibration_physical_trace_rows == len(failed_calibration_physical_trace_required_rows)
                else "missing"
            ),
            (
                f"failed_calibration_physical_trace_rows={failed_calibration_physical_trace_rows}; "
                "required_failed_calibration_physical_trace_rows="
                f"{len(failed_calibration_physical_trace_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed calibration objective traces retain process-vs-claim gate classifications",
            (
                "implemented"
                if failed_calibration_process_trace_rows == len(failed_calibration_process_trace_required_rows)
                else "missing"
            ),
            (
                f"failed_calibration_process_trace_rows={failed_calibration_process_trace_rows}; "
                "required_failed_calibration_process_trace_rows="
                f"{len(failed_calibration_process_trace_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Attempted calibrations retain precheck gate sequence evidence",
            (
                "implemented"
                if calibration_precheck_rows == len(calibration_precheck_required_rows)
                else "missing"
            ),
            (
                f"calibration_precheck_rows={calibration_precheck_rows}; "
                f"required_calibration_precheck_rows={len(calibration_precheck_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Volume-bias blockers retain diagnostic flags and next actions",
            (
                "implemented"
                if volume_diagnostic_rows == len(volume_diagnostic_required_rows)
                else "missing"
            ),
            (
                f"volume_diagnostic_rows={volume_diagnostic_rows}; "
                f"required_volume_diagnostic_rows={len(volume_diagnostic_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope volume blockers retain row-level selected-vs-all hydrograph diagnostics",
            (
                "implemented"
                if terminal_hydrograph_scope_rows == len(terminal_hydrograph_scope_required_rows)
                else "missing"
            ),
            (
                f"terminal_hydrograph_scope_rows={terminal_hydrograph_scope_rows}; "
                f"required_terminal_hydrograph_scope_rows={len(terminal_hydrograph_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope hydrograph diagnostics retain KGE component decomposition",
            (
                "implemented"
                if terminal_hydrograph_kge_component_rows == len(terminal_hydrograph_scope_required_rows)
                else "missing"
            ),
            (
                f"terminal_hydrograph_kge_component_rows={terminal_hydrograph_kge_component_rows}; "
                "required_terminal_hydrograph_kge_component_rows="
                f"{len(terminal_hydrograph_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope hydrograph diagnostics retain all-terminal aggregation validity context",
            (
                "implemented"
                if terminal_hydrograph_aggregation_context_rows == len(terminal_hydrograph_scope_required_rows)
                else "missing"
            ),
            (
                f"terminal_hydrograph_aggregation_context_rows={terminal_hydrograph_aggregation_context_rows}; "
                "required_terminal_hydrograph_aggregation_context_rows="
                f"{len(terminal_hydrograph_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope hydrograph diagnostics retain package-owned scope classification",
            (
                "implemented"
                if terminal_hydrograph_scope_class_rows == len(terminal_hydrograph_scope_required_rows)
                else "missing"
            ),
            (
                f"terminal_hydrograph_scope_class_rows={terminal_hydrograph_scope_class_rows}; "
                "required_terminal_hydrograph_scope_class_rows="
                f"{len(terminal_hydrograph_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope hydrograph diagnostics retain resolution plans before claim promotion",
            (
                "implemented"
                if terminal_scope_resolution_plan_rows == len(terminal_hydrograph_scope_required_rows)
                else "missing"
            ),
            (
                f"terminal_scope_resolution_plan_rows={terminal_scope_resolution_plan_rows}; "
                "required_terminal_scope_resolution_plan_rows="
                f"{len(terminal_hydrograph_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Not-nearest terminal diagnostics retain nearest-terminal hydrograph metrics",
            (
                "implemented"
                if nearest_terminal_hydrograph_rows == len(nearest_terminal_hydrograph_required_rows)
                else "missing"
            ),
            (
                f"nearest_terminal_hydrograph_rows={nearest_terminal_hydrograph_rows}; "
                "required_nearest_terminal_hydrograph_rows="
                f"{len(nearest_terminal_hydrograph_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Post-aggregation terminal volume deficits retain process-diagnosis probes",
            (
                "implemented"
                if post_aggregation_volume_deficit_rows
                == len(post_aggregation_volume_deficit_required_rows)
                else "missing"
            ),
            (
                f"post_aggregation_volume_deficit_rows={post_aggregation_volume_deficit_rows}; "
                "required_post_aggregation_volume_deficit_rows="
                f"{len(post_aggregation_volume_deficit_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Post-aggregation terminal volume deficits retain process context",
            (
                "implemented"
                if post_aggregation_process_context_rows
                == len(post_aggregation_volume_deficit_required_rows)
                else "missing"
            ),
            (
                f"post_aggregation_process_context_rows={post_aggregation_process_context_rows}; "
                "required_post_aggregation_process_context_rows="
                f"{len(post_aggregation_volume_deficit_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Post-aggregation terminal volume deficits retain candidate explanations",
            (
                "implemented"
                if post_aggregation_candidate_explanation_rows
                == len(post_aggregation_volume_deficit_required_rows)
                else "missing"
            ),
            (
                f"post_aggregation_candidate_explanation_rows="
                f"{post_aggregation_candidate_explanation_rows}; "
                "required_post_aggregation_candidate_explanation_rows="
                f"{len(post_aggregation_volume_deficit_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Volume-bias blockers retain observed-window forcing context",
            (
                "implemented"
                if volume_forcing_context_rows == len(volume_forcing_context_required_rows)
                else "missing"
            ),
            (
                f"volume_forcing_context_rows={volume_forcing_context_rows}; "
                "required_volume_forcing_context_rows="
                f"{len(volume_forcing_context_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Volume-bias forcing context classifies runoff-precipitation plausibility",
            (
                "implemented"
                if volume_forcing_plausibility_rows == len(volume_forcing_context_required_rows)
                else "missing"
            ),
            (
                f"volume_forcing_plausibility_rows={volume_forcing_plausibility_rows}; "
                "required_volume_forcing_plausibility_rows="
                f"{len(volume_forcing_context_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "High observed runoff fraction rows retain snow-storage/baseflow/area context",
            (
                "implemented"
                if high_runoff_demand_context_rows == len(high_runoff_demand_required_rows)
                else "missing"
            ),
            (
                f"high_runoff_demand_context_rows={high_runoff_demand_context_rows}; "
                "required_high_runoff_demand_rows="
                f"{len(high_runoff_demand_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "High observed runoff fraction rows classify snow/baseflow/yield gaps",
            (
                "implemented"
                if high_runoff_interpretation_rows == len(high_runoff_demand_required_rows)
                else "missing"
            ),
            (
                f"high_runoff_interpretation_rows={high_runoff_interpretation_rows}; "
                "required_high_runoff_demand_rows="
                f"{len(high_runoff_demand_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope volume blockers retain machine-readable outlet-scope classification",
            (
                "implemented"
                if terminal_scope_blocker_rows == len(terminal_hydrograph_scope_required_rows)
                else "missing"
            ),
            (
                f"terminal_scope_blocker_rows={terminal_scope_blocker_rows}; "
                f"required_terminal_scope_blocker_rows={len(terminal_hydrograph_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Routing-scope terminal warnings retain machine-readable outlet-scope classification",
            (
                "implemented"
                if routing_terminal_scope_blocker_rows == len(routing_terminal_scope_required_rows)
                else "missing"
            ),
            (
                f"routing_terminal_scope_blocker_rows={routing_terminal_scope_blocker_rows}; "
                "required_routing_terminal_scope_blocker_rows="
                f"{len(routing_terminal_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope blockers retain terminal-scope blocked claim evidence",
            (
                "implemented"
                if terminal_scope_claim_blocked_rows == len(terminal_scope_claim_required_rows)
                else "missing"
            ),
            (
                f"terminal_scope_claim_blocked_rows={terminal_scope_claim_blocked_rows}; "
                f"required_terminal_scope_claim_rows={len(terminal_scope_claim_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Virtual all-terminal outlet rows retain machine-readable scope-gate evidence",
            (
                "implemented"
                if virtual_outlet_scope_gate_rows == len(virtual_outlet_scope_required_rows)
                else "missing"
            ),
            (
                f"virtual_outlet_scope_gate_rows={virtual_outlet_scope_gate_rows}; "
                f"required_virtual_outlet_scope_rows={len(virtual_outlet_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-scope volume blockers prioritize outlet reconciliation before parameter screens",
            (
                "implemented"
                if terminal_scope_probe_priority_rows == len(terminal_hydrograph_scope_required_rows)
                else "missing"
            ),
            (
                f"terminal_scope_probe_priority_rows={terminal_scope_probe_priority_rows}; "
                "required_terminal_scope_probe_priority_rows="
                f"{len(terminal_hydrograph_scope_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill blockers retain hydrograph diagnostic flags and next actions",
            (
                "implemented"
                if skill_diagnostic_rows == len(skill_diagnostic_required_rows)
                else "missing"
            ),
            (
                f"skill_diagnostic_rows={skill_diagnostic_rows}; "
                f"required_skill_diagnostic_rows={len(skill_diagnostic_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill blockers retain machine-readable skill-limitation classification",
            (
                "implemented"
                if skill_limitation_class_rows == len(skill_diagnostic_required_rows)
                else "missing"
            ),
            (
                f"skill_limitation_class_rows={skill_limitation_class_rows}; "
                f"required_skill_diagnostic_rows={len(skill_diagnostic_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill blockers retain structured diagnostic evidence metrics",
            (
                "implemented"
                if skill_evidence_metrics_rows == len(skill_evidence_metrics_required_rows)
                else "missing"
            ),
            (
                f"skill_evidence_metrics_rows={skill_evidence_metrics_rows}; "
                f"required_skill_evidence_metrics_rows={len(skill_evidence_metrics_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill blockers retain KGE component decomposition evidence",
            (
                "implemented"
                if skill_kge_component_rows == len(skill_kge_component_required_rows)
                else "missing"
            ),
            (
                f"skill_kge_component_rows={skill_kge_component_rows}; "
                f"required_skill_kge_component_rows={len(skill_kge_component_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill channel-routing attenuation blockers retain locked screen evidence",
            (
                "implemented"
                if skill_channel_screen_rows == len(skill_channel_screen_required_rows)
                else "missing"
            ),
            (
                f"skill_channel_screen_rows={skill_channel_screen_rows}; "
                f"required_skill_channel_screen_rows={len(skill_channel_screen_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill channel-routing refinements retain verified locked-rerun evidence",
            (
                "implemented"
                if skill_channel_refinement_rows == len(skill_channel_refinement_required_rows)
                else "missing"
            ),
            (
                f"skill_channel_refinement_rows={skill_channel_refinement_rows}; "
                f"required_skill_channel_refinement_rows={len(skill_channel_refinement_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill diagnostics retain parameter-governance blockers",
            (
                "implemented"
                if skill_parameter_governance_rows == len(skill_parameter_governance_required_rows)
                else "missing"
            ),
            (
                f"skill_parameter_governance_rows={skill_parameter_governance_rows}; "
                f"required_skill_parameter_governance_rows={len(skill_parameter_governance_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill diagnostic suggested controls expose sensitivity-screen coverage gaps",
            (
                "implemented"
                if skill_probe_gap_rows == len(skill_probe_gap_required_rows)
                else "missing"
            ),
            (
                f"skill_probe_gap_rows={skill_probe_gap_rows}; "
                f"required_skill_probe_gap_rows={len(skill_probe_gap_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill diagnostic suggested controls distinguish screened-dead from unscreened controls",
            (
                "implemented"
                if skill_sensitivity_triage_rows == len(skill_sensitivity_triage_required_rows)
                else "missing"
            ),
            (
                f"skill_sensitivity_triage_rows={skill_sensitivity_triage_rows}; "
                f"required_skill_sensitivity_triage_rows={len(skill_sensitivity_triage_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill diagnostics retain locked-parameter bound context",
            (
                "implemented"
                if skill_bound_context_rows == len(skill_bound_context_required_rows)
                else "missing"
            ),
            (
                f"skill_bound_context_rows={skill_bound_context_rows}; "
                f"required_skill_bound_context_rows={len(skill_bound_context_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Skill diagnostics deprioritize fully bound-exhausted probes",
            (
                "implemented"
                if skill_bound_aware_probe_rows == len(skill_bound_aware_probe_required_rows)
                else "missing"
            ),
            (
                f"skill_bound_aware_probe_rows={skill_bound_aware_probe_rows}; "
                f"required_skill_bound_aware_probe_rows={len(skill_bound_aware_probe_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Superseded unsupported skill controls are marked by current bridge support",
            (
                "implemented"
                if superseded_skill_parameter_rows == len(superseded_skill_parameter_required_rows)
                else "missing"
            ),
            (
                f"superseded_skill_parameter_rows={superseded_skill_parameter_rows}; "
                f"required_superseded_skill_parameter_rows={len(superseded_skill_parameter_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Soil-realism blockers retain build diagnostic artifacts",
            (
                "implemented"
                if soil_realism_diagnostic_rows == len(soil_realism_required_rows)
                else "missing"
            ),
            (
                f"soil_realism_diagnostic_rows={soil_realism_diagnostic_rows}; "
                f"required_soil_realism_rows={len(soil_realism_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Soil-realism blockers expose machine-readable next actions",
            (
                "implemented"
                if soil_realism_remediation_rows == len(soil_realism_required_rows)
                else "missing"
            ),
            (
                f"soil_realism_remediation_rows={soil_realism_remediation_rows}; "
                f"required_soil_realism_rows={len(soil_realism_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Soil-fidelity blockers retain soil provenance fields",
            (
                "implemented"
                if soil_fidelity_provenance_rows == len(soil_fidelity_required_rows)
                else "missing"
            ),
            (
                f"soil_fidelity_provenance_rows={soil_fidelity_provenance_rows}; "
                f"required_soil_fidelity_rows={len(soil_fidelity_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed or warning routing-flow rows retain closure diagnostics",
            (
                "implemented"
                if routing_diagnostic_rows == len(routing_diagnostic_required_rows)
                else "missing"
            ),
            (
                f"routing_diagnostic_rows={routing_diagnostic_rows}; "
                f"required_routing_diagnostic_rows={len(routing_diagnostic_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Failed or warning routing-flow rows retain source coverage diagnostics",
            (
                "implemented"
                if routing_coverage_rows == len(routing_diagnostic_required_rows)
                else "missing"
            ),
            (
                f"routing_coverage_rows={routing_coverage_rows}; "
                f"required_routing_diagnostic_rows={len(routing_diagnostic_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Routing-unit scale-suspect rows retain unit-semantics diagnostics",
            (
                "implemented"
                if routing_unit_semantics_rows == len(routing_unit_semantics_required_rows)
                else "missing"
            ),
            (
                f"routing_unit_semantics_rows={routing_unit_semantics_rows}; "
                f"required_routing_unit_semantics_rows={len(routing_unit_semantics_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Routed-to-channel semantic-ambiguity rows retain diagnostic ratios",
            (
                "implemented"
                if routed_to_channel_semantics_rows == len(routed_to_channel_required_rows)
                else "missing"
            ),
            (
                f"routed_to_channel_semantics_rows={routed_to_channel_semantics_rows}; "
                f"required_routed_to_channel_semantics_rows={len(routed_to_channel_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Routing gate artifact/status mismatches are explicit",
            (
                "implemented"
                if routing_status_mismatch_rows == len(routing_status_mismatch_required_rows)
                else "missing"
            ),
            (
                f"routing_status_mismatch_rows={routing_status_mismatch_rows}; "
                f"required_routing_status_mismatch_rows={len(routing_status_mismatch_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Multi-terminal routing rows retain terminal inventory diagnostics",
            (
                "implemented"
                if terminal_inventory_rows == len(terminal_inventory_required_rows)
                else "missing"
            ),
            (
                f"terminal_inventory_rows={terminal_inventory_rows}; "
                f"required_terminal_inventory_rows={len(terminal_inventory_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Multi-terminal routing rows retain source-backed terminal area context",
            (
                "implemented"
                if terminal_area_context_rows == len(terminal_inventory_required_rows)
                else "missing"
            ),
            (
                f"terminal_area_context_rows={terminal_area_context_rows}; "
                f"required_terminal_area_context_rows={len(terminal_inventory_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Multi-terminal routing rows retain machine-readable area-scope classification",
            (
                "implemented"
                if terminal_area_scope_class_rows == len(terminal_inventory_required_rows)
                else "missing"
            ),
            (
                f"terminal_area_scope_class_rows={terminal_area_scope_class_rows}; "
                f"required_terminal_area_scope_class_rows={len(terminal_inventory_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Multi-terminal routing rows retain official USGS drainage-area authority checks",
            (
                "implemented"
                if terminal_authority_area_context_rows == len(terminal_inventory_required_rows)
                else "missing"
            ),
            (
                f"terminal_authority_area_context_rows={terminal_authority_area_context_rows}; "
                "required_terminal_authority_area_context_rows="
                f"{len(terminal_inventory_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Official-area matching multi-terminal rows retain diagnostic-only virtual outlet candidates",
            (
                "implemented"
                if terminal_virtual_outlet_candidate_rows == len(terminal_virtual_outlet_candidate_required_rows)
                else "missing"
            ),
            (
                f"terminal_virtual_outlet_candidate_rows={terminal_virtual_outlet_candidate_rows}; "
                "required_terminal_virtual_outlet_candidate_rows="
                f"{len(terminal_virtual_outlet_candidate_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Multi-terminal routing rows retain gauge-coordinate terminal ranking context",
            (
                "implemented"
                if terminal_gauge_context_rows == len(terminal_inventory_required_rows)
                else "missing"
            ),
            (
                f"terminal_gauge_context_rows={terminal_gauge_context_rows}; "
                f"required_terminal_gauge_context_rows={len(terminal_inventory_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Selected outlets that are not nearest gauge terminals prioritize outlet reconciliation",
            (
                "implemented"
                if not_nearest_terminal_probe_rows == len(not_nearest_terminal_required_rows)
                else "missing"
            ),
            (
                f"not_nearest_terminal_probe_rows={not_nearest_terminal_probe_rows}; "
                f"required_not_nearest_terminal_probe_rows={len(not_nearest_terminal_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Selected outlets that are not nearest gauge terminals retain conflict classification",
            (
                "implemented"
                if terminal_outlet_conflict_class_rows == len(not_nearest_terminal_required_rows)
                else "missing"
            ),
            (
                f"terminal_outlet_conflict_class_rows={terminal_outlet_conflict_class_rows}; "
                "required_terminal_outlet_conflict_class_rows="
                f"{len(not_nearest_terminal_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Terminal-topology overlap blockers retain pairwise overlap diagnostics",
            (
                "implemented"
                if terminal_topology_overlap_rows == len(terminal_topology_overlap_required_rows)
                else "missing"
            ),
            (
                f"terminal_topology_overlap_rows={terminal_topology_overlap_rows}; "
                "required_terminal_topology_overlap_rows="
                f"{len(terminal_topology_overlap_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "ET-dominated rows require ET parameter screen context",
            (
                "implemented"
                if et_context_rows == len(et_context_required_rows)
                else "missing"
            ),
            (
                f"et_context_rows={et_context_rows}; "
                f"required_et_context_rows={len(et_context_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "ET-dominated rows retain ET partition diagnostics",
            "implemented" if et_diagnostic_rows == len(et_context_required_rows) else "missing",
            (
                f"et_diagnostic_rows={et_diagnostic_rows}; "
                f"required_et_context_rows={len(et_context_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Mass-imbalance rows retain mass-balance closure diagnostics",
            (
                "implemented"
                if mass_balance_diagnostic_rows == len(mass_balance_required_rows)
                else "missing"
            ),
            (
                f"mass_balance_diagnostic_rows={mass_balance_diagnostic_rows}; "
                f"required_mass_balance_rows={len(mass_balance_required_rows)}"
            ),
        )
    )
    checks.append(
        Check(
            "Final completion requires non-seeded physics evidence",
            "implemented" if seeded_rows == 0 else "missing",
            f"seeded_metric_rows={seeded_rows}",
        )
    )


def build_audit() -> dict[str, Any]:
    checks: list[Check] = []
    _append_static_checks(checks)
    report = _load_objective_report()
    rows = _objective_rows(report)
    routing_counts = _routing_status_counts(rows)
    _append_objective_report_checks(checks, report)
    missing = [c for c in checks if c.status != "implemented"]
    return {
        "objective": "research-grade, agent-governed full-mode SWAT+ workflow",
        "objective_report_json": str(OBJECTIVE_REPORT_JSON),
        "implemented": len(checks) - len(missing),
        "total": len(checks),
        "metrics": {
            "research_grade_count": sum(
                1
                for row in rows
                if str(row.get("tier")) == "research_grade"
            ),
            "blocker_domain_action_rows": sum(
                1
                for row in _non_research_rows(rows)
                if _row_blocker_domain_action_plan_ok(row)
            ),
            "required_blocker_domain_action_rows": len(_non_research_rows(rows)),
            "report_blocker_classification_ok": _report_blocker_classification_ok(
                report or {}, rows
            ),
            "target_hypothesis_evaluation_ok": _target_hypothesis_evaluation_ok(
                report or {}, rows
            ),
            "science_blocker_summary_ok": _science_blocker_summary_ok(
                report or {}, rows
            ),
            "pipeline_improvement_plan_ok": _pipeline_improvement_plan_ok(
                report or {}, rows
            ),
            "pipeline_improvement_plan_domains": (
                (report or {}).get("pipeline_improvement_plan", {}).get("domains", [])
                if isinstance((report or {}).get("pipeline_improvement_plan"), dict)
                else []
            ),
            "pipeline_improvement_plan_basin_rows": sum(
                len(item.get("basin_items", []))
                for item in (report or {}).get("pipeline_improvement_plan", {}).get("items", [])
                if isinstance(item, dict) and isinstance(item.get("basin_items"), list)
            )
            if isinstance((report or {}).get("pipeline_improvement_plan"), dict)
            else 0,
            "required_pipeline_improvement_plan_basin_rows": sum(
                1
                for row in _non_research_rows(rows)
                if row.get("blocker_domain")
                in {"engineering", "diagnostics", "calibration", "provenance", "parameter_support"}
            ),
            "pipeline_improvement_decision_request_rows": sum(
                1
                for item in (report or {}).get("pipeline_improvement_plan", {}).get("items", [])
                if isinstance(item, dict)
                for basin_item in item.get("basin_items", [])
                if isinstance(basin_item, dict)
                and _pipeline_improvement_decision_request_ok(
                    basin_item.get("decision_request"),
                    basin_item,
                )
            )
            if isinstance((report or {}).get("pipeline_improvement_plan"), dict)
            else 0,
            "pipeline_improvement_diagnostic_context_rows": (
                _pipeline_improvement_diagnostic_context_rows(report or {})[0]
            ),
            "required_pipeline_improvement_diagnostic_context_rows": (
                _pipeline_improvement_diagnostic_context_rows(report or {})[1]
            ),
            "pipeline_improvement_diagnostic_explanation_rows": (
                _pipeline_improvement_diagnostic_explanation_rows(report or {})[0]
            ),
            "required_pipeline_improvement_diagnostic_explanation_rows": (
                _pipeline_improvement_diagnostic_explanation_rows(report or {})[1]
            ),
            "pipeline_improvement_provenance_context_rows": (
                _pipeline_improvement_provenance_context_rows(report or {})[0]
            ),
            "required_pipeline_improvement_provenance_context_rows": (
                _pipeline_improvement_provenance_context_rows(report or {})[1]
            ),
            "claim_policy_name_rows": sum(
                1
                for row in rows
                if _row_claim_policy_names_ok(row)
            ),
            "hydrograph_rows": sum(
                1
                for row in rows
                if _row_hydrograph_ok(row)
            ),
            "calibration_rows": sum(
                1
                for row in rows
                if str(row.get("calibration")) in {"attempted", "done", "verified"}
            ),
            "calibration_provenance_rows": sum(
                1
                for row in rows
                if _row_calibration_provenance_ok(row)
            ),
            "sensitivity_screen_rows": sum(
                1
                for row in rows
                if _row_sensitivity_screen_ok(row)
            ),
            "research_grade_core_sensitivity_rows": sum(
                1
                for row in _research_grade_core_sensitivity_required_rows(rows)
                if _row_research_grade_core_sensitivity_ok(row)
            ),
            "required_research_grade_core_sensitivity_rows": len(
                _research_grade_core_sensitivity_required_rows(rows)
            ),
            "calibration_delta_rows": sum(
                1
                for row in rows
                if _row_calibration_delta_ok(row)
            ),
            "calibration_regression_rows": sum(
                1
                for row in _calibration_regression_required_rows(rows)
                if _row_calibration_regression_ok(row)
            ),
            "required_calibration_regression_rows": len(_calibration_regression_required_rows(rows)),
            "promotion_gate_failure_rows": sum(
                1
                for row in _promotion_gate_failure_required_rows(rows)
                if _row_promotion_gate_failure_ok(row)
            ),
            "required_promotion_gate_failure_rows": len(
                _promotion_gate_failure_required_rows(rows)
            ),
            "failed_calibration_evidence_rows": sum(
                1
                for row in _failed_calibration_required_rows(rows)
                if _row_failed_calibration_evidence_ok(row)
            ),
            "required_failed_calibration_rows": len(_failed_calibration_required_rows(rows)),
            "failed_calibration_context_rows": sum(
                1
                for row in _failed_calibration_context_required_rows(rows)
                if _row_failed_calibration_context_ok(row)
            ),
            "required_failed_calibration_context_rows": len(_failed_calibration_context_required_rows(rows)),
            "calibration_phase_coverage_rows": sum(
                1
                for row in _calibration_phase_coverage_required_rows(rows)
                if _row_calibration_phase_coverage_ok(row)
            ),
            "required_calibration_phase_coverage_rows": len(
                _calibration_phase_coverage_required_rows(rows)
            ),
            "calibration_bound_interaction_rows": sum(
                1
                for row in _calibration_bound_interaction_required_rows(rows)
                if _row_calibration_bound_interaction_ok(row)
            ),
            "required_calibration_bound_interaction_rows": len(
                _calibration_bound_interaction_required_rows(rows)
            ),
            "failed_calibration_physical_trace_rows": sum(
                1
                for row in _failed_calibration_physical_trace_required_rows(rows)
                if _row_failed_calibration_physical_trace_ok(row)
            ),
            "required_failed_calibration_physical_trace_rows": len(
                _failed_calibration_physical_trace_required_rows(rows)
            ),
            "failed_calibration_process_trace_rows": sum(
                1
                for row in _failed_calibration_process_trace_required_rows(rows)
                if _row_failed_calibration_process_trace_ok(row)
            ),
            "required_failed_calibration_process_trace_rows": len(
                _failed_calibration_process_trace_required_rows(rows)
            ),
            "calibration_precheck_rows": sum(
                1
                for row in _calibration_precheck_required_rows(rows)
                if _row_calibration_precheck_ok(row)
            ),
            "required_calibration_precheck_rows": len(_calibration_precheck_required_rows(rows)),
            "failed_calibration_tradeoff_frontier_rows": sum(
                1
                for row in _failed_calibration_context_required_rows(rows)
                if _row_failed_calibration_tradeoff_frontier_ok(row)
            ),
            "required_failed_calibration_tradeoff_frontier_rows": len(
                _failed_calibration_context_required_rows(rows)
            ),
            "failed_calibration_terminal_scope_history_rows": sum(
                1
                for row in _failed_calibration_terminal_scope_history_required_rows(rows)
                if _row_failed_calibration_terminal_scope_history_ok(row)
            ),
            "required_failed_calibration_terminal_scope_history_rows": len(
                _failed_calibration_terminal_scope_history_required_rows(rows)
            ),
            "volume_diagnostic_rows": sum(
                1
                for row in _volume_diagnostic_required_rows(rows)
                if _row_volume_diagnostics_ok(row)
            ),
            "required_volume_diagnostic_rows": len(_volume_diagnostic_required_rows(rows)),
            "terminal_hydrograph_scope_rows": sum(
                1
                for row in _terminal_hydrograph_scope_required_rows(rows)
                if _row_terminal_hydrograph_scope_ok(row)
            ),
            "required_terminal_hydrograph_scope_rows": len(
                _terminal_hydrograph_scope_required_rows(rows)
            ),
            "terminal_hydrograph_kge_component_rows": sum(
                1
                for row in _terminal_hydrograph_scope_required_rows(rows)
                if _row_terminal_hydrograph_kge_component_ok(row)
            ),
            "required_terminal_hydrograph_kge_component_rows": len(
                _terminal_hydrograph_scope_required_rows(rows)
            ),
            "terminal_hydrograph_aggregation_context_rows": sum(
                1
                for row in _terminal_hydrograph_scope_required_rows(rows)
                if _row_terminal_hydrograph_aggregation_context_ok(row)
            ),
            "required_terminal_hydrograph_aggregation_context_rows": len(
                _terminal_hydrograph_scope_required_rows(rows)
            ),
            "terminal_hydrograph_scope_class_rows": sum(
                1
                for row in _terminal_hydrograph_scope_required_rows(rows)
                if _row_terminal_hydrograph_scope_class_ok(row)
            ),
            "required_terminal_hydrograph_scope_class_rows": len(
                _terminal_hydrograph_scope_required_rows(rows)
            ),
            "terminal_scope_resolution_plan_rows": sum(
                1
                for row in _terminal_hydrograph_scope_required_rows(rows)
                if _row_terminal_scope_resolution_plan_ok(row)
            ),
            "required_terminal_scope_resolution_plan_rows": len(
                _terminal_hydrograph_scope_required_rows(rows)
            ),
            "nearest_terminal_hydrograph_rows": sum(
                1
                for row in _nearest_terminal_hydrograph_required_rows(rows)
                if _row_nearest_terminal_hydrograph_ok(row)
            ),
            "required_nearest_terminal_hydrograph_rows": len(
                _nearest_terminal_hydrograph_required_rows(rows)
            ),
            "post_aggregation_volume_deficit_rows": sum(
                1
                for row in _post_aggregation_volume_deficit_required_rows(rows)
                if _row_post_aggregation_volume_deficit_ok(row)
            ),
            "required_post_aggregation_volume_deficit_rows": len(
                _post_aggregation_volume_deficit_required_rows(rows)
            ),
            "post_aggregation_process_context_rows": sum(
                1
                for row in _post_aggregation_volume_deficit_required_rows(rows)
                if _row_post_aggregation_process_context_ok(row)
            ),
            "required_post_aggregation_process_context_rows": len(
                _post_aggregation_volume_deficit_required_rows(rows)
            ),
            "post_aggregation_candidate_explanation_rows": sum(
                1
                for row in _post_aggregation_volume_deficit_required_rows(rows)
                if _row_post_aggregation_candidate_explanations_ok(row)
            ),
            "required_post_aggregation_candidate_explanation_rows": len(
                _post_aggregation_volume_deficit_required_rows(rows)
            ),
            "volume_forcing_context_rows": sum(
                1
                for row in _volume_diagnostic_required_rows(rows)
                if _row_volume_forcing_context_ok(row)
            ),
            "required_volume_forcing_context_rows": len(_volume_diagnostic_required_rows(rows)),
            "volume_forcing_plausibility_rows": sum(
                1
                for row in _volume_diagnostic_required_rows(rows)
                if _row_volume_forcing_plausibility_ok(row)
            ),
            "required_volume_forcing_plausibility_rows": len(_volume_diagnostic_required_rows(rows)),
            "high_runoff_demand_context_rows": sum(
                1
                for row in _high_runoff_demand_required_rows(rows)
                if _row_high_runoff_demand_context_ok(row)
            ),
            "high_runoff_interpretation_rows": sum(
                1
                for row in _high_runoff_demand_required_rows(rows)
                if _row_high_runoff_interpretation_ok(row)
            ),
            "required_high_runoff_demand_rows": len(_high_runoff_demand_required_rows(rows)),
            "terminal_scope_blocker_rows": sum(
                1
                for row in _terminal_hydrograph_scope_required_rows(rows)
                if _row_terminal_scope_blocker_ok(row)
            ),
            "required_terminal_scope_blocker_rows": len(
                _terminal_hydrograph_scope_required_rows(rows)
            ),
            "routing_terminal_scope_blocker_rows": sum(
                1
                for row in _routing_terminal_scope_required_rows(rows)
                if _row_terminal_scope_blocker_ok(row)
            ),
            "required_routing_terminal_scope_blocker_rows": len(
                _routing_terminal_scope_required_rows(rows)
            ),
            "terminal_scope_claim_blocked_rows": sum(
                1
                for row in _terminal_scope_claim_required_rows(rows)
                if _row_terminal_scope_claim_blocked_ok(row)
            ),
            "required_terminal_scope_claim_rows": len(_terminal_scope_claim_required_rows(rows)),
            "virtual_outlet_scope_gate_rows": sum(
                1
                for row in _virtual_outlet_scope_required_rows(rows)
                if _row_virtual_outlet_scope_gate_ok(row)
            ),
            "required_virtual_outlet_scope_rows": len(_virtual_outlet_scope_required_rows(rows)),
            "terminal_scope_probe_priority_rows": sum(
                1
                for row in _terminal_hydrograph_scope_required_rows(rows)
                if _row_terminal_scope_probe_priority_ok(row)
            ),
            "required_terminal_scope_probe_priority_rows": len(
                _terminal_hydrograph_scope_required_rows(rows)
            ),
            "skill_diagnostic_rows": sum(
                1
                for row in _skill_diagnostic_required_rows(rows)
                if _row_skill_diagnostics_ok(row)
            ),
            "required_skill_diagnostic_rows": len(_skill_diagnostic_required_rows(rows)),
            "skill_limitation_class_rows": sum(
                1
                for row in _skill_diagnostic_required_rows(rows)
                if _row_skill_limitation_class_ok(row)
            ),
            "required_skill_limitation_class_rows": len(_skill_diagnostic_required_rows(rows)),
            "skill_evidence_metrics_rows": sum(
                1
                for row in _skill_evidence_metrics_required_rows(rows)
                if _row_skill_evidence_metrics_ok(row)
            ),
            "required_skill_evidence_metrics_rows": len(
                _skill_evidence_metrics_required_rows(rows)
            ),
            "skill_kge_component_rows": sum(
                1
                for row in _skill_kge_component_required_rows(rows)
                if _row_skill_kge_component_ok(row)
            ),
            "required_skill_kge_component_rows": len(
                _skill_kge_component_required_rows(rows)
            ),
            "skill_channel_screen_rows": sum(
                1
                for row in _skill_channel_screen_required_rows(rows)
                if _row_skill_channel_screen_ok(row)
            ),
            "required_skill_channel_screen_rows": len(_skill_channel_screen_required_rows(rows)),
            "skill_channel_refinement_rows": sum(
                1
                for row in _skill_channel_refinement_required_rows(rows)
                if _row_skill_channel_refinement_ok(row)
            ),
            "required_skill_channel_refinement_rows": len(
                _skill_channel_refinement_required_rows(rows)
            ),
            "skill_probe_gap_rows": sum(
                1
                for row in _skill_probe_gap_required_rows(rows)
                if _row_skill_probe_gap_ok(row)
            ),
            "required_skill_probe_gap_rows": len(_skill_probe_gap_required_rows(rows)),
            "skill_sensitivity_triage_rows": sum(
                1
                for row in _skill_sensitivity_triage_required_rows(rows)
                if _row_skill_sensitivity_triage_ok(row)
            ),
            "required_skill_sensitivity_triage_rows": len(
                _skill_sensitivity_triage_required_rows(rows)
            ),
            "skill_bound_context_rows": sum(
                1
                for row in _skill_bound_context_required_rows(rows)
                if _row_skill_bound_context_ok(row)
            ),
            "required_skill_bound_context_rows": len(_skill_bound_context_required_rows(rows)),
            "skill_bound_aware_probe_rows": sum(
                1
                for row in _skill_bound_aware_probe_required_rows(rows)
                if _row_skill_bound_aware_probe_order_ok(row)
            ),
            "required_skill_bound_aware_probe_rows": len(
                _skill_bound_aware_probe_required_rows(rows)
            ),
            "skill_parameter_governance_rows": sum(
                1
                for row in _skill_parameter_governance_required_rows(rows)
                if _row_skill_parameter_governance_ok(row)
            ),
            "required_skill_parameter_governance_rows": len(
                _skill_parameter_governance_required_rows(rows)
            ),
            "superseded_skill_parameter_rows": sum(
                1
                for row in _superseded_skill_parameter_required_rows(rows)
                if _row_superseded_skill_parameter_ok(row)
            ),
            "required_superseded_skill_parameter_rows": len(
                _superseded_skill_parameter_required_rows(rows)
            ),
            "soil_realism_diagnostic_rows": sum(
                1
                for row in _soil_realism_required_rows(rows)
                if _row_soil_realism_diagnostics_ok(row)
            ),
            "soil_realism_remediation_rows": sum(
                1
                for row in _soil_realism_required_rows(rows)
                if _row_soil_realism_remediation_ok(row)
            ),
            "required_soil_realism_rows": len(_soil_realism_required_rows(rows)),
            "soil_fidelity_provenance_rows": sum(
                1
                for row in _soil_fidelity_required_rows(rows)
                if _row_soil_fidelity_provenance_ok(row)
            ),
            "required_soil_fidelity_rows": len(_soil_fidelity_required_rows(rows)),
            "routing_diagnostic_rows": sum(
                1
                for row in _routing_diagnostic_required_rows(rows)
                if _row_routing_diagnostics_ok(row)
            ),
            "routing_source_coverage_rows": sum(
                1
                for row in _routing_diagnostic_required_rows(rows)
                if _row_routing_source_coverage_ok(row)
            ),
            "required_routing_diagnostic_rows": len(_routing_diagnostic_required_rows(rows)),
            "routing_unit_semantics_rows": sum(
                1
                for row in _routing_unit_semantics_required_rows(rows)
                if _row_routing_unit_semantics_ok(row)
            ),
            "required_routing_unit_semantics_rows": len(_routing_unit_semantics_required_rows(rows)),
            "routed_to_channel_semantics_rows": sum(
                1
                for row in _routed_to_channel_semantics_required_rows(rows)
                if _row_routed_to_channel_semantics_ok(row)
            ),
            "required_routed_to_channel_semantics_rows": len(
                _routed_to_channel_semantics_required_rows(rows)
            ),
            "routing_status_mismatch_rows": sum(
                1
                for row in _routing_status_mismatch_required_rows(rows)
                if _row_routing_status_mismatch_ok(row)
            ),
            "required_routing_status_mismatch_rows": len(
                _routing_status_mismatch_required_rows(rows)
            ),
            "terminal_inventory_rows": sum(
                1
                for row in _terminal_inventory_required_rows(rows)
                if _row_terminal_inventory_ok(row)
            ),
            "required_terminal_inventory_rows": len(_terminal_inventory_required_rows(rows)),
            "terminal_area_context_rows": sum(
                1
                for row in _terminal_inventory_required_rows(rows)
                if _row_terminal_area_context_ok(row)
            ),
            "required_terminal_area_context_rows": len(_terminal_inventory_required_rows(rows)),
            "terminal_area_scope_class_rows": sum(
                1
                for row in _terminal_inventory_required_rows(rows)
                if _row_terminal_area_scope_class_ok(row)
            ),
            "required_terminal_area_scope_class_rows": len(_terminal_inventory_required_rows(rows)),
            "terminal_authority_area_context_rows": sum(
                1
                for row in _terminal_inventory_required_rows(rows)
                if _row_terminal_authority_area_context_ok(row)
            ),
            "required_terminal_authority_area_context_rows": len(
                _terminal_inventory_required_rows(rows)
            ),
            "terminal_virtual_outlet_candidate_rows": sum(
                1
                for row in _terminal_virtual_outlet_candidate_required_rows(rows)
                if _row_terminal_virtual_outlet_candidate_ok(row)
            ),
            "required_terminal_virtual_outlet_candidate_rows": len(
                _terminal_virtual_outlet_candidate_required_rows(rows)
            ),
            "terminal_gauge_context_rows": sum(
                1
                for row in _terminal_inventory_required_rows(rows)
                if _row_terminal_gauge_context_ok(row)
            ),
            "required_terminal_gauge_context_rows": len(_terminal_inventory_required_rows(rows)),
            "not_nearest_terminal_probe_rows": sum(
                1
                for row in _not_nearest_terminal_required_rows(rows)
                if _row_not_nearest_terminal_probe_ok(row)
            ),
            "required_not_nearest_terminal_probe_rows": len(
                _not_nearest_terminal_required_rows(rows)
            ),
            "terminal_outlet_conflict_class_rows": sum(
                1
                for row in _not_nearest_terminal_required_rows(rows)
                if _row_terminal_outlet_conflict_class_ok(row)
            ),
            "required_terminal_outlet_conflict_class_rows": len(
                _not_nearest_terminal_required_rows(rows)
            ),
            "terminal_topology_overlap_rows": sum(
                1
                for row in _terminal_topology_overlap_required_rows(rows)
                if _row_terminal_topology_overlap_ok(row)
            ),
            "required_terminal_topology_overlap_rows": len(
                _terminal_topology_overlap_required_rows(rows)
            ),
            "et_context_rows": sum(
                1
                for row in _et_context_required_rows(rows)
                if _row_et_context_ok(row)
            ),
            "et_diagnostic_rows": sum(
                1
                for row in _et_context_required_rows(rows)
                if _row_et_diagnostics_ok(row)
            ),
            "required_et_context_rows": len(_et_context_required_rows(rows)),
            "mass_balance_diagnostic_rows": sum(
                1
                for row in _mass_balance_required_rows(rows)
                if _row_mass_balance_diagnostics_ok(row)
            ),
            "required_mass_balance_rows": len(_mass_balance_required_rows(rows)),
            "physical_gate_artifact_rows": sum(
                1 for row in rows if _row_physical_gate_artifact_ok(row)
            ),
            "required_physical_gate_artifact_rows": len(rows),
            "routing_status_counts": routing_counts,
            "primary_blocker_counts": _primary_blocker_counts(rows),
        },
        "checks": [asdict(c) for c in checks],
        "overall_status": "not_complete" if missing else "complete",
    }


def main() -> None:
    out = build_audit()
    out_dir = ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "OBJECTIVE_COMPLIANCE_AUDIT.json"
    md_path = out_dir / "OBJECTIVE_COMPLIANCE_AUDIT.md"
    json_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Objective Compliance Audit",
        "",
        f"Overall: **{out['overall_status']}** ({out['implemented']}/{out['total']} checks implemented)",
        "",
        "| Requirement | Status | Evidence |",
        "|---|---|---|",
    ]
    for c in out["checks"]:
        lines.append(f"| {c['requirement']} | {c['status']} | {c['evidence']} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {"json": str(json_path), "md": str(md_path), "overall_status": out["overall_status"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
