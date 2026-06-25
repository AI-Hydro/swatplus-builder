from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from swatplus_builder import cli as cli_module
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


def test_workflow_run_acceptance_flags_reach_contract_policy(tmp_path: Path):
    runner = CliRunner()
    out = tmp_path / "run_flags"
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
            "--claim-tier",
            "research_grade",
            "--contract-status",
            "accepted",
            "--accepted-by",
            "user",
            "--out-dir",
            str(out),
            "--json",
        ],
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    ev = json.loads(Path(payload["evidence_summary_path"]).read_text(encoding="utf-8"))
    assert ev["values"]["requested_claim_tier"] == "research_grade"
    assert ev["values"]["policy_notes"] == ["window_short_for_research"]
    assert ev["blocker_class"] == "contract_policy_blocked"


def test_workflow_run_hru_options_reach_request(monkeypatch, tmp_path: Path):
    from swatplus_builder.workflows import usgs_e2e

    seen = {}

    def fake_run(req):
        seen["hru_mode"] = req.hru_mode
        seen["min_hru_fraction"] = req.min_hru_fraction
        evidence = Path(req.out_dir) / "evidence_summary.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        return usgs_e2e.RunUSGSWorkflowResult(
            success=True,
            run_id="fake",
            artifact_dir=str(req.out_dir),
            evidence_summary_path=str(evidence),
            blocker_class=None,
            values={"effective_claim_tier": "diagnostic"},
        )

    monkeypatch.setattr(usgs_e2e, "run_usgs_workflow", fake_run)

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "workflow",
            "run",
            "--usgs-id",
            "01654000",
            "--hru-mode",
            "full_overlay",
            "--min-hru-fraction",
            "0.001",
            "--out-dir",
            str(tmp_path / "run_hru"),
            "--json",
        ],
    )

    assert res.exit_code == 0, res.stdout
    assert seen == {"hru_mode": "full_overlay", "min_hru_fraction": 0.001}


def test_workflow_run_json_stdout_suppresses_internal_progress(monkeypatch, tmp_path: Path):
    import sys

    from swatplus_builder.workflows import usgs_e2e

    def fake_run(req):
        print("NOISY INTERNAL PROGRESS")
        print("NOISY INTERNAL STDERR", file=sys.stderr)
        evidence = Path(req.out_dir) / "evidence_summary.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        return usgs_e2e.RunUSGSWorkflowResult(
            success=True,
            run_id="fake",
            artifact_dir=str(req.out_dir),
            evidence_summary_path=str(evidence),
            blocker_class=None,
            values={"effective_claim_tier": "diagnostic"},
        )

    monkeypatch.setattr(usgs_e2e, "run_usgs_workflow", fake_run)

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "workflow",
            "run",
            "--usgs-id",
            "01654000",
            "--out-dir",
            str(tmp_path / "run_json"),
            "--json",
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert "NOISY INTERNAL PROGRESS" not in res.stdout
    assert "NOISY INTERNAL STDERR" not in res.stdout
    assert "NOISY INTERNAL STDERR" not in getattr(res, "stderr", "")
    payload = json.loads(res.stdout)
    assert payload["success"] is True
    assert payload["run_id"] == "fake"


