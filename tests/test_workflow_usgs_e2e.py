from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from swatplus_builder.calibration.diagnostic_calibrator import (
    DiagnosticCalibrationResult,
    PhaseRun,
    _annotate_skill_parameter_bound_context,
    _annotate_skill_sensitivity_gaps,
    _check_locked_txt_physical_gates,
    _check_locked_txt_routing_flow,
    _documented_timing_limitation,
    run_diagnostic_calibration,
)
from swatplus_builder.calibration.locked_benchmark import CalibrationEvidence, VerificationResult
from swatplus_builder.output.mass_trace import (
    classify_terminal_scope_blocker,
    trace_mass_balance,
    trace_terminal_inventory,
)
from swatplus_builder.params.governance import (
    FULL_MODE_CORE_PARAMETERS,
    FULL_MODE_EXTENDED_PARAMETERS,
    FULL_MODE_PARAMETER_GOVERNANCE,
)
from swatplus_builder.workflows.usgs_e2e import (
    RunUSGSWorkflowRequest,
    _annotate_parameter_screen_for_physical_context,
    _annotate_parameter_screen_for_volume_context,
    _calibration_precheck,
    _claim_lists,
    _effective_claim_tier,
    _evaluate_routing_flow_gate,
    _load_observed_series_for_relock,
    _promote_terminal_hydrograph_scope_values,
    _sensitivity_gate,
    _soil_fidelity_gate,
    _virtual_all_terminal_scope_gate,
    run_usgs_workflow,
)


def _core_sensitivity_classes() -> dict[str, str]:
    return {
        name: FULL_MODE_PARAMETER_GOVERNANCE[name].activity_class
        for name in FULL_MODE_CORE_PARAMETERS
        if FULL_MODE_PARAMETER_GOVERNANCE[name].activity_class != "dead"
    }


def _passing_landuse_fidelity() -> dict[str, object]:
    return {
        "status": "evaluated",
        "hru_mode": "full_overlay",
        "dominant_only": False,
        "n_hrus": 120,
        "n_subbasins": 31,
        "landuse_classes_present": ["AGRL", "FRSD"],
        "landuse_classes_retained": ["AGRL", "FRSD"],
        "landuse_class_retention_fraction": 1.0,
        "landuse_vintage_year": 2011,
        "sim_midpoint_year": 2014,
        "landuse_vintage_mismatch_years": -3,
    }


def _core_sensitivity_values(**overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "sensitivity_screen_basis": "basin_specific",
        "sensitivity_screen_activity_classes": _core_sensitivity_classes(),
        "calibration_provenance": {"blocked_parameters": ["GW_DELAY"]},
        "landuse_fidelity": _passing_landuse_fidelity(),
    }
    values.update(overrides)
    return values


def _write_basin_wb(txt: Path, *, precip: float = 1000.0, et: float = 300.0, perc: float = 200.0, wateryld: float = 500.0) -> None:
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 7 cha7 1.0 1.0\n",
        encoding="utf-8",
    )

    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        f"0 0 0 0 0 0 basin {precip} {et} 0 100 100 {perc} {wateryld}\n",
        encoding="utf-8",
    )


def test_terminal_scope_blocker_is_explicit_blocked_claim() -> None:
    _allowed, blocked = _claim_lists(
        requested_tier="research_grade",
        allowed_tier="research_grade",
        blocker=None,
        calibration_success=False,
        policy_notes=[],
        values={
            "fresh_engine_run": True,
            "benchmark_lock_path": "benchmark/benchmark_lock.json",
            "outlet_provenance_path": "outlet_provenance.json",
            "selected_outlet_gis_id": 7,
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
            "metrics": {"kge": 0.5, "nse": 0.1, "pbias": -20.0},
            "terminal_scope_blocker": "outlet_scope_volume_mismatch",
        },
        physical_gates={"status": "failed"},
        routing_gates={"status": "warning"},
    )

    claims = {claim["claim"]: claim for claim in blocked}
    assert claims["terminal_scope_claim"]["tier"] == "research_grade"
    assert claims["terminal_scope_claim"]["reason"] == "outlet_scope_volume_mismatch"


def test_terminal_scope_blocker_classified_from_routing_scope_evidence() -> None:
    blocker = classify_terminal_scope_blocker(
        {
            "status": "warning",
            "closure_status": "fail_mass_closure",
            "flags": [
                "multiple_terminal_outlets_present",
                "selected_terminal_partial_of_all_terminal_flow",
                "all_terminal_routed_to_channel_reference_matches",
            ],
            "selected_terminal_fraction_of_all_terminal_flow": 0.52,
            "all_terminal_routed_to_channel_closure_ratio": 1.01,
            "terminal_outlet_count": 4,
        }
    )

    assert blocker == "outlet_scope_volume_mismatch"


def test_terminal_scope_blocker_classifies_routing_overlap_before_outlet_scope() -> None:
    blocker = classify_terminal_scope_blocker(
        {
            "status": "warning",
            "closure_status": "fail_mass_closure",
            "flags": [
                "multiple_terminal_outlets_present",
                "selected_terminal_partial_of_all_terminal_flow",
                "all_terminal_routed_to_channel_reference_matches",
            ],
            "selected_terminal_fraction_of_all_terminal_flow": 0.52,
            "all_terminal_routed_to_channel_closure_ratio": 1.01,
            "terminal_outlet_count": 4,
            "terminal_shared_upstream_area_km2": 889.19,
            "terminal_overlap_pair_count": 3,
        }
    )

    assert blocker == "terminal_topology_overlap"


def test_routing_flow_gate_promotes_terminal_overlap_summary(monkeypatch, tmp_path: Path) -> None:
    import networkx as nx

    from swatplus_builder.output import mass_trace as mass_trace_module

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text('{"usgs_id":"fixture","selected_outlet_gis_id":2}\n', encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 cha1 1 10.0 40.2 -86.2 0 1 null 0 0 0 2 sdc 2 tot 1.00000 sdc 3 tot 1.00000\n"
        "2 cha2 2 20.0 40.0 -86.0 0 2 null 0 0 0 0\n"
        "3 cha3 3 30.0 40.1 -86.1 0 3 null 0 0 0 0\n",
        encoding="utf-8",
    )
    _write_basin_wb(txt, precip=1000.0, et=300.0, perc=200.0, wateryld=500.0)
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 2 cha2 50.0 50.0\n"
        "1 1 1 2010 1 3 cha3 20.0 20.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_edge("1", "2")
    graph.add_edge("1", "3")
    graph_path = run / "delin" / "routing_graph.graphml"
    graph_path.parent.mkdir(parents=True)
    nx.write_graphml(graph, graph_path)
    monkeypatch.setattr(
        mass_trace_module,
        "_subbasin_area_map",
        lambda _run: {1: 10.0, 2: 20.0, 3: 30.0},
    )

    gate = _evaluate_routing_flow_gate(run, {"usgs_id": "fixture", "txtinout_dir": str(txt)})

    assert gate["terminal_shared_upstream_area_km2"] == pytest.approx(10.0)
    assert gate["terminal_overlap_pair_count"] == 1
    assert gate["terminal_overlap_pairs"][0]["terminal_a_gis_id"] == 2
    assert gate["terminal_overlap_pairs"][0]["terminal_b_gis_id"] == 3
    assert classify_terminal_scope_blocker(gate) == "terminal_topology_overlap"


def test_terminal_scope_blocker_classified_when_passed_routing_is_partial_scope() -> None:
    blocker = classify_terminal_scope_blocker(
        {
            "status": "passed",
            "closure_status": "pass",
            "flags": [
                "multiple_terminal_outlets_present",
                "selected_terminal_partial_of_all_terminal_flow",
                "all_terminal_routed_to_channel_reference_matches",
            ],
            "selected_terminal_fraction_of_all_terminal_flow": 0.52,
            "all_terminal_routed_to_channel_closure_ratio": 1.01,
            "terminal_outlet_count": 4,
        }
    )

    assert blocker == "outlet_scope_volume_mismatch"


def test_terminal_scope_blocker_not_classified_when_passed_routing_scope_is_materially_complete() -> None:
    blocker = classify_terminal_scope_blocker(
        {
            "status": "passed",
            "closure_status": "pass",
            "flags": [
                "multiple_terminal_outlets_present",
                "all_terminal_outflow_differs_from_selected_terminal",
                "all_terminal_routed_to_channel_reference_matches",
            ],
            "selected_terminal_fraction_of_all_terminal_flow": 0.93,
            "all_terminal_routed_to_channel_closure_ratio": 0.95,
            "terminal_outlet_count": 2,
        }
    )

    assert blocker is None


def test_virtual_all_terminal_scope_gate_requires_clean_authorized_aggregation() -> None:
    gate = _virtual_all_terminal_scope_gate(
        {
            "outlet_scope": "virtual_all_terminal",
            "outlet_policy": "all_terminal_sum",
            "virtual_outlet_authority": "official_site_area_matches_all_terminal_candidate",
            "virtual_outlet_claim_authority": True,
            "selected_outlet_gis_ids": [7, 8],
        },
        {
            "terminal_outlet_count": 2,
            "terminal_overlap_pair_count": 0,
            "terminal_shared_upstream_area_km2": 0.0,
            "all_terminal_routed_to_channel_closure_ratio": 1.02,
            "all_terminal_outflow_m3": 100.0,
        },
    )

    assert gate["applicable"] is True
    assert gate["passed"] is True


def test_virtual_all_terminal_scope_gate_blocks_overlapping_aggregation() -> None:
    gate = _virtual_all_terminal_scope_gate(
        {
            "outlet_scope": "virtual_all_terminal",
            "outlet_policy": "all_terminal_sum",
            "virtual_outlet_authority": "official_site_area_matches_all_terminal_candidate",
            "virtual_outlet_claim_authority": True,
            "selected_outlet_gis_ids": [7, 8],
        },
        {
            "terminal_outlet_count": 2,
            "terminal_overlap_pair_count": 1,
            "terminal_shared_upstream_area_km2": 4.2,
            "all_terminal_routed_to_channel_closure_ratio": 1.02,
            "all_terminal_outflow_m3": 100.0,
        },
    )

    assert gate["passed"] is False
    assert "terminal_topology_overlap" in gate["blockers"]


def test_terminal_hydrograph_scope_class_promotes_to_workflow_values() -> None:
    values: dict[str, object] = {}
    promoted = _promote_terminal_hydrograph_scope_values(
        values,
        {
            "terminal_hydrograph_scope": {
                "available": True,
                "diagnostic_only": True,
                "selected_terminal": {"pbias_pct": 2.0},
                "all_terminal": {"pbias_pct": 35.0},
            },
            "terminal_hydrograph_scope_class": "selected_metric_passes_but_area_scope_partial",
            "terminal_hydrograph_scope_flags": [
                "selected_terminal_metric_gate_passes",
                "selected_terminal_scope_partial",
            ],
            "terminal_hydrograph_scope_recommended_focus": [
                "confirm_gauge_drainage_area_against_selected_terminal",
                "audit_outlet_selection_against_terminal_inventory",
            ],
            "terminal_hydrograph_scope_claim_impact": (
                "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
            ),
            "terminal_scope_decision_request": {
                "status": "needs_input",
                "question_id": "02129000_outlet_scope_authority",
                "decision_type": "selected_outlet_scope_authority_required",
                "accepted_by_required": "user_or_policy",
            },
        },
    )

    assert values["terminal_hydrograph_scope_class"] == (
        "selected_metric_passes_but_area_scope_partial"
    )
    assert values["terminal_hydrograph_scope_flags"] == [
        "selected_terminal_metric_gate_passes",
        "selected_terminal_scope_partial",
    ]
    assert values["terminal_hydrograph_scope_recommended_focus"][0] == (
        "confirm_gauge_drainage_area_against_selected_terminal"
    )
    assert promoted["terminal_hydrograph_scope_claim_impact"] == (
        "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
    )
    assert values["terminal_scope_decision_request"]["question_id"] == (
        "02129000_outlet_scope_authority"
    )
    assert promoted["terminal_scope_decision_request"]["accepted_by_required"] == "user_or_policy"


def _touch_benchmark_lock(run_dir: Path) -> str:
    lock = run_dir / "benchmark" / "benchmark_lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("{}\n", encoding="utf-8")
    return str(lock)


def _passed_routing_gate(*args, **kwargs) -> dict:
    return {
        "status": "passed",
        "pass": True,
        "reason": "routing flow closure passed",
        "closure_status": "pass",
        "flags": [],
        "condition_codes": [],
        "terminal_outflow_m3": 1.0,
        "mass_closure_ratio": 1.0,
    }


def _partial_scope_passed_routing_gate(*args, **kwargs) -> dict:
    payload = _passed_routing_gate()
    payload.update(
        {
            "flags": [
                "multiple_terminal_outlets_present",
                "selected_terminal_partial_of_all_terminal_flow",
                "all_terminal_routed_to_channel_reference_matches",
            ],
            "terminal_outlet_count": 4,
            "selected_terminal_fraction_of_all_terminal_flow": 0.76,
            "all_terminal_routed_to_channel_closure_ratio": 0.93,
            "all_terminal_mass_closure_ratio": 0.93,
        }
    )
    return payload


def _virtual_scope_passed_routing_gate(*args, **kwargs) -> dict:
    payload = _passed_routing_gate()
    payload.update(
        {
            "flags": [
                "multiple_terminal_outlets_present",
                "selected_terminal_partial_of_all_terminal_flow",
                "all_terminal_routed_to_channel_reference_matches",
            ],
            "terminal_outlet_count": 2,
            "terminal_overlap_pair_count": 0,
            "terminal_shared_upstream_area_km2": 0.0,
            "selected_terminal_fraction_of_all_terminal_flow": 0.4,
            "all_terminal_routed_to_channel_closure_ratio": 1.0,
            "all_terminal_mass_closure_ratio": 1.0,
            "all_terminal_outflow_m3": 8.0,
        }
    )
    return payload


def test_soil_fidelity_gate_allows_authoritative_gnatsgo_provenance() -> None:
    gate = _soil_fidelity_gate(
        {
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
        }
    )

    assert gate["passed"] is True
    assert "gnatsgo_raster" in gate["reason"]


def test_claim_lists_block_terrain_lapse_derived_claim_when_defaults_flagged(tmp_path: Path) -> None:
    values = _research_grade_single_channel_values(tmp_path)
    values["terrain_climate_defaults"] = {
        "status": "evaluated",
        "diagnostic_flags": [
            "constant_slp_len",
            "constant_lat_len",
            "constant_dist_cha",
            "lapse_disabled",
        ],
        "claim_impact": "diagnostic_context_disclosed",
    }

    _allowed, blocked = _claim_lists(
        requested_tier="research_grade",
        allowed_tier="research_grade",
        blocker=None,
        calibration_success=False,
        policy_notes=[],
        values=values,
        physical_gates={"status": "passed"},
        routing_gates=_passed_routing_gate(),
    )

    terrain_claims = [c for c in blocked if c["claim"] == "terrain_length_or_lapse_derived_claim"]
    assert terrain_claims
    assert "constant_slp_len" in terrain_claims[0]["reason"]
    assert "lapse_disabled" in terrain_claims[0]["reason"]


def test_soil_fidelity_gate_blocks_missing_authoritative_provenance() -> None:
    gate = _soil_fidelity_gate(
        {
            "soil_mode": "high_fidelity",
            "pct_fallback_soils": 0.0,
        }
    )

    assert gate["passed"] is False
    assert "soil_provenance_mode=n/a" in gate["reason"]


