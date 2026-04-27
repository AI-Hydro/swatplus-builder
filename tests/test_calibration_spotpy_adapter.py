from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from swatplus_builder.calibration import CalibrationRequest, run_calibration


def test_run_calibration_writes_artifact_per_iteration(tmp_path: Path) -> None:
    calls = {"n": 0}

    def objective(params: dict[str, float]) -> dict[str, float]:
        calls["n"] += 1
        nse = 1.0 - abs(params["CN2"] - 75.0) / 100.0
        return {"nse": nse, "kge": nse - 0.1, "pbias": 0.0}

    req = CalibrationRequest(
        basin_id="usgs_01547700",
        simulation_start=date(2015, 1, 1),
        simulation_end=date(2015, 12, 31),
        parameters=["CN2", "ALPHA_BF"],
        n_iter=3,
        seed=123,
        engine_version="swatplus-61.0.6",
        warm_start=True,
    )

    results = run_calibration(req, artifacts_root=tmp_path, objective_fn=objective, builder_git_sha="abc123")
    assert len(results) == 3
    assert calls["n"] == 3
    assert all(not r.cache_hit for r in results)
    runs_dir = tmp_path / "runs"
    assert runs_dir.exists()
    assert len([p for p in runs_dir.iterdir() if p.is_dir()]) == 3


def test_run_calibration_warm_start_skips_existing_samples(tmp_path: Path) -> None:
    calls = {"n": 0}

    def objective(_params: dict[str, float]) -> dict[str, float]:
        calls["n"] += 1
        return {"nse": 0.2, "kge": 0.1, "pbias": -1.0}

    req = CalibrationRequest(
        basin_id="usgs_01547700",
        simulation_start=date(2015, 1, 1),
        simulation_end=date(2015, 12, 31),
        parameters=["CN2"],
        n_iter=2,
        seed=999,
        engine_version="swatplus-61.0.6",
        warm_start=True,
    )

    first = run_calibration(req, artifacts_root=tmp_path, objective_fn=objective, builder_git_sha="abc123")
    assert calls["n"] == 2
    assert all(not r.cache_hit for r in first)

    second = run_calibration(req, artifacts_root=tmp_path, objective_fn=objective, builder_git_sha="abc123")
    assert calls["n"] == 2, "warm_start should avoid recomputation"
    assert all(r.cache_hit for r in second)


def test_run_calibration_cache_partitioned_by_objective_mode(tmp_path: Path) -> None:
    calls = {"n": 0}

    def objective(_params: dict[str, float]) -> dict[str, float]:
        calls["n"] += 1
        return {"nse": 0.1}

    base = CalibrationRequest(
        basin_id="usgs_01547700",
        simulation_start=date(2015, 1, 1),
        simulation_end=date(2015, 12, 31),
        parameters=["CN2"],
        n_iter=1,
        seed=1234,
        engine_version="swatplus-61.0.6",
        warm_start=True,
    )
    req_proxy = base
    req_real = replace(base, objective_mode="real_engine")

    run_calibration(req_proxy, artifacts_root=tmp_path, objective_fn=objective, builder_git_sha="abc123")
    run_calibration(req_real, artifacts_root=tmp_path, objective_fn=objective, builder_git_sha="abc123")
    assert calls["n"] == 2, "proxy and real-engine objective modes must not share cache entries"
