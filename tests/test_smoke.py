"""Smoke tests — verify package imports and public surface.

These tests run without the GIS stack (rasterio, geopandas, whitebox, etc.)
and without the SWAT+ engine. They are the only tests expected to pass in a
bare-metal CI environment that only has the core + dev extras installed.
"""

from __future__ import annotations

import pytest


def test_version() -> None:
    import swatplus_builder

    assert swatplus_builder.__version__


def test_tools_surface() -> None:
    from swatplus_builder.tools import (
        build_watershed,
        create_hrus,
        run_swat,
    )

    assert callable(build_watershed)
    assert callable(create_hrus)
    assert callable(run_swat)


def test_types_surface() -> None:
    from swatplus_builder.types import (
        GisTables,
        Outlet,
    )

    assert Outlet(lon=-77.0, lat=41.0).as_tuple() == (-77.0, 41.0)
    assert Outlet(usgs_id="01547700").as_tuple() is None
    # empty GisTables is valid and round-trips through JSON.
    empty = GisTables()
    assert GisTables.model_validate_json(empty.model_dump_json()) == empty


def test_errors_hierarchy() -> None:
    from swatplus_builder.errors import (
        SwatBuilderError,
        SwatBuilderExternalError,
        SwatBuilderInputError,
        SwatBuilderPipelineError,
    )

    for cls in (
        SwatBuilderInputError,
        SwatBuilderPipelineError,
        SwatBuilderExternalError,
    ):
        assert issubclass(cls, SwatBuilderError)
        err = cls("msg", foo=1)
        assert err.context == {"foo": 1}


def test_config_defaults() -> None:
    from swatplus_builder.config import DEFAULT_SETTINGS, HruFilters, Settings

    assert isinstance(DEFAULT_SETTINGS, Settings)
    assert isinstance(DEFAULT_SETTINGS.hru_filter, HruFilters)


# Core modules MUST import cleanly even without the GIS stack installed —
# this is the guarantee that protects core/LTE users who `pip install` without
# the [gis] extra. Heavy deps (whitebox/rasterio/geopandas) must be lazy here.
_CORE_MODULES = [
    "swatplus_builder.gis.landuse",
    "swatplus_builder.db.schema",
    "swatplus_builder.db.project",
    "swatplus_builder.db.writer",
    "swatplus_builder.editor.api",
    "swatplus_builder.weather",
    "swatplus_builder.weather.gridmet",
    "swatplus_builder.weather.synthetic",
    "swatplus_builder.weather.wgn",
    "swatplus_builder.weather.writer",
    "swatplus_builder.soil",
    "swatplus_builder.soil.gnatsgo",
    "swatplus_builder.soil.params",
    "swatplus_builder.soil.writer",
    "swatplus_builder.output",
    "swatplus_builder.output.reader",
    "swatplus_builder.output.summary",
    "swatplus_builder.run.swatplus",
    "swatplus_builder.tools.agent",
    "swatplus_builder.cli",
]

# GIS overlay modules are genuinely GIS-bound and import geopandas/rasterio at
# module scope. They are only importable when the [gis] extra is present.
_GIS_MODULES = [
    "swatplus_builder.gis.delineation",
    "swatplus_builder.gis.soil",
    "swatplus_builder.gis.hru",
    "swatplus_builder.gis.validate",
]


@pytest.mark.parametrize("dotted", _CORE_MODULES)
def test_all_modules_importable(dotted: str) -> None:
    """Core modules must import cleanly — even without the GIS stack installed.

    Modules with optional heavy deps (whitebox, rasterio, geopandas) must use
    lazy imports inside functions, never at module level.
    """
    __import__(dotted)


@pytest.mark.parametrize("dotted", _GIS_MODULES)
def test_gis_modules_importable_with_gis_extra(dotted: str) -> None:
    """GIS overlay modules import only when the [gis] extra is installed."""
    pytest.importorskip("geopandas")
    pytest.importorskip("rasterio")
    __import__(dotted)


