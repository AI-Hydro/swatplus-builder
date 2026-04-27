from __future__ import annotations

import sys
import types

import pandas as pd

from swatplus_builder.calibration.nwis import fetch_usgs_daily_q


def test_fetch_usgs_daily_q_uses_pygeohydro_streamflow_as_m3s(monkeypatch, tmp_path) -> None:
    idx = pd.date_range("2015-01-01", periods=3, freq="D", tz="UTC")
    df = pd.DataFrame({"USGS-01547700": [1.0, 2.0, 3.0]}, index=idx)

    class _FakeNWIS:
        def get_streamflow(self, usgs_id: str, dates: tuple[str, str], freq: str):  # noqa: ANN001
            assert usgs_id == "01547700"
            assert freq == "dv"
            return df

    fake_mod = types.ModuleType("pygeohydro")
    fake_mod.NWIS = _FakeNWIS
    monkeypatch.setitem(sys.modules, "pygeohydro", fake_mod)

    out_csv = tmp_path / "obs_q.csv"
    q = fetch_usgs_daily_q("01547700", "2015-01-01", "2015-01-03", out_csv=out_csv)

    assert list(q.values) == [1.0, 2.0, 3.0]
    assert q.index.tz is None
    assert out_csv.exists()
