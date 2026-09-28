from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swatplus_builder.audit import (
    GENESIS_SHA256,
    HashChainedLedger,
    RunAuditTrail,
    archive_previous_trail,
    export_decision_episodes,
    iter_records,
    verify_ledger,
    verify_run_audit,
)
from swatplus_builder.cli import app
from swatplus_builder.workflows.usgs_e2e import RunUSGSWorkflowRequest, run_usgs_workflow


def _ledger_with(tmp_path: Path, n: int = 3) -> Path:
    path = tmp_path / "ledger.jsonl"
    ledger = HashChainedLedger(path)
    for i in range(n):
        ledger.append({"stage": f"s{i}", "value": i})
    return path


def _rewrite(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


# ---------------------------------------------------------------------------
# Hash chain
# ---------------------------------------------------------------------------


def test_ledger_chain_links_and_verifies(tmp_path: Path) -> None:
    path = _ledger_with(tmp_path)
    records = list(iter_records(path))
    assert [r["seq"] for r in records] == [0, 1, 2]
    assert records[0]["prev_sha256"] == GENESIS_SHA256
    assert records[1]["prev_sha256"] == records[0]["sha256"]
    result = verify_ledger(path, expected_head=records[-1]["sha256"])
    assert result.ok, result.problems
    assert result.record_count == 3


def test_ledger_resumes_chain_when_reopened(tmp_path: Path) -> None:
    path = _ledger_with(tmp_path, n=2)
    reopened = HashChainedLedger(path)
    entry = reopened.append({"stage": "later"})
    assert entry["seq"] == 2
    assert verify_ledger(path).ok


def test_ledger_detects_edited_record(tmp_path: Path) -> None:
    path = _ledger_with(tmp_path)
    records = list(iter_records(path))
    records[1]["value"] = 999
    _rewrite(path, records)
    result = verify_ledger(path)
    assert not result.ok
    assert result.first_bad_seq == 1


def test_ledger_detects_deleted_record(tmp_path: Path) -> None:
    path = _ledger_with(tmp_path)
    records = list(iter_records(path))
    _rewrite(path, [records[0], records[2]])
    result = verify_ledger(path)
    assert not result.ok
    assert result.first_bad_seq == 1


def test_ledger_detects_truncation_against_sealed_head(tmp_path: Path) -> None:
    path = _ledger_with(tmp_path)
    records = list(iter_records(path))
    sealed = records[-1]["sha256"]
    _rewrite(path, records[:-1])
    assert verify_ledger(path).ok  # the chain alone cannot see a cut tail...
    assert not verify_ledger(path, expected_head=sealed).ok  # ...the sealed head can


def test_ledger_rejects_reserved_fields(tmp_path: Path) -> None:
    ledger = HashChainedLedger(tmp_path / "l.jsonl")
    with pytest.raises(ValueError, match="reserved"):
        ledger.append({"sha256": "forged"})


# ---------------------------------------------------------------------------
# Decisions and episodes
# ---------------------------------------------------------------------------


def test_decision_requires_chosen_option_in_option_set(tmp_path: Path) -> None:
    trail = RunAuditTrail(tmp_path, run_id="r", basin_id="01")
    with pytest.raises(ValueError, match="not one of"):
        trail.decision("x", state={}, options=["a", "b"], chosen="c", policy="p")


def test_decisions_export_as_episodes_with_outcomes(tmp_path: Path) -> None:
    trail = RunAuditTrail(tmp_path, run_id="r", basin_id="01547700", attempt_id="a1")
    trail.event("environment", "captured", git_sha="abc", engine_sha256="def", package_version="0")
    did = trail.decision(
        "calibration_precheck",
        state={"physical_gates_status": "passed"},
        options=["run_diagnostic_calibration", "block_calibration"],
        chosen="run_diagnostic_calibration",
        policy="rule",
    )
    trail.outcome(did, {"calibration_success": True})
    trail.decision("unresolved", state={}, options=["a"], chosen="a", policy="rule")

    episodes = {e["decision_point"]: e for e in export_decision_episodes(tmp_path)}
    ep = episodes["calibration_precheck"]
    assert ep["episode_id"] == "r@a1:calibration_precheck:1"
    assert ep["chosen_action"] == "run_diagnostic_calibration"
    assert ep["outcome_vector"] == {"calibration_success": True}
    assert ep["split_group"] == "01547700"
    assert ep["builder_git_sha"] == "abc"
    assert len(ep["ledger_record_sha256"]) == 2
    assert episodes["unresolved"]["outcome_observed"] is False


def test_archive_previous_trail_keeps_old_attempts(tmp_path: Path) -> None:
    RunAuditTrail(tmp_path, run_id="r", basin_id="01").event("workflow", "started")
    moved = archive_previous_trail(tmp_path)
    assert len(moved) == 1
    assert not (tmp_path / "events.jsonl").exists()
    assert verify_ledger(moved[0]).ok


# ---------------------------------------------------------------------------
# Workflow integration
# ---------------------------------------------------------------------------


def _fake_pipeline_factory(txt: Path):
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 0 0 basin 1000 300 0 100 100 200 500\n",
        encoding="utf-8",
    )

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "metrics": {"nse": 0.30, "kge": 0.45},
        }

    return fake_run_pipeline


