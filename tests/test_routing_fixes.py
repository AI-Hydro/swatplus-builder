from __future__ import annotations

from pathlib import Path

import pytest

from swatplus_builder.full_mode.routing_fixes import (
    RoutingFixError,
    _validate_fixes,
    apply_full_routing_fixes,
)


def _make_txtinout(tmp_path: Path) -> Path:
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    (txt / "codes.bsn").write_text(
        "codes.bsn\n"
        "rte_cha swift_out uhyd soil_p i_fpwet\n"
        "0 1 1 0 1\n",
        encoding="utf-8",
    )
    (txt / "rout_unit.def").write_text(
        "rout_unit.def\n"
        "id name elem_tot elements\n"
        "1 rtu01 1 1\n"
        "2 rtu02 1 2\n",
        encoding="utf-8",
    )
    (txt / "rout_unit.con").write_text(
        "rout_unit.con\n"
        "id name gis_id area lat lon elev rtu wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 rtu01 1 10 0 0 0 1 w 0 0 0 1 sdc 1 tot 1.0\n"
        "2 rtu02 2 10 0 0 0 2 w 0 0 0 1 sdc 1 tot 1.0\n",
        encoding="utf-8",
    )
    return txt


def test_rout_unit_def_negative_element_uses_own_routing_unit_id(tmp_path: Path) -> None:
    txt = _make_txtinout(tmp_path)

    apply_full_routing_fixes(txt)

    rows = (txt / "rout_unit.def").read_text(encoding="utf-8").splitlines()[2:]
    assert rows[0].split()[-1] == "-1"
    assert rows[1].split()[-1] == "-2"
    con_rows = (txt / "rout_unit.con").read_text(encoding="utf-8").splitlines()[2:]
    assert all(" tot " not in f" {row} " for row in con_rows)
    assert all(" sur " in f" {row} " and " lat " in f" {row} " for row in con_rows)
    assert all(row.split()[12] == "2" for row in con_rows)


def test_rout_unit_def_expands_full_overlay_hru_element_ranges(tmp_path: Path) -> None:
    txt = _make_txtinout(tmp_path)
    (txt / "rout_unit.def").write_text(
        "rout_unit.def\n"
        "id name elem_tot elements\n"
        "1 rtu01 2 1 -1\n"
        "2 rtu02 2 4 -2\n",
        encoding="utf-8",
    )
    (txt / "rout_unit.ele").write_text(
        "rout_unit.ele\n"
        "id name obj_typ obj_id frac dlr\n"
        "1 hru0001 hru 1 0.50 0\n"
        "2 hru0002 hru 2 0.25 0\n"
        "3 hru0003 hru 3 0.25 0\n"
        "4 hru0004 hru 4 0.60 0\n"
        "5 hru0005 hru 5 0.40 0\n",
        encoding="utf-8",
    )

    apply_full_routing_fixes(txt)

    rows = (txt / "rout_unit.def").read_text(encoding="utf-8").splitlines()[2:]
    assert rows[0].split() == ["1", "rtu01", "4", "1", "2", "3", "-1"]
    assert rows[1].split() == ["2", "rtu02", "3", "4", "5", "-2"]


def test_validate_fixes_rejects_nonconserving_hru_fractions(tmp_path: Path) -> None:
    txt = _make_txtinout(tmp_path)
    (txt / "rout_unit.def").write_text(
        "rout_unit.def\n"
        "id name elem_tot elements\n"
        "1 rtu01 3 1 2 -1\n"
        "2 rtu02 2 3 -2\n",
        encoding="utf-8",
    )
    (txt / "rout_unit.ele").write_text(
        "rout_unit.ele\n"
        "id name obj_typ obj_id frac dlr\n"
        "1 hru0001 hru 1 0.40 0\n"
        "2 hru0002 hru 2 0.40 0\n"
        "3 hru0003 hru 3 1.00 0\n",
        encoding="utf-8",
    )

    with pytest.raises(RoutingFixError, match="routing unit 1 sum to 0.800000"):
        _validate_fixes(txt)


def test_validate_fixes_rejects_wrong_negative_routing_unit_element(tmp_path: Path) -> None:
    txt = _make_txtinout(tmp_path)
    (txt / "rout_unit.def").write_text(
        "rout_unit.def\n"
        "id name elem_tot elements\n"
        "1 rtu01 2 1 -1\n"
        "2 rtu02 2 2 -1\n",
        encoding="utf-8",
    )
    (txt / "rout_unit.con").write_text(
        "rout_unit.con\n"
        "id name gis_id area lat lon elev rtu wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 rtu01 1 10 0 0 0 1 w 0 0 0 2 sdc 1 sur 1.0 sdc 1 lat 1.0\n"
        "2 rtu02 2 10 0 0 0 2 w 0 0 0 2 sdc 1 sur 1.0 sdc 1 lat 1.0\n",
        encoding="utf-8",
    )

    with pytest.raises(RoutingFixError, match="expected own negative sdc element -2"):
        _validate_fixes(txt)


def test_rout_unit_con_prior_tot_sur_lat_rows_collapse_without_double_counting(tmp_path: Path) -> None:
    txt = _make_txtinout(tmp_path)
    (txt / "rout_unit.con").write_text(
        "rout_unit.con\n"
        "id name gis_id area lat lon elev rtu wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 rtu01 1 10 0 0 0 1 w 0 0 0 3 sdc 1 tot 1.0 sdc 1 sur 1.0 sdc 1 lat 1.0\n"
        "2 rtu02 2 10 0 0 0 2 w 0 0 0 1 sdc 2 tot 1.0\n",
        encoding="utf-8",
    )

    apply_full_routing_fixes(txt)

    rows = (txt / "rout_unit.con").read_text(encoding="utf-8").splitlines()[2:]
    assert rows[0].split()[12] == "2"
    assert rows[1].split()[12] == "2"
    assert all(" tot " not in f" {row} " for row in rows)
    assert rows[0].count(" sur ") == 1
    assert rows[0].count(" lat ") == 1
    assert rows[1].count(" sur ") == 1
    assert rows[1].count(" lat ") == 1


def test_groundwater_recharge_routes_are_restored(tmp_path: Path) -> None:
    txt = _make_txtinout(tmp_path)
    (txt / "aquifer.con").write_text(
        "aquifer.con\n"
        "id name gis_id area lat lon elev aqu wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 aqu01 1 10 0 0 0 1 w 0 0 0 1 sdc 1 tot 1.0\n"
        "2 aqu02 2 10 0 0 0 2 w 0 0 0 1 sdc 2 tot 1.0\n"
        "3 aqu_deep01 1 10 0 0 0 3 w 0 0 0 0\n"
        "4 aqu_deep02 2 10 0 0 0 4 w 0 0 0 0\n",
        encoding="utf-8",
    )

    apply_full_routing_fixes(txt)

    ru_rows = (txt / "rout_unit.con").read_text().splitlines()[2:]
    assert all(" aqu " in f" {row} " and " rhg " in f" {row} " for row in ru_rows)
    aqu_rows = (txt / "aquifer.con").read_text().splitlines()[2:]
    assert " aqu 3 rhg 1.00000" in aqu_rows[0]
    assert " aqu 4 rhg 1.00000" in aqu_rows[1]
