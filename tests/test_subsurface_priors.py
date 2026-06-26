from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from swatplus_builder.full_mode.subsurface_priors import (
    apply_subsurface_prior_correction,
    finalize_subsurface_prior_correction,
)


def _write_fixture(
    run: Path,
    *,
    wateryld: float = 100.0,
    et: float = 400.0,
    perc: float = 500.0,
) -> Path:
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    (run / "delin").mkdir(parents=True, exist_ok=True)
    (run / "delin" / "validation_result.json").write_text(
        json.dumps({"delineated_area_km2": 100.0}) + "\n",
        encoding="utf-8",
    )
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        f"0 0 0 0 0 0 basin 1000 {et} 0 10 90 {perc} {wateryld}\n",
        encoding="utf-8",
    )
    (txt / "hydrology.hyd").write_text(
        "hydrology.hyd\n"
        "name lat_ttime lat_sed can_max esco epco orgn_enrich orgp_enrich cn3_swf bio_mix perco lat_orgn lat_orgp pet_co latq_co\n"
        "hyd1 0.00 0.00 0.00 0.95 1.00 0.00 0.00 0.95 0.00 0.90 0.00 0.00 1.00 0.01\n",
        encoding="utf-8",
    )
    (txt / "aquifer.aqu").write_text(
        "aquifer.aqu\n"
        "name flo_min revap_min alpha_bf revap rchg_dp spec_yld hlife flo_dist dep_bot dep_wt no3_n\n"
        "aqu1 3.00 0.00 0.05 0.00 0.05 0.00 0.00 0.00 0.00 0.00 0.00\n",
        encoding="utf-8",
    )
    return txt


def _obs_series_for_annual_depth(area_km2: float, depth_mm: float, n_days: int = 365) -> pd.Series:
    total_m3 = depth_mm / 1000.0 * area_km2 * 1_000_000.0
    q_m3s = total_m3 / (n_days * 86_400.0)
    return pd.Series(
        [q_m3s] * n_days,
        index=pd.date_range("2010-01-01", periods=n_days, freq="D"),
        name="obs",
    )


def test_subsurface_prior_applies_when_modeled_water_yield_is_far_below_observed(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = _write_fixture(run, wateryld=100.0)
    obs = _obs_series_for_annual_depth(100.0, 500.0)

    payload = apply_subsurface_prior_correction(run, txt, obs_series=obs)

    assert payload["status"] == "applied"
    assert payload["fresh_engine_rerun_required"] is True
    assert payload["modeled_wateryld_to_precip_before"] == pytest.approx(0.1)
    assert payload["observed_runoff"]["observed_runoff_to_precip"] == pytest.approx(0.5, rel=0.01)
    changes = {(c["file"], c["column"]): c for c in payload["parameter_changes"]}
    assert changes[("hydrology.hyd", "perco")]["old_value"] == pytest.approx(0.9)
    assert changes[("hydrology.hyd", "perco")]["new_value"] == pytest.approx(0.75)
    assert changes[("hydrology.hyd", "cn3_swf")]["new_value"] == pytest.approx(0.85)
    assert changes[("hydrology.hyd", "latq_co")]["new_value"] == pytest.approx(0.08)
    assert changes[("aquifer.aqu", "alpha_bf")]["new_value"] == pytest.approx(0.08)
    assert changes[("aquifer.aqu", "rchg_dp")]["new_value"] == pytest.approx(0.04)
    assert changes[("aquifer.aqu", "flo_min")]["new_value"] == pytest.approx(2.0)
    assert (run / "reports" / "subsurface_prior_correction.json").is_file()


def test_subsurface_prior_skips_when_modeled_water_yield_is_near_observed(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = _write_fixture(run, wateryld=410.0)
    obs = _obs_series_for_annual_depth(100.0, 500.0)

    payload = apply_subsurface_prior_correction(run, txt, obs_series=obs)

    assert payload["status"] == "not_applied"
    assert "within" in payload["reason"]
    assert "parameter_changes" not in payload


def test_subsurface_prior_reports_already_applied_profile_when_water_yield_is_near_observed(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = _write_fixture(run, wateryld=100.0)
    obs = _obs_series_for_annual_depth(100.0, 500.0)
    first = apply_subsurface_prior_correction(run, txt, obs_series=obs)
    assert first["status"] == "applied"
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 0 0 basin 1000 400 0 10 90 300 410\n",
        encoding="utf-8",
    )

    payload = apply_subsurface_prior_correction(run, txt, obs_series=obs)

    assert payload["status"] == "already_applied"
    assert payload["current_profile_state"]["matches_profile"] is True
    assert payload["fresh_engine_rerun_required"] is False


def test_subsurface_prior_skips_et_dominated_deficits(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = _write_fixture(run, wateryld=150.0, et=820.0, perc=25.0)
    obs = _obs_series_for_annual_depth(100.0, 500.0)

    payload = apply_subsurface_prior_correction(run, txt, obs_series=obs)

    assert payload["status"] == "not_applied"
    assert "et_to_precip" in payload["reason"]
    assert "parameter_changes" not in payload


def test_subsurface_prior_requires_excessive_percolation_partition(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = _write_fixture(run, wateryld=150.0, et=500.0, perc=50.0)
    obs = _obs_series_for_annual_depth(100.0, 500.0)

    payload = apply_subsurface_prior_correction(run, txt, obs_series=obs)

    assert payload["status"] == "not_applied"
    assert "perc_to_precip" in payload["reason"]
    assert "parameter_changes" not in payload


def test_subsurface_prior_finalize_records_post_rerun_improvement(tmp_path: Path) -> None:
    run = tmp_path / "run"
    txt = _write_fixture(run, wateryld=100.0)
    obs = _obs_series_for_annual_depth(100.0, 500.0)
    payload = apply_subsurface_prior_correction(run, txt, obs_series=obs)
    _write_fixture(run, wateryld=470.0)

    finalized = finalize_subsurface_prior_correction(run, txt, payload)

    assert finalized["status"] == "applied_improved"
    assert finalized["water_balance_after"]["wateryld_to_precip"] == pytest.approx(0.47)
    assert finalized["improvement"]["improved_toward_observed_qp"] is True