def test_workflow_run_json_stream_sinks_survive_late_library_writes(monkeypatch, tmp_path: Path):
    import os
    import sys

    from swatplus_builder.workflows import usgs_e2e

    retained_streams = {}

    def fake_run(req):
        retained_streams["stdout"] = sys.stdout
        retained_streams["stderr"] = sys.stderr
        evidence = Path(req.out_dir) / "evidence_summary.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{"ok": true}\n', encoding="utf-8")
        return usgs_e2e.RunUSGSWorkflowResult(
            success=True,
            run_id="fake",
            artifact_dir=str(req.out_dir),
            evidence_summary_path=str(evidence),
            blocker_class=None,
            values={"effective_claim_tier": "diagnostic"},
        )

    monkeypatch.setattr(usgs_e2e, "run_usgs_workflow", fake_run)

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "workflow",
            "run",
            "--usgs-id",
            "01654000",
            "--out-dir",
            str(tmp_path / "run_json_late"),
            "--json",
        ],
    )

    assert res.exit_code == 0, res.stdout
    for stream in retained_streams.values():
        stream.write("late library shutdown write")
        stream.writelines(["late ", "library ", "shutdown ", "writelines"])
        stream.buffer.write(b"late binary shutdown write")
        stream.buffer.writelines([b"late ", b"binary ", b"writelines"])
        os.write(stream.fileno(), b"late fd shutdown write")
        os.write(stream.buffer.fileno(), b"late buffer fd shutdown write")
        stream.flush()
        stream.buffer.flush()
        assert stream.writable() is True
        assert stream.readable() is False
        assert stream.seekable() is False
        assert stream.closed is False
        assert stream.buffer.writable() is True
        assert stream.buffer.readable() is False
        assert stream.buffer.seekable() is False
        assert stream.buffer.closed is False


def test_json_shutdown_stream_redirects_process_owned_streams(monkeypatch, tmp_path: Path):
    import sys

    paths = {
        "stdout": str(tmp_path / "json_shutdown_stdout.log"),
        "stderr": str(tmp_path / "json_shutdown_stderr.log"),
    }
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        monkeypatch.setattr(sys, "stdout", sys.__stdout__)
        monkeypatch.setattr(sys, "stderr", sys.__stderr__)
        cli_module._redirect_json_shutdown_streams(paths)
        sys.stdout.write("late stdout\n")
        sys.stderr.write("late stderr\n")
        sys.stdout.buffer.write(b"late binary stdout\n")
        sys.stderr.buffer.write(b"late binary stderr\n")
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        monkeypatch.setattr(sys, "stdout", old_stdout)
        monkeypatch.setattr(sys, "stderr", old_stderr)

    assert "late stdout" in Path(paths["stdout"]).read_text(encoding="utf-8")
    assert "late binary stdout" in Path(paths["stdout"]).read_text(encoding="utf-8")
    assert "late stderr" in Path(paths["stderr"]).read_text(encoding="utf-8")
    assert "late binary stderr" in Path(paths["stderr"]).read_text(encoding="utf-8")


def test_json_shutdown_stream_redirect_can_redirect_process_file_descriptors(
    monkeypatch, tmp_path: Path
):
    import sys

    paths = {
        "stdout": str(tmp_path / "json_shutdown_stdout.log"),
        "stderr": str(tmp_path / "json_shutdown_stderr.log"),
    }
    dup2_calls: list[tuple[int, int]] = []
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_dunder_stdout = sys.__stdout__
    old_dunder_stderr = sys.__stderr__

    def fake_dup2(src: int, dst: int) -> None:
        dup2_calls.append((src, dst))

    try:
        monkeypatch.setattr(cli_module.os, "dup2", fake_dup2)
        monkeypatch.setattr(sys, "stdout", sys.__stdout__)
        monkeypatch.setattr(sys, "stderr", sys.__stderr__)
        cli_module._redirect_json_shutdown_streams(paths, redirect_fds=True)
        assert sys.stdout is sys.__stdout__
        assert sys.stderr is sys.__stderr__
    finally:
        monkeypatch.setattr(sys, "stdout", old_stdout)
        monkeypatch.setattr(sys, "stderr", old_stderr)
        monkeypatch.setattr(sys, "__stdout__", old_dunder_stdout)
        monkeypatch.setattr(sys, "__stderr__", old_dunder_stderr)

    assert [dst for _, dst in dup2_calls] == [1, 2]


def test_json_shutdown_stream_redirect_skips_in_process_capture(monkeypatch, tmp_path: Path):
    import io
    import sys

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_stdout)
    monkeypatch.setattr(sys, "stderr", captured_stderr)

    cli_module._redirect_json_shutdown_streams(
        {
            "stdout": str(tmp_path / "json_shutdown_stdout.log"),
            "stderr": str(tmp_path / "json_shutdown_stderr.log"),
        }
    )

    assert sys.stdout is captured_stdout
    assert sys.stderr is captured_stderr
