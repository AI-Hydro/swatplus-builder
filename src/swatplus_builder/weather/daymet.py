"""Daymet -> :class:`WeatherBundle` adapter.

Daymet is a 1 km ORNL/NASA daily gridded product for North America. This
adapter is intentionally a fallback provider for real-basin builds when
GridMET/THREDDS is unavailable. Daymet does not provide wind speed, so the
returned bundle includes precipitation, temperature, humidity, and solar
radiation only.
"""

from __future__ import annotations

import datetime as _dt
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

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
        df = _repair_bounded_day_gaps(
            df,
            station=station,
            start=start,
            end=end,
            n_days=n_days,
        )
        _validate_response_shape(df, station=station, n_days=n_days)
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
) -> "pd.DataFrame":
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


def _validate_response_shape(df: "pd.DataFrame", *, station: WeatherStation, n_days: int) -> None:
    if len(df) != n_days:
        raise SwatBuilderPipelineError(
            f"Daymet returned {len(df)} rows for station {station.name!r}, "
            f"expected {n_days}. The server may have clamped the date range.",
            station=station.name,
            got=int(len(df)),
            expected=n_days,
        )


def _build_series(
    *,
    df: "pd.DataFrame",
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


def _normalize_columns(df: "pd.DataFrame") -> dict[str, "pd.Series"]:
    out: dict[str, pd.Series] = {}
    for col in df.columns:
        key = str(col).split("(")[0].strip().split()[0].lower()
        out[key] = df[col]
    return out


def _col(cols: dict[str, "pd.Series"], name: str, station: WeatherStation):  # type: ignore[no-untyped-def]
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
