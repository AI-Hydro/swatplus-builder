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
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

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


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


from typing import Union

StationLike = Union[WeatherStation, tuple[float, float, float]]
"""What ``fetch_gridmet`` accepts per station.

Either a fully-formed :class:`WeatherStation` (caller provides the name)
or a 3-tuple ``(lat, lon, elev)`` — in which case the station name is
derived via :func:`station_name` so rows collide with the editor's
auto-generated ``weather_sta_cli``."""


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

    series_list: list[StationSeries] = []
    for station in stations_typed:
        df = _fetch_one(
            client=client,
            station=station,
            start=start,
            end=end,
            variables=gridmet_vars,
            cache_dir=cache_path,
        )
        _validate_response_shape(df, station=station, n_days=n_days)
        series = _build_series(
            df=df, station=station, start=start, n_days=n_days, variables=variables
        )
        series_list.append(series)

    return WeatherBundle(stations=series_list, start=start, n_days=n_days)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


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


def _fetch_one(
    *,
    client,  # type: ignore[no-untyped-def]
    station: WeatherStation,
    start: str,
    end: str,
    variables: Sequence[str],
    cache_dir: Path,
) -> "pd.DataFrame":
    """Call pygridmet for a single (lon, lat). Translate errors."""
    try:
        df = client.get_bycoords(
            coords=(station.lon, station.lat),
            dates=(start, end),
            variables=list(variables),
            to_xarray=False,
        )
    except Exception as exc:  # pygridmet raises a medley of types
        raise SwatBuilderExternalError(
            f"pygridmet.get_bycoords failed for station {station.name!r} "
            f"at ({station.lat}, {station.lon}): {exc}",
            station=station.name,
            lat=station.lat,
            lon=station.lon,
            start=start,
            end=end,
            variables=list(variables),
            cache_dir=str(cache_dir),
        ) from exc
    return df


def _validate_response_shape(
    df: "pd.DataFrame",
    *,
    station: WeatherStation,
    n_days: int,
) -> None:
    """Guard against upstream date-range bugs.

    GridMET usually returns exactly ``(end - start + 1)`` rows; if it
    ever returns fewer (e.g. the server silently clamped to the data
    coverage) we want to fail loudly here rather than write a partial
    ``.pcp`` file that the engine would choke on hours later.
    """
    if len(df) != n_days:
        raise SwatBuilderPipelineError(
            f"GridMET returned {len(df)} rows for station {station.name!r}, "
            f"expected {n_days}. The server may have clamped the date "
            "range; try a later start date.",
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
    """Assemble a :class:`StationSeries` from the per-station dataframe."""
    normalized = _normalize_columns(df)

    pcp = tmax = tmin = hmd = wnd = slr = None

    if "pcp" in variables:
        pcp = [round(float(v), 2) for v in _col(normalized, "pr", station)]
    if "tmp" in variables:
        tmmx = _col(normalized, "tmmx", station)
        tmmn = _col(normalized, "tmmn", station)
        tmax = [round(float(v) - 273.15, 2) for v in tmmx]
        tmin = [round(float(v) - 273.15, 2) for v in tmmn]
        # Sanity — if GridMET ever ships a bad cell, tmmx < tmmn flips
        # signs downstream. Log-and-clamp rather than reject; the user
        # can filter later.
        tmax, tmin = _ensure_tmax_gt_tmin(tmax, tmin)
    if "hmd" in variables:
        rmin = _col(normalized, "rmin", station)
        rmax = _col(normalized, "rmax", station)
        hmd = [
            round(max(0.0, min(1.0, (float(a) + float(b)) / 200.0)), 3)
            for a, b in zip(rmin, rmax)
        ]
    if "wnd" in variables:
        wnd = [round(max(0.0, float(v)), 2) for v in _col(normalized, "vs", station)]
    if "slr" in variables:
        # W/m² → MJ/m²/day: multiply by 86400 s / 1e6 = 0.0864.
        slr = [
            round(max(0.0, float(v) * 0.0864), 2)
            for v in _col(normalized, "srad", station)
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


def _normalize_columns(df: "pd.DataFrame") -> dict[str, "pd.Series"]:
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
    cols: dict[str, "pd.Series"], name: str, station: WeatherStation
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
