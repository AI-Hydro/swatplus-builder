"""GridMET -> :class:`WeatherBundle` adapter.

GridMET (Abatzoglou 2013) is a 4 km CONUS daily surface meteorology
product hosted by the Northwest Knowledge Network. We reuse the HyRiver
``pygridmet`` client to hit its THREDDS/OPeNDAP server — cheaper than
re-implementing the NCSS protocol, and it handles server-side time
chunking + retries.

Public API:

* :func:`fetch_gridmet` — pull daily data for a list of stations and
  return a :class:`~swatplus_builder.types.WeatherBundle` ready for
  :func:`swatplus_builder.weather.writer.write_observed`.
* :data:`GRIDMET_VARIABLE_MAP` — translation from our
  :class:`~swatplus_builder.types.WeatherVar` codes to GridMET's.

Unit handling (done by this module, **not** by ``pygridmet`` itself):

====== ================= ==================== =======================
SWAT+  GridMET source    GridMET unit         Conversion we apply
====== ================= ==================== =======================
pcp    ``pr``            mm / day             passthrough
tmax   ``tmmx``          K                    -273.15 → °C
tmin   ``tmmn``          K                    -273.15 → °C
hmd    mean(rmin, rmax)  %                    ×0.01 → fraction
wnd    ``vs``            m/s @ 10 m           passthrough
slr    ``srad``          W / m²               ×0.0864 → MJ/m²/day
====== ================= ==================== =======================

pygridmet is an **optional** dependency. Install it via
``pip install 'swatplus-builder[gridmet]'``. Importing this module
does not import ``pygridmet``; the import is deferred until
:func:`fetch_gridmet` actually runs.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import os
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)
from ..types import StationSeries, WeatherBundle, WeatherStation, WeatherVar
from .writer import station_name

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger(__name__)

__all__ = [
    "GRIDMET_VARIABLE_MAP",
    "fetch_gridmet",
]


# Map our Pydantic ``WeatherVar`` codes → set of GridMET variable names we
# need to request from the server. Note:
#   * ``tmp`` needs TWO GridMET vars (tmmx, tmmn) because SWAT+ writes them
#     together into one ``.tmp`` file.
#   * ``hmd`` needs TWO (rmin, rmax) averaged, since GridMET doesn't ship a
#     single daily-mean RH — documented upstream as intentional because
#     min/max are more useful for agronomy.
GRIDMET_VARIABLE_MAP: dict[WeatherVar, tuple[str, ...]] = {
    "pcp": ("pr",),
    "tmp": ("tmmx", "tmmn"),
    "hmd": ("rmin", "rmax"),
    "wnd": ("vs",),
    "slr": ("srad",),
}

_GRIDMET_FETCH_ATTEMPTS = 2
_GRIDMET_RETRY_SLEEP_SECONDS = 2.0
_GRIDMET_CONN_TIMEOUT_SECONDS = 300
_GRIDMET_GRID_SPACING_DEGREES = 1.0 / 24.0
_GRIDMET_WESTERNMOST_CENTER = -124.7666666667
_GRIDMET_NORTHERNMOST_CENTER = 49.4
# GridMET typically lags real-time by 3–5 days; 7 is a conservative buffer.
# Requests with end dates within this window may receive fewer rows than
# expected because the THREDDS server silently clips to its coverage boundary.
_GRIDMET_REALTIME_LAG_DAYS = 7


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


StationLike = WeatherStation | tuple[float, float, float]
"""What ``fetch_gridmet`` accepts per station.

