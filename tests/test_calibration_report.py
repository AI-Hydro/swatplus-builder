from __future__ import annotations

import json
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
    assert (tmp_path / "parameter_comparison.csv").exists()
    assert (tmp_path / "parameter_comparison.png").exists()
    assert (tmp_path / "best_solution.json").exists()


def test_write_calibration_reports_with_alignment_outputs_hydrograph(tmp_path: Path) -> None:
    alignment = tmp_path / "alignment.csv"
    alignment.write_text(
        "date,obs,sim\n"
        "2015-01-01,1.0,0.8\n"
        "2015-01-02,2.0,1.7\n"
        "2015-01-03,0.5,0.6\n",
        encoding="utf-8",
    )
    results = [
        CalibrationIterationResult(
            iteration=0,
            content_hash="abc",
            cache_hit=False,
            parameters={"CN2": 70.0, "ALPHA_BF": 0.1, "SURLAG": 3.0},
            metrics={"nse": 0.3, "kge": 0.2, "pbias": -2.0},
        )
    ]
    write_calibration_reports(results, tmp_path, alignment_csv=alignment)
    assert (tmp_path / "hydrograph_calibrated_vs_observed.png").exists()
    m = json.loads((tmp_path / "hydrograph_comparison_metrics.json").read_text(encoding="utf-8"))
    assert "proxy_result_nse" in m
