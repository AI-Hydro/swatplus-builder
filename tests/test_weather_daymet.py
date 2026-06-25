from __future__ import annotations

import importlib
import sys

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


# ---------------------------------------------------------------------------
# _clip_to_range: pydaymet ignores dates=() and returns full archive
# ---------------------------------------------------------------------------


def _mk_full_archive_df(*, coords, dates, variables):
    """Simulate pydaymet ≥ 0.19 ignoring dates and returning 1980-01-01→2025-12-31."""
    return _mk_df(coords=coords, dates=("1980-01-01", "2025-12-31"), variables=variables)


def test_clip_to_range_trims_full_archive_response(monkeypatch, tmp_path):
    """When pydaymet returns the full 1980-2025 archive, clip to the requested window."""
    from swatplus_builder.weather.daymet import fetch_daymet

    _install_fake_pydaymet(monkeypatch, _FakeDaymet(_mk_full_archive_df))
    # 2015-01-01 → 2015-01-05 = 5 days; no leap Dec-31 in this range
    bundle = fetch_daymet(
        stations=[(41.1, -77.5, 300.0)],
        start="2015-01-01",
        end="2015-01-05",
        cache_dir=tmp_path,
    )
    assert bundle.n_days == 5
    assert len(bundle.stations[0].pcp or []) == 5


def test_clip_to_range_multi_year_span(monkeypatch, tmp_path):
    """Full-archive clip works across a multi-year, leap-spanning window."""
    from swatplus_builder.weather.daymet import fetch_daymet

    _install_fake_pydaymet(monkeypatch, _FakeDaymet(_mk_full_archive_df))
    # 2000-01-01 → 2001-12-31: 731 calendar days (both endpoints inclusive),
    # 1 leap Dec-31 (2000) → 730 in Daymet; _fill_daymet_calendar_gaps restores it → 731
    bundle = fetch_daymet(
        stations=[(41.1, -77.5, 300.0)],
        start="2000-01-01",
        end="2001-12-31",
        cache_dir=tmp_path,
    )
    assert bundle.n_days == 731
    assert len(bundle.stations[0].pcp or []) == 731


# ---------------------------------------------------------------------------
# _fill_daymet_calendar_gaps: Dec-31 of leap years missing from response
# ---------------------------------------------------------------------------


def _mk_missing_leap_dec31(*, coords, dates, variables):
    """Return the requested range but omit Dec-31 of any leap year it contains."""
    df = _mk_df(coords=coords, dates=dates, variables=variables)
    import calendar
    import datetime as dt

    start_d = dt.date.fromisoformat(dates[0])
    end_d = dt.date.fromisoformat(dates[1])
    drops = [
        pd.Timestamp(dt.date(y, 12, 31))
        for y in range(start_d.year, end_d.year + 1)
        if calendar.isleap(y) and start_d <= dt.date(y, 12, 31) <= end_d
    ]
    return df.drop(index=[d for d in drops if d in df.index])


def test_fill_daymet_calendar_gaps_restores_single_leap_dec31(monkeypatch, tmp_path):
    """A single missing Dec-31 in a leap year is interpolated and the count is correct."""
    from swatplus_builder.weather.daymet import fetch_daymet

    _install_fake_pydaymet(monkeypatch, _FakeDaymet(_mk_missing_leap_dec31))
    # 2000-12-29 → 2001-01-02: 5 days; Dec-31-2000 omitted by Daymet → should be filled
    bundle = fetch_daymet(
        stations=[(40.0, -80.0, 200.0)],
        start="2000-12-29",
        end="2001-01-02",
        cache_dir=tmp_path,
    )
    assert bundle.n_days == 5
    assert len(bundle.stations[0].pcp or []) == 5


def test_fill_daymet_calendar_gaps_multiple_leap_years(monkeypatch, tmp_path):
    """Five leap Dec-31 dates missing across 2000-2019 are all filled."""
    from swatplus_builder.weather.daymet import fetch_daymet

    _install_fake_pydaymet(monkeypatch, _FakeDaymet(_mk_missing_leap_dec31))
    bundle = fetch_daymet(
        stations=[(40.0, -80.0, 200.0)],
        start="2000-01-01",
        end="2019-12-31",
        cache_dir=tmp_path,
    )
    # 7305 calendar days (7300 Daymet + 5 filled leap Dec-31s)
    assert bundle.n_days == 7305
    assert len(bundle.stations[0].pcp or []) == 7305


# ---------------------------------------------------------------------------
# _validate_response_shape: directional error messages
# ---------------------------------------------------------------------------


def test_validate_response_shape_too_many_raises_with_direction():
    """got > expected raises SwatBuilderPipelineError with direction=too_many."""
    from swatplus_builder.types import WeatherStation
    from swatplus_builder.weather.daymet import _validate_response_shape

    station = WeatherStation(name="test", lat=40.0, lon=-80.0, elev=200.0)
    df = pd.DataFrame({"x": range(100)})
    with pytest.raises(SwatBuilderPipelineError, match="date-range argument was likely ignored"):
        _validate_response_shape(df, station=station, n_days=5, start="2015-01-01", end="2015-01-05")


def test_validate_response_shape_too_few_raises_with_direction():
    """got < expected raises SwatBuilderPipelineError with direction=too_few."""
    from swatplus_builder.types import WeatherStation
    from swatplus_builder.weather.daymet import _validate_response_shape

    station = WeatherStation(name="test", lat=40.0, lon=-80.0, elev=200.0)
    df = pd.DataFrame({"x": range(4)})
    with pytest.raises(SwatBuilderPipelineError, match="THREDDS server may have clamped"):
        _validate_response_shape(df, station=station, n_days=5, start="2015-01-01", end="2015-01-05")
