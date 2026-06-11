from __future__ import annotations

from pathlib import Path

from swatplus_builder.full_mode.water_balance_gate import check_water_balance


def _write_basin_wb(txt: Path) -> None:
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 0 0 basin 1000 300 0 100 100 200 500\n",
        encoding="utf-8",
    )


def test_pbias_blocks_diagnostic_and_research_tiers(tmp_path: Path) -> None:
    txt = tmp_path / "TxtInOut"
    _write_basin_wb(txt)

    result = check_water_balance(txt, nse=0.2, kge=0.5, pbias=78.3)

    assert result["pass"] is False
    assert any(str(c).startswith("VOLUME_BIAS") for c in result["conditions"])
    assert "VOLUME_BIAS" in result["condition_codes"]
    assert result["dominant_blocker"] == "VOLUME_BIAS"
    assert "volume mismatch" in str(result["recommended_next_action"])
    assert "diagnostic" in result["blocked_tiers"]
    assert "research_grade" in result["blocked_tiers"]


def test_zero_surface_runoff_blocks_diagnostic_and_research_tiers(tmp_path: Path) -> None:
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 0 0 basin 1000 300 0 0 100 200 500\n",
        encoding="utf-8",
    )

    result = check_water_balance(txt, nse=0.4, kge=0.5, pbias=5.0)

    assert result["pass"] is False
    assert "ZERO_SURFACE_RUNOFF" in result["condition_codes"]
    assert result["dominant_blocker"] == "ZERO_SURFACE_RUNOFF"
    assert "diagnostic" in result["blocked_tiers"]
    assert "research_grade" in result["blocked_tiers"]


def test_wetland_outflow_is_not_double_counted_as_net_mass_loss(tmp_path: Path) -> None:
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld wet_oflo\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 0 0 basin 1000 300 0 500 0 200 600 100\n",
        encoding="utf-8",
    )

    result = check_water_balance(txt, nse=0.4, kge=0.5, pbias=5.0)

    assert "MASS_IMBALANCE" not in result["condition_codes"]


def test_wetland_adjusted_mass_imbalance_still_blocks_research(tmp_path: Path) -> None:
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld wet_oflo\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 0 0 basin 1000 300 0 600 0 200 700 100\n",
        encoding="utf-8",
    )

    result = check_water_balance(txt, nse=0.4, kge=0.5, pbias=5.0)

    assert "MASS_IMBALANCE" in result["condition_codes"]
    assert "net_wateryld=600.0" in " ".join(result["conditions"])
    assert "research_grade" in result["blocked_tiers"]


def test_negative_nse_requires_documented_timing_limitation_even_when_kge_passes(tmp_path: Path) -> None:
    txt = tmp_path / "TxtInOut"
    _write_basin_wb(txt)

    blocked = check_water_balance(txt, nse=-0.2, kge=0.45, pbias=5.0)
    assert blocked["pass"] is False
    assert "NEGATIVE_SKILL" in blocked["condition_codes"]
    assert "No timing limitation was documented" in " ".join(blocked["conditions"])

    allowed = check_water_balance(
        txt,
        nse=-0.2,
        kge=0.45,
        pbias=5.0,
        timing_limitation_documented=True,
        timing_limitation_basis="Peak timing lag exceeds 1 day.",
    )
    assert allowed["pass"] is True
    assert "NEGATIVE_SKILL" not in allowed["condition_codes"]
    assert allowed["timing_limitation_documented"] is True