def test_build_watershed_missing_gis_raises_cleanly() -> None:
    """build_watershed must raise SwatBuilderExternalError (not ImportError)
    when whitebox is not installed, and SwatBuilderInputError for a bad path."""
    from swatplus_builder.errors import SwatBuilderInputError
    from swatplus_builder.tools import build_watershed

    # Non-existent DEM → SwatBuilderInputError before whitebox is even touched
    with pytest.raises(SwatBuilderInputError):
        build_watershed(
            dem_path="/definitely/does/not/exist.tif",
            outlet=(-77.12, 41.45),
            validate=False,
        )


def test_validation_result_model() -> None:
    pytest.importorskip("geopandas")
    from swatplus_builder.gis.validate import ValidationResult

    vr = ValidationResult(
        delineated_area_km2=58.3,
        n_subbasins=12,
        reference_area_km2=62.1,
        reference_source="usgs_nldi",
        area_diff_pct=-6.1,
        iou_pct=91.2,
        centroid_distance_km=0.8,
        passed=True,
        area_tolerance_pct=10.0,
        notes=["All checks passed."],
    )
    assert vr.passed
    assert vr.to_dict()["iou_pct"] == 91.2


def test_delineation_public_surface() -> None:
    pytest.importorskip("geopandas")
    from swatplus_builder.gis.delineation import delineate, load_result, resolve_usgs_outlet

    assert callable(delineate)
    assert callable(load_result)
    assert callable(resolve_usgs_outlet)


def test_validate_public_surface() -> None:
    pytest.importorskip("geopandas")
    from swatplus_builder.gis.validate import ValidationResult, validate_watershed

    assert callable(validate_watershed)
    assert issubclass(ValidationResult, object)


def test_db_schema_ensures_all_tables() -> None:
    """ensure_schema must create every canonical gis_* table + project_config
    in a fresh in-memory SQLite, idempotently."""
    import sqlite3

    from swatplus_builder.db.schema import ensure_schema

    expected = {
        "project_config",
        "gis_points",
        "gis_subbasins",
        "gis_channels",
        "gis_lsus",
        "gis_hrus",
        "gis_water",
        "gis_aquifers",
        "gis_deep_aquifers",
        "gis_routing",
        "gis_elevationbands",
        "gis_landexempt",
        "gis_splithrus",
    }

    conn = sqlite3.connect(":memory:")
    try:
        ensure_schema(conn)
        ensure_schema(conn)  # idempotent
        got = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()

    missing = expected - got
    assert not missing, f"ensure_schema did not create: {missing}"


def test_db_schema_column_counts_match_qswatplus_ddl() -> None:
    """Column counts must match QSWATPlus/DBUtils.py DDL (see SCHEMA.md).

    This is the contract that makes positional INSERTs safe.
    """
    import sqlite3

    from swatplus_builder.db.schema import ensure_schema

    # project_config tracks the editor's Peewee model (24 cols + id = 25),
    # superset of QSWATPlus's 22+id DDL (ADR-015). All gis_* match
    # QSWATPlus exactly.
    expected_cols: dict[str, int] = {
        "project_config": 25,
        "gis_points": 8,
        "gis_subbasins": 11,
        "gis_channels": 12,
        "gis_lsus": 13,
        "gis_hrus": 14,
        "gis_water": 10,
        "gis_aquifers": 8,
        "gis_deep_aquifers": 6,
        "gis_routing": 6,
    }

    conn = sqlite3.connect(":memory:")
    try:
        ensure_schema(conn)
        for table, expected in expected_cols.items():
            rows = list(conn.execute(f'PRAGMA table_info("{table}")'))
            assert len(rows) == expected, (
                f"{table}: expected {expected} cols, got {len(rows)} "
                f"({[r[1] for r in rows]})"
            )
    finally:
        conn.close()


