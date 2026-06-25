"""Daymet -> :class:`WeatherBundle` adapter.

Daymet is a 1 km ORNL/NASA daily gridded product for North America. This
adapter is intentionally a fallback provider for real-basin builds when
GridMET/THREDDS is unavailable. Daymet does not provide wind speed, so the
returned bundle includes precipitation, temperature, humidity, and solar
radiation only.

Known upstream quirk (pydaymet ≥ 0.19):
    ``get_bycoords`` can ignore the ``dates=(start, end)`` argument and return
    the full Daymet archive (1980-present) when its internal file-metadata
    cache is stale or the request falls outside a cached region.  We defend
    against this in ``_clip_to_range`` — called immediately after each fetch —
    which slices the returned DataFrame to exactly ``[start, end]`` before any
    downstream validation or gap-repair runs.

Daymet 365-day calendar:
    Daymet omits December 31 in leap years.  After clipping to the requested
    window, ``_fill_daymet_calendar_gaps`` synthetically fills those missing
    Dec-31 rows by interpolating from Dec-30 and Jan-1, so the downstream
    SWAT+ writer always receives a complete calendar-day sequence.
"""

from __future__ import annotations

import calendar as _calendar
import datetime as _dt
import math
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)
from ..types import StationSeries, WeatherBundle, WeatherStation, WeatherVar
from .gridmet import _coerce_station, _ensure_tmax_gt_tmin, _repair_bounded_day_gaps

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "DAYMET_VARIABLE_MAP",
    "fetch_daymet",
]


DAYMET_VARIABLE_MAP: dict[WeatherVar, tuple[str, ...]] = {
    "pcp": ("prcp",),
    "tmp": ("tmax", "tmin"),
    "hmd": ("vp", "tmax", "tmin"),
    "slr": ("srad", "dayl"),
}

_DAYMET_FETCH_ATTEMPTS = 3
_DAYMET_RETRY_SLEEP_SECONDS = 2.0
_DAYMET_CONN_TIMEOUT_SECONDS = 1800