def test_sensitivity_gate_requires_current_governed_core_coverage() -> None:
    narrow = _sensitivity_gate(
        _core_sensitivity_values(
            sensitivity_screen_activity_classes={
                "CN2": "active",
                "PERCO": "active",
                "LATQ_CO": "active",
                "ESCO": "weak",
            }
        )
    )

    assert narrow["passed"] is False
    assert "missing current governed core parameters" in narrow["reason"]
    assert "ALPHA_BF" in narrow["reason"]
    assert "SURLAG" in narrow["reason"]

    full = _sensitivity_gate(_core_sensitivity_values())

    assert full["passed"] is True
    assert "covers current governed core set" in full["reason"]


def test_sensitivity_gate_requires_dead_core_accounting() -> None:
    gate = _sensitivity_gate(
        {
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": _core_sensitivity_classes(),
        }
    )

    assert gate["passed"] is False
    assert "blocked/dead accounting" in gate["reason"]
    assert "GW_DELAY" in gate["reason"]


def test_contract_policy_blocks_research_without_acceptance(tmp_path: Path):
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run",
        claim_tier="research_grade",
        contract_status="draft",
        accepted_by=None,
    )
    res = run_usgs_workflow(req)
    assert res.success is False
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    assert data["blocker_class"] == "contract_policy_blocked"
    assert data["claim_tier"] == "diagnostic"
    assert data["effective_claim_tier"] == "exploratory"
    manifest_path = Path(res.artifact_dir, "run_manifest.json")
    assert manifest_path.exists()
    assert Path(res.artifact_dir, "parameter_screen.json").exists()
    assert Path(res.artifact_dir, "calibration_provenance.json").exists()
    evidence_md = Path(res.artifact_dir, "EVIDENCE_SUMMARY.md")
    assert evidence_md.exists()
    evidence_md_text = evidence_md.read_text(encoding="utf-8")
    assert "# Evidence Summary" in evidence_md_text
    assert "contract_policy_blocked" in evidence_md_text
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert Path(manifest["artifacts"]["evidence_summary_md"]) == evidence_md
    events_path = Path(res.artifact_dir, "events.jsonl")
    assert events_path.exists()
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events
    assert {event["run_id"] for event in events} == {res.run_id}
    assert {event["usgs_id"] for event in events} == {"01654000"}
    assert data["allowed_claims"]
    assert data["blocked_claims"]


def test_virtual_outlet_workflow_requires_authority(monkeypatch, tmp_path: Path) -> None:
    def fail_run_pipeline(**kwargs):
        raise AssertionError("pipeline should not run without virtual outlet authority")

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fail_run_pipeline)

    req = RunUSGSWorkflowRequest(
        usgs_id="02129000",
        out_dir=tmp_path / "run_virtual_missing_authority",
        claim_tier="research_grade",
        contract_status="accepted",
        accepted_by="user",
        start="2010-01-01",
        end="2019-12-31",
        virtual_all_terminal_outlet=True,
    )

    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert res.success is False
    assert data["blocker_class"] == "virtual_outlet_authority_required"
    assert data["values"]["virtual_all_terminal_outlet_requested"] is True
    assert "virtual_all_terminal_outlet_requires_authority" in data["values"]["policy_notes"]


def test_workflow_can_relock_virtual_all_terminal_benchmark(
    monkeypatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run_virtual"
    txt = run_dir / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_out\n"
        "n/a n/a n/a n/a n/a n/a n/a m3/s\n"
        "1 1 1 2010 7 7 cha07 1.0\n"
        "1 1 1 2010 8 8 cha08 2.0\n"
        "2 1 2 2010 7 7 cha07 2.0\n"
        "2 1 2 2010 8 8 cha08 3.0\n",
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "7 cha0007 7 0 0 0 0 7 s 0 0 0 0 out 1 tot 1.0\n"
        "8 cha0008 8 0 0 0 0 8 s 0 0 0 0 out 2 tot 1.0\n",
        encoding="utf-8",
    )
    obs_csv = run_dir / "outputs" / "obs_q.csv"
    obs_csv.parent.mkdir(parents=True)
    obs_csv.write_text(
        "date,discharge\n2010-01-01,3.0\n2010-01-02,5.0\n",
        encoding="utf-8",
    )

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "observed_csv": str(obs_csv),
            "fresh_engine_run": True,
            "sim_source_file": "channel_sd_day.txt",
            "benchmark_lock_path": str(run_dir / "benchmark" / "benchmark_lock.json"),
            "metrics": {"nse": -1.0, "kge": -1.0, "pbias": 99.0},
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e._evaluate_physical_gates",
        lambda values: {"status": "passed", "pass": True},
    )
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate",
        _virtual_scope_passed_routing_gate,
    )

    req = RunUSGSWorkflowRequest(
        usgs_id="02129000",
        out_dir=run_dir,
        claim_tier="diagnostic",
        start="2010-01-01",
        end="2019-12-31",
        calibrate=False,
        virtual_all_terminal_outlet=True,
        virtual_outlet_authority="official_site_area_matches_all_terminal_candidate",
    )

    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert res.success is True
    assert data["values"]["outlet_scope"] == "virtual_all_terminal"
    assert data["values"]["outlet_policy"] == "all_terminal_sum"
    assert data["values"]["selected_outlet_gis_ids"] == [7, 8]
    assert data["values"]["virtual_outlet_scope_gate_status"] == "passed"
    assert data["values"]["metrics"]["pbias"] == pytest.approx(0.0)
    claims = {claim["claim"]: claim for claim in data["allowed_claims"]}
    assert "virtual_all_terminal_outlet_scope_passed" in claims
    lock = json.loads(Path(data["values"]["benchmark_lock_path"]).read_text(encoding="utf-8"))
    assert lock["outlet_scope"] == "virtual_all_terminal"


def test_virtual_scope_gate_overrides_selected_scope_volume_diagnostic_blocker(
    monkeypatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run_virtual_volume_diag"
    txt = run_dir / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_out\n"
        "n/a n/a n/a n/a n/a n/a n/a m3/s\n"
        "1 1 1 2010 7 7 cha07 1.0\n"
        "1 1 1 2010 8 8 cha08 2.0\n"
        "2 1 2 2010 7 7 cha07 2.0\n"
        "2 1 2 2010 8 8 cha08 3.0\n",
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "7 cha0007 7 0 0 0 0 7 s 0 0 0 0 out 1 tot 1.0\n"
        "8 cha0008 8 0 0 0 0 8 s 0 0 0 0 out 2 tot 1.0\n",
        encoding="utf-8",
    )
    obs_csv = run_dir / "outputs" / "obs_q.csv"
    obs_csv.parent.mkdir(parents=True)
    obs_csv.write_text(
        "date,obs\n2010-01-01 05:00:00,3.0\n2010-01-02 05:00:00,5.0\n",
        encoding="utf-8",
    )

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "observed_csv": str(obs_csv),
            "fresh_engine_run": True,
            "sim_source_file": "channel_sd_day.txt",
            "benchmark_lock_path": str(run_dir / "benchmark" / "benchmark_lock.json"),
            "metrics": {"nse": -1.0, "kge": -1.0, "pbias": 99.0},
        }

    def fake_physical_gates(values):
        return {
            "status": "passed",
            "pass": True,
            "dominant_blocker": "VOLUME_BIAS",
            "condition_codes": ["VOLUME_BIAS"],
        }

    def fake_volume_diagnostics(run, *, physical_gates, values):
        report = Path(run) / "reports" / "volume_bias_diagnostics.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("{}\n", encoding="utf-8")
        return {
            "json_path": str(report),
            "markdown_path": str(report.with_suffix(".md")),
            "primary_issue": "all_terminal_hydrograph_volume_closer",
            "terminal_scope_blocker": "outlet_scope_volume_mismatch",
            "terminal_hydrograph_scope": {
                "available": True,
                "diagnostic_only": True,
                "selected_terminal": {"pbias_pct": -90.0},
                "all_terminal": {"pbias_pct": 0.0},
            },
            "terminal_hydrograph_scope_class": "all_terminal_volume_corrected_but_outlet_scope_unresolved",
            "terminal_hydrograph_scope_flags": ["all_terminal_volume_gate_passes_diagnostic"],
            "terminal_hydrograph_scope_recommended_focus": [
                "rerun_with_claim_authoritative_outlet_before_promotion"
            ],
            "terminal_hydrograph_scope_claim_impact": (
                "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
            ),
            "diagnostic_flags": [],
            "source_backed_alternatives": [],
            "recommended_probe_order": [],
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e._evaluate_physical_gates",
        fake_physical_gates,
    )
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate",
        _virtual_scope_passed_routing_gate,
    )
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e.write_volume_bias_diagnostics",
        fake_volume_diagnostics,
    )

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="02129000",
            out_dir=run_dir,
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="policy",
            start="2010-01-01",
            end="2019-12-31",
            calibrate=False,
            virtual_all_terminal_outlet=True,
            virtual_outlet_authority="official_site_area_matches_all_terminal_candidate",
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    blocked = {claim["claim"]: claim for claim in data["blocked_claims"]}

    assert data["values"]["virtual_outlet_scope_gate_status"] == "passed"
    assert data["values"]["terminal_scope_blocker"] is None
    assert "terminal_scope_claim" not in blocked


def test_virtual_scope_pass_can_support_research_tier_despite_selected_scope_blocker(
    tmp_path: Path,
) -> None:
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    (txt / "channel_sd_day.txt").write_text("nonempty\n", encoding="utf-8")
    lock = tmp_path / "benchmark_lock.json"
    lock.write_text("{}\n", encoding="utf-8")
    outlet = tmp_path / "outlet_provenance.json"
    outlet.write_text("{}\n", encoding="utf-8")
    values = _core_sensitivity_values(
        fresh_engine_run=True,
        engine_returncode=0,
        txtinout_dir=str(txt),
        sim_source_file="channel_sd_day.txt",
        benchmark_lock_path=str(lock),
        outlet_provenance_path=str(outlet),
        selected_outlet_gis_id=1,
        outlet_scope="virtual_all_terminal",
        outlet_policy="all_terminal_sum",
        virtual_outlet_authority="official_site_area_matches_all_terminal_candidate",
        virtual_outlet_claim_authority=True,
        selected_outlet_gis_ids=[7, 8],
        terminal_scope_blocker="outlet_scope_volume_mismatch",
        metrics={"nse": 0.44, "kge": 0.63, "pbias": 6.3},
        calibration_success=True,
        calibration_locked_verification_succeeded=True,
        calibration_delta_metrics={"nse": 0.20, "kge": 0.40},
        soil_mode="high_fidelity",
        soil_provenance_mode="gnatsgo_raster",
        pct_fallback_soils=0.0,
    )
    routing = _virtual_scope_passed_routing_gate()

    tier = _effective_claim_tier(
        allowed_tier="research_grade",
        blocker=None,
        calibration_success=True,
        values=values,
        physical_gates={"status": "passed"},
        routing_gates=routing,
    )

    assert tier == "research_grade"


def _research_grade_single_channel_values(tmp_path: Path, **overrides) -> dict[str, object]:
    """A clean single-channel basin that SHOULD earn a research_grade claim.

    This is the A2 positive-control fixture: every gate is satisfied along the
    canonical single-outlet path (no virtual all-terminal aggregation, no
    terminal-scope blocker). Until now the gate stack was only ever tested in
    the failing direction (and the one passing _effective_claim_tier test went
    through the virtual-scope path), so a real should-pass basin had no
    regression anchor — gate rigor was indistinguishable from a gate that can
    never pass. This fixture proves the stack CAN return research_grade.
    """
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    (txt / "channel_sd_day.txt").write_text("nonempty\n", encoding="utf-8")
    lock = tmp_path / "benchmark_lock.json"
    lock.write_text("{}\n", encoding="utf-8")
    outlet = tmp_path / "outlet_provenance.json"
    outlet.write_text("{}\n", encoding="utf-8")
    values = _core_sensitivity_values(
        fresh_engine_run=True,
        engine_returncode=0,
        txtinout_dir=str(txt),
        sim_source_file="channel_sd_day.txt",
        benchmark_lock_path=str(lock),
        outlet_provenance_path=str(outlet),
        selected_outlet_gis_id=1,
        # single natural outlet — virtual all-terminal scope is NOT engaged
        metrics={"nse": 0.62, "kge": 0.71, "pbias": 4.2},
        calibration_success=True,
        calibration_locked_verification_succeeded=True,
        calibration_delta_metrics={"nse": 0.30, "kge": 0.45},
        soil_mode="high_fidelity",
        soil_provenance_mode="gnatsgo_raster",
        pct_fallback_soils=0.0,
    )
    values.update(overrides)
    return values


def test_effective_claim_tier_research_grade_on_clean_single_channel_basin(
    tmp_path: Path,
) -> None:
    values = _research_grade_single_channel_values(tmp_path)

    tier = _effective_claim_tier(
        allowed_tier="research_grade",
        blocker=None,
        calibration_success=True,
        values=values,
        physical_gates={"status": "passed"},
        routing_gates=_passed_routing_gate(),
    )

    assert tier == "research_grade"


def test_claim_lists_clean_single_channel_basin_blocks_no_research_grade_claims(
    tmp_path: Path,
) -> None:
    values = _research_grade_single_channel_values(tmp_path)

    allowed, blocked = _claim_lists(
        requested_tier="research_grade",
        allowed_tier="research_grade",
        blocker=None,
        calibration_success=True,
        policy_notes=[],
        values=values,
        physical_gates={"status": "passed"},
        routing_gates=_passed_routing_gate(),
    )

    # The positive control's defining property: nothing at research_grade is blocked.
    research_grade_blocked = [c for c in blocked if c.get("tier") == "research_grade"]
    assert research_grade_blocked == [], (
        "clean single-channel basin should block no research_grade claims, "
        f"but got: {research_grade_blocked}"
    )

    # And the research_grade evidence claims are affirmatively allowed.
    allowed_claims = {c["claim"] for c in allowed}
    for required in (
        "outlet_provenance_verified",
        "research_metric_thresholds_passed",
        "calibration_improvement_verified",
        "basin_specific_sensitivity_screen_passed",
        "soil_fidelity_gate_passed",
    ):
        assert required in allowed_claims, f"expected {required} in allowed claims"


def test_virtual_relock_observed_loader_preserves_time_shifted_obs(tmp_path: Path) -> None:
    obs_csv = tmp_path / "obs_q.csv"
    obs_csv.write_text(
        "date,obs\n"
        "2010-01-01 05:00:00,348.29721308160003\n"
        "2010-01-02 05:00:00,342.63384376320005\n",
        encoding="utf-8",
    )

    series = _load_observed_series_for_relock(obs_csv)

    assert list(series.index.strftime("%Y-%m-%d")) == ["2010-01-01", "2010-01-02"]
    assert series.iloc[0] == pytest.approx(348.29721308160003)
    assert series.iloc[1] == pytest.approx(342.63384376320005)


