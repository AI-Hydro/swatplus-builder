from __future__ import annotations

from pathlib import Path

from swatplus_builder.calibration.report import write_calibration_reports
from swatplus_builder.calibration.spotpy_adapter import CalibrationIterationResult


def test_write_calibration_reports_outputs_core_files(tmp_path: Path) -> None:
    results = [
        CalibrationIterationResult(
            iteration=0,
            content_hash="aaa111",
            cache_hit=False,
            parameters={"CN2": 70.0, "ALPHA_BF": 0.1},
            metrics={"nse": 0.2, "kge": 0.1, "pbias": -5.0},
        ),
        CalibrationIterationResult(
            iteration=1,
            content_hash="bbb222",
            cache_hit=True,
            parameters={"CN2": 75.0, "ALPHA_BF": 0.2},
            metrics={"nse": 0.3, "kge": 0.2, "pbias": -3.0},
        ),
    ]
    out = write_calibration_reports(results, tmp_path)
    assert Path(out["history_csv"]).exists()
    assert Path(out["summary_md"]).exists()
    assert (tmp_path / "convergence.png").exists()
    assert (tmp_path / "dotty.png").exists()
    assert (tmp_path / "pareto.png").exists()

