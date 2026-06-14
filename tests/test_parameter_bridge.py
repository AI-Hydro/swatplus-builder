"""Tests for full-mode parameter bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from swatplus_builder.full_mode.parameter_bridge import (
    ParameterBridgeError,
    _apply_alpha_bf,
    _apply_ch_k2,
    _apply_ch_n2,
    _apply_cn2,
    _apply_cn3_swf,
    _apply_esco,
    _apply_lat_ttime,
    _apply_pet_co,
    _apply_rchg_dp,
    _apply_sftmp,
    _apply_smtmp,
    _apply_surlag,
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
        "urban                 98.00000      98.00000      98.00000      98.00000  Paved ----\n"
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


def _write_parameters_bsn(tio: Path) -> Path:
    p = tio / "parameters.bsn"
    p.write_text(
        "parameters.bsn: test fixture\n"
        "name       sw_init      surq_lag      adj_pkrt\n"
        "bsn            0.00000       4.00000       1.00000\n"
    )
    return p


def _write_snow(tio: Path) -> Path:
    p = tio / "snow.sno"
    p.write_text(
        "snow.sno: test fixture\n"
        "name                  fall_tmp      melt_tmp      melt_max      melt_min       tmp_lag      snow_h2o         cov50     snow_init\n"
        "snow001                1.00000       0.50000       4.50000       4.50000       1.00000       1.00000       0.50000       0.00000\n"
    )
    return p


def _write_hyd_sed_lte(tio: Path) -> Path:
    p = tio / "hyd-sed-lte.cha"
    p.write_text(
        "hyd-sed-lte.cha: test fixture\n"
        "name                         order            wd            dp           slp           len          mann             k     erod_fact      cov_fact\n"
        "hydcha01                         1      53.23400       1.55200       0.00277       1.75333       0.05000       1.00000       0.01000       0.00500\n"
        "hydcha02                         1      95.14100       2.28600       0.00282      11.71821       0.05000       1.00000       0.01000       0.00500\n"
    )
    return p


def _write_urban_inputs(tio: Path) -> None:
    (tio / "landuse.lum").write_text(
        "landuse.lum: test fixture\n"
        "name                         cal_group          plnt_com mgt cn2 cons_prac urban urb_ro ov_mann tile sep vfs grww bmp\n"
        "urmd_lum                          null              null null urban up_down_slope urmd buildup_washoff urban_asphalt null null null null null\n"
        "frsd_lum                          null         frsd_comm null wood_f up_down_slope null null forest_med null null null null null\n"
        "ucom_lum                          null              null null urban up_down_slope ucom buildup_washoff urban_asphalt null null null null null\n",
        encoding="utf-8",
    )
    (tio / "urban.urb").write_text(
        "urban.urb: test fixture\n"
        "name                  frac_imp   frac_dc_imp      curb_den      urb_wash      dirt_max     t_halfmax     conc_totn     conc_totp     conc_no3n        urb_cn  description\n"
        "urmd                   0.38000       0.30000       0.24000       0.18000     225.00000       0.75000     550.00000     223.00000       7.20000      98.00000  Residential-Medium\n"
        "ucom                   0.67000       0.62000       0.28000       0.18000     200.00000       1.60000     420.00000     240.00000       5.50000      98.00000  Commercial\n"
        "uidu                   0.84000       0.79000       0.14000       0.18000     400.00000       2.35000     430.00000     104.00000       5.60000      98.00000  Industrial\n",
        encoding="utf-8",
    )


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
            _apply_cn2(tmp_path, 34.9)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_cn2(tmp_path, 98.1)

    def test_cn2_documented_bounds_are_allowed(self, tmp_path):
        _write_cntable(tmp_path)
        _apply_cn2(tmp_path, 98.0)
        content = (tmp_path / "cntable.lum").read_text()
        assert "98.00000" in content

    def test_cn2_updates_referenced_urban_curve_numbers(self, tmp_path):
        _write_cntable(tmp_path)
        _write_urban_inputs(tmp_path)

        _apply_cn2(tmp_path, 74.0)

        cntable_lines = (tmp_path / "cntable.lum").read_text().splitlines()
        assert float(cntable_lines[5].split()[1]) == 74.0
        assert float(cntable_lines[5].split()[2]) == 74.0
        assert float(cntable_lines[5].split()[3]) == 74.0
        assert float(cntable_lines[5].split()[4]) == 74.0
        urban_lines = (tmp_path / "urban.urb").read_text().splitlines()
        assert float(urban_lines[2].split()[10]) == 74.0
        assert float(urban_lines[3].split()[10]) == 74.0
        assert float(urban_lines[4].split()[10]) == 98.0

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

    def test_surlag_uses_documented_parameters_bsn_range(self, tmp_path):
        _write_parameters_bsn(tmp_path)
        _apply_surlag(tmp_path, 1.0)
        content = (tmp_path / "parameters.bsn").read_text()
        assert "1.00000" in content
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_surlag(tmp_path, 0.5)

    def test_channel_routing_controls_write_hyd_sed_lte_columns(self, tmp_path):
        _write_hyd_sed_lte(tmp_path)

        _apply_ch_n2(tmp_path, 0.035)
        _apply_ch_k2(tmp_path, 12.5)

        lines = (tmp_path / "hyd-sed-lte.cha").read_text().splitlines()
        header = lines[1].split()
        mann_idx = header.index("mann")
        k_idx = header.index("k")
        assert float(lines[2].split()[mann_idx]) == 0.035
        assert float(lines[3].split()[mann_idx]) == 0.035
        assert float(lines[2].split()[k_idx]) == 12.5
        assert float(lines[3].split()[k_idx]) == 12.5
        with pytest.raises(ParameterBridgeError, match="CH_N2 out of range"):
            _apply_ch_n2(tmp_path, 0.013)
        with pytest.raises(ParameterBridgeError, match="CH_K2 out of range"):
            _apply_ch_k2(tmp_path, 500.1)

    def test_pet_co_writes_all_hru_rows(self, tmp_path):
        _write_hydrology(tmp_path)
        _apply_pet_co(tmp_path, 0.85)
        content = (tmp_path / "hydrology.hyd").read_text()
        lines = content.split("\n")
        assert "0.85000" in lines[2]
        assert "0.85000" in lines[3]
        # esco unchanged at 0.95000
        assert "0.95000" in lines[2]

    def test_pet_co_out_of_range_raises(self, tmp_path):
        _write_hydrology(tmp_path)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_pet_co(tmp_path, 0.79)
        with pytest.raises(ParameterBridgeError, match="out of range"):
            _apply_pet_co(tmp_path, 1.21)

    def test_lat_ttime_writes_all_hru_rows(self, tmp_path):
        _write_hydrology(tmp_path)
        _apply_lat_ttime(tmp_path, 20.0)

        lines = (tmp_path / "hydrology.hyd").read_text().splitlines()
        header = lines[1].split()
        lat_ttime_idx = header.index("lat_ttime")
        assert float(lines[2].split()[lat_ttime_idx]) == 20.0
        assert float(lines[3].split()[lat_ttime_idx]) == 20.0

    def test_lat_ttime_validates_documented_bounds(self, tmp_path):
        _write_hydrology(tmp_path)
        _apply_lat_ttime(tmp_path, 0.0)
        _apply_lat_ttime(tmp_path, 120.0)
        with pytest.raises(ParameterBridgeError, match="LAT_TTIME out of range"):
            _apply_lat_ttime(tmp_path, -0.1)
        with pytest.raises(ParameterBridgeError, match="LAT_TTIME out of range"):
            _apply_lat_ttime(tmp_path, 120.1)

    def test_cn3_swf_writes_soft_surface_runoff_control(self, tmp_path):
        _write_hydrology(tmp_path)

        _apply_cn3_swf(tmp_path, 0.25)

        lines = (tmp_path / "hydrology.hyd").read_text().splitlines()
        header = lines[1].split()
        cn3_swf_idx = header.index("cn3_swf")
        assert float(lines[2].split()[cn3_swf_idx]) == 0.25
        assert float(lines[3].split()[cn3_swf_idx]) == 0.25
        with pytest.raises(ParameterBridgeError, match="CN3_SWF out of range"):
            _apply_cn3_swf(tmp_path, -0.1)
        with pytest.raises(ParameterBridgeError, match="CN3_SWF out of range"):
            _apply_cn3_swf(tmp_path, 1.1)

    def test_snow_temperature_controls_write_snow_sno_columns(self, tmp_path):
        _write_snow(tmp_path)

        _apply_sftmp(tmp_path, 2.0)
        _apply_smtmp(tmp_path, -1.0)

        toks = (tmp_path / "snow.sno").read_text().splitlines()[2].split()
        header = (tmp_path / "snow.sno").read_text().splitlines()[1].split()
        assert float(toks[header.index("fall_tmp")]) == 2.0
        assert float(toks[header.index("melt_tmp")]) == -1.0
        assert float(toks[header.index("melt_max")]) == 4.5

    def test_snow_temperature_controls_validate_documented_bounds(self, tmp_path):
        _write_snow(tmp_path)
        _apply_sftmp(tmp_path, -5.0)
        _apply_smtmp(tmp_path, 5.0)
        with pytest.raises(ParameterBridgeError, match="SFTMP out of range"):
            _apply_sftmp(tmp_path, -5.1)
        with pytest.raises(ParameterBridgeError, match="SMTMP out of range"):
            _apply_smtmp(tmp_path, 5.1)

    def test_top_level_dispatch_applies_multiple(self, tmp_path):
        _write_cntable(tmp_path)
        _write_hydrology(tmp_path)
        _write_aquifer(tmp_path)
        _write_snow(tmp_path)
        _write_hyd_sed_lte(tmp_path)
        apply_parameters_to_full_swat_txtinout(
            tmp_path,
            {
                "CN2": 75.0,
                "ESCO": 0.10,
                "ALPHA_BF": 0.40,
                "SFTMP": 2.0,
                "LAT_TTIME": 30.0,
                "CN3_SWF": 0.25,
                "CH_N2": 0.035,
                "CH_K2": 12.5,
            },
        )
        cn = (tmp_path / "cntable.lum").read_text()
        hyd = (tmp_path / "hydrology.hyd").read_text()
        aqu = (tmp_path / "aquifer.aqu").read_text()
        snow = (tmp_path / "snow.sno").read_text()
        hyd_sed = (tmp_path / "hyd-sed-lte.cha").read_text()
        assert "75.00000" in cn  # wood_f cn_b now 75
        assert "0.10000" in hyd  # esco now 0.10
        assert "30.00000" in hyd  # lat_ttime now 30 days
        assert "0.25000" in hyd  # cn3_swf now 0.25
        assert "0.40000" in aqu  # alpha_bf now 0.40
        assert "2.00000" in snow  # fall_tmp now 2.0
        assert "0.03500" in hyd_sed  # channel Manning n now 0.035
        assert "12.50000" in hyd_sed  # channel alluvium conductivity now 12.5

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
