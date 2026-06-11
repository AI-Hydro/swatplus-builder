from __future__ import annotations

import importlib
import sys
import types

import pandas as pd
import pytest

from swatplus_builder.errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)


class _FakeDaymet:
    def __init__(self, df_factory):
        self._df_factory = df_factory
        self.calls: list[dict] = []

    def get_bycoords(self, *, coords, dates, variables, to_xarray=False, **kwargs):
        self.calls.append(
            {
                "coords": coords,
                "dates": dates,
                "variables": list(variables),
                "to_xarray": to_xarray,
                **kwargs,
            }
        )
        return self._df_factory(coords=coords, dates=dates, variables=variables)


def _install_fake_pydaymet(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "pydaymet", fake)


def _mk_df(*, coords, dates, variables):
    start, end = (pd.Timestamp(dates[0]), pd.Timestamp(dates[1]))
    idx = pd.date_range(start, end, freq="D")
    n = len(idx)
    data: dict[str, list[float]] = {}
    unit_map = {
        "prcp": "mm/day",
        "tmax": "deg C",
        "tmin": "deg C",
        "vp": "Pa",
        "srad": "W/m2",
        "dayl": "s",
    }
    for var in variables:
        col = f"{var} ({unit_map[var]})"
        if var == "prcp":
            data[col] = [2.5] * n
        elif var == "tmax":
            data[col] = [24.0] * n
        elif var == "tmin":
            data[col] = [14.0] * n
        elif var == "vp":
            data[col] = [1500.0] * n
        elif var == "srad":
            data[col] = [250.0] * n
        elif var == "dayl":
            data[col] = [43200.0] * n
    df = pd.DataFrame(data, index=idx)
    df.index.name = "time"
    return df


def test_module_imports_without_pydaymet():
    sys.modules.pop("pydaymet", None)
    importlib.reload(importlib.import_module("swatplus_builder.weather.daymet"))


def test_missing_pydaymet_yields_clear_external_error(monkeypatch):
    from swatplus_builder.weather.daymet import fetch_daymet

    sys.modules.pop("pydaymet", None)
    finders = sys.meta_path.copy()

    class _Blocker:
        def find_spec(self, name, *_, **__):
            if name == "pydaymet":
                raise ImportError("blocked for test")
            return None

    sys.meta_path.insert(0, _Blocker())
    try:
        with pytest.raises(SwatBuilderExternalError, match="pydaymet is not installed"):
            fetch_daymet(
                stations=[(40.0, -80.0, 200.0)],
                start="2015-01-01",
                end="2015-01-05",
            )
    finally:
        sys.meta_path[:] = finders


def test_daymet_full_supported_variable_set(monkeypatch, tmp_path):
    from swatplus_builder.weather.daymet import fetch_daymet

    fake = _FakeDaymet(_mk_df)
    _install_fake_pydaymet(monkeypatch, fake)
    bundle = fetch_daymet(
        stations=[(41.1, -77.5, 300.0)],
        start="2015-01-01",
        end="2015-01-05",
        cache_dir=tmp_path,
    )

    assert bundle.n_days == 5
    assert len(bundle.stations) == 1
    series = bundle.stations[0]
    assert series.station.name == "s41100n77500w"
    assert series.pcp == [2.5, 2.5, 2.5, 2.5, 2.5]
    assert series.tmax == [24.0, 24.0, 24.0, 24.0, 24.0]
    assert series.tmin == [14.0, 14.0, 14.0, 14.0, 14.0]
    assert series.hmd is not None
    assert all(0.0 <= value <= 1.0 for value in series.hmd)
    assert series.wnd is None
    assert series.slr == [10.8, 10.8, 10.8, 10.8, 10.8]
    assert series.variables() == ["pcp", "tmp", "hmd", "slr"]

    (call,) = fake.calls
    assert call["coords"] == (-77.5, 41.1)
    assert call["dates"] == ("2015-01-01", "2015-01-05")
    assert call["variables"] == ["prcp", "tmax", "tmin", "vp", "srad", "dayl"]
    assert call["conn_timeout"] == 1800
    assert call["validate_filesize"] is False


def test_daymet_rejects_wind_request(monkeypatch, tmp_path):
    from swatplus_builder.weather.daymet import fetch_daymet

    _install_fake_pydaymet(monkeypatch, _FakeDaymet(_mk_df))
    with pytest.raises(SwatBuilderInputError, match="does not provide wind"):
        fetch_daymet(
            stations=[(40.0, -80.0, 200.0)],
            start="2015-01-01",
            end="2015-01-05",
            variables=["pcp", "wnd"],  # type: ignore[list-item]
            cache_dir=tmp_path,
        )


def test_daymet_repairs_isolated_missing_day(monkeypatch, tmp_path):
    from swatplus_builder.weather.daymet import fetch_daymet

    def _gap_df(*, coords, dates, variables):
        df = _mk_df(coords=coords, dates=dates, variables=variables)
        return df.drop(pd.Timestamp("2015-01-03"))

    _install_fake_pydaymet(monkeypatch, _FakeDaymet(_gap_df))
    bundle = fetch_daymet(
        stations=[(40.0, -80.0, 200.0)],
        start="2015-01-01",
        end="2015-01-05",
        cache_dir=tmp_path,
    )
    assert bundle.n_days == 5
    assert len(bundle.stations[0].pcp or []) == 5


def test_daymet_missing_expected_column_is_pipeline_error(monkeypatch, tmp_path):
    from swatplus_builder.weather.daymet import fetch_daymet

    def _missing_df(*, coords, dates, variables):
        df = _mk_df(coords=coords, dates=dates, variables=variables)
        return df.drop(columns=["vp (Pa)"])

    _install_fake_pydaymet(monkeypatch, _FakeDaymet(_missing_df))
    with pytest.raises(SwatBuilderPipelineError, match="missing expected Daymet variable"):
        fetch_daymet(
            stations=[(40.0, -80.0, 200.0)],
            start="2015-01-01",
            end="2015-01-05",
            cache_dir=tmp_path,
        )
