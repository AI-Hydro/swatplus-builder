from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest


def test_summarize_water_balance_uses_numeric_columns_despite_trailing_text(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.water_balance import summarize_water_balance

    txt = tmp_path / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "basin_wb_yr.txt").write_text(
        dedent(
            """\
             title
              jday mon day yr unit gis_id name precip surq_gen latq wateryld perc et plant_cov mgt_ops
                                      mm    mm      mm   mm       mm   mm  mm        ---
               365 12 31 2007 1 1 bsn 1000.0 10.0 100.0 110.0 450.0 420.0 0.0 Original Simulation
               366 12 31 2008 1 1 bsn 1200.0 20.0 120.0 140.0 500.0 440.0 0.0 Original Simulation
            """
        )
    )
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "alignment.csv").write_text(",obs,sim\n2007-01-01,1.0,0.2\n2008-01-01,1.0,0.2\n")
    delin = tmp_path / "delin"
    delin.mkdir()
    (delin / "validation_result.json").write_text(json.dumps({"delineated_area_km2": 100.0}))

    values = summarize_water_balance(tmp_path)

    assert values.precip == pytest.approx(1100.0)
    assert values.et == pytest.approx(430.0)
    assert values.wateryld == pytest.approx(125.0)
    assert values.residual == pytest.approx(545.0)
    assert values.wateryld_ratio == pytest.approx(125.0 / 1100.0)
    assert values.years == (2007, 2008)
    assert values.observed_runoff_mm is not None


def test_plot_water_balance_writes_png_and_pdf(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.water_balance import plot_water_balance

    txt = tmp_path / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "basin_wb_aa.txt").write_text(
        "title\n"
        "jday mon day yr unit gis_id name precip surq_gen latq wateryld perc et\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 1 1 bsn 1000.0 20.0 130.0 150.0 450.0 400.0\n"
    )

    out = tmp_path / "plots" / "fig_10_water_balance"
    values = plot_water_balance(tmp_path, out)

    assert values.precip == pytest.approx(1000.0)
    assert out.with_suffix(".png").is_file()
    assert out.with_suffix(".pdf").is_file()
    assert out.with_suffix(".png").stat().st_size > 1000
