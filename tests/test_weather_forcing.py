from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.output.weather_forcing import write_weather_forcing_summary


def test_weather_forcing_summary_reads_swatplus_precipitation_files(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "pcp.cli").write_text(
        "pcp.cli: Precipitation file names\n"
        "filename\n"
        "sta1.pcp\n"
        "sta2.pcp\n",
        encoding="utf-8",
    )
    for name, values in {"sta1.pcp": [1.0, 2.0, 3.0], "sta2.pcp": [2.0, 4.0, 6.0]}.items():
        rows = "\n".join(f"2010    {idx}    {value:.5f}  " for idx, value in enumerate(values, start=1))
        (txt / name).write_text(
            f"{name}: Precipitation data\n"
            "nbyr     tstep       lat       lon      elev\n"
            "   1         0    40.000   -86.000   200.000\n"
            f"{rows}\n",
            encoding="utf-8",
        )
    outputs = run / "outputs"
    outputs.mkdir()
    (outputs / "obs_q.csv").write_text(
        "date,obs\n2010-01-01,1.0\n2010-01-02,2.0\n2010-01-03,3.0\n",
        encoding="utf-8",
    )
    delin = run / "delin"
    delin.mkdir()
    (delin / "validation_result.json").write_text(
        json.dumps({"reference_area_km2": 100.0}) + "\n",
        encoding="utf-8",
    )
    (run / "metadata.json").write_text(
        json.dumps({"weather_source": "gridmet", "weather_coverage_flags": {"n_weather_stations": 2}}) + "\n",
        encoding="utf-8",
    )

    report = write_weather_forcing_summary(run)

    assert report["weather_source"] == "gridmet"
    assert report["precipitation"]["available"] is True
    assert report["precipitation"]["station_count"] == 2
    assert report["precipitation"]["n_days"] == 3
    assert report["precipitation"]["mean_areal_total_precip_mm"] == 9.0
    assert report["observed_runoff"]["observed_runoff_depth_mm"] == 5.184
    assert report["observed_runoff"]["precip_overlap_total_mm"] == 9.0
    assert report["observed_runoff"]["observed_runoff_to_overlap_precip_ratio"] == 0.5760000000000001
    assert report["observed_runoff"]["runoff_precip_ratio_class"] == "ordinary_observed_runoff_fraction"
    assert (
        report["observed_runoff"]["runoff_precip_ratio_claim_impact"]
        == "diagnostic_only_forcing_context_available"
    )
    assert Path(report["json_path"]).exists()
    assert Path(report["markdown_path"]).exists()


def test_weather_forcing_summary_flags_high_observed_runoff_fraction(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = run / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "pcp.cli").write_text(
        "pcp.cli: Precipitation file names\n"
        "filename\n"
        "sta1.pcp\n",
        encoding="utf-8",
    )
    (txt / "sta1.pcp").write_text(
        "sta1.pcp: Precipitation data\n"
        "nbyr     tstep       lat       lon      elev\n"
        "   1         0    40.000   -86.000   200.000\n"
        "2010    1    1.00000\n"
        "2010    2    1.00000\n",
        encoding="utf-8",
    )
    outputs = run / "outputs"
    outputs.mkdir()
    (outputs / "obs_q.csv").write_text("date,obs\n2010-01-01,0.5\n2010-01-02,0.5\n", encoding="utf-8")
    delin = run / "delin"
    delin.mkdir()
    (delin / "validation_result.json").write_text(
        json.dumps({"reference_area_km2": 50.0}) + "\n",
        encoding="utf-8",
    )

    report = write_weather_forcing_summary(run)

    assert report["observed_runoff"]["runoff_precip_ratio_class"] == "high_observed_runoff_fraction"
    assert any(flag["code"] == "high_observed_runoff_fraction" for flag in report["diagnostic_flags"])
