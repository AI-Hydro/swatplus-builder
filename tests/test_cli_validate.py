from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from swatplus_builder.cli import app


def test_validate_cli_runs_with_fixture_basins(tmp_path: Path) -> None:
    basins = [
        {
            "usgs_id": "01547700",
            "simulation_start": "2015-01-01",
            "simulation_end": "2015-12-31",
        }
    ]
    basins_path = tmp_path / "basins.json"
    basins_path.write_text(json.dumps(basins), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--basins",
            str(basins_path),
            "--artifacts-root",
            str(tmp_path / "artifacts"),
            "--runs-root",
            str(tmp_path / "runs"),
            "--engine-version",
            "test-engine",
        ],
    )
    assert result.exit_code == 0
    assert "swat validate" in result.stdout
    assert "complete" in result.stdout
    assert (tmp_path / "artifacts" / "validation_reports" / "summary.csv").exists()


def test_validate_cli_errors_on_missing_basins(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--basins", str(tmp_path / "missing.json")])
    assert result.exit_code == 2
    assert "basins file not found" in result.stdout

