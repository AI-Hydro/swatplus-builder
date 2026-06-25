"""Typed writers for the ``gis_*`` tables.

The public entry point is :func:`write_all`. It takes a typed
:class:`~swatplus_builder.types.GisTables` container (pydantic-validated at
its boundary) and writes every row in a single transaction. Per-table
writers are exposed for testing.

Separation of concerns:

* **Schema** lives in :mod:`swatplus_builder.db.schema` (DDL strings).
* **Row validation** lives in :mod:`swatplus_builder.types` (pydantic models).
* **Referential / cross-table validation** lives here in
  :func:`validate_tables`.

Any rule violation raises
:class:`swatplus_builder.errors.SwatBuilderPipelineError` with a
``.context`` carrying the offending rows/ids. The transaction is rolled
back; the sqlite file is left in its pre-call state.

The writer does **not** know anything about GeoPackages, rasters, or
``WatershedResult`` — those are the GIS stage's job. This keeps the writer
trivially unit-testable with hand-built rows.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from ..errors import SwatBuilderPipelineError
from ..types import (
    AquiferRow,
    ChannelRow,
    DeepAquiferRow,
    GisTables,
    HruRow,
    LsuRow,
    PointRow,
    RoutingRow,
    SubbasinRow,
    WaterRow,
)
from . import schema
from .project import mark_gis_ready

__all__ = [
    "ROUTING_PERCENT_TOLERANCE",
    "validate_tables",
    "write_all",
    "write_aquifers",
    "write_channels",
    "write_deep_aquifers",
    "write_hrus",
    "write_lsus",
    "write_points",
    "write_routing",
    "write_subbasins",
    "write_water",
]


ROUTING_PERCENT_TOLERANCE: float = 0.5
"""Absolute tolerance for ``SUM(percent) == 100`` per routing group."""


# ---- Per-table writers -----------------------------------------------------
#
# Each helper takes an open sqlite3.Connection and a list of pydantic rows,
# and does a single ``executemany`` with the schema's positional INSERT SQL.
# None of them commits — :func:`write_all` owns the transaction.


def write_subbasins(conn: sqlite3.Connection, rows: Iterable[SubbasinRow]) -> int:
    tuples = [
        (
            r.id, r.area, r.slo1, r.len1, r.sll,
            r.lat, r.lon, r.elev, r.elevmin, r.elevmax, r.waterid,
        )
        for r in rows
    ]
    conn.executemany(schema.GIS_SUBBASINS_INSERT_SQL, tuples)
    return len(tuples)


def write_channels(conn: sqlite3.Connection, rows: Iterable[ChannelRow]) -> int:
    tuples = [
        (
            r.id, r.subbasin, r.areac, r.strahler, r.len2, r.slo2,
            r.wid2, r.dep2, r.elevmin, r.elevmax, r.midlat, r.midlon,
        )
        for r in rows
    ]
    conn.executemany(schema.GIS_CHANNELS_INSERT_SQL, tuples)
    return len(tuples)


def write_lsus(conn: sqlite3.Connection, rows: Iterable[LsuRow]) -> int:
    tuples = [
        (
            r.id, r.category, r.channel, r.subbasin, r.area, r.slope,
            r.len1, r.csl, r.wid1, r.dep1, r.lat, r.lon, r.elev,
        )
        for r in rows
    ]
    conn.executemany(schema.GIS_LSUS_INSERT_SQL, tuples)
    return len(tuples)


def write_hrus(conn: sqlite3.Connection, rows: Iterable[HruRow]) -> int:
    tuples = [
        (
            r.id, r.lsu, r.arsub, r.arlsu, r.landuse, r.arland,
            r.soil, r.arso, r.slp, r.arslp, r.slope, r.lat, r.lon, r.elev,
        )
        for r in rows
    ]
    conn.executemany(schema.GIS_HRUS_INSERT_SQL, tuples)
    return len(tuples)


def write_water(conn: sqlite3.Connection, rows: Iterable[WaterRow]) -> int:
    tuples = [
        (
            r.id, r.wtype, r.lsu, r.subbasin, r.area,
            r.xpr, r.ypr, r.lat, r.lon, r.elev,
        )
        for r in rows
    ]
    conn.executemany(schema.GIS_WATER_INSERT_SQL, tuples)
    return len(tuples)


def write_points(conn: sqlite3.Connection, rows: Iterable[PointRow]) -> int:
    tuples = [
        (r.id, r.subbasin, r.ptype, r.xpr, r.ypr, r.lat, r.lon, r.elev)
        for r in rows
    ]
    conn.executemany(schema.GIS_POINTS_INSERT_SQL, tuples)
    return len(tuples)


def write_routing(conn: sqlite3.Connection, rows: Iterable[RoutingRow]) -> int:
    tuples = [
        (r.sourceid, r.sourcecat, r.hyd_typ, r.sinkid, r.sinkcat, r.percent)
        for r in rows
    ]
    conn.executemany(schema.GIS_ROUTING_INSERT_SQL, tuples)
    return len(tuples)


def write_aquifers(conn: sqlite3.Connection, rows: Iterable[AquiferRow]) -> int:
    tuples = [
        (
            r.id, r.category, r.subbasin, r.deep_aquifer,
            r.area, r.lat, r.lon, r.elev,
        )
        for r in rows
    ]
    conn.executemany(schema.GIS_AQUIFERS_INSERT_SQL, tuples)
    return len(tuples)


def write_deep_aquifers(
    conn: sqlite3.Connection, rows: Iterable[DeepAquiferRow]
) -> int:
    tuples = [
        (r.id, r.subbasin, r.area, r.lat, r.lon, r.elev)
        for r in rows
    ]
    conn.executemany(schema.GIS_DEEP_AQUIFERS_INSERT_SQL, tuples)
    return len(tuples)


# ---- Cross-table validation -----------------------------------------------


def validate_tables(tables: GisTables) -> None:
    """Run every cross-row integrity check. Raises on any failure.

    Checks:

    1. **Unique ids** within each of ``subbasins``, ``channels``, ``lsus``,
       ``hrus``, ``water``, ``points``, ``aquifers``, ``deep_aquifers``.
    2. **FK integrity**:

       * every ``channel.subbasin`` is a known subbasin id;
       * every ``lsu.{channel,subbasin}`` resolves;
       * every ``hru.lsu`` resolves;
       * every ``water.{lsu,subbasin}`` resolves (``lsu=0`` is allowed —
         sentinel for "no host LSU");
       * every ``point.subbasin`` resolves (``subbasin=0`` is allowed);
       * every ``aquifer.{subbasin,deep_aquifer}`` resolves.

    3. **Routing** (per ADR-013, :class:`RoutingRow` docstring):

       * at most one row per ``(sourceid, sourcecat, sinkid, sinkcat, hyd_typ)``
         triple;
       * for every ``(sourceid, sourcecat, hyd_typ)`` group,
         ``|SUM(percent) - 100| <= ROUTING_PERCENT_TOLERANCE``;
       * no self-loops (``source == sink``), except the reserved exit
         ``sinkid=0, sinkcat='X'``.

    Raises:
        SwatBuilderPipelineError: first failure; ``.context`` holds details.
    """
    _check_unique_ids(tables)
    _check_foreign_keys(tables)
    _check_routing(tables)


def _check_unique_ids(t: GisTables) -> None:
    for name, rows in (
        ("subbasins", t.subbasins),
        ("channels", t.channels),
        ("lsus", t.lsus),
        ("hrus", t.hrus),
        ("water", t.water),
        ("points", t.points),
        ("aquifers", t.aquifers),
        ("deep_aquifers", t.deep_aquifers),
    ):
        ids = [r.id for r in rows]  # type: ignore[union-attr]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise SwatBuilderPipelineError(
                f"duplicate ids in gis_{name}",
                table=name,
                duplicate_ids=dupes,
            )


def _check_foreign_keys(t: GisTables) -> None:
    sub_ids = {s.id for s in t.subbasins}
    cha_ids = {c.id for c in t.channels}
    lsu_ids = {l.id for l in t.lsus}
    daq_ids = {d.id for d in t.deep_aquifers}

    def _fail(table: str, field: str, row_id: int, bad: int) -> None:
        raise SwatBuilderPipelineError(
            f"gis_{table}.{field}={bad} does not reference any known id",
            table=table,
            field=field,
            row_id=row_id,
            missing_ref=bad,
        )

    for c in t.channels:
        if c.subbasin not in sub_ids:
            _fail("channels", "subbasin", c.id, c.subbasin)

    for lsu in t.lsus:
        if lsu.channel not in cha_ids:
            _fail("lsus", "channel", lsu.id, lsu.channel)
        if lsu.subbasin not in sub_ids:
            _fail("lsus", "subbasin", lsu.id, lsu.subbasin)

    for h in t.hrus:
        if h.lsu not in lsu_ids:
            _fail("hrus", "lsu", h.id, h.lsu)

    for w in t.water:
        if w.lsu != 0 and w.lsu not in lsu_ids:
            _fail("water", "lsu", w.id, w.lsu)
        if w.subbasin not in sub_ids:
            _fail("water", "subbasin", w.id, w.subbasin)

    for p in t.points:
        if p.subbasin != 0 and p.subbasin not in sub_ids:
            _fail("points", "subbasin", p.id, p.subbasin)

    for a in t.aquifers:
        if a.subbasin not in sub_ids:
            _fail("aquifers", "subbasin", a.id, a.subbasin)
        if t.deep_aquifers and a.deep_aquifer not in daq_ids:
            _fail("aquifers", "deep_aquifer", a.id, a.deep_aquifer)

    for d in t.deep_aquifers:
        if d.subbasin not in sub_ids:
            _fail("deep_aquifers", "subbasin", d.id, d.subbasin)


def _check_routing(t: GisTables) -> None:
    if not t.routing:
        return

    # 1) duplicate triples
    seen: set[tuple[int, str, int, str, str | None]] = set()
    for r in t.routing:
        key = (r.sourceid, r.sourcecat, r.sinkid, r.sinkcat, r.hyd_typ)
        if key in seen:
            raise SwatBuilderPipelineError(
                "duplicate routing triple (sourceid, sourcecat, sinkid, "
                "sinkcat, hyd_typ)",
                triple=key,
            )
        seen.add(key)

    # 2) self-loops (except the reserved exit)
    for r in t.routing:
        if r.sourceid == r.sinkid and r.sourcecat == r.sinkcat:
            is_exit = r.sinkid == 0 and r.sinkcat == "X"
            if not is_exit:
                raise SwatBuilderPipelineError(
                    "routing row is a self-loop",
                    row=r.model_dump(),
                )

    # 3) sum-of-percents per (source, hyd_typ)
    groups: dict[tuple[int, str, str | None], float] = defaultdict(float)
    group_counts: dict[tuple[int, str, str | None], int] = defaultdict(int)
    for r in t.routing:
        k = (r.sourceid, r.sourcecat, r.hyd_typ)
        groups[k] += r.percent
        group_counts[k] += 1

    bad = [
        (k, total)
        for k, total in groups.items()
        if abs(total - 100.0) > ROUTING_PERCENT_TOLERANCE
    ]
    if bad:
        details = [
            {
                "sourceid": k[0],
                "sourcecat": k[1],
                "hyd_typ": k[2],
                "sum_percent": round(total, 4),
                "n_rows": group_counts[k],
            }
            for k, total in bad
        ]
        raise SwatBuilderPipelineError(
            "routing groups whose SUM(percent) != 100",
            bad_groups=details,
            tolerance=ROUTING_PERCENT_TOLERANCE,
        )


# ---- Orchestration --------------------------------------------------------


def write_all(
    project_db: Path | str,
    tables: GisTables,
    *,
    validate: bool = True,
    mark_ready: bool = True,
) -> dict[str, int]:
    """Write every ``gis_*`` row in one transaction.

    Args:
        project_db: Path to a project SQLite previously created by
            :func:`swatplus_builder.db.project.create_project_db`.
        tables: Typed rows to insert.
        validate: If ``True`` (default), run :func:`validate_tables` **before**
            writing. Failure aborts without touching the file.
        mark_ready: If ``True`` (default), also flip
            ``project_config.delineation_done = hrus_done = 1`` as part of
            the same SQLite transaction, so partial writes can't leave the
            editor thinking the GIS is ready.

    Returns:
        Dict mapping table name → row count written.

    Raises:
        SwatBuilderPipelineError: validation failed, or a SQL error occurred.
            The transaction is rolled back; no partial rows remain.
    """
    if validate:
        validate_tables(tables)

    db_path = Path(project_db)
    if not db_path.exists():
        raise SwatBuilderPipelineError(
            f"project_db does not exist: {db_path}",
            project_db=str(db_path),
        )

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        # Single atomic transaction.
        try:
            schema.ensure_schema(conn)
            # After ensure_schema (which commits) open a new transaction.
            conn.execute("BEGIN")
            counts = {
                "subbasins": write_subbasins(conn, tables.subbasins),
                "channels": write_channels(conn, tables.channels),
                "lsus": write_lsus(conn, tables.lsus),
                "hrus": write_hrus(conn, tables.hrus),
                "water": write_water(conn, tables.water),
                "points": write_points(conn, tables.points),
                "routing": write_routing(conn, tables.routing),
                "aquifers": write_aquifers(conn, tables.aquifers),
                "deep_aquifers": write_deep_aquifers(conn, tables.deep_aquifers),
            }
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK")
            raise SwatBuilderPipelineError(
                f"sqlite error while writing gis_* tables: {exc}",
                sqlite_error=str(exc),
            ) from exc
    finally:
        conn.close()

    if mark_ready:
        # Separate connection so a failure here doesn't roll back the data
        # writes above.
        mark_gis_ready(db_path)

    return counts
