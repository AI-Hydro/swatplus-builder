from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.validation.runner import (
    BasinSpec,
    ExecutorResult,
    load_basin_specs,
    run_validation,
)


def test_load_basin_specs_accepts_list_and_object(tmp_path: Path) -> None:
    payload = [
        {"usgs_id": "01547700", "simulation_start": "2015-01-01", "simulation_end": "2015-12-31"}
    ]
    p_list = tmp_path / "list.json"
    p_obj = tmp_path / "obj.json"
    p_list.write_text(json.dumps(payload), encoding="utf-8")
    p_obj.write_text(json.dumps({"basins": payload}), encoding="utf-8")

    a = load_basin_specs(p_list)
    b = load_basin_specs(p_obj)
    assert len(a) == 1
    assert len(b) == 1
    assert a[0].usgs_id == b[0].usgs_id == "01547700"


def test_run_validation_uses_cache_on_second_run(tmp_path: Path) -> None:
    calls = {"n": 0}

    def _exec(spec: BasinSpec, run_dir: Path) -> ExecutorResult:
        calls["n"] += 1
        return ExecutorResult(
            status="success",
            metrics={"nse": 0.2, "kge": 0.1, "pbias": -2.0},
            metadata={"engine_version": "swatplus-61.0.6", "soil_mode": "high_fidelity"},
        )

    basins = [
        BasinSpec(usgs_id="01547700", simulation_start="2015-01-01", simulation_end="2015-12-31"),
        BasinSpec(usgs_id="01013500", simulation_start="2015-01-01", simulation_end="2015-12-31"),
    ]
    artifacts_root = tmp_path / "artifacts"
    runs_root = tmp_path / "runs"

    first, report_dir_1 = run_validation(
        basins=basins,
        artifacts_root=artifacts_root,
        runs_root=runs_root,
        executor=_exec,
        engine_version="swatplus-61.0.6",
        builder_git_sha="abc123",
    )
    assert calls["n"] == 2
    assert all(not r.cache_hit for r in first)
    assert all(r.passed is True for r in first)
    assert (report_dir_1 / "summary.csv").exists()
    assert (report_dir_1 / "summary.md").exists()
    assert (report_dir_1 / "benchmark_report.md").exists()
    assert (report_dir_1 / "benchmark_summary.json").exists()

    second, _report_dir_2 = run_validation(
        basins=basins,
        artifacts_root=artifacts_root,
        runs_root=runs_root,
        executor=_exec,
        engine_version="swatplus-61.0.6",
        builder_git_sha="abc123",
    )
    assert calls["n"] == 2, "executor should not run on cache hit"
    assert all(r.cache_hit for r in second)
    assert all(r.status == "cached" for r in second)
    assert all(r.passed is True for r in second)
