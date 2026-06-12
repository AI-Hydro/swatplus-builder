from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from swatplus_builder.artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)
from swatplus_builder.mcp import server as mcp_server
from swatplus_builder.mcp.server import (
    BuildProjectRequest,
    CalibrateRequest,
    CompareRunsRequest,
    DiagnoseFailureRequest,
    LockBenchmarkRequest,
    LockedCalibrateRequest,
    ProposeParametersRequest,
    QueryArtifactsRequest,
    ReadinessTableRequest,
    RunBasinRequest,
    RunWorkflowRequest,
    ValidateRequest,
    WorkflowStatusRequest,
    create_mcp_server,
)


def _tool_map() -> dict[str, object]:
    mcp = create_mcp_server()
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def test_mcp_server_registers_exactly_thirteen_tools() -> None:
    tools = _tool_map()
    assert set(tools) == {
        "run_workflow",
        "workflow_status",
        "build_project",
        "run_basin",
        "calibrate",
        "propose_parameters",
        "compare_runs",
        "query_artifacts",
        "diagnose_failure",
        "validate",
        "lock_benchmark",
        "locked_calibrate",
        "readiness_table",
    }


def test_build_run_calibrate_tools_execute_wrappers(monkeypatch, tmp_path: Path) -> None:
    tools = _tool_map()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text('{"usgs_id":"01547700","name":"marsh"}\n', encoding="utf-8")
    cfg_path = tmp_path / "run.json"
    cfg_path.write_text(
        '{"usgs_id":"01547700","outdir":"%s","start_date":"2015-01-01","end_date":"2015-12-31"}\n'
        % (tmp_path / "run_out"),
        encoding="utf-8",
    )

    class _FakeCalibrator:
        def run(self, request):
            assert request.basin_id == "usgs_01547700"
            return SimpleNamespace(
                calibration_hash="abc123",
                best_nse=0.42,
                outdir=tmp_path / "calibration_out",
            )

    def fake_run_pipeline(*, usgs_id, outdir, start_date, end_date, threads, engine_timeout_s):
        assert usgs_id == "01547700"
        assert start_date == "2015-01-01"
        assert end_date == "2015-12-31"
        _ = threads
        _ = engine_timeout_s
        return {"status": "SUCCESS", "usgs_id": usgs_id, "outdir": str(outdir)}

    monkeypatch.setattr(mcp_server, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(mcp_server, "Calibrator", _FakeCalibrator)

    build_res = tools["build_project"].fn(
        req=BuildProjectRequest(
            basin_spec_path=str(spec_path),
            workdir=str(tmp_path / "build_out"),
        )
    )
    run_res = tools["run_basin"].fn(req=RunBasinRequest(basin_config_path=str(cfg_path)))
    cal_res = tools["calibrate"].fn(
        req=CalibrateRequest(
            basin_id="usgs_01547700",
            start="2015-01-01",
            end="2015-12-31",
            txtinout_dir=str(tmp_path / "txt"),
            observed_csv=str(tmp_path / "obs.csv"),
            parameters=["CN2", "SURLAG"],
            objectives=["nse"],
        )
    )

    assert build_res.status == "success"
    assert run_res.status == "success"
    assert cal_res.status == "success"
    assert Path(build_res.manifest_path).exists()
    assert Path(run_res.run_summary_path).exists()
    assert cal_res.calibration_hash == "abc123"


def test_run_workflow_launches_detached_process_and_status_roundtrips(
    monkeypatch, tmp_path: Path
) -> None:
    import json as _json

    tools = _tool_map()

    captured: dict[str, object] = {}

    class _FakePopen:
        pid = 99999999  # certain to not be a live pid when status is polled

        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs

    monkeypatch.setattr(mcp_server.subprocess, "Popen", _FakePopen)

    out_dir = tmp_path / "wf"
    res = tools["run_workflow"].fn(
        req=RunWorkflowRequest(usgs_id="01547700", out_dir=str(out_dir))
    )
    assert res.status == "started"
    assert res.pid == 99999999
    assert "--usgs-id" in captured["argv"] and "01547700" in captured["argv"]
    assert captured["kwargs"]["start_new_session"] is True
    assert (out_dir / "workflow_launch.json").exists()
    assert "swat workflow run" in res.equivalent_cli

    # Dead pid + final JSON payload in the log → completed with evidence pointers.
    payload = {
        "success": True,
        "run_id": "usgs_01547700_x",
        "artifact_dir": str(out_dir / "artifacts"),
        "evidence_summary_path": str(out_dir / "artifacts" / "evidence_summary.json"),
        "blocker_class": None,
        "values": {},
    }
    Path(res.log_path).write_text(
        "engine noise line\n" + _json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    status = tools["workflow_status"].fn(req=WorkflowStatusRequest(out_dir=str(out_dir)))
    assert status.status == "completed"
    assert status.success is True
    assert status.evidence_summary_path == payload["evidence_summary_path"]

    # Dead pid + no JSON → failed with log tail.
    Path(res.log_path).write_text("Traceback (most recent call last):\nboom\n", encoding="utf-8")
    status2 = tools["workflow_status"].fn(req=WorkflowStatusRequest(out_dir=str(out_dir)))
    assert status2.status == "failed"
    assert "boom" in (status2.log_tail or "")

    # Unknown directory → unknown.
    status3 = tools["workflow_status"].fn(
        req=WorkflowStatusRequest(out_dir=str(tmp_path / "nope"))
    )
    assert status3.status == "unknown"


def test_propose_parameters_grid_hits_bounds_for_multi_count() -> None:
    tools = _tool_map()
    response = tools["propose_parameters"].fn(
        req=ProposeParametersRequest(strategy="grid", count=3, parameters=["CN2"])
    )

    assert len(response.proposals) == 3
    assert response.proposals[0]["CN2"] == 35.0
    assert response.proposals[-1]["CN2"] == 98.0


def test_compare_runs_reads_metrics_and_marks_missing(tmp_path: Path) -> None:
    tools = _tool_map()
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    run_a.mkdir()
    run_b.mkdir()
    (run_a / "metrics.json").write_text('{"nse":0.25,"kge":0.10,"pbias":-5.0}\n', encoding="utf-8")

    response = tools["compare_runs"].fn(
        req=CompareRunsRequest(run_artifacts=[str(run_a), str(run_b)])
    )

    assert len(response.summaries) == 2
    assert response.summaries[0]["nse"] == 0.25
    assert response.summaries[1]["nse"] is None


def test_query_artifacts_filters_by_basin_and_nse(tmp_path: Path) -> None:
    tools = _tool_map()
    store = LocalArtifactStore(tmp_path / "artifacts")

    cfg = RunConfig.model_validate(
        {
            "basin_id": "usgs_01547700",
            "bbox": [-77.0, 39.0, -76.5, 39.5],
            "simulation_start": "2010-01-01",
            "simulation_end": "2010-12-31",
            "parameters": {},
            "options": {},
        }
    )
    content_hash = compute_content_hash(
        cfg, engine_version="swatplus-61.0.6", builder_git_sha="git-test-sha"
    )
    store.write(
        ArtifactRecord(
            content_hash=content_hash,
            config=cfg,
            metadata=ArtifactMetadata(
                run_id=content_hash,
                timestamp_utc="2026-04-24T00:00:00Z",
                soil_mode="high_fidelity",
            ),
            metrics=ArtifactMetrics(nse=0.4),
        )
    )

    response = tools["query_artifacts"].fn(
        req=QueryArtifactsRequest(
            artifacts_root=str(tmp_path / "artifacts"),
            basin_id="usgs_01547700",
            nse_min=0.3,
        )
    )

    assert response.count == 1
    assert response.items[0]["basin_id"] == "usgs_01547700"


def test_diagnose_failure_accepts_alignment_csv(tmp_path: Path) -> None:
    tools = _tool_map()
    alignment = tmp_path / "alignment.csv"
    alignment.write_text(
        "date,obs,sim\n"
        "2015-01-01,1.0,0.7\n"
        "2015-01-02,0.8,0.6\n"
        "2015-01-03,0.2,0.3\n"
        "2015-01-04,0.1,0.2\n",
        encoding="utf-8",
    )

    response = tools["diagnose_failure"].fn(req=DiagnoseFailureRequest(run_artifact=str(alignment)))

    assert response.count >= 0
    assert isinstance(response.diagnoses, list)


def test_validate_tool_uses_runner_and_returns_summary(monkeypatch, tmp_path: Path) -> None:
    tools = _tool_map()

    def fake_load_basin_specs(path: str):
        assert path == "/tmp/curated.json"
        return [SimpleNamespace(resolved_basin_id="usgs_01547700")]

    def fake_run_validation(*, basins, artifacts_root, runs_root, engine_version):
        assert len(basins) == 1
        assert artifacts_root == str(tmp_path / "artifacts")
        assert runs_root == str(tmp_path / "runs")
        assert engine_version == "swatplus-61.0.6"
        return [SimpleNamespace(status="success", cache_hit=False)], tmp_path / "report"

    monkeypatch.setattr(mcp_server, "load_basin_specs", fake_load_basin_specs)
    monkeypatch.setattr(mcp_server, "run_validation", fake_run_validation)

    response = tools["validate"].fn(
        req=ValidateRequest(
            basins_file="/tmp/curated.json",
            artifacts_root=str(tmp_path / "artifacts"),
            runs_root=str(tmp_path / "runs"),
            engine_version="swatplus-61.0.6",
        )
    )

    assert response.report_dir == str(tmp_path / "report")
    assert response.basin_count == 1
    assert response.success_count == 1
    assert response.cache_hits == 0


def test_lock_benchmark_tool_monkeypatched(monkeypatch, tmp_path: Path) -> None:
    """lock_benchmark MCP tool must return a LockBenchmarkResponse via monkeypatched function."""
    import swatplus_builder.mcp.server as mcp_server_mod

    def fake_lock_benchmark(txtinout_dir, obs_series, out_dir, *, basin_id, outlet_gis_id, sim_source_file):
        from swatplus_builder.calibration.locked_benchmark import BenchmarkLock

        return BenchmarkLock(
            basin_id=basin_id,
            locked_at_utc="2026-04-24T00:00:00+00:00",
            alignment_sha256="deadbeef",
            metrics_sha256="cafebabe",
            outlet_gis_id=outlet_gis_id,
            sim_source_file=sim_source_file,
            baseline_nse=0.12,
            baseline_kge=-0.05,
            benchmark_dir=str(tmp_path / "benchmark"),
        )

    monkeypatch.setattr(mcp_server_mod, "lock_benchmark", fake_lock_benchmark)

    obs_csv = tmp_path / "obs.csv"
    obs_csv.write_text("date,discharge\n2010-01-01,1.5\n2010-01-02,1.2\n", encoding="utf-8")

    tools = _tool_map()
    # rebuild with monkeypatch active
    from swatplus_builder.mcp.server import create_mcp_server as _cms

    tools = {t.name: t for t in _cms()._tool_manager.list_tools()}

    resp = tools["lock_benchmark"].fn(
        req=LockBenchmarkRequest(
            txtinout_dir=str(tmp_path),
            observed_csv=str(obs_csv),
            out_dir=str(tmp_path / "out"),
            basin_id="usgs_test01",
            outlet_gis_id=1,
            sim_source_file="basin_sd_cha_day.txt",
        )
    )
    assert resp.status == "success"
    assert resp.basin_id == "usgs_test01"
    assert resp.baseline_nse == 0.12


def test_readiness_table_tool_empty_dir(tmp_path: Path) -> None:
    """readiness_table MCP tool must return empty list for directory with no artifacts."""
    tools = _tool_map()
    resp = tools["readiness_table"].fn(
        req=ReadinessTableRequest(locks_root=str(tmp_path / "nonexistent"))
    )
    assert resp.row_count == 0
    assert resp.rows == []


def test_readiness_table_tool_finds_verification_artifacts(tmp_path: Path) -> None:
    """readiness_table must discover verification_summary.json and return structured rows."""
    import json

    basin_dir = tmp_path / "usgs_01547700"
    basin_dir.mkdir()
    summary = {
        "basin_id": "usgs_01547700",
        "benchmark_nse": 0.125,
        "benchmark_kge": 0.036,
        "verified_nse": 0.210,
        "verified_kge": 0.116,
        "delta_nse": 0.085,
        "delta_kge": 0.080,
        "improved": True,
        "verification_dir": str(basin_dir),
        "verification_summary_path": str(basin_dir / "verification_summary.json"),
    }
    (basin_dir / "verification_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )

    tools = _tool_map()
    resp = tools["readiness_table"].fn(
        req=ReadinessTableRequest(locks_root=str(tmp_path))
    )
    assert resp.row_count == 1
    assert resp.rows[0]["basin_id"] == "usgs_01547700"
    assert resp.rows[0]["verification_status"] == "verified_improved"
