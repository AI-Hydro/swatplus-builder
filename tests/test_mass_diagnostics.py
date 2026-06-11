from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.output.mass_diagnostics import write_mass_balance_diagnostics


def test_mass_balance_diagnostics_flags_closure_and_process_context(tmp_path: Path) -> None:
    gates = {
        "status": "failed",
        "dominant_blocker": "MASS_IMBALANCE",
        "condition_codes": ["ET_DOMINATED", "MASS_IMBALANCE"],
        "wb": {
            "precip": 1000.0,
            "wateryld": 320.0,
            "wet_oflo": 250.0,
            "et": 880.0,
            "perc": 20.0,
            "latq": 2.0,
            "surq_gen": 318.0,
            "sw_init": 200.0,
            "sw_final": 150.0,
        },
    }

    report = write_mass_balance_diagnostics(
        tmp_path / "run",
        physical_gates=gates,
        gate_context="baseline",
        physical_gates_source_path="physical_gates.json",
    )

    codes = {flag["code"] for flag in report["diagnostic_flags"]}
    assert {
        "mass_closure_residual_high",
        "wetland_outflow_material",
        "et_consumes_precip_during_mass_imbalance",
        "net_water_yield_low_after_wetland_outflow",
        "soil_storage_change_material",
        "lateral_flow_partition_low",
    } <= codes
    assert report["water_balance"]["closure_residual_abs_pct_of_precip"] == 3.0
    assert report["water_balance"]["wetland_outflow_to_precip"] == 0.25
    assert report["gate_context"] == "baseline"
    alternatives = {row["option"]: row for row in report["source_backed_alternatives"]}
    assert "audit_basin_water_balance_closure_terms" in alternatives
    assert "audit_wetland_storage_and_outflow_accounting" in alternatives
    assert alternatives["repair_et_partition_before_mass_claim"]["parameters"] == [
        "PET_CO",
        "ESCO",
        "EPCO",
    ]
    assert alternatives["audit_soil_storage_and_subsurface_partition"]["parameters"] == [
        "PERCO",
        "LATQ_CO",
        "LAT_TTIME",
    ]
    assert report["recommended_probe_order"][0]["diagnostic"] == "audit_basin_water_balance_closure_terms"
    assert Path(report["json_path"]).exists()
    assert Path(report["markdown_path"]).exists()

    saved = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    assert saved["dominant_blocker"] == "MASS_IMBALANCE"
    assert saved["physical_gates_source_path"] == "physical_gates.json"
    md = Path(report["markdown_path"]).read_text(encoding="utf-8")
    assert "Mass Balance Diagnostics" in md
    assert "Source-Backed Alternatives" in md