def test_contract_policy_allows_research_with_window_and_acceptance(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run2" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "metrics": {"nse": 0.30, "kge": 0.45},
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run2",
        claim_tier="research_grade",
        contract_status="accepted",
        accepted_by="user",
        start="2010-01-01",
        end="2019-12-31",
        warmup_years=3,
    )
    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    assert data["claim_tier"] == "research_grade"
    assert data["effective_claim_tier"] == "exploratory"
    assert data["values"]["effective_claim_tier"] == "exploratory"
    assert "provenance_hash" in data
    assert data["values"]["policy_split"] == "chronological_60_40"
    assert data["values"]["calibration_start"] == "2010-01-01"
    assert data["values"]["validation_end"] == "2019-12-31"
    assert "calibration_attempted" in data["values"]
    assert "outlet_provenance_path" in data["values"]
    assert "parameter_screen_path" in data["values"]
    assert "calibration_provenance_path" in data["values"]
    assert "run_manifest_path" in data["values"]
    assert "allowed_claims" in data
    assert "blocked_claims" in data
    screen = json.loads(Path(res.artifact_dir, "parameter_screen.json").read_text(encoding="utf-8"))
    assert [p["parameter"] for p in screen["parameters"]] == list(
        FULL_MODE_CORE_PARAMETERS + FULL_MODE_EXTENDED_PARAMETERS
    )
    cal = json.loads(Path(res.artifact_dir, "calibration_provenance.json").read_text(encoding="utf-8"))
    assert cal["provenance"]["calibration_method"] == "locked_diagnostic_full_mode"
    assert cal["provenance"]["temporary_candidate_metrics_allowed_as_final"] is False
    assert "benchmark/benchmark_lock.json" in cal["provenance"]["missing_artifacts"]
    assert Path(res.artifact_dir, "physical_gates.json").exists()
    assert any(c["claim"] == "research_metric_thresholds_passed" for c in data["blocked_claims"])


def test_workflow_promotes_build_diagnostic_artifacts_to_evidence(monkeypatch, tmp_path: Path):
    overlay_report = tmp_path / "run_build_block" / "reports" / "overlay_repair" / "overlay_repair_report.json"
    overlay_report.parent.mkdir(parents=True)
    overlay_report.write_text('{"reason":"categorical_overlay_gap_too_large"}\n', encoding="utf-8")

    def fake_run_pipeline(**kwargs):
        return {
            "status": "BLOCKED",
            "blocker_class": "hru_overlay_realism_failed",
            "build": {
                "success": False,
                "status": "BLOCKED",
                "blocker_class": "hru_overlay_realism_failed",
                "diagnostic_artifacts": {
                    "overlay_repair_report": str(overlay_report),
                },
            },
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01013500",
            out_dir=tmp_path / "run_build_block",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="policy",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )

    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path(res.artifact_dir, "run_manifest.json").read_text(encoding="utf-8"))

    assert data["blocker_class"] == "hru_overlay_realism_failed"
    assert data["values"]["build_diagnostic_artifacts"]["overlay_repair_report"] == str(overlay_report)
    assert manifest["artifacts"]["build_overlay_repair_report"] == str(overlay_report)


def test_workflow_marks_soil_realism_build_blocker_as_not_verified(monkeypatch, tmp_path: Path):
    soil_diag = tmp_path / "run_soil_block" / "reports" / "soil_realism_diagnostics.json"
    soil_diag.parent.mkdir(parents=True)
    soil_diag.write_text('{"blocker_class":"soil_realism_gate_failed"}\n', encoding="utf-8")

    def fake_run_pipeline(**kwargs):
        return {
            "status": "BLOCKED",
            "soil_mode": "high_fidelity",
            "blocker_class": "soil_realism_gate_failed",
            "build": {
                "success": False,
                "status": "BLOCKED",
                "blocker_class": "soil_realism_gate_failed",
                "diagnostic_artifacts": {
                    "soil_realism_diagnostics": str(soil_diag),
                },
            },
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="02129000",
            out_dir=tmp_path / "run_soil_block",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="policy",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )

    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["blocker_class"] == "soil_realism_gate_failed"
    assert data["values"]["soil_mode"] == "not_verified"
    assert data["values"]["soil_provenance_mode"] == "soil_realism_gate_failed"
    assert "contract_policy" in data["gates_passed"]
    assert "contract_policy" not in data["gates_failed"]
    assert "soil_fidelity" in data["gates_failed"]
    blocked = {claim["claim"]: claim for claim in data["blocked_claims"]}
    assert "soil_realism_gate_failed" in blocked["soil_fidelity_gate_passed"]["reason"]


def test_effective_claim_tier_reaches_research_only_with_complete_evidence(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_research" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_research"),
            "selected_outlet_gis_id": 7,
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
            "metrics": {"nse": 0.10, "kge": 0.41, "pbias": 25.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": _core_sensitivity_classes(),
        }

    def fake_calibration(*args, **kwargs):
        hydrograph_dir = tmp_path / "run_research" / "calibration" / "hydrograph_comparison"
        hydrograph_dir.mkdir(parents=True, exist_ok=True)
        hydrograph_plot = hydrograph_dir / "hydrograph_calibrated_vs_observed.png"
        hydrograph_pdf = hydrograph_dir / "hydrograph_calibrated_vs_observed.pdf"
        hydrograph_overlay_plot = hydrograph_dir / "hydrograph_observed_simulated_calibrated.png"
        hydrograph_overlay_pdf = hydrograph_dir / "hydrograph_observed_simulated_calibrated.pdf"
        hydrograph_metrics = hydrograph_dir / "hydrograph_comparison_metrics.json"
        hydrograph_plot.write_bytes(b"png")
        hydrograph_pdf.write_bytes(b"pdf")
        hydrograph_overlay_plot.write_bytes(b"png")
        hydrograph_overlay_pdf.write_bytes(b"pdf")
        hydrograph_metrics.write_text('{"mode":"real_engine"}\n', encoding="utf-8")
        skill_dir = tmp_path / "run_research" / "calibration" / "skill_diagnostics"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_json = skill_dir / "skill_diagnostics.json"
        skill_md = skill_dir / "skill_diagnostics.md"
        skill_json.write_text('{"diagnostic_flags":[{"symptom":"low skill"}],"next_actions":["inspect"]}\n', encoding="utf-8")
        skill_md.write_text("# Skill Diagnostics\n", encoding="utf-8")
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "blocked_parameters": ["GW_DELAY"],
                "final_physical_gates": {"status": "passed"},
                "verification_metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
                "verification_delta_metrics": {"nse": 0.20, "kge": 0.25, "pbias": -20.0},
                "hydrograph_comparison": {
                    "status": "written",
                    "hydrograph_plot": str(hydrograph_plot),
                    "hydrograph_plot_pdf": str(hydrograph_pdf),
                    "hydrograph_overlay_plot": str(hydrograph_overlay_plot),
                    "hydrograph_overlay_plot_pdf": str(hydrograph_overlay_pdf),
                    "hydrograph_metrics_json": str(hydrograph_metrics),
                },
                "skill_diagnostics": {
                    "status": "written",
                    "skill_diagnostics_json": str(skill_json),
                    "skill_diagnostics_md": str(skill_md),
                    "diagnostic_count": 1,
                },
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e.build_landuse_fidelity_block",
        lambda *args, **kwargs: {
            "status": "evaluated",
            "hru_mode": "full_overlay",
            "dominant_only": False,
            "n_hrus": 120,
            "n_subbasins": 31,
            "landuse_classes_present": ["AGRL", "FRSD"],
            "landuse_classes_retained": ["AGRL", "FRSD"],
            "landuse_class_retention_fraction": 1.0,
            "landuse_vintage_year": 2011,
            "sim_midpoint_year": 2014,
            "landuse_vintage_mismatch_years": -3,
        },
    )
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run_research",
        claim_tier="research_grade",
        contract_status="accepted",
        accepted_by="user",
        start="2010-01-01",
        end="2019-12-31",
        warmup_years=3,
    )

    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["claim_tier"] == "research_grade"
    assert data["effective_claim_tier"] == "research_grade"
    assert data["values"]["effective_claim_tier"] == "research_grade"
    assert data["values"]["baseline_metrics"]["kge"] == 0.41
    assert data["values"]["metrics"]["kge"] == 0.45
    assert data["values"]["calibrated_metrics"]["pbias"] == 5.0
    assert Path(data["values"]["hydrograph_comparison_plot"]).exists()
    assert Path(data["values"]["hydrograph_comparison_plot_pdf"]).exists()
    assert Path(data["values"]["hydrograph_observed_simulated_calibrated_plot"]).exists()
    assert Path(data["values"]["hydrograph_observed_simulated_calibrated_plot_pdf"]).exists()
    assert Path(data["values"]["hydrograph_comparison_metrics"]).exists()
    assert Path(data["values"]["skill_diagnostics_json"]).exists()
    assert Path(data["values"]["skill_diagnostics_md"]).exists()
    manifest = json.loads(Path(res.artifact_dir, "run_manifest.json").read_text(encoding="utf-8"))
    assert Path(manifest["artifacts"]["hydrograph_comparison_plot"]).exists()
    assert Path(manifest["artifacts"]["hydrograph_comparison_plot_pdf"]).exists()
    assert Path(manifest["artifacts"]["hydrograph_observed_simulated_calibrated_plot"]).exists()
    assert Path(manifest["artifacts"]["hydrograph_observed_simulated_calibrated_plot_pdf"]).exists()
    assert Path(manifest["artifacts"]["skill_diagnostics_json"]).exists()
    assert Path(manifest["artifacts"]["skill_diagnostics_md"]).exists()
    md = Path(res.artifact_dir, "EVIDENCE_SUMMARY.md").read_text(encoding="utf-8")
    assert "Hydrograph comparison PDF" in md
    assert "Observed/simulated/calibrated hydrograph" in md
    assert "Skill diagnostics JSON" in md
    assert "physical_gates" in data["gates_passed"]
    assert "outlet_provenance" in data["gates_passed"]
    assert "benchmark_lock" in data["gates_passed"]
    assert "fresh_engine_output" in data["gates_passed"]
    assert "sensitivity_screen" in data["gates_passed"]
    assert "landuse_fidelity" in data["gates_passed"]
    assert "calibration_verification" in data["gates_passed"]


def test_effective_claim_tier_blocks_research_for_partial_terminal_scope(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_partial_scope" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_partial_scope"),
            "selected_outlet_gis_id": 7,
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
            "metrics": {"nse": 0.10, "kge": 0.41, "pbias": 25.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": _core_sensitivity_classes(),
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "blocked_parameters": ["GW_DELAY"],
                "final_physical_gates": {"status": "passed"},
                "final_routing_flow_gates": _partial_scope_passed_routing_gate(),
                "verification_metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
                "verification_delta_metrics": {"nse": 0.20, "kge": 0.25, "pbias": -20.0},
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _partial_scope_passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_partial_scope",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["values"]["terminal_scope_blocker"] == "outlet_scope_volume_mismatch"
    assert data["effective_claim_tier"] == "exploratory"
    blocked = {claim["claim"]: claim for claim in data["blocked_claims"]}
    assert blocked["terminal_scope_claim"]["reason"] == "outlet_scope_volume_mismatch"


def test_workflow_evidence_promotes_terminal_hydrograph_scope_class(monkeypatch, tmp_path: Path):
    run_dir = tmp_path / "run_terminal_scope_class"
    txt = run_dir / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(run_dir),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.10, "kge": 0.42, "pbias": 82.0},
        }

    def fake_volume_diagnostics(run, *, physical_gates, values):
        report = Path(run) / "reports" / "volume_bias_diagnostics.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("{}\n", encoding="utf-8")
        return {
            "json_path": str(report),
            "markdown_path": str(report.with_suffix(".md")),
            "primary_issue": "simulated_volume_excess",
            "terminal_scope_blocker": "outlet_scope_volume_mismatch",
            "terminal_hydrograph_scope": {
                "available": True,
                "diagnostic_only": True,
                "selected_terminal": {"pbias_pct": 2.0},
                "all_terminal": {"pbias_pct": 35.0},
            },
            "terminal_hydrograph_scope_class": "selected_metric_passes_but_area_scope_partial",
            "terminal_hydrograph_scope_flags": [
                "selected_terminal_metric_gate_passes",
                "selected_terminal_scope_partial",
            ],
            "terminal_hydrograph_scope_recommended_focus": [
                "confirm_gauge_drainage_area_against_selected_terminal",
                "audit_outlet_selection_against_terminal_inventory",
            ],
            "terminal_hydrograph_scope_claim_impact": (
                "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
            ),
            "terminal_scope_decision_request": {
                "status": "needs_input",
                "question_id": "02129000_outlet_scope_authority",
                "decision_type": "selected_outlet_scope_authority_required",
                "accepted_by_required": "user_or_policy",
            },
            "post_aggregation_process_context": {
                "available": True,
                "status": "diagnostic_only_process_or_forcing_blocker",
                "claim_authority": False,
                "temporary_metrics_allowed_as_final": False,
                "fresh_locked_rerun_required": True,
                "likely_process_domains": ["swat_water_yield_below_observed_runoff"],
                "recommended_focus": [
                    "increase_water_yield_only_if_physical_and_forcing_gates_support_it"
                ],
                "required_before_claim": [
                    "retain_all_terminal_metrics_as_diagnostic_only",
                    "document_post_aggregation_volume_deficit_source",
                ],
            },
            "diagnostic_flags": [{"code": "simulated_volume_excess"}],
            "source_backed_alternatives": [],
            "recommended_probe_order": [],
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e.write_volume_bias_diagnostics",
        fake_volume_diagnostics,
    )

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="02129000",
            out_dir=run_dir,
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
            calibrate=False,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    cal = json.loads(Path(res.artifact_dir, "calibration_provenance.json").read_text(encoding="utf-8"))

    assert data["values"]["terminal_hydrograph_scope_class"] == (
        "selected_metric_passes_but_area_scope_partial"
    )
    assert data["values"]["terminal_hydrograph_scope_flags"] == [
        "selected_terminal_metric_gate_passes",
        "selected_terminal_scope_partial",
    ]
    assert data["values"]["terminal_hydrograph_scope_recommended_focus"][0] == (
        "confirm_gauge_drainage_area_against_selected_terminal"
    )
    assert data["values"]["terminal_hydrograph_scope_claim_impact"] == (
        "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass"
    )
    assert data["values"]["post_aggregation_process_context"]["status"] == (
        "diagnostic_only_process_or_forcing_blocker"
    )
    assert data["values"]["post_aggregation_process_context"]["claim_authority"] is False
    assert data["values"]["terminal_scope_decision_request"]["question_id"] == (
        "02129000_outlet_scope_authority"
    )
    assert cal["provenance"]["terminal_hydrograph_scope_class"] == (
        "selected_metric_passes_but_area_scope_partial"
    )
    assert cal["provenance"]["terminal_scope_decision_request"]["accepted_by_required"] == (
        "user_or_policy"
    )
    assert cal["provenance"]["post_aggregation_process_context"]["likely_process_domains"] == [
        "swat_water_yield_below_observed_runoff"
    ]
    assert cal["provenance"]["terminal_scope_blocker"] == "outlet_scope_volume_mismatch"