def fetch_daymet(
    stations: Iterable[WeatherStation | tuple[float, float, float]],
    *,
    start: str,
    end: str,
    variables: Sequence[WeatherVar] = ("pcp", "tmp", "hmd", "slr"),
    cache_dir: Path | str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> WeatherBundle:
    """Fetch daily Daymet point data and build a SWAT+ weather bundle."""
    start_date, end_date = _parse_date_range(start, end)
    n_days = (end_date - start_date).days + 1

    stations_typed = [_coerce_station(s) for s in stations]
    if not stations_typed:
        raise SwatBuilderInputError("fetch_daymet() needs at least one station", stations=[])

    if "wnd" in variables:
        raise SwatBuilderInputError(
            "Daymet does not provide wind speed; request GridMET or omit 'wnd'",
            unknown=["wnd"],
            allowed=sorted(DAYMET_VARIABLE_MAP),
        )
    unknown = set(variables) - set(DAYMET_VARIABLE_MAP)
    if unknown:
        raise SwatBuilderInputError(
            f"unknown weather variable codes for Daymet: {sorted(unknown)}",
            unknown=sorted(unknown),
            allowed=sorted(DAYMET_VARIABLE_MAP),
        )

    daymet_vars = _required_daymet_vars(variables)
    client = _load_pydaymet()
    cache_path = _resolve_cache_dir(cache_dir, settings)

    series_list: list[StationSeries] = []
    for station in stations_typed:
        df = _fetch_one(
            client=client,
            station=station,
            start=start,
            end=end,
            variables=daymet_vars,
            cache_dir=cache_path,
        )
        # Clip first: pydaymet ≥ 0.19 can return the full archive (1980-present)
        # when dates=() is ignored.  Slice to exactly [start, end] before any
        # gap-repair or validation so the rest of the pipeline sees a clean window.
        df = _clip_to_range(df, start_date, end_date)
        # Fill Dec-31 gaps introduced by Daymet's 365-day calendar in leap years.
        df = _fill_daymet_calendar_gaps(df, start_date, end_date)
        df = _repair_bounded_day_gaps(
            df,
            station=station,
            start=start,
            end=end,
            n_days=n_days,
        )
        _validate_response_shape(df, station=station, n_days=n_days, start=start, end=end)
        series_list.append(
            _build_series(
                df=df,
                station=station,
                start=start,
                n_days=n_days,
                variables=variables,
            )
        )

    return WeatherBundle(stations=series_list, start=start, n_days=n_days)


def _parse_date_range(start: str, end: str) -> tuple[_dt.date, _dt.date]:
    try:
        s = _dt.date.fromisoformat(start)
        e = _dt.date.fromisoformat(end)
    except ValueError as exc:
        raise SwatBuilderInputError(
            f"Daymet date not ISO YYYY-MM-DD: start={start!r} end={end!r}",
            start=start,
            end=end,
        ) from exc
    if e < s:
        raise SwatBuilderInputError(
            f"end ({end}) precedes start ({start})",
            start=start,
            end=end,
        )
    if s < _dt.date(1980, 1, 1):
        raise SwatBuilderInputError(
            f"Daymet starts 1980-01-01 for North America; start={start} is earlier",
            start=start,
        )
    return s, e


def _required_daymet_vars(variables: Sequence[WeatherVar]) -> tuple[str, ...]:
    seen: list[str] = []
    for var in variables:
        for daymet_var in DAYMET_VARIABLE_MAP[var]:
            if daymet_var not in seen:
                seen.append(daymet_var)
    return tuple(seen)


def _load_pydaymet():  # type: ignore[no-untyped-def]
    try:
        import pydaymet  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SwatBuilderExternalError(
            "pydaymet is not installed but is required for Daymet fallback. "
            "Install with: pip install 'swatplus-builder[hyriver]'",
            extra_install="swatplus-builder[hyriver]",
        ) from exc
    return pydaymet


def _resolve_cache_dir(cache_dir: Path | str | None, settings: Settings) -> Path:
    if cache_dir is not None:
        path = Path(cache_dir).expanduser().resolve()
    else:
        path = Path(settings.reference_db_dir).expanduser().resolve().parent / "daymet_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fetch_one(
    *,
    client,  # type: ignore[no-untyped-def]
    station: WeatherStation,
    start: str,
    end: str,
    variables: Sequence[str],
    cache_dir: Path,
) -> pd.DataFrame:
    last_exc: Exception | None = None
    for attempt in range(1, _DAYMET_FETCH_ATTEMPTS + 1):
        try:
            return client.get_bycoords(
                coords=(station.lon, station.lat),
                dates=(start, end),
                variables=list(variables),
                to_xarray=False,
                conn_timeout=_DAYMET_CONN_TIMEOUT_SECONDS,
                validate_filesize=False,
            )
        except TypeError as exc:
            if "conn_timeout" not in str(exc) and "validate_filesize" not in str(exc):
                raise
            try:
                return client.get_bycoords(
                    coords=(station.lon, station.lat),
                    dates=(start, end),
                    variables=list(variables),
                    to_xarray=False,
                )
            except Exception as fallback_exc:
                last_exc = fallback_exc
                if attempt < _DAYMET_FETCH_ATTEMPTS:
                    time.sleep(_DAYMET_RETRY_SLEEP_SECONDS)
        except Exception as exc:
            last_exc = exc
            if attempt < _DAYMET_FETCH_ATTEMPTS:
                time.sleep(_DAYMET_RETRY_SLEEP_SECONDS)

    assert last_exc is not None
    raise SwatBuilderExternalError(
        f"pydaymet.get_bycoords failed for station {station.name!r} "
        f"at ({station.lat}, {station.lon}) after "
        f"{_DAYMET_FETCH_ATTEMPTS} attempts: {last_exc}",
        station=station.name,
        lat=station.lat,
        lon=station.lon,
        start=start,
        end=end,
        variables=list(variables),
        cache_dir=str(cache_dir),
        attempts=_DAYMET_FETCH_ATTEMPTS,
    ) from last_exc


