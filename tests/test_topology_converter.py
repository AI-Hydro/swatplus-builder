"""Tests for full-mode topology converter (cha→sdc/chandeg)."""
import hashlib
import shutil
from pathlib import Path

import pytest

from swatplus_builder.full_mode.topology_converter import (
    TopologyConversionError,
    convert_topology,
)


def _make_full_tio(tmp_path: Path) -> Path:
    """Create a minimal full-mode TxtInOut for converter testing."""
    tio = tmp_path / "TxtInOut"
    tio.mkdir()

    # codes.bsn with rte_cha=0
    (tio / "codes.bsn").write_text(
        "codes.bsn: written by SWAT+ editor v3.2.2\n"
        "        pet_file           wq_file       pet     event     crack  swift_out   sed_det   rte_cha   deg_cha    wq_cha  nostress        cn    c_fact    carbon     lapse      uhyd   sed_cha  tiledrain    wtable    soil_p     gampt          atmo_dep  stor_max   i_fpwet    gwflow  \n"
        "            null              null         1         0         0         1         0         0         0         1         0         0         0         0         0         1         0         0         0         0         0                 a         0         1         0  \n"
    )

    # channel.con
    (tio / "channel.con").write_text(
        "channel.con: written by SWAT+ editor v3.2.2\n"
        "      id  name                gis_id          area           lat           lon          elev       cha               wst       cst      ovfl      rule   out_tot       obj_typ    obj_id       hyd_typ          frac  \n"
        "       1  cha01                    1     100.0      41.0     -77.0     200.0         1     s41085n77678w         0         0         0         1           cha         2           tot       1.00000  \n"
        "       2  cha02                    2     200.0      41.1     -77.1     180.0         2     s41071n77717w         0         0         0         1           out         1           tot       1.00000  \n"
    )

    # rout_unit.con
    (tio / "rout_unit.con").write_text(
        "rout_unit.con: written by SWAT+ editor v3.2.2\n"
        "      id  name                gis_id          area           lat           lon          elev       rtu               wst       cst      ovfl      rule   out_tot       obj_typ    obj_id       hyd_typ          frac  \n"
        "       1  rtu01                    1     100.0      41.0     -77.0     200.0         1     s41085n77678w         0         0         0         1           cha         1           tot       1.00000  \n"
    )

    # channel.cha
    (tio / "channel.cha").write_text(
        "channel.cha: written by SWAT+ editor v3.2.2\n"
        "      id  name                       cha_ini           cha_hyd           cha_sed           cha_nut  \n"
        "       1  cha01                     initcha1          hydcha1           sedcha1           nutcha1  \n"
        "       2  cha02                     initcha1          hydcha2           sedcha1           nutcha1  \n"
    )

    # hydrology.cha
    (tio / "hydrology.cha").write_text(
        "hydrology.cha: written by SWAT+ editor v3.2.2\n"
        "name                        wd            dp           slp           len          mann             k           wdr     alpha_bnk      side_slp  description\n"
        "hydcha1              20.72000       0.82800       0.03095       2.88844       0.05000       1.00000       5.00000       0.10000       0.50000  \n"
        "hydcha2              18.94000       0.77900       0.02647       5.09992       0.05000       1.00000       5.00000       0.10000       0.50000  \n"
    )

    # object.cnt
    (tio / "object.cnt").write_text(
        "object.cnt: written by SWAT+ editor v3.2.2\n"
        "name                   ls_area      tot_area       obj       hru      lhru       rtu      gwfl       aqu       cha       res       rec      exco       dlr       can       pmp       out      lcha     aqu2d       hrd       wro  \n"
        "test_basin          11364.0       11364.0        10         2         0         2         0         2         2         0         0         0         0         0         0         1         0         0         0         0  \n"
    )

    # file.cio
    (tio / "file.cio").write_text(
        "file.cio: written by SWAT+ editor v3.2.2\n"
        "simulation        time.sim          print.prt         null              object.cnt        null              \n"
        "basin             codes.bsn         parameters.bsn    \n"
        "connect           hru.con           null              rout_unit.con     null              aquifer.con       null              channel.con       null              null              null              null              outlet.con        null              \n"
        "channel           initial.cha       channel.cha       hydrology.cha     sediment.cha      nutrients.cha     null              null              null              \n"
        "routing_unit      rout_unit.def     rout_unit.ele     rout_unit.rtu     null              \n"
    )

    return tio


class TestTopologyConverter:
    def test_convert_codes_bsn(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        lines = (tio / "codes.bsn").read_text().split("\n")
        h = lines[1].split()
        d = lines[2].split()
        assert d[h.index("rte_cha")] == "1"

    def test_codes_bsn_flags_d1_fix(self, tmp_path):
        """D1: swift_out=0, uhyd=0, soil_p=1, i_fpwet=0 after conversion."""
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        lines = (tio / "codes.bsn").read_text().split("\n")
        h = lines[1].split()
        d = lines[2].split()
        assert d[h.index("swift_out")] == "0"
        assert d[h.index("uhyd")] == "0"
        assert d[h.index("soil_p")] == "1"
        assert d[h.index("i_fpwet")] == "0"

    def test_file_cio_no_outlet_con_d2_fix(self, tmp_path):
        """D2: outlet.con removed from connect block."""
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        cio = (tio / "file.cio").read_text()
        connect_lines = [l for l in cio.split("\n") if "connect" in l[:10]]
        assert connect_lines, "connect line not found"
        assert "outlet.con" not in connect_lines[0], (
            "outlet.con should not appear in connect block"
        )
        assert "chandeg.con" in connect_lines[0]

    def test_convert_rout_unit_con(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        ruc = (tio / "rout_unit.con").read_text()
        assert " cha " not in ruc
        assert " sdc " in ruc

    def test_generates_chandeg_con(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        assert (tio / "chandeg.con").exists()
        assert not (tio / "channel.con").exists()
        cd = (tio / "chandeg.con").read_text()
        assert "lcha" in cd
        assert "sdc" in cd

    def test_generates_channel_lte_cha(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        cle = (tio / "channel-lte.cha").read_text()
        assert "null" in cle

    def test_generates_hyd_sed_lte_cha(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        hsl = (tio / "hyd-sed-lte.cha").read_text()
        assert "erod_fact" in hsl
        assert "bankfull_flo" in hsl

    def test_updates_object_cnt(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        obj = (tio / "object.cnt").read_text().split("\n")
        oh = obj[1].split()
        od = obj[2].split()
        assert od[oh.index("lcha")] == "2"
        assert od[oh.index("cha")] == "0"

    def test_updates_file_cio(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        cio = (tio / "file.cio").read_text()
        assert "chandeg.con" in cio
        assert "channel.con" not in cio
        assert "channel-lte.cha" in cio
        assert "hyd-sed-lte.cha" in cio

    def test_missing_required_file_raises(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        (tio / "codes.bsn").unlink()
        with pytest.raises(TopologyConversionError, match="codes.bsn"):
            convert_topology(tio, backup=False)

    def test_empty_txtinout_raises(self, tmp_path):
        tio = tmp_path / "empty"
        tio.mkdir()
        with pytest.raises(TopologyConversionError):
            convert_topology(tio, backup=False)

    def test_backup_created(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=True)
        backup = tio.parent / (tio.name + "_cha_original")
        assert backup.exists()

    def test_idempotent(self, tmp_path):
        tio = _make_full_tio(tmp_path)
        convert_topology(tio, backup=False)
        # Second run should succeed gracefully (channel.con was removed)
        # If chandeg.con exists, return early (already converted)
        result = convert_topology(tio, backup=False)
        assert result == tio