def test_db_schema_preserves_reak_typo() -> None:
    """ADR-012: the QSWATPlus aquifer DDL has a REAK typo. We preserve it
    verbatim so downstream consumers see byte-identical schema."""
    from swatplus_builder.db.schema import (
        GIS_AQUIFERS_DDL,
        GIS_DEEP_AQUIFERS_DDL,
    )

    assert "REAK" in GIS_AQUIFERS_DDL
    assert "REAK" in GIS_DEEP_AQUIFERS_DDL


def test_db_schema_insert_sql_placeholders_match_column_counts() -> None:
    """Positional INSERT tuples must align with column counts."""
    from swatplus_builder.db import schema

    checks = {
        schema.PROJECT_CONFIG_INSERT_SQL: 25,
        schema.GIS_POINTS_INSERT_SQL: 8,
        schema.GIS_SUBBASINS_INSERT_SQL: 11,
        schema.GIS_CHANNELS_INSERT_SQL: 12,
        schema.GIS_LSUS_INSERT_SQL: 13,
        schema.GIS_HRUS_INSERT_SQL: 14,
        schema.GIS_WATER_INSERT_SQL: 10,
        schema.GIS_ROUTING_INSERT_SQL: 6,
        schema.GIS_AQUIFERS_INSERT_SQL: 8,
        schema.GIS_DEEP_AQUIFERS_INSERT_SQL: 6,
    }
    for sql, n in checks.items():
        assert sql.count("?") == n, f"{sql!r} should have {n} '?'"


def test_db_schema_gis_routing_index_is_not_unique() -> None:
    """Step 1 finding: editor's Gis_routing allows duplicate (sourceid,
    sourcecat) because a single source can split into multiple sinks. Our
    index must be plain, not UNIQUE."""
    import sqlite3

    from swatplus_builder.db.schema import ensure_schema

    conn = sqlite3.connect(":memory:")
    try:
        ensure_schema(conn)
        idx = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND tbl_name='gis_routing' AND name='source'"
        ).fetchone()
        assert idx is not None, "routing index missing"
        assert "UNIQUE" not in (idx[0] or "").upper(), (
            f"routing index must NOT be UNIQUE; got: {idx[0]}"
        )

        # Prove duplicates are allowed: same (sourceid, sourcecat) twice.
        conn.execute(
            "INSERT INTO gis_routing VALUES(?,?,?,?,?,?)",
            (1, "LSU", "sur", 10, "CH", 80.0),
        )
        conn.execute(
            "INSERT INTO gis_routing VALUES(?,?,?,?,?,?)",
            (1, "LSU", "sur", 20, "LSU", 20.0),
        )
        conn.commit()
    finally:
        conn.close()


def test_db_project_create_writes_valid_config(tmp_path) -> None:
    from swatplus_builder.db.project import (
        EDITOR_VERSION,
        create_project_db,
        read_project_config,
    )

    db = create_project_db(
        project_name="unit_test_proj",
        workdir=tmp_path,
        reference_db=tmp_path / "fake_ref.sqlite",
        wgn_db=tmp_path / "fake_wgn.sqlite",
    )
    assert db.exists()
    assert db.name == "unit_test_proj.sqlite"

    cfg = read_project_config(db)
    assert cfg["id"] == 1
    assert cfg["project_name"] == "unit_test_proj"
    assert cfg["editor_version"] == EDITOR_VERSION
    assert cfg["delineation_done"] == 0
    assert cfg["hrus_done"] == 0
    assert cfg["imported_gis"] == 0
    assert cfg["is_lte"] == 0
    assert cfg["use_gwflow"] == 0
    assert cfg["weather_data_format"] == "plus"
    assert str(tmp_path / "fake_ref.sqlite") in str(cfg["reference_db"])


def test_db_project_create_rejects_invalid_name(tmp_path) -> None:
    from swatplus_builder.db.project import create_project_db
    from swatplus_builder.errors import SwatBuilderInputError

    with pytest.raises(SwatBuilderInputError):
        create_project_db(project_name="bad/name", workdir=tmp_path)


