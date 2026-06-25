"""Tests for swatplus_builder.governance — pure gate logic with no hydrology imports."""
from __future__ import annotations

from pathlib import Path

from swatplus_builder.governance import (
    CLAIM_TIERS,
    benchmark_lock_gate,
    calibration_improvement_gate,
    fresh_engine_gate,
    landuse_fidelity_gate,
    outlet_provenance_gate,
    research_metric_gate,
    soil_fidelity_gate,
    tier_rank,
)
from swatplus_builder.governance.gates import sensitivity_gate
from swatplus_builder.governance.tiers import higher_tier

# ---------------------------------------------------------------------------
# Tier hierarchy
# ---------------------------------------------------------------------------

def test_claim_tiers_ordered_low_to_high() -> None:
    ranks = [tier_rank(t) for t in CLAIM_TIERS]
    assert ranks == sorted(ranks)


def test_tier_rank_research_grade_highest() -> None:
    assert tier_rank("research_grade") > tier_rank("exploratory")
    assert tier_rank("exploratory") > tier_rank("blocked")


def test_higher_tier_returns_better() -> None:
    assert higher_tier("research_grade", "exploratory") == "research_grade"
    assert higher_tier("blocked", "exploratory") == "exploratory"
    assert higher_tier("exploratory", "exploratory") == "exploratory"


# ---------------------------------------------------------------------------
# No hydrology imports in governance package
# ---------------------------------------------------------------------------

def test_governance_module_has_no_hydrology_imports() -> None:
    import swatplus_builder.governance.gates as gates_mod
    import swatplus_builder.governance.tiers as tiers_mod
    for mod in (gates_mod, tiers_mod):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        import_lines = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
        import_block = "\n".join(import_lines)
        for forbidden in ("swatplus_builder", "orchestrate", "params"):
            assert forbidden not in import_block, (
                f"{mod.__name__} imports hydrology module {forbidden!r}:\n{import_block}"
            )


# ---------------------------------------------------------------------------
# research_metric_gate
# ---------------------------------------------------------------------------

def test_research_metric_gate_passes_good_metrics() -> None:
    result = research_metric_gate({"metrics": {"kge": 0.55, "nse": 0.40, "pbias": 10.0}})
    assert result["passed"] is True


def test_research_metric_gate_fails_low_kge() -> None:
    result = research_metric_gate({"metrics": {"kge": 0.20, "nse": 0.50, "pbias": 5.0}})
    assert result["passed"] is False
    assert "KGE" in result["reason"]


def test_research_metric_gate_fails_high_pbias() -> None:
    result = research_metric_gate({"metrics": {"kge": 0.60, "nse": 0.50, "pbias": 40.0}})
    assert result["passed"] is False
    assert "PBIAS" in result["reason"]


def test_research_metric_gate_negative_nse_with_documented_timing_passes() -> None:
    result = research_metric_gate({
        "metrics": {"kge": 0.50, "nse": -0.10, "pbias": 10.0},
        "timing_limitation_documented": True,
    })
    assert result["passed"] is True


def test_research_metric_gate_missing_metrics_fails() -> None:
    result = research_metric_gate({})
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# soil_fidelity_gate
# ---------------------------------------------------------------------------

def test_soil_fidelity_gate_passes_gnatsgo_zero_fallback() -> None:
    result = soil_fidelity_gate({
        "soil_mode": "high_fidelity",
        "soil_provenance_mode": "gnatsgo_raster",
        "pct_fallback_soils": 0.0,
    })
    assert result["passed"] is True


def test_soil_fidelity_gate_fails_fallback_soils() -> None:
    result = soil_fidelity_gate({
        "soil_mode": "high_fidelity",
        "soil_provenance_mode": "gnatsgo_raster",
        "pct_fallback_soils": 0.15,
    })
    assert result["passed"] is False


def test_soil_fidelity_gate_fails_non_authoritative_provenance() -> None:
    result = soil_fidelity_gate({
        "soil_mode": "high_fidelity",
        "soil_provenance_mode": "ssurgo_tabular",
        "pct_fallback_soils": 0.0,
    })
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# landuse_fidelity_gate
# ---------------------------------------------------------------------------

def test_landuse_fidelity_gate_passes_full_overlay_complete_current_vintage() -> None:
    result = landuse_fidelity_gate({
        "landuse_fidelity": {
            "status": "evaluated",
            "hru_mode": "full_overlay",
            "landuse_class_retention_fraction": 1.0,
            "landuse_vintage_mismatch_years": 2,
        }
    })

    assert result["passed"] is True


def test_landuse_fidelity_gate_fails_dominant_only_and_old_vintage() -> None:
    result = landuse_fidelity_gate({
        "landuse_fidelity": {
            "status": "evaluated",
            "hru_mode": "dominant_only",
            "landuse_class_retention_fraction": 0.2,
            "landuse_vintage_mismatch_years": 14,
        }
    })

    assert result["passed"] is False
    assert "hru_mode=dominant_only" in result["reason"]
    assert "landuse_class_retention_fraction=0.20" in result["reason"]
    assert "landuse_vintage_mismatch_years=14.0" in result["reason"]


