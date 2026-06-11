from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.output.et_diagnostics import write_et_partition_diagnostics


def test_et_partition_diagnostics_flags_partition_context(tmp_path: Path) -> None:
    gates = {
        "status": "failed",
        "dominant_blocker": "ET_DOMINATED",
        "condition_codes": ["ET_DOMINATED"],
        "wb": {
            "precip": 1000.0,
            "et": 780.0,
            "pet": 1200.0,
            "esoil": 600.0,
            "eplant": 150.0,
            "ecanopy": 30.0,
            "wateryld": 200.0,
            "perc": 20.0,
            "latq": 4.0,
            "sw_init": 300.0,
            "sw_final": 325.0,
        },
    }

    report = write_et_partition_diagnostics(
        tmp_path / "run",
        physical_gates=gates,
        values={"pct_fallback_soils": 1.0},
        gate_context="final_locked",
        physical_gates_source_path="physical_gates.json",
    )

    codes = {flag["code"] for flag in report["diagnostic_flags"]}
    assert {
        "et_to_precip_high",
        "pet_demand_exceeds_precip",
        "soil_evaporation_dominates_et",
        "plant_transpiration_fraction_low",
        "percolation_partition_low",
        "lateral_flow_partition_low",
        "water_yield_partition_low",
    } <= codes
    assert report["water_balance"]["et_to_precip"] == 0.78
    assert report["soil_context"]["soil_degraded"] is True
    assert report["gate_context"] == "final_locked"
    assert report["physical_gates_source_path"] == "physical_gates.json"
    assert any("PET_CO/ESCO/EPCO" in action for action in report["next_actions"])
    alternatives = {row["option"]: row for row in report["source_backed_alternatives"]}
    assert "audit_pet_forcing_or_pet_method" in alternatives
    assert alternatives["audit_pet_forcing_or_pet_method"]["parameters"] == ["PET_CO"]
    assert "screen_soil_evaporation_compensation" in alternatives
    assert alternatives["screen_soil_evaporation_compensation"]["parameters"] == ["ESCO"]
    assert "screen_plant_uptake_compensation_and_management" in alternatives
    assert alternatives["screen_plant_uptake_compensation_and_management"]["parameters"] == ["EPCO"]
    assert "defer_subsurface_partition_controls_until_soils_are_defensible" in alternatives
    assert alternatives["defer_subsurface_partition_controls_until_soils_are_defensible"]["parameters"] == [
        "LATQ_CO",
        "PERCO",
    ]
    assert "recover_authoritative_soil_provenance_before_et_claims" in alternatives
    assert report["recommended_probe_order"][0]["parameters"] == ["PET_CO"]
    assert Path(report["json_path"]).exists()
    assert Path(report["markdown_path"]).exists()

    saved = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    assert saved["dominant_blocker"] == "ET_DOMINATED"
    assert saved["gate_context"] == "final_locked"
    assert saved["source_backed_alternatives"][0]["option"] == "audit_pet_forcing_or_pet_method"
    md = Path(report["markdown_path"]).read_text(encoding="utf-8")
    assert "final_locked" in md
    assert "Source-Backed Alternatives" in md


def test_et_partition_diagnostics_screens_subsurface_when_soils_are_retained(tmp_path: Path) -> None:
    gates = {
        "status": "failed",
        "dominant_blocker": "ET_DOMINATED",
        "condition_codes": ["ET_DOMINATED"],
        "wb": {
            "precip": 1000.0,
            "et": 780.0,
            "pet": 900.0,
            "esoil": 300.0,
            "eplant": 300.0,
            "wateryld": 200.0,
            "perc": 20.0,
            "latq": 4.0,
        },
    }

    report = write_et_partition_diagnostics(
        tmp_path / "run",
        physical_gates=gates,
        values={
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
        },
    )

    alternatives = {row["option"]: row for row in report["source_backed_alternatives"]}
    assert "screen_subsurface_partition_controls_with_retained_soil_provenance" in alternatives
    assert alternatives["screen_subsurface_partition_controls_with_retained_soil_provenance"][
        "claim_impact"
    ] == "diagnostic_until_basin_specific_screen_and_final_gates_pass"
    actions = "\n".join(report["next_actions"])
    assert "retained soil provenance" in actions
    assert "Resolve degraded soil provenance" not in actions
