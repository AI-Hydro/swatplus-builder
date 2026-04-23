from __future__ import annotations

from textwrap import dedent

import pandas as pd
import pytest


def _write(path, text: str) -> None:
    path.write_text(dedent(text))


def test_evaluate_run_falls_back_when_channel_day_is_zero(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    # Primary candidate: valid shape but zero discharge everywhere.
    _write(
        txt / "channel_day.txt",
        """\
        channel_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a ha-m
        1 1 1 2015 1 1 cha01 0.0
        2 1 2 2015 1 1 cha01 0.0
        """,
    )

    # Fallback candidate: basin-level daily routed discharge volume.
    _write(
        txt / "basin_sd_cha_day.txt",
        """\
        basin_sd_cha_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3
        1 1 1 2015 1 1 bsn 8640
        2 1 2 2015 1 1 bsn 17280
        """,
    )

    obs = pd.Series(
        [0.08, 0.18],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, metrics = evaluate_run(txt / "channel_day.txt", obs, outlet_gis_id=1)

    # basin_sd_cha_day fallback values are interpreted as daily volume and
    # converted to m3/s.
    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(0.1)
    assert df["sim"].iloc[1] == pytest.approx(0.2)
    assert "nse" in metrics


def test_evaluate_run_converts_channel_day_ha_m_to_cms(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_day.txt",
        """\
        channel_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a ha-m
        1 1 1 2015 1 1 cha01 1.0
        2 1 2 2015 1 1 cha01 2.0
        """,
    )

    obs = pd.Series(
        [0.1, 0.2],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, _ = evaluate_run(txt / "channel_day.txt", obs, outlet_gis_id=1)

    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(10000.0 / 86400.0)
    assert df["sim"].iloc[1] == pytest.approx(20000.0 / 86400.0)


def test_evaluate_run_autodetects_flowing_outlet_when_gis1_is_dry(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 cha01 0.0
        2 1 2 2015 1 1 cha01 0.0
        1 1 1 2015 7 7 cha07 1.5
        2 1 2 2015 7 7 cha07 2.5
        """,
    )

    # Mark channel 7 as terminal outlet in chandeg.con.
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        1 cha0001 1 0 0 0 0 1 s 0 0 0 1 sdc 7 tot 1.0
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        """,
    )

    obs = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    # outlet_gis_id=1 is dry; evaluator should auto-switch to the flowing outlet.
    df, _, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        return_diagnostics=True,
    )

    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(1.5)
    assert df["sim"].iloc[1] == pytest.approx(2.5)
    assert diag["requested_outlet_gis_id"] == 1
    assert diag["selected_outlet_gis_id"] == 7
    assert diag["outlet_autodetected"] is True
    assert diag["outlet_selection_reason"] == "requested_outlet_dry"