def test_degraded_soil_provenance_blocks_research_effective_tier(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_degraded_soil" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        assert kwargs["allow_diagnostic_fallbacks"] is True
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_degraded_soil"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.10, "kge": 0.41, "pbias": 25.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
            "soil_mode": "fallback",
            "soil_provenance_mode": "diagnostic_partial_gnatsgo_constant",
            "pct_fallback_soils": 1.0,
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "final_physical_gates": {"status": "passed"},
                "verification_metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
                "verification_delta_metrics": {"nse": 0.20, "kge": 0.25, "pbias": -20.0},
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="03353000",
            out_dir=tmp_path / "run_degraded_soil",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "publication_grade"
    assert "soil_fidelity" in data["gates_failed"]
    assert any(
        c["claim"] == "soil_fidelity_gate_passed"
        and "diagnostic_partial_gnatsgo_constant" in c["reason"]
        for c in data["blocked_claims"]
    )


def test_verified_locked_calibration_can_be_diagnostic_when_claim_gates_fail(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_verified_diagnostic" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_verified_diagnostic"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.05, "kge": 0.10, "pbias": -55.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=False,
            phases=[
                PhaseRun(
                    stage=4,
                    phase="kge_nse_finetune",
                    status="failed",
                    message="locked rerun improved but final research skill gates failed",
                    script="verify_calibration",
                )
            ],
            provenance={
                "final_metrics_authority": "verification_summary.json",
                "temporary_candidate_metrics_allowed_as_final": False,
                "verification_improvement_basis": "nse_and_kge",
                "verification_metrics": {"nse": 0.27, "kge": 0.25, "pbias": 12.0},
                "verification_delta_metrics": {"nse": 0.22, "kge": 0.15, "pbias": 67.0},
                "locked_verification_succeeded": True,
                "locked_rerun_improved": True,
                "final_claim_gates_passed": False,
                "calibration_claim_status": "verified_diagnostic_claim_blocked_by_final_gates",
                "final_physical_gates": {
                    "status": "failed",
                    "pass": False,
                    "condition_codes": ["BELOW_RESEARCH_SKILL"],
                    "blocked_tiers": {"research_grade": ["skill below research threshold"]},
                },
                "final_routing_flow_gates": {
                    "status": "passed",
                    "pass": True,
                    "closure_status": "pass",
                    "calibration_blocking": False,
                    "research_grade_blocking": False,
                    "condition_codes": [],
                },
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01547700",
            out_dir=tmp_path / "run_verified_diagnostic",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "exploratory"
    assert data["values"]["calibration_success"] is False
    assert data["values"]["calibration_status"] == "verified_diagnostic_claim_blocked"
    assert data["values"]["calibration_locked_verification_succeeded"] is True
    assert data["values"]["calibration_locked_rerun_improved"] is True
    assert data["values"]["calibration_final_claim_gates_passed"] is False
    assert data["values"]["calibration_claim_status"] == "verified_diagnostic_claim_blocked_by_final_gates"
    assert data["values"]["calibration_final_metrics_authority"] == "verification_summary.json"
    assert "calibration_verification" in data["gates_passed"]
    allowed = {c["claim"]: c for c in data["allowed_claims"]}
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert "locked_calibration_verification_completed" in allowed
    assert blocked["calibrated_model_skill_claim"]["reason"] == "verified_diagnostic_claim_blocked_by_final_gates"


def test_research_claim_blocks_without_selected_outlet_provenance(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_no_outlet" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_no_outlet"),
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "final_physical_gates": {"status": "passed"},
                "verification_metrics": {"nse": 0.45, "kge": 0.50, "pbias": 5.0},
                "verification_delta_metrics": {"nse": 0.15, "kge": 0.05, "pbias": 0.0},
                "verification_improvement_basis": "nse_and_kge",
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_no_outlet",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "exploratory"
    assert "outlet_provenance" in data["gates_failed"]
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert "outlet_provenance_verified" in blocked
    assert "selected outlet GIS id missing" in blocked["outlet_provenance_verified"]["reason"]


def test_research_claim_blocks_without_benchmark_lock_artifact(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_no_lock" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": str(tmp_path / "run_no_lock" / "benchmark" / "benchmark_lock.json"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "final_physical_gates": {"status": "passed"},
                "verification_metrics": {"nse": 0.45, "kge": 0.50, "pbias": 5.0},
                "verification_delta_metrics": {"nse": 0.15, "kge": 0.05, "pbias": 0.0},
                "verification_improvement_basis": "nse_and_kge",
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_no_lock",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "exploratory"
    assert "benchmark_lock" in data["gates_failed"]
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert "locked_benchmark_claim" in blocked
    assert "benchmark lock artifact missing" in blocked["locked_benchmark_claim"]["reason"]


def test_research_claim_blocks_without_fresh_output_artifact(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_no_fresh_output" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)
    (txt / "channel_sd_day.txt").unlink()

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "engine_returncode": 0,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_no_fresh_output"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "final_physical_gates": {"status": "passed"},
                "verification_metrics": {"nse": 0.45, "kge": 0.50, "pbias": 5.0},
                "verification_delta_metrics": {"nse": 0.15, "kge": 0.05, "pbias": 0.0},
                "verification_improvement_basis": "nse_and_kge",
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_no_fresh_output",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "exploratory"
    assert "fresh_engine_output" in data["gates_failed"]
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert "fresh_output_claim" in blocked
    assert "fresh simulation output artifact missing" in blocked["fresh_output_claim"]["reason"]


def test_research_claim_blocks_without_locked_calibration_improvement(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_no_improvement" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_no_improvement"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "final_physical_gates": {"status": "passed"},
                "verification_metrics": {"nse": 0.45, "kge": 0.50, "pbias": 5.0},
                "verification_delta_metrics": {"nse": 0.0, "kge": -0.01, "pbias": 0.0},
                "verification_improvement_basis": "none",
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_no_improvement",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "diagnostic"
    assert "calibration_verification" in data["gates_failed"]
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert "calibration_improvement_verified" in blocked
    assert "positive NSE or KGE improvement" in blocked["calibration_improvement_verified"]["reason"]


def test_research_claim_blocks_without_basin_specific_sensitivity(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_no_sens" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_no_sens"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={"final_physical_gates": {"status": "passed"}},
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run_no_sens",
        claim_tier="research_grade",
        contract_status="accepted",
        accepted_by="user",
        start="2010-01-01",
        end="2019-12-31",
        warmup_years=3,
    )

    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "diagnostic"
    assert "sensitivity_screen" in data["gates_failed"]
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert "basin_specific_sensitivity_screen_passed" in blocked
    assert "governance_default" in blocked["basin_specific_sensitivity_screen_passed"]["reason"]


def test_research_metric_gate_requires_timing_documentation_for_negative_nse(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_negative_nse" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_negative_nse"),
            "selected_outlet_gis_id": 7,
            "soil_mode": "high_fidelity",
            "soil_provenance_mode": "gnatsgo_raster",
            "pct_fallback_soils": 0.0,
            "metrics": {"nse": 0.10, "kge": 0.41, "pbias": 25.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": _core_sensitivity_classes(),
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=True,
            phases=[PhaseRun(stage=1, phase="volume", status="done", message="ok", script="locked")],
            provenance={
                "blocked_parameters": ["GW_DELAY"],
                "final_physical_gates": {"status": "passed"},
                "verification_metrics": {"nse": -0.05, "kge": 0.45, "pbias": 5.0},
                "verification_delta_metrics": {"nse": -0.15, "kge": 0.04, "pbias": -20.0},
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e.build_landuse_fidelity_block",
        lambda *args, **kwargs: _passing_landuse_fidelity(),
    )
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run_negative_nse",
        claim_tier="research_grade",
        contract_status="accepted",
        accepted_by="user",
        start="2010-01-01",
        end="2019-12-31",
        warmup_years=3,
    )

    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))

    assert data["effective_claim_tier"] == "diagnostic"
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert "research_metric_thresholds_passed" in blocked
    assert "without documented timing limitation" in blocked["research_metric_thresholds_passed"]["reason"]

    def fake_calibration_with_timing_doc(*args, **kwargs):
        result = fake_calibration(*args, **kwargs)
        result.provenance["timing_limitation_documented"] = True
        result.provenance["timing_limitation_basis"] = "KGE passes while NSE is depressed by documented timing limitation."
        return result

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration_with_timing_doc)
    res2 = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_negative_nse_documented",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data2 = json.loads(Path(res2.evidence_summary_path).read_text(encoding="utf-8"))
    assert data2["effective_claim_tier"] == "research_grade"


def test_documented_timing_limitation_requires_skill_diagnostic_evidence(tmp_path: Path) -> None:
    skill_json = tmp_path / "skill_diagnostics.json"
    skill_json.write_text(
        json.dumps(
            {
                "diagnostic_flags": [
                    {"symptom": "Peak timing lag exceeds 1 day"},
                    {"symptom": "Total flow volume bias exceeds 15%"},
                ]
            }
        ),
        encoding="utf-8",
    )

    timing = _documented_timing_limitation(
        {"skill_diagnostics_json": str(skill_json)},
        nse=-0.25,
        kge=0.45,
        pbias=5.0,
    )

    assert timing["documented"] is True
    assert "Peak timing lag" in str(timing["basis"])

    no_timing = _documented_timing_limitation(
        {"skill_diagnostics_json": str(skill_json)},
        nse=-0.25,
        kge=0.39,
        pbias=5.0,
    )
    assert no_timing["documented"] is False


def test_short_window_downgrades_to_exploratory(tmp_path: Path):
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run3",
        claim_tier="diagnostic",
        start="2018-01-01",
        end="2020-12-31",
        warmup_years=1,
    )
    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    assert data["claim_tier"] == "exploratory"
    assert data["effective_claim_tier"] == "exploratory"
    assert "window_short_for_diagnostic" in data["values"]["policy_notes"]
    assert data["blocked_claims"]


def test_volume_bias_gate_allows_diagnostic_calibration_attempt_but_blocks_claim(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run4" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt, wateryld=500.0)

    def fake_run_pipeline(**kwargs):
        alignment = tmp_path / "run4" / "benchmark" / "alignment.csv"
        alignment.parent.mkdir(parents=True, exist_ok=True)
        import pandas as pd

        pd.DataFrame(
            {"obs": [10.0, 12.0, 8.0], "sim": [18.0, 20.0, 16.0]},
            index=pd.date_range("2010-01-01", periods=3, freq="D"),
        ).to_csv(alignment)
        detailed = tmp_path / "run4" / "outputs" / "outlet_provenance.json"
        detailed.parent.mkdir(parents=True, exist_ok=True)
        detailed.write_text(
            json.dumps(
                {
                    "selection_pass": {
                        "diagnostics": {
                            "outlet_autodetected": True,
                            "outlet_selection_reason": "requested_outlet_non_terminal_largest_terminal_flow",
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
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": str(tmp_path / "run4" / "benchmark" / "benchmark_lock.json"),
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 80.0},
        }

    def fake_run_diagnostic_calibration(source_run, *, claim_tier, strict):
        assert Path(source_run) == tmp_path / "run4"
        return DiagnosticCalibrationResult(
            success=False,
            phases=[
                PhaseRun(
                    stage=1,
                    phase="volume",
                    status="failed",
                    message="No calibration candidate passed the volume gate.",
                    script="locked_benchmark",
                )
            ],
            provenance={
                "calibration_method": "locked_diagnostic_full_mode",
                "claim_tier": claim_tier,
                "strict": strict,
                "final_metrics_authority": "none",
                "temporary_candidate_metrics_allowed_as_final": False,
                "error": "No calibration candidate passed the volume gate.",
                "history_csv": str(tmp_path / "run4" / "calibration" / "history.csv"),
                "n_evaluations": 8,
                "promotion_gate": {"nse": 0.0, "kge": 0.4, "pbias_abs_pct": 30.0},
            },
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)
    monkeypatch.setattr(
        "swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration",
        fake_run_diagnostic_calibration,
    )
    req = RunUSGSWorkflowRequest(
        usgs_id="01654000",
        out_dir=tmp_path / "run4",
        claim_tier="research_grade",
        contract_status="accepted",
        accepted_by="user",
        start="2010-01-01",
        end="2019-12-31",
        warmup_years=3,
    )

    res = run_usgs_workflow(req)
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    gates = json.loads(Path(res.artifact_dir, "physical_gates.json").read_text(encoding="utf-8"))

    assert gates["status"] == "failed"
    assert "research_grade" in gates["blocked_tiers"]
    assert "physical_gates" in data["gates_failed"]
    assert "calibration_verification" in data["gates_failed"]
    assert data["effective_claim_tier"] == "exploratory"
    assert data["values"]["calibration_attempted"] is True
    assert data["values"]["calibration_status"] == "attempted_failed_or_blocked"
    assert data["values"]["calibration_final_metrics_authority"] == "none"
    assert data["values"]["temporary_candidate_metrics_allowed_as_final"] is False
    assert data["values"]["calibration_failure_phase"] == "volume"
    assert data["values"]["calibration_failure_message"] == "No calibration candidate passed the volume gate."
    assert data["values"]["calibration_failure_history_csv"].endswith("calibration/history.csv")
    assert data["values"]["calibration_failure_n_evaluations"] == 8
    assert data["values"]["calibration_failure_promotion_gate"] == {
        "nse": 0.0,
        "kge": 0.4,
        "pbias_abs_pct": 30.0,
    }
    assert data["values"]["calibration_precheck_sequence"] == "volume_bias_repair_before_final_physical_gate"
    assert data["values"]["calibration_precheck_physical_gates_status"] == "failed"
    assert data["values"]["calibration_precheck_routing_flow_gates_status"] == "passed"
    assert data["values"]["volume_bias_primary_issue"] == "simulated_volume_excess"
    assert data["values"]["terminal_scope_blocker"] is None
    assert isinstance(data["values"]["terminal_hydrograph_scope"], dict)
    assert Path(data["values"]["volume_bias_diagnostics_path"]).exists()
    cal = json.loads(Path(res.artifact_dir, "calibration_provenance.json").read_text(encoding="utf-8"))
    assert cal["status"] == "attempted_failed_or_blocked"
    assert cal["phases"][0]["phase"] == "volume"
    assert cal["provenance"]["calibration_sequence"] == "volume_bias_repair_before_final_physical_gate"
    assert cal["provenance"]["calibration_precheck"]["physical_gates_status"] == "failed"
    assert cal["provenance"]["calibration_precheck"]["routing_flow_gates_status"] == "passed"
    assert any(c["claim"] == "physical_gate_claim" for c in data["blocked_claims"])


def test_skill_only_metric_gate_allows_diagnostic_calibration_attempt() -> None:
    allowed, reason, sequence = _calibration_precheck(
        {
            "status": "failed",
            "condition_codes": ["BELOW_RESEARCH_SKILL"],
            "dominant_blocker": "BELOW_RESEARCH_SKILL",
        },
        {"status": "passed", "pass": True},
    )

    assert allowed is True
    assert reason is None
    assert sequence == "metric_skill_repair_before_final_research_gate"


def test_mass_closure_warning_allows_diagnostic_calibration_attempt() -> None:
    allowed, reason, sequence = _calibration_precheck(
        {
            "status": "failed",
            "condition_codes": ["BELOW_RESEARCH_SKILL"],
            "dominant_blocker": "BELOW_RESEARCH_SKILL",
        },
        {
            "status": "warning",
            "pass": False,
            "calibration_blocking": False,
            "closure_status": "fail_mass_closure",
        },
    )

    assert allowed is True
    assert reason is None
    assert sequence == "metric_skill_repair_before_final_research_gate"


def test_et_dominated_metric_gate_allows_diagnostic_calibration_attempt() -> None:
    allowed, reason, sequence = _calibration_precheck(
        {
            "status": "failed",
            "condition_codes": ["ET_DOMINATED", "VOLUME_BIAS", "BELOW_RESEARCH_SKILL"],
            "dominant_blocker": "ET_DOMINATED",
        },
        {
            "status": "warning",
            "pass": False,
            "calibration_blocking": False,
            "closure_status": "fail_mass_closure",
        },
    )

    assert allowed is True
    assert reason is None
    assert sequence == "volume_bias_repair_before_final_physical_gate"


def test_et_dominated_only_gate_uses_et_partition_repair_sequence() -> None:
    allowed, reason, sequence = _calibration_precheck(
        {
            "status": "failed",
            "condition_codes": ["ET_DOMINATED"],
            "dominant_blocker": "ET_DOMINATED",
        },
        {"status": "passed", "pass": True},
    )

    assert allowed is True
    assert reason is None
    assert sequence == "et_partition_repair_before_final_physical_gate"


def test_mass_imbalance_with_volume_target_allows_diagnostic_repair_attempt() -> None:
    allowed, reason, sequence = _calibration_precheck(
        {
            "status": "failed",
            "condition_codes": ["MASS_IMBALANCE", "VOLUME_BIAS", "ET_DOMINATED"],
            "dominant_blocker": "MASS_IMBALANCE",
        },
        {"status": "passed", "pass": True},
    )

    assert allowed is True
    assert reason is None
    assert sequence == "volume_bias_repair_before_final_physical_gate"


def test_mass_imbalance_only_still_blocks_diagnostic_calibration() -> None:
    allowed, reason, sequence = _calibration_precheck(
        {
            "status": "failed",
            "condition_codes": ["MASS_IMBALANCE"],
            "dominant_blocker": "MASS_IMBALANCE",
        },
        {"status": "passed", "pass": True},
    )

    assert allowed is False
    assert reason == "physical_gates_not_passed"
    assert sequence == "blocked_before_volume_stage"


def test_hard_physical_gate_still_blocks_diagnostic_calibration() -> None:
    allowed, reason, sequence = _calibration_precheck(
        {
            "status": "failed",
            "condition_codes": ["ZERO_SURFACE_RUNOFF", "BELOW_RESEARCH_SKILL"],
            "dominant_blocker": "ZERO_SURFACE_RUNOFF",
        },
        {"status": "passed", "pass": True},
    )

    assert allowed is False
    assert reason == "physical_gates_not_passed"
    assert sequence == "blocked_before_volume_stage"


def test_zero_surface_runoff_gate_blocks_calibration_and_claims(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_zero_surq" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt, wateryld=500.0)
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        "jday mon day yr unit gis_id name precip et pet surq_gen latq perc wateryld\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "0 0 0 0 0 0 basin 1000 300 0 0 100 200 500\n",
        encoding="utf-8",
    )

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": str(tmp_path / "run_zero_surq" / "benchmark" / "benchmark_lock.json"),
            "metrics": {"nse": 0.45, "kge": 0.50, "pbias": 5.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_zero_surq",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    gates = json.loads(Path(res.artifact_dir, "physical_gates.json").read_text(encoding="utf-8"))

    assert gates["status"] == "failed"
    assert "ZERO_SURFACE_RUNOFF" in gates["condition_codes"]
    assert data["effective_claim_tier"] == "exploratory"
    assert data["values"]["calibration_status"] == "blocked_by_physical_gates"
    assert "physical_gates" in data["gates_failed"]
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert blocked["physical_gate_claim"]["reason"] == "failed"


def test_routing_flow_gate_failure_blocks_calibration_and_research_claim(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_routing_block" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": str(tmp_path / "run_routing_block" / "benchmark" / "benchmark_lock.json"),
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
        }

    def failed_routing_gate(*args, **kwargs) -> dict:
        return {
            "status": "failed",
            "pass": False,
            "reason": "routing flow closure status=fail_hru_to_channel",
            "closure_status": "fail_hru_to_channel",
            "flags": ["hru_wateryld_without_terminal_channel_flow"],
            "condition_codes": ["fail_hru_to_channel"],
            "blocked_tiers": {
                "diagnostic": ["routing flow closure status=fail_hru_to_channel"],
                "research_grade": ["routing flow closure status=fail_hru_to_channel"],
            },
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", failed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_routing_block",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    gates = json.loads(Path(res.artifact_dir, "routing_flow_gates.json").read_text(encoding="utf-8"))

    assert gates["status"] == "failed"
    assert data["effective_claim_tier"] == "exploratory"
    assert "routing_flow" in data["gates_failed"]
    assert data["values"]["calibration_attempted"] is False
    assert data["values"]["calibration_status"] == "blocked_by_routing_flow_gates"
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert blocked["routing_flow_gate_claim"]["reason"] == "failed"
    cal = json.loads(Path(res.artifact_dir, "calibration_provenance.json").read_text(encoding="utf-8"))
    assert cal["reason"] == "routing_flow_gates_not_passed"
    assert cal["provenance"]["routing_flow_gates_status"] == "failed"


def test_routing_flow_warning_blocks_research_claim_without_blocking_calibration(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_routing_warning" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_routing_warning"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.30, "kge": 0.45, "pbias": 5.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
            "soil_mode": "high_fidelity",
            "pct_fallback_soils": 0.0,
        }

    def warning_routing_gate(*args, **kwargs) -> dict:
        return {
            "status": "warning",
            "pass": False,
            "calibration_blocking": False,
            "research_grade_blocking": True,
            "reason": "routing flow closure status=fail_mass_closure",
            "closure_status": "fail_mass_closure",
            "flags": ["routed_to_channel_reference_matches_terminal"],
            "condition_codes": ["fail_mass_closure"],
            "blocked_tiers": {
                "research_grade": ["routing flow closure status=fail_mass_closure"],
            },
        }

    def fake_calibration(*args, **kwargs):
        return DiagnosticCalibrationResult(
            success=False,
            phases=[PhaseRun(stage=1, phase="volume", status="blocked", message="volume", script="locked")],
            provenance={"error": "No calibration candidate passed the volume gate."},
        )

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", warning_routing_gate)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_diagnostic_calibration", fake_calibration)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01654000",
            out_dir=tmp_path / "run_routing_warning",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )
    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    gates = json.loads(Path(res.artifact_dir, "routing_flow_gates.json").read_text(encoding="utf-8"))

    assert gates["status"] == "warning"
    assert data["effective_claim_tier"] == "exploratory"
    assert "routing_flow" in data["gates_failed"]
    assert data["values"]["calibration_attempted"] is True
    assert data["values"]["calibration_status"] == "attempted_failed_or_blocked"
    blocked = {c["claim"]: c for c in data["blocked_claims"]}
    assert blocked["routing_flow_gate_claim"]["reason"] == "warning"


def test_workflow_writes_mass_balance_diagnostics_for_mass_imbalance(monkeypatch, tmp_path: Path):
    txt = tmp_path / "run_mass_imbalance" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)

    def fake_run_pipeline(**kwargs):
        return {
            "status": "SUCCESS",
            "usgs_id": kwargs["usgs_id"],
            "txtinout_dir": str(txt),
            "fresh_engine_run": True,
            "benchmark_lock_path": _touch_benchmark_lock(tmp_path / "run_mass_imbalance"),
            "selected_outlet_gis_id": 7,
            "metrics": {"nse": 0.20, "kge": 0.45, "pbias": -10.0},
            "sensitivity_screen_basis": "basin_specific",
            "sensitivity_screen_activity_classes": {"CN2": "active"},
            "soil_mode": "high_fidelity",
            "pct_fallback_soils": 0.0,
        }

    def fake_physical_gates(values: dict) -> dict:
        return {
            "status": "failed",
            "pass": False,
            "wb": {
                "precip": 1000.0,
                "wateryld": 220.0,
                "wet_oflo": 90.0,
                "et": 760.0,
                "perc": 80.0,
                "latq": 3.0,
                "surq_gen": 40.0,
            },
            "conditions": ["mass balance residual is outside tolerance"],
            "condition_codes": ["MASS_IMBALANCE"],
            "dominant_blocker": "MASS_IMBALANCE",
            "blocked_tiers": {
                "diagnostic": ["mass balance residual is outside tolerance"],
                "research_grade": ["mass balance residual is outside tolerance"],
            },
            "allowed_tiers": ["exploratory"],
        }

    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_physical_gates", fake_physical_gates)
    monkeypatch.setattr("swatplus_builder.workflows.usgs_e2e._evaluate_routing_flow_gate", _passed_routing_gate)

    res = run_usgs_workflow(
        RunUSGSWorkflowRequest(
            usgs_id="01491000",
            out_dir=tmp_path / "run_mass_imbalance",
            claim_tier="research_grade",
            contract_status="accepted",
            accepted_by="user",
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
        )
    )

    data = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
    diagnostics_path = Path(data["values"]["mass_balance_diagnostics_path"])
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    provenance = json.loads(Path(res.artifact_dir, "calibration_provenance.json").read_text(encoding="utf-8"))

    assert diagnostics_path.is_file()
    assert diagnostics["gate_context"] == "baseline"
    assert diagnostics["physical_gates_source_path"] == data["values"]["physical_gates_path"]
    assert "mass_closure_residual_high" in data["values"]["mass_balance_diagnostic_flags"]
    assert diagnostics["recommended_probe_order"][0]["diagnostic"] == "audit_basin_water_balance_closure_terms"
    assert provenance["status"] == "blocked_by_physical_gates"
    assert provenance["provenance"]["mass_balance_diagnostics_path"] == str(diagnostics_path)
    assert provenance["provenance"]["mass_balance_diagnostic_flags"] == data["values"][
        "mass_balance_diagnostic_flags"
    ]


def test_locked_calibrated_txtinout_physical_gate_requires_final_artifact(tmp_path: Path):
    locked_txt = tmp_path / "locked_calibrated_TxtInOut"
    _write_basin_wb(locked_txt)

    passed = _check_locked_txt_physical_gates(locked_txt, nse=0.4, kge=0.5)
    missing = _check_locked_txt_physical_gates(tmp_path / "missing", nse=0.4, kge=0.5)

    assert passed["status"] == "passed"
    assert missing["status"] == "failed"
    assert missing["reason"] == "locked_calibrated_txtinout_missing"


def test_locked_calibrated_txtinout_routing_gate_uses_mass_trace(monkeypatch, tmp_path: Path):
    locked_txt = tmp_path / "locked_calibrated_TxtInOut"
    _write_basin_wb(locked_txt)

    def fake_trace_mass_balance(run_dir, **kwargs):
        assert Path(run_dir) == locked_txt
        assert kwargs["basin_id"] == "usgs_test"
        assert kwargs["selected_outlet_gis_id"] == 24
        return SimpleNamespace(
            closure_status="fail_hru_to_channel",
            flags=["hru_wateryld_without_terminal_channel_flow"],
            selected_outlet_gis_id=24,
            selected_outlet_is_terminal=True,
            terminal_outlet_count=1,
            basin_wateryld_m3=100.0,
            hru_wateryld_m3=100.0,
            ru_outflow_m3=None,
            ru_outflow_to_basin_wateryld_ratio=None,
            channel_inflow_m3=0.0,
            terminal_outflow_m3=0.0,
            all_terminal_outflow_m3=0.0,
            mass_closure_ratio=0.0,
        )

    monkeypatch.setattr("swatplus_builder.output.mass_trace.trace_mass_balance", fake_trace_mass_balance)
    result = _check_locked_txt_routing_flow(
        locked_txt,
        out_dir=tmp_path / "routing_gate",
        basin_id="usgs_test",
        selected_outlet_gis_id=24,
    )

    assert result["status"] == "failed"
    assert result["pass"] is False
    assert result["closure_status"] == "fail_hru_to_channel"
    assert result["flags"] == ["hru_wateryld_without_terminal_channel_flow"]
    assert result["recommended_next_action"] == (
        "Inspect HRU-to-channel transfer, terminal outlet selection, and channel routing before calibration."
    )


def test_locked_calibrated_txtinout_mass_closure_is_warning(monkeypatch, tmp_path: Path):
    locked_txt = tmp_path / "locked_calibrated_TxtInOut"
    _write_basin_wb(locked_txt)

    def fake_trace_mass_balance(run_dir, **kwargs):
        return SimpleNamespace(
            closure_status="fail_mass_closure",
            flags=["terminal_outflow_not_consistent_with_basin_wateryld"],
            selected_outlet_gis_id=24,
            selected_outlet_is_terminal=True,
            terminal_outlet_count=1,
            basin_wateryld_m3=100.0,
            hru_wateryld_m3=None,
            ru_outflow_m3=None,
            ru_outflow_to_basin_wateryld_ratio=None,
            channel_inflow_m3=190.0,
            terminal_outflow_m3=190.0,
            all_terminal_outflow_m3=190.0,
            mass_closure_ratio=1.9,
        )

    monkeypatch.setattr("swatplus_builder.output.mass_trace.trace_mass_balance", fake_trace_mass_balance)
    result = _check_locked_txt_routing_flow(
        locked_txt,
        out_dir=tmp_path / "routing_gate",
        basin_id="usgs_test",
        selected_outlet_gis_id=24,
    )

    assert result["status"] == "warning"
    assert result["pass"] is False
    assert result["calibration_blocking"] is False
    assert result["research_grade_blocking"] is True
    assert result["closure_status"] == "fail_mass_closure"
    assert result["recommended_next_action"] == (
        "Mass-closure mismatch is retained as a research-grade blocker; diagnostic calibration may proceed."
    )


def test_locked_calibrated_txtinout_virtual_scope_gate_uses_all_terminal_closure(
    monkeypatch, tmp_path: Path
):
    locked_txt = tmp_path / "locked_calibrated_TxtInOut"
    _write_basin_wb(locked_txt)

    def fake_trace_mass_balance(run_dir, **kwargs):
        assert Path(run_dir) == locked_txt
        return SimpleNamespace(
            closure_status="fail_mass_closure",
            flags=[
                "multiple_terminal_outlets_present",
                "selected_terminal_partial_of_all_terminal_flow",
                "all_terminal_routed_to_channel_reference_matches",
            ],
            selected_outlet_gis_id=1,
            selected_outlet_is_terminal=False,
            terminal_outlet_count=2,
            basin_wateryld_m3=100.0,
            basin_routed_to_channel_m3=100.0,
            routed_to_channel_closure_ratio=0.4,
            all_terminal_routed_to_channel_closure_ratio=1.0,
            all_terminal_mass_closure_ratio=1.0,
            selected_terminal_fraction_of_all_terminal_flow=0.4,
            closure_reference="basin_wateryld_m3",
            hru_wateryld_m3=100.0,
            ru_outflow_m3=None,
            ru_outflow_to_basin_wateryld_ratio=None,
            channel_inflow_m3=100.0,
            terminal_outflow_m3=40.0,
            all_terminal_outflow_m3=100.0,
            mass_closure_ratio=0.4,
        )

    def fake_trace_terminal_inventory(*args, **kwargs):
        return SimpleNamespace(
            failure_class=None,
            terminal_inventory=[SimpleNamespace(), SimpleNamespace()],
            shared_upstream_area_km2=0.0,
            terminal_overlap_pairs=[],
        )

    monkeypatch.setattr("swatplus_builder.output.mass_trace.trace_mass_balance", fake_trace_mass_balance)
    monkeypatch.setattr("swatplus_builder.output.mass_trace.trace_terminal_inventory", fake_trace_terminal_inventory)

    result = _check_locked_txt_routing_flow(
        locked_txt,
        out_dir=tmp_path / "routing_gate",
        basin_id="usgs_test",
        selected_outlet_gis_id=1,
        outlet_scope="virtual_all_terminal",
        outlet_policy="all_terminal_sum",
        selected_outlet_gis_ids=[7, 8],
        virtual_outlet_authority="official_site_area_matches_all_terminal_candidate",
        virtual_outlet_claim_authority=True,
    )

    assert result["status"] == "passed"
    assert result["pass"] is True
    assert result["closure_status"] == "pass"
    assert result["virtual_outlet_scope_gate_status"] == "passed"
    assert result["condition_codes"] == []
    assert Path(tmp_path, "routing_gate", "routing_flow_gates.json").exists()


def test_mass_trace_accepts_standalone_txtinout_for_locked_verification(tmp_path: Path):
    txt = tmp_path / "locked_calibrated_TxtInOut"
    _write_basin_wb(txt)
    (txt / "object.cnt").write_text("object.cnt:\nbasin 100\n", encoding="utf-8")
    (txt / "metadata.json").write_text('{"selected_outlet_gis_id": 24}\n', encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha24 24 0 cha\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 24 cha24 5.787 5.787\n",
        encoding="utf-8",
    )

    report = trace_mass_balance(txt, out_dir=tmp_path / "mass_trace")

    assert report.closure_status == "pass"
    assert report.txtinout_dir == str(txt.resolve())
    assert report.selected_outlet_is_terminal is True
    assert Path(tmp_path, "mass_trace", "mass_trace.json").exists()


def test_mass_trace_recovers_selected_outlet_from_run_root_provenance(tmp_path: Path):
    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)
    (txt / "object.cnt").write_text("object.cnt:\nbasin 100\n", encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha12 12 0 cha\n",
        encoding="utf-8",
    )
    (txt / "channel_sdmorph_day.txt").write_text(
        "channel_sdmorph_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 12 cha12 5.787 5.787\n",
        encoding="utf-8",
    )
    (run / "outlet_provenance.json").write_text(
        json.dumps({"selected_outlet_gis_id": 12}) + "\n",
        encoding="utf-8",
    )

    report = trace_mass_balance(run, out_dir=tmp_path / "mass_trace")

    assert report.selected_outlet_gis_id == 12
    assert report.selected_channel_row_count == 1
    assert report.terminal_channel_row_count == 1
    assert report.closure_status == "pass"


def test_mass_trace_recovers_locked_txt_outlet_from_benchmark_lock(tmp_path: Path):
    source_run = tmp_path / "run"
    txt = source_run / "calibration" / "locked_calibrated_TxtInOut"
    _write_basin_wb(txt)
    (txt / "object.cnt").write_text("object.cnt:\nbasin 100\n", encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha12 12 0 cha\n",
        encoding="utf-8",
    )
    (txt / "channel_sdmorph_day.txt").write_text(
        "channel_sdmorph_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 12 cha12 5.787 5.787\n",
        encoding="utf-8",
    )
    benchmark = source_run / "benchmark"
    benchmark.mkdir(parents=True)
    (benchmark / "benchmark_lock.json").write_text(
        json.dumps({"basin_id": "usgs_fixture", "outlet_gis_id": 12}) + "\n",
        encoding="utf-8",
    )

    report = trace_mass_balance(txt, out_dir=tmp_path / "mass_trace")

    assert report.selected_outlet_gis_id == 12
    assert report.selected_channel_row_count == 1
    assert report.terminal_channel_row_count == 1
    assert report.closure_status == "pass"


def test_mass_trace_missing_selected_outlet_is_explicit_outlet_failure(tmp_path: Path):
    txt = tmp_path / "run" / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)
    (txt / "object.cnt").write_text("object.cnt:\nbasin 100\n", encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha12 12 0 cha\n",
        encoding="utf-8",
    )
    (txt / "channel_sdmorph_day.txt").write_text(
        "channel_sdmorph_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 12 cha12 5.787 5.787\n",
        encoding="utf-8",
    )

    report = trace_mass_balance(tmp_path / "run", out_dir=tmp_path / "mass_trace")

    assert report.selected_outlet_gis_id is None
    assert report.selected_channel_row_count == 0
    assert report.terminal_channel_row_count == 1
    assert report.all_terminal_mass_closure_ratio is not None
    assert report.closure_status == "fail_outlet_selection"
    assert "selected_outlet_gis_id_missing" in report.flags


def test_mass_trace_tolerates_trailing_blank_water_balance_fields(tmp_path: Path):
    txt = tmp_path / "run" / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "object.cnt").write_text("object.cnt:\nbasin 100\n", encoding="utf-8")
    (tmp_path / "run" / "metadata.json").write_text('{"selected_outlet_gis_id": 24}\n', encoding="utf-8")
    (txt / "metadata.json").write_text('{"selected_outlet_gis_id": 24}\n', encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha24 24 0 cha\n",
        encoding="utf-8",
    )
    (txt / "basin_wb_yr.txt").write_text(
        "basin_wb_yr\n"
        "jday mon day yr unit gis_id name precip snofall snomlt surq_gen latq wateryld perc et "
        "ecanopy eplant esoil surq_cont cn sw_init sw_final sw_ave sw_300 sno_init sno_final "
        "snopack pet qtile irr surq_runon latq_runon overbank surq_cha surq_res surq_ls "
        "latq_cha latq_res latq_ls gwsoilq satex satex_chan sw_change lagsurf laglatq "
        "lagsatex wet_evap wet_oflo wet_stor plant_cov mgt_ops\n"
        "mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm mm\n"
        "365 12 31 2010 1 1 basin 1000 0 0 100 100 500 200 300 "
        "0 0 0 100 50 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 25 0 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 24 cha24 5.787 5.787\n",
        encoding="utf-8",
    )

    report = trace_mass_balance(
        tmp_path / "run",
        selected_outlet_gis_id=24,
        out_dir=tmp_path / "mass_trace",
    )

    assert report.closure_status == "pass"
    assert report.basin_wateryld_mm == 500.0
    assert report.gwq_mm == 25.0


def test_mass_trace_uses_routed_to_channel_components_when_available(tmp_path: Path):
    txt = tmp_path / "run" / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "object.cnt").write_text("object.cnt:\nbasin 100\n", encoding="utf-8")
    (tmp_path / "run" / "metadata.json").write_text('{"selected_outlet_gis_id": 24}\n', encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha24 24 0 cha\n",
        encoding="utf-8",
    )
    (txt / "basin_wb_yr.txt").write_text(
        "basin_wb_yr\n"
        "jday mon day yr unit gis_id name precip et surq_gen latq wateryld perc surq_cha latq_cha satex_chan\n"
        "mm mm mm mm mm mm mm mm mm mm\n"
        "365 12 31 2010 1 1 basin 1000 300 100 400 500 100 200 800 0\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 24 cha24 11.574 11.574\n",
        encoding="utf-8",
    )

    report = trace_mass_balance(
        tmp_path / "run",
        selected_outlet_gis_id=24,
        out_dir=tmp_path / "mass_trace",
    )

    assert report.basin_wateryld_mm == 500.0
    assert report.basin_routed_to_channel_mm == 1000.0
    assert report.closure_reference == "basin_wateryld_m3"
    assert report.closure_status == "fail_mass_closure"
    assert "routed_to_channel_reference_matches_terminal" in report.flags
    assert "all_terminal_routed_to_channel_reference_matches" in report.flags
    assert report.mass_closure_ratio == pytest.approx(2.0, rel=1e-3)
    assert report.routed_to_channel_closure_ratio == pytest.approx(1.0, rel=1e-3)
    assert report.all_terminal_routed_to_channel_closure_ratio == pytest.approx(1.0, rel=1e-3)
    assert report.all_terminal_mass_closure_ratio == pytest.approx(2.0, rel=1e-3)
    assert report.selected_terminal_fraction_of_all_terminal_flow == pytest.approx(1.0, rel=1e-3)


def test_mass_trace_adds_specific_mass_closure_context_flags(tmp_path: Path):
    txt = tmp_path / "run" / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "object.cnt").write_text("object.cnt:\nbasin 100\n", encoding="utf-8")
    (tmp_path / "run" / "metadata.json").write_text('{"selected_outlet_gis_id": 24}\n', encoding="utf-8")
    (txt / "metadata.json").write_text('{"selected_outlet_gis_id": 24}\n', encoding="utf-8")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ\n"
        "1 cha24 24 0 cha\n"
        "2 cha25 25 0 cha\n",
        encoding="utf-8",
    )
    _write_basin_wb(txt, precip=1000.0, et=300.0, perc=200.0, wateryld=500.0)
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 24 cha24 50.0 50.0\n"
        "1 1 1 2010 2 25 cha25 20.0 20.0\n",
        encoding="utf-8",
    )
    (txt / "ru_yr.txt").write_text(
        "ru_yr\n"
        "jday mon day yr name type flo\n"
        "m^3/s\n"
        "365 12 31 2010 rtu01 ru 10000.0\n",
        encoding="utf-8",
    )

    report = trace_mass_balance(
        tmp_path / "run",
        selected_outlet_gis_id=24,
        out_dir=tmp_path / "mass_trace",
    )

    assert report.closure_status == "fail_mass_closure"
    assert "terminal_outflow_not_consistent_with_basin_wateryld" in report.flags
    assert "channel_inflow_exceeds_basin_wateryld" in report.flags
    assert "routing_unit_outflow_unit_semantics_suspect" in report.flags
    assert "multiple_terminal_outlets_present" in report.flags
    assert "all_terminal_outflow_differs_from_selected_terminal" in report.flags
    assert "selected_terminal_partial_of_all_terminal_flow" in report.flags
    assert report.ru_outflow_to_basin_wateryld_ratio is not None
    assert report.ru_outflow_to_basin_wateryld_ratio > 1000.0
    assert report.selected_terminal_fraction_of_all_terminal_flow == pytest.approx(50.0 / 70.0)
    alternatives = {row["option"]: row for row in report.source_backed_alternatives}
    assert "audit_terminal_inventory_and_aggregation" in alternatives
    assert "treat_routing_unit_outputs_as_non_authoritative_until_unit_semantics_are_audited" in alternatives
    assert "cross_check_channel_rate_units_and_basin_yield_semantics" in alternatives
    assert report.recommended_probe_order
    assert report.recommended_probe_order[0]["required_artifacts"]
    assert report.basin_wb_source_file == "basin_wb_aa.txt"
    assert report.basin_wb_row_count == 1
    assert report.basin_wb_years == []
    assert report.channel_source_file == "channel_sd_day.txt"
    assert report.channel_row_count == 2
    assert report.channel_years == [2010]
    assert report.selected_channel_row_count == 1
    assert report.terminal_channel_row_count == 2
    markdown = (tmp_path / "mass_trace" / "mass_trace.md").read_text(encoding="utf-8")
    assert "Channel rows" in markdown
    assert "Basin water-balance rows" in markdown
    assert "Source-Backed Alternatives" in markdown
    assert "Recommended Probe Order" in markdown

    gate = _evaluate_routing_flow_gate(
        tmp_path / "run",
        {"usgs_id": "fixture", "txtinout_dir": str(txt)},
    )
    assert gate["mass_trace_channel_row_count"] == 2
    assert gate["mass_trace_selected_channel_row_count"] == 1
    assert gate["mass_trace_terminal_channel_row_count"] == 2
    assert gate["extended_diagnostics"]["ru_outflow_to_basin_wateryld_ratio"] == report.ru_outflow_to_basin_wateryld_ratio


