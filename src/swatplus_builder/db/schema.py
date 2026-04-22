"""Canonical DDL for the SWAT+ project-side ``gis_*`` tables and ``project_config``.

Source of truth: **``QSWATPlus/DBUtils.py`` source code**, *not* the shipped
``QSWATPlusProj.sqlite`` template DB. The template has drifted and is missing
columns added by newer QSWATPlus builds (see ``docs/DECISIONS.md`` ADR-011).

Each constant below preserves the exact column list and ordering QSWATPlus uses
at runtime, so an INSERT that uses positional placeholders will round-trip.
"""

from __future__ import annotations

import sqlite3

# --- project_config (DBUtils.py:3150, _CREATEPROJECTCONFIG) -------------------

# We use a **named-column** INSERT so additive schema changes (e.g. the
# editor's `netcdf_data_file`, `swat_exe_filename`) don't force us to
# re-number positional placeholders throughout the stack. The column
# list below must match the CREATE TABLE above, in the same order.
#
# Column set tracks the editor's Peewee model `database/project/config.py`
# (ADR-014) plus the four QSWATPlus-only fields we still need
# (`delineation_done`, `hrus_done`, `soil_table`, `soil_layer_table`,
# `use_gwflow`). See ADR-015.
PROJECT_CONFIG_COLUMNS: tuple[str, ...] = (
    "id",
    "project_name",
    "project_directory",
    "editor_version",
    "gis_type",
    "gis_version",
    "project_db",
    "reference_db",
    "wgn_db",
    "wgn_table_name",
    "weather_data_dir",
    "weather_data_format",
    "netcdf_data_file",
    "input_files_dir",
    "input_files_last_written",
    "swat_last_run",
    "swat_exe_filename",
    "delineation_done",
    "hrus_done",
    "soil_table",
    "soil_layer_table",
    "output_last_imported",
    "imported_gis",
    "is_lte",
    "use_gwflow",
)

PROJECT_CONFIG_DDL: str = """
CREATE TABLE IF NOT EXISTS project_config (
    id                       INTEGER PRIMARY KEY NOT NULL DEFAULT (1),
    project_name             TEXT,
    project_directory        TEXT,
    editor_version           TEXT,
    gis_type                 TEXT,
    gis_version              TEXT,
    project_db               TEXT,
    reference_db             TEXT,
    wgn_db                   TEXT,
    wgn_table_name           TEXT,
    weather_data_dir         TEXT,
    weather_data_format      TEXT,
    netcdf_data_file         TEXT,
    input_files_dir          TEXT,
    input_files_last_written DATETIME,
    swat_last_run            DATETIME,
    swat_exe_filename        TEXT,
    delineation_done         BOOLEAN DEFAULT (0) NOT NULL,
    hrus_done                BOOLEAN DEFAULT (0) NOT NULL,
    soil_table               TEXT,
    soil_layer_table         TEXT,
    output_last_imported     DATETIME,
    imported_gis             BOOLEAN DEFAULT (0) NOT NULL,
    is_lte                   BOOLEAN DEFAULT (0) NOT NULL,
    use_gwflow               BOOLEAN DEFAULT (0) NOT NULL
);
"""

PROJECT_CONFIG_INSERT_SQL: str = (
    "INSERT INTO project_config ("
    + ",".join(PROJECT_CONFIG_COLUMNS)
    + ") VALUES("
    + ",".join(["?"] * len(PROJECT_CONFIG_COLUMNS))
    + ")"
)

# --- gis_points (DBUtils.py:3034, _POINTSCREATESQL) ---------------------------

GIS_POINTS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_points (
    id       INTEGER NOT NULL,
    subbasin INTEGER,
    ptype    TEXT,
    xpr      REAL,
    ypr      REAL,
    lat      REAL,
    lon      REAL,
    elev     REAL
);
"""

GIS_POINTS_INSERT_SQL: str = (
    "INSERT INTO gis_points VALUES(" + ",".join(["?"] * 8) + ")"
)

# --- gis_channels (DBUtils.py:3049, _CHANNELSCREATESQL) -----------------------

GIS_CHANNELS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_channels (
    id       INTEGER PRIMARY KEY UNIQUE NOT NULL,
    subbasin INTEGER,
    areac    REAL,
    strahler INTEGER,
    len2     REAL,
    slo2     REAL,
    wid2     REAL,
    dep2     REAL,
    elevmin  REAL,
    elevmax  REAL,
    midlat   REAL,
    midlon   REAL
);
"""

