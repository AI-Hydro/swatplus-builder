from __future__ import annotations

from pathlib import Path


def _write_weather_files(txt: Path) -> None:
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "pcp.cli").write_text(
        "pcp.cli\nfilename\nstation01.pcp\n",
        encoding="utf-8",
    )
    (txt / "station01.pcp").write_text(
        "\n".join(
            [
                "station01.pcp",
                "nbyr tstep lat lon elev",
                "1 0 40.0 -86.0 200",
                "2010 1 1.0",
                "2010 2 2.0",
                "2010 32 3.0",
                "2010 33 4.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (txt / "tmp.cli").write_text(
        "tmp.cli\nfilename\nstation01.tmp\n",
        encoding="utf-8",
    )
    (txt / "station01.tmp").write_text(
        "\n".join(
            [
                "station01.tmp",
                "nbyr tstep lat lon elev",
                "1 0 40.0 -86.0 200",
                "2010 1 10.0 0.0",
                "2010 2 12.0 2.0",
                "2010 32 15.0 5.0",
                "2010 33 16.0 6.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (txt / "basin_wb_yr.txt").write_text(
        "\n".join(
            [
                "test SWAT+",
                " jday mon day yr unit gis_id name precip surq_gen latq wateryld perc et pet",
                " mm mm mm mm",
                " 365 12 31 2010 1 1 basin 1000.0 40.0 310.0 350.0 200.0 450.0 1100.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_plot_forcing_context_writes_png_and_pdf(tmp_path: Path) -> None:
    from swatplus_builder.output.plots.forcing_context import plot_forcing_context

    txt = tmp_path / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_weather_files(txt)
    out = tmp_path / "plots" / "fig_09_forcing_context"

    values = plot_forcing_context(tmp_path, out, metadata={"usgs_id": "00000000"})

    assert values.precip_station_count == 1
    assert values.temp_station_count == 1
    assert values.total_precip_mm == 10.0
    assert values.annual_precip_mm == 1000.0
    assert values.annual_pet_mm == 1100.0
    assert values.annual_et_mm == 450.0
    assert out.with_suffix(".png").is_file()
    assert out.with_suffix(".pdf").is_file()
    assert out.with_suffix(".png").stat().st_size > 1000