def test_terminal_trace_records_missing_graph_terminals(tmp_path: Path):
    import networkx as nx

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"fixture","selected_outlet_gis_id":1}\n',
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 cha1 1 10.0 40.0 -86.0 0 1 null 0 0 0 1 sdc 2 tot 1.00000\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 1 cha1 1.0 1.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node("1")
    graph_path = run / "delin" / "routing_graph.graphml"
    graph_path.parent.mkdir(parents=True)
    nx.write_graphml(graph, graph_path)

    report = trace_terminal_inventory(
        run,
        selected_outlet_gis_id=1,
        out_dir=run / "reports",
        fetch_usgs_site_area=True,
    )

    assert report.terminal_count == 1
    assert report.terminal_inventory_count == 0
    assert report.missing_terminal_gis_ids == [2]
    assert report.orphan_terminal_gis_ids == []
    assert report.material_missing_terminal_gis_ids == [2]
    assert report.failure_class == "routing_graph_chandeg_mismatch"
    assert "Routing graph terminal IDs missing from chandeg.con" in report.notes[0]
    markdown = (run / "reports" / "terminal_trace.md").read_text(encoding="utf-8")
    assert "Missing terminal GIS IDs" in markdown
    assert "`2`" in markdown


def test_terminal_trace_separates_orphan_graph_terminals(tmp_path: Path):
    import networkx as nx

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"fixture","selected_outlet_gis_id":1}\n',
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ lat lon\n"
        "1 cha1 1 0 cha 40.0 -86.0\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 1 cha1 1.0 1.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_nodes_from(["1", "2"])
    graph_path = run / "delin" / "routing_graph.graphml"
    graph_path.parent.mkdir(parents=True)
    nx.write_graphml(graph, graph_path)

    report = trace_terminal_inventory(
        run,
        selected_outlet_gis_id=1,
        out_dir=run / "reports",
        fetch_usgs_site_area=True,
    )

    assert report.missing_terminal_gis_ids == []
    assert report.orphan_terminal_gis_ids == []
    assert report.material_missing_terminal_gis_ids == []
    assert report.failure_class == "generated_topology_mismatch"
    assert "orphan terminal IDs ignored" not in " ".join(report.notes)


