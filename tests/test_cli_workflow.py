from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from swatplus_builder.cli import app


def test_workflow_negotiate_needs_input(tmp_path: Path):
    runner = CliRunner()
    out = tmp_path / "c1"
    res = runner.invoke(
        app,
        [
            "workflow",
            "negotiate",
            "--task",
            "Calibrate basin 01654000",
            "--out-dir",
            str(out),
            "--json",
        ],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["status"] == "needs_input"
    assert Path(payload["workflow_contract_json"]).exists()


def test_workflow_negotiate_research_short_window_policy_block(tmp_path: Path):
    runner = CliRunner()
    out = tmp_path / "c2"
    res = runner.invoke(
        app,
        [
            "workflow",
            "negotiate",
            "--task",
            "Research-grade SWAT run for USGS 01654000 from 2019-01-01 to 2020-12-31",
            "--out-dir",
            str(out),
            "--json",
        ],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["status"] == "needs_input"
    assert "research_claim_requires_>=10_year_window" in payload["policy_issues"]
    assert "longer_time_window" in payload["needs_input"]


def test_workflow_run_with_contract_blocks_research_without_acceptance(tmp_path: Path):
    runner = CliRunner()
    cdir = tmp_path / "contract"
    cdir.mkdir(parents=True)
    contract = cdir / "workflow_contract.json"
    contract.write_text(
        json.dumps(
            {
                "status": "planned",
                "workflow_name": "x",
                "usgs_id": "01654000",
                "start": "2015-01-01",
                "end": "2015-12-31",
                "claim_tier": "research_grade",
                "contract_status": "draft",
                "accepted_by": None,
                "needs_input": [],
            }
        ),
        encoding="utf-8",
    )

    out = tmp_path / "run"
    res = runner.invoke(
        app,
        [
            "workflow",
            "run",
            "--usgs-id",
            "01654000",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--contract",
            str(contract),
            "--out-dir",
            str(out),
            "--json",
        ],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    ev = json.loads(Path(payload["evidence_summary_path"]).read_text(encoding="utf-8"))
    assert ev["blocker_class"] == "contract_policy_blocked"
    assert ev["claim_tier"] == "diagnostic"
