#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from swatplus_builder.evidence.migration import migrate_legacy_bundle

OBJECTIVE_REPORT_JSON = ROOT / "docs" / "objective_basin_validation_report.json"
OBJECTIVE_REPORT_MD = ROOT / "docs" / "OBJECTIVE_BASIN_VALIDATION_REPORT.md"
OVERLAY_REPAIR_REPORT = (
    ROOT
    / "swatplus_runs"
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

_RESEARCH_REQUIRED_GATES: frozenset[str] = frozenset({
    "fresh_engine_output",
    "benchmark_lock",
    "outlet_provenance",
    "physical_gates",
    "routing_flow",
    "calibration_verification",
    "sensitivity_screen",
})


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


def _objective_rows(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = (report or {}).get("rows", [])
    return [row for row in rows if isinstance(row, dict)]


def _load_evidence_summary(row: dict[str, Any]) -> dict[str, Any] | None:
    path_str = row.get("evidence_summary_path")
    if not path_str:
        return None
    p = Path(str(path_str))
    if not p.is_file():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _tier_consistent_with_gates(bundle: Any) -> bool:
    if bundle.effective_claim_tier != "research_grade":
        return True
    failed_gate_ids = {g.gate_id for g in bundle.gate_table if g.status == "failed"}
    return not bool(failed_gate_ids & _RESEARCH_REQUIRED_GATES)


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
                "swatplus_runs/post_overlay_repair_01013500_network/reports/overlay_repair/overlay_repair_report.json"
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


def _inv_blocked_claims_have_reasons(rows: list[dict[str, Any]]) -> Check:
    failures: list[str] = []
    for row in rows:
        ev = _load_evidence_summary(row)
        if ev is None:
            continue
        try:
            bundle = migrate_legacy_bundle(ev)
        except Exception as exc:
            failures.append(f"{row.get('basin', '?')}: migration error: {exc}")
            continue
        for claim in bundle.claims:
            if claim.status == "blocked" and not (isinstance(claim.reason, str) and claim.reason.strip()):
                failures.append(f"{row.get('basin', '?')}: claim {claim.claim_id!r} blocked without reason")
    return Check(
        "I1 Every blocked claim has typed reason",
        "implemented" if not failures else "missing",
        "; ".join(failures[:5]) or "all blocked claims have typed reasons",
    )


def _inv_artifact_dirs_exist(rows: list[dict[str, Any]]) -> Check:
    failures: list[str] = []
    for row in rows:
        ev = _load_evidence_summary(row)
        if ev is None:
            continue
        if not ev.get("success"):
            continue
        artifact_dir = ev.get("artifact_dir")
        if not artifact_dir or not Path(str(artifact_dir)).is_dir():
            failures.append(f"{row.get('basin', '?')}: artifact_dir missing or absent ({artifact_dir!r})")
    return Check(
        "I2 Artifact directory exists for every completed run",
        "implemented" if not failures else "missing",
        "; ".join(failures[:5]) or "all completed runs have artifact directories",
    )


def _inv_bundles_migrate_to_v1(rows: list[dict[str, Any]]) -> Check:
    failures: list[str] = []
    for row in rows:
        ev = _load_evidence_summary(row)
        if ev is None:
            continue
        try:
            bundle = migrate_legacy_bundle(ev)
            assert bundle.schema_version == "1.0"
        except Exception as exc:
            failures.append(f"{row.get('basin', '?')}: {exc}")
    return Check(
        "I3 All evidence bundles migrate to v1 schema",
        "implemented" if not failures else "missing",
        "; ".join(failures[:5]) or "all bundles migrate cleanly to v1",
    )


def _inv_tier_vector_consistent(rows: list[dict[str, Any]]) -> Check:
    failures: list[str] = []
    for row in rows:
        ev = _load_evidence_summary(row)
        if ev is None:
            continue
        try:
            bundle = migrate_legacy_bundle(ev)
        except Exception:
            continue
        if not _tier_consistent_with_gates(bundle):
            failed_gates = [g.gate_id for g in bundle.gate_table if g.status == "failed"]
            failures.append(
                f"{row.get('basin', '?')}: tier={bundle.effective_claim_tier!r} but required gates failed: {failed_gates}"
            )
    return Check(
        "I4 Effective claim tier consistent with gate table",
        "implemented" if not failures else "missing",
        "; ".join(failures[:5]) or "all tier vectors consistent with gate tables",
    )


def build_audit() -> dict[str, Any]:
    checks: list[Check] = []
    _append_static_checks(checks)

    report = _load_objective_report()
    rows = _objective_rows(report)
    reported_basins = {str(row.get("basin", "")) for row in rows}

    # Basin coverage check
    checks.append(
        Check(
            "Objective report covers the requested basin suite",
            "implemented" if REQUIRED_BASINS.issubset(reported_basins) else "missing",
            f"required={sorted(REQUIRED_BASINS)} reported={sorted(reported_basins)}",
        )
    )

    # 4 generic evidence-bundle invariants
    checks.append(_inv_blocked_claims_have_reasons(rows))
    checks.append(_inv_artifact_dirs_exist(rows))
    checks.append(_inv_bundles_migrate_to_v1(rows))
    checks.append(_inv_tier_vector_consistent(rows))

    missing = [c for c in checks if c.status != "implemented"]
    return {
        "objective": "research-grade, agent-governed full-mode SWAT+ workflow",
        "objective_report_json": str(OBJECTIVE_REPORT_JSON),
        "implemented": len(checks) - len(missing),
        "total": len(checks),
        "overall_status": "complete" if not missing else "not_complete",
        "checks": [asdict(c) for c in checks],
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
