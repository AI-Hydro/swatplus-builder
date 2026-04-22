"""Tests for :mod:`swatplus_builder.db.writer` and the ``GisTables`` row
models in :mod:`swatplus_builder.types`.

These tests construct a tiny synthetic watershed in-memory — no GIS stack
required — and assert the writer produces a database that matches the
SWAT+ Editor's consumer contract (the peewee models in
``editor/vendored/database/project/gis.py``).
"""

from __future__ import annotations

import sqlite3

import pytest


# ---------------------------------------------------------------------------
# A tiny synthetic two-subbasin watershed that we reuse across tests.
#
#    subbasin 1  --channel 1 (Strahler 1)--> outlet 0 ('X')
#    subbasin 2  --channel 2 (Strahler 1)--> subbasin 1 / channel 1
#
# Each subbasin has one floodplain LSU (category=1) containing one HRU.
# Routing covers every required flow type.
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_watershed():
    from swatplus_builder.types import (
        ChannelRow,
        GisTables,
        HruRow,
        LsuRow,
        PointRow,
        RoutingRow,
        SubbasinRow,
    )

    subs = [
        SubbasinRow(
            id=1, area=1200.0, slo1=3.5, len1=4500.0, sll=50.0,
            lat=41.10, lon=-77.50, elev=320.0, elevmin=280.0, elevmax=450.0,
        ),
        SubbasinRow(
            id=2, area=800.0, slo1=4.2, len1=3000.0, sll=60.0,
            lat=41.15, lon=-77.55, elev=360.0, elevmin=310.0, elevmax=500.0,
        ),
    ]
    channels = [
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
    ]
    lsus = [
        LsuRow(
            id=101, category=1, channel=1, subbasin=1, area=1200.0, slope=3.5,
            len1=4500.0, csl=0.8, wid1=12.0, dep1=1.5,
            lat=41.10, lon=-77.50, elev=320.0,
        ),
        LsuRow(
            id=102, category=1, channel=2, subbasin=2, area=800.0, slope=4.2,
            len1=3000.0, csl=1.2, wid1=6.0, dep1=0.9,
            lat=41.15, lon=-77.55, elev=360.0,
        ),
    ]
    hrus = [
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
    ]
    points = [
        PointRow(
            id=1, subbasin=0, ptype="O", xpr=600000.0, ypr=4550000.0,
            lat=41.08, lon=-77.48, elev=275.0,
        ),
    ]
    # Routing: HRU→LSU→channel→(channel or outlet)
    routing = [
        RoutingRow(sourceid=1, sourcecat="HRU", hyd_typ="tot", sinkid=101, sinkcat="LSU", percent=100.0),
        RoutingRow(sourceid=2, sourcecat="HRU", hyd_typ="tot", sinkid=102, sinkcat="LSU", percent=100.0),
        RoutingRow(sourceid=101, sourcecat="LSU", hyd_typ="sur", sinkid=1, sinkcat="CH", percent=100.0),
        RoutingRow(sourceid=101, sourcecat="LSU", hyd_typ="lat", sinkid=1, sinkcat="CH", percent=100.0),
        RoutingRow(sourceid=102, sourcecat="LSU", hyd_typ="sur", sinkid=2, sinkcat="CH", percent=100.0),
        RoutingRow(sourceid=102, sourcecat="LSU", hyd_typ="lat", sinkid=2, sinkcat="CH", percent=100.0),
        RoutingRow(sourceid=2, sourcecat="CH", hyd_typ="tot", sinkid=1, sinkcat="CH", percent=100.0),
        RoutingRow(sourceid=1, sourcecat="CH", hyd_typ="tot", sinkid=1, sinkcat="PT", percent=100.0),
        RoutingRow(sourceid=1, sourcecat="PT", hyd_typ="tot", sinkid=0, sinkcat="X", percent=100.0),
    ]
    return GisTables(
        subbasins=subs, channels=channels, lsus=lsus, hrus=hrus,
        points=points, routing=routing,
    )


@pytest.fixture
def fresh_project_db(tmp_path):
    from swatplus_builder.db.project import create_project_db

    return create_project_db(project_name="wtest", workdir=tmp_path)


# ---- happy path -----------------------------------------------------------


