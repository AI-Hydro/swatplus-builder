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
