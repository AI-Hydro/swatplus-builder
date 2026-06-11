"""Tests for full-mode parameter bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from swatplus_builder.full_mode.parameter_bridge import (
    ParameterBridgeError,
    _apply_cn2,
    _apply_esco,
    _apply_alpha_bf,
    _apply_rchg_dp,
    _apply_pet_co,
    _rewrite_column_for_rows,
    apply_parameters_to_full_swat_txtinout,
)


def _write_cntable(tio: Path) -> Path:
    p = tio / "cntable.lum"
    p.write_text(
        "cntable.lum: test fixture\n"
        "name                      cn_a          cn_b          cn_c          cn_d  description treat cond_cov\n"
        "fal_bare              77.00000      86.00000      91.00000      94.00000  Fallow Bare ----\n"
        "wood_f                36.00000      60.00000      73.00000      79.00000  Woods ---- Fair\n"
        "wood_g                30.00000      55.00000      70.00000      77.00000  Woods ---- Good\n"
    )
    return p


def _write_hydrology(tio: Path) -> Path:
    p = tio / "hydrology.hyd"
    p.write_text(
        "hydrology.hyd: test fixture\n"
        "name                 lat_ttime       lat_sed       can_max          esco          epco   orgn_enrich   orgp_enrich       cn3_swf       bio_mix         perco      lat_orgn      lat_orgp        pet_co       latq_co\n"
        "hyd01                  0.00000       0.00000       1.00000       0.95000       0.50000       0.00000       0.00000       0.95000       0.20000       0.90000       0.00000       0.00000       1.00000       0.01000\n"
        "hyd02                  0.00000       0.00000       1.00000       0.95000       0.50000       0.00000       0.00000       0.95000       0.20000       0.90000       0.00000       0.00000       1.00000       0.01000\n"
    )
    return p


def _write_aquifer(tio: Path) -> Path:
    p = tio / "aquifer.aqu"
    p.write_text(
        "aquifer.aqu: test fixture\n"
        "id  name        init   gw_flo  dep_bot  dep_wt  no3_n  sol_p  carbon  flo_dist  bf_max  alpha_bf  revap  rchg_dp  spec_yld  hl_no3n  flo_min  revap_min\n"
        " 1  aqu01   initaqu1  0.05000 10.00000  3.00000 0.00000 0.00000 0.50000 50.00000 1.00000   0.05000 0.02000  0.05000   0.05000 30.00000  3.00000   5.00000\n"
    )
    return p


class TestParameterBridge:
    def test_cn2_shifts_wood_rows_by_delta_to_target(self, tmp_path):
        _write_cntable(tmp_path)
        _apply_cn2(tmp_path, 80.0)  # target cn_b = 80; wood_f goes from cn_b=60 to 80 (delta +20)
        content = (tmp_path / "cntable.lum").read_text()
        lines = content.split("\n")
        # fal_bare should be untouched
        assert "77.00000" in lines[2] and "86.00000" in lines[2]
        # wood_f shifted: cn_a 36→56, cn_b 60→80, cn_c 73→93, cn_d 79→98 (capped)
        assert "56.00000" in lines[3]
        assert "80.00000" in lines[3]
        # wood_g shifted: cn_b 55→80 (delta +25); cn_a 30→55, cn_b 55→80, cn_c 70→95, cn_d 77→98 (capped)
        assert "55.00000" in lines[4]
        assert "80.00000" in lines[4]

    def test_cn2_out_of_range_raises(self, tmp_path):
        _write_cntable(tmp_path)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_cn2(tmp_path, 10.0)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_cn2(tmp_path, 100.0)

    def test_cn2_missing_file_raises(self, tmp_path):
        with pytest.raises(ParameterBridgeError, match="Required file missing"):
            _apply_cn2(tmp_path, 70.0)

    def test_esco_writes_all_hru_rows(self, tmp_path):
        _write_hydrology(tmp_path)
        _apply_esco(tmp_path, 0.30)
        content = (tmp_path / "hydrology.hyd").read_text()
        # both rows should now have 0.30 in esco column (col 4 after header tokens)
        lines = content.split("\n")
        assert "0.30000" in lines[2]
        assert "0.30000" in lines[3]
        # epco unchanged
        assert "0.50000" in lines[2]

    def test_esco_out_of_range_raises(self, tmp_path):
        _write_hydrology(tmp_path)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_esco(tmp_path, 0.0)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_esco(tmp_path, 1.5)

    def test_alpha_bf_writes_aquifer_rows(self, tmp_path):
        _write_aquifer(tmp_path)
        _apply_alpha_bf(tmp_path, 0.30)
        content = (tmp_path / "aquifer.aqu").read_text()
        assert "0.30000" in content
        # rchg_dp unchanged at 0.05000
        assert "0.05000" in content

    def test_rchg_dp_writes_aquifer_rows(self, tmp_path):
        _write_aquifer(tmp_path)
        _apply_rchg_dp(tmp_path, 0.0)
        content = (tmp_path / "aquifer.aqu").read_text()
        lines = content.split("\n")
        toks = lines[2].split()
        rchg_dp_idx = lines[1].split().index("rchg_dp")
        assert float(toks[rchg_dp_idx]) == 0.0

    def test_pet_co_writes_all_hru_rows(self, tmp_path):
        _write_hydrology(tmp_path)
        _apply_pet_co(tmp_path, 0.35)
        content = (tmp_path / "hydrology.hyd").read_text()
        lines = content.split("\n")
        assert "0.35000" in lines[2]
        assert "0.35000" in lines[3]
        # esco unchanged at 0.95000
        assert "0.95000" in lines[2]

    def test_pet_co_out_of_range_raises(self, tmp_path):
        _write_hydrology(tmp_path)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_pet_co(tmp_path, 0.0)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_pet_co(tmp_path, 2.0)

    def test_top_level_dispatch_applies_multiple(self, tmp_path):
        _write_cntable(tmp_path)
        _write_hydrology(tmp_path)
        _write_aquifer(tmp_path)
        apply_parameters_to_full_swat_txtinout(
            tmp_path,
            {"CN2": 75.0, "ESCO": 0.10, "ALPHA_BF": 0.40},
        )
        cn = (tmp_path / "cntable.lum").read_text()
        hyd = (tmp_path / "hydrology.hyd").read_text()
        aqu = (tmp_path / "aquifer.aqu").read_text()
        assert "75.00000" in cn  # wood_f cn_b now 75
        assert "0.10000" in hyd  # esco now 0.10
        assert "0.40000" in aqu  # alpha_bf now 0.40

    def test_unknown_parameter_raises(self, tmp_path):
        _write_cntable(tmp_path)
        with pytest.raises(ParameterBridgeError, match="Unknown"):
            apply_parameters_to_full_swat_txtinout(tmp_path, {"NOT_A_PARAM": 1.0})

    def test_rewrite_column_for_rows_preserves_other_columns(self, tmp_path):
        _write_hydrology(tmp_path)
        original = (tmp_path / "hydrology.hyd").read_text()
        _rewrite_column_for_rows(tmp_path / "hydrology.hyd", "epco", "0.25000", width=14)
        new = (tmp_path / "hydrology.hyd").read_text()
        # esco still 0.95000
        assert "0.95000" in new
        # epco changed to 0.25
        assert "0.25000" in new
        # row count preserved
        assert new.count("\n") == original.count("\n")
