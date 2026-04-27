from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swatplus_builder.calibration.pyswatplus_runtime import ensure_pyswatplus_runtime
from swatplus_builder.cli import app


@pytest.mark.slow
@pytest.mark.swat_binary
def test_pyswatplus_cli_integration_smoke(tmp_path: Path) -> None:
    """Opt-in real integration smoke for revised 3C.1.

    Guarded by env var so normal CI/dev does not execute this expensive path.
    """

    if os.environ.get("SWATPLUS_BUILDER_RUN_PYSWATPLUS_INTEGRATION") != "1":
        pytest.skip("Set SWATPLUS_BUILDER_RUN_PYSWATPLUS_INTEGRATION=1 to enable.")
    try:
        ensure_pyswatplus_runtime()
    except Exception as exc:  # pragma: no cover - env dependent
        pytest.skip(f"pySWATPlus runtime unavailable: {exc}")

    txt = Path(
        "tests/_artifacts/e2e_runs/marsh_creek_output_e2e_20260422_201046_manualcheck/"
        "project/Scenarios/Default/TxtInOut"
    )
    alignment = Path(
        "tests/_artifacts/e2e_runs/marsh_creek_output_e2e_20260422_201046_manualcheck/"
        "outputs/alignment.csv"
    )
    if not txt.exists() or not alignment.exists():
        pytest.skip("Required local Marsh Creek fixture artifacts not available.")

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
            str(tmp_path / "calib"),
            "--algo",
            "nsga2",
            "--n-gen",
            "2",
            "--pop-size",
            "4",
        ],
    )
    assert res.exit_code == 0, res.stdout