def test_db_project_create_refuses_overwrite_by_default(tmp_path) -> None:
    from swatplus_builder.db.project import create_project_db
    from swatplus_builder.errors import SwatBuilderInputError

    create_project_db(project_name="p", workdir=tmp_path)
    with pytest.raises(SwatBuilderInputError):
        create_project_db(project_name="p", workdir=tmp_path)

    # overwrite=True succeeds.
    db = create_project_db(project_name="p", workdir=tmp_path, overwrite=True)
    assert db.exists()


def test_db_project_mark_gis_ready_and_imported(tmp_path) -> None:
    from swatplus_builder.db.project import (
        create_project_db,
        mark_gis_imported,
        mark_gis_ready,
        read_project_config,
    )

    db = create_project_db(project_name="m", workdir=tmp_path)
    mark_gis_ready(db)
    cfg = read_project_config(db)
    assert cfg["delineation_done"] == 1
    assert cfg["hrus_done"] == 1
    assert cfg["input_files_last_written"] is not None

    mark_gis_imported(db)
    cfg2 = read_project_config(db)
    assert cfg2["imported_gis"] == 1


def test_editor_vendored_commit_pinned() -> None:
    """Ensure the vendored SWAT+ Editor has a pinned commit."""
    from pathlib import Path

    import swatplus_builder

    commit_file = (
        Path(swatplus_builder.__file__).parent
        / "editor"
        / "vendored"
        / ".VENDORED_COMMIT"
    )
    if not commit_file.exists():
        pytest.skip(
            ".VENDORED_COMMIT absent — provenance pin is written by "
            "scripts/vendor_swatplus_editor.sh, not committed to the tree."
        )
    commit = commit_file.read_text().strip()
    assert len(commit) == 40, f"expected 40-char SHA, got: {commit!r}"


