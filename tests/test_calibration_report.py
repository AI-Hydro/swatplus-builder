from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.calibration.report import write_calibration_reports
from swatplus_builder.calibration.report import write_hydrograph_comparison_from_two_alignments
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
    out = write_calibration_reports(results, tmp_path, alignment_csv=alignment)
    assert (tmp_path / "hydrograph_calibrated_vs_observed.png").exists()
    assert (tmp_path / "hydrograph_observed_simulated_calibrated.png").exists()
    assert (tmp_path / "hydrograph_observed_simulated_calibrated.pdf").exists()
    assert Path(out["hydrograph_overlay_plot"]).exists()
    assert Path(out["hydrograph_overlay_plot_pdf"]).exists()
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Observed / baseline simulated / calibrated simulated" in summary
    m = json.loads((tmp_path / "hydrograph_comparison_metrics.json").read_text(encoding="utf-8"))
    assert "proxy_result_nse" in m


def test_write_calibration_reports_with_real_alignments_returns_hydrograph_paths(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline_alignment.csv"
    calibrated = tmp_path / "calibrated_alignment.csv"
    baseline.write_text(
        "date,obs,sim\n"
        "2015-01-01,1.0,0.5\n"
        "2015-01-02,2.0,1.2\n"
        "2015-01-03,3.0,2.0\n",
        encoding="utf-8",
    )
    calibrated.write_text(
        "date,obs,sim\n"
        "2015-01-01,1.0,0.9\n"
        "2015-01-02,2.0,2.1\n"
        "2015-01-03,3.0,2.9\n",
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

    out = write_calibration_reports(
        results,
        tmp_path,
        alignment_csv=baseline,
        calibrated_alignment_csv=calibrated,
    )

    assert Path(out["hydrograph_overlay_plot"]).exists()
    assert Path(out["hydrograph_overlay_plot_pdf"]).exists()
    assert Path(out["hydrograph_metrics_json"]).exists()
    metrics = json.loads(Path(out["hydrograph_metrics_json"]).read_text(encoding="utf-8"))
    assert metrics["mode"] == "real_engine"


def test_write_real_hydrograph_comparison_outputs_gate_metrics(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline_alignment.csv"
    calibrated = tmp_path / "calibrated_alignment.csv"
    baseline.write_text(
        "date,obs,sim\n"
        "2015-01-01,1.0,0.5\n"
        "2015-01-02,2.0,1.2\n"
        "2015-01-03,3.0,2.0\n",
        encoding="utf-8",
    )
    calibrated.write_text(
        "date,obs,sim\n"
        "2015-01-01,1.0,0.9\n"
        "2015-01-02,2.0,2.1\n"
        "2015-01-03,3.0,2.9\n",
        encoding="utf-8",
    )

    out = write_hydrograph_comparison_from_two_alignments(
        baseline_alignment_csv=baseline,
        calibrated_alignment_csv=calibrated,
        outdir=tmp_path,
    )

    assert Path(out["hydrograph_plot"]).exists()
    assert Path(out["hydrograph_plot_pdf"]).exists()
    assert Path(out["hydrograph_overlay_plot"]).exists()
    assert Path(out["hydrograph_overlay_plot_pdf"]).exists()
    metrics = json.loads(Path(out["hydrograph_metrics_json"]).read_text(encoding="utf-8"))
    for key in (
        "baseline_nse",
        "baseline_kge",
        "baseline_pbias",
        "calibrated_nse",
        "calibrated_kge",
        "calibrated_pbias",
        "delta_nse",
        "delta_kge",
        "delta_pbias",
    ):
        assert key in metrics
    assert metrics["calibrated_nse"] > metrics["baseline_nse"]
