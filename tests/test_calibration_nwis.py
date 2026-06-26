from __future__ import annotations

import sys
import types

import pandas as pd

from swatplus_builder.calibration.nwis import fetch_usgs_daily_q


def test_fetch_usgs_daily_q_uses_pygeohydro_streamflow_as_m3s(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SWATPLUS_NWIS_CACHE_DIR", str(tmp_path / "cache"))
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


def test_fetch_usgs_daily_q_reuses_matching_cached_observations(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SWATPLUS_NWIS_CACHE_DIR", str(tmp_path / "cache"))
    out_csv = tmp_path / "obs_q.csv"
    out_csv.write_text(
        "date,obs\n"
        "2015-01-01,1.0\n"
        "2015-01-02,2.0\n"
        "2015-01-03,3.0\n",
        encoding="utf-8",
    )

    class _FailingNWIS:
        def get_streamflow(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("cache hit should not call NWIS")

    fake_mod = types.ModuleType("pygeohydro")
    fake_mod.NWIS = _FailingNWIS
    monkeypatch.setitem(sys.modules, "pygeohydro", fake_mod)

    q = fetch_usgs_daily_q("01547700", "2015-01-01", "2015-01-03", out_csv=out_csv)

    assert list(q.values) == [1.0, 2.0, 3.0]
    assert list(q.index.strftime("%Y-%m-%d")) == ["2015-01-01", "2015-01-02", "2015-01-03"]


def test_fetch_usgs_daily_q_retries_transient_nwis_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SWATPLUS_NWIS_CACHE_DIR", str(tmp_path / "cache"))
    idx = pd.date_range("2015-01-01", periods=2, freq="D", tz="UTC")
    df = pd.DataFrame({"USGS-01547700": [1.0, 2.0]}, index=idx)
    attempts = {"count": 0}

    class _FlakyNWIS:
        def get_streamflow(self, usgs_id: str, dates: tuple[str, str], freq: str):  # noqa: ANN001
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ConnectionResetError("connection reset by peer")
            return df

    fake_mod = types.ModuleType("pygeohydro")
    fake_mod.NWIS = _FlakyNWIS
    monkeypatch.setitem(sys.modules, "pygeohydro", fake_mod)
    monkeypatch.setenv("SWATPLUS_NWIS_FETCH_RETRY_BASE_S", "0")

    q = fetch_usgs_daily_q("01547700", "2015-01-01", "2015-01-02", out_csv=tmp_path / "obs_q.csv")

    assert attempts["count"] == 2
    assert list(q.values) == [1.0, 2.0]