def _run(monkeypatch, out: Path, **overrides) -> Path:
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e.run_pipeline",
        _fake_pipeline_factory(out / "project" / "TxtInOut"),
    )
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=out,
        start="2010-01-01",
        end="2019-12-31",
        warmup_years=3,
        calibrate=False,
        **overrides,
    )
    return Path(run_usgs_workflow(req).artifact_dir)


def test_workflow_writes_sealed_verifiable_ledgers(monkeypatch, tmp_path: Path) -> None:
    run_dir = _run(monkeypatch, tmp_path / "run")

    report = verify_run_audit(run_dir)
    assert report["ok"], report

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["audit_ledgers"]["decisions"]["records"] >= 3

    events = list(iter_records(run_dir / "events.jsonl"))
    stages = [e["stage"] for e in events]
    assert stages[:2] == ["workflow", "environment"]
    assert stages[-1] == "evidence_sealed"
    assert "evidence_summary.json" in events[-1]["artifacts_sha256"]

    points = {e["decision_point"] for e in export_decision_episodes(run_dir)}
    assert {"claim_tier_contract", "effective_claim_tier"} <= points


def test_workflow_rerun_archives_previous_attempt(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "run"
    _run(monkeypatch, out)
    _run(monkeypatch, out)
    archived = sorted((out / "audit_history").glob("*.jsonl"))
    assert len(archived) == 2  # previous events + decisions
    assert verify_run_audit(out)["ok"]


def test_workflow_tampering_is_detected(monkeypatch, tmp_path: Path) -> None:
    run_dir = _run(monkeypatch, tmp_path / "run")
    path = run_dir / "decisions.jsonl"
    records = list(iter_records(path))
    first = next(r for r in records if r.get("decision_point") == "effective_claim_tier")
    first["chosen"] = "research_grade"
    _rewrite(path, [first if r["seq"] == first["seq"] else r for r in records])
    assert not verify_run_audit(run_dir)["ok"]


def test_unrecognized_claim_tier_falls_back_to_diagnostic(monkeypatch, tmp_path: Path) -> None:
    run_dir = _run(monkeypatch, tmp_path / "run", claim_tier="research")  # typo
    data = json.loads((run_dir / "evidence_summary.json").read_text(encoding="utf-8"))
    assert data["claim_tier"] == "diagnostic"
    assert "unrecognized_claim_tier:research" in data["values"]["policy_notes"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_audit_verify_and_episodes(monkeypatch, tmp_path: Path) -> None:
    run_dir = _run(monkeypatch, tmp_path / "run")
    runner = CliRunner()

    res = runner.invoke(app, ["audit", "verify", str(run_dir), "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["ok"] is True

    out = tmp_path / "episodes.jsonl"
    res = runner.invoke(app, ["audit", "episodes", str(run_dir), "--out", str(out)])
    assert res.exit_code == 0, res.output
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows and all(r["schema"] == "swatplus_builder.decision_episode/v1" for r in rows)

    (run_dir / "events.jsonl").write_text("{}\n", encoding="utf-8")
    res = runner.invoke(app, ["audit", "verify", str(run_dir), "--json"])
    assert res.exit_code == 1
