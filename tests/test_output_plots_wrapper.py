from __future__ import annotations

import json
from pathlib import Path


def test_plot_wrapper_prefers_locked_benchmark_metrics_and_alignment(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.wrapper import (
        _preferred_alignment_path,
        _preferred_metrics_path,
    )

    reports = tmp_path / "reports"
    outputs = tmp_path / "outputs"
    benchmark = tmp_path / "benchmark"
    reports.mkdir()
    outputs.mkdir()
    benchmark.mkdir()
    (reports / "metrics.json").write_text(json.dumps({"nse": -9.0, "kge": -9.0}), encoding="utf-8")
    (outputs / "alignment.csv").write_text("date,obs,sim\n2010-01-01,1.0,0.0\n", encoding="utf-8")
    (benchmark / "metrics.json").write_text(json.dumps({"nse": 0.3, "kge": 0.4}), encoding="utf-8")
    (benchmark / "alignment.csv").write_text("date,obs,sim\n2010-01-01,1.0,0.8\n", encoding="utf-8")

    assert _preferred_metrics_path(tmp_path) == benchmark / "metrics.json"
    assert _preferred_alignment_path(tmp_path) == benchmark / "alignment.csv"


def test_plot_wrapper_falls_back_to_legacy_output_artifacts(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.wrapper import (
        _preferred_alignment_path,
        _preferred_metrics_path,
    )

    reports = tmp_path / "reports"
    outputs = tmp_path / "outputs"
    reports.mkdir()
    outputs.mkdir()
    (reports / "metrics.json").write_text(json.dumps({"nse": 0.1, "kge": 0.2}), encoding="utf-8")
    (outputs / "alignment.csv").write_text("date,obs,sim\n2010-01-01,1.0,0.8\n", encoding="utf-8")

    assert _preferred_metrics_path(tmp_path) == reports / "metrics.json"
    assert _preferred_alignment_path(tmp_path) == outputs / "alignment.csv"
