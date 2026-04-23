from __future__ import annotations

from pathlib import Path

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
