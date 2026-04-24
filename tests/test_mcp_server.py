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
    ProposeParametersRequest,
    QueryArtifactsRequest,
    RunBasinRequest,
    ValidateRequest,
    create_mcp_server,
)


def _tool_map() -> dict[str, object]:
    mcp = create_mcp_server()
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def test_mcp_server_registers_exactly_eight_tools() -> None:
    tools = _tool_map()
    assert set(tools) == {
        "build_project",
        "run_basin",
        "calibrate",
        "propose_parameters",
        "compare_runs",
        "query_artifacts",
        "diagnose_failure",
        "validate",
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