def test_terminal_trace_uses_locked_txtinout_channel_outputs(tmp_path: Path):
    import networkx as nx

    run = tmp_path / "run"
    root_txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    locked_txt = run / "calibration" / "locked_calibrated_TxtInOut"
    root_txt.mkdir(parents=True)
    locked_txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"fixture","selected_outlet_gis_id":1}\n',
        encoding="utf-8",
    )
    chandeg = (
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ lat lon\n"
        "1 cha1 1 0 cha 40.0 -86.0\n"
    )
    (root_txt / "chandeg.con").write_text(chandeg, encoding="utf-8")
    (locked_txt / "chandeg.con").write_text(chandeg, encoding="utf-8")
    (locked_txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
    (root_txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 1 cha1 1.0 1.0\n",
        encoding="utf-8",
    )
    (locked_txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 1 cha1 10.0 10.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node("1")
    graph_path = run / "delin" / "routing_graph.graphml"
    graph_path.parent.mkdir(parents=True)
    nx.write_graphml(graph, graph_path)

    report = trace_terminal_inventory(
        locked_txt,
        selected_outlet_gis_id=1,
        out_dir=run / "calibration" / "locked_calibrated_routing_flow",
    )

    assert report.txtinout_dir == str(locked_txt.resolve())
    assert report.run_dir == str(run.resolve())
    assert report.terminal_inventory[0].outflow_m3 == pytest.approx(10.0 * 86400.0)


def test_terminal_trace_uses_validation_area_for_footprint_context(monkeypatch, tmp_path: Path):
    import networkx as nx

    from swatplus_builder.output import mass_trace as mass_trace_module

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"fixture","selected_outlet_gis_id":1}\n',
        encoding="utf-8",
    )
    (run / "delin" / "validation_result.json").parent.mkdir(parents=True)
    (run / "delin" / "validation_result.json").write_text(
        '{"reference_area_km2":62.5,"delineated_area_km2":60.0}\n',
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ lat lon\n"
        "1 cha1 1 0 cha 40.0 -86.0\n"
        "3 cha3 3 0 cha 40.1 -86.1\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 1 cha1 1.0 1.0\n"
        "1 1 1 2010 1 3 cha3 2.0 2.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node("1")
    graph.add_edge("2", "3")
    nx.write_graphml(graph, run / "delin" / "routing_graph.graphml")
    monkeypatch.setattr(
        mass_trace_module,
        "_subbasin_area_map",
        lambda _run: {1: 10.0, 2: 30.0, 3: 20.0},
    )

    report = trace_terminal_inventory(run, selected_outlet_gis_id=1, out_dir=run / "reports")

    assert report.basin_nldi_area_km2 == 62.5
    assert report.delineated_area_km2 == 60.0
    assert report.selected_terminal_upstream_area_km2 == 10.0
    assert report.all_terminal_upstream_area_km2 == 30.0
    assert report.selected_terminal_fraction_of_nldi_area == pytest.approx(10.0 / 62.5)
    assert report.all_terminal_fraction_of_nldi_area == pytest.approx(30.0 / 62.5)
    assert report.delineated_fraction_of_nldi_area == pytest.approx(60.0 / 62.5)
    assert report.selected_terminal_fraction_of_delineated_area == pytest.approx(10.0 / 60.0)
    assert report.all_terminal_fraction_of_delineated_area == pytest.approx(30.0 / 60.0)
    persisted = json.loads((run / "reports" / "terminal_trace.json").read_text(encoding="utf-8"))
    assert persisted["selected_terminal_fraction_of_nldi_area"] == pytest.approx(10.0 / 62.5)
    markdown = (run / "reports" / "terminal_trace.md").read_text(encoding="utf-8")
    assert "Selected terminal fraction of NLDI area" in markdown
    assert "All-terminal fraction of delineated area" in markdown


def test_terminal_trace_retains_usgs_site_drainage_area_context(monkeypatch, tmp_path: Path):
    import networkx as nx

    from swatplus_builder.output import mass_trace as mass_trace_module

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"02129000","selected_outlet_gis_id":1}\n',
        encoding="utf-8",
    )
    (run / "delin" / "validation_result.json").parent.mkdir(parents=True)
    (run / "delin" / "validation_result.json").write_text(
        '{"reference_area_km2":100.0,"delineated_area_km2":99.0}\n',
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id out_tot obj_typ lat lon\n"
        "1 cha1 1 0 cha 40.0 -86.0\n"
        "3 cha3 3 0 cha 40.1 -86.1\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 1 cha1 1.0 1.0\n"
        "1 1 1 2010 1 3 cha3 2.0 2.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node("1")
    graph.add_edge("2", "3")
    nx.write_graphml(graph, run / "delin" / "routing_graph.graphml")
    monkeypatch.setattr(
        mass_trace_module,
        "_subbasin_area_map",
        lambda _run: {1: 40.0, 2: 30.0, 3: 30.0},
    )
    monkeypatch.setattr(
        mass_trace_module,
        "fetch_usgs_site_metadata",
        lambda _site: {
            "available": True,
            "site_no": "02129000",
            "drain_area_va_sqmi": 38.61,
            "drain_area_km2": 70.0,
            "source": "https://waterservices.usgs.gov/nwis/site/?sites=02129000",
        },
    )

    report = trace_terminal_inventory(
        run,
        selected_outlet_gis_id=1,
        out_dir=run / "reports",
        fetch_usgs_site_area=True,
    )

    assert report.usgs_site_drainage_area_km2 == pytest.approx(70.0)
    assert report.selected_terminal_fraction_of_usgs_site_area == pytest.approx(40.0 / 70.0)
    assert report.all_terminal_fraction_of_usgs_site_area == pytest.approx(1.0)
    assert report.terminal_authority_area_check["reference_area_source"] == "usgs_site_drainage_area"
    assert report.terminal_authority_area_check["class"] == (
        "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
    )
    assert report.terminal_virtual_outlet_candidate["available"] is True
    assert report.terminal_virtual_outlet_candidate["claim_authority"] is False
    assert report.terminal_virtual_outlet_candidate["fresh_locked_rerun_required"] is True
    assert report.terminal_virtual_outlet_candidate["terminal_gis_ids"] == [1, 3]
    persisted = json.loads((run / "reports" / "terminal_trace.json").read_text(encoding="utf-8"))
    assert persisted["usgs_site_drainage_area_km2"] == pytest.approx(70.0)
    assert persisted["terminal_authority_area_check"]["reference_area_source"] == "usgs_site_drainage_area"
    assert persisted["terminal_virtual_outlet_candidate"]["status"] == "diagnostic_only_authority_required"
    assert Path(persisted["terminal_virtual_outlet_candidate_path"]).is_file()
    assert (run / "reports" / "usgs_site_metadata.json").is_file()
    assert (run / "reports" / "terminal_virtual_outlet_candidate.json").is_file()
    markdown = (run / "reports" / "terminal_trace.md").read_text(encoding="utf-8")
    assert "USGS site drainage area km2" in markdown
    assert "Terminal authority area class" in markdown
    assert "Terminal virtual outlet candidate" in markdown


def test_terminal_trace_recovers_gauge_coordinates_from_outlet_vector(monkeypatch, tmp_path: Path):
    import geopandas as gpd
    import networkx as nx
    from shapely.geometry import Point

    from swatplus_builder.output import mass_trace as mass_trace_module

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"fixture","selected_outlet_gis_id":3}\n',
        encoding="utf-8",
    )
    outlets = run / "delin" / "shapes" / "outlets.gpkg"
    outlets.parent.mkdir(parents=True)
    gpd.GeoDataFrame(
        {"outlet_id": [1], "lat": [40.0], "lon": [-86.0]},
        geometry=[Point(-86.0, 40.0)],
        crs="EPSG:4326",
    ).to_file(outlets, driver="GPKG")
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 cha1 1 10.0 40.0 -86.0 0 1 null 0 0 0 0\n"
        "3 cha3 3 20.0 40.3 -86.3 0 3 null 0 0 0 0\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 1 cha1 1.0 1.0\n"
        "1 1 1 2010 1 3 cha3 2.0 2.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node("1")
    graph.add_node("3")
    graph_path = run / "delin" / "routing_graph.graphml"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(graph, graph_path)
    monkeypatch.setattr(
        mass_trace_module,
        "_subbasin_area_map",
        lambda _run: {1: 10.0, 3: 20.0},
    )

    report = trace_terminal_inventory(run, selected_outlet_gis_id=3, out_dir=run / "reports")

    assert report.gauge_lat == pytest.approx(40.0)
    assert report.gauge_lon == pytest.approx(-86.0)
    assert report.gauge_coordinate_source == "delin/shapes/outlets.gpkg"
    by_gid = {row.terminal_gis_id: row for row in report.terminal_inventory}
    assert by_gid[1].is_nearest_terminal is True
    assert by_gid[1].distance_to_usgs_outlet_m == pytest.approx(0.0)
    assert by_gid[3].is_selected_evaluation_outlet is True
    assert by_gid[3].distance_to_usgs_outlet_m is not None
    assert report.source_backed_alternatives[0]["option"] == (
        "audit_selected_terminal_against_nearest_gauge_terminal"
    )
    assert report.source_backed_alternatives[0]["nearest_terminal_gis_id"] == 1
    assert report.terminal_outlet_conflict_class == (
        "selected_largest_terminal_not_nearest_minor_branch_conflict"
    )
    assert "selected_terminal_largest_flow" in report.terminal_outlet_conflict_flags
    assert report.source_backed_alternatives[0]["terminal_outlet_conflict_class"] == (
        "selected_largest_terminal_not_nearest_minor_branch_conflict"
    )
    assert report.recommended_probe_order[0]["diagnostic"] == (
        "audit_selected_terminal_against_nearest_gauge_terminal"
    )
    persisted = json.loads((run / "reports" / "terminal_trace.json").read_text(encoding="utf-8"))
    assert persisted["gauge_coordinate_source"] == "delin/shapes/outlets.gpkg"
    assert persisted["terminal_outlet_conflict_class"] == (
        "selected_largest_terminal_not_nearest_minor_branch_conflict"
    )
    assert persisted["recommended_probe_order"][0]["diagnostic"] == (
        "audit_selected_terminal_against_nearest_gauge_terminal"
    )
    markdown = (run / "reports" / "terminal_trace.md").read_text(encoding="utf-8")
    assert "Gauge coordinate source" in markdown
    assert "Terminal outlet conflict class" in markdown
    assert "Terminal distance ranking used gauge coordinates" in markdown
    assert "audit_selected_terminal_against_nearest_gauge_terminal" in markdown


