from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from swatplus_builder.cli import app


def test_calibrate_cli_runs_and_writes_artifacts(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--algo",
            "dds",
            "--n-iter",
            "3",
            "--objectives",
            "nse,pbias",
            "--parameters",
            "CN2,ALPHA_BF",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
            "--engine-version",
            "swatplus-61.0.6",
            "--seed",
            "123",
        ],
    )
    assert res.exit_code == 0
    assert "swat calibrate" in res.stdout
    assert "samples=3" in res.stdout
    assert (tmp_path / "calib_artifacts" / "runs").exists()
    assert (tmp_path / "calib_artifacts" / "calibration_reports" / "history.csv").exists()


def test_calibrate_cli_rejects_invalid_objective(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--objectives",
            "nse,unknown_metric",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
        ],
    )
    assert res.exit_code == 2
    assert "invalid objectives" in res.stdout


def test_calibrate_cli_real_engine_requires_base_txtinout(tmp_path: Path) -> None:
    runner = CliRunner()
    alignment = tmp_path / "alignment.csv"
    alignment.write_text(
        "date,obs,sim\n"
        "2015-01-01,1.0,0.8\n",
        encoding="utf-8",
    )
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--real-engine",
            "--alignment-csv",
            str(alignment),
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
        ],
    )
    assert res.exit_code == 2
    assert "--base-txtinout is required" in res.stdout


def test_calibrate_cli_proxy_ignores_min_improvement_gate(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--n-iter",
            "2",
            "--parameters",
            "CN2",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
            "--min-improvement-nse",
            "0.1",
        ],
    )
    assert res.exit_code == 0


def test_calibrate_cli_rejects_unknown_engine(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--calibration-engine",
            "nope",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
        ],
    )
    assert res.exit_code == 2
    assert "--calibration-engine must be one of" in res.stdout


def test_calibrate_cli_pyswatplus_bridge_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from swatplus_builder.calibration import calibrator as calibrator_mod

    captured = {"n": 0}

    def _fake_run(self, req):  # noqa: ANN001
        captured["n"] += 1
        outdir = req.artifacts_root / "runs" / "calibrations" / "abc"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "history.csv").write_text("generation,individual\n0,0\n", encoding="utf-8")
        (outdir / "summary.md").write_text("# x\n", encoding="utf-8")
        (outdir / "best_solution.json").write_text("{}", encoding="utf-8")
        return calibrator_mod.CalibrationSummary(
            calibration_hash="abc",
            cache_hit=False,
            n_evaluations=1,
            best_nse=0.2,
            outdir=outdir,
            history_csv=outdir / "history.csv",
            summary_md=outdir / "summary.md",
            best_solution_json=outdir / "best_solution.json",
            pareto_csv=None,
        )

    monkeypatch.setattr(calibrator_mod.Calibrator, "run", _fake_run)

    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    alignment = tmp_path / "alignment.csv"
    alignment.write_text("date,obs,sim\n2015-01-01,1.0,0.8\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--calibration-engine",
            "pyswatplus",
            "--base-txtinout",
            str(txt),
            "--alignment-csv",
            str(alignment),
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
            "--n-gen",
            "2",
            "--pop-size",
            "4",
            "--algo",
            "nsga2",
            "--objectives",
            "nse",
        ],
    )
    assert res.exit_code == 0
    assert "engine=pyswatplus" in res.stdout
    assert captured["n"] == 1


def test_calibrate_cli_pyswatplus_rejects_multi_objective(tmp_path: Path) -> None:
    runner = CliRunner()
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    alignment = tmp_path / "alignment.csv"
    alignment.write_text("date,obs,sim\n2015-01-01,1.0,0.8\n", encoding="utf-8")
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--calibration-engine",
            "pyswatplus",
            "--base-txtinout",
            str(txt),
            "--alignment-csv",
            str(alignment),
            "--algo",
            "nsga2",
            "--objectives",
            "nse,kge",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
        ],
    )
    assert res.exit_code == 2
    assert "supports one objective per run" in res.stdout


def test_calibrate_cli_rejects_invalid_preset(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--preset",
            "badpreset",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
        ],
    )
    assert res.exit_code == 2
    assert "--preset must be one of" in res.stdout


def test_calibrate_cli_spotpy_quick_preset_overrides_defaults(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--preset",
            "quick",
            "--parameters",
            "CN2",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
        ],
    )
    assert res.exit_code == 0
    assert "preset quick applied" in res.stdout
    assert "samples=10" in res.stdout


def test_calibrate_cli_pyswatplus_quick_preset_overrides_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swatplus_builder.calibration import calibrator as calibrator_mod

    captured: dict[str, object] = {}

    def _fake_run(self, req):  # noqa: ANN001
        captured["algorithm"] = req.algorithm
        captured["n_gen"] = req.n_gen
        captured["pop_size"] = req.pop_size
        captured["objectives"] = list(req.objectives)
        outdir = req.artifacts_root / "runs" / "calibrations" / "abc"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "history.csv").write_text("generation,individual\n0,0\n", encoding="utf-8")
        (outdir / "summary.md").write_text("# x\n", encoding="utf-8")
        (outdir / "best_solution.json").write_text("{}", encoding="utf-8")
        return calibrator_mod.CalibrationSummary(
            calibration_hash="abc",
            cache_hit=False,
            n_evaluations=1,
            best_nse=0.2,
            outdir=outdir,
            history_csv=outdir / "history.csv",
            summary_md=outdir / "summary.md",
            best_solution_json=outdir / "best_solution.json",
            pareto_csv=None,
        )

    monkeypatch.setattr(calibrator_mod.Calibrator, "run", _fake_run)

    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    alignment = tmp_path / "alignment.csv"
    alignment.write_text("date,obs,sim\n2015-01-01,1.0,0.8\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "calibrate",
            "--basin",
            "usgs_01547700",
            "--start",
            "2015-01-01",
            "--end",
            "2015-12-31",
            "--calibration-engine",
            "pyswatplus",
            "--base-txtinout",
            str(txt),
            "--alignment-csv",
            str(alignment),
            "--preset",
            "quick",
            "--artifacts-root",
            str(tmp_path / "calib_artifacts"),
        ],
    )
    assert res.exit_code == 0
    assert "preset quick applied" in res.stdout
    assert captured["algorithm"] == "de"
    assert captured["n_gen"] == 10
    assert captured["pop_size"] == 16
    assert captured["objectives"] == ["nse"]
