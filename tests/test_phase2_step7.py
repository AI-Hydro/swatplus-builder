"""Phase 2 Step 7 — first ``TxtInOut/`` from pure-Python inputs.

Tests the full pipeline:

    GisTables (LTE-compatible routing)
        → create_project_db + write_all + seed_minimal_soils
        → create_mock_datasets_db
        → editor.api.setup_project(is_lte=True)   [auto-runs import_gis]
        → editor.api.write_files
        → TxtInOut/file.cio ✓

All tests here use :func:`swatplus_builder.db.mock_datasets.create_mock_datasets_db`
so **no network access and no pre-downloaded reference DB** is required.

The tests are marked ``@pytest.mark.slow`` because they spawn two subprocesses
(mock-DB creation + editor invocation), each under 30 s on a laptop.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lte_datasets_db(tmp_path_factory) -> Path:
    """Module-scoped mock datasets DB seeded for FRST + AGRR landuses."""
    from swatplus_builder.db.mock_datasets import create_mock_datasets_db

    db = create_mock_datasets_db(
        tmp_path_factory.mktemp("ds") / "mock_datasets.sqlite",
        landuses=["frst", "agrr"],
    )
    return db


@pytest.fixture()
def lte_project(tmp_path, lte_datasets_db):
    """Project DB with gis_* tables and seeded soils, ready for setup_project."""
    from swatplus_builder.db.project import create_project_db
    from swatplus_builder.db.seed import seed_minimal_soils
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.types import (
        AquiferRow,
        ChannelRow,
        DeepAquiferRow,
        GisTables,
        HruRow,
        LsuRow,
        PointRow,
        RoutingRow,
        SubbasinRow,
    )

    # Two-subbasin watershed with HRU→CH routing (LTE-compatible).
    tables = GisTables(
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
                id=1, category=1, channel=1, subbasin=1, area=1200.0,
                slope=3.5, len1=4500.0, csl=0.8, wid1=12.0, dep1=1.5,
                lat=41.10, lon=-77.50, elev=320.0,
            ),
            LsuRow(
                id=2, category=1, channel=2, subbasin=2, area=800.0,
                slope=4.2, len1=3000.0, csl=1.2, wid1=6.0, dep1=0.9,
                lat=41.15, lon=-77.55, elev=360.0,
            ),
        ],
        hrus=[
            HruRow(
                id=1, lsu=1, arsub=1200.0, arlsu=1200.0,
                landuse="frst", arland=1200.0, soil="test_soil_a", arso=1200.0,
                slp="0-5", arslp=1200.0, slope=3.5,
                lat=41.10, lon=-77.50, elev=320.0,
            ),
            HruRow(
                id=2, lsu=2, arsub=800.0, arlsu=800.0,
                landuse="agrr", arland=800.0, soil="test_soil_b", arso=800.0,
                slp="0-5", arslp=800.0, slope=4.2,
                lat=41.15, lon=-77.55, elev=360.0,
            ),
        ],
        aquifers=[
            AquiferRow(id=1, category=1, deep_aquifer=1, subbasin=1, area=1200.0,
                       lat=41.10, lon=-77.50, elev=310.0),
            AquiferRow(id=2, category=1, deep_aquifer=2, subbasin=2, area=800.0,
                       lat=41.15, lon=-77.55, elev=350.0),
        ],
        deep_aquifers=[
            DeepAquiferRow(id=1, subbasin=1, area=1200.0, lat=41.10, lon=-77.50, elev=200.0),
            DeepAquiferRow(id=2, subbasin=2, area=800.0, lat=41.15, lon=-77.55, elev=230.0),
        ],
        points=[
            PointRow(
                id=1, subbasin=0, ptype="O",
                xpr=600000.0, ypr=4550000.0,
                lat=41.08, lon=-77.48, elev=275.0,
            ),
        ],
        # LTE-compatible routing: HRU→CH directly (no LSU layer)
        routing=[
            # HRU → CH
            RoutingRow(sourceid=1, sourcecat="HRU", hyd_typ="tot",
                       sinkid=1, sinkcat="CH", percent=100.0),
            RoutingRow(sourceid=2, sourcecat="HRU", hyd_typ="tot",
                       sinkid=2, sinkcat="CH", percent=100.0),
            # CH → CH (sub-basin 2 drains into sub-basin 1)
            RoutingRow(sourceid=2, sourcecat="CH", hyd_typ="tot",
                       sinkid=1, sinkcat="CH", percent=100.0),
            # CH → X (terminal channel)
            RoutingRow(sourceid=1, sourcecat="CH", hyd_typ="tot",
                       sinkid=0, sinkcat="X", percent=100.0),
            # AQU → CH
            RoutingRow(sourceid=1, sourcecat="AQU", hyd_typ="tot",
                       sinkid=1, sinkcat="CH", percent=100.0),
            RoutingRow(sourceid=2, sourcecat="AQU", hyd_typ="tot",
                       sinkid=2, sinkcat="CH", percent=100.0),
            # DAQ → X
            RoutingRow(sourceid=1, sourcecat="DAQ", hyd_typ="tot",
                       sinkid=0, sinkcat="X", percent=100.0),
            RoutingRow(sourceid=2, sourcecat="DAQ", hyd_typ="tot",
                       sinkid=0, sinkcat="X", percent=100.0),
        ],
    )

    db = create_project_db(
        project_name="step7",
        workdir=tmp_path,
        reference_db=lte_datasets_db,
    )
    write_all(db, tables)
    seed_minimal_soils(db, {row.soil for row in tables.hrus})
    return db, tables


# ---------------------------------------------------------------------------
# Unit: mock datasets DB itself
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_mock_datasets_db_has_required_tables(lte_datasets_db) -> None:
    """Minimal smoke-test that create_mock_datasets_db produced valid content."""
    conn = sqlite3.connect(str(lte_datasets_db))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        (ver,) = conn.execute("SELECT value FROM version LIMIT 1").fetchone()
        (n_plants,) = conn.execute("SELECT COUNT(*) FROM plants_plt").fetchone()
        (n_soils_lte,) = conn.execute("SELECT COUNT(*) FROM soils_lte_sol").fetchone()
        (n_dtables,) = conn.execute("SELECT COUNT(*) FROM d_table_dtl").fetchone()
        (n_fcio,) = conn.execute("SELECT COUNT(*) FROM file_cio").fetchone()
    finally:
        conn.close()

    assert "plants_plt" in tables
    assert "soils_lte_sol" in tables
    assert "d_table_dtl" in tables
    assert "file_cio" in tables
    assert ver.startswith("3.")
    assert n_plants >= 2, f"Expected ≥2 plants, got {n_plants}"
    assert n_soils_lte >= 4, f"Expected ≥4 soil textures, got {n_soils_lte}"
    assert n_dtables == 4, f"Expected 4 decision tables, got {n_dtables}"
    assert n_fcio > 0, "file_cio must not be empty"


# ---------------------------------------------------------------------------
# Integration: setup_project (LTE) auto-runs import_gis
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_setup_project_lte_populates_connection_tables(lte_project) -> None:
    """setup_project(is_lte=True) must create hru_lte_con rows via import_gis."""
    from swatplus_builder.editor.api import setup_project

    db, tables = lte_project
    result = setup_project(db, is_lte=True, timeout=120.0)

    assert result.returncode == 0, f"setup_project failed:\n{result.stderr}"

    conn = sqlite3.connect(str(db))
    try:
        (n_hru_lte_con,) = conn.execute(
            "SELECT COUNT(*) FROM hru_lte_con"
        ).fetchone()
        (n_cha,) = conn.execute(
            "SELECT COUNT(*) FROM channel_lte_cha"
        ).fetchone()
        hyd_sed_lengths = [
            row[0]
            for row in conn.execute(
                "SELECT len FROM hyd_sed_lte_cha ORDER BY id"
            ).fetchall()
        ]
        gis_lengths = [
            row[0]
            for row in conn.execute(
                "SELECT len2 FROM gis_channels ORDER BY id"
            ).fetchall()
        ]
        (n_lsu_def,) = conn.execute(
            "SELECT COUNT(*) FROM ls_unit_def"
        ).fetchone()
        (n_plants,) = conn.execute(
            "SELECT COUNT(*) FROM plants_plt"
        ).fetchone()
        (imported,) = conn.execute(
            "SELECT imported_gis FROM project_config WHERE id=1"
        ).fetchone()
    finally:
        conn.close()

    assert n_hru_lte_con == len(tables.hrus), (
        f"Expected {len(tables.hrus)} hru_lte_con rows, got {n_hru_lte_con}"
    )
    assert n_cha == len(tables.channels), (
        f"Expected {len(tables.channels)} channel_lte_cha rows, got {n_cha}"
    )
    assert hyd_sed_lengths == [0.0005, 0.0005], (
        "hyd_sed_lte_cha.len must use the LTE transfer-length "
        f"compatibility value, got {hyd_sed_lengths}"
    )
    assert gis_lengths == [row.len2 for row in tables.channels], (
        "source GIS channel lengths must remain physical geometry"
    )
    assert n_lsu_def == len(tables.lsus), (
        f"Expected {len(tables.lsus)} ls_unit_def rows, got {n_lsu_def}"
    )
    assert n_plants > 0, "editor must copy plants_plt from datasets DB"
    assert imported == 1, "project_config.imported_gis must be set to 1"


# ---------------------------------------------------------------------------
# Integration: write_files produces TxtInOut/
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_write_files_produces_txtinout(lte_project, tmp_path) -> None:
    """Full round-trip: setup_project → write_files → TxtInOut/file.cio exists."""
    from swatplus_builder.editor.api import setup_project, write_files

    db, tables = lte_project
    setup_result = setup_project(db, is_lte=True, timeout=120.0)
    assert setup_result.returncode == 0, f"setup_project failed:\n{setup_result.stderr}"

    write_result = write_files(db, timeout=120.0)
    assert write_result.returncode == 0, f"write_files failed:\n{write_result.stderr}"

    txtinout = write_result.txtinout_dir
    assert txtinout is not None
    assert txtinout.is_dir(), f"TxtInOut dir was not created: {txtinout}"

    file_cio = txtinout / "file.cio"
    assert file_cio.is_file(), "file.cio was not produced"

    cio_text = file_cio.read_text(errors="replace")
    assert "object.cnt" in cio_text, "file.cio must list object.cnt"
    assert len(cio_text) > 50, "file.cio looks suspiciously short"


@pytest.mark.slow
def test_write_files_lte_artifacts_present(lte_project) -> None:
    """After write_files, LTE-specific files must exist in TxtInOut/."""
    from swatplus_builder.editor.api import setup_project, write_files

    db, tables = lte_project
    setup_project(db, is_lte=True, timeout=120.0)
    result = write_files(db, timeout=120.0)
    assert result.returncode == 0

    txtinout = result.txtinout_dir
    # Core files that must always be present
    core = [
        "file.cio",
        "time.sim",
        "object.cnt",
        "plants.plt",
        "soils_lte.sol",
    ]
    missing = [f for f in core if not (txtinout / f).is_file()]
    assert not missing, f"Missing core files: {missing}"


# ---------------------------------------------------------------------------
# Integration: re-import after gis_* edit
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_reimport_gis_after_edit(lte_project) -> None:
    """import_gis(delete_existing=True) must succeed after setup_project."""
    from swatplus_builder.editor.api import import_gis, setup_project

    db, _ = lte_project
    setup_project(db, is_lte=True, timeout=120.0)

    # Re-import: should succeed and re-populate connection tables.
    result = import_gis(db, delete_existing=True, timeout=60.0)
    assert result.returncode == 0, f"re-import_gis failed:\n{result.stderr}"

    conn = sqlite3.connect(str(db))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM hru_lte_con").fetchone()
    finally:
        conn.close()
    assert n >= 1, "hru_lte_con should be repopulated after re-import"