GIS_CHANNELS_INSERT_SQL: str = (
    "INSERT INTO gis_channels VALUES(" + ",".join(["?"] * 12) + ")"
)

# --- gis_subbasins (DBUtils.py:3069, _SUBBASINSCREATESQL) ---------------------

GIS_SUBBASINS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_subbasins (
    id       INTEGER PRIMARY KEY UNIQUE NOT NULL,
    area     REAL,
    slo1     REAL,
    len1     REAL,
    sll      REAL,
    lat      REAL,
    lon      REAL,
    elev     REAL,
    elevmin  REAL,
    elevmax  REAL,
    waterid  INTEGER
);
"""

GIS_SUBBASINS_INSERT_SQL: str = (
    "INSERT INTO gis_subbasins VALUES(" + ",".join(["?"] * 11) + ")"
)

# --- gis_lsus (DBUtils.py:3011, _LSUSCREATESQL) -------------------------------

GIS_LSUS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_lsus (
    id       INTEGER PRIMARY KEY UNIQUE NOT NULL,
    category INTEGER,
    channel  INTEGER,
    subbasin INTEGER,
    area     REAL,
    slope    REAL,
    len1     REAL,
    csl      REAL,
    wid1     REAL,
    dep1     REAL,
    lat      REAL,
    lon      REAL,
    elev     REAL
);
"""

GIS_LSUS_INSERT_SQL: str = (
    "INSERT INTO gis_lsus VALUES(" + ",".join(["?"] * 13) + ")"
)

# --- gis_hrus (DBUtils.py:2987, _HRUSCREATESQL) -------------------------------

GIS_HRUS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_hrus (
    id       INTEGER PRIMARY KEY UNIQUE NOT NULL,
    lsu      INTEGER,
    arsub    REAL,
    arlsu    REAL,
    landuse  TEXT,
    arland   REAL,
    soil     TEXT,
    arso     REAL,
    slp      TEXT,
    arslp    REAL,
    slope    REAL,
    lat      REAL,
    lon      REAL,
    elev     REAL
);
"""

GIS_HRUS_INSERT_SQL: str = (
    "INSERT INTO gis_hrus VALUES(" + ",".join(["?"] * 14) + ")"
)

# --- gis_water (DBUtils.py:3090, _WATERCREATESQL) -----------------------------

GIS_WATER_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_water (
    id       INTEGER,
    wtype    TEXT,
    lsu      INTEGER,
    subbasin INTEGER,
    area     REAL,
    xpr      REAL,
    ypr      REAL,
    lat      REAL,
    lon      REAL,
    elev     REAL
);
"""

GIS_WATER_INSERT_SQL: str = (
    "INSERT INTO gis_water VALUES(" + ",".join(["?"] * 10) + ")"
)

# --- gis_routing (DBUtils.py:3108, _ROUTINGCREATESQL) -------------------------

GIS_ROUTING_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_routing (
    sourceid  INTEGER,
    sourcecat TEXT,
    hyd_typ   TEXT,
    sinkid    INTEGER,
    sinkcat   TEXT,
    percent   REAL
);
"""

GIS_ROUTING_INDEX_DDL: str = """
CREATE INDEX IF NOT EXISTS source ON gis_routing (sourceid, sourcecat);
"""
# NOTE: NON-UNIQUE. QSWATPlus's DBUtils.py:3120 uses CREATE INDEX (not UNIQUE)
# because a single (sourceid, sourcecat) routinely appears multiple times —
# e.g. an LSU splits surface runoff into 80% to a channel and 20% to a
# downslope LSU, which is two rows with the same (sourceid='LSU', sourcecat).
# The shipped template DBs use UNIQUE INDEX — that's template drift (ADR-011).

GIS_ROUTING_INSERT_SQL: str = (
    "INSERT INTO gis_routing VALUES(" + ",".join(["?"] * 6) + ")"
)

# --- gis_landexempt / gis_splithrus (DBUtils.py:3130-3148) --------------------

GIS_LANDEXEMPT_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_landexempt (
    landuse TEXT
);
"""