def _clip_to_range(
    df: "pd.DataFrame",  # noqa: UP037
    start_date: _dt.date,
    end_date: _dt.date,
) -> "pd.DataFrame":  # noqa: UP037
    """Slice a Daymet response to exactly [start_date, end_date].

    pydaymet ≥ 0.19 sometimes returns the full archive (1980-present) when
    the ``dates=`` argument is silently ignored.  Slicing here makes the
    caller robust against that version-specific bug without needing to pin
    the library.

    If the returned frame does not have a DatetimeIndex we return it
    unchanged and let ``_validate_response_shape`` raise a useful error.
    """
    try:
        import pandas as pd

        if not isinstance(df.index, pd.DatetimeIndex):
            return df
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        clipped = df.loc[start_ts:end_ts]
        return clipped
    except Exception:
        return df


def _fill_daymet_calendar_gaps(
    df: "pd.DataFrame",  # noqa: UP037
    start_date: _dt.date,
    end_date: _dt.date,
) -> "pd.DataFrame":  # noqa: UP037
    """Synthetically fill December 31 rows that Daymet omits in leap years.

    Daymet uses a 365-day calendar and never emits a Dec-31 row for leap
    years.  After ``_clip_to_range`` those dates are simply absent from the
    index.  We interpolate each missing Dec-31 as the mean of Dec-30 and
    Jan-1 so the downstream SWAT+ writer always sees a continuous
    calendar-day sequence.

    If the frame does not have a DatetimeIndex, or any expected neighbour is
    also missing, we return the frame unchanged (``_validate_response_shape``
    will then fire).
    """
    try:
        import pandas as pd

        if not isinstance(df.index, pd.DatetimeIndex):
            return df

        leap_dec31: list[_dt.date] = [
            _dt.date(y, 12, 31)
            for y in range(start_date.year, end_date.year + 1)
            if _calendar.isleap(y) and start_date <= _dt.date(y, 12, 31) <= end_date
        ]
        if not leap_dec31:
            return df

        got_dates = set(df.index.normalize().date)  # type: ignore[attr-defined]
        missing = [d for d in leap_dec31 if d not in got_dates]
        if not missing:
            return df

        repaired = df.copy()
        for day in missing:
            dec30 = pd.Timestamp(_dt.date(day.year, 12, 30))
            jan01 = pd.Timestamp(_dt.date(day.year + 1, 1, 1))
            if dec30 not in repaired.index or jan01 not in repaired.index:
                # Can't interpolate without both neighbours; leave it for the
                # validator to catch rather than writing a garbled value.
                continue
            row = (
                (
                    repaired.loc[[dec30]].reset_index(drop=True)
                    + repaired.loc[[jan01]].reset_index(drop=True)
                )
                / 2.0
            )
            row.index = pd.DatetimeIndex([pd.Timestamp(day)])
            repaired = pd.concat([repaired, row])

        return repaired.sort_index()
    except Exception:
        return df


