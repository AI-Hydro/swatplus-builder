"""Deterministic synthetic weather for tests and first-run smoke.

This is **not** climate science — it's a stand-in so that the end-to-end
``build → setup_project → import_weather → write_files → run_engine`` loop
can be exercised without depending on GridMET / THREDDS at test time.

Model
-----

For each station and variable we produce a sinusoidal annual cycle with a
small amount of deterministic noise driven from
:class:`random.Random(seed=<station_hash>)` so results are reproducible
across machines. The numbers are climatologically plausible for a
mid-latitude (~40°N) basin but should NOT be mistaken for actual data.

* ``pcp``  — mean ~2 mm/day with a simple wet-day mask (≈30% wet days).
* ``tmax`` — winter min ~0 °C, summer max ~30 °C.
* ``tmin`` — tmax − 10 °C always (so tmax > tmin by construction).
* ``hmd``  — fraction in [0.4, 0.9].
* ``wnd``  — 2–5 m/s with a gentle annual cycle.
* ``slr``  — 3–25 MJ/m²/day mid-latitude cycle.

Use :func:`synthesize` to build a :class:`WeatherBundle` ready for
:func:`swatplus_builder.weather.writer.write_observed`.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
import random
from collections.abc import Iterable, Sequence

from ..errors import SwatBuilderInputError
from ..types import StationSeries, WeatherBundle, WeatherStation
from .writer import station_name

__all__ = [
    "synthesize",
    "synthesize_station",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesize(
    stations: Iterable[tuple[float, float, float]],
    *,
    start: str,
    n_days: int,
    seed: int = 0,
    variables: Sequence[str] = ("pcp", "tmp", "hmd", "wnd", "slr"),
) -> WeatherBundle:
    """Build a fully-populated :class:`WeatherBundle`.

    Args:
        stations:  Iterable of ``(lat, lon, elev_m)``. Station names are
                   derived via :func:`station_name` so the
                   ``weather_sta_cli`` rows the editor creates later
                   collide deterministically with ours.
        start:     ISO date ``YYYY-MM-DD``.
        n_days:    Number of daily records per station.
        seed:      Base seed. Each station's RNG is seeded with
                   ``hash((seed, name))`` so different runs reproduce
                   exactly while remaining correlated across stations
                   only by design.
        variables: Which variables to emit. Any subset of
                   ``("pcp", "tmp", "hmd", "wnd", "slr")``. ``"tmp"``
                   means *both* tmax and tmin.

    Returns:
        :class:`WeatherBundle` ready to pass to
        :func:`swatplus_builder.weather.writer.write_observed`.

    Raises:
        SwatBuilderInputError: bad date, non-positive ``n_days``, or an
            unknown variable code.
    """
    if n_days < 1:
        raise SwatBuilderInputError(
            f"n_days must be >= 1, got {n_days}", n_days=n_days
        )
    try:
        start_date = _dt.date.fromisoformat(start)
    except ValueError as exc:
        raise SwatBuilderInputError(
            f"start is not an ISO date: {start!r}", start=start
        ) from exc

    allowed = {"pcp", "tmp", "hmd", "wnd", "slr"}
    unknown = set(variables) - allowed
    if unknown:
        raise SwatBuilderInputError(
            f"unknown weather variable codes: {sorted(unknown)}",
            unknown=sorted(unknown),
            allowed=sorted(allowed),
        )

    station_list = list(stations)
    if not station_list:
        raise SwatBuilderInputError(
            "synthesize() needs at least one station", stations=[]
        )

    series_list: list[StationSeries] = [
        synthesize_station(
            lat=lat,
            lon=lon,
            elev=elev,
            start_date=start_date,
            n_days=n_days,
            seed=seed,
            variables=variables,
        )
        for (lat, lon, elev) in station_list
    ]
    return WeatherBundle(stations=series_list, start=start, n_days=n_days)


def synthesize_station(
    *,
    lat: float,
    lon: float,
    elev: float,
    start_date: _dt.date,
    n_days: int,
    seed: int = 0,
    variables: Sequence[str] = ("pcp", "tmp", "hmd", "wnd", "slr"),
) -> StationSeries:
    """Build a :class:`StationSeries` for one station.

    Public because production adapters may want to fill in a single
    station deterministically (e.g. a sanity-check run around a real
    gauge).
    """
    name = station_name(lat, lon)
    station = WeatherStation(name=name, lat=lat, lon=lon, elev=elev)
    rng = _station_rng(seed=seed, name=name)

    pcp = _synth_pcp(start_date, n_days, rng) if "pcp" in variables else None
    tmax = tmin = None
    if "tmp" in variables:
        tmax, tmin = _synth_tmax_tmin(start_date, n_days, rng)
    hmd = _synth_hmd(start_date, n_days, rng) if "hmd" in variables else None
    wnd = _synth_wnd(start_date, n_days, rng) if "wnd" in variables else None
    slr = _synth_slr(start_date, n_days, rng) if "slr" in variables else None

    return StationSeries(
        station=station,
        start=start_date.isoformat(),
        n_days=n_days,
        pcp=pcp,
        tmax=tmax,
        tmin=tmin,
        hmd=hmd,
        wnd=wnd,
        slr=slr,
    )


# ---------------------------------------------------------------------------
# Per-variable generators
# ---------------------------------------------------------------------------


def _station_rng(*, seed: int, name: str) -> random.Random:
    """Per-station deterministic RNG. ``hash()`` is salted per-process, so
    we derive a stable int from SHA-256 to guarantee cross-machine
    reproducibility.
    """
    h = hashlib.sha256(f"{seed}:{name}".encode()).digest()
    seed_int = int.from_bytes(h[:8], "big", signed=False)
    return random.Random(seed_int)


def _annual_phase(day: _dt.date) -> float:
    """Return a value in [0, 1] peaking at day-of-year 200 (mid-July)."""
    doy = day.timetuple().tm_yday
    # Cosine peaking at doy=200, trough at doy=18 (~Jan 18).
    return 0.5 * (1.0 - math.cos(2.0 * math.pi * (doy - 18) / 365.0))


def _synth_pcp(start: _dt.date, n_days: int, rng: random.Random) -> list[float]:
    out: list[float] = []
    day = start
    for _ in range(n_days):
        # ~30 % wet days; on wet days, exponential distribution mean 7 mm.
        if rng.random() < 0.3:
            val = rng.expovariate(1 / 7.0)
        else:
            val = 0.0
        out.append(round(val, 2))
        day += _dt.timedelta(days=1)
    return out


def _synth_tmax_tmin(
    start: _dt.date, n_days: int, rng: random.Random
) -> tuple[list[float], list[float]]:
    tmax: list[float] = []
    tmin: list[float] = []
    day = start
    for _ in range(n_days):
        cycle = _annual_phase(day)  # 0 in winter, 1 in summer
        # Winter tmax min 0 °C, summer tmax max 30 °C; ±3 °C daily noise.
        tx = 0.0 + 30.0 * cycle + rng.uniform(-3.0, 3.0)
        # tmin lags tmax by 10 °C; guarantee strict ordering for the engine.
        tn = tx - 10.0 + rng.uniform(-1.0, 1.0)
        if tn >= tx:
            tn = tx - 1.0
        tmax.append(round(tx, 2))
        tmin.append(round(tn, 2))
        day += _dt.timedelta(days=1)
    return tmax, tmin


def _synth_hmd(start: _dt.date, n_days: int, rng: random.Random) -> list[float]:
    out: list[float] = []
    day = start
    for _ in range(n_days):
        cycle = _annual_phase(day)
        # Winter humid (0.8), summer drier (0.55); ±5 % noise; clamped.
        rh = (0.8 - 0.25 * cycle) + rng.uniform(-0.05, 0.05)
        out.append(round(max(0.40, min(0.95, rh)), 3))
        day += _dt.timedelta(days=1)
    return out


def _synth_wnd(start: _dt.date, n_days: int, rng: random.Random) -> list[float]:
    out: list[float] = []
    day = start
    for _ in range(n_days):
        cycle = _annual_phase(day)
        # Winter ~4 m/s, summer ~2.5 m/s; ±0.5 m/s noise.
        ws = (4.0 - 1.5 * cycle) + rng.uniform(-0.5, 0.5)
        out.append(round(max(0.1, ws), 2))
        day += _dt.timedelta(days=1)
    return out


def _synth_slr(start: _dt.date, n_days: int, rng: random.Random) -> list[float]:
    out: list[float] = []
    day = start
    for _ in range(n_days):
        cycle = _annual_phase(day)
        sr = 3.0 + 22.0 * cycle + rng.uniform(-2.0, 2.0)
        out.append(round(max(0.1, sr), 2))
        day += _dt.timedelta(days=1)
    return out