Either a fully-formed :class:`WeatherStation` (caller provides the name)
or a 3-tuple ``(lat, lon, elev)`` — in which case the station name is
derived via :func:`station_name` so rows collide with the editor's
auto-generated ``weather_sta_cli``."""

ProgressCallback = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_gridmet(
    stations: Iterable[StationLike],
    *,
    start: str,
    end: str,
    variables: Sequence[WeatherVar] = ("pcp", "tmp", "hmd", "wnd", "slr"),
    cache_dir: Path | str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
    progress_callback: ProgressCallback | None = None,
) -> WeatherBundle:
    """Fetch daily GridMET for every station and build a :class:`WeatherBundle`.

    One ``pygridmet.get_bycoords`` call is made per station, which is
    simpler than batching because:

    * Per-station retries don't cascade — a single bad coordinate
      doesn't kill a multi-basin run.
    * pygridmet's multi-coord return uses a MultiIndex that adds zero
      value for our single-pixel sampling case.

    Args:
        stations: Iterable of stations. Each entry is either a
            :class:`WeatherStation` or ``(lat, lon, elev)``.
        start: ISO ``YYYY-MM-DD``.
        end: ISO ``YYYY-MM-DD``, inclusive. Must be >= ``start`` and
            within GridMET's coverage (``1979-01-01`` to ~yesterday).
        variables: Subset of ``("pcp", "tmp", "hmd", "wnd", "slr")``.
            ``"tmp"`` requests tmmx+tmmn; ``"hmd"`` requests rmin+rmax.
        cache_dir: Optional local NetCDF cache forwarded to
            ``pygridmet`` (pygridmet's own logic — we just honour it).
            Defaults to ``settings.cache_dir / "gridmet"``.
        settings: Runtime overrides.
        progress_callback: Optional callback receiving provider/station progress
            dictionaries. Callback failures are logged and do not interrupt
            weather acquisition.

    Returns:
        :class:`WeatherBundle` with one :class:`StationSeries` per input
        station, each carrying every array the ``variables`` argument
        implied.

    Raises:
        SwatBuilderInputError:    empty stations list, bad dates,
            unknown variable code.
        SwatBuilderExternalError: ``pygridmet`` is not installed, or the
            THREDDS server returned an error.
        SwatBuilderPipelineError: server returned data whose length or
            date range disagreed with what we asked for (schema drift
            or server-side date bug).
    """
    start_date, end_date = _parse_date_range(start, end)
    n_days = (end_date - start_date).days + 1
    _warn_if_end_near_realtime(end_date, end)

    stations_typed = [_coerce_station(s) for s in stations]
    if not stations_typed:
        raise SwatBuilderInputError(
            "fetch_gridmet() needs at least one station", stations=[]
        )

    unknown = set(variables) - set(GRIDMET_VARIABLE_MAP)
    if unknown:
        raise SwatBuilderInputError(
            f"unknown weather variable codes: {sorted(unknown)}",
            unknown=sorted(unknown),
            allowed=sorted(GRIDMET_VARIABLE_MAP),
        )

    gridmet_vars = _required_gridmet_vars(variables)

    client = _load_pygridmet()
    cache_path = _resolve_cache_dir(cache_dir, settings)
    os.environ.setdefault("HYRIVER_CACHE_NAME", str(cache_path / "hyriver_cache.sqlite"))
    conn_timeout = _positive_env_int(
        "SWATPLUS_GRIDMET_CONN_TIMEOUT_SECONDS",
        _GRIDMET_CONN_TIMEOUT_SECONDS,
        maximum=1800,
    )
    fetch_attempts = _positive_env_int(
        "SWATPLUS_GRIDMET_FETCH_ATTEMPTS",
        _GRIDMET_FETCH_ATTEMPTS,
        maximum=5,
    )
    unique_grid_cells = {_gridmet_cell_key(station) for station in stations_typed}

    _emit_progress(
        progress_callback,
        status="started",
        provider="gridmet",
        stations_total=len(stations_typed),
        variables=list(gridmet_vars),
        start=start,
        end=end,
        connection_timeout_seconds=conn_timeout,
        fetch_attempts=fetch_attempts,
        unique_grid_cells=len(unique_grid_cells),
    )

    series_list: list[StationSeries] = []
    data_by_grid_cell: dict[tuple[int, int], pd.DataFrame] = {}
    imputation_records: list[dict[str, Any]] = []
    calendar_adjustment_records: list[dict[str, Any]] = []
    started_at = time.monotonic()
    for station_index, station in enumerate(stations_typed, start=1):
        station_started_at = time.monotonic()
        grid_cell = _gridmet_cell_key(station)
        reused_grid_cell = grid_cell in data_by_grid_cell
        _emit_progress(
            progress_callback,
            status="station_started",
            provider="gridmet",
            station=station.name,
            station_index=station_index,
            stations_total=len(stations_typed),
            grid_cell=list(grid_cell),
            reused_grid_cell=reused_grid_cell,
        )
        if reused_grid_cell:
            df = data_by_grid_cell[grid_cell]
        else:
            df = _fetch_one(
                client=client,
                station=station,
                start=start,
                end=end,
                variables=gridmet_vars,
                cache_dir=cache_path,
                conn_timeout=conn_timeout,
                fetch_attempts=fetch_attempts,
                progress_callback=progress_callback,
                station_index=station_index,
                stations_total=len(stations_typed),
            )
            df = _repair_bounded_day_gaps(
                df,
                station=station,
                start=start,
                end=end,
                n_days=n_days,
            )
            _validate_response_shape(
                df,
                station=station,
                start=start,
                end=end,
                n_days=n_days,
            )
            data_by_grid_cell[grid_cell] = df
        series = _build_series(
            df=df, station=station, start=start, n_days=n_days, variables=variables
        )
        series_list.append(series)
        for record in df.attrs.get("imputations", []):
            if isinstance(record, dict):
                imputation_records.append(
                    {
                        **record,
                        "station": station.name,
                        "grid_cell": list(grid_cell),
                        "reused_grid_cell": reused_grid_cell,
                    }
                )
        for record in df.attrs.get("calendar_adjustments", []):
            if isinstance(record, dict):
                calendar_adjustment_records.append(
                    {
                        **record,
                        "station": station.name,
                        "grid_cell": list(grid_cell),
                        "reused_grid_cell": reused_grid_cell,
                    }
                )

        _emit_progress(
            progress_callback,
            status="station_completed",
            provider="gridmet",
            station=station.name,
            station_index=station_index,
            stations_total=len(stations_typed),
            grid_cell=list(grid_cell),
            reused_grid_cell=reused_grid_cell,
            elapsed_seconds=round(time.monotonic() - station_started_at, 3),
        )

    _emit_progress(
        progress_callback,
        status="completed",
        provider="gridmet",
        stations_completed=len(series_list),
        stations_total=len(stations_typed),
        unique_grid_cells=len(data_by_grid_cell),
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )

    return WeatherBundle(
        stations=series_list,
        start=start,
        n_days=n_days,
        provenance={
            "provider": "gridmet",
            "calendar_validated": True,
            "raw_values_validated": True,
            "imputation_count": len(imputation_records),
            "imputations": imputation_records,
            "calendar_adjustment_count": len(calendar_adjustment_records),
            "calendar_adjustments": calendar_adjustment_records,
            "claim_impact": (
                "weather_forcing_contains_declared_imputation"
                if imputation_records
                else (
                    "gridmet_noleap_calendar_normalized"
                    if calendar_adjustment_records
                    else "none"
                )
            ),
        },
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _warn_if_end_near_realtime(end_date: _dt.date, end_str: str) -> None:
    """Emit a warning when *end_date* falls within GridMET's real-time lag window.

    The THREDDS server silently clips responses to its coverage boundary
    (~3–5 days behind today).  Requesting data inside that window will cause
    the server to return fewer rows than asked for; those trailing days will be
    forward-filled with the last available real observation.

    Warn early so the operator can deliberately choose a safe end date rather
    than silently receiving synthetic weather data.
    """
    today = _dt.date.today()
    lag_boundary = today - _dt.timedelta(days=_GRIDMET_REALTIME_LAG_DAYS)
    if end_date > lag_boundary:
        log.warning(
            "GridMET end date %s is within the server's real-time lag window "
            "(estimated coverage boundary: %s). The server may return fewer rows "
            "than requested; trailing missing days will be forward-filled with the "
            "last available real observation. Consider using end ≤ %s to avoid "
            "synthetic weather data.",
            end_str,
            lag_boundary.isoformat(),
            lag_boundary.isoformat(),
        )


def _parse_date_range(start: str, end: str) -> tuple[_dt.date, _dt.date]:
    try:
        s = _dt.date.fromisoformat(start)
        e = _dt.date.fromisoformat(end)
    except ValueError as exc:
        raise SwatBuilderInputError(
            f"GridMET date not ISO YYYY-MM-DD: start={start!r} end={end!r}",
            start=start,
            end=end,
        ) from exc
    if e < s:
        raise SwatBuilderInputError(
            f"end ({end}) precedes start ({start})",
            start=start,
            end=end,
        )
    # GridMET coverage. Server-side enforcement is more authoritative, but
    # pre-checking lets us fail fast on obvious typos without a round-trip.
    if s < _dt.date(1979, 1, 1):
        raise SwatBuilderInputError(
            f"GridMET starts 1979-01-01; start={start} is earlier",
            start=start,
        )
    return s, e


def _coerce_station(s: StationLike) -> WeatherStation:
    if isinstance(s, WeatherStation):
        return s
    if isinstance(s, tuple) and len(s) == 3:
        lat, lon, elev = (float(s[0]), float(s[1]), float(s[2]))
        return WeatherStation(name=station_name(lat, lon), lat=lat, lon=lon, elev=elev)
    raise SwatBuilderInputError(
        "station must be a WeatherStation or (lat, lon, elev) tuple; "
        f"got {type(s).__name__}: {s!r}",
        station=repr(s),
    )


def _required_gridmet_vars(variables: Sequence[WeatherVar]) -> tuple[str, ...]:
    """Deduplicate and preserve a stable order across the request."""
    seen: list[str] = []
    for v in variables:
        for g in GRIDMET_VARIABLE_MAP[v]:
            if g not in seen:
                seen.append(g)
    return tuple(seen)


def _load_pygridmet():  # type: ignore[no-untyped-def]
    """Lazy-import pygridmet with a helpful error when missing."""
    try:
        import pygridmet  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SwatBuilderExternalError(
            "pygridmet is not installed but is required for GridMET fetch. "
            "Install with: pip install 'swatplus-builder[gridmet]'",
            extra_install="swatplus-builder[gridmet]",
        ) from exc
    return pygridmet


def _resolve_cache_dir(
    cache_dir: Path | str | None,
    settings: Settings,
) -> Path:
    """Derive the pygridmet download cache directory.

    We don't (yet) have a dedicated ``Settings.cache_dir``; piggyback on
    ``reference_db_dir``'s parent, which is the same ``~/.swatplus_builder``
    root the reference-data bootstrapper uses.
    """
    if cache_dir is not None:
        p = Path(cache_dir).expanduser().resolve()
    else:
        p = Path(settings.reference_db_dir).expanduser().resolve().parent / "gridmet_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _positive_env_int(name: str, default: int, *, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SwatBuilderInputError(
            f"{name} must be an integer; got {raw!r}",
            setting=name,
            value=raw,
        ) from exc
    if value < 1 or value > maximum:
        raise SwatBuilderInputError(
            f"{name} must be between 1 and {maximum}; got {value}",
            setting=name,
            value=value,
            maximum=maximum,
        )
    return value


def _gridmet_cell_key(station: WeatherStation) -> tuple[int, int]:
    """Return the nearest native GridMET cell index for a station.

    GridMET cell centers form a 1/24-degree grid starting at the westernmost
    and northernmost centers below. Stations with the same key would be
    selected from the same cell by pygridmet, so one provider fetch can safely
    supply each of their SWAT+ station series.
    """
    lon_index = math.floor(
        (station.lon - _GRIDMET_WESTERNMOST_CENTER) / _GRIDMET_GRID_SPACING_DEGREES
        + 0.5
    )
    lat_index = math.floor(
        (_GRIDMET_NORTHERNMOST_CENTER - station.lat) / _GRIDMET_GRID_SPACING_DEGREES
        + 0.5
    )
    return lat_index, lon_index


def _emit_progress(callback: ProgressCallback | None, **event: Any) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception as exc:  # pragma: no cover - defensive observer isolation
        log.warning("GridMET progress callback failed: %s", exc)


def _fetch_one(
    *,
    client,  # type: ignore[no-untyped-def]
    station: WeatherStation,
    start: str,
    end: str,
    variables: Sequence[str],
    cache_dir: Path,
    conn_timeout: int,
    fetch_attempts: int,
    progress_callback: ProgressCallback | None,
    station_index: int,
    stations_total: int,
) -> pd.DataFrame:
    """Call pygridmet for a single (lon, lat). Translate errors."""
    import inspect

    parameters = inspect.signature(client.get_bycoords).parameters
    supports_reliability_options = (
        "conn_timeout" in parameters
        and "validate_filesize" in parameters
    ) or any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    if not supports_reliability_options and (
        getattr(client, "__version__", None) is not None
        or getattr(client, "__name__", "") == "pygridmet"
    ):
        raise SwatBuilderExternalError(
            "Installed pygridmet does not support bounded connection timeouts. "
            "Install pygridmet>=0.16 before acquiring GridMET forcing.",
            provider="gridmet",
            client_version=getattr(client, "__version__", None),
        )
    last_exc: Exception | None = None
    for attempt in range(1, fetch_attempts + 1):
        try:
            kwargs = dict(
                coords=(station.lon, station.lat),
                dates=(start, end),
                variables=list(variables),
                to_xarray=False,
            )
            if supports_reliability_options:
                kwargs.update(conn_timeout=conn_timeout, validate_filesize=False)
            return client.get_bycoords(**kwargs)
        except Exception as exc:  # pygridmet raises a medley of types
            last_exc = exc
            if attempt < fetch_attempts:
                _emit_progress(
                    progress_callback,
                    status="station_retrying",
                    provider="gridmet",
                    station=station.name,
                    station_index=station_index,
                    stations_total=stations_total,
                    attempt=attempt,
                    attempts_total=fetch_attempts,
                    error=str(exc)[-300:],
                )
                time.sleep(_GRIDMET_RETRY_SLEEP_SECONDS)

    assert last_exc is not None
    _emit_progress(
        progress_callback,
        status="station_failed",
        provider="gridmet",
        station=station.name,
        station_index=station_index,
        stations_total=stations_total,
        attempts=fetch_attempts,
        connection_timeout_seconds=conn_timeout,
        error=str(last_exc)[-300:],
    )
    raise SwatBuilderExternalError(
        f"pygridmet.get_bycoords failed for station {station.name!r} "
        f"at ({station.lat}, {station.lon}) after "
        f"{fetch_attempts} attempts: {last_exc}",
        station=station.name,
        lat=station.lat,
        lon=station.lon,
        start=start,
        end=end,
        variables=list(variables),
        cache_dir=str(cache_dir),
        attempts=fetch_attempts,
        connection_timeout_seconds=conn_timeout,
    ) from last_exc


def _repair_bounded_day_gaps(
    df: pd.DataFrame,
    *,
    station: WeatherStation,
    start: str,
    end: str,
    n_days: int,
) -> pd.DataFrame:
    """Fill provider-missing days using adjacent or nearest data.

    Handles three gap patterns:

    * **Leading** (missing days before the first returned row): backward-fill
      from the first available row.
    * **Trailing** (missing days after the last returned row — the common case
      when the server clips to its real-time coverage boundary): forward-fill
      from the last available row.
    * **Interior** (isolated missing day between two available days): linear
      average of the flanking days.

    The cap is 7 days, which covers the typical GridMET real-time lag (~3 days)
    plus a safety margin.  Gaps larger than 7 days are returned unrepaired so
    that ``_validate_response_shape`` raises a clear error.
    """
    if len(df) == n_days:
        return df

    missing_count = n_days - len(df)
    if missing_count < 1 or missing_count > 7:
        return df

    import pandas as pd

    if not isinstance(df.index, pd.DatetimeIndex):
        return df

    expected = pd.date_range(start, end, freq="D")
    got = pd.DatetimeIndex(df.index).normalize()
    missing = expected.difference(got)
    if len(missing) != missing_count:
        return df

    first_available = got[0]
    last_available = got[-1]

    trailing_days = sorted(d for d in missing if d > last_available)
    if trailing_days:
        log.warning(
            "GridMET station %r: server returned data through %s but %s was "
            "requested (%d trailing day(s) missing). Forward-filling from last "
            "real observation — these days contain synthetic weather data.",
            station.name,
            last_available.strftime("%Y-%m-%d"),
            end,
            len(trailing_days),
        )

    repaired = df.copy()
    imputations: list[dict[str, Any]] = []
    calendar_adjustments: list[dict[str, Any]] = []
    for day in sorted(missing):
        if day < first_available:
            # Leading gap: backward-fill from first available row
            row = repaired.loc[[repaired.index.min()]].copy()
            row.index = pd.DatetimeIndex([day])
            repaired = pd.concat([row, repaired])
            method = "backward_fill_from_first_provider_day"
        elif day > last_available:
            # Trailing gap (server clipped end of coverage): forward-fill
            row = repaired.loc[[repaired.index.max()]].copy()
            row.index = pd.DatetimeIndex([day])
            repaired = pd.concat([repaired, row])
            method = "forward_fill_from_last_provider_day"
        else:
            # Interior gap: average flanking days from the original data
            prev_day = day - pd.Timedelta(days=1)
            next_day = day + pd.Timedelta(days=1)
            if prev_day not in got or next_day not in got:
                return df
            row = (
                (
                    repaired.loc[[prev_day]].reset_index(drop=True)
                    + repaired.loc[[next_day]].reset_index(drop=True)
                )
                / 2.0
            )
            row.index = pd.DatetimeIndex([day])
            repaired = pd.concat([repaired, row])
            method = "linear_mean_of_adjacent_provider_days"
        record = {
            "date": str(day.date()),
            "variables": [str(column).split("(")[0].strip() for column in df.columns],
            "method": method,
        }
        if day.month == 12 and day.day == 31 and day.is_leap_year:
            record["kind"] = "gridmet_noleap_dec31_normalization"
            calendar_adjustments.append(record)
        else:
            record["kind"] = "provider_data_gap_imputation"
            imputations.append(record)

    repaired = repaired.sort_index()
    repaired.attrs["imputations"] = imputations
    repaired.attrs["calendar_adjustments"] = calendar_adjustments
    return repaired


def _validate_response_shape(
    df: pd.DataFrame,
    *,
    station: WeatherStation,
    start: str,
    end: str,
    n_days: int,
) -> None:
    """Guard against upstream date-range bugs.

    GridMET usually returns exactly ``(end - start + 1)`` rows; if it
    ever returns fewer (e.g. the server silently clamped to the data
    coverage) we want to fail loudly here rather than write a partial
    ``.pcp`` file that the engine would choke on hours later.
    """
    import pandas as pd

    if len(df) != n_days:
        raise SwatBuilderPipelineError(
            f"GridMET returned {len(df)} rows for station {station.name!r}, "
            f"expected {n_days}. The server may have clamped the date "
            "range; try a later start date.",
            station=station.name,
            got=int(len(df)),
            expected=n_days,
        )
    if not isinstance(df.index, pd.DatetimeIndex):
        raise SwatBuilderPipelineError(
            f"GridMET returned a non-datetime index for station {station.name!r}",
            station=station.name,
        )
    got = pd.DatetimeIndex(df.index)
    if got.tz is not None:
        got = got.tz_localize(None)
    got = got.normalize()
    expected_index = pd.date_range(start, end, freq="D")
    if not got.equals(expected_index):
        raise SwatBuilderPipelineError(
            f"GridMET returned the wrong daily calendar for station {station.name!r}: "
            f"expected {start} through {end}",
            station=station.name,
            expected_start=start,
            expected_end=end,
            got_start=str(got.min().date()) if len(got) else None,
            got_end=str(got.max().date()) if len(got) else None,
            unique=bool(got.is_unique),
            monotonic=bool(got.is_monotonic_increasing),
        )


def _build_series(
    *,
    df: pd.DataFrame,
    station: WeatherStation,
    start: str,
    n_days: int,
    variables: Sequence[WeatherVar],
) -> StationSeries:
    """Assemble a :class:`StationSeries` from the per-station dataframe."""
    normalized = _normalize_columns(df)

    pcp = tmax = tmin = hmd = wnd = slr = None

    if "pcp" in variables:
        raw_pcp = _validated_raw_values(normalized, "pr", station, minimum=0.0)
        pcp = [round(v, 2) for v in raw_pcp]
    if "tmp" in variables:
        tmmx = _validated_raw_values(normalized, "tmmx", station, minimum=150.0, maximum=350.0)
        tmmn = _validated_raw_values(normalized, "tmmn", station, minimum=150.0, maximum=350.0)
        if any(low >= high for high, low in zip(tmmx, tmmn)):
            raise SwatBuilderPipelineError(
                f"GridMET minimum temperature is not below maximum temperature for station {station.name!r}",
                station=station.name,
            )
        tmax = [round(v - 273.15, 2) for v in tmmx]
        tmin = [round(v - 273.15, 2) for v in tmmn]
    if "hmd" in variables:
        rmin = _validated_raw_values(normalized, "rmin", station, minimum=0.0, maximum=100.0)
        rmax = _validated_raw_values(normalized, "rmax", station, minimum=0.0, maximum=100.0)
        if any(low > high for low, high in zip(rmin, rmax)):
            raise SwatBuilderPipelineError(
                f"GridMET minimum humidity exceeds maximum humidity for station {station.name!r}",
                station=station.name,
            )
        hmd = [
            round((a + b) / 200.0, 3)
            for a, b in zip(rmin, rmax)
        ]
    if "wnd" in variables:
        wnd = [
            round(v, 2)
            for v in _validated_raw_values(normalized, "vs", station, minimum=0.0)
        ]
    if "slr" in variables:
        # W/m² → MJ/m²/day: multiply by 86400 s / 1e6 = 0.0864.
        slr = [
            round(v * 0.0864, 2)
            for v in _validated_raw_values(normalized, "srad", station, minimum=0.0)
        ]

    return StationSeries(
        station=station,
        start=start,
        n_days=n_days,
        pcp=pcp,
        tmax=tmax,
        tmin=tmin,
        hmd=hmd,
        wnd=wnd,
        slr=slr,
    )


def _normalize_columns(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Flatten pygridmet's column names to their pure variable name.

    pygridmet's DataFrames label columns like ``"pr (mm)"`` /
    ``"tmmx (K)"`` — the unit suffix is human-friendly but inconvenient.
    We strip everything after the first space / parenthesis and
    lower-case to make lookups robust.
    """
    out: dict[str, pd.Series] = {}
    for col in df.columns:
        key = str(col).split("(")[0].strip().split()[0].lower()
        out[key] = df[col]
    return out


def _col(
    cols: dict[str, pd.Series], name: str, station: WeatherStation
):  # type: ignore[no-untyped-def]
    try:
        return cols[name].to_list()
    except KeyError as exc:
        raise SwatBuilderPipelineError(
            f"pygridmet response for station {station.name!r} is missing "
            f"expected GridMET variable {name!r}. Available: "
            f"{sorted(cols)}",
            station=station.name,
            missing=name,
            available=sorted(cols),
        ) from exc


def _validated_raw_values(
    cols: dict[str, pd.Series],
    name: str,
    station: WeatherStation,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> list[float]:
    values = [float(value) for value in _col(cols, name, station)]
    for index, value in enumerate(values):
        if not math.isfinite(value):
            raise SwatBuilderPipelineError(
                f"GridMET variable {name!r} contains a non-finite value for station {station.name!r}",
                station=station.name,
                variable=name,
                row=index,
            )
        if minimum is not None and value < minimum:
            raise SwatBuilderPipelineError(
                f"GridMET variable {name!r} is below {minimum} for station {station.name!r}",
                station=station.name,
                variable=name,
                row=index,
                value=value,
            )
        if maximum is not None and value > maximum:
            raise SwatBuilderPipelineError(
                f"GridMET variable {name!r} exceeds {maximum} for station {station.name!r}",
                station=station.name,
                variable=name,
                row=index,
                value=value,
            )
    return values


def _ensure_tmax_gt_tmin(
    tmax: list[float], tmin: list[float]
) -> tuple[list[float], list[float]]:
    """Clamp ``tmin = min(tmin, tmax - 0.1)`` to preserve the SWAT+
    invariant ``tmax > tmin`` on the rare days GridMET ships equal or
    inverted values.
    """
    fixed_tmin: list[float] = []
    for i, (tx, tn) in enumerate(zip(tmax, tmin)):
        if tn >= tx:
            fixed_tmin.append(round(tx - 0.1, 2))
        else:
            fixed_tmin.append(tn)
        _ = i  # purely for readability; no-op
    return tmax, fixed_tmin
