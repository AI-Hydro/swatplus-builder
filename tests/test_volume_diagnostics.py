from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from swatplus_builder.output.volume_diagnostics import (
    build_terminal_scope_decision_request,
    write_volume_bias_diagnostics,
)


def _write_alignment(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "obs": [10.0, 12.0, 8.0, 10.0],
            "sim": [18.0, 20.0, 15.0, 18.0],
        },
        index=pd.date_range("2010-01-01", periods=4, freq="D"),
    )
    df.to_csv(path)


def _write_terminal_scope_outputs(run: Path, *, terminal_flows: tuple[float, float] = (4.0, 6.0)) -> None:
    outputs = run / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"obs": [10.0, 10.0, 10.0, 10.0]},
        index=pd.date_range("2010-01-01", periods=4, freq="D"),
    ).to_csv(outputs / "obs_q.csv", index_label="date")
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha01 1 0 out\n"
        "2 cha02 2 0 out\n",
        encoding="utf-8",
    )
    rows = []
    for i, date in enumerate(pd.date_range("2010-01-01", periods=4, freq="D"), start=1):
        rows.append(f"{i} {date.month} {date.day} {date.year} 1 1 cha01 {terminal_flows[0]}")
        rows.append(f"{i} {date.month} {date.day} {date.year} 2 2 cha02 {terminal_flows[1]}")
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_out\n"
        "m^3/s\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def test_terminal_scope_decision_request_is_package_owned_for_provenance() -> None:
    resolution = {
        "decision_type": "selected_outlet_scope_authority_required",
        "next_experiment": "confirm_selected_terminal_drainage_area_or_rebuild_claim_outlet",
    }

    decision = build_terminal_scope_decision_request(
        basin_id="02129000",
        blocker_domain="provenance",
        terminal_scope_resolution_plan=resolution,
    )

    assert decision["status"] == "needs_input"
    assert decision["question_id"] == "02129000_outlet_scope_authority"
    assert decision["decision_type"] == "selected_outlet_scope_authority_required"
    assert decision["recommended_next_experiment"] == (
        "confirm_selected_terminal_drainage_area_or_rebuild_claim_outlet"
    )
    assert decision["accepted_by_required"] == "user_or_policy"
    option_ids = [option["id"] for option in decision["options"]]
    assert option_ids == [
        "confirm_selected_terminal_authority",
        "authorize_virtual_all_terminal_outlet",
        "retain_exploratory_until_outlet_rebuilt",
    ]
    all_terminal = next(
        option for option in decision["options"] if option["id"] == "authorize_virtual_all_terminal_outlet"
    )
    assert all_terminal["requires"] == [
        "virtual_outlet_authority",
        "virtual_outlet_scope_gate",
        "same_scope_sensitivity_calibration_and_verification",
    ]


def test_terminal_scope_decision_request_uses_provenance_context() -> None:
    decision = build_terminal_scope_decision_request(
        basin_id="01013500",
        blocker_domain="provenance",
        terminal_scope_resolution_plan={
            "decision_type": "selected_outlet_scope_authority_required",
            "next_experiment": "confirm_selected_terminal_drainage_area_or_rebuild_claim_outlet",
        },
        terminal_scope_provenance_context={
            "terminal_authority_area_check": {
                "reference_area_source": "usgs_site_drainage_area",
                "class": "selected_terminal_partial_basin_all_terminal_matches_authoritative_area",
                "selected_fraction": 0.481,
                "all_terminal_fraction": 0.986,
            },
            "terminal_virtual_outlet_candidate": {
                "available": True,
                "status": "diagnostic_only_authority_required",
                "candidate_type": "all_terminal_virtual_outlet",
                "claim_authority": False,
                "temporary_terminal_metrics_allowed_as_final": False,
                "fresh_locked_rerun_required": True,
                "all_terminal_aggregation_valid": True,
                "all_terminal_aggregation_reason": "all_terminal_area_matches_authority",
                "terminal_gis_ids": [1, 2],
                "required_before_claim": [
                    "document_gauge_outlet_is_represented_by_all_terminal_aggregation",
                    "make_virtual_outlet_selection_explicit_in_outlet_provenance",
                    "relock_benchmark_against_virtual_all_terminal_outlet",
                    "rerun_clean_locked_txtinout_before_reporting_metrics",
                ],
            },
            "terminal_outlet_conflict": {
                "class": "selected_largest_terminal_not_nearest_minor_branch_conflict",
            },
            "terminal_area_scope": {
                "class": "selected_terminal_partial_basin_all_terminal_matches_authoritative_area",
            },
        },
    )

    assert decision["recommended_option"] == "authorize_virtual_all_terminal_outlet"
    evidence = decision["outlet_scope_evidence"]
    assert evidence["reference_area_source"] == "usgs_site_drainage_area"
    assert evidence["authority_area_class"] == (
        "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
    )
    assert evidence["selected_fraction_of_authority_area"] == 0.481
    assert evidence["all_terminal_fraction_of_authority_area"] == 0.986
    assert evidence["virtual_all_terminal_candidate_supported"] is True
    assert evidence["virtual_candidate_status"] == "diagnostic_only_authority_required"
    assert evidence["virtual_terminal_gis_ids"] == [1, 2]
    assert {
        "selected_terminal_partial_authoritative_area",
        "all_terminal_matches_authoritative_area",
        "virtual_all_terminal_candidate_available",
        "selected_outlet_not_nearest_terminal",
    }.issubset(set(evidence["evidence_flags"]))
    assert {
        "document_gauge_outlet_is_represented_by_all_terminal_aggregation",
        "make_virtual_outlet_selection_explicit_in_outlet_provenance",
        "relock_benchmark_against_virtual_all_terminal_outlet",
        "rerun_clean_locked_txtinout_before_reporting_metrics",
    }.issubset(set(evidence["required_before_claim"]))