# ---------------------------------------------------------------------------
# fresh_engine_gate
# ---------------------------------------------------------------------------

def test_fresh_engine_gate_passes_with_artifact(tmp_path: Path) -> None:
    sim = tmp_path / "basin_sd_cha_day.txt"
    sim.write_text("data")
    result = fresh_engine_gate({
        "fresh_engine_run": True,
        "txtinout_dir": str(tmp_path),
    })
    assert result["passed"] is True


def test_fresh_engine_gate_fails_without_fresh_flag() -> None:
    result = fresh_engine_gate({"fresh_engine_run": False})
    assert result["passed"] is False


def test_fresh_engine_gate_fails_nonzero_returncode(tmp_path: Path) -> None:
    sim = tmp_path / "basin_sd_cha_day.txt"
    sim.write_text("data")
    result = fresh_engine_gate({
        "fresh_engine_run": True,
        "engine_returncode": 1,
        "txtinout_dir": str(tmp_path),
    })
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# benchmark_lock_gate
# ---------------------------------------------------------------------------

def test_benchmark_lock_gate_passes_with_file(tmp_path: Path) -> None:
    lock = tmp_path / "lock.json"
    lock.write_text("{}")
    result = benchmark_lock_gate({"benchmark_lock_path": str(lock)})
    assert result["passed"] is True


def test_benchmark_lock_gate_fails_missing_path() -> None:
    result = benchmark_lock_gate({})
    assert result["passed"] is False


def test_benchmark_lock_gate_fails_missing_file(tmp_path: Path) -> None:
    result = benchmark_lock_gate({"benchmark_lock_path": str(tmp_path / "nonexistent.json")})
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# outlet_provenance_gate
# ---------------------------------------------------------------------------

def test_outlet_provenance_gate_passes(tmp_path: Path) -> None:
    prov = tmp_path / "outlet_provenance.json"
    prov.write_text("{}")
    result = outlet_provenance_gate({
        "outlet_provenance_path": str(prov),
        "selected_outlet_gis_id": 42,
    })
    assert result["passed"] is True


def test_outlet_provenance_gate_fails_no_file() -> None:
    result = outlet_provenance_gate({"outlet_provenance_path": "/nonexistent/prov.json"})
    assert result["passed"] is False


def test_outlet_provenance_gate_fails_no_gis_id(tmp_path: Path) -> None:
    prov = tmp_path / "outlet_provenance.json"
    prov.write_text("{}")
    result = outlet_provenance_gate({"outlet_provenance_path": str(prov)})
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# calibration_improvement_gate
# ---------------------------------------------------------------------------

def test_calibration_improvement_gate_passes_on_delta_kge() -> None:
    result = calibration_improvement_gate({
        "calibration_success": True,
        "calibration_delta_metrics": {"kge": 0.05, "nse": -0.01},
    })
    assert result["passed"] is True


def test_calibration_improvement_gate_passes_on_basis() -> None:
    result = calibration_improvement_gate({
        "calibration_success": True,
        "calibration_provenance": {"verification_improvement_basis": "kge_improved"},
    })
    assert result["passed"] is True


def test_calibration_improvement_gate_fails_no_calibration() -> None:
    result = calibration_improvement_gate({"calibration_success": False})
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# sensitivity_gate (requires caller to supply param sets)
# ---------------------------------------------------------------------------

def test_sensitivity_gate_passes_with_basin_specific_screen() -> None:
    required = frozenset({"CN2", "ALPHA_BF", "GW_DELAY"})
    dead: frozenset[str] = frozenset()
    result = sensitivity_gate(
        {
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {
                "CN2": "active",
                "ALPHA_BF": "weak",
                "GW_DELAY": "active",
            },
        },
        required_params=required,
        dead_params=dead,
    )
    assert result["passed"] is True


def test_sensitivity_gate_fails_not_basin_specific() -> None:
    result = sensitivity_gate(
        {"sensitivity_screen_basis": "default"},
        required_params=frozenset({"CN2"}),
        dead_params=frozenset(),
    )
    assert result["passed"] is False


def test_sensitivity_gate_fails_missing_required_param() -> None:
    result = sensitivity_gate(
        {
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"ALPHA_BF": "active"},
        },
        required_params=frozenset({"CN2", "ALPHA_BF"}),
        dead_params=frozenset(),
    )
    assert result["passed"] is False
    assert "CN2" in result["reason"]


def test_sensitivity_gate_fails_unaccounted_dead_params() -> None:
    result = sensitivity_gate(
        {
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
        },
        required_params=frozenset({"CN2"}),
        dead_params=frozenset({"ESCO"}),
    )
    assert result["passed"] is False
    assert "ESCO" in result["reason"]
