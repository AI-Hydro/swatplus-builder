"""Driver for the vendored SWAT+ Editor ``swatplus_api.py``.

This module is the **only** place in the package that knows how to spawn the
SWAT+ Editor. Everything else talks to these functions.

Design:

* **Subprocess mode.** We run the vendored ``swatplus_api.py`` in a child
  Python interpreter. Isolation means an editor crash can't take down the
  calling agent, and any stray ``sys.exit`` the editor does is caught as a
  non-zero return code.
* **Same interpreter, isolated sys.path.** The child uses ``sys.executable``
  so it has our installed ``peewee`` etc. We prepend the vendored directory
  to ``PYTHONPATH`` so the editor's ``from database.project import ...``
  imports resolve, without polluting our own namespace.
* **CWD = vendored dir.** The editor uses a mix of absolute paths (we pass
  those in as args) and relative paths (it sometimes writes logs next to
  itself). Running in the vendored dir avoids surprises.
* **Typed result.** Every call returns an
  :class:`EditorResult` that carries stdout/stderr (truncated), runtime,
  and the arg list. Agents can inspect it without string-parsing.
* **Failures translate to** :class:`~swatplus_builder.errors.SwatBuilderExternalError`
  with the last ~2 KB of stderr and the full command line in ``.context``
  for triage.

Typical flow for an agent:

.. code-block:: python

    from swatplus_builder.db.project import create_project_db
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.editor.api import setup_project, write_files

    db = create_project_db("hello", workdir="/tmp/hello",
                           reference_db="/data/swatplus_datasets.sqlite",
                           wgn_db="/data/swatplus_wgn.sqlite")
    write_all(db, tables)          # gis_* rows
    setup_project(db)              # model tables + auto import_gis
    result = write_files(db)       # TxtInOut/ on disk
    assert result.txtinout_dir.is_dir()
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import SwatBuilderExternalError, SwatBuilderInputError

__all__ = [
    "EditorResult",
    "VENDORED_EDITOR_VERSION",
    "editor_available",
    "import_gis",
    "import_weather_observed",
    "require_available",
    "setup_project",
    "vendored_commit",
    "vendored_dir",
    "write_files",
]


_VENDORED_DIR: Path = Path(__file__).parent / "vendored"
_API_ENTRY: Path = _VENDORED_DIR / "swatplus_api.py"
_STDERR_TAIL_BYTES: int = 4000
_STDOUT_TAIL_BYTES: int = 4000

# Version of the vendored SWAT+ Editor tag (see .VENDORED_COMMIT for the
# exact upstream SHA).  This is the upstream release string, *not* our
# package version.  Kept as a module constant so tests can assert against
# it when the vendor script bumps the tag.
VENDORED_EDITOR_VERSION: str = "3.2.2"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EditorResult:
    """Outcome of one vendored-editor subprocess invocation.

    ``stdout`` and ``stderr`` are truncated to the last
    :data:`_STDOUT_TAIL_BYTES` / :data:`_STDERR_TAIL_BYTES` respectively —
    the editor emits progress lines for every table which would otherwise
    overwhelm agent context windows. The full output is discarded; if you
    need it, set ``settings.log_level='DEBUG'`` to re-run with verbose
    tee-to-disk (not implemented in Phase 1).
    """

    action: str
    args: tuple[str, ...]
    returncode: int
    runtime_seconds: float
    stdout: str
    stderr: str
    project_db: Path
    txtinout_dir: Path | None = None
    extra: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Availability helpers
# ---------------------------------------------------------------------------


def vendored_dir() -> Path:
    """Return the absolute path to the vendored editor source tree."""
    return _VENDORED_DIR


def vendored_commit() -> str:
    """Return the pinned upstream commit of the vendored editor (or ``"unknown"``)."""
    pin = _VENDORED_DIR / ".VENDORED_COMMIT"
    if pin.exists():
        return pin.read_text(encoding="utf-8").strip()
    return "unknown"


def editor_available() -> bool:
    """Return ``True`` iff the vendored editor files and peewee are importable."""
    if not _API_ENTRY.exists():
        return False
    try:
        import peewee  # noqa: F401
    except ImportError:
        return False
    return True


def require_available() -> None:
    """Raise :class:`SwatBuilderExternalError` if the editor can't run.

    Agents can call this before building anything expensive to fail fast with
    an actionable message.
    """
    if not _API_ENTRY.exists():
        raise SwatBuilderExternalError(
            "Vendored SWAT+ Editor is missing. Run "
            "scripts/vendor_swatplus_editor.sh <commit_sha>.",
            expected_path=str(_API_ENTRY),
        )
    try:
        import peewee  # noqa: F401
    except ImportError as exc:
        raise SwatBuilderExternalError(
            "The 'peewee' runtime dependency is not installed. "
            "Run: pip install swatplus-builder  (or: pip install peewee).",
            missing_module="peewee",
        ) from exc


# ---------------------------------------------------------------------------
# Subprocess core
# ---------------------------------------------------------------------------


def _build_env() -> dict[str, str]:
    """Return an environment for the child that can import the vendored editor."""
    env = dict(os.environ)
    # Prepend the vendored directory so the editor's imports resolve. Do NOT
    # also add our own src/ dir; we want strict one-way isolation.
    existing = env.get("PYTHONPATH", "")
    parts = [str(_VENDORED_DIR)]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    # Unbuffered, so progress lines stream instead of being lost on crash.
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _run(
    action: str,
    extra_args: Sequence[str],
    *,
    project_db: Path,
    settings: Settings,
    timeout: float | None,
    txtinout_dir: Path | None = None,
    extra: dict[str, str] | None = None,
) -> EditorResult:
    """Core subprocess invocation. All helpers below funnel through here."""
    require_available()

    cmd = [sys.executable, str(_API_ENTRY), action, *extra_args]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(_VENDORED_DIR),
            env=_build_env(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SwatBuilderExternalError(
            f"swatplus_api.py {action!r} timed out after {timeout}s",
            cmd=cmd,
            action=action,
            timeout_s=timeout,
        ) from exc
    elapsed = time.monotonic() - start

    stdout_tail = (proc.stdout or "")[-_STDOUT_TAIL_BYTES:]
    stderr_tail = (proc.stderr or "")[-_STDERR_TAIL_BYTES:]

    if proc.returncode != 0:
        raise SwatBuilderExternalError(
            f"swatplus_api.py {action!r} exited {proc.returncode}",
            cmd=cmd,
            action=action,
            returncode=proc.returncode,
            runtime_seconds=round(elapsed, 3),
            stderr_tail=stderr_tail,
            stdout_tail=stdout_tail,
        )

    return EditorResult(
        action=action,
        args=tuple(extra_args),
        returncode=0,
        runtime_seconds=round(elapsed, 3),
        stdout=stdout_tail,
        stderr=stderr_tail,
        project_db=project_db,
        txtinout_dir=txtinout_dir,
        extra=dict(extra or {}),
    )


# ---------------------------------------------------------------------------
# Public actions
# ---------------------------------------------------------------------------


def setup_project(
    project_db: Path | str,
    *,
    datasets_db: Path | str | None = None,
    editor_version: str | None = None,
    project_name: str | None = None,
    constant_ps: bool = False,
    is_lte: bool = False,
    project_description: str | None = None,
    timeout: float | None = 600.0,
    settings: Settings = DEFAULT_SETTINGS,
) -> EditorResult:
    """Run the editor's ``setup_project`` action on a project DB we created.

    ``setup_project`` does three things in one shot:

    1. Creates all SWAT+ model tables (``connect.*``, ``channel.*``,
       ``hru.*``, ``aquifer.*``, etc.) via peewee ``create_tables(safe=True)``.
       Tables that already exist (our ``gis_*``) are left alone.
    2. Copies default rows from ``reference_db`` (a.k.a. datasets DB) into
       the project: plants, soils, urban, fertilizer, etc.
    3. If the project DB already exists (it does — we created it), **auto-runs
       ``import_gis``** to expand our populated ``gis_*`` into the
       ``*_con`` connection tables.

    Args:
        project_db: Path to the sqlite produced by
            :func:`swatplus_builder.db.project.create_project_db`. Must
            contain a populated ``project_config`` row and non-empty
            ``gis_subbasins`` (otherwise import_gis silently no-ops).
        datasets_db: Full path to ``swatplus_datasets.sqlite``. If ``None``,
            we read it from the ``project_config.reference_db`` column, which
            is what ``create_project_db`` writes. Must exist on disk.
        editor_version: String like ``"3.0.0"`` recorded in the project
            metadata. Defaults to the pinned
            :func:`vendored_commit()` prefix.
        project_name: If ``None``, read from ``project_config``.
        constant_ps: Passed as ``--constant_ps y/n``. Default ``False``.
        is_lte: ``True`` to build a SWAT+ LTE project.
        project_description: Free-text description stored in the DB.
        timeout: Seconds. ``None`` = wait forever.
        settings: Runtime overrides.

    Returns:
        :class:`EditorResult`.

    Raises:
        SwatBuilderInputError: ``project_db`` doesn't exist, or
            ``datasets_db`` can't be resolved.
        SwatBuilderExternalError: editor exited non-zero or timed out.
    """
    project_db = Path(project_db).resolve()
    if not project_db.exists():
        raise SwatBuilderInputError(
            f"project_db does not exist: {project_db}",
            project_db=str(project_db),
        )

    if datasets_db is None:
        datasets_db_path = _read_reference_db(project_db)
    else:
        datasets_db_path = Path(datasets_db).resolve()
    if not datasets_db_path.exists():
        raise SwatBuilderInputError(
            "datasets_db (SWAT+ reference sqlite) not found. Either pass "
            "datasets_db=<path> or ensure project_config.reference_db "
            "points at an existing file. Download it with `swat init` "
            "when that CLI lands.",
            datasets_db=str(datasets_db_path),
        )

    ev = editor_version or _default_editor_version()

    # The vendored editor only rebuilds GIS-derived connect/object rows when
    # `project_config.imported_gis = 0`. If callers switch mode (LTE <-> standard)
    # without clearing that flag, the DB can retain stale object families
    # (e.g., chandeg_* while is_lte=0), which yields disconnected runtime routing.
    current_is_lte_raw = _read_project_config_field(project_db, "is_lte")
    current_imported_raw = _read_project_config_field(project_db, "imported_gis")
    if current_is_lte_raw is not None and current_imported_raw is not None:
        try:
            current_is_lte = int(str(current_is_lte_raw)) == 1
            current_imported = int(str(current_imported_raw)) == 1
        except (TypeError, ValueError):
            current_is_lte = is_lte
            current_imported = False
        if current_imported and current_is_lte != is_lte:
            _set_project_config_field(project_db, "imported_gis", "0")

    # When --datasets_db_file is passed, the editor skips the code path that
    # reads project_name from project_config (see vendored
    # actions/setup_project.py:44-52, compared with the `do_gis` branch at
    # line 62). As a result, Object_cnt.get_or_create_default(project_name=None)
    # fails with "NOT NULL constraint failed: object_cnt.name". We side-step
    # that by always passing --project_name, sourced from project_config when
    # the caller didn't supply one.
    pname = project_name or _read_project_config_field(project_db, "project_name")
    pdesc = project_description or pname

    args: list[str] = [
        f"--project_db_file={project_db}",
        f"--datasets_db_file={datasets_db_path}",
        f"--editor_version={ev}",
        f"--constant_ps={'y' if constant_ps else 'n'}",
        f"--is_lte={'y' if is_lte else 'n'}",
    ]
    if pname:
        args.append(f"--project_name={pname}")
    if pdesc:
        args.append(f"--project_description={pdesc}")

    return _run(
        "setup_project",
        args,
        project_db=project_db,
        settings=settings,
        timeout=timeout,
        extra={"datasets_db": str(datasets_db_path), "editor_version": ev},
    )


def import_gis(
    project_db: Path | str,
    *,
    delete_existing: bool = False,
    timeout: float | None = 600.0,
    settings: Settings = DEFAULT_SETTINGS,
) -> EditorResult:
    """Run the editor's ``import_gis`` action.

    Usually redundant — :func:`setup_project` auto-runs it — but useful for
    **re-imports** after editing the ``gis_*`` tables in place.

    Args:
        project_db: Path to the project sqlite. Must already have model
            tables (i.e. :func:`setup_project` has run at least once).
        delete_existing: If ``True``, the editor first deletes the existing
            model rows derived from GIS. Required when re-running after a
            ``gis_*`` edit; the editor refuses otherwise.
        timeout: Seconds.
        settings: Runtime overrides.

    Returns:
        :class:`EditorResult`.
    """
    project_db = Path(project_db).resolve()
    if not project_db.exists():
        raise SwatBuilderInputError(
            f"project_db does not exist: {project_db}",
            project_db=str(project_db),
        )
    return _run(
        "import_gis",
        [
            f"--project_db_file={project_db}",
            f"--delete_existing={'y' if delete_existing else 'n'}",
        ],
        project_db=project_db,
        settings=settings,
        timeout=timeout,
    )


def import_weather_observed(
    project_db: Path | str,
    weather_data_dir: Path | str | None = None,
    *,
    delete_existing: bool = True,
    create_stations: bool = True,
    timeout: float | None = 600.0,
    settings: Settings = DEFAULT_SETTINGS,
) -> EditorResult:
    """Run the editor's ``import_weather --import_type=observed`` action.

    Scans ``project_config.weather_data_dir`` (or the explicit override) for
    ``pcp.cli`` / ``tmp.cli`` / ``hmd.cli`` / ``wnd.cli`` / ``slr.cli`` index
    files — exactly what :func:`swatplus_builder.weather.writer.write_observed`
    produces — and populates the project DB's ``weather_file`` and (if
    ``create_stations``) ``weather_sta_cli`` tables. Also updates
    ``time_sim`` to the common intersection of all station date ranges.

    Run this **after** :func:`setup_project` (so the weather tables exist)
    and **before** :func:`write_files` (so ``hru.con`` / ``channel.con``
    know which stations to reference).

    Args:
        project_db: Path to the project sqlite.
        weather_data_dir: Override ``project_config.weather_data_dir`` for
            this call only. We write the override back to the table so the
            editor's next call (and our own re-import) sees it. ``None``
            means "trust whatever is already there".
        delete_existing: If ``True``, the editor first clears existing
            ``weather_file`` + ``weather_sta_cli`` rows. Default ``True``
            because our pipeline always rewrites weather from scratch.
        create_stations: If ``True``, the editor creates
            ``weather_sta_cli`` rows and matches stations to each
            connection table (HRUs, channels, aquifers, …). Default
            ``True``.
        timeout: Seconds.
        settings: Runtime overrides.

    Returns:
        :class:`EditorResult`.
    """
    project_db = Path(project_db).resolve()
    if not project_db.exists():
        raise SwatBuilderInputError(
            f"project_db does not exist: {project_db}",
            project_db=str(project_db),
        )

    if weather_data_dir is not None:
        wdir = Path(weather_data_dir).expanduser().resolve()
        if not wdir.is_dir():
            raise SwatBuilderInputError(
                f"weather_data_dir does not exist: {wdir}",
                weather_data_dir=str(wdir),
            )
        _set_project_config_field(project_db, "weather_data_dir", str(wdir))
    else:
        current = _read_project_config_field(project_db, "weather_data_dir")
        if not current:
            raise SwatBuilderInputError(
                "project_config.weather_data_dir is unset and no override "
                "was provided.",
                project_db=str(project_db),
            )

    return _run(
        "import_weather",
        [
            f"--project_db_file={project_db}",
            "--import_type=observed",
            f"--delete_existing={'y' if delete_existing else 'n'}",
            f"--create_stations={'y' if create_stations else 'n'}",
        ],
        project_db=project_db,
        settings=settings,
        timeout=timeout,
        extra={"import_type": "observed"},
    )


def write_files(
    project_db: Path | str,
    *,
    input_files_dir: Path | str | None = None,
    swat_version: str | None = None,
    ignore_files: Sequence[str] | None = None,
    ignore_cio_files: Sequence[str] | None = None,
    custom_cio_files: Sequence[str] | None = None,
    timeout: float | None = 900.0,
    settings: Settings = DEFAULT_SETTINGS,
) -> EditorResult:
    """Run the editor's ``write_files`` action.

    Produces the ``TxtInOut/`` directory of plain-text SWAT+ inputs.

    Args:
        project_db: Project sqlite. ``setup_project`` must have run.
        input_files_dir: Where to write. If ``None``, the editor uses
            ``project_config.input_files_dir`` (our
            ``create_project_db`` sets this to
            ``<workdir>/Scenarios/Default/TxtInOut``).
        swat_version: Reported in ``file.cio`` headers. If ``None``, the
            editor uses its internal default.
        ignore_files: File names the editor should skip writing.
        ignore_cio_files: File names to omit from ``file.cio``.
        custom_cio_files: User-provided file names to add to ``file.cio``.
        timeout: Seconds.
        settings: Runtime overrides.

    Returns:
        :class:`EditorResult` with ``txtinout_dir`` populated.
    """
    project_db = Path(project_db).resolve()
    if not project_db.exists():
        raise SwatBuilderInputError(
            f"project_db does not exist: {project_db}",
            project_db=str(project_db),
        )

    txtinout_dir: Path
    if input_files_dir is None:
        txtinout_dir = Path(
            _read_project_config_field(project_db, "input_files_dir")
            or _default_txtinout_dir(project_db)
        )
    else:
        txtinout_dir = Path(input_files_dir).resolve()
    txtinout_dir.mkdir(parents=True, exist_ok=True)

    args: list[str] = [
        f"--project_db_file={project_db}",
        f"--input_files_dir={txtinout_dir}",
    ]
    if swat_version:
        args.append(f"--swat_version={swat_version}")
    if ignore_files:
        args.append(f"--ignore_files={','.join(ignore_files)}")
    if ignore_cio_files:
        args.append(f"--ignore_cio_files={','.join(ignore_cio_files)}")
    if custom_cio_files:
        args.append(f"--custom_cio_files={','.join(custom_cio_files)}")

    return _run(
        "write_files",
        args,
        project_db=project_db,
        settings=settings,
        timeout=timeout,
        txtinout_dir=txtinout_dir,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_reference_db(project_db: Path) -> Path:
    """Return ``project_config.reference_db`` as an absolute path."""
    raw = _read_project_config_field(project_db, "reference_db")
    if not raw:
        raise SwatBuilderInputError(
            "project_config.reference_db is empty; cannot find datasets DB.",
            project_db=str(project_db),
        )
    p = Path(raw)
    if not p.is_absolute():
        # editor stores it relative to the project_db's parent.
        p = (project_db.parent / p).resolve()
    return p


def _read_project_config_field(project_db: Path, field: str) -> str | None:
    import sqlite3

    conn = sqlite3.connect(str(project_db))
    try:
        cur = conn.execute(f"SELECT {field} FROM project_config WHERE id = 1")
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _set_project_config_field(project_db: Path, field: str, value: str) -> None:
    """Update a single ``project_config`` column on row ``id=1``.

    Guarded against SQL injection in ``field`` via an allow-list — we only
    accept columns declared in :data:`db.schema.PROJECT_CONFIG_COLUMNS`.
    """
    import sqlite3

    from ..db import schema

    if field not in schema.PROJECT_CONFIG_COLUMNS:
        raise SwatBuilderInputError(
            f"unknown project_config field {field!r}", field=field
        )

    conn = sqlite3.connect(str(project_db))
    try:
        with conn:
            conn.execute(
                f"UPDATE project_config SET {field} = ? WHERE id = 1",
                (value,),
            )
    finally:
        conn.close()


def _default_txtinout_dir(project_db: Path) -> str:
    return str(project_db.parent / "Scenarios" / "Default" / "TxtInOut")


def _default_editor_version() -> str:
    commit = vendored_commit()
    if commit != "unknown" and len(commit) >= 7:
        return f"{VENDORED_EDITOR_VERSION}+{commit[:7]}"
    return f"{VENDORED_EDITOR_VERSION}-dev"