def test_write_all_happy_path(fresh_project_db, tiny_watershed) -> None:
    from swatplus_builder.db.writer import write_all

    counts = write_all(fresh_project_db, tiny_watershed)
    assert counts == {
        "subbasins": 2, "channels": 2, "lsus": 2, "hrus": 2,
        "water": 0, "points": 1, "routing": 9,
        "aquifers": 0, "deep_aquifers": 0,
    }

    conn = sqlite3.connect(str(fresh_project_db))
    try:
        for table, expected in (
            ("gis_subbasins", 2), ("gis_channels", 2), ("gis_lsus", 2),
            ("gis_hrus", 2), ("gis_points", 1), ("gis_routing", 9),
        ):
            (n,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert n == expected, f"{table}: expected {expected}, got {n}"

        (delin, hrus_done) = conn.execute(
            "SELECT delineation_done, hrus_done FROM project_config"
        ).fetchone()
        assert delin == 1 and hrus_done == 1
    finally:
        conn.close()


def test_write_all_round_trips_exact_values(
    fresh_project_db, tiny_watershed,
) -> None:
    from swatplus_builder.db.writer import write_all

    write_all(fresh_project_db, tiny_watershed)

    conn = sqlite3.connect(str(fresh_project_db))
    try:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute(
            "SELECT * FROM gis_hrus WHERE id = 1"
        ).fetchone())
    finally:
        conn.close()

    expected = tiny_watershed.hrus[0]
    assert row["id"] == expected.id
    assert row["lsu"] == expected.lsu
    assert row["landuse"] == expected.landuse
    assert row["soil"] == expected.soil
    assert row["slp"] == expected.slp
    assert row["slope"] == pytest.approx(expected.slope)
    assert row["lat"] == pytest.approx(expected.lat)


# ---- routing rules --------------------------------------------------------


def test_routing_allows_duplicate_source_with_different_hyd_typ(
    fresh_project_db, tiny_watershed,
) -> None:
    """LSU splitting surface + lateral to the same channel is legal."""
    from swatplus_builder.db.writer import write_all

    # tiny_watershed already has (LSU 101, sur → CH 1) AND (LSU 101, lat → CH 1)
    # which share (sourceid, sourcecat) but differ on hyd_typ. Writer must
    # accept.
    write_all(fresh_project_db, tiny_watershed)


def test_routing_rejects_duplicate_triple(fresh_project_db, tiny_watershed) -> None:
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.types import RoutingRow

    tiny_watershed.routing.append(
        RoutingRow(
            sourceid=101, sourcecat="LSU", hyd_typ="sur",
            sinkid=1, sinkcat="CH", percent=100.0,
        ),
    )
    with pytest.raises(SwatBuilderPipelineError) as excinfo:
        write_all(fresh_project_db, tiny_watershed)
    assert "duplicate routing triple" in str(excinfo.value)


def test_routing_rejects_bad_percent_sum(fresh_project_db, tiny_watershed) -> None:
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.types import RoutingRow

    tiny_watershed.routing.append(
        RoutingRow(
            sourceid=101, sourcecat="LSU", hyd_typ="sur",
            sinkid=2, sinkcat="CH", percent=50.0,
        ),
    )
    with pytest.raises(SwatBuilderPipelineError) as excinfo:
        write_all(fresh_project_db, tiny_watershed)
    assert "SUM(percent)" in str(excinfo.value)
    assert "bad_groups" in excinfo.value.context


def test_routing_allows_percent_within_tolerance(
    fresh_project_db, tiny_watershed,
) -> None:
    from swatplus_builder.db.writer import ROUTING_PERCENT_TOLERANCE, write_all
    from swatplus_builder.types import RoutingRow

    # Replace one (sourceid=2, 'CH', 'tot') with two rows summing to 99.7
    # (within the 0.5 tolerance).
    tiny_watershed.routing = [
        r for r in tiny_watershed.routing
        if not (r.sourceid == 2 and r.sourcecat == "CH")
    ]
    tiny_watershed.routing.extend([
        RoutingRow(sourceid=2, sourcecat="CH", hyd_typ="tot", sinkid=1, sinkcat="CH", percent=60.0),
        RoutingRow(sourceid=2, sourcecat="CH", hyd_typ="tot", sinkid=101, sinkcat="LSU", percent=39.7),
    ])
    assert ROUTING_PERCENT_TOLERANCE >= 0.3
    write_all(fresh_project_db, tiny_watershed)


def test_routing_rejects_self_loop(fresh_project_db, tiny_watershed) -> None:
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.types import RoutingRow

    tiny_watershed.routing.append(
        RoutingRow(
            sourceid=1, sourcecat="CH", hyd_typ="tot",
            sinkid=1, sinkcat="CH", percent=100.0,
        ),
    )
    with pytest.raises(SwatBuilderPipelineError, match="self-loop"):
        write_all(fresh_project_db, tiny_watershed)


# ---- FK integrity ---------------------------------------------------------


def test_hru_referencing_unknown_lsu_rejected(
    fresh_project_db, tiny_watershed,
) -> None:
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.types import HruRow

    tiny_watershed.hrus.append(
        HruRow(
            id=999, lsu=9999, arsub=1.0, arlsu=1.0,
            landuse="X", arland=1.0, soil="Y", arso=1.0,
            slp="0-5", arslp=1.0, slope=1.0,
            lat=41.0, lon=-77.0, elev=300.0,
        ),
    )
    with pytest.raises(SwatBuilderPipelineError, match="gis_hrus.lsu"):
        write_all(fresh_project_db, tiny_watershed)


