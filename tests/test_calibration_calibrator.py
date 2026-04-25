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
from swatplus_builder.errors import SwatBuilderPipelineError


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
    staged = calsim.parent / "_txtinout_staged"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "hydrology.hyd").write_text("cn2 70\n", encoding="utf-8")
    for i in (1, 2):
        sim_dir = calsim / f"sim_{i}"
        sim_dir.mkdir(parents=True, exist_ok=True)
        (sim_dir / "hydrology.hyd").write_text(f"cn2 {70+i}\n", encoding="utf-8")
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
        staged_txtinout=staged,
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
        "input_changed_files_count",
        "sim_output_sha256",
        "sim_output_mtime_utc",
        "sim_output_changed_vs_previous_eval",
    }
    assert required.issubset(set(log.columns))
    assert int(log["input_changed_files_count"].iloc[0]) >= 1


def test_metric_parity_fails_if_calibration_does_not_modify_input_files(
    tmp_path: Path, monkeypatch
) -> None:
    calsim = tmp_path / "pyswatplus_run"
    calsim.mkdir(parents=True, exist_ok=True)
    staged = calsim.parent / "_txtinout_staged"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "hydrology.hyd").write_text("cn2 70\n", encoding="utf-8")

    sim_dir = calsim / "sim_1"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "hydrology.hyd").write_text("cn2 70\n", encoding="utf-8")
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
            metrics={"nse": -3.0},
        )
    ]

    try:
        _apply_metric_parity(
            evaluations=ev,
            calsim_dir=calsim,
            sim_output_file="basin_sd_cha_day.txt",
            normalized_obs_csv=obs_csv,
            obs_column="discharge",
            outlet_gis_id=1,
            pop_size=1,
            staged_txtinout=staged,
        )
    except SwatBuilderPipelineError as exc:
        assert "did not modify any SWAT+ input file" in str(exc)
    else:
        raise AssertionError("Expected SwatBuilderPipelineError when no input files changed.")