def test_terminal_scope_decision_request_uses_post_aggregation_context() -> None:
    decision = build_terminal_scope_decision_request(
        basin_id="03349000",
        blocker_domain="diagnostics",
        terminal_scope_resolution_plan={
            "decision_type": "post_aggregation_process_deficit",
            "next_experiment": "diagnose_weather_et_runoff_subsurface_deficit_after_terminal_scope",
        },
        post_aggregation_process_context={
            "available": True,
            "soil_degraded": True,
            "likely_process_domains": [
                "soil_provenance_limited",
                "et_fraction_high",
                "subsurface_partition_low",
                "swat_water_yield_below_observed_runoff",
            ],
            "recommended_focus": [
                "repair_soil_provenance_before_parameter_attribution",
                "audit_pet_et_partition_and_soil_evaporation_controls",
            ],
            "candidate_explanations": [
                {
                    "domain": "soil_provenance_limited",
                    "status": "soil_provenance_degraded",
                    "evidence": "soil_provenance_mode=diagnostic_partial_gnatsgo_constant",
                    "next_action": "repair_soil_provenance_before_parameter_attribution",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "soil_fidelity_blocks_research_grade_until_repaired_and_rerun",
                },
                {
                    "domain": "et_fraction_high",
                    "status": "et_fraction_high",
                    "evidence": "SWAT ET/P=0.84",
                    "next_action": "audit_pet_et_partition_and_soil_evaporation_controls",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "et_partition_controls_are_diagnostic_until_fresh_locked_gates_pass",
                },
            ],
        },
    )

    assert decision["status"] == "diagnostic_only"
    assert decision["recommended_option"] == "repair_soil_provenance_before_parameter_attribution"
    assert decision["likely_process_domains"] == [
        "soil_provenance_limited",
        "et_fraction_high",
        "subsurface_partition_low",
        "swat_water_yield_below_observed_runoff",
    ]
    explanations = {item["domain"]: item for item in decision["candidate_explanations"]}
    assert explanations["soil_provenance_limited"]["status"] == "soil_provenance_degraded"
    assert explanations["et_fraction_high"]["next_action"] == (
        "audit_pet_et_partition_and_soil_evaporation_controls"
    )
    option_ids = [option["id"] for option in decision["options"]]
    assert option_ids[:4] == [
        "repair_soil_provenance_before_parameter_attribution",
        "screen_pet_and_et_partition_controls",
        "screen_subsurface_partition_controls_after_soil_provenance",
        "diagnose_post_aggregation_water_balance_deficit",
    ]
    assert "run_source_backed_diagnostic" in option_ids
    assert "retain_exploratory_science_blocker" in option_ids