def _validate_response_shape(
    df: pd.DataFrame,
    *,
    station: WeatherStation,
    n_days: int,
    start: str,
    end: str,
) -> None:
    """Fail loudly when the row count does not match what was requested.

    Two distinct failure modes are reported separately:

    * ``got > expected`` — the date-range argument was ignored by the upstream
      library and more data than requested was returned.  ``_clip_to_range``
      should have prevented this; if it occurs anyway the DataFrame index is
      likely not a DatetimeIndex.
    * ``got < expected`` — the Daymet server or THREDDS clamped the date range
      (e.g. the start predates available coverage for this location).  A later
      start date or a shorter window usually resolves this.
    """
    got = int(len(df))
    if got == n_days:
        return
    if got > n_days:
        raise SwatBuilderPipelineError(
            f"Daymet returned {got} rows for station {station.name!r} but only "
            f"{n_days} were requested ({start} → {end}). The date-range argument "
            "was likely ignored by pydaymet (known issue in ≥ 0.19 when its file "
            "cache is stale). Automatic clipping failed because the response index "
            "is not a DatetimeIndex. Try upgrading pydaymet or clearing its cache.",
            station=station.name,
            got=got,
            expected=n_days,
            direction="too_many",
            start=start,
            end=end,
        )
    raise SwatBuilderPipelineError(
        f"Daymet returned only {got} of {n_days} requested rows for station "
        f"{station.name!r} ({start} → {end}). The Daymet THREDDS server may have "
        "clamped the date range (data may not be available for the full window at "
        "this location). Try a later start date or a shorter time window.",
        station=station.name,
        got=got,
        expected=n_days,
        direction="too_few",
        start=start,
        end=end,
    )


def _build_series(
    *,
    df: pd.DataFrame,
    station: WeatherStation,
    start: str,
    n_days: int,
    variables: Sequence[WeatherVar],
) -> StationSeries:
    cols = _normalize_columns(df)
    pcp = tmax = tmin = hmd = slr = None

    if "pcp" in variables:
        pcp = [round(max(0.0, float(v)), 2) for v in _col(cols, "prcp", station)]
    if "tmp" in variables or "hmd" in variables:
        tmax_values = [round(float(v), 2) for v in _col(cols, "tmax", station)]
        tmin_values = [round(float(v), 2) for v in _col(cols, "tmin", station)]
        tmax_values, tmin_values = _ensure_tmax_gt_tmin(tmax_values, tmin_values)
        if "tmp" in variables:
            tmax = tmax_values
            tmin = tmin_values
    if "hmd" in variables:
        vp_pa = _col(cols, "vp", station)
        hmd = [
            round(_relative_humidity_from_vp(float(vp), tx, tn), 3)
            for vp, tx, tn in zip(vp_pa, tmax_values, tmin_values)
        ]
    if "slr" in variables:
        srad = _col(cols, "srad", station)
        dayl = _col(cols, "dayl", station)
        slr = [
            round(max(0.0, float(rad) * float(seconds) / 1_000_000.0), 2)
            for rad, seconds in zip(srad, dayl)
        ]

    return StationSeries(
        station=station,
        start=start,
        n_days=n_days,
        pcp=pcp,
        tmax=tmax,
        tmin=tmin,
        hmd=hmd,
        wnd=None,
        slr=slr,
    )


def _normalize_columns(df: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for col in df.columns:
        key = str(col).split("(")[0].strip().split()[0].lower()
        out[key] = df[col]
    return out


def _col(cols: dict[str, pd.Series], name: str, station: WeatherStation):  # type: ignore[no-untyped-def]
    try:
        return cols[name].to_list()
    except KeyError as exc:
        raise SwatBuilderPipelineError(
            f"pydaymet response for station {station.name!r} is missing "
            f"expected Daymet variable {name!r}. Available: {sorted(cols)}",
            station=station.name,
            missing=name,
            available=sorted(cols),
        ) from exc


def _relative_humidity_from_vp(vp_pa: float, tmax_c: float, tmin_c: float) -> float:
    vp_kpa = max(0.0, vp_pa / 1000.0)
    es_tmax = _saturation_vapor_pressure_kpa(tmax_c)
    es_tmin = _saturation_vapor_pressure_kpa(tmin_c)
    es_mean = max(0.001, (es_tmax + es_tmin) / 2.0)
    return max(0.0, min(1.0, vp_kpa / es_mean))


def _saturation_vapor_pressure_kpa(temp_c: float) -> float:
    return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
