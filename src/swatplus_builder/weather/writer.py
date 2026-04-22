"""Serialize a :class:`WeatherBundle` to SWAT+ observed-weather files.

File layout written into ``output_dir``:

* ``{station_name}.pcp`` / ``.tmp`` / ``.hmd`` / ``.wnd`` / ``.slr`` — one
  per (station, variable) pair that has data.
* ``pcp.cli`` / ``tmp.cli`` / ``hmd.cli`` / ``wnd.cli`` / ``slr.cli`` —
  index files listing every station file for that variable.

Byte-for-byte format targets the editor's
``actions/import_weather.py::add_weather_files_type`` parser. In particular:

* **Line 2** of each station file lists the column names
  ``nbyr tstep lat lon elev`` as right-justified strings of widths
  ``4, 10, 10, 10, 10``.
* **Line 3** has the numeric metadata: ``nbyr`` as int width 4, ``tstep``
  hard-coded to ``"0"`` width 10 (daily), then lat/lon/elev as
  ``"{:.3f}"`` width 10.
* **Data rows** (line 4+) are ``YYYY<doy.rjust(5)> <val>`` for
  scalar vars, or ``YYYY<doy.rjust(5)> <tmax><tmin>`` for ``tmp``.
  Each numeric value is rendered as ``"{:.5f}"`` right-justified in a
  field of width 10, followed by 2 spaces (matching
  ``helpers/utils.py:write_num`` ``default_pad=10``, ``spaces_after=2``).

``.cli`` index files are two-line headers
(``<type>.cli: <desc> file names - <who> <when>`` then ``filename``)
followed by one sorted station filename per line.

Station names follow the editor's ``weather_sta_name`` convention —
``s<|lat|*1000><n|s><|lon|*1000><e|w>`` (e.g. ``s41100n77500w``) — so that
``weather_sta_cli`` rows created by ``import_weather`` are a deterministic
function of the station coordinates.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..errors import SwatBuilderInputError, SwatBuilderPipelineError
from ..types import StationSeries, WeatherBundle, WeatherStation, WeatherVar

__all__ = [
    "WeatherWriteResult",
    "station_name",
    "write_observed",
]


_WRITER_TAG = "swatplus-builder"

_DESC: dict[WeatherVar, str] = {
    "pcp": "Precipitation",
    "tmp": "Temperature",
    "hmd": "Relative humidity",
    "wnd": "Wind speed",
    "slr": "Solar radiation",
}

# Column widths in the per-station file header (line 2 / line 3).
_NBYR_W, _TSTEP_W, _LATLON_W, _ELEV_W = 4, 10, 10, 10

# Numeric formatting for daily rows — matches editor's utils.write_num with
# default_pad=10 / default_decimals=5 / spaces_after=2.
_VAL_WIDTH = 10
_VAL_DECIMALS = 5
_VAL_TRAIL = "  "  # two trailing spaces (spaces_after)

# Day-of-year width (matches editor line ``str(day_of_year).rjust(5)``).
_DOY_W = 5


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeatherWriteResult:
    """Outcome of :func:`write_observed` for one project."""

    output_dir: Path
    n_stations: int
    variables: tuple[WeatherVar, ...]
    station_files: list[Path]
    index_files: list[Path]

    @property
    def all_files(self) -> list[Path]:
        return [*self.station_files, *self.index_files]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def station_name(lat: float, lon: float, *, prefix: str = "s", mult: int = 1000) -> str:
    """Return the editor-compatible station name for ``(lat, lon)``.

    Deliberately byte-identical to ``import_weather.weather_sta_name`` so
    rows written here collide with rows the editor would autogenerate.
    """
    latp = "n" if lat >= 0 else "s"
    lonp = "e" if lon >= 0 else "w"
    return f"{prefix}{abs(round(lat * mult))}{latp}{abs(round(lon * mult))}{lonp}"


def write_observed(
    bundle: WeatherBundle,
    output_dir: Path | str,
    *,
    writer_tag: str = _WRITER_TAG,
) -> WeatherWriteResult:
    """Write every per-station file and the per-variable ``.cli`` index.

    Idempotent — overwrites existing files. Creates ``output_dir`` if it
    does not yet exist (``parents=True, exist_ok=True``).

    Args:
        bundle:     Typed weather dataset produced by an adapter
                    (``weather/synthetic.py`` for tests,
                    ``weather/gridmet.py`` for real data).
        output_dir: Destination directory, typically
                    ``<workdir>/Scenarios/Default/TxtInOut`` so the files
                    sit alongside the rest of the SWAT+ inputs.
        writer_tag: Free-text tag written into each file's header line
                    (``"... - file written by <tag> YYYY-MM-DDTHH:MM:SS"``).

    Returns:
        :class:`WeatherWriteResult` enumerating every path written.

    Raises:
        SwatBuilderInputError:    any station's variable array length
            doesn't match the bundle's ``n_days``, or ``start`` is not an
            ISO date.
        SwatBuilderPipelineError: the bundle declares a variable that no
            station actually carries (would produce an empty ``.cli``).
    """
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    start_date = _parse_start(bundle.start)
    _validate_bundle(bundle, start_date)

    now_iso = _dt.datetime.now().replace(microsecond=0).isoformat()
    header_trailer = f" - file written by {writer_tag} {now_iso}"

    # One pass over stations — write every per-variable file they carry.
    station_files: list[Path] = []
    # var → [station_filenames] (sorted at the end when writing .cli indexes)
    files_by_var: dict[WeatherVar, list[str]] = {}
    for series in bundle.stations:
        for var in series.variables():
            fname = f"{series.station.name}.{var}"
            path = output_dir / fname
            _write_station_file(
                path=path,
                series=series,
                var=var,
                start_date=start_date,
                header_trailer=header_trailer,
            )
            station_files.append(path)
            files_by_var.setdefault(var, []).append(fname)

    # One `.cli` index per variable that at least one station has.
    index_files: list[Path] = []
    for var, fnames in sorted(files_by_var.items()):
        path = output_dir / f"{var}.cli"
        _write_cli_index(
            path=path,
            var=var,
            station_files=fnames,
            header_trailer=header_trailer,
        )
        index_files.append(path)

    return WeatherWriteResult(
        output_dir=output_dir,
        n_stations=len(bundle.stations),
        variables=tuple(sorted(files_by_var)),
        station_files=station_files,
        index_files=index_files,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _parse_start(s: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(s)
    except ValueError as exc:
        raise SwatBuilderInputError(
            f"WeatherBundle.start is not an ISO date: {s!r}",
            start=s,
        ) from exc


def _validate_bundle(bundle: WeatherBundle, start: _dt.date) -> None:
    if not bundle.stations:
        raise SwatBuilderInputError(
            "WeatherBundle has no stations — nothing to write.",
        )
    for idx, series in enumerate(bundle.stations):
        if series.start != bundle.start or series.n_days != bundle.n_days:
            raise SwatBuilderInputError(
                f"station {series.station.name!r} (index {idx}) has "
                f"start={series.start!r}/n_days={series.n_days} but bundle "
                f"has {bundle.start!r}/{bundle.n_days}. SWAT+ requires all "
                "stations to span the same date range.",
                station=series.station.name,
                bundle_start=bundle.start,
                bundle_n_days=bundle.n_days,
            )
        for arr_name, arr in (
            ("pcp", series.pcp),
            ("tmax", series.tmax),
            ("tmin", series.tmin),
            ("hmd", series.hmd),
            ("wnd", series.wnd),
            ("slr", series.slr),
        ):
            if arr is not None and len(arr) != bundle.n_days:
                raise SwatBuilderInputError(
                    f"station {series.station.name!r} array {arr_name!r} "
                    f"has length {len(arr)} but bundle n_days={bundle.n_days}",
                    station=series.station.name,
                    array=arr_name,
                    expected_length=bundle.n_days,
                    actual_length=len(arr),
                )
        # tmax / tmin must come as a pair — the engine reads them as
        # two columns from the same ``.tmp`` file.
        if (series.tmax is None) ^ (series.tmin is None):
            raise SwatBuilderInputError(
                f"station {series.station.name!r}: tmax and tmin must be "
                "provided together (SWAT+ reads both from a single .tmp "
                "file).",
                station=series.station.name,
            )

    # Use the start date so validators don't warn about an unused argument.
    _ = start

    # Every variable the bundle *implies* must be provided by at least one
    # station. Empty .cli files trip up import_weather.
    variables: set[WeatherVar] = set()
    for s in bundle.stations:
        variables.update(s.variables())
    if not variables:
        raise SwatBuilderPipelineError(
            "WeatherBundle has stations but zero weather variables across "
            "all of them. At minimum include pcp + (tmax, tmin) for a "
            "usable SWAT+ run.",
            n_stations=len(bundle.stations),
        )


def _write_station_file(
    *,
    path: Path,
    series: StationSeries,
    var: WeatherVar,
    start_date: _dt.date,
    header_trailer: str,
) -> None:
    """Write one ``<station>.<var>`` file matching the editor's format."""
    end_date = start_date + _dt.timedelta(days=series.n_days - 1)
    nbyr = end_date.year - start_date.year + 1
    st = series.station

    with path.open("w", encoding="utf-8", newline="\n") as fh:
        # Header line.
        fh.write(f"{path.name}: {_DESC[var]} data{header_trailer}\n")

        # Line 2 — column labels (format-critical for the editor parser).
        fh.write(
            "nbyr".rjust(_NBYR_W)
            + "tstep".rjust(_TSTEP_W)
            + "lat".rjust(_LATLON_W)
            + "lon".rjust(_LATLON_W)
            + "elev".rjust(_ELEV_W)
            + "\n"
        )

        # Line 3 — numeric metadata.
        fh.write(
            str(nbyr).rjust(_NBYR_W)
            + "0".rjust(_TSTEP_W)
            + f"{st.lat:.3f}".rjust(_LATLON_W)
            + f"{st.lon:.3f}".rjust(_LATLON_W)
            + f"{st.elev:.3f}".rjust(_ELEV_W)
            + "\n"
        )

        # Data rows.
        values = _select_values(series, var)
        _write_rows(fh, start_date=start_date, n_days=series.n_days, values=values)