def test_volume_bias_diagnostics_flags_runoff_and_outlet_context(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_alignment(run / "benchmark" / "alignment.csv")
    raw = run / "raw"
    raw.mkdir(parents=True)
    raster_path = raw / "nlcd_2021.tif"
    transform = from_origin(0, 3, 1, 1)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=1,
        dtype="int16",
        crs="EPSG:5070",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(
            pd.DataFrame(
                [
                    [21, 22, 23],
                    [24, 22, 41],
                    [41, 22, 11],
                ]
            ).to_numpy(dtype="int16"),
            1,
        )
    gpd.GeoDataFrame({"id": [1]}, geometry=[box(0, 0, 3, 3)], crs="EPSG:5070").to_file(
        raw / "basin_boundary.gpkg"
    )
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "hru_wb_aa.txt").write_text(
        "hru_wb_aa\n"
        "jday mon day yr unit gis_id name precip surq_gen wateryld cn\n"
        "mm mm mm mm mm mm mm mm mm mm ---\n"
        "365 12 31 2019 1 1 hru01 1000 760 760 98\n"
        "365 12 31 2019 2 2 hru02 1000 740 740 97\n"
        "365 12 31 2019 3 3 hru03 1000 300 450 80\n",
        encoding="utf-8",
    )
    (txt / "hru-data.hru").write_text(
        "hru-data.hru\n"
        "id name topo hydro soil lu_mgt soil_plant_init surf_stor snow field\n"
        "1 hru01 top1 hyd1 soil1 urhd_lum init null snow null\n"
        "2 hru02 top2 hyd2 soil2 urhd_lum init null snow null\n"
        "3 hru03 top3 hyd3 soil3 frsd_lum init null snow null\n",
        encoding="utf-8",
    )
    (txt / "landuse.lum").write_text(
        "landuse.lum\n"
        "name cal_group plnt_com mgt cn2 cons_prac urban urb_ro ov_mann tile sep vfs grww bmp\n"
        "urhd_lum null null null urban up_down_slope urhd buildup urban_asphalt null null null null null\n"
        "frsd_lum null frsd_comm null wood_f up_down_slope null null forest_med null null null null null\n",
        encoding="utf-8",
    )
    (txt / "urban.urb").write_text(
        "urban.urb\n"
        "name frac_imp frac_dc_imp curb_den urb_wash dirt_max t_halfmax conc_totn conc_totp conc_no3n urb_cn description\n"
        "urhd 0.60000 0.44000 0.24000 0.18000 225.00000 0.75000 550.00000 223.00000 7.20000 98.00000 Residential-High\n",
        encoding="utf-8",
    )
    (run / "outputs").mkdir(parents=True)
    (run / "outputs" / "outlet_provenance.json").write_text(
        json.dumps(
            {
                "selection_pass": {
                    "diagnostics": {
                        "outlet_autodetected": True,
                        "outlet_selection_reason": "requested_outlet_non_terminal_single_terminal",
                        "requested_outlet_gis_id": 1,
                        "requested_outlet_is_terminal": False,
                        "selected_outlet_gis_id": 8,
                        "terminal_outlet_count": 4,
                        "terminal_outlet_ids": [8, 18, 24, 30],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    gates = {
        "status": "failed",
        "dominant_blocker": "VOLUME_BIAS",
        "condition_codes": ["VOLUME_BIAS", "NEGATIVE_SKILL"],
        "recommended_next_action": "Diagnose simulated/observed volume mismatch before calibration.",
        "wb": {
            "precip": 1000.0,
            "et": 300.0,
            "wateryld": 760.0,
            "surq_gen": 700.0,
            "latq": 5.0,
            "perc": 10.0,
            "cn": 94.0,
        },
    }

    report = write_volume_bias_diagnostics(
        run,
        physical_gates=gates,
        values={
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
        },
    )
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    codes = [f["code"] for f in persisted["diagnostic_flags"]]

    assert persisted["primary_issue"] == "simulated_volume_excess"
    assert persisted["alignment"]["pbias_pct"] > 70.0
    assert persisted["hru_runoff"]["cn_p90"] >= 97.0
    assert persisted["landuse_raster"]["urban_fraction"] > 0.5
    assert persisted["urban_assumptions"]["hru_weighted_urb_cn"] == 98.0
    assert "surface_runoff_partition_high" in codes
    assert "hru_cn_distribution_extreme" in codes
    assert "urban_landuse_dominates_runoff_response" in codes
    assert "urban_curve_number_fixed_high" in codes
    assert "outlet_provenance_needs_review" in codes
    assert "outlet_reason_terminal_count_mismatch" in codes
    alternatives = {row["option"]: row for row in persisted["source_backed_alternatives"]}
    assert "audit_curve_number_and_landuse_soil_mapping" in alternatives
    assert alternatives["audit_curve_number_and_landuse_soil_mapping"]["parameters"] == ["CN2"]
    assert "audit_developed_land_and_urban_curve_number_assumptions" in alternatives
    assert "audit_outlet_selection_against_terminal_inventory" in alternatives
    assert persisted["recommended_probe_order"][0]["diagnostic"] == "audit_curve_number_and_landuse_soil_mapping"
    assert Path(report["markdown_path"]).exists()
    markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
    assert "Source-Backed Alternatives" in markdown
    assert "Recommended Probe Order" in markdown


def test_volume_bias_diagnostics_flags_et_dominated_deficit(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_alignment(run / "benchmark" / "alignment.csv")
    alignment = pd.read_csv(run / "benchmark" / "alignment.csv", index_col=0)
    alignment["sim"] = [5.0, 7.0, 4.0, 6.0]
    alignment.to_csv(run / "benchmark" / "alignment.csv")
    gates = {
        "status": "failed",
        "dominant_blocker": "VOLUME_BIAS",
        "condition_codes": ["ET_DOMINATED", "MASS_IMBALANCE", "VOLUME_BIAS", "BELOW_RESEARCH_SKILL"],
        "recommended_next_action": "Diagnose simulated/observed volume mismatch before calibration; parameter search is blocked.",
        "wb": {
            "precip": 1177.441,
            "et": 965.589,
            "eplant": 168.960,
            "esoil": 782.174,
            "wateryld": 180.833,
            "surq_gen": 178.548,
            "latq": 2.285,
            "perc": 25.968,
            "wet_oflo": 354.437,
            "pet": 1210.0,
            "cn": 68.0,
        },
    }

    report = write_volume_bias_diagnostics(run, physical_gates=gates)
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    codes = [f["code"] for f in persisted["diagnostic_flags"]]

    assert persisted["primary_issue"] == "simulated_volume_deficit"
    assert "et_partition_high" in codes
    assert "soil_evaporation_dominates_et" in codes
    assert "basin_water_yield_fraction_low" in codes
    assert "subsurface_partition_low" in codes
    assert "mass_closure_residual_high" in codes
    assert persisted["water_balance"]["et_to_precip"] > 0.80
    assert persisted["water_balance"]["esoil_to_et"] > 0.80
    assert persisted["water_balance"]["mass_residual_basis"] == "net_wateryld_excludes_wet_oflo"
    actions = "\n".join(persisted["next_actions"])
    assert "PET_CO within 0.8-1.2" in actions
    assert "legacy out-of-range PET_CO" in actions
    assert "retained soil provenance" in actions
    assert "water-balance accounting" in actions
    alternatives = {row["option"]: row for row in persisted["source_backed_alternatives"]}
    assert alternatives["screen_pet_and_et_partition_controls"]["parameters"] == ["PET_CO", "ESCO", "EPCO"]
    assert persisted["soil_context"]["soil_degraded"] is False
    assert alternatives["screen_subsurface_partition_controls_with_retained_soil_provenance"]["parameters"] == [
        "LATQ_CO",
        "PERCO",
        "ALPHA_BF",
        "RCHG_DP",
    ]
    assert alternatives["audit_basin_water_balance_closure_terms"]["parameters"] == []
    assert alternatives["audit_basin_water_balance_closure_terms"]["claim_impact"] == (
        "research_grade_blocked_until_mass_closure_is_explained"
    )
    assert persisted["recommended_probe_order"][0]["diagnostic"] == "screen_pet_and_et_partition_controls"


def test_volume_bias_diagnostics_flags_selected_terminal_scope_for_deficit(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_alignment(run / "benchmark" / "alignment.csv")
    _write_terminal_scope_outputs(run)
    alignment = pd.read_csv(run / "benchmark" / "alignment.csv", index_col=0)
    alignment["sim"] = [4.0, 5.0, 3.0, 4.0]
    alignment.to_csv(run / "benchmark" / "alignment.csv")
    mass_trace = run / "reports" / "mass_trace.json"
    mass_trace.parent.mkdir(parents=True)
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "terminal_trace.json").write_text(
        json.dumps(
            {
                "selected_outlet_gis_id": 1,
                "gauge_coordinate_source": "delin/shapes/outlets.gpkg",
                "selected_outlet_distance_to_gauge_m": 1200.0,
                "shared_upstream_area_km2": 0.0,
                "all_terminal_upstream_area_km2": 100.0,
                "terminal_inventory": [
                    {
                        "terminal_gis_id": 1,
                        "is_selected_evaluation_outlet": True,
                        "is_nearest_terminal": False,
                        "distance_to_usgs_outlet_m": 1200.0,
                    },
                    {
                        "terminal_gis_id": 2,
                        "is_selected_evaluation_outlet": False,
                        "is_nearest_terminal": True,
                        "distance_to_usgs_outlet_m": 100.0,
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mass_trace.write_text(
        json.dumps(
            {
                "closure_status": "fail_mass_closure",
                "terminal_outlet_count": 4,
                "selected_terminal_fraction_of_all_terminal_flow": 0.42,
                "all_terminal_routed_to_channel_closure_ratio": 0.97,
                "all_terminal_mass_closure_ratio": 1.88,
                "flags": [
                    "multiple_terminal_outlets_present",
                    "selected_terminal_partial_of_all_terminal_flow",
                    "all_terminal_routed_to_channel_reference_matches",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    routing_gate = run / "routing_flow_gates.json"
    routing_gate.write_text(
        json.dumps(
            {
                "closure_status": "fail_mass_closure",
                "terminal_outlet_count": 4,
                "selected_terminal_fraction_of_all_terminal_flow": 0.42,
                "all_terminal_routed_to_channel_closure_ratio": 0.97,
                "all_terminal_mass_closure_ratio": 1.88,
                "selected_outlet_gis_id": 1,
                "terminal_outlet_ids": [1, 2],
                "json_path": str(mass_trace),
                "flags": [
                    "multiple_terminal_outlets_present",
                    "selected_terminal_partial_of_all_terminal_flow",
                    "all_terminal_routed_to_channel_reference_matches",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gates = {
        "status": "failed",
        "dominant_blocker": "VOLUME_BIAS",
        "condition_codes": ["VOLUME_BIAS"],
        "wb": {"precip": 1000.0, "et": 400.0, "wateryld": 500.0, "latq": 20.0, "perc": 30.0},
    }

    report = write_volume_bias_diagnostics(run, physical_gates=gates)
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    codes = [f["code"] for f in persisted["diagnostic_flags"]]

    assert persisted["primary_issue"] == "simulated_volume_deficit"
    assert persisted["routing_scope"]["selected_terminal_fraction_of_all_terminal_flow"] == 0.42
    assert persisted["routing_scope"]["all_terminal_routed_to_channel_closure_ratio"] == 0.97
    assert persisted["terminal_hydrograph_scope"]["available"] is True
    assert persisted["terminal_hydrograph_scope"]["diagnostic_only"] is True
    assert persisted["terminal_hydrograph_scope"]["selected_terminal"]["pbias_pct"] == -60.0
    assert persisted["terminal_hydrograph_scope"]["nearest_terminal_gis_id"] == 2
    assert persisted["terminal_hydrograph_scope"]["nearest_terminal"]["pbias_pct"] == -40.0
    assert persisted["terminal_hydrograph_scope"]["nearest_vs_selected_pbias_abs_improvement_pct_points"] == 20.0
    assert persisted["terminal_hydrograph_scope"]["all_terminal"]["pbias_pct"] == 0.0
    assert (
        persisted["terminal_hydrograph_scope"]["all_terminal"]["kge_components"]["method"]
        == "kge_2009_components"
    )
    assert "kge_dominant_deficit" in persisted["terminal_hydrograph_scope"]["all_terminal"]
    assert persisted["terminal_hydrograph_scope_class"] == (
        "all_terminal_volume_corrected_but_skill_limited"
    )
    assert persisted["terminal_hydrograph_scope_claim_impact"] == (
        "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
    )
    assert "selected_outlet_not_nearest_terminal" in persisted["terminal_hydrograph_scope_flags"]
    assert "diagnose_timing_variability_or_peak_response" in persisted[
        "terminal_hydrograph_scope_recommended_focus"
    ]
    resolution = persisted["terminal_scope_resolution_plan"]
    assert resolution["status"] == "blocked_until_resolved"
    assert resolution["decision_type"] == "all_terminal_volume_diagnostic_not_claim_authority"
    assert resolution["next_experiment"] == "resolve_claim_authoritative_outlet_then_diagnose_skill"
    assert resolution["fresh_locked_rerun_required"] is True
    assert resolution["temporary_terminal_metrics_allowed_as_final"] is False
    assert resolution["all_terminal_metrics_claim_authority"] is False
    assert resolution["nearest_terminal_metrics_claim_authority"] is False
    assert resolution["all_terminal"]["pbias_pct"] == 0.0
    assert "resolve_selected_vs_nearest_terminal_conflict" in resolution["required_before_promotion"]
    decision = persisted["terminal_scope_decision_request"]
    assert decision["status"] == "diagnostic_only"
    assert decision["recommended_next_experiment"] == (
        "resolve_claim_authoritative_outlet_then_diagnose_skill"
    )
    assert decision["accepted_by_required"] == "agent_or_policy"
    assert persisted["terminal_scope_blocker"] == "outlet_scope_volume_mismatch"
    assert "selected_terminal_partial_of_all_terminal_flow" in codes
    assert "selected_terminal_not_nearest_gauge_terminal" in codes
    assert "nearest_terminal_hydrograph_volume_closer" in codes
    assert "all_terminal_routed_to_channel_reference_matches" in codes
    assert "all_terminal_hydrograph_volume_closer" in codes
    assert "all_terminal_hydrograph_volume_gate_passes_diagnostic" in codes
    actions = "\n".join(persisted["next_actions"])
    assert "selected-vs-all terminal hydrographs" in actions
    assert "Do not promote all-terminal hydrograph metrics" in actions
    alternatives = {row["option"]: row for row in persisted["source_backed_alternatives"]}
    assert "audit_outlet_selection_against_terminal_inventory" in alternatives
    assert "audit_selected_vs_nearest_terminal_hydrographs" in alternatives
    assert "audit_selected_vs_all_terminal_hydrographs" in alternatives
    assert "reports/mass_trace.json" in alternatives["audit_outlet_selection_against_terminal_inventory"]["required_artifacts"]
    assert persisted["recommended_probe_order"][0]["diagnostic"] == "audit_outlet_selection_against_terminal_inventory"
    assert persisted["recommended_probe_order"][1]["diagnostic"] == "audit_selected_vs_nearest_terminal_hydrographs"
    assert persisted["recommended_probe_order"][2]["diagnostic"] == "audit_selected_vs_all_terminal_hydrographs"
    markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
    assert "Routing Scope" in markdown
    assert "Terminal Hydrograph Scope" in markdown


def test_volume_bias_diagnostics_flags_persistent_all_terminal_volume_deficit(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_alignment(run / "benchmark" / "alignment.csv")
    _write_terminal_scope_outputs(run, terminal_flows=(4.0, 2.0))
    alignment = pd.read_csv(run / "benchmark" / "alignment.csv", index_col=0)
    alignment["obs"] = 10.0
    alignment["sim"] = 4.0
    alignment.to_csv(run / "benchmark" / "alignment.csv")
    mass_trace = run / "reports" / "terminal_trace.json"
    mass_trace.parent.mkdir(parents=True, exist_ok=True)
    mass_trace.write_text(
        json.dumps(
            {
                "all_terminal_aggregation_valid": True,
                "all_terminal_aggregation_reason": "no_material_terminal_upstream_overlap",
                "terminal_failure_class": "multi_terminal_requires_aggregation",
                "shared_upstream_area_km2": 0.0,
                "all_terminal_upstream_area_km2": 100.0,
                "terminal_outlets": [
                    {"terminal_gis_id": 1, "selected_outlet": True, "is_nearest_terminal": True},
                    {"terminal_gis_id": 2, "selected_outlet": False, "is_nearest_terminal": False},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "routing_flow_gates.json").write_text(
        json.dumps(
            {
                "closure_status": "fail_mass_closure",
                "terminal_outlet_count": 2,
                "selected_terminal_fraction_of_all_terminal_flow": 0.67,
                "all_terminal_routed_to_channel_closure_ratio": 0.97,
                "selected_outlet_gis_id": 1,
                "terminal_outlet_ids": [1, 2],
                "json_path": str(mass_trace),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gates = {
        "status": "failed",
        "dominant_blocker": "VOLUME_BIAS",
        "condition_codes": ["VOLUME_BIAS"],
        "wb": {"precip": 1000.0, "et": 400.0, "wateryld": 500.0, "latq": 20.0, "perc": 30.0},
    }

    report = write_volume_bias_diagnostics(run, physical_gates=gates)
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    codes = [f["code"] for f in persisted["diagnostic_flags"]]
    alternatives = {row["option"]: row for row in persisted["source_backed_alternatives"]}

    assert persisted["terminal_hydrograph_scope"]["selected_terminal"]["pbias_pct"] == -60.0
    assert persisted["terminal_hydrograph_scope"]["all_terminal"]["pbias_pct"] == -40.0
    assert persisted["terminal_hydrograph_scope_class"] == (
        "all_terminal_volume_deficit_persists_after_valid_aggregation"
    )
    assert "all_terminal_volume_deficit_persists" in persisted["terminal_hydrograph_scope_flags"]
    assert "diagnose_post_aggregation_water_balance_deficit" in persisted[
        "terminal_hydrograph_scope_recommended_focus"
    ]
    assert "all_terminal_hydrograph_volume_closer" in codes
    assert "all_terminal_hydrograph_volume_deficit_persists" in codes
    assert "all_terminal_hydrograph_volume_gate_passes_diagnostic" not in codes
    assert persisted["terminal_scope_blocker"] == "multi_terminal_volume_deficit"
    resolution = persisted["terminal_scope_resolution_plan"]
    assert resolution["decision_type"] == "post_aggregation_process_deficit"
    assert resolution["next_experiment"] == (
        "diagnose_weather_et_runoff_subsurface_deficit_after_terminal_scope"
    )
    assert "treat_remaining_volume_deficit_as_process_or_forcing_blocker" in resolution[
        "required_before_promotion"
    ]
    assert "diagnose_post_aggregation_water_balance_deficit" in alternatives
    assert alternatives["diagnose_post_aggregation_water_balance_deficit"]["fresh_output_required"] is True
    process_context = persisted["post_aggregation_process_context"]
    assert process_context["available"] is True
    assert process_context["status"] == "diagnostic_only_process_or_forcing_blocker"
    assert process_context["claim_authority"] is False
    assert process_context["temporary_metrics_allowed_as_final"] is False
    assert process_context["fresh_locked_rerun_required"] is True
    assert process_context["all_terminal_pbias_pct"] == -40.0
    assert process_context["swat_net_wateryld_to_precip"] == 0.5
    assert process_context["likely_process_domains"] == ["process_deficit_unresolved"]
    assert process_context["candidate_explanations"] == [
        {
            "domain": "process_deficit_unresolved",
            "status": "process_deficit_unresolved",
            "evidence": "Qobs/P=n/a; SWAT net wateryld/P=0.5",
            "next_action": "review_water_balance_forcing_et_runoff_and_subsurface_terms",
            "fresh_locked_rerun_required": True,
            "claim_impact": "unresolved_process_deficit_blocks_research_grade_until_explained",
        }
    ]
    assert "document_post_aggregation_volume_deficit_source" in process_context["required_before_claim"]
    decision = persisted["terminal_scope_decision_request"]
    assert decision["recommended_option"] == "diagnose_post_aggregation_water_balance_deficit"
    assert [
        option["id"] for option in decision["options"][:3]
    ] == [
        "diagnose_post_aggregation_water_balance_deficit",
        "run_source_backed_diagnostic",
        "retain_exploratory_science_blocker",
    ]
    assert persisted["recommended_probe_order"][0]["diagnostic"] == "audit_outlet_selection_against_terminal_inventory"
    assert persisted["recommended_probe_order"][1]["diagnostic"] == "audit_selected_vs_all_terminal_hydrographs"
    assert any(
        row["diagnostic"] == "diagnose_post_aggregation_water_balance_deficit"
        for row in persisted["recommended_probe_order"]
    )


def test_terminal_scope_diagnostics_use_explicit_locked_sim_source(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_terminal_scope_outputs(run, terminal_flows=(4.0, 2.0))
    locked = run / "calibration" / "locked_calibrated_TxtInOut"
    locked.mkdir(parents=True)
    rows = []
    for i, date in enumerate(pd.date_range("2010-01-01", periods=4, freq="D"), start=1):
        rows.append(f"{i} {date.month} {date.day} {date.year} 1 1 cha01 8.0")
        rows.append(f"{i} {date.month} {date.day} {date.year} 2 2 cha02 2.0")
    locked_source = locked / "channel_sd_day.txt"
    locked_source.write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_out\n"
        "m^3/s\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    alignment = pd.DataFrame(
        {"obs": [10.0, 10.0, 10.0, 10.0], "sim": [10.0, 10.0, 10.0, 10.0]},
        index=pd.date_range("2010-01-01", periods=4, freq="D"),
    )
    alignment_path = locked / "alignment_calibration.csv"
    alignment.to_csv(alignment_path)
    terminal_trace = run / "reports" / "terminal_trace.json"
    terminal_trace.parent.mkdir(parents=True, exist_ok=True)
    terminal_trace.write_text(
        json.dumps(
            {
                "all_terminal_aggregation_valid": True,
                "all_terminal_aggregation_reason": "no_material_terminal_upstream_overlap",
                "terminal_failure_class": "multi_terminal_requires_aggregation",
                "shared_upstream_area_km2": 0.0,
                "all_terminal_upstream_area_km2": 100.0,
                "terminal_outlets": [
                    {"terminal_gis_id": 1, "selected_outlet": True, "is_nearest_terminal": True},
                    {"terminal_gis_id": 2, "selected_outlet": False, "is_nearest_terminal": False},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    routing_gates = run / "routing_flow_gates.json"
    routing_gates.write_text(
        json.dumps(
            {
                "closure_status": "pass",
                "terminal_outlet_count": 2,
                "selected_terminal_fraction_of_all_terminal_flow": 0.8,
                "all_terminal_routed_to_channel_closure_ratio": 1.0,
                "selected_outlet_gis_id": 1,
                "terminal_outlet_ids": [1, 2],
                "terminal_trace_path": str(terminal_trace),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = write_volume_bias_diagnostics(
        run,
        physical_gates={"status": "passed", "condition_codes": []},
        values={
            "alignment_csv": str(alignment_path),
            "routing_flow_gates_path": str(routing_gates),
            "sim_source_path": str(locked_source),
        },
    )
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    codes = [f["code"] for f in persisted["diagnostic_flags"]]

    assert persisted["alignment"]["pbias_pct"] == 0.0
    assert persisted["terminal_hydrograph_scope"]["sim_source_path"] == str(locked_source)
    assert persisted["terminal_hydrograph_scope"]["selected_terminal"]["pbias_pct"] == -20.0
    assert persisted["terminal_hydrograph_scope"]["all_terminal"]["pbias_pct"] == 0.0
    assert "simulated_volume_deficit" not in codes
    assert "selected_terminal_partial_of_all_terminal_flow" in codes
    assert "all_terminal_routed_to_channel_reference_matches" in codes


def test_volume_bias_diagnostics_retains_high_runoff_demand_context(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_alignment(run / "benchmark" / "alignment.csv")
    _write_terminal_scope_outputs(run, terminal_flows=(4.0, 2.0))
    outputs = run / "outputs"
    pd.DataFrame(
        {"obs": [0.868, 0.868, 0.868, 0.868]},
        index=pd.date_range("2010-01-01", periods=4, freq="D"),
    ).to_csv(outputs / "obs_q.csv", index_label="date")
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    (txt / "pcp.cli").write_text(
        "pcp.cli: Precipitation file names\nfilename\nsta1.pcp\n",
        encoding="utf-8",
    )
    (txt / "sta1.pcp").write_text(
        "sta1.pcp: Precipitation data\n"
        "nbyr     tstep       lat       lon      elev\n"
        "   1         0    40.000   -86.000   200.000\n"
        "2010    1    1.00000\n"
        "2010    2    1.00000\n"
        "2010    3    1.00000\n"
        "2010    4    1.00000\n",
        encoding="utf-8",
    )
    (txt / "basin_aqu_aa.txt").write_text(
        "basin_aqu_aa\n"
        "jday mon day yr unit gis_id name flo dep_wt stor rchrg seep revap\n"
        "mm m mm mm mm mm\n"
        "365 12 31 2019 1 1 aqu01 2.0 3.0 100.0 8.0 1.0 4.0\n"
        "365 12 31 2019 2 2 aqu02 6.0 3.5 120.0 12.0 2.0 5.0\n",
        encoding="utf-8",
    )
    delin = run / "delin"
    delin.mkdir(parents=True)
    (delin / "validation_result.json").write_text(
        json.dumps({"reference_area_km2": 100.0}) + "\n",
        encoding="utf-8",
    )
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "terminal_trace.json").write_text(
        json.dumps(
            {
                "all_terminal_aggregation_valid": True,
                "all_terminal_aggregation_reason": "no_material_terminal_upstream_overlap",
                "terminal_failure_class": "multi_terminal_requires_aggregation",
                "shared_upstream_area_km2": 0.0,
                "all_terminal_upstream_area_km2": 100.0,
                "terminal_outlets": [
                    {"terminal_gis_id": 1, "selected_outlet": True, "is_nearest_terminal": True},
                    {"terminal_gis_id": 2, "selected_outlet": False, "is_nearest_terminal": False},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "routing_flow_gates.json").write_text(
        json.dumps(
            {
                "closure_status": "fail_mass_closure",
                "terminal_outlet_count": 2,
                "selected_terminal_fraction_of_all_terminal_flow": 0.67,
                "all_terminal_routed_to_channel_closure_ratio": 0.97,
                "all_terminal_mass_closure_ratio": 0.98,
                "selected_outlet_gis_id": 1,
                "terminal_outlet_ids": [1, 2],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gates = {
        "status": "failed",
        "dominant_blocker": "VOLUME_BIAS",
        "condition_codes": ["VOLUME_BIAS"],
        "wb": {
            "precip": 1000.0,
            "et": 250.0,
            "wateryld": 300.0,
            "surq_gen": 100.0,
            "latq": 100.0,
            "perc": 450.0,
            "snofall": 20.0,
            "snomlt": 18.0,
            "snopack": 1.0,
            "sw_change": 4.0,
            "laglatq": 30.0,
            "gwsoilq": 2.0,
        },
    }

    report = write_volume_bias_diagnostics(run, physical_gates=gates)
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    context = persisted["high_runoff_demand_context"]
    codes = [f["code"] for f in persisted["diagnostic_flags"]]

    assert "high_observed_runoff_fraction" in codes
    assert context["available"] is True
    assert context["runoff_precip_ratio_class"] == "high_observed_runoff_fraction"
    assert context["swat_net_wateryld_to_precip"] == 0.3
    assert context["swat_snowfall_to_precip"] == 0.02
    assert context["swat_snowmelt_to_precip"] == 0.018
    assert context["swat_lagged_lateral_flow_mm"] == 30.0
    assert context["aquifer_context_available"] is True
    assert context["aquifer_flow_mean_mm"] == 4.0
    assert context["aquifer_recharge_mean_mm"] == 10.0
    assert context["selected_terminal_fraction_of_all_terminal_flow"] == 0.67
    assert context["observed_area_to_all_terminal_area_ratio"] == 1.0
    flag_codes = {flag["code"] for flag in context["interpretation_flags"]}
    assert "swat_water_yield_far_below_observed_runoff_fraction" in flag_codes
    assert "snow_storage_not_explaining_high_runoff_demand" in flag_codes
    assert "aquifer_release_absent_for_high_runoff_demand" not in flag_codes
    assert "selected_terminal_partial_during_high_runoff_demand" in flag_codes
    assert "observed_area_mismatch_during_high_runoff_demand" not in flag_codes
    explanations = {
        item["hypothesis"]: item
        for item in context["candidate_explanations"]
    }
    assert explanations["precipitation_area_or_external_inflow_basis"]["status"] == (
        "area_matches_all_terminal_but_runoff_fraction_remains_high"
    )
    assert explanations["snow_storage_or_snowmelt_release"]["status"] == (
        "not_supported_by_current_swat_snow_terms"
    )
    assert explanations["groundwater_or_aquifer_release"]["status"] == (
        "aquifer_release_present_requires_baseflow_timing_audit"
    )
    assert explanations["selected_terminal_scope"]["status"] == "selected_terminal_partial"
    assert explanations["model_water_yield_deficit"]["status"] == (
        "swat_water_yield_far_below_observed_runoff_fraction"
    )
    assert "run_fresh_locked_rerun_after_high_runoff_repair" in context["required_before_claim"]
    alternatives = {row["option"]: row for row in persisted["source_backed_alternatives"]}
    assert "audit_high_observed_runoff_fraction_context" in alternatives
    high_runoff_parameters = alternatives["audit_high_observed_runoff_fraction_context"]["parameters"]
    assert "GW_DELAY" not in high_runoff_parameters
    assert {"SFTMP", "SMTMP", "LAT_TTIME", "ALPHA_BF", "RCHG_DP"}.issubset(
        set(high_runoff_parameters)
    )
    assert any(
        row["diagnostic"] == "audit_high_observed_runoff_fraction_context"
        for row in persisted["recommended_probe_order"]
    )


def test_volume_bias_diagnostics_blocks_all_terminal_gate_when_terminal_areas_overlap(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_alignment(run / "benchmark" / "alignment.csv")
    _write_terminal_scope_outputs(run)
    alignment = pd.read_csv(run / "benchmark" / "alignment.csv", index_col=0)
    alignment["sim"] = [4.0, 5.0, 3.0, 4.0]
    alignment.to_csv(run / "benchmark" / "alignment.csv")
    reports = run / "reports"
    reports.mkdir(parents=True)
    terminal_trace = reports / "terminal_trace.json"
    terminal_trace.write_text(
        json.dumps(
            {
                "failure_class": "generated_topology_mismatch",
                "shared_upstream_area_km2": 25.0,
                "all_terminal_upstream_area_km2": 100.0,
                "sum_terminal_upstream_area_km2": 125.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mass_trace = reports / "mass_trace.json"
    mass_trace.write_text(
        json.dumps(
            {
                "closure_status": "fail_mass_closure",
                "terminal_outlet_count": 2,
                "selected_terminal_fraction_of_all_terminal_flow": 0.40,
                "all_terminal_routed_to_channel_closure_ratio": 1.0,
                "flags": [
                    "multiple_terminal_outlets_present",
                    "selected_terminal_partial_of_all_terminal_flow",
                    "all_terminal_routed_to_channel_reference_matches",
                ],
                "terminal_trace_path": str(terminal_trace),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "routing_flow_gates.json").write_text(
        json.dumps(
            {
                "closure_status": "fail_mass_closure",
                "terminal_outlet_count": 2,
                "selected_terminal_fraction_of_all_terminal_flow": 0.40,
                "all_terminal_routed_to_channel_closure_ratio": 1.0,
                "selected_outlet_gis_id": 1,
                "terminal_outlet_ids": [1, 2],
                "json_path": str(mass_trace),
                "terminal_trace_path": str(terminal_trace),
                "flags": [
                    "multiple_terminal_outlets_present",
                    "selected_terminal_partial_of_all_terminal_flow",
                    "all_terminal_routed_to_channel_reference_matches",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gates = {
        "status": "failed",
        "dominant_blocker": "VOLUME_BIAS",
        "condition_codes": ["VOLUME_BIAS"],
        "wb": {"precip": 1000.0, "et": 400.0, "wateryld": 500.0},
    }

    report = write_volume_bias_diagnostics(run, physical_gates=gates)
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    codes = [f["code"] for f in persisted["diagnostic_flags"]]

    assert persisted["routing_scope"]["all_terminal_aggregation_valid"] is False
    assert persisted["terminal_hydrograph_scope"]["all_terminal_aggregation_valid"] is False
    assert persisted["terminal_hydrograph_scope"]["all_terminal"]["pbias_pct"] == 0.0
    assert persisted["terminal_hydrograph_scope_class"] == (
        "terminal_topology_overlap_invalidates_aggregation"
    )
    assert "all_terminal_aggregation_not_claim_valid" in persisted[
        "terminal_hydrograph_scope_flags"
    ]
    assert "all_terminal_hydrograph_aggregation_not_claim_valid" in codes
    assert "all_terminal_hydrograph_volume_closer" in codes
    assert "all_terminal_hydrograph_volume_gate_passes_diagnostic" not in codes
    assert persisted["terminal_scope_blocker"] == "terminal_topology_overlap"
    resolution = persisted["terminal_scope_resolution_plan"]
    assert resolution["decision_type"] == "terminal_topology_repair_required"
    assert resolution["next_experiment"] == "repair_terminal_topology_before_all_terminal_aggregation"
    assert "repair_or_explain_terminal_upstream_overlap" in resolution["required_before_promotion"]
    alternatives = {row["option"]: row for row in persisted["source_backed_alternatives"]}
    assert "audit_terminal_topology_overlap_before_aggregation" in alternatives
    markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
    assert "All-terminal aggregation valid: `False`" in markdown


def test_volume_bias_diagnostics_uses_net_wateryld_for_wetland_outflow(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_alignment(run / "benchmark" / "alignment.csv")
    gates = {
        "status": "failed",
        "dominant_blocker": "VOLUME_BIAS",
        "condition_codes": ["VOLUME_BIAS"],
        "wb": {
            "precip": 1000.0,
            "et": 300.0,
            "wateryld": 900.0,
            "wet_oflo": 300.0,
            "surq_gen": 250.0,
            "latq": 100.0,
            "perc": 100.0,
        },
    }

    report = write_volume_bias_diagnostics(run, physical_gates=gates)
    persisted = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
    wb = persisted["water_balance"]

    assert wb["wateryld_to_precip"] == 0.9
    assert wb["net_wateryld_to_precip"] == 0.6
    assert wb["wet_oflo_mm"] == 300.0
    assert wb["mass_residual_pct_of_precip"] == 0.0
    assert wb["mass_residual_basis"] == "net_wateryld_excludes_wet_oflo"
