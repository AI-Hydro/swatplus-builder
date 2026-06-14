"""Tests for :mod:`swatplus_builder.editor.api`.

Two tiers:

* **Unit** (always run): availability probe, error translation, arg
  construction, default TxtInOut dir resolution. These don't invoke the real
  editor against a real dataset DB — they verify the subprocess wrapper's
  correctness using a deliberately failing invocation.
* **Integration** (``@pytest.mark.slow``, skipped unless
  ``SWATPLUS_DATASETS_DB`` env var points at a real ``swatplus_datasets.sqlite``):
  runs ``setup_project`` + ``write_files`` end-to-end on a tiny synthetic
  watershed and checks that ``TxtInOut/file.cio`` is produced.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_watershed():
    """Minimum two-subbasin GisTables fixture (copy of test_writer's)."""
    from swatplus_builder.types import (
        ChannelRow,
        GisTables,
        HruRow,
        LsuRow,
        PointRow,
        RoutingRow,
        SubbasinRow,
    )

    return GisTables(
        subbasins=[
            SubbasinRow(
                id=1, area=1200.0, slo1=3.5, len1=4500.0, sll=50.0,
                lat=41.10, lon=-77.50, elev=320.0, elevmin=280.0, elevmax=450.0,
            ),
            SubbasinRow(
                id=2, area=800.0, slo1=4.2, len1=3000.0, sll=60.0,
                lat=41.15, lon=-77.55, elev=360.0, elevmin=310.0, elevmax=500.0,
            ),
        ],
        channels=[
            ChannelRow(
                id=1, subbasin=1, areac=2000.0, strahler=2, len2=4200.0,
                slo2=0.8, wid2=12.0, dep2=1.5, elevmin=280.0, elevmax=340.0,
                midlat=41.09, midlon=-77.49,
            ),
            ChannelRow(
                id=2, subbasin=2, areac=800.0, strahler=1, len2=2800.0,
                slo2=1.2, wid2=6.0, dep2=0.9, elevmin=310.0, elevmax=420.0,
                midlat=41.16, midlon=-77.54,
            ),
        ],
        lsus=[
            LsuRow(
                id=101, category=1, channel=1, subbasin=1, area=1200.0,
                slope=3.5, len1=4500.0, csl=0.8, wid1=12.0, dep1=1.5,
                lat=41.10, lon=-77.50, elev=320.0,
            ),
            LsuRow(
                id=102, category=1, channel=2, subbasin=2, area=800.0,
                slope=4.2, len1=3000.0, csl=1.2, wid1=6.0, dep1=0.9,
                lat=41.15, lon=-77.55, elev=360.0,
            ),
        ],
        hrus=[
            HruRow(
                id=1, lsu=101, arsub=1200.0, arlsu=1200.0,
                landuse="FRST", arland=1200.0, soil="SSURGO_A", arso=1200.0,
                slp="0-5", arslp=1200.0, slope=3.5,
                lat=41.10, lon=-77.50, elev=320.0,
            ),
            HruRow(
                id=2, lsu=102, arsub=800.0, arlsu=800.0,
                landuse="AGRL", arland=800.0, soil="SSURGO_B", arso=800.0,
                slp="0-5", arslp=800.0, slope=4.2,
                lat=41.15, lon=-77.55, elev=360.0,
            ),
        ],
        points=[
            PointRow(
                id=1, subbasin=0, ptype="O",
                xpr=600000.0, ypr=4550000.0,
                lat=41.08, lon=-77.48, elev=275.0,
            ),
        ],
        routing=[
            RoutingRow(sourceid=1, sourcecat="HRU", hyd_typ="tot", sinkid=101, sinkcat="LSU", percent=100.0),
            RoutingRow(sourceid=2, sourcecat="HRU", hyd_typ="tot", sinkid=102, sinkcat="LSU", percent=100.0),
            RoutingRow(sourceid=101, sourcecat="LSU", hyd_typ="sur", sinkid=1, sinkcat="CH", percent=100.0),
            RoutingRow(sourceid=101, sourcecat="LSU", hyd_typ="lat", sinkid=1, sinkcat="CH", percent=100.0),
            RoutingRow(sourceid=102, sourcecat="LSU", hyd_typ="sur", sinkid=2, sinkcat="CH", percent=100.0),
            RoutingRow(sourceid=102, sourcecat="LSU", hyd_typ="lat", sinkid=2, sinkcat="CH", percent=100.0),
            RoutingRow(sourceid=2, sourcecat="CH", hyd_typ="tot", sinkid=1, sinkcat="CH", percent=100.0),
            RoutingRow(sourceid=1, sourcecat="CH", hyd_typ="tot", sinkid=1, sinkcat="PT", percent=100.0),
            RoutingRow(sourceid=1, sourcecat="PT", hyd_typ="tot", sinkid=0, sinkcat="X", percent=100.0),
        ],
    )


@pytest.fixture
def populated_project(tmp_path, tiny_watershed):
    """Return a project DB with populated gis_* tables, pointing at a fake
    reference DB path. Useful for unit tests that assert on pre-flight error
    messages without running the editor itself."""
    from swatplus_builder.db.project import create_project_db
    from swatplus_builder.db.writer import write_all

    fake_ref = tmp_path / "fake_datasets.sqlite"
    fake_wgn = tmp_path / "fake_wgn.sqlite"
    db = create_project_db(
        project_name="itest",
        workdir=tmp_path,
        reference_db=fake_ref,
        wgn_db=fake_wgn,
    )
    write_all(db, tiny_watershed)
    return db


# ---------------------------------------------------------------------------
# Availability / metadata
# ---------------------------------------------------------------------------


def test_editor_available_reports_true() -> None:
    from swatplus_builder.editor.api import editor_available

    assert editor_available() is True


def test_vendored_commit_is_pinned_hex() -> None:
    import pytest

    from swatplus_builder.editor.api import vendored_commit

    commit = vendored_commit()
    if commit == "unknown":
        pytest.skip(
            "vendored commit pin unavailable — written by "
            "scripts/vendor_swatplus_editor.sh, not committed to the tree."
        )
    assert len(commit) == 40
    int(commit, 16)  # hex


def test_vendored_dir_exists() -> None:
    from swatplus_builder.editor.api import vendored_dir

    d = vendored_dir()
    assert d.is_dir()
    assert (d / "swatplus_api.py").is_file()


def test_require_available_passes() -> None:
    from swatplus_builder.editor.api import require_available

    require_available()


# ---------------------------------------------------------------------------
# Pre-flight input validation (no subprocess invocation)
# ---------------------------------------------------------------------------


def test_setup_project_rejects_missing_project_db(tmp_path) -> None:
    from swatplus_builder.editor.api import setup_project
    from swatplus_builder.errors import SwatBuilderInputError

    with pytest.raises(SwatBuilderInputError, match="project_db does not exist"):
        setup_project(tmp_path / "nope.sqlite")


def test_setup_project_rejects_missing_datasets_db(populated_project) -> None:
    """The fake reference_db path doesn't point at a real file; setup_project
    must complain *before* launching the subprocess."""
    from swatplus_builder.editor.api import setup_project
    from swatplus_builder.errors import SwatBuilderInputError

    with pytest.raises(SwatBuilderInputError, match="datasets_db"):
        setup_project(populated_project)


def test_seeds_missing_watr_landuse_for_compat(tmp_path) -> None:
    """If GIS HRUs contain WATR and datasets lacks watr, seed a compat row."""
    from swatplus_builder.editor.api import _ensure_datasets_landuse_compat

    project_db = tmp_path / "project.sqlite"
    ds_db = tmp_path / "datasets.sqlite"

    with sqlite3.connect(project_db) as conn:
        conn.execute("CREATE TABLE gis_hrus (id INTEGER PRIMARY KEY, landuse TEXT)")
        conn.execute("INSERT INTO gis_hrus (landuse) VALUES ('WATR')")

    with sqlite3.connect(ds_db) as conn:
        conn.execute(
            "CREATE TABLE plants_plt ("
            "id INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL UNIQUE, "
            "plnt_typ TEXT NOT NULL, "
            "description TEXT)"
        )
        conn.execute(
            "CREATE TABLE urban_urb ("
            "id INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL UNIQUE)"
        )
        conn.execute(
            "INSERT INTO plants_plt (name, plnt_typ, description) "
            "VALUES ('agrl', 'warm_annual', 'agriculture')"
        )

    _ensure_datasets_landuse_compat(project_db=project_db, datasets_db=ds_db)

    with sqlite3.connect(ds_db) as conn:
        (n_watr,) = conn.execute(
            "SELECT COUNT(*) FROM plants_plt WHERE lower(name)='watr'"
        ).fetchone()
    assert n_watr == 1


def test_setup_project_accepts_explicit_datasets_db_path(
    populated_project, tmp_path,
) -> None:
    """If the caller provides an explicit datasets_db that happens to exist
    (even if empty), the pre-flight check passes and we get past the args
    construction. The subprocess will then fail (empty DB isn't a valid
    datasets DB) — but with a editor-level error, not a pre-flight error."""
    from swatplus_builder.editor.api import setup_project
    from swatplus_builder.errors import SwatBuilderExternalError

    fake_ds = tmp_path / "ds.sqlite"
    # Create a plausible but empty sqlite file.
    sqlite3.connect(str(fake_ds)).close()

    with pytest.raises(SwatBuilderExternalError) as excinfo:
        setup_project(
            populated_project,
            datasets_db=fake_ds,
            timeout=60.0,
        )
    # Editor was reached, so command and returncode are present.
    assert "setup_project" in excinfo.value.context.get("action", "")
    assert excinfo.value.context.get("returncode", 0) != 0


def test_import_gis_rejects_missing_project_db(tmp_path) -> None:
    from swatplus_builder.editor.api import import_gis
    from swatplus_builder.errors import SwatBuilderInputError

    with pytest.raises(SwatBuilderInputError):
        import_gis(tmp_path / "nope.sqlite")


def test_import_weather_rejects_missing_project_db(tmp_path) -> None:
    from swatplus_builder.editor.api import import_weather_observed
    from swatplus_builder.errors import SwatBuilderInputError

    with pytest.raises(SwatBuilderInputError, match="project_db does not exist"):
        import_weather_observed(tmp_path / "nope.sqlite", tmp_path)


def test_import_weather_rejects_missing_weather_dir(populated_project, tmp_path) -> None:
    from swatplus_builder.editor.api import import_weather_observed
    from swatplus_builder.errors import SwatBuilderInputError

    with pytest.raises(SwatBuilderInputError, match="weather_data_dir does not exist"):
        import_weather_observed(populated_project, tmp_path / "nope")


def test_import_weather_writes_weather_data_dir_into_config(
    populated_project, tmp_path,
) -> None:
    """When an override is passed, it must be persisted to project_config
    so the editor subprocess (and any subsequent import) sees it."""
    from swatplus_builder.editor.api import import_weather_observed
    from swatplus_builder.errors import SwatBuilderExternalError

    wdir = tmp_path / "wx"
    wdir.mkdir()
    # Subprocess will fail (no .cli files present) — but only *after* the
    # weather_data_dir write has happened.
    with pytest.raises(SwatBuilderExternalError):
        import_weather_observed(populated_project, wdir, timeout=60.0)

    conn = sqlite3.connect(str(populated_project))
    try:
        cur = conn.execute(
            "SELECT weather_data_dir FROM project_config WHERE id = 1"
        )
        (stored,) = cur.fetchone()
    finally:
        conn.close()
    assert Path(stored) == wdir.resolve()


def test_write_files_rejects_missing_project_db(tmp_path) -> None:
    from swatplus_builder.editor.api import write_files
    from swatplus_builder.errors import SwatBuilderInputError

    with pytest.raises(SwatBuilderInputError):
        write_files(tmp_path / "nope.sqlite")


def test_write_files_creates_txtinout_dir(populated_project) -> None:
    """Even if the subprocess fails (empty model tables), the wrapper must
    pre-create the TxtInOut/ dir so the editor has somewhere to write."""
    from swatplus_builder.editor.api import write_files
    from swatplus_builder.errors import SwatBuilderExternalError

    expected_dir = populated_project.parent / "Scenarios" / "Default" / "TxtInOut"
    assert not expected_dir.exists()

    with pytest.raises(SwatBuilderExternalError):
        write_files(populated_project, timeout=60.0)

    assert expected_dir.is_dir()


# ---------------------------------------------------------------------------
# Error translation: run the editor with a bogus project_db that exists but
# is empty; confirm SwatBuilderExternalError carries the editor's traceback.
# ---------------------------------------------------------------------------


def test_editor_nonzero_exit_translates_cleanly(tmp_path) -> None:
    """Create an empty sqlite file and pass it to import_gis — the editor
    will fail because project_config is missing. The wrapper must translate
    that to SwatBuilderExternalError with useful context."""
    from swatplus_builder.editor.api import import_gis
    from swatplus_builder.errors import SwatBuilderExternalError

    bogus = tmp_path / "bogus.sqlite"
    sqlite3.connect(str(bogus)).close()

    with pytest.raises(SwatBuilderExternalError) as excinfo:
        import_gis(bogus, timeout=60.0)

    ctx = excinfo.value.context
    assert ctx["action"] == "import_gis"
    assert ctx["returncode"] != 0
    # The editor's sys.exit message should be in the tail.
    combined = (ctx.get("stdout_tail", "") or "") + (ctx.get("stderr_tail", "") or "")
    assert len(combined) > 0


# ---------------------------------------------------------------------------
# Integration: bootstrap the datasets DB if not already present, then run
# setup_project + write_files end-to-end against our tiny_watershed fixture.
# ---------------------------------------------------------------------------


_DATASETS_DB_ENV = "SWATPLUS_DATASETS_DB"
_SKIP_BOOTSTRAP_ENV = "SWATPLUS_BUILDER_SKIP_BOOTSTRAP"


def _preexisting_datasets_db() -> Path | None:
    raw = os.environ.get(_DATASETS_DB_ENV)
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    return p if p.is_file() else None


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get(_SKIP_BOOTSTRAP_ENV) == "1",
    reason=(
        f"{_SKIP_BOOTSTRAP_ENV}=1 set; skipping the end-to-end editor "
        "integration test (CI toggle for offline envs)."
    ),
)
def test_setup_project_and_write_files_end_to_end(tmp_path, tiny_watershed) -> None:
    """Smallest-possible end-to-end proof: tiny_watershed → project DB →
    setup_project → write_files → readable ``TxtInOut/``.

    This is the guard-rail that breaks loudly the day an editor upgrade
    changes its consumer contract. It does two network-free things when
    the datasets DB is already cached, and one cheap network fetch
    (1.1 MB, SHA-256-pinned) otherwise.
    """
    from swatplus_builder.db.project import create_project_db
    from swatplus_builder.db.seed import seed_minimal_soils
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.editor.api import (
        import_weather_observed,
        setup_project,
        write_files,
    )
    from swatplus_builder.errors import SwatBuilderExternalError
    from swatplus_builder.weather import synthesize, write_observed

    ds_db = _preexisting_datasets_db()
    if ds_db is None:
        from swatplus_builder.config import DEFAULT_SETTINGS, Settings
        from swatplus_builder.ref import ensure_datasets_db

        cache_dir = tmp_path / "ref_cache"
        test_settings = Settings(
            **{**DEFAULT_SETTINGS.model_dump(), "reference_db_dir": cache_dir},
        )
        try:
            ds_db = ensure_datasets_db(settings=test_settings)
        except SwatBuilderExternalError as exc:
            pytest.skip(
                "Could not bootstrap swatplus_datasets.sqlite "
                f"(probably offline): {exc}"
            )
    assert ds_db.is_file()

    db = create_project_db(
        project_name="e2e",
        workdir=tmp_path,
        reference_db=ds_db,
    )
    write_all(db, tiny_watershed)
    seed_minimal_soils(db, {row.soil for row in tiny_watershed.hrus})

    setup_result = setup_project(db, datasets_db=ds_db, timeout=600.0)
    assert setup_result.returncode == 0
    assert setup_result.runtime_seconds > 0
    assert setup_result.extra["datasets_db"] == str(ds_db)

    # Verify import_gis's side effect: gis_hrus → hru_con expansion, and
    # plants copied from the datasets DB.
    conn = sqlite3.connect(str(db))
    try:
        (n_hru_con,) = conn.execute("SELECT COUNT(*) FROM hru_con").fetchone()
        (n_plants,) = conn.execute("SELECT COUNT(*) FROM plants_plt").fetchone()
    finally:
        conn.close()
    assert n_hru_con == len(tiny_watershed.hrus), (
        f"editor should have emitted {len(tiny_watershed.hrus)} hru_con rows, got {n_hru_con}"
    )
    assert n_plants > 0, "editor should have copied plants_plt from datasets DB"

    # Weather: synthesize a tiny 1-year dataset for both subbasin centroids,
    # write it to project_config.weather_data_dir, then let the editor import.
    txt_dir = tmp_path / "Scenarios" / "Default" / "TxtInOut"
    txt_dir.mkdir(parents=True, exist_ok=True)
    weather_bundle = synthesize(
        stations=[
            (row.lat, row.lon, row.elev) for row in tiny_watershed.subbasins
        ],
        start="2015-01-01",
        n_days=365,
        seed=0,
    )
    write_observed(weather_bundle, txt_dir)

    weather_result = import_weather_observed(db, txt_dir, timeout=300.0)
    assert weather_result.returncode == 0

    conn = sqlite3.connect(str(db))
    try:
        (n_weather_files,) = conn.execute(
            "SELECT COUNT(*) FROM weather_file"
        ).fetchone()
        (n_stations,) = conn.execute(
            "SELECT COUNT(*) FROM weather_sta_cli"
        ).fetchone()
        (n_hrus_with_wst,) = conn.execute(
            "SELECT COUNT(*) FROM hru_con WHERE wst_id IS NOT NULL"
        ).fetchone()
    finally:
        conn.close()
    # 2 stations * 5 variables = 10 rows in weather_file.
    assert n_weather_files == 10, f"expected 10 weather_file rows, got {n_weather_files}"
    assert n_stations == 2, f"expected 2 weather_sta_cli rows, got {n_stations}"
    assert n_hrus_with_wst == len(tiny_watershed.hrus), (
        "every HRU must have a nearest weather station matched"
    )

    write_result = write_files(db, timeout=900.0)
    assert write_result.returncode == 0
    assert write_result.txtinout_dir is not None

    # Core artifacts the engine refuses to run without, now including the
    # weather index files we imported above.
    # ``weather-wgn.cli`` is deliberately omitted — WGN import is a separate
    # Phase 2 Step 2 deliverable. The engine tolerates its absence as long
    # as every weather station supplies the observed variables (which ours
    # do via synthesize()).
    required = [
        "file.cio",
        "time.sim",
        "hru.con",
        "object.cnt",
        "plants.plt",
        "weather-sta.cli",
        "pcp.cli",
        "tmp.cli",
        "hmd.cli",
        "wnd.cli",
        "slr.cli",
    ]
    missing = [f for f in required if not (write_result.txtinout_dir / f).is_file()]
    assert not missing, f"write_files missed required artifacts: {missing}"

    # Quick content check: file.cio references object.cnt + the weather index.
    cio_text = (write_result.txtinout_dir / "file.cio").read_text(errors="replace")
    assert "object.cnt" in cio_text, "file.cio must list object.cnt"
    assert "weather-sta.cli" in cio_text, "file.cio must list weather-sta.cli"
