from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from swatplus_builder.calibration.calibrator import (
    BackendRequest,
    BackendResult,
    Calibrator,
    CalibratorRequest,
    EvaluationRecord,
    _apply_metric_parity,
)


class FakeBackend:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: BackendRequest) -> BackendResult:
        self.calls += 1
        _ = request
        return BackendResult(
            evaluations=[
                EvaluationRecord(
                    generation=0,
                    individual=0,
                    parameters={"CN2": 70.0, "ALPHA_BF": 0.1, "SURLAG": 3.0},
                    metrics={"nse": 0.21, "kge": 0.1, "pbias": -3.0},
                ),
                EvaluationRecord(
                    generation=0,
                    individual=1,
                    parameters={"CN2": 68.0, "ALPHA_BF": 0.2, "SURLAG": 4.0},
                    metrics={"nse": 0.34, "kge": 0.2, "pbias": -1.0},
                ),
            ]
        )


def _request(tmp_path: Path) -> CalibratorRequest:
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    obs = tmp_path / "alignment.csv"
    obs.write_text("date,obs,sim\n2015-01-01,1.0,0.8\n", encoding="utf-8")
    return CalibratorRequest(
        basin_id="usgs_01547700",
        simulation_start=date(2015, 1, 1),
        simulation_end=date(2015, 12, 31),
        txtinout_dir=txt,
        observed_csv=obs,
        parameters=["CN2", "ALPHA_BF", "SURLAG"],
        objectives=["nse", "kge", "pbias"],
        algorithm="nsga2",
        n_gen=2,
        pop_size=4,
        seed=123,
        artifacts_root=tmp_path / "artifacts",
        engine_version="test-engine",
        builder_git_sha="abc123",
        warm_start=True,
    )


def test_calibrator_writes_calibration_and_eval_artifacts(tmp_path: Path) -> None:
    backend = FakeBackend()
    req = _request(tmp_path)
    out = Calibrator(backend=backend).run(req)
    assert out.cache_hit is False
    assert out.n_evaluations == 2
    assert backend.calls == 1
    assert out.history_csv.exists()
    assert out.best_solution_json.exists()
    assert out.summary_md.exists()
    assert out.pareto_csv is not None and out.pareto_csv.exists()

    runs_dir = req.artifacts_root / "runs"
    assert runs_dir.exists()
    eval_runs = [p for p in runs_dir.iterdir() if p.is_dir() and p.name != "calibrations"]
    assert len(eval_runs) == 2


def test_calibrator_warm_start_skips_backend(tmp_path: Path) -> None:
    backend = FakeBackend()
    req = _request(tmp_path)
    c = Calibrator(backend=backend)
    first = c.run(req)
    second = c.run(req)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert backend.calls == 1


def test_metric_parity_overwrites_bridge_metrics_and_writes_required_log(
    tmp_path: Path, monkeypatch
) -> None:
    calsim = tmp_path / "pyswatplus_run"
    calsim.mkdir(parents=True, exist_ok=True)
    for i in (1, 2):
        sim_dir = calsim / f"sim_{i}"
        sim_dir.mkdir(parents=True, exist_ok=True)
        (sim_dir / "basin_sd_cha_day.txt").write_text("dummy\n", encoding="utf-8")

    obs_csv = tmp_path / "observed_for_pyswatplus.csv"
    obs_csv.write_text(
        "date,discharge\n2015-01-01,1.0\n2015-01-02,2.0\n",
        encoding="utf-8",
    )

    def _fake_evaluate_run(*args, **kwargs):  # noqa: ANN002, ANN003
        idx = pd.to_datetime(["2015-01-01", "2015-01-02"])
        align = pd.DataFrame({"obs": [1.0, 2.0], "sim": [0.9, 2.1]}, index=idx)
        metrics = {"nse": 0.55, "kge": 0.44}
        diagnostics = {"sim_source_file": "basin_sd_cha_day.txt"}
        return align, metrics, diagnostics

    monkeypatch.setattr("swatplus_builder.output.eval.evaluate_run", _fake_evaluate_run)

    ev = [
        EvaluationRecord(
            generation=0,
            individual=0,
            parameters={"CN2": 70.0},
            metrics={"nse": -3671945939.0},
        ),
        EvaluationRecord(
            generation=0,
            individual=1,
            parameters={"CN2": 65.0},
            metrics={"nse": -3671945938.0},
        ),
    ]

    parity_csv = _apply_metric_parity(
        evaluations=ev,
        calsim_dir=calsim,
        sim_output_file="basin_sd_cha_day.txt",
        normalized_obs_csv=obs_csv,
        obs_column="discharge",
        outlet_gis_id=1,
        pop_size=2,
    )

    assert parity_csv.exists()
    assert ev[0].metrics["nse"] == 0.55
    assert ev[0].metrics["kge"] == 0.44
    log = pd.read_csv(parity_csv)
    required = {
        "aligned_days",
        "obs_mean",
        "obs_std",
        "obs_min",
        "obs_max",
        "sim_mean",
        "sim_std",
        "sim_min",
        "sim_max",
        "first_date",
        "last_date",
        "outlet_gis_id",
        "bridge_reported_nse",
        "bridge_reported_kge",
        "pyswatplus_raw_objective_nse",
    }
    assert required.issubset(set(log.columns))