def test_terminal_trace_records_pairwise_terminal_overlap(monkeypatch, tmp_path: Path):
    import networkx as nx

    from swatplus_builder.output import mass_trace as mass_trace_module

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"fixture","selected_outlet_gis_id":2}\n',
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 cha1 1 10.0 40.2 -86.2 0 1 null 0 0 0 2 sdc 2 tot 1.00000 sdc 3 tot 1.00000\n"
        "2 cha2 2 20.0 40.0 -86.0 0 2 null 0 0 0 0\n"
        "3 cha3 3 30.0 40.1 -86.1 0 3 null 0 0 0 0\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 2 cha2 1.0 1.0\n"
        "1 1 1 2010 1 3 cha3 2.0 2.0\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_edge("1", "2")
    graph.add_edge("1", "3")
    graph_path = run / "delin" / "routing_graph.graphml"
    graph_path.parent.mkdir(parents=True)
    nx.write_graphml(graph, graph_path)
    monkeypatch.setattr(
        mass_trace_module,
        "_subbasin_area_map",
        lambda _run: {1: 10.0, 2: 20.0, 3: 30.0},
    )

    report = trace_terminal_inventory(run, selected_outlet_gis_id=2, out_dir=run / "reports")

    assert report.shared_upstream_area_km2 == pytest.approx(10.0)
    assert len(report.terminal_overlap_pairs) == 1
    overlap = report.terminal_overlap_pairs[0]
    assert overlap.terminal_a_gis_id == 2
    assert overlap.terminal_b_gis_id == 3
    assert overlap.shared_upstream_area_km2 == pytest.approx(10.0)
    assert overlap.fraction_of_terminal_a == pytest.approx(10.0 / 30.0)
    assert overlap.fraction_of_terminal_b == pytest.approx(10.0 / 40.0)
    assert overlap.shared_channel_ids == [1]
    persisted = json.loads((run / "reports" / "terminal_trace.json").read_text(encoding="utf-8"))
    assert persisted["terminal_overlap_pairs"][0]["shared_channel_ids"] == [1]
    markdown = (run / "reports" / "terminal_trace.md").read_text(encoding="utf-8")
    assert "Terminal Overlap Pairs" in markdown
    assert "Terminal overlap pair count" in markdown


