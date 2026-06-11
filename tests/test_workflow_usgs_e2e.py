from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.workflows.usgs_e2e import RunUSGSWorkflowRequest, run_usgs_workflow


def test_contract_policy_blocks_research_without_acceptance(tmp_path: Path):
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run",
        claim_tier="research_grade",
        contract_status="draft",
        accepted_by=None,
    )
    res = run_usgs_workflow(req)
    assert res.success is False
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    assert data["blocker_class"] == "contract_policy_blocked"
    assert data["claim_tier"] == "diagnostic"


def test_contract_policy_allows_research_with_window_and_acceptance(tmp_path: Path):
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run2",
        claim_tier="research_grade",
        contract_status="accepted",
        accepted_by="user",
        start="2010-01-01",
        end="2019-12-31",
        warmup_years=3,
    )
    # run_pipeline may fail in CI env; we only assert policy path and evidence emitted.
    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    assert data["claim_tier"] == "research_grade"
    assert "provenance_hash" in data
    assert data["values"]["policy_split"] == "chronological_60_40"
    assert data["values"]["calibration_start"] == "2010-01-01"
    assert data["values"]["validation_end"] == "2019-12-31"
    assert "calibration_attempted" in data["values"]
    assert "outlet_provenance_path" in data["values"]


def test_short_window_downgrades_to_exploratory(tmp_path: Path):
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run3",
        claim_tier="diagnostic",
        start="2018-01-01",
        end="2020-12-31",
        warmup_years=1,
    )
    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    assert data["claim_tier"] == "exploratory"
    assert "window_short_for_diagnostic" in data["values"]["policy_notes"]
