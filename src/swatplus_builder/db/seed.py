"""Tiny project-DB seed helpers for tests and toy pipelines.

The editor's ``import_gis`` cross-checks every ``gis_hrus.soil`` against the
project's ``soils_sol`` table and raises ``ValueError("Soil ... does not
exist in your soils_sol table")`` if any are missing. Real pipelines
populate ``soils_sol`` via :mod:`swatplus_builder.soil` (see
:func:`~swatplus_builder.soil.writer.write_soils` /
:func:`~swatplus_builder.soil.gnatsgo.fetch_gnatsgo_profiles`); our
synthetic ``tiny_watershed`` fixture only needs a three-line stand-in.

This module is intentionally narrow. It pre-creates the two soil tables
with the editor's peewee-compatible DDL and inserts one generic row per
distinct soil name, so the editor's ``create_tables(safe=True)`` call
leaves our rows alone during :func:`~swatplus_builder.editor.api.setup_project`.

**Deprecation path** (ADR-017 + ADR-022): for any non-test pipeline, use
:func:`~swatplus_builder.soil.writer.write_soils` — it accepts the same
sqlite DB and is idempotent, so calling it after ``seed_minimal_soils``
overwrites the placeholder rows in place.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

__all__ = [
    "SOILS_SOL_DDL",
    "SOILS_SOL_LAYER_DDL",
    "seed_minimal_soils",
]


SOILS_SOL_DDL: str = """
CREATE TABLE IF NOT EXISTS soils_sol (
    id          INTEGER NOT NULL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL UNIQUE,
    hyd_grp     VARCHAR(255) NOT NULL,
    dp_tot      REAL NOT NULL,
    anion_excl  REAL NOT NULL,
    perc_crk    REAL NOT NULL,
    texture     VARCHAR(255),
    description TEXT
);
"""

SOILS_SOL_LAYER_DDL: str = """
CREATE TABLE IF NOT EXISTS soils_sol_layer (
    id         INTEGER NOT NULL PRIMARY KEY,
    soil_id    INTEGER NOT NULL REFERENCES soils_sol(id) ON DELETE CASCADE,
    layer_num  INTEGER NOT NULL,
    dp         REAL NOT NULL,
    bd         REAL NOT NULL,
    awc        REAL NOT NULL,
    soil_k     REAL NOT NULL,
    carbon     REAL NOT NULL,
    clay       REAL NOT NULL,
    silt       REAL NOT NULL,
    sand       REAL NOT NULL,
    rock       REAL NOT NULL,
    alb        REAL NOT NULL,
    usle_k     REAL NOT NULL,
    ec         REAL NOT NULL,
    caco3      REAL,
    ph         REAL
);
CREATE INDEX IF NOT EXISTS soils_sol_layer_soil_id
    ON soils_sol_layer (soil_id);
"""


def seed_minimal_soils(
    project_db: Path | str,
    soil_names: Iterable[str],
    *,
    hyd_grp: str = "B",
) -> int:
    """Ensure every soil in ``soil_names`` has a row in ``soils_sol``.

    Creates the two soil tables if they don't exist (safe to call before
    or after ``setup_project`` — peewee's ``create_tables(safe=True)``
    is a no-op on existing tables). Upserts one generic layer per soil
    into ``soils_sol_layer``.

    The values are deliberately conservative defaults: a loam-like soil,
    single 1000-mm layer, hydrological group B. They let ``import_gis``
    pass its cross-check and ``write_files`` produce valid .sol outputs.
    Realistic values require a proper soils adapter (out of scope here).

    Args:
        project_db: Path to a project sqlite created by
            :func:`swatplus_builder.db.project.create_project_db`.
        soil_names: Iterable of soil codes to seed (e.g. from the
            ``soil`` column of ``gis_hrus``). Duplicates are ignored.
        hyd_grp: Hydrological group code (``"A".."D"``). Applied to
            every seeded soil.

    Returns:
        Number of new rows inserted into ``soils_sol`` (0 if every name
        already existed).
    """
    unique = sorted({s for s in soil_names if s})
    if not unique:
        return 0

    conn = sqlite3.connect(str(project_db))
    try:
        conn.executescript(SOILS_SOL_DDL + SOILS_SOL_LAYER_DDL)
        inserted = 0
        with conn:
            for name in unique:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO soils_sol "
                    "(name, hyd_grp, dp_tot, anion_excl, perc_crk, texture, description) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, hyd_grp, 1000.0, 0.5, 0.0, "loam", "placeholder seed"),
                )
                if cur.rowcount:
                    inserted += 1
                    soil_id = cur.lastrowid
                    conn.execute(
                        "INSERT INTO soils_sol_layer "
                        "(soil_id, layer_num, dp, bd, awc, soil_k, carbon, "
                        " clay, silt, sand, rock, alb, usle_k, ec, caco3, ph) "
                        "VALUES (?, 1, 1000.0, 1.4, 0.15, 10.0, 1.0, "
                        "        20.0, 40.0, 40.0, 2.0, 0.13, 0.2, 0.0, 0.0, 6.5)",
                        (soil_id,),
                    )
        return inserted
    finally:
        conn.close()