GIS_SPLITHRUS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_splithrus (
    landuse    TEXT,
    sublanduse TEXT,
    percent    REAL
);
"""

# --- gis_elevationbands (from the shipped template; QSWATPlus does not
#     recreate this table, so the template's column names — including the
#     `elevb_frR7` typo — are the contract.)

GIS_ELEVATIONBANDS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_elevationbands (
    subbasin INTEGER PRIMARY KEY UNIQUE NOT NULL,
    elevb1 REAL, elevb2 REAL, elevb3 REAL, elevb4 REAL, elevb5 REAL,
    elevb6 REAL, elevb7 REAL, elevb8 REAL, elevb9 REAL, elevb10 REAL,
    elevb_fr1 REAL, elevb_fr2 REAL, elevb_fr3 REAL, elevb_fr4 REAL,
    elevb_fr5 REAL, elevb_fr6 REAL, elevb_frR7 REAL, elevb_fr8 REAL,
    elevb_fr9 REAL, elevb_fr10 REAL
);
"""

# --- gis_aquifers / gis_deep_aquifers (DBUtils.py:3234, 3250) ----------------
# NOTE: QSWATPlus source contains a typo "REAK" for the `area` column's type.
# SQLite accepts unknown types (dynamic typing), so values still round-trip.
# We mirror the typo to keep byte-for-byte schema parity.

GIS_AQUIFERS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_aquifers (
    id           INTEGER PRIMARY KEY,
    category     INTEGER,
    subbasin     INTEGER,
    deep_aquifer INTEGER,
    area         REAK,
    lat          REAL,
    lon          REAL,
    elev         REAL
);
"""

GIS_DEEP_AQUIFERS_DDL: str = """
CREATE TABLE IF NOT EXISTS gis_deep_aquifers (
    id       INTEGER PRIMARY KEY,
    subbasin INTEGER,
    area     REAK,
    lat      REAL,
    lon      REAL,
    elev     REAL
);
"""

GIS_AQUIFERS_INSERT_SQL: str = (
    "INSERT INTO gis_aquifers VALUES(" + ",".join(["?"] * 8) + ")"
)

GIS_DEEP_AQUIFERS_INSERT_SQL: str = (
    "INSERT INTO gis_deep_aquifers VALUES(" + ",".join(["?"] * 6) + ")"
)

# --- project_metadata --------------------------------------------------------

PROJECT_METADATA_DDL: str = """
CREATE TABLE IF NOT EXISTS project_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT
);
"""

PROJECT_METADATA_UPSERT_SQL: str = """
INSERT INTO project_metadata (key, value)
VALUES (?, ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value;
"""

# --- aggregate order ---------------------------------------------------------

ALL_DDL: tuple[str, ...] = (
    PROJECT_CONFIG_DDL,
    PROJECT_METADATA_DDL,
    GIS_POINTS_DDL,
    GIS_SUBBASINS_DDL,
    GIS_CHANNELS_DDL,
    GIS_LSUS_DDL,
    GIS_HRUS_DDL,
    GIS_WATER_DDL,
    GIS_AQUIFERS_DDL,
    GIS_DEEP_AQUIFERS_DDL,
    GIS_ROUTING_DDL,
    GIS_ROUTING_INDEX_DDL,
    GIS_ELEVATIONBANDS_DDL,
    GIS_LANDEXEMPT_DDL,
    GIS_SPLITHRUS_DDL,
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create any missing ``gis_*`` tables in ``conn``. Idempotent.

    Uses ``CREATE TABLE IF NOT EXISTS`` so calling twice is a no-op. Does NOT
    drop or migrate existing tables — if your pre-existing sqlite has a drifted
    schema (e.g. from an old ``QSWATPlusProj.sqlite`` template), drop the file
    first.
    """
    with conn:
        for stmt in ALL_DDL:
            if stmt.strip():
                conn.executescript(stmt)