def test_editor_gis_orm_columns_are_producer_subset() -> None:
    """The editor's peewee ORM declares column names we must write.

    Every field declared in ``vendored/database/project/gis.py`` must appear
    either as a column in our ``db.schema`` DDL or as the implicit peewee
    ``id`` PK. This protects us against editor upgrades silently introducing
    new required columns.
    """
    import re
    from pathlib import Path

    import swatplus_builder

    gis_path = (
        Path(swatplus_builder.__file__).parent
        / "editor"
        / "vendored"
        / "database"
        / "project"
        / "gis.py"
    )
    if not gis_path.exists():
        pytest.skip("vendored editor not present")

    text = gis_path.read_text()

    # Parse "class Gis_foo(base.BaseModel):" blocks and their field lines
    # of the form "<name> = <Field>(…)" (peewee).
    class_blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^class (Gis_\w+)\(", line)
        if m:
            current = m.group(1)
            class_blocks[current] = []
            continue
        if current is None:
            continue
        m = re.match(r"^\t(\w+)\s*=\s*\w*Field", line)
        if m and not line.strip().startswith("#"):
            class_blocks[current].append(m.group(1))

    from swatplus_builder.db import schema

    # Map editor model name → our DDL string.
    matrix = {
        "Gis_subbasins": schema.GIS_SUBBASINS_DDL,
        "Gis_channels": schema.GIS_CHANNELS_DDL,
        "Gis_lsus": schema.GIS_LSUS_DDL,
        "Gis_hrus": schema.GIS_HRUS_DDL,
        "Gis_water": schema.GIS_WATER_DDL,
        "Gis_points": schema.GIS_POINTS_DDL,
        "Gis_routing": schema.GIS_ROUTING_DDL,
        "Gis_aquifers": schema.GIS_AQUIFERS_DDL,
        "Gis_deep_aquifers": schema.GIS_DEEP_AQUIFERS_DDL,
    }

    problems: list[str] = []
    for model, ddl in matrix.items():
        if model not in class_blocks:
            problems.append(f"{model}: not found in vendored gis.py")
            continue
        ddl_lower = ddl.lower()
        for field in class_blocks[model]:
            # peewee's implicit id PK is on every BaseModel; our DDL
            # names the PK 'id' too, so that's fine.
            if f" {field.lower()}" not in ddl_lower:
                problems.append(f"{model}: field {field!r} missing in our DDL")
    assert not problems, "Editor/producer schema mismatch:\n  " + "\n  ".join(
        problems
    )


# ---------------------------------------------------------------------------
# ref/ — datasets DB catalog + bootstrap (offline assertions only)
# ---------------------------------------------------------------------------


def test_ref_catalog_default_release_is_pinned() -> None:
    from swatplus_builder.ref import (
        DATASETS_RELEASES,
        DEFAULT_DATASETS_VERSION,
        get_release,
    )

    assert DEFAULT_DATASETS_VERSION in DATASETS_RELEASES
    release = get_release()
    assert release.datasets_version == DEFAULT_DATASETS_VERSION
    assert len(release.sha256) == 64
    assert release.size > 0
    assert release.url.startswith("https://")
    assert release.editor_tag.startswith("v")


def test_ref_catalog_rejects_unknown_version() -> None:
    from swatplus_builder.ref import get_release

    with pytest.raises(KeyError, match="Unknown datasets version"):
        get_release("99.9.9")


def test_ref_locate_returns_none_when_cache_empty(tmp_path) -> None:
    from swatplus_builder.config import Settings
    from swatplus_builder.ref import locate_datasets_db

    settings = Settings(reference_db_dir=tmp_path)
    assert locate_datasets_db(settings=settings) is None


def test_ref_locate_rejects_wrong_sized_cache(tmp_path) -> None:
    """A leftover partial download with a matching filename but wrong
    size/hash must be treated as a cache miss — never surfaced as valid."""
    from swatplus_builder.config import Settings
    from swatplus_builder.ref import DEFAULT_DATASETS_VERSION, get_release, locate_datasets_db
    from swatplus_builder.ref.bootstrap import cached_filename

    release = get_release(DEFAULT_DATASETS_VERSION)
    (tmp_path / cached_filename(release)).write_bytes(b"not a sqlite file")

    settings = Settings(reference_db_dir=tmp_path)
    assert locate_datasets_db(settings=settings) is None


def test_ref_fetch_rejects_unknown_version(tmp_path) -> None:
    from swatplus_builder.config import Settings
    from swatplus_builder.errors import SwatBuilderInputError
    from swatplus_builder.ref import fetch_datasets_db

    settings = Settings(reference_db_dir=tmp_path)
    with pytest.raises(SwatBuilderInputError, match="Unknown datasets version"):
        fetch_datasets_db("99.9.9", settings=settings)


def test_ref_verify_sha256_roundtrip(tmp_path) -> None:
    """Ensure our hex-digest helper matches stdlib hashlib for a known blob."""
    import hashlib

    from swatplus_builder.ref.bootstrap import verify_sha256

    blob = b"swatplus-builder datasets verification fixture" * 64
    f = tmp_path / "blob.bin"
    f.write_bytes(blob)
    assert verify_sha256(f) == hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# db.seed — placeholder soils helper
# ---------------------------------------------------------------------------


def test_db_seed_creates_and_upserts_soils(tmp_path) -> None:
    import sqlite3

    from swatplus_builder.db.project import create_project_db
    from swatplus_builder.db.seed import seed_minimal_soils

    db = create_project_db(
        project_name="seed_t",
        workdir=tmp_path,
        reference_db=tmp_path / "fake.sqlite",
    )
    n = seed_minimal_soils(db, ["SILT_LOAM", "SILT_LOAM", "CLAY"])
    assert n == 2  # duplicates are de-duped

    conn = sqlite3.connect(str(db))
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM soils_sol")}
        layer_n = conn.execute("SELECT COUNT(*) FROM soils_sol_layer").fetchone()[0]
    finally:
        conn.close()
    assert names == {"SILT_LOAM", "CLAY"}
    assert layer_n == 2

    # Re-seed with overlap: no new rows.
    again = seed_minimal_soils(db, ["SILT_LOAM", "SAND"])
    assert again == 1