def test_metric_parity_records_distinct_metrics_when_outputs_change(
    tmp_path: Path, monkeypatch
) -> None:
    calsim = tmp_path / "pyswatplus_run"
    calsim.mkdir(parents=True, exist_ok=True)
    staged = calsim.parent / "_txtinout_staged"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "hydrology.hyd").write_text("cn2 70\n", encoding="utf-8")

    for i, val in ((1, 71), (2, 90)):
        sim_dir = calsim / f"sim_{i}"
        sim_dir.mkdir(parents=True, exist_ok=True)
        (sim_dir / "hydrology.hyd").write_text(f"cn2 {val}\n", encoding="utf-8")
        (sim_dir / "basin_sd_cha_day.txt").write_text(f"sim{i}\n", encoding="utf-8")

    obs_csv = tmp_path / "observed_for_pyswatplus.csv"
    obs_csv.write_text(
        "date,discharge\n2015-01-01,1.0\n2015-01-02,2.0\n",
        encoding="utf-8",
    )

    def _fake_evaluate_run(sim_file, *_args, **_kwargs):  # noqa: ANN001
        idx = pd.to_datetime(["2015-01-01", "2015-01-02"])
        content = Path(sim_file).read_text(encoding="utf-8")
        if "sim1" in content:
            align = pd.DataFrame({"obs": [1.0, 2.0], "sim": [0.9, 2.1]}, index=idx)
            return align, {"nse": 0.45, "kge": 0.35}, {"sim_source_file": "basin_sd_cha_day.txt"}
        align = pd.DataFrame({"obs": [1.0, 2.0], "sim": [1.2, 2.3]}, index=idx)
        return align, {"nse": 0.12, "kge": 0.11}, {"sim_source_file": "basin_sd_cha_day.txt"}

    monkeypatch.setattr("swatplus_builder.output.eval.evaluate_run", _fake_evaluate_run)
    ev = [
        EvaluationRecord(
            generation=0,
            individual=0,
            parameters={"CN2": 70.0},
            metrics={"nse": -1.0},
        ),
        EvaluationRecord(
            generation=0,
            individual=1,
            parameters={"CN2": 90.0},
            metrics={"nse": -2.0},
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
        staged_txtinout=staged,
    )
    log = pd.read_csv(parity_csv)
    assert ev[0].metrics["nse"] != ev[1].metrics["nse"]
    assert log["bridge_reported_nse"].nunique() == 2


def test_metric_parity_uses_authoritative_rerun_when_outputs_are_flat(
    tmp_path: Path, monkeypatch
) -> None:
    calsim = tmp_path / "pyswatplus_run"
    calsim.mkdir(parents=True, exist_ok=True)
    staged = calsim.parent / "_txtinout_staged"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / "hydrology.hyd").write_text("cn2 70\n", encoding="utf-8")
    base_txt = tmp_path / "base_txtinout"
    base_txt.mkdir(parents=True, exist_ok=True)
    (base_txt / "hydrology.hyd").write_text("cn2 70\n", encoding="utf-8")

    for i, val in ((1, 71), (2, 90)):
        sim_dir = calsim / f"sim_{i}"
        sim_dir.mkdir(parents=True, exist_ok=True)
        (sim_dir / "hydrology.hyd").write_text(f"cn2 {val}\n", encoding="utf-8")
        (sim_dir / "calibration.cal").write_text(f"cn2 absval {val}\n", encoding="utf-8")
        (sim_dir / "basin_sd_cha_day.txt").write_text("same-output\n", encoding="utf-8")

    obs_csv = tmp_path / "observed_for_pyswatplus.csv"
    obs_csv.write_text(
        "date,discharge\n2015-01-01,1.0\n2015-01-02,2.0\n",
        encoding="utf-8",
    )

    def _fake_evaluate_run(*args, **kwargs):  # noqa: ANN002, ANN003
        idx = pd.to_datetime(["2015-01-01", "2015-01-02"])
        align = pd.DataFrame({"obs": [1.0, 2.0], "sim": [0.9, 2.1]}, index=idx)
        metrics = {"nse": 0.10, "kge": 0.10}
        diagnostics = {"sim_source_file": "basin_sd_cha_day.txt"}
        return align, metrics, diagnostics

    def _fake_rerun(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs
        return [
            {
                "generation": 0,
                "individual": 0,
                "sim_index": 1,
                "sim_output_file": "basin_sd_cha_day.txt",
                "outlet_gis_id": 1,
                "unit_convention": "flow_m3s",
                "metric_source": "evaluate_run_real_objective_rerun",
                "aligned_days": 2,
                "obs_mean": 1.5,
                "obs_std": 0.5,
                "obs_min": 1.0,
                "obs_max": 2.0,
                "sim_mean": 1.5,
                "sim_std": 0.4,
                "sim_min": 1.1,
                "sim_max": 1.9,
                "first_date": "2015-01-01",
                "last_date": "2015-01-02",
                "bridge_reported_nse": 0.55,
                "bridge_reported_kge": 0.44,
                "pyswatplus_raw_objective_nse": 0.1,
                "input_changed_files_count": 2,
                "input_changed_files_sample": "calibration.cal;file.cio",
                "sim_output_sha256": "h1",
                "sim_output_mtime_utc": "2026-04-24T00:00:00+00:00",
                "sim_output_changed_vs_previous_eval": True,
            },
            {
                "generation": 0,
                "individual": 1,
                "sim_index": 2,
                "sim_output_file": "basin_sd_cha_day.txt",
                "outlet_gis_id": 1,
                "unit_convention": "flow_m3s",
                "metric_source": "evaluate_run_real_objective_rerun",
                "aligned_days": 2,
                "obs_mean": 1.5,
                "obs_std": 0.5,
                "obs_min": 1.0,
                "obs_max": 2.0,
                "sim_mean": 1.7,
                "sim_std": 0.6,
                "sim_min": 1.0,
                "sim_max": 2.2,
                "first_date": "2015-01-01",
                "last_date": "2015-01-02",
                "bridge_reported_nse": 0.15,
                "bridge_reported_kge": 0.10,
                "pyswatplus_raw_objective_nse": 0.1,
                "input_changed_files_count": 2,
                "input_changed_files_sample": "calibration.cal;file.cio",
                "sim_output_sha256": "h2",
                "sim_output_mtime_utc": "2026-04-24T00:00:01+00:00",
                "sim_output_changed_vs_previous_eval": True,
            },
        ]

    monkeypatch.setattr("swatplus_builder.output.eval.evaluate_run", _fake_evaluate_run)
    monkeypatch.setattr(
        "swatplus_builder.calibration.calibrator._rerun_metric_parity_with_direct_objective",
        _fake_rerun,
    )
    ev = [
        EvaluationRecord(
            generation=0,
            individual=0,
            parameters={"CN2": 71.0},
            metrics={"nse": -1.0},
        ),
        EvaluationRecord(
            generation=0,
            individual=1,
            parameters={"CN2": 90.0},
            metrics={"nse": -2.0},
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
        staged_txtinout=staged,
        base_txtinout=base_txt,
    )
    log = pd.read_csv(parity_csv)
    assert log["metric_source"].iloc[0] == "evaluate_run_real_objective_rerun"