def test_terminal_trace_ignores_unemitted_delineation_graph_split(monkeypatch, tmp_path: Path):
    import networkx as nx

    from swatplus_builder.output import mass_trace as mass_trace_module

    run = tmp_path / "run"
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (run / "metadata.json").write_text(
        '{"usgs_id":"fixture","selected_outlet_gis_id":2}\n',
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text(
        "chandeg.con\n"
        "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 cha1 1 10.0 40.2 -86.2 0 1 null 0 0 0 1 sdc 2 tot 1.00000\n"
        "2 cha2 2 20.0 40.0 -86.0 0 2 null 0 0 0 0\n"
        "3 cha3 3 30.0 40.1 -86.1 0 3 null 0 0 0 0\n",
        encoding="utf-8",
    )
    (txt / "channel_sd_day.txt").write_text(
        "channel_sd_day\n"
        "jday mon day yr unit gis_id name flo_in flo_out\n"
        "m^3/s m^3/s\n"
        "1 1 1 2010 1 2 cha2 1.0 1.0\n"
        "1 1 1 2010 1 3 cha3 2.0 2.0\n",
        encoding="utf-8",
    )
    raw_graph = nx.DiGraph()
    raw_graph.add_edge("1", "2")
    raw_graph.add_edge("1", "3")
    graph_path = run / "delin" / "routing_graph.graphml"
    graph_path.parent.mkdir(parents=True)
    nx.write_graphml(raw_graph, graph_path)
    monkeypatch.setattr(
        mass_trace_module,
        "_subbasin_area_map",
        lambda _run: {1: 10.0, 2: 20.0, 3: 30.0},
    )

    report = trace_terminal_inventory(run, selected_outlet_gis_id=2, out_dir=run / "reports")

    assert report.shared_upstream_area_km2 == pytest.approx(0.0)
    assert report.terminal_overlap_pairs == []
    assert report.selected_terminal_upstream_area_km2 == pytest.approx(30.0)
    assert report.all_terminal_upstream_area_km2 == pytest.approx(60.0)


def test_parameter_screen_marks_cn2_urban_scope_for_urban_volume_context() -> None:
    payload = {
        "warnings": [],
        "parameters": [
            {
                "parameter": "CN2",
                "activity_class": "active",
                "evidence": {"target_file": "cntable.lum", "target_column": "wood_*"},
            },
            {
                "parameter": "PERCO",
                "activity_class": "active",
                "evidence": {"target_file": "hydrology.hyd", "target_column": "perco"},
            },
        ],
    }
    updates = _annotate_parameter_screen_for_volume_context(
        payload,
        {
            "diagnostic_flags": [{"code": "urban_curve_number_fixed_high"}],
            "urban_assumptions": {
                "urban_hru_fraction": 0.8,
                "hru_weighted_urb_cn": 98.0,
            },
        },
    )

    cn2 = payload["parameters"][0]
    assert updates["flags"] == ["cn2_runtime_cn_table_scope_required"]
    assert updates["effective_activity_classes"] == {"CN2": "active"}
    assert cn2["activity_class"] == "active"
    assert cn2["basin_context"]["effective_activity_class"] == "active"
    assert "landuse.lum:cn2" in cn2["basin_context"]["reason"]
    assert "cntable.lum" in cn2["basin_context"]["reason"]
    assert payload["warnings"]


def test_parameter_screen_marks_et_controls_for_et_dominated_context() -> None:
    payload = {
        "warnings": [],
        "parameters": [
            {"parameter": "PET_CO", "activity_class": "not_tested", "evidence": {}},
            {"parameter": "ESCO", "activity_class": "weak", "evidence": {}},
            {"parameter": "EPCO", "activity_class": "not_tested", "evidence": {}},
            {"parameter": "CN2", "activity_class": "active", "evidence": {}},
        ],
    }

    updates = _annotate_parameter_screen_for_physical_context(
        payload,
        {
            "condition_codes": ["ET_DOMINATED"],
            "wb": {"precip": 1000.0, "et": 780.0, "pet": 1200.0, "esoil": 600.0, "eplant": 150.0},
        },
    )

    assert updates["flags"] == ["et_dominated_pet_esco_epco_probe_required"]
    assert updates["effective_activity_classes"] == {
        "PET_CO": "requires_basin_screen",
        "ESCO": "requires_basin_screen",
        "EPCO": "requires_basin_screen",
    }
    for row in payload["parameters"][:3]:
        assert row["basin_context"]["effective_activity_class"] == "requires_basin_screen"
        assert row["basin_context"]["et_to_precip"] == 0.78
    assert "ET_DOMINATED" in payload["warnings"][0]


def test_skill_diagnostics_annotate_sensitivity_gap_parameters(tmp_path: Path) -> None:
    diagnostics_json = tmp_path / "skill_diagnostics.json"
    diagnostics_json.write_text(
        json.dumps(
            {
                "diagnostic_flags": [
                    {
                        "symptom": "Low baseflow",
                        "suggested_parameters": ["ALPHA_BF", "RCHG_DP", "GW_DELAY"],
                    }
                ],
                "source_backed_alternatives": [
                    {
                        "option": "audit_surface_runoff_lag_and_peak_timing",
                        "parameters": ["SURLAG"],
                    },
                    {
                        "option": "rebalance_runoff_and_et_partition",
                        "parameters": ["CN2", "ESCO", "EPCO"],
                    },
                    {
                        "option": (
                            "replace_legacy_gw_delay_advice_with_supported_alpha_and_"
                            "partition_controls"
                        ),
                        "parameters": ["ALPHA_BF", "LATQ_CO", "PERCO", "RCHG_DP"],
                        "blocked_parameters": ["GW_DELAY"],
                    },
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = _annotate_skill_sensitivity_gaps(
        diagnostics_json,
        {
            "CN2": "active",
            "ESCO": "active",
            "LATQ_CO": "active",
            "PERCO": "weak",
            "ALPHA_BF": "dead",
        },
    )

    assert payload["skill_probe_gap_parameters"] == ["SURLAG", "EPCO", "ALPHA_BF", "RCHG_DP"]
    assert payload["skill_probe_gap_reasons"] == {
        "SURLAG": "not_screened",
        "EPCO": "not_screened",
        "ALPHA_BF": "dead",
        "RCHG_DP": "not_screened",
    }
    assert payload["skill_screened_dead_parameters"] == ["ALPHA_BF"]
    assert payload["skill_unscreened_suggested_parameters"] == ["SURLAG", "EPCO", "RCHG_DP"]
    assert payload["skill_usable_suggested_parameters"] == ["CN2", "ESCO", "LATQ_CO", "PERCO"]
    assert payload["skill_probe_gap_claim_impact"] == (
        "diagnostic_only_until_screened_dead_or_unscreened_suggested_controls_are_explained"
    )
    assert payload["diagnostic_flags"][0]["sensitivity_context"]["screened_dead_parameters"] == [
        "ALPHA_BF"
    ]
    assert payload["diagnostic_flags"][0]["sensitivity_context"]["unscreened_suggested_parameters"] == [
        "RCHG_DP",
        "GW_DELAY",
    ]
    persisted = json.loads(diagnostics_json.read_text(encoding="utf-8"))
    assert persisted["sensitivity_screen_activity_classes"] == {
        "CN2": "active",
        "ESCO": "active",
        "LATQ_CO": "active",
        "PERCO": "weak",
        "ALPHA_BF": "dead",
    }
    assert persisted["skill_probe_gap_parameters"] == ["SURLAG", "EPCO", "ALPHA_BF", "RCHG_DP"]


def test_skill_diagnostics_annotate_parameter_bound_context(tmp_path: Path) -> None:
    diagnostics_json = tmp_path / "skill_diagnostics.json"
    diagnostics_json.write_text(
        json.dumps(
            {
                "diagnostic_flags": [
                    {
                        "symptom": "High-flow peaks are attenuated relative to observed events",
                        "suggested_parameters": ["SURLAG", "CN2"],
                        "suggested_action": "Run SURLAG/CN2 peak probe.",
                    }
                ],
                "next_actions": ["Run SURLAG/CN2 peak probe."],
                "source_backed_alternatives": [
                    {
                        "option": "audit_surface_runoff_lag_and_peak_timing",
                        "parameters": ["SURLAG"],
                    },
                    {
                        "option": "screen_channel_routing_attenuation_controls",
                        "parameters": ["CH_N2", "CH_K2"],
                    },
                    {
                        "option": "rebalance_runoff_and_et_partition",
                        "parameters": ["CN2"],
                    },
                ],
                "recommended_probe_order": [
                    {
                        "rank": 1,
                        "diagnostic": "audit_surface_runoff_lag_and_peak_timing",
                        "parameters": ["SURLAG"],
                    },
                    {
                        "rank": 2,
                        "diagnostic": "screen_channel_routing_attenuation_controls",
                        "parameters": ["CH_N2", "CH_K2"],
                    },
                    {
                        "rank": 3,
                        "diagnostic": "rebalance_runoff_and_et_partition",
                        "parameters": ["CN2"],
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = _annotate_skill_parameter_bound_context(
        diagnostics_json,
        {"SURLAG": 23.8, "CN2": 98.0},
    )

    assert payload["calibrated_parameter_bound_hits"]["SURLAG"]["boundary"] == "upper"
    assert payload["calibrated_parameter_bound_hits"]["CN2"]["boundary"] == "upper"
    flag = payload["diagnostic_flags"][0]
    assert flag["parameter_bound_context"]["all_tuned_suggested_parameters_at_bounds"] is True
    assert flag["bound_aware_next_action"].startswith("Suggested controls (SURLAG, CN2) are already")
    assert payload["next_actions"] == [flag["bound_aware_next_action"]]
    assert payload["recommended_probe_order"][0]["diagnostic"] == (
        "screen_channel_routing_attenuation_controls"
    )
    assert payload["recommended_probe_order"][1]["bound_exhausted_parameters"] == ["SURLAG"]
    assert payload["recommended_probe_order"][2]["bound_exhausted_parameters"] == ["CN2"]
    persisted = json.loads(diagnostics_json.read_text(encoding="utf-8"))
    assert persisted["parameter_bound_claim_impact"] == (
        "diagnostic_only_until_bound-hit controls are structurally explained"
    )
    assert persisted["source_backed_alternatives"][0]["option"] == (
        "screen_channel_routing_attenuation_controls"
    )


def test_diagnostic_calibration_provenance_records_staged_protocol(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    txt = source / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)
    benchmark = source / "benchmark"
    benchmark.mkdir(parents=True)
    (benchmark / "benchmark_lock.json").write_text("{}", encoding="utf-8")
    (benchmark / "alignment.csv").write_text(
        "date,obs,sim\n"
        "2010-01-01,1.0,0.8\n"
        "2010-01-02,2.0,1.6\n"
        "2010-01-03,1.5,1.2\n",
        encoding="utf-8",
    )
    best_json = source / "calibration" / "calibration_reports_locked" / "best_solution.json"
    best_json.parent.mkdir(parents=True)
    protocol = [
        {"phase": "volume", "parameters": ["CN2", "PERCO"]},
        {"phase": "baseflow_subsurface", "parameters": ["LATQ_CO"]},
        {"phase": "peaks_timing", "parameters": []},
        {"phase": "kge_nse_finetune", "parameters": ["CN2", "PERCO", "LATQ_CO", "ESCO"]},
    ]
    best_json.write_text(
        json.dumps(
            {
                "parameters": {"CN2": 75.0},
                "metrics": {"nse": 0.3, "kge": 0.4, "pbias": 5.0},
                "selection_policy": "staged_volume_baseflow_peaks_then_nse_kge",
                "calibration_protocol": protocol,
            }
        ),
        encoding="utf-8",
    )

    def fake_calibrate_against_lock(**kwargs):
        assert kwargs["parameters"] == ["CN2"]
        return CalibrationEvidence(
            basin_id="usgs_test",
            n_evaluations=4,
            best_nse=0.3,
            best_kge=0.4,
            best_parameters={"CN2": 75.0},
            history_csv=str(best_json.parent / "history.csv"),
            summary_md=str(best_json.parent / "summary.md"),
            best_solution_json=str(best_json),
            outdir=str(best_json.parent),
        )

    def fake_verify_calibration(**kwargs):
        from swatplus_builder.calibration.real_engine import params_hash

        verify_dir = source / "calibration" / "verification_real_objective"
        verified_txt = verify_dir / params_hash({"CN2": 75.0}) / "TxtInOut"
        _write_basin_wb(verified_txt)
        (verified_txt / "alignment_calibration.csv").write_text(
            "date,obs,sim\n"
            "2010-01-01,1.0,0.9\n"
            "2010-01-02,2.0,1.9\n"
            "2010-01-03,1.5,1.4\n",
            encoding="utf-8",
        )
        return VerificationResult(
            basin_id="usgs_test",
            benchmark_nse=0.1,
            benchmark_kge=0.2,
            verified_nse=0.3,
            verified_kge=0.4,
            delta_nse=0.2,
            delta_kge=0.2,
            improved=True,
            improvement_basis="nse_and_kge",
            verification_dir=str(verify_dir),
            verification_summary_path=str(source / "calibration" / "verification_summary.json"),
        )

    def fake_screen_parameters_against_lock(**kwargs):
        screened = set(kwargs["parameters"])
        assert "GW_DELAY" not in screened
        assert {"PET_CO", "EPCO", "SURLAG", "ALPHA_BF", "RCHG_DP", "LAT_TTIME", "CH_N2", "CH_K2"}.issubset(screened)
        return SimpleNamespace(
            basis="basin_specific",
            json_path=str(source / "calibration" / "sensitivity_screen_locked" / "sensitivity_screen.json"),
            markdown_path=str(source / "calibration" / "sensitivity_screen_locked" / "sensitivity_screen.md"),
            parameters=[{"parameter": "CN2", "activity_class": "active"}],
        )

    monkeypatch.setattr("swatplus_builder.calibration.locked_benchmark.calibrate_against_lock", fake_calibrate_against_lock)
    monkeypatch.setattr("swatplus_builder.calibration.locked_benchmark.screen_parameters_against_lock", fake_screen_parameters_against_lock)
    monkeypatch.setattr("swatplus_builder.calibration.locked_benchmark.verify_calibration", fake_verify_calibration)
    monkeypatch.setattr(
        "swatplus_builder.calibration.diagnostic_calibrator._check_locked_txt_routing_flow",
        lambda *args, **kwargs: {"status": "passed", "pass": True, "reason": "routing flow closure passed"},
    )

    result = run_diagnostic_calibration(source, claim_tier="research_grade")

    assert result.success is True
    assert result.provenance["sensitivity_screen_basis"] == "basin_specific"
    assert result.provenance["screened_parameters"] == ["CN2"]
    assert result.provenance["selection_policy"] == "staged_volume_baseflow_peaks_then_nse_kge"
    assert result.provenance["verification_improvement_basis"] == "nse_and_kge"
    assert result.provenance["verification_metrics"] == {"nse": 0.3, "kge": 0.4, "pbias": None}
    assert result.provenance["verification_delta_metrics"]["nse"] == 0.2
    assert result.provenance["final_routing_flow_gates"]["status"] == "passed"
    assert result.provenance["hydrograph_comparison"]["status"] == "written"
    assert Path(result.provenance["hydrograph_comparison"]["hydrograph_plot"]).exists()
    assert Path(result.provenance["hydrograph_comparison"]["hydrograph_plot_pdf"]).exists()
    assert Path(result.provenance["hydrograph_comparison"]["hydrograph_overlay_plot"]).exists()
    assert Path(result.provenance["hydrograph_comparison"]["hydrograph_overlay_plot_pdf"]).exists()
    assert result.provenance["skill_diagnostics"]["status"] == "written"
    assert Path(result.provenance["skill_diagnostics"]["skill_diagnostics_json"]).exists()
    assert Path(result.provenance["skill_diagnostics"]["skill_diagnostics_md"]).exists()
    hydrograph_metrics_path = Path(result.provenance["hydrograph_comparison"]["hydrograph_metrics_json"])
    assert hydrograph_metrics_path.exists()
    hydrograph_metrics = json.loads(hydrograph_metrics_path.read_text(encoding="utf-8"))
    assert "calibrated_kge" in hydrograph_metrics
    assert "delta_pbias" in hydrograph_metrics
    assert [p["phase"] for p in result.provenance["calibration_protocol"]] == [
        "volume",
        "baseflow_subsurface",
        "peaks_timing",
        "kge_nse_finetune",
    ]
    persisted = json.loads((source / "reports" / "diagnostic_calibration.json").read_text(encoding="utf-8"))
    assert persisted["provenance"]["calibration_protocol"] == protocol


def test_diagnostic_calibration_blocks_when_screen_retains_no_parameters(monkeypatch, tmp_path: Path):
    source = tmp_path / "source_no_sensitive"
    txt = source / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)
    benchmark = source / "benchmark"
    benchmark.mkdir(parents=True)
    (benchmark / "benchmark_lock.json").write_text("{}", encoding="utf-8")

    def fake_screen_parameters_against_lock(**kwargs):
        return SimpleNamespace(
            basis="basin_specific",
            json_path=str(source / "calibration" / "sensitivity_screen_locked" / "sensitivity_screen.json"),
            markdown_path=str(source / "calibration" / "sensitivity_screen_locked" / "sensitivity_screen.md"),
            parameters=[
                {"parameter": "CN2", "activity_class": "dead"},
                {"parameter": "PERCO", "activity_class": "not_tested"},
            ],
        )

    def fail_calibrate_against_lock(**kwargs):
        raise AssertionError("calibration search should be blocked by sensitivity screen")

    monkeypatch.setattr("swatplus_builder.calibration.locked_benchmark.screen_parameters_against_lock", fake_screen_parameters_against_lock)
    monkeypatch.setattr("swatplus_builder.calibration.locked_benchmark.calibrate_against_lock", fail_calibrate_against_lock)

    result = run_diagnostic_calibration(source, claim_tier="research_grade")

    assert result.success is False
    assert result.provenance["screened_parameters"] == []
    assert "No basin-specific active/weak eligible parameters" in result.provenance["error"]
    phases = {p.phase: p for p in result.phases}
    assert phases["sensitivity_screen"].status == "blocked"
    assert phases["baseflow_subsurface"].status == "blocked"


def test_diagnostic_calibration_retains_string_promotion_gate(monkeypatch, tmp_path: Path):
    source = tmp_path / "source_promotion_gate"
    txt = source / "project" / "Scenarios" / "Default" / "TxtInOut"
    _write_basin_wb(txt)
    benchmark = source / "benchmark"
    benchmark.mkdir(parents=True)
    (benchmark / "benchmark_lock.json").write_text("{}", encoding="utf-8")
    history_csv = source / "calibration" / "calibration_reports_locked" / "history.csv"
    history_csv.parent.mkdir(parents=True)
    history_csv.write_text(
        "eval_idx,phase,metric_nse,metric_kge,metric_pbias,volume_gate_passed,physical_gate_passed,calibration_process_gate_passed\n",
        encoding="utf-8",
    )

    def fake_screen_parameters_against_lock(**kwargs):
        return SimpleNamespace(
            basis="basin_specific",
            json_path=str(source / "calibration" / "sensitivity_screen_locked" / "sensitivity_screen.json"),
            markdown_path=str(source / "calibration" / "sensitivity_screen_locked" / "sensitivity_screen.md"),
            parameters=[{"parameter": "CN2", "activity_class": "active"}],
        )

    def fail_calibrate_against_lock(**kwargs):
        exc = RuntimeError("No calibration candidate passed the promotion gates.")
        exc.context = {
            "phase": "kge_nse_finetune",
            "history_csv": str(history_csv),
            "n_evaluations": 1,
            "promotion_gate": "abs(pbias) <= 30 and candidate calibration process gates pass",
        }
        raise exc

    monkeypatch.setattr("swatplus_builder.calibration.locked_benchmark.screen_parameters_against_lock", fake_screen_parameters_against_lock)
    monkeypatch.setattr("swatplus_builder.calibration.locked_benchmark.calibrate_against_lock", fail_calibrate_against_lock)

    result = run_diagnostic_calibration(source, claim_tier="research_grade")

    assert result.success is False
    assert result.provenance["promotion_gate"] == (
        "abs(pbias) <= 30 and candidate calibration process gates pass"
    )
    persisted = json.loads((source / "reports" / "diagnostic_calibration.json").read_text(encoding="utf-8"))
    assert persisted["provenance"]["promotion_gate"] == result.provenance["promotion_gate"]
