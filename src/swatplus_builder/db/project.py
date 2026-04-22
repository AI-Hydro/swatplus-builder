"""Project SQLite creation and ``project_config`` management.

This module is the bridge between the GIS stage and the SWAT+ Editor. It
creates an empty project database with all ``gis_*`` tables declared (per
``db.schema``) and a single ``project_config`` row filled in with the paths
and flags the editor expects.

Typical flow:

1. ``create_project_db(name, workdir, …)`` — returns a path to the new sqlite.
2. GIS writers (``db.writer.write_watershed``, ``db.writer.write_hrus``) fill
   the ``gis_*`` tables.
3. ``mark_gis_ready(path)`` — flips ``delineation_done = hrus_done = 1``.
4. The SWAT+ Editor's ``import_gis`` subprocess reads, expands into model
   tables, and flips ``imported_gis = 1``.
5. The editor's ``write_files`` produces ``TxtInOut/`` on disk.

We deliberately do NOT open the project DB as a long-lived connection —
every function in this module opens and closes its own connection so the
writer is safe to call from multiple threads and so file locks don't leak
into agent sessions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import SwatBuilderInputError, SwatBuilderPipelineError
from . import schema

__all__ = [
    "EDITOR_VERSION",
    "GIS_VERSION",
    "create_project_db",
    "mark_gis_ready",
    "mark_gis_imported",
    "read_project_config",
    "update_project_config",
    "upsert_project_metadata",
]


# Pinned to the vendored commit in src/swatplus_builder/editor/vendored/.
# The SWAT+ Editor writes this string into its own TxtInOut headers; keep in
# sync with editor/vendored/.VENDORED_COMMIT (currently SWAT+ Editor v3.2.2
# @ ed60db068e83602727267e2bffb1b7b6e346726a, released 2026-04-17).
EDITOR_VERSION: str = "3.2.2-dev"

# Format string the editor accepts. We claim QGIS even though we never ran
# QGIS — the editor only uses this for informational logging.
GIS_TYPE: str = "qgis"
GIS_VERSION: str = "3.28"


def create_project_db(
    project_name: str,
    workdir: Path | str,
    *,
    reference_db: Path | str | None = None,
    wgn_db: Path | str | None = None,
    wgn_table_name: str = "wgn_cfsr_world",
    weather_data_format: str = "plus",
    settings: Settings = DEFAULT_SETTINGS,
    overwrite: bool = False,
) -> Path:
    """Create an empty project SQLite file and populate ``project_config``.

    The created file contains:

    - All ``gis_*`` tables as declared in :mod:`swatplus_builder.db.schema`
      (empty — the GIS writer fills them next).
    - Exactly one row in ``project_config`` with the caller-supplied paths,
      ``delineation_done = hrus_done = imported_gis = 0``.

    Args:
        project_name: Short name (e.g. ``"marsh_creek_v1"``). Becomes
            ``<workdir>/<project_name>.sqlite``. Must be a valid filename stem
            (no path separators).
        workdir: Project root directory. Created if missing.
        reference_db: Path to ``swatplus_datasets.sqlite``. If ``None``, we
            use ``settings.reference_db_dir / "swatplus_datasets.sqlite"``.
            The file need not exist yet — the editor only opens it when
            ``import_gis`` runs — but a warning is logged if it's missing.
        wgn_db: Path to ``swatplus_wgn.sqlite``. Resolved same way.
        wgn_table_name: Table within ``wgn_db`` to use as the weather
            generator. Default ``"wgn_cfsr_world"``.
        weather_data_format: One of ``"plus"`` (text TxtInOut), ``"observed"``,
            ``"netcdf"``.
        settings: Runtime overrides. Uses :data:`DEFAULT_SETTINGS` if not set.
        overwrite: If ``True`` and the project file already exists, delete it
            first. If ``False`` and the file exists, raise
            :class:`SwatBuilderInputError`.

    Returns:
        Absolute path to the created ``<workdir>/<project_name>.sqlite``.

    Raises:
        SwatBuilderInputError: ``project_name`` contains path separators, or
            the target file exists and ``overwrite=False``.
        SwatBuilderPipelineError: Schema creation fails (unlikely).
    """
    if "/" in project_name or "\\" in project_name or project_name in (".", ".."):
        raise SwatBuilderInputError(
            "project_name must be a plain filename stem, got "
            f"{project_name!r}",
            project_name=project_name,
        )

    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = workdir / f"{project_name}.sqlite"

    if db_path.exists():
        if not overwrite:
            raise SwatBuilderInputError(
                f"Project DB already exists at {db_path}. "
                "Pass overwrite=True to replace it.",
                db_path=str(db_path),
            )
        db_path.unlink()

    ref_db_path = (
        Path(reference_db).resolve()
        if reference_db is not None
        else (settings.reference_db_dir / "swatplus_datasets.sqlite").resolve()
    )
    wgn_db_path = (
        Path(wgn_db).resolve()
        if wgn_db is not None
        else (settings.reference_db_dir / "swatplus_wgn.sqlite").resolve()
    )

    scenarios_txtinout = workdir / "Scenarios" / "Default" / "TxtInOut"

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        schema.ensure_schema(conn)

        swat_exe = (
            str(settings.swatplus_exe) if settings.swatplus_exe is not None else None
        )
        values: dict[str, object | None] = {
            "id": 1,
            "project_name": project_name,
            "project_directory": str(workdir),
            "editor_version": EDITOR_VERSION,
            "gis_type": GIS_TYPE,
            "gis_version": GIS_VERSION,
            "project_db": str(db_path),
            "reference_db": str(ref_db_path),
            "wgn_db": str(wgn_db_path),
            "wgn_table_name": wgn_table_name,
            "weather_data_dir": str(scenarios_txtinout),
            "weather_data_format": weather_data_format,
            "netcdf_data_file": None,
            "input_files_dir": str(scenarios_txtinout),
            "input_files_last_written": None,
            "swat_last_run": None,
            "swat_exe_filename": swat_exe,
            "delineation_done": 0,
            "hrus_done": 0,
            "soil_table": "SSURGO",
            "soil_layer_table": None,
            "output_last_imported": None,
            "imported_gis": 0,
            "is_lte": 0,
            "use_gwflow": 0,
        }
        missing = set(schema.PROJECT_CONFIG_COLUMNS) - set(values)
        if missing:
            raise SwatBuilderPipelineError(
                "project_config values missing keys declared in schema",
                missing=sorted(missing),
            )
        row = tuple(values[col] for col in schema.PROJECT_CONFIG_COLUMNS)

        with conn:
            conn.execute(schema.PROJECT_CONFIG_INSERT_SQL, row)
    finally:
        conn.close()

    return db_path


def read_project_config(project_db: Path | str) -> dict[str, object]:
    """Return the single ``project_config`` row as a dict.

    Raises :class:`SwatBuilderPipelineError` if the row is missing.
    """
    project_db = Path(project_db)
    conn = sqlite3.connect(str(project_db))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM project_config WHERE id = 1")
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise SwatBuilderPipelineError(
            f"project_config has no row in {project_db}",
            project_db=str(project_db),
        )
    return {k: row[k] for k in row.keys()}


def update_project_config(project_db: Path | str, **fields: object) -> None:
    """Update one or more ``project_config`` fields on the single row.

    Only fields that are actual columns are written; unknown keys raise
    :class:`SwatBuilderInputError`.
    """
    if not fields:
        return
    project_db = Path(project_db)
    # Set of columns update_project_config will accept. Mirrors the schema
    # constant so adding a column in one place is picked up here.
    allowed = set(schema.PROJECT_CONFIG_COLUMNS) - {"id"}
    bad = set(fields) - allowed
    if bad:
        raise SwatBuilderInputError(
            f"Unknown project_config columns: {sorted(bad)}",
            bad_columns=sorted(bad),
        )
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = tuple(fields.values())
    conn = sqlite3.connect(str(project_db))
    try:
        with conn:
            conn.execute(
                f"UPDATE project_config SET {cols} WHERE id = 1",
                values,
            )
    finally:
        conn.close()


def mark_gis_ready(project_db: Path | str) -> None:
    """Set ``delineation_done = hrus_done = 1`` after the GIS writer finishes.

    This is the handoff signal to the SWAT+ Editor's ``import_gis`` step.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    update_project_config(
        project_db,
        delineation_done=1,
        hrus_done=1,
        input_files_last_written=now,
    )


def mark_gis_imported(project_db: Path | str) -> None:
    """Flip ``imported_gis = 1`` after a successful ``swatplus_api import_gis``.

    Called by :mod:`swatplus_builder.editor.api` after the editor subprocess
    exits cleanly. Never called by GIS code directly.
    """
    update_project_config(project_db, imported_gis=1)


def upsert_project_metadata(project_db: Path | str, key: str, value_json: str) -> None:
    """Insert or update a free-form JSON value in project_metadata.

    Useful for tracking pipeline metrics like soil_report along with the project database.
    """
    project_db = Path(project_db)
    conn = sqlite3.connect(str(project_db))
    try:
        with conn:
            conn.execute(schema.PROJECT_METADATA_UPSERT_SQL, (key, value_json))
    finally:
        conn.close()