def test_channel_referencing_unknown_subbasin_rejected(
    fresh_project_db, tiny_watershed,
) -> None:
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.types import ChannelRow

    tiny_watershed.channels.append(
        ChannelRow(
            id=99, subbasin=99, areac=10.0, strahler=1, len2=100.0,
            slo2=1.0, wid2=2.0, dep2=0.5,
            elevmin=300.0, elevmax=310.0,
            midlat=41.0, midlon=-77.0,
        ),
    )
    with pytest.raises(SwatBuilderPipelineError, match="gis_channels.subbasin"):
        write_all(fresh_project_db, tiny_watershed)


def test_duplicate_ids_rejected(fresh_project_db, tiny_watershed) -> None:
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.types import SubbasinRow

    tiny_watershed.subbasins.append(
        SubbasinRow(
            id=1, area=1.0, slo1=0.0, len1=1.0, sll=1.0,
            lat=0.0, lon=0.0, elev=0.0, elevmin=0.0, elevmax=0.0,
        ),
    )
    with pytest.raises(SwatBuilderPipelineError) as excinfo:
        write_all(fresh_project_db, tiny_watershed)
    assert "duplicate ids" in str(excinfo.value)
    assert excinfo.value.context["duplicate_ids"] == [1]


# ---- transaction rollback -------------------------------------------------


def test_failed_write_leaves_db_clean(fresh_project_db, tiny_watershed) -> None:
    """If validation fails, project_config.delineation_done stays 0 and
    no gis_* rows are written."""
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.types import HruRow

    tiny_watershed.hrus.append(
        HruRow(
            id=999, lsu=9999, arsub=1.0, arlsu=1.0,
            landuse="X", arland=1.0, soil="Y", arso=1.0,
            slp="0-5", arslp=1.0, slope=1.0,
            lat=41.0, lon=-77.0, elev=300.0,
        ),
    )
    with pytest.raises(SwatBuilderPipelineError):
        write_all(fresh_project_db, tiny_watershed)

    conn = sqlite3.connect(str(fresh_project_db))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM gis_hrus").fetchone()
        (n2,) = conn.execute("SELECT COUNT(*) FROM gis_subbasins").fetchone()
        (delin,) = conn.execute(
            "SELECT delineation_done FROM project_config"
        ).fetchone()
    finally:
        conn.close()
    assert n == 0, "no HRU rows should exist"
    assert n2 == 0, "no subbasin rows should exist (validate runs first)"
    assert delin == 0


def test_validate_false_skips_checks(fresh_project_db, tiny_watershed) -> None:
    """With validate=False, FK-broken rows still get written."""
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.types import HruRow

    tiny_watershed.hrus.append(
        HruRow(
            id=999, lsu=9999, arsub=1.0, arlsu=1.0,
            landuse="X", arland=1.0, soil="Y", arso=1.0,
            slp="0-5", arslp=1.0, slope=1.0,
            lat=41.0, lon=-77.0, elev=300.0,
        ),
    )
    counts = write_all(fresh_project_db, tiny_watershed, validate=False)
    assert counts["hrus"] == 3


def test_missing_project_db_raises(tmp_path, tiny_watershed) -> None:
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.errors import SwatBuilderPipelineError

    with pytest.raises(SwatBuilderPipelineError, match="does not exist"):
        write_all(tmp_path / "nope.sqlite", tiny_watershed)


# ---- editor compat spot-check ---------------------------------------------


def test_written_columns_satisfy_editor_orm(
    fresh_project_db, tiny_watershed,
) -> None:
    """Spot-check: every column the editor's peewee ORM declares for the
    core tables is present (not NULL) in our written rows."""
    from swatplus_builder.db.writer import write_all

    write_all(fresh_project_db, tiny_watershed)

    conn = sqlite3.connect(str(fresh_project_db))
    conn.row_factory = sqlite3.Row
    try:
        must_be_set = {
            "gis_channels": [
                "subbasin", "areac", "strahler", "len2", "slo2",
                "wid2", "dep2", "elevmin", "elevmax", "midlat", "midlon",
            ],
            "gis_hrus": [
                "lsu", "arsub", "arlsu", "landuse", "arland", "soil",
                "arso", "slp", "arslp", "slope", "lat", "lon", "elev",
            ],
            "gis_lsus": [
                "category", "channel", "area", "slope", "len1", "csl",
                "wid1", "dep1", "lat", "lon", "elev",
            ],
        }
        for table, cols in must_be_set.items():
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            assert rows, f"{table} is empty"
            for row in rows:
                for c in cols:
                    assert row[c] is not None, f"{table}.{c} is NULL"
    finally:
        conn.close()