def _select_values(series: StationSeries, var: WeatherVar) -> Sequence[Sequence[float]]:
    """Return ``n_cols`` aligned arrays for the variable (``tmp`` has 2)."""
    if var == "pcp":
        assert series.pcp is not None
        return (series.pcp,)
    if var == "tmp":
        assert series.tmax is not None and series.tmin is not None
        return (series.tmax, series.tmin)
    if var == "hmd":
        assert series.hmd is not None
        return (series.hmd,)
    if var == "wnd":
        assert series.wnd is not None
        return (series.wnd,)
    if var == "slr":
        assert series.slr is not None
        return (series.slr,)
    raise SwatBuilderPipelineError(f"unknown weather variable {var!r}", var=var)


def _write_rows(
    fh,
    *,
    start_date: _dt.date,
    n_days: int,
    values: Sequence[Sequence[float]],
) -> None:
    day = start_date
    for i in range(n_days):
        doy = day.timetuple().tm_yday
        fh.write(f"{day.year}{str(doy).rjust(_DOY_W)} ")
        for col in values:
            fh.write(_pad_num(col[i]))
        fh.write("\n")
        day += _dt.timedelta(days=1)


def _pad_num(val: float) -> str:
    """Render ``val`` as ``"{:.5f}"`` rjust-10, with 2 trailing spaces.

    Matches the editor's ``utils.write_num(..., default_pad=10)`` contract.
    """
    return f"{float(val):.{_VAL_DECIMALS}f}".rjust(_VAL_WIDTH) + _VAL_TRAIL


def _write_cli_index(
    *,
    path: Path,
    var: WeatherVar,
    station_files: list[str],
    header_trailer: str,
) -> None:
    """Write the ``<var>.cli`` two-header-line index file.

    The editor's ``Swat2012WeatherImport.write_weather`` sorts filenames
    case-insensitively; we match that so our file is byte-identical to one
    the editor would produce.
    """
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{var}.cli: {_DESC[var]} file names{header_trailer}\n")
        fh.write("filename\n")
        for fname in sorted(set(station_files), key=str.lower):
            fh.write(f"{fname}\n")
