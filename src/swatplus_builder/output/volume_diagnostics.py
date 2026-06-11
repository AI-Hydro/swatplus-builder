"""Volume-bias diagnostic synthesis for workflow artifacts.

This module does not rerun SWAT+ or reinterpret output units.  It combines
locked alignment, physical gate context, basin water-balance terms, and outlet
provenance into a small audit report for runs blocked by simulated/observed
flow-volume mismatch.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..gis.landuse import NLCD_CLASS_DESCRIPTIONS, NLCD_URBAN_CODES, is_water
from .eval import _extract_flo_out_rows, _normalize_discharge_units, _terminal_ids_from_chandeg_con
from .metrics import kge, kge_components, nse, pbias
from .plots.utils import align_timeseries
from .reader import read_output_file
from .weather_forcing import write_weather_forcing_summary


def write_volume_bias_diagnostics(
    run_dir: Path | str,
    *,
    physical_gates: dict[str, Any] | None = None,
    values: dict[str, Any] | None = None,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Write JSON/Markdown diagnostics for volume-bias gate failures.

    The report is useful even when only part of the evidence bundle exists:
    missing inputs are reported as ``available=false`` sections instead of
    raising, so workflow completion is not hidden behind diagnostics failures.
    """

    run = Path(run_dir).expanduser().resolve()
    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)

    gates = physical_gates or {}
    vals = values or {}
    alignment = _alignment_summary(run, vals)
    water_balance = _water_balance_summary(gates)
    outlet = _outlet_summary(run, vals)
    hru_runoff = _hru_runoff_summary(run)
    aquifer_context = _aquifer_summary(run)
    landuse_raster = _landuse_raster_summary(run)
    urban_assumptions = _urban_assumptions_summary(run, hru_runoff)
    routing_scope = _routing_scope_summary(run, vals)
    terminal_hydrograph = _terminal_hydrograph_scope_summary(run, vals, routing_scope, outlet)
    weather_forcing = write_weather_forcing_summary(run, values=vals, out_dir=destination)
    soil_context = _soil_context(vals)
    flags = _classify(
        gates,
        alignment,
        water_balance,
        outlet,
        hru_runoff,
        landuse_raster,
        urban_assumptions,
        routing_scope,
        terminal_hydrograph,
        weather_forcing,
    )
    primary = flags[0]["code"] if flags else "no_volume_bias_diagnostic_flags"
    terminal_scope_blocker = _terminal_scope_blocker(flags, terminal_hydrograph)
    if terminal_scope_blocker is None and isinstance(vals.get("terminal_scope_blocker"), str):
        terminal_scope_blocker = vals["terminal_scope_blocker"]
    terminal_hydrograph_scope_classification = classify_terminal_hydrograph_scope(
        terminal_hydrograph,
        flags,
    )
    if (
        terminal_hydrograph_scope_classification.get("class")
        == "selected_metric_passes_but_area_scope_partial"
    ):
        terminal_scope_blocker = "outlet_scope_volume_mismatch"
    terminal_scope_resolution_plan = build_terminal_scope_resolution_plan(
        terminal_hydrograph,
        terminal_hydrograph_scope_classification,
        terminal_scope_blocker=terminal_scope_blocker,
    )
    post_aggregation_process_context = _post_aggregation_process_context(
        terminal_hydrograph,
        terminal_hydrograph_scope_classification,
        water_balance,
        weather_forcing,
        soil_context,
    )
    terminal_scope_decision_request = build_terminal_scope_decision_request(
        basin_id=_safe_str(vals.get("usgs_id") or vals.get("basin") or vals.get("site_no")),
        blocker_domain=_safe_str(vals.get("blocker_domain")),
        terminal_scope_resolution_plan=terminal_scope_resolution_plan,
        post_aggregation_process_context=post_aggregation_process_context,
    )

    report = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_dir": str(run),
        "physical_gate_status": gates.get("status"),
        "dominant_blocker": gates.get("dominant_blocker"),
        "condition_codes": gates.get("condition_codes") or [],
        "primary_issue": primary,
        "alignment": alignment,
        "water_balance": water_balance,
        "aquifer_context": aquifer_context,
        "hru_runoff": hru_runoff,
        "landuse_raster": landuse_raster,
        "urban_assumptions": urban_assumptions,
        "outlet_provenance": outlet,
        "routing_scope": routing_scope,
        "terminal_hydrograph_scope": terminal_hydrograph,
        "terminal_hydrograph_scope_class": terminal_hydrograph_scope_classification["class"],
        "terminal_hydrograph_scope_flags": terminal_hydrograph_scope_classification["flags"],
        "terminal_hydrograph_scope_recommended_focus": terminal_hydrograph_scope_classification[
            "recommended_focus"
        ],
        "terminal_hydrograph_scope_claim_impact": terminal_hydrograph_scope_classification[
            "claim_impact"
        ],
        "terminal_scope_resolution_plan": terminal_scope_resolution_plan,
        "terminal_scope_decision_request": terminal_scope_decision_request,
        "post_aggregation_process_context": post_aggregation_process_context,
        "weather_forcing_summary": weather_forcing,
        "weather_forcing_summary_path": weather_forcing.get("json_path"),
        "high_runoff_demand_context": _high_runoff_demand_context(
            weather_forcing,
            water_balance,
            aquifer_context,
            routing_scope,
            terminal_hydrograph,
        ),
        "terminal_scope_blocker": terminal_scope_blocker,
        "soil_context": soil_context,
        "diagnostic_flags": flags,
        "next_actions": _next_actions(flags, gates, vals),
        "source_backed_alternatives": _source_backed_alternatives(flags, vals),
        "recommended_probe_order": _recommended_probe_order(flags, vals),
    }

    json_path = destination / "volume_bias_diagnostics.json"
    md_path = destination / "volume_bias_diagnostics.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    report["json_path"] = str(json_path)
    report["markdown_path"] = str(md_path)
    return report


def _alignment_summary(run: Path, values: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for key in ("alignment_csv", "alignment_path", "benchmark_alignment_path"):
        if values.get(key):
            candidates.append(Path(str(values[key])))
    candidates.extend([run / "benchmark" / "alignment.csv", run / "outputs" / "alignment.csv"])
    alignment_path = next((p for p in candidates if p.is_file()), None)
    if alignment_path is None:
        metrics = values.get("metrics") if isinstance(values.get("metrics"), dict) else {}
        return {
            "available": False,
            "reason": "alignment_csv_missing",
            "pbias_pct": _safe_float(metrics.get("pbias")) if metrics else None,
            "nse": _safe_float(metrics.get("nse")) if metrics else None,
            "kge": _safe_float(metrics.get("kge")) if metrics else None,
        }

    try:
        df = pd.read_csv(alignment_path, index_col=0, parse_dates=True)
        df = df[["obs", "sim"]].astype(float).dropna()
    except Exception as exc:
        return {"available": False, "path": str(alignment_path), "reason": str(exc)}
    if df.empty:
        return {"available": False, "path": str(alignment_path), "reason": "alignment_empty"}

    obs_sum = float(df["obs"].sum())
    sim_sum = float(df["sim"].sum())
    pbias = ((sim_sum - obs_sum) / obs_sum * 100.0) if obs_sum else None
    return {
        "available": True,
        "path": str(alignment_path),
        "n_days": int(len(df)),
        "start": str(pd.to_datetime(df.index[0]).date()),
        "end": str(pd.to_datetime(df.index[-1]).date()),
        "obs_sum": obs_sum,
        "sim_sum": sim_sum,
        "obs_mean": float(df["obs"].mean()),
        "sim_mean": float(df["sim"].mean()),
        "sim_to_obs_volume_ratio": (sim_sum / obs_sum) if obs_sum else None,
        "pbias_pct": pbias,
        "nse": _safe_float(_lookup(values, ("metrics", "nse"))),
        "kge": _safe_float(_lookup(values, ("metrics", "kge"))),
    }


def _soil_context(values: dict[str, Any]) -> dict[str, Any]:
    pct_fallback = _safe_float(values.get("pct_fallback_soils"))
    soil_mode = values.get("soil_mode")
    provenance = values.get("soil_provenance_mode")
    degraded = (
        (pct_fallback is not None and pct_fallback > 0.0)
        or str(soil_mode or "").lower() in {"fallback", "not_verified"}
    )
    return {
        "soil_mode": str(soil_mode) if soil_mode is not None else None,
        "soil_provenance_mode": str(provenance) if provenance is not None else None,
        "pct_fallback_soils": pct_fallback,
        "soil_degraded": bool(degraded),
    }


def _water_balance_summary(physical_gates: dict[str, Any]) -> dict[str, Any]:
    wb = physical_gates.get("wb")
    if not isinstance(wb, dict) or not wb:
        return {"available": False, "reason": "physical_gates_wb_missing"}
    precip = _safe_float(wb.get("precip"))
    et = _safe_float(wb.get("et"))
    eplant = _safe_float(wb.get("eplant"))
    esoil = _safe_float(wb.get("esoil"))
    pet = _safe_float(wb.get("pet"))
    wateryld = _safe_float(wb.get("wateryld"))
    wet_oflo = _safe_float(wb.get("wet_oflo"))
    snofall = _safe_float(wb.get("snofall"))
    snomlt = _safe_float(wb.get("snomlt"))
    sno_init = _safe_float(wb.get("sno_init"))
    sno_final = _safe_float(wb.get("sno_final"))
    snopack = _safe_float(wb.get("snopack"))
    sw_change = _safe_float(wb.get("sw_change"))
    laglatq = _safe_float(wb.get("laglatq"))
    gwsoilq = _safe_float(wb.get("gwsoilq"))
    surq = _safe_float(wb.get("surq_gen", wb.get("surq")))
    latq = _safe_float(wb.get("latq"))
    perc = _safe_float(wb.get("perc"))
    cn = _safe_float(wb.get("cn"))
    net_wateryld = None
    if wateryld is not None:
        wetland_outflow = max(0.0, wet_oflo or 0.0)
        net_wateryld = max(0.0, wateryld - wetland_outflow) if wetland_outflow > 0.0 else wateryld
    residual = None
    if precip and all(x is not None for x in (net_wateryld, et, perc)):
        residual = (precip - (net_wateryld or 0.0) - (et or 0.0) - (perc or 0.0)) / precip * 100.0
    return {
        "available": True,
        "precip_mm": precip,
        "et_mm": et,
        "eplant_mm": eplant,
        "esoil_mm": esoil,
        "pet_mm": pet,
        "wateryld_mm": wateryld,
        "wet_oflo_mm": wet_oflo,
        "snowfall_mm": snofall,
        "snowmelt_mm": snomlt,
        "snow_initial_mm": sno_init,
        "snow_final_mm": sno_final,
        "snowpack_mm": snopack,
        "soil_water_change_mm": sw_change,
        "lagged_lateral_flow_mm": laglatq,
        "groundwater_soil_flow_mm": gwsoilq,
        "net_wateryld_mm": net_wateryld,
        "surq_gen_mm": surq,
        "latq_mm": latq,
        "perc_mm": perc,
        "cn": cn,
        "et_to_precip": _ratio(et, precip),
        "pet_to_precip": _ratio(pet, precip),
        "snowfall_to_precip": _ratio(snofall, precip),
        "snowmelt_to_precip": _ratio(snomlt, precip),
        "snowpack_to_precip": _ratio(snopack, precip),
        "eplant_to_et": _ratio(eplant, et),
        "esoil_to_et": _ratio(esoil, et),
        "wateryld_to_precip": _ratio(wateryld, precip),
        "net_wateryld_to_precip": _ratio(net_wateryld, precip),
        "surface_runoff_to_precip": _ratio(surq, precip),
        "latq_to_precip": _ratio(latq, precip),
        "perc_to_precip": _ratio(perc, precip),
        "mass_residual_pct_of_precip": residual,
        "mass_residual_basis": "net_wateryld_excludes_wet_oflo" if wet_oflo and wet_oflo > 0.0 else "wateryld",
    }


def _aquifer_summary(run: Path) -> dict[str, Any]:
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    path = txt / "basin_aqu_aa.txt"
    if not path.is_file():
        path = txt / "aquifer_aa.txt"
    if not path.is_file():
        return {"available": False, "reason": "aquifer_output_missing"}
    try:
        table = read_output_file(path)
    except Exception as exc:
        return {"available": False, "path": str(path), "reason": str(exc)}
    if not table.rows:
        return {"available": False, "path": str(path), "reason": "aquifer_output_empty"}
    df = pd.DataFrame(table.rows)

    def mean_col(name: str) -> float | None:
        return _safe_float(df[name].mean()) if name in df.columns else None

    def max_col(name: str) -> float | None:
        return _safe_float(df[name].max()) if name in df.columns else None

    return {
        "available": True,
        "path": str(path),
        "aquifer_count": int(len(df)),
        "flow_mean_mm": mean_col("flo"),
        "flow_max_mm": max_col("flo"),
        "storage_mean_mm": mean_col("stor"),
        "storage_max_mm": max_col("stor"),
        "recharge_mean_mm": mean_col("rchrg"),
        "recharge_max_mm": max_col("rchrg"),
        "seepage_mean_mm": mean_col("seep"),
        "revap_mean_mm": mean_col("revap"),
        "flow_to_storage_mean_ratio": _ratio(mean_col("flo"), mean_col("stor")),
        "recharge_to_storage_mean_ratio": _ratio(mean_col("rchrg"), mean_col("stor")),
    }


def _outlet_summary(run: Path, values: dict[str, Any]) -> dict[str, Any]:
    metadata = _load_json(run / "metadata.json")
    top = _load_json(run / "outlet_provenance.json")
    benchmark = _load_json(run / "benchmark" / "outlet_provenance.json")
    detailed = _load_json(run / "outputs" / "outlet_provenance.json")
    selection = _lookup(detailed, ("selection_pass", "diagnostics")) or {}
    pinned = _lookup(detailed, ("pinned_pass", "diagnostics")) or {}
    selected = _first_not_none(
        values.get("selected_outlet_gis_id"),
        benchmark.get("selected_outlet_gis_id"),
        metadata.get("selected_outlet_gis_id"),
        top.get("selected_outlet_gis_id"),
        pinned.get("selected_outlet_gis_id") if isinstance(pinned, dict) else None,
    )
    requested = _first_not_none(
        values.get("requested_outlet_gis_id"),
        benchmark.get("requested_outlet_gis_id"),
        metadata.get("requested_outlet_gis_id"),
        selection.get("requested_outlet_gis_id") if isinstance(selection, dict) else None,
    )
    terminal_ids = _first_not_none(
        values.get("terminal_outlet_ids"),
        benchmark.get("terminal_outlet_ids"),
        selection.get("terminal_outlet_ids") if isinstance(selection, dict) else None,
        pinned.get("terminal_outlet_ids") if isinstance(pinned, dict) else None,
    )
    terminal_count = _first_not_none(
        values.get("terminal_outlet_count"),
        len(terminal_ids) if isinstance(terminal_ids, list) else None,
        selection.get("terminal_outlet_count") if isinstance(selection, dict) else None,
        pinned.get("terminal_outlet_count") if isinstance(pinned, dict) else None,
    )
    return {
        "available": bool(metadata or top or benchmark or detailed),
        "requested_outlet_gis_id": requested,
        "selected_outlet_gis_id": selected,
        "outlet_autodetected": bool(
            _first_not_none(
                values.get("outlet_autodetected"),
                benchmark.get("outlet_autodetected"),
                metadata.get("outlet_autodetected"),
                selection.get("outlet_autodetected") if isinstance(selection, dict) else None,
            )
        ),
        "outlet_selection_reason": _first_not_none(
            values.get("outlet_selection_reason"),
            benchmark.get("outlet_selection_reason"),
            metadata.get("outlet_selection_reason"),
            selection.get("outlet_selection_reason") if isinstance(selection, dict) else None,
        ),
        "requested_outlet_is_terminal": (
            selection.get("requested_outlet_is_terminal") if isinstance(selection, dict) else None
        ),
        "terminal_outlet_count": terminal_count,
        "terminal_outlet_ids": terminal_ids,
        "pinned_policy": _lookup(detailed, ("pinned_pass", "policy")),
        "selection_policy": _lookup(detailed, ("selection_pass", "policy")),
    }


def _routing_scope_summary(run: Path, values: dict[str, Any]) -> dict[str, Any]:
    gate_path = _first_existing_path(
        values.get("routing_flow_gates_path"),
        run / "routing_flow_gates.json",
    )
    gate = _load_json(gate_path) if gate_path else {}
    trace_path = _first_existing_path(
        gate.get("json_path") if isinstance(gate, dict) else None,
        values.get("routing_flow_trace_path"),
        run / "reports" / "mass_trace.json",
    )
    trace = _load_json(trace_path) if trace_path else {}
    terminal_trace_path = _first_existing_path(
        values.get("terminal_trace_path"),
        gate.get("terminal_trace_path") if isinstance(gate, dict) else None,
        trace.get("terminal_trace_path") if isinstance(trace, dict) else None,
        run / "reports" / "terminal_trace.json",
    )
    terminal_trace = _load_json(terminal_trace_path) if terminal_trace_path else {}

    def value(name: str) -> Any:
        return _first_not_none(
            values.get(name),
            gate.get(name) if isinstance(gate, dict) else None,
            trace.get(name) if isinstance(trace, dict) else None,
        )

    flags = value("flags") or []
    if not isinstance(flags, list):
        flags = []
    return {
        "available": bool(gate or trace),
        "routing_flow_gates_path": str(gate_path) if gate_path else None,
        "mass_trace_path": str(trace_path) if trace_path else None,
        "terminal_trace_path": str(terminal_trace_path) if terminal_trace_path else None,
        "closure_status": value("closure_status"),
        "flags": [str(flag) for flag in flags if flag],
        "selected_outlet_gis_id": value("selected_outlet_gis_id"),
        "terminal_outlet_count": value("terminal_outlet_count"),
        "selected_terminal_fraction_of_all_terminal_flow": _safe_float(
            value("selected_terminal_fraction_of_all_terminal_flow")
        ),
        "all_terminal_routed_to_channel_closure_ratio": _safe_float(
            value("all_terminal_routed_to_channel_closure_ratio")
        ),
        "all_terminal_mass_closure_ratio": _safe_float(value("all_terminal_mass_closure_ratio")),
        "routed_to_channel_closure_ratio": _safe_float(value("routed_to_channel_closure_ratio")),
        "mass_closure_ratio": _safe_float(value("mass_closure_ratio")),
        **_terminal_aggregation_context(terminal_trace),
    }


def _terminal_aggregation_context(terminal_trace: dict[str, Any]) -> dict[str, Any]:
    if not terminal_trace:
        return {
            "terminal_failure_class": None,
            "shared_upstream_area_km2": None,
            "all_terminal_upstream_area_km2": None,
            "all_terminal_aggregation_valid": None,
            "all_terminal_aggregation_reason": "terminal_trace_unavailable",
            "gauge_coordinate_source": None,
            "nearest_terminal_gis_id": None,
            "nearest_terminal_distance_to_gauge_m": None,
            "selected_outlet_is_nearest_terminal": None,
            "selected_outlet_distance_to_gauge_m": None,
        }
    inventory = terminal_trace.get("terminal_inventory")
    nearest_row = None
    selected_row = None
    if isinstance(inventory, list):
        for item in inventory:
            if not isinstance(item, dict):
                continue
            if item.get("is_nearest_terminal") is True:
                nearest_row = item
            if item.get("is_selected_evaluation_outlet") is True:
                selected_row = item
    shared_area = _safe_float(terminal_trace.get("shared_upstream_area_km2"))
    all_area = _safe_float(terminal_trace.get("all_terminal_upstream_area_km2"))
    tolerance = max(0.01, 0.01 * all_area) if all_area is not None else 0.01
    aggregation_valid = None if shared_area is None else shared_area <= tolerance
    reason = "no_material_terminal_upstream_overlap"
    if aggregation_valid is False:
        reason = (
            "terminal_upstream_areas_overlap; summed all-terminal hydrograph is "
            "diagnostic-only and not claim-valid"
        )
    elif aggregation_valid is None:
        reason = "terminal_shared_upstream_area_missing"
    return {
        "terminal_failure_class": _first_not_none(
            terminal_trace.get("failure_class"),
            terminal_trace.get("terminal_failure_class"),
        ),
        "shared_upstream_area_km2": shared_area,
        "all_terminal_upstream_area_km2": all_area,
        "sum_terminal_upstream_area_km2": _safe_float(terminal_trace.get("sum_terminal_upstream_area_km2")),
        "all_terminal_aggregation_valid": aggregation_valid,
        "all_terminal_aggregation_reason": reason,
        "gauge_coordinate_source": terminal_trace.get("gauge_coordinate_source"),
        "nearest_terminal_gis_id": _safe_int(nearest_row.get("terminal_gis_id")) if nearest_row else None,
        "nearest_terminal_distance_to_gauge_m": (
            _safe_float(nearest_row.get("distance_to_usgs_outlet_m")) if nearest_row else None
        ),
        "selected_outlet_is_nearest_terminal": (
            selected_row.get("is_nearest_terminal") if isinstance(selected_row, dict) else None
        ),
        "selected_outlet_distance_to_gauge_m": _safe_float(
            terminal_trace.get("selected_outlet_distance_to_gauge_m")
        ),
    }


def _terminal_hydrograph_scope_summary(
    run: Path,
    values: dict[str, Any],
    routing_scope: dict[str, Any],
    outlet: dict[str, Any],
) -> dict[str, Any]:
    """Compare selected-terminal and all-terminal hydrographs against observations.

    This is diagnostic-only. Multi-terminal aggregation can reveal whether a
    volume deficit is mostly outlet scope, but it is not final gauge evidence
    until the selected outlet, gauge drainage area, and terminal inventory are
    explained.
    """

    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    if not txt.is_dir():
        return {"available": False, "reason": "txtinout_missing"}

    obs_path = _first_existing_path(
        values.get("observed_csv"),
        values.get("obs_csv"),
        run / "outputs" / "obs_q.csv",
    )
    if obs_path is None:
        return {"available": False, "reason": "observed_csv_missing"}
    obs = _read_observed_series(obs_path)
    if obs is None or obs.empty:
        return {"available": False, "observed_path": str(obs_path), "reason": "observed_series_unavailable"}

    source_candidates: list[Any] = []
    if values.get("sim_source_path"):
        source_candidates.append(values.get("sim_source_path"))
    source_name = values.get("sim_source_file")
    if source_name:
        source_candidates.append(txt / str(source_name))
    source_candidates.extend(
        [
            txt / "channel_sd_day.txt",
            txt / "channel_sdmorph_day.txt",
            txt / "basin_sd_cha_day.txt",
            txt / "channel_day.txt",
            txt / "basin_cha_day.txt",
        ]
    )
    source_path = _first_existing_path(*source_candidates)
    if source_path is None:
        return {"available": False, "observed_path": str(obs_path), "reason": "sim_channel_output_missing"}

    terminal_ids = _terminal_ids_from_values(values, routing_scope, outlet, txt)
    if not terminal_ids or len(terminal_ids) < 2:
        return {
            "available": False,
            "observed_path": str(obs_path),
            "sim_source_path": str(source_path),
            "reason": "multi_terminal_inventory_missing",
            "terminal_ids": terminal_ids,
        }

    selected = _safe_int(
        _first_not_none(
            routing_scope.get("selected_outlet_gis_id"),
            outlet.get("selected_outlet_gis_id"),
            values.get("selected_outlet_gis_id"),
        )
    )
    if selected is None:
        return {
            "available": False,
            "observed_path": str(obs_path),
            "sim_source_path": str(source_path),
            "reason": "selected_outlet_missing",
            "terminal_ids": terminal_ids,
        }

    try:
        table = read_output_file(source_path)
    except Exception as exc:
        return {
            "available": False,
            "observed_path": str(obs_path),
            "sim_source_path": str(source_path),
            "reason": f"sim_source_unreadable: {exc}",
            "terminal_ids": terminal_ids,
        }

    terminal_series: list[pd.Series] = []
    for gid in terminal_ids:
        df = _extract_flo_out_rows(table, int(gid))
        if df.empty:
            continue
        series = _normalize_discharge_units(df["sim"], source_path.name).rename(str(gid))
        if float(series.abs().sum()) > 0.0:
            terminal_series.append(series)

    if not terminal_series:
        return {
            "available": False,
            "observed_path": str(obs_path),
            "sim_source_path": str(source_path),
            "reason": "terminal_series_empty",
            "terminal_ids": terminal_ids,
        }

    selected_df = _extract_flo_out_rows(table, selected)
    selected_series = (
        _normalize_discharge_units(selected_df["sim"], source_path.name)
        if not selected_df.empty
        else pd.Series(dtype=float)
    )
    all_terminal = pd.concat(terminal_series, axis=1).sum(axis=1).rename("sim")
    selected_summary = _hydrograph_metric_summary(obs, selected_series)
    all_summary = _hydrograph_metric_summary(obs, all_terminal)
    nearest = _safe_int(routing_scope.get("nearest_terminal_gis_id"))
    nearest_summary: dict[str, Any] | None = None
    if nearest is not None and nearest != selected:
        nearest_df = _extract_flo_out_rows(table, nearest)
        nearest_series = (
            _normalize_discharge_units(nearest_df["sim"], source_path.name)
            if not nearest_df.empty
            else pd.Series(dtype=float)
        )
        nearest_summary = _hydrograph_metric_summary(obs, nearest_series)

    selected_pbias = _safe_float(selected_summary.get("pbias_pct"))
    all_pbias = _safe_float(all_summary.get("pbias_pct"))
    nearest_pbias = _safe_float(nearest_summary.get("pbias_pct")) if nearest_summary else None
    pbias_abs_improvement = None
    if selected_pbias is not None and all_pbias is not None:
        pbias_abs_improvement = abs(selected_pbias) - abs(all_pbias)
    nearest_pbias_abs_improvement = None
    if selected_pbias is not None and nearest_pbias is not None:
        nearest_pbias_abs_improvement = abs(selected_pbias) - abs(nearest_pbias)
    aggregation_valid = routing_scope.get("all_terminal_aggregation_valid")
    aggregation_reason = routing_scope.get("all_terminal_aggregation_reason")

    return {
        "available": bool(selected_summary.get("available") and all_summary.get("available")),
        "diagnostic_only": True,
        "claim_impact": "outlet_and_routing_claims_remain_blocked_until_selected_terminal_scope_is_explained",
        "observed_path": str(obs_path),
        "sim_source_path": str(source_path),
        "terminal_ids": terminal_ids,
        "selected_outlet_gis_id": selected,
        "selected_terminal": selected_summary,
        "all_terminal": all_summary,
        "nearest_terminal_gis_id": nearest,
        "nearest_terminal": nearest_summary,
        "pbias_abs_improvement_pct_points": pbias_abs_improvement,
        "nearest_vs_selected_pbias_abs_improvement_pct_points": nearest_pbias_abs_improvement,
        "selected_outlet_is_nearest_terminal": routing_scope.get("selected_outlet_is_nearest_terminal"),
        "selected_outlet_distance_to_gauge_m": routing_scope.get("selected_outlet_distance_to_gauge_m"),
        "nearest_terminal_distance_to_gauge_m": routing_scope.get("nearest_terminal_distance_to_gauge_m"),
        "gauge_coordinate_source": routing_scope.get("gauge_coordinate_source"),
        "all_terminal_aggregation_valid": aggregation_valid,
        "all_terminal_aggregation_reason": aggregation_reason,
        "terminal_failure_class": routing_scope.get("terminal_failure_class"),
        "shared_upstream_area_km2": routing_scope.get("shared_upstream_area_km2"),
        "all_terminal_upstream_area_km2": routing_scope.get("all_terminal_upstream_area_km2"),
    }


def _high_runoff_demand_context(
    weather_forcing: dict[str, Any],
    water_balance: dict[str, Any],
    aquifer_context: dict[str, Any],
    routing_scope: dict[str, Any],
    terminal_hydrograph: dict[str, Any],
) -> dict[str, Any]:
    observed = weather_forcing.get("observed_runoff") if isinstance(weather_forcing, dict) else {}
    if not isinstance(observed, dict):
        observed = {}
    ratio_class = observed.get("runoff_precip_ratio_class")
    if ratio_class != "high_observed_runoff_fraction":
        return {
            "available": False,
            "reason": "not_high_observed_runoff_fraction",
            "runoff_precip_ratio_class": ratio_class,
        }
    selected = (
        terminal_hydrograph.get("selected_terminal")
        if isinstance(terminal_hydrograph.get("selected_terminal"), dict)
        else {}
    )
    all_terminal = (
        terminal_hydrograph.get("all_terminal")
        if isinstance(terminal_hydrograph.get("all_terminal"), dict)
        else {}
    )
    context = {
        "available": True,
        "runoff_precip_ratio_class": ratio_class,
        "observed_runoff_to_overlap_precip_ratio": _safe_float(
            observed.get("observed_runoff_to_overlap_precip_ratio")
        ),
        "observed_runoff_depth_mm": _safe_float(observed.get("observed_runoff_depth_mm")),
        "precip_overlap_total_mm": _safe_float(observed.get("precip_overlap_total_mm")),
        "observed_area_km2": _safe_float(observed.get("area_km2")),
        "swat_precip_mm": _safe_float(water_balance.get("precip_mm")),
        "swat_net_wateryld_to_precip": _safe_float(water_balance.get("net_wateryld_to_precip")),
        "swat_surface_runoff_to_precip": _safe_float(water_balance.get("surface_runoff_to_precip")),
        "swat_lateral_flow_to_precip": _safe_float(water_balance.get("latq_to_precip")),
        "swat_percolation_to_precip": _safe_float(water_balance.get("perc_to_precip")),
        "swat_et_to_precip": _safe_float(water_balance.get("et_to_precip")),
        "swat_snowfall_to_precip": _safe_float(water_balance.get("snowfall_to_precip")),
        "swat_snowmelt_to_precip": _safe_float(water_balance.get("snowmelt_to_precip")),
        "swat_snowpack_to_precip": _safe_float(water_balance.get("snowpack_to_precip")),
        "swat_snowfall_mm": _safe_float(water_balance.get("snowfall_mm")),
        "swat_snowmelt_mm": _safe_float(water_balance.get("snowmelt_mm")),
        "swat_snowpack_mm": _safe_float(water_balance.get("snowpack_mm")),
        "swat_soil_water_change_mm": _safe_float(water_balance.get("soil_water_change_mm")),
        "swat_lagged_lateral_flow_mm": _safe_float(water_balance.get("lagged_lateral_flow_mm")),
        "swat_groundwater_soil_flow_mm": _safe_float(water_balance.get("groundwater_soil_flow_mm")),
        "swat_mass_residual_pct_of_precip": _safe_float(water_balance.get("mass_residual_pct_of_precip")),
        "aquifer_context_available": aquifer_context.get("available") is True,
        "aquifer_flow_mean_mm": _safe_float(aquifer_context.get("flow_mean_mm")),
        "aquifer_flow_max_mm": _safe_float(aquifer_context.get("flow_max_mm")),
        "aquifer_storage_mean_mm": _safe_float(aquifer_context.get("storage_mean_mm")),
        "aquifer_recharge_mean_mm": _safe_float(aquifer_context.get("recharge_mean_mm")),
        "aquifer_revap_mean_mm": _safe_float(aquifer_context.get("revap_mean_mm")),
        "selected_terminal_fraction_of_all_terminal_flow": _safe_float(
            routing_scope.get("selected_terminal_fraction_of_all_terminal_flow")
        ),
        "all_terminal_routed_to_channel_closure_ratio": _safe_float(
            routing_scope.get("all_terminal_routed_to_channel_closure_ratio")
        ),
        "all_terminal_mass_closure_ratio": _safe_float(routing_scope.get("all_terminal_mass_closure_ratio")),
        "all_terminal_upstream_area_km2": _safe_float(routing_scope.get("all_terminal_upstream_area_km2")),
        "selected_terminal_pbias_pct": _safe_float(selected.get("pbias_pct")),
        "all_terminal_pbias_pct": _safe_float(all_terminal.get("pbias_pct")),
        "claim_impact": "diagnostic_only_high_runoff_demand_requires_snow_storage_baseflow_or_forcing_area_context",
        "recommended_probe": "audit_high_observed_runoff_fraction_context",
        "rationale": (
            "Observed runoff uses a large fraction of precipitation while SWAT water-yield, snow/storage, "
            "aquifer, and terminal-scope evidence remain below observed volume; retain forcing, snow/storage, "
            "baseflow, and drainage-area context before another parameter-only calibration attempt."
        ),
    }
    area = context["observed_area_km2"]
    all_area = context["all_terminal_upstream_area_km2"]
    context["observed_area_to_all_terminal_area_ratio"] = _ratio(area, all_area)
    interpretation_flags = _high_runoff_interpretation_flags(context)
    context["interpretation_flags"] = interpretation_flags
    context["candidate_explanations"] = _high_runoff_candidate_explanations(
        context,
        interpretation_flags,
    )
    context["required_before_claim"] = [
        "retain_high_runoff_context_as_diagnostic_only",
        "audit_precipitation_area_snow_storage_aquifer_and_external_inflow_before_parameter_attribution",
        "select_a_source_backed_high_runoff_repair_target",
        "run_fresh_locked_rerun_after_high_runoff_repair",
        "pass_physical_routing_sensitivity_calibration_metric_and_contract_gates",
    ]
    return context


def _high_runoff_interpretation_flags(context: dict[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    qobs_p = _safe_float(context.get("observed_runoff_to_overlap_precip_ratio"))
    wateryld_p = _safe_float(context.get("swat_net_wateryld_to_precip"))
    if qobs_p is not None and wateryld_p is not None and (qobs_p - wateryld_p) >= 0.20:
        flags.append(
            {
                "code": "swat_water_yield_far_below_observed_runoff_fraction",
                "evidence": f"Qobs/P={qobs_p:.3f}; SWAT net wateryld/P={wateryld_p:.3f}",
            }
        )
    snowmelt_p = _safe_float(context.get("swat_snowmelt_to_precip"))
    snowpack_p = _safe_float(context.get("swat_snowpack_to_precip"))
    if (
        qobs_p is not None
        and qobs_p >= 0.70
        and snowmelt_p is not None
        and snowmelt_p < 0.05
        and (snowpack_p is None or snowpack_p < 0.01)
    ):
        flags.append(
            {
                "code": "snow_storage_not_explaining_high_runoff_demand",
                "evidence": f"snowmelt/P={snowmelt_p:.3f}; snowpack/P={_fmt(snowpack_p)}",
            }
        )
    aquifer_flow = _safe_float(context.get("aquifer_flow_mean_mm"))
    aquifer_recharge = _safe_float(context.get("aquifer_recharge_mean_mm"))
    if aquifer_flow is not None and aquifer_flow <= 0.01 and aquifer_recharge is not None and aquifer_recharge <= 0.01:
        flags.append(
            {
                "code": "aquifer_release_absent_for_high_runoff_demand",
                "evidence": f"aquifer_flow_mean_mm={aquifer_flow:.3f}; aquifer_recharge_mean_mm={aquifer_recharge:.3f}",
            }
        )
    selected_fraction = _safe_float(context.get("selected_terminal_fraction_of_all_terminal_flow"))
    if selected_fraction is not None and selected_fraction < 0.90:
        flags.append(
            {
                "code": "selected_terminal_partial_during_high_runoff_demand",
                "evidence": f"selected_terminal_fraction_of_all_terminal_flow={selected_fraction:.3f}",
            }
        )
    area_ratio = _safe_float(context.get("observed_area_to_all_terminal_area_ratio"))
    if area_ratio is not None and (area_ratio < 0.80 or area_ratio > 1.20):
        flags.append(
            {
                "code": "observed_area_mismatch_during_high_runoff_demand",
                "evidence": f"observed_area/all_terminal_area={area_ratio:.3f}",
            }
        )
    return flags


def _high_runoff_candidate_explanations(
    context: dict[str, Any],
    flags: list[dict[str, str]],
) -> list[dict[str, Any]]:
    flag_codes = {str(flag.get("code")) for flag in flags if isinstance(flag, dict)}
    qobs_p = _safe_float(context.get("observed_runoff_to_overlap_precip_ratio"))
    wateryld_p = _safe_float(context.get("swat_net_wateryld_to_precip"))
    area_ratio = _safe_float(context.get("observed_area_to_all_terminal_area_ratio"))
    snowmelt_p = _safe_float(context.get("swat_snowmelt_to_precip"))
    snowpack_p = _safe_float(context.get("swat_snowpack_to_precip"))
    aquifer_flow = _safe_float(context.get("aquifer_flow_mean_mm"))
    aquifer_recharge = _safe_float(context.get("aquifer_recharge_mean_mm"))
    selected_fraction = _safe_float(context.get("selected_terminal_fraction_of_all_terminal_flow"))
    return [
        {
            "hypothesis": "precipitation_area_or_external_inflow_basis",
            "status": (
                "area_mismatch_requires_review"
                if "observed_area_mismatch_during_high_runoff_demand" in flag_codes
                else "area_matches_all_terminal_but_runoff_fraction_remains_high"
            ),
            "evidence": (
                f"Qobs/P={_fmt(qobs_p)}; observed_area/all_terminal_area={_fmt(area_ratio)}"
            ),
            "next_action": "audit_precipitation_overlap_gauge_area_and_possible_external_inflow",
            "fresh_locked_rerun_required": False,
            "claim_impact": "diagnostic_only_until_forcing_area_or_external_inflow_basis_is_explained",
        },
        {
            "hypothesis": "snow_storage_or_snowmelt_release",
            "status": (
                "not_supported_by_current_swat_snow_terms"
                if "snow_storage_not_explaining_high_runoff_demand" in flag_codes
                else "needs_snow_storage_timing_audit"
            ),
            "evidence": f"snowmelt/P={_fmt(snowmelt_p)}; snowpack/P={_fmt(snowpack_p)}",
            "next_action": "audit_snow_threshold_controls_only_if_snow_storage_evidence_supports_it",
            "fresh_locked_rerun_required": True,
            "claim_impact": "snow controls remain diagnostic unless fresh locked gates pass",
        },
        {
            "hypothesis": "groundwater_or_aquifer_release",
            "status": (
                "not_supported_by_current_aquifer_release"
                if "aquifer_release_absent_for_high_runoff_demand" in flag_codes
                else "aquifer_release_present_requires_baseflow_timing_audit"
            ),
            "evidence": f"aquifer_flow_mean_mm={_fmt(aquifer_flow)}; aquifer_recharge_mean_mm={_fmt(aquifer_recharge)}",
            "next_action": "audit_recharge_baseflow_and_lateral_flow_before_groundwater_parameter_attribution",
            "fresh_locked_rerun_required": True,
            "claim_impact": "groundwater controls remain diagnostic until source-backed process gates pass",
        },
        {
            "hypothesis": "selected_terminal_scope",
            "status": (
                "selected_terminal_partial"
                if "selected_terminal_partial_during_high_runoff_demand" in flag_codes
                else "selected_terminal_scope_not_primary_high_runoff_explanation"
            ),
            "evidence": f"selected_terminal_fraction_of_all_terminal_flow={_fmt(selected_fraction)}",
            "next_action": "reconcile_selected_vs_all_terminal_scope_before_claim_authority",
            "fresh_locked_rerun_required": True,
            "claim_impact": "terminal_scope_claim_blocks_research_grade_until_same_scope_locked_evidence_passes",
        },
        {
            "hypothesis": "model_water_yield_deficit",
            "status": (
                "swat_water_yield_far_below_observed_runoff_fraction"
                if "swat_water_yield_far_below_observed_runoff_fraction" in flag_codes
                else "water_yield_gap_not_classified"
            ),
            "evidence": f"Qobs/P={_fmt(qobs_p)}; SWAT net wateryld/P={_fmt(wateryld_p)}",
            "next_action": "increase_water_yield_only_after_forcing_area_and_process_basis_are_explained",
            "fresh_locked_rerun_required": True,
            "claim_impact": "parameter search remains diagnostic until high-runoff basis is source-backed",
        },
    ]


def _hru_runoff_summary(run: Path) -> dict[str, Any]:
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    wb_path = txt / "hru_wb_aa.txt"
    data_path = txt / "hru-data.hru"
    if not wb_path.is_file():
        return {"available": False, "reason": "hru_wb_aa_missing"}
    try:
        wb = pd.read_csv(wb_path, sep=r"\s+", skiprows=[0, 2], engine="python")
    except Exception as exc:
        return {"available": False, "path": str(wb_path), "reason": str(exc)}
    if wb.empty or "cn" not in wb.columns:
        return {"available": False, "path": str(wb_path), "reason": "hru_wb_aa_missing_cn"}

    hru = pd.DataFrame()
    if data_path.is_file():
        try:
            hru = pd.read_csv(data_path, sep=r"\s+", skiprows=[0], engine="python")
        except Exception:
            hru = pd.DataFrame()
    if not hru.empty and {"id", "lu_mgt"}.issubset(hru.columns):
        merged = wb.merge(hru[["id", "lu_mgt", "soil", "hydro"]], left_on="unit", right_on="id", how="left")
    else:
        merged = wb.copy()
        merged["lu_mgt"] = None
        merged["soil"] = None
        merged["hydro"] = None

    cn = pd.to_numeric(merged["cn"], errors="coerce").dropna()
    if cn.empty:
        return {"available": False, "path": str(wb_path), "reason": "hru_cn_non_numeric"}
    surq_p = _series_ratio(merged, "surq_gen", "precip")
    wateryld_p = _series_ratio(merged, "wateryld", "precip")
    landuse_summary = []
    if "lu_mgt" in merged.columns:
        temp = merged.copy()
        temp["cn_numeric"] = pd.to_numeric(temp["cn"], errors="coerce")
        temp["surq_to_precip"] = surq_p
        temp["wateryld_to_precip"] = wateryld_p
        for lu, grp in temp.groupby("lu_mgt", dropna=False):
            landuse_summary.append(
                {
                    "lu_mgt": None if pd.isna(lu) else str(lu),
                    "hru_count": int(len(grp)),
                    "mean_cn": _safe_float(grp["cn_numeric"].mean()),
                    "mean_surq_to_precip": _safe_float(grp["surq_to_precip"].mean()),
                    "mean_wateryld_to_precip": _safe_float(grp["wateryld_to_precip"].mean()),
                }
            )
    landuse_summary.sort(key=lambda row: (row.get("hru_count") or 0), reverse=True)
    return {
        "available": True,
        "path": str(wb_path),
        "weighting": "unweighted_hru_count",
        "hru_count": int(len(merged)),
        "cn_min": _safe_float(cn.min()),
        "cn_mean": _safe_float(cn.mean()),
        "cn_median": _safe_float(cn.median()),
        "cn_p90": _safe_float(cn.quantile(0.90)),
        "cn_max": _safe_float(cn.max()),
        "hru_count_cn_ge_95": int((cn >= 95.0).sum()),
        "hru_fraction_cn_ge_95": float((cn >= 95.0).sum() / len(cn)),
        "mean_surq_to_precip": _safe_float(surq_p.mean()),
        "mean_wateryld_to_precip": _safe_float(wateryld_p.mean()),
        "landuse_summary": landuse_summary[:10],
    }


def _landuse_raster_summary(run: Path) -> dict[str, Any]:
    raster_path = run / "raw" / "nlcd_2021.tif"
    boundary_path = run / "raw" / "basin_boundary.gpkg"
    if not raster_path.is_file():
        return {"available": False, "reason": "nlcd_raster_missing"}
    try:
        import geopandas as gpd
        import numpy as np
        import rasterio
        from rasterio.mask import mask
    except Exception as exc:
        return {"available": False, "path": str(raster_path), "reason": f"dependency_unavailable: {exc}"}

    try:
        with rasterio.open(raster_path) as src:
            pixel_area = abs(float(src.transform.a) * float(src.transform.e))
            pixel_area_m2 = pixel_area if src.crs and src.crs.is_projected else None
            raster_crs = str(src.crs) if src.crs else None
            if boundary_path.is_file():
                boundary = gpd.read_file(boundary_path).to_crs(src.crs)
                arr, _transform = mask(src, list(boundary.geometry), crop=True, filled=True)
                source_scope = "basin_boundary_mask"
            else:
                arr = src.read(1, masked=False)[None, :, :]
                source_scope = "whole_raster"
            nodata = src.nodata
    except Exception as exc:
        return {"available": False, "path": str(raster_path), "reason": str(exc)}

    data = arr[0]
    valid = data[np.isfinite(data)].astype("int64")
    if nodata is not None:
        valid = valid[valid != int(nodata)]
    valid = valid[~np.isin(valid, [0, 255, 2_147_483_647])]
    if len(valid) == 0:
        return {"available": False, "path": str(raster_path), "reason": "no_valid_landuse_pixels"}
    codes, counts = np.unique(valid, return_counts=True)
    total = int(counts.sum())
    class_summary = []
    for code, count in sorted(zip(codes.tolist(), counts.tolist()), key=lambda row: row[1], reverse=True):
        class_summary.append(
            {
                "nlcd_code": int(code),
                "description": NLCD_CLASS_DESCRIPTIONS.get(int(code), "unknown"),
                "pixel_count": int(count),
                "fraction": float(count / total),
                "urban": int(code) in NLCD_URBAN_CODES,
                "water": is_water(int(code)),
            }
        )
    urban_count = sum(row["pixel_count"] for row in class_summary if row["urban"])
    water_count = sum(row["pixel_count"] for row in class_summary if row["water"])
    return {
        "available": True,
        "path": str(raster_path),
        "boundary_path": str(boundary_path) if boundary_path.is_file() else None,
        "source_scope": source_scope,
        "crs": raster_crs,
        "pixel_count": total,
        "pixel_area_m2": pixel_area_m2,
        "pixel_area_crs_units2": pixel_area,
        "urban_fraction": float(urban_count / total),
        "water_fraction": float(water_count / total),
        "class_summary": class_summary,
    }


def _urban_assumptions_summary(run: Path, hru_runoff: dict[str, Any]) -> dict[str, Any]:
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    lum_path = txt / "landuse.lum"
    urban_path = txt / "urban.urb"
    if not lum_path.is_file() or not urban_path.is_file():
        return {"available": False, "reason": "landuse_lum_or_urban_urb_missing"}
    try:
        lum = pd.read_csv(lum_path, sep=r"\s+", skiprows=[0], engine="python")
        urban = pd.read_csv(urban_path, sep=r"\s+", skiprows=[0], engine="python")
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    if not {"name", "urban"}.issubset(lum.columns) or not {"name", "frac_imp", "urb_cn"}.issubset(urban.columns):
        return {"available": False, "reason": "required_urban_columns_missing"}

    hru_landuses = {
        row.get("lu_mgt"): row
        for row in hru_runoff.get("landuse_summary", [])
        if isinstance(row, dict) and row.get("lu_mgt")
    }
    rows: list[dict[str, Any]] = []
    total_hru_count = 0
    weighted_frac_imp = 0.0
    weighted_urb_cn = 0.0
    urban_hru_count = 0
    for _, lum_row in lum.iterrows():
        lu_name = str(lum_row.get("name"))
        urban_raw = lum_row.get("urban")
        if pd.isna(urban_raw):
            continue
        urban_name = str(urban_raw)
        if not urban_name or urban_name in {"null", "nan", "None"}:
            continue
        hru_row = hru_landuses.get(lu_name)
        hru_count = int(hru_row.get("hru_count", 0)) if hru_row else 0
        u = urban.loc[urban["name"].astype(str) == urban_name]
        if u.empty:
            rows.append({"lu_mgt": lu_name, "urban": urban_name, "hru_count": hru_count, "missing_urban_row": True})
            continue
        rec = u.iloc[0]
        frac_imp = _safe_float(rec.get("frac_imp"))
        frac_dc_imp = _safe_float(rec.get("frac_dc_imp"))
        urb_cn = _safe_float(rec.get("urb_cn"))
        rows.append(
            {
                "lu_mgt": lu_name,
                "urban": urban_name,
                "hru_count": hru_count,
                "frac_imp": frac_imp,
                "frac_dc_imp": frac_dc_imp,
                "urb_cn": urb_cn,
            }
        )
        total_hru_count += hru_count
        if hru_count > 0:
            urban_hru_count += hru_count
            if frac_imp is not None:
                weighted_frac_imp += hru_count * frac_imp
            if urb_cn is not None:
                weighted_urb_cn += hru_count * urb_cn
    total_hrus = int(hru_runoff.get("hru_count") or total_hru_count or 0)
    return {
        "available": True,
        "landuse_lum_path": str(lum_path),
        "urban_urb_path": str(urban_path),
        "urban_lum_count": len(rows),
        "urban_hru_count": urban_hru_count,
        "urban_hru_fraction": (urban_hru_count / total_hrus) if total_hrus else None,
        "hru_weighted_frac_imp": (weighted_frac_imp / urban_hru_count) if urban_hru_count else None,
        "hru_weighted_urb_cn": (weighted_urb_cn / urban_hru_count) if urban_hru_count else None,
        "urban_rows": rows,
    }


def _classify(
    gates: dict[str, Any],
    alignment: dict[str, Any],
    water_balance: dict[str, Any],
    outlet: dict[str, Any],
    hru_runoff: dict[str, Any],
    landuse_raster: dict[str, Any],
    urban_assumptions: dict[str, Any],
    routing_scope: dict[str, Any],
    terminal_hydrograph: dict[str, Any],
    weather_forcing: dict[str, Any],
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    codes = set(gates.get("condition_codes") or [])
    pbias = _safe_float(alignment.get("pbias_pct"))
    if "VOLUME_BIAS" in codes or (pbias is not None and abs(pbias) > 30.0):
        if pbias is not None and pbias > 30.0:
            ratio = _safe_float(alignment.get("sim_to_obs_volume_ratio"))
            flags.append(
                {
                    "code": "simulated_volume_excess",
                    "evidence": f"PBIAS={pbias:.1f}% and sim/obs volume ratio={_fmt(ratio)}",
                }
            )
        elif pbias is not None and pbias < -30.0:
            flags.append({"code": "simulated_volume_deficit", "evidence": f"PBIAS={pbias:.1f}%"})
        else:
            flags.append({"code": "volume_bias_gate_without_alignment", "evidence": "Physical gate reported VOLUME_BIAS"})

    surq_p = _safe_float(water_balance.get("surface_runoff_to_precip"))
    wateryld_p = _safe_float(
        water_balance.get("net_wateryld_to_precip", water_balance.get("wateryld_to_precip"))
    )
    et_p = _safe_float(water_balance.get("et_to_precip"))
    esoil_et = _safe_float(water_balance.get("esoil_to_et"))
    latq_p = _safe_float(water_balance.get("latq_to_precip"))
    perc_p = _safe_float(water_balance.get("perc_to_precip"))
    cn = _safe_float(water_balance.get("cn"))
    mass_residual_pct = _safe_float(water_balance.get("mass_residual_pct_of_precip"))
    if "MASS_IMBALANCE" in codes:
        evidence = "physical gate reported MASS_IMBALANCE"
        if mass_residual_pct is not None:
            evidence = f"|P-(net_wateryld+ET+perc)|/P={abs(mass_residual_pct) / 100.0:.3f}"
        flags.append({"code": "mass_closure_residual_high", "evidence": evidence})
    deficit = any(flag.get("code") == "simulated_volume_deficit" for flag in flags)
    if ("ET_DOMINATED" in codes or (et_p is not None and et_p > 0.70)) and et_p is not None:
        flags.append(
            {
                "code": "et_partition_high",
                "evidence": f"ET/P={et_p:.3f}; documented PET_CO range is 0.8-1.2",
            }
        )
    if deficit and wateryld_p is not None and wateryld_p < 0.25:
        flags.append({"code": "basin_water_yield_fraction_low", "evidence": f"wateryld/P={wateryld_p:.3f}"})
    if deficit and esoil_et is not None and esoil_et > 0.70:
        flags.append(
            {
                "code": "soil_evaporation_dominates_et",
                "evidence": f"esoil/ET={esoil_et:.3f}; plant transpiration and soil evaporation partitioning need review",
            }
        )
    if deficit and latq_p is not None and perc_p is not None and latq_p < 0.02 and perc_p < 0.05:
        flags.append(
            {
                "code": "subsurface_partition_low",
                "evidence": f"latq/P={latq_p:.3f}; perc/P={perc_p:.3f}",
            }
        )
    if surq_p is not None and surq_p > 0.55:
        flags.append(
            {
                "code": "surface_runoff_partition_high",
                "evidence": f"surq_gen/P={surq_p:.3f}; CN={cn:.3g}" if cn is not None else f"surq_gen/P={surq_p:.3f}",
            }
        )
    if wateryld_p is not None and wateryld_p > 0.65:
        flags.append({"code": "basin_water_yield_fraction_high", "evidence": f"wateryld/P={wateryld_p:.3f}"})
    observed_weather = (
        weather_forcing.get("observed_runoff")
        if isinstance(weather_forcing.get("observed_runoff"), dict)
        else {}
    )
    observed_ratio = _safe_float(observed_weather.get("observed_runoff_to_overlap_precip_ratio"))
    if observed_weather.get("runoff_precip_ratio_class") == "high_observed_runoff_fraction":
        flags.append(
            {
                "code": "high_observed_runoff_fraction",
                "evidence": f"Qobs/P={observed_ratio:.3f}" if observed_ratio is not None else "Qobs/P is high",
            }
        )
    hru_cn_p90 = _safe_float(hru_runoff.get("cn_p90"))
    hru_cn_frac = _safe_float(hru_runoff.get("hru_fraction_cn_ge_95"))
    if hru_cn_p90 is not None and hru_cn_frac is not None and hru_cn_p90 >= 95.0:
        flags.append(
            {
                "code": "hru_cn_distribution_extreme",
                "evidence": f"HRU CN p90={hru_cn_p90:.1f}; fraction CN>=95={hru_cn_frac:.3f}",
            }
        )
    urban_fraction = _safe_float(landuse_raster.get("urban_fraction"))
    if urban_fraction is not None and urban_fraction > 0.60 and surq_p is not None and surq_p > 0.55:
        flags.append(
            {
                "code": "urban_landuse_dominates_runoff_response",
                "evidence": f"NLCD urban fraction={urban_fraction:.3f}; basin surq_gen/P={surq_p:.3f}",
            }
        )
    urban_hru_fraction = _safe_float(urban_assumptions.get("urban_hru_fraction"))
    weighted_urb_cn = _safe_float(urban_assumptions.get("hru_weighted_urb_cn"))
    if urban_hru_fraction is not None and weighted_urb_cn is not None:
        if urban_hru_fraction > 0.60 and weighted_urb_cn >= 98.0:
            flags.append(
                {
                    "code": "urban_curve_number_fixed_high",
                    "evidence": f"urban HRU fraction={urban_hru_fraction:.3f}; hru-weighted urb_cn={weighted_urb_cn:.1f}",
                }
            )

    terminal_count = _safe_int(outlet.get("terminal_outlet_count"))
    if outlet.get("outlet_autodetected") and terminal_count and terminal_count > 1:
        flags.append(
            {
                "code": "outlet_provenance_needs_review",
                "evidence": f"requested outlet was auto-remapped with {terminal_count} terminal outlets present",
            }
        )
    reason = str(outlet.get("outlet_selection_reason") or "")
    if "single_terminal" in reason and terminal_count and terminal_count > 1:
        flags.append(
            {
                "code": "outlet_reason_terminal_count_mismatch",
                "evidence": f"selection reason={reason!r} but terminal_outlet_count={terminal_count}",
            }
        )
    selected_share = _safe_float(routing_scope.get("selected_terminal_fraction_of_all_terminal_flow"))
    all_terminal_routed_ratio = _safe_float(routing_scope.get("all_terminal_routed_to_channel_closure_ratio"))
    routing_terminal_count = _safe_int(
        _first_not_none(routing_scope.get("terminal_outlet_count"), terminal_count)
    )
    terminal_scope_possible = bool(
        routing_terminal_count
        and routing_terminal_count > 1
        and (
            deficit
            or (selected_share is not None and selected_share < 0.9)
            or terminal_hydrograph.get("available") is True
        )
    )
    if terminal_scope_possible:
        if selected_share is not None and selected_share < 0.9:
            flags.append(
                {
                    "code": "selected_terminal_partial_of_all_terminal_flow",
                    "evidence": (
                        f"selected terminal carries {selected_share:.3f} of all terminal flow; "
                        "gauge-volume comparison may reflect terminal scope"
                    ),
                }
            )
        if (
            selected_share is not None
            and selected_share < 0.9
            and all_terminal_routed_ratio is not None
            and 0.7 <= all_terminal_routed_ratio <= 1.3
        ):
            flags.append(
                {
                    "code": "all_terminal_routed_to_channel_reference_matches",
                    "evidence": (
                        "all-terminal/routed-to-channel closure ratio="
                        f"{all_terminal_routed_ratio:.3f}; selected terminal remains partial"
                    ),
                }
            )
        if terminal_hydrograph.get("available"):
            aggregation_valid = terminal_hydrograph.get("all_terminal_aggregation_valid")
            if terminal_hydrograph.get("selected_outlet_is_nearest_terminal") is False:
                flags.append(
                    {
                        "code": "selected_terminal_not_nearest_gauge_terminal",
                        "evidence": (
                            "selected outlet terminal is "
                            f"{_fmt(terminal_hydrograph.get('selected_outlet_distance_to_gauge_m'))} m "
                            "from the recovered gauge point; nearest terminal is "
                            f"{terminal_hydrograph.get('nearest_terminal_gis_id')}"
                        ),
                    }
                )
            if aggregation_valid is False:
                flags.append(
                    {
                        "code": "all_terminal_hydrograph_aggregation_not_claim_valid",
                        "evidence": str(
                            terminal_hydrograph.get("all_terminal_aggregation_reason")
                            or "terminal upstream areas overlap"
                        ),
                    }
                )
            selected_metrics = terminal_hydrograph.get("selected_terminal")
            all_metrics = terminal_hydrograph.get("all_terminal")
            nearest_metrics = terminal_hydrograph.get("nearest_terminal")
            if isinstance(selected_metrics, dict) and isinstance(nearest_metrics, dict):
                selected_pbias = _safe_float(selected_metrics.get("pbias_pct"))
                nearest_pbias = _safe_float(nearest_metrics.get("pbias_pct"))
                if (
                    selected_pbias is not None
                    and nearest_pbias is not None
                    and abs(selected_pbias) - abs(nearest_pbias) >= 10.0
                ):
                    flags.append(
                        {
                            "code": "nearest_terminal_hydrograph_volume_closer",
                            "evidence": (
                                f"selected-terminal PBIAS={selected_pbias:.1f}%; "
                                f"nearest-terminal PBIAS={nearest_pbias:.1f}%"
                            ),
                        }
                    )
                if nearest_pbias is not None and abs(nearest_pbias) <= 30.0:
                    flags.append(
                        {
                            "code": "nearest_terminal_hydrograph_volume_gate_passes_diagnostic",
                            "evidence": (
                                f"nearest-terminal diagnostic PBIAS={nearest_pbias:.1f}%; "
                                "nearest terminal is not claim-authoritative until outlet provenance is updated"
                            ),
                        }
                    )
            if isinstance(selected_metrics, dict) and isinstance(all_metrics, dict):
                selected_pbias = _safe_float(selected_metrics.get("pbias_pct"))
                all_pbias = _safe_float(all_metrics.get("pbias_pct"))
                selected_nse = _safe_float(selected_metrics.get("nse"))
                all_nse = _safe_float(all_metrics.get("nse"))
                all_kge = _safe_float(all_metrics.get("kge"))
                if (
                    selected_pbias is not None
                    and all_pbias is not None
                    and abs(selected_pbias) - abs(all_pbias) >= 10.0
                ):
                    flags.append(
                        {
                            "code": "all_terminal_hydrograph_volume_closer",
                            "evidence": (
                                f"selected-terminal PBIAS={selected_pbias:.1f}%; "
                                f"all-terminal PBIAS={all_pbias:.1f}%"
                            ),
                        }
                    )
                if (
                    selected_pbias is not None
                    and all_pbias is not None
                    and abs(all_pbias) > 30.0
                    and abs(all_pbias) < abs(selected_pbias)
                    and aggregation_valid is not False
                ):
                    flags.append(
                        {
                            "code": "all_terminal_hydrograph_volume_deficit_persists",
                            "evidence": (
                                f"all-terminal diagnostic PBIAS={all_pbias:.1f}% after valid aggregation; "
                                "terminal aggregation improves volume but still misses the hard volume gate"
                            ),
                        }
                    )
                if (
                    all_pbias is not None
                    and abs(all_pbias) <= 30.0
                    and aggregation_valid is not False
                ):
                    flags.append(
                        {
                            "code": "all_terminal_hydrograph_volume_gate_passes_diagnostic",
                            "evidence": (
                                f"all-terminal diagnostic PBIAS={all_pbias:.1f}%; "
                                "selected outlet remains the only claim-authoritative hydrograph"
                            ),
                        }
                    )
                if (
                    selected_pbias is not None
                    and all_pbias is not None
                    and abs(all_pbias) < abs(selected_pbias)
                    and (
                        (all_kge is not None and all_kge < 0.40)
                        or (all_nse is not None and all_nse < 0.0)
                    )
                ):
                    flags.append(
                        {
                            "code": "all_terminal_hydrograph_skill_limited_after_volume_correction",
                            "evidence": (
                                f"all-terminal diagnostic KGE={_fmt(all_kge)}; NSE={_fmt(all_nse)}; "
                                "terminal aggregation alone does not satisfy research skill gates"
                            ),
                        }
                    )
                if (
                    selected_nse is not None
                    and all_nse is not None
                    and all_nse < selected_nse - 0.05
                    and all_pbias is not None
                    and selected_pbias is not None
                    and abs(all_pbias) < abs(selected_pbias)
                ):
                    flags.append(
                        {
                            "code": "all_terminal_hydrograph_volume_better_skill_worse",
                            "evidence": (
                                f"all-terminal PBIAS improves from {selected_pbias:.1f}% to {all_pbias:.1f}% "
                                f"but NSE changes from {selected_nse:.3f} to {all_nse:.3f}"
                            ),
                        }
                    )
    return flags


def _terminal_scope_blocker(
    flags: list[dict[str, str]],
    terminal_hydrograph: dict[str, Any],
) -> str | None:
    """Classify terminal-scope volume blockers without promoting all-terminal metrics."""

    if not terminal_hydrograph.get("available"):
        return None
    codes = {flag.get("code") for flag in flags}
    if "all_terminal_hydrograph_aggregation_not_claim_valid" in codes:
        return "terminal_topology_overlap"
    if "all_terminal_hydrograph_volume_gate_passes_diagnostic" in codes:
        return "outlet_scope_volume_mismatch"
    if "all_terminal_hydrograph_volume_closer" in codes:
        return "multi_terminal_volume_deficit"
    return None


def classify_terminal_hydrograph_scope(
    terminal_hydrograph: dict[str, Any],
    flags: list[dict[str, str]] | list[str],
) -> dict[str, Any]:
    """Classify selected-vs-all terminal diagnostics without promoting claims."""

    if not isinstance(terminal_hydrograph, dict) or terminal_hydrograph.get("available") is not True:
        return {
            "class": None,
            "flags": [],
            "recommended_focus": [],
            "claim_impact": None,
        }

    codes: set[str] = set()
    for flag in flags:
        if isinstance(flag, dict) and flag.get("code"):
            codes.add(str(flag["code"]))
        elif isinstance(flag, str) and flag:
            codes.add(flag)

    selected = terminal_hydrograph.get("selected_terminal")
    all_terminal = terminal_hydrograph.get("all_terminal")
    nearest = terminal_hydrograph.get("nearest_terminal")
    selected = selected if isinstance(selected, dict) else {}
    all_terminal = all_terminal if isinstance(all_terminal, dict) else {}
    nearest = nearest if isinstance(nearest, dict) else {}
    selected_pbias = _safe_float(selected.get("pbias_pct"))
    selected_kge = _safe_float(selected.get("kge"))
    selected_nse = _safe_float(selected.get("nse"))
    all_pbias = _safe_float(all_terminal.get("pbias_pct"))
    all_kge = _safe_float(all_terminal.get("kge"))
    all_nse = _safe_float(all_terminal.get("nse"))
    nearest_pbias = _safe_float(nearest.get("pbias_pct"))
    selected_metric_minimum = (
        selected_pbias is not None
        and abs(selected_pbias) <= 30.0
        and selected_kge is not None
        and selected_kge >= 0.40
        and (selected_nse is None or selected_nse >= 0.0)
    )
    all_terminal_volume_gate = all_pbias is not None and abs(all_pbias) <= 30.0
    all_terminal_skill_gate = (
        all_kge is not None
        and all_kge >= 0.40
        and (all_nse is None or all_nse >= 0.0)
    )
    nearest_volume_gate = nearest_pbias is not None and abs(nearest_pbias) <= 30.0

    result_flags: list[str] = []
    focus: list[str] = []
    cls = "terminal_hydrograph_scope_unresolved"

    if "all_terminal_hydrograph_aggregation_not_claim_valid" in codes:
        cls = "terminal_topology_overlap_invalidates_aggregation"
        result_flags.append("all_terminal_aggregation_not_claim_valid")
        focus.extend(
            [
                "audit_terminal_topology_overlap_before_aggregation",
                "repair_or_explain_terminal_routing_topology",
            ]
        )
    elif selected_metric_minimum and "selected_terminal_partial_of_all_terminal_flow" in codes:
        cls = "selected_metric_passes_but_area_scope_partial"
        result_flags.extend(["selected_terminal_metric_gate_passes", "selected_terminal_scope_partial"])
        focus.extend(
            [
                "confirm_gauge_drainage_area_against_selected_terminal",
                "audit_outlet_selection_against_terminal_inventory",
            ]
        )
    elif all_terminal_volume_gate and not all_terminal_skill_gate:
        cls = "all_terminal_volume_corrected_but_skill_limited"
        result_flags.extend(["all_terminal_volume_gate_passes_diagnostic", "all_terminal_skill_gate_fails"])
        focus.extend(
            [
                "keep_all_terminal_metrics_diagnostic_only",
                "resolve_claim_authoritative_outlet_scope",
                "diagnose_timing_variability_or_peak_response",
            ]
        )
    elif all_terminal_volume_gate:
        cls = "all_terminal_volume_corrected_but_outlet_scope_unresolved"
        result_flags.append("all_terminal_volume_gate_passes_diagnostic")
        focus.extend(
            [
                "keep_all_terminal_metrics_diagnostic_only",
                "confirm_gauge_drainage_area_and_terminal_topology",
                "rerun_with_claim_authoritative_outlet_before_promotion",
            ]
        )
    elif "all_terminal_hydrograph_volume_deficit_persists" in codes:
        cls = "all_terminal_volume_deficit_persists_after_valid_aggregation"
        result_flags.append("all_terminal_volume_deficit_persists")
        focus.extend(
            [
                "diagnose_post_aggregation_water_balance_deficit",
                "audit_weather_forcing_et_runoff_and_subsurface_processes",
            ]
        )
    elif "all_terminal_hydrograph_volume_closer" in codes:
        cls = "all_terminal_volume_improves_but_gate_unresolved"
        result_flags.append("all_terminal_volume_closer")
        focus.extend(
            [
                "audit_selected_vs_all_terminal_hydrographs",
                "retain_terminal_aggregation_as_diagnostic_only",
            ]
        )
    elif nearest_volume_gate:
        cls = "nearest_terminal_volume_corrected_but_outlet_scope_unresolved"
        result_flags.append("nearest_terminal_volume_gate_passes_diagnostic")
        focus.extend(
            [
                "audit_selected_vs_nearest_terminal_hydrographs",
                "resolve_claim_authoritative_outlet_scope",
            ]
        )

    if terminal_hydrograph.get("selected_outlet_is_nearest_terminal") is False:
        result_flags.append("selected_outlet_not_nearest_terminal")
        if "audit_selected_vs_nearest_terminal_hydrographs" not in focus:
            focus.append("audit_selected_vs_nearest_terminal_hydrographs")
    dominant = all_terminal.get("kge_dominant_deficit") or selected.get("kge_dominant_deficit")
    if isinstance(dominant, str) and dominant:
        result_flags.append(f"dominant_kge_deficit_{dominant}")

    return {
        "class": cls,
        "flags": result_flags,
        "recommended_focus": focus,
        "claim_impact": "diagnostic_only_until_selected_outlet_scope_and_locked_gates_pass",
    }


def build_terminal_scope_resolution_plan(
    terminal_hydrograph: dict[str, Any],
    classification: dict[str, Any],
    *,
    terminal_scope_blocker: str | None = None,
) -> dict[str, Any]:
    """Describe what must be resolved before terminal-scope claims can advance."""

    if not isinstance(terminal_hydrograph, dict) or terminal_hydrograph.get("available") is not True:
        return {
            "available": False,
            "status": "not_applicable",
            "diagnostic_only": True,
            "terminal_scope_blocker": terminal_scope_blocker,
            "required_before_promotion": [],
            "fresh_locked_rerun_required": True,
            "temporary_terminal_metrics_allowed_as_final": False,
        }

    scope_class = classification.get("class") if isinstance(classification, dict) else None
    flags = classification.get("flags") if isinstance(classification, dict) else []
    focus = classification.get("recommended_focus") if isinstance(classification, dict) else []
    flags = [str(flag) for flag in flags if isinstance(flag, str) and flag]
    focus = [str(item) for item in focus if isinstance(item, str) and item]
    selected = terminal_hydrograph.get("selected_terminal")
    all_terminal = terminal_hydrograph.get("all_terminal")
    nearest = terminal_hydrograph.get("nearest_terminal")
    selected = selected if isinstance(selected, dict) else {}
    all_terminal = all_terminal if isinstance(all_terminal, dict) else {}
    nearest = nearest if isinstance(nearest, dict) else {}

    decision_type = "terminal_scope_unresolved"
    next_experiment = "audit_outlet_selection_against_terminal_inventory"
    required = [
        "retain_selected_terminal_as_only_current_claim_authority",
        "keep_all_terminal_and_nearest_metrics_diagnostic_only",
        "document_gauge_drainage_area_vs_terminal_area",
        "rerun_clean_locked_txtinout_after_claim_authoritative_outlet_is_resolved",
    ]

    if scope_class == "terminal_topology_overlap_invalidates_aggregation":
        decision_type = "terminal_topology_repair_required"
        next_experiment = "repair_terminal_topology_before_all_terminal_aggregation"
        required = [
            "repair_or_explain_terminal_upstream_overlap",
            "regenerate_terminal_inventory_from_emitted_routing",
            "rerun_clean_locked_txtinout_after_topology_repair",
        ]
    elif scope_class == "selected_metric_passes_but_area_scope_partial":
        decision_type = "selected_outlet_scope_authority_required"
        next_experiment = "confirm_selected_terminal_drainage_area_or_rebuild_claim_outlet"
        required.extend(
            [
                "prove_selected_terminal_represents_usgs_gauge_basin",
                "reject_metric_promotion_if_selected_terminal_area_remains_partial",
            ]
        )
    elif scope_class in {
        "all_terminal_volume_corrected_but_skill_limited",
        "all_terminal_volume_corrected_but_outlet_scope_unresolved",
    }:
        decision_type = "all_terminal_volume_diagnostic_not_claim_authority"
        next_experiment = "resolve_claim_authoritative_outlet_then_diagnose_skill"
        required.extend(
            [
                "confirm_whether_gauge_basin_matches_all_terminal_aggregation",
                "relock_and_rerun_using_claim_authoritative_outlet_before_reporting_metrics",
            ]
        )
    elif scope_class == "all_terminal_volume_deficit_persists_after_valid_aggregation":
        decision_type = "post_aggregation_process_deficit"
        next_experiment = "diagnose_weather_et_runoff_subsurface_deficit_after_terminal_scope"
        required.extend(
            [
                "treat_remaining_volume_deficit_as_process_or_forcing_blocker",
                "screen_governed_volume_controls_only_after_terminal_scope_evidence_is_retained",
            ]
        )
    elif scope_class == "all_terminal_volume_improves_but_gate_unresolved":
        decision_type = "all_terminal_volume_improves_but_still_not_claim_authority"
        next_experiment = "separate_outlet_scope_from_process_volume_deficit"
    elif scope_class == "nearest_terminal_volume_corrected_but_outlet_scope_unresolved":
        decision_type = "nearest_terminal_candidate_requires_authority"
        next_experiment = "audit_nearest_terminal_authority_then_relock"
        required.extend(
            [
                "prove_nearest_terminal_is_the_usgs_gauge_outlet",
                "do_not_replace_selected_outlet_without_rebuilding_outlet_provenance",
            ]
        )

    if terminal_hydrograph.get("selected_outlet_is_nearest_terminal") is False:
        if "resolve_selected_vs_nearest_terminal_conflict" not in required:
            required.append("resolve_selected_vs_nearest_terminal_conflict")

    return {
        "available": True,
        "status": "blocked_until_resolved",
        "diagnostic_only": True,
        "terminal_scope_blocker": terminal_scope_blocker,
        "scope_class": scope_class,
        "decision_type": decision_type,
        "next_experiment": next_experiment,
        "recommended_focus": focus,
        "flags": flags,
        "required_before_promotion": _dedupe_text(required),
        "fresh_locked_rerun_required": True,
        "temporary_terminal_metrics_allowed_as_final": False,
        "all_terminal_metrics_claim_authority": False,
        "nearest_terminal_metrics_claim_authority": False,
        "selected_terminal": _terminal_resolution_metrics(selected),
        "all_terminal": _terminal_resolution_metrics(all_terminal),
        "nearest_terminal": _terminal_resolution_metrics(nearest),
        "selected_outlet_is_nearest_terminal": terminal_hydrograph.get("selected_outlet_is_nearest_terminal"),
        "selected_outlet_distance_to_gauge_m": _safe_float(
            terminal_hydrograph.get("selected_outlet_distance_to_gauge_m")
        ),
        "nearest_terminal_distance_to_gauge_m": _safe_float(
            terminal_hydrograph.get("nearest_terminal_distance_to_gauge_m")
        ),
        "all_terminal_aggregation_valid": terminal_hydrograph.get("all_terminal_aggregation_valid"),
        "all_terminal_aggregation_reason": terminal_hydrograph.get("all_terminal_aggregation_reason"),
    }


def _post_aggregation_process_context(
    terminal_hydrograph: dict[str, Any],
    classification: dict[str, Any],
    water_balance: dict[str, Any],
    weather_forcing: dict[str, Any],
    soil_context: dict[str, Any],
) -> dict[str, Any]:
    """Explain residual volume deficit after valid all-terminal aggregation."""

    scope_class = classification.get("class") if isinstance(classification, dict) else None
    if (
        not isinstance(terminal_hydrograph, dict)
        or terminal_hydrograph.get("available") is not True
        or terminal_hydrograph.get("all_terminal_aggregation_valid") is not True
        or scope_class != "all_terminal_volume_deficit_persists_after_valid_aggregation"
    ):
        return {
            "available": False,
            "status": "not_applicable",
            "claim_authority": False,
            "temporary_metrics_allowed_as_final": False,
            "fresh_locked_rerun_required": True,
            "reason": "valid_all_terminal_post_aggregation_deficit_not_present",
        }

    selected = terminal_hydrograph.get("selected_terminal")
    all_terminal = terminal_hydrograph.get("all_terminal")
    selected = selected if isinstance(selected, dict) else {}
    all_terminal = all_terminal if isinstance(all_terminal, dict) else {}
    selected_pbias = _safe_float(selected.get("pbias_pct"))
    all_pbias = _safe_float(all_terminal.get("pbias_pct"))
    abs_improvement = None
    if selected_pbias is not None and all_pbias is not None:
        abs_improvement = abs(selected_pbias) - abs(all_pbias)

    observed = (
        weather_forcing.get("observed_runoff")
        if isinstance(weather_forcing.get("observed_runoff"), dict)
        else {}
    )
    observed_runoff_to_precip = _safe_float(observed.get("observed_runoff_to_overlap_precip_ratio"))
    observed_class = observed.get("runoff_precip_ratio_class")
    net_wateryld_to_precip = _safe_float(
        water_balance.get("net_wateryld_to_precip", water_balance.get("wateryld_to_precip"))
    )
    et_to_precip = _safe_float(water_balance.get("et_to_precip"))
    surface_runoff_to_precip = _safe_float(water_balance.get("surface_runoff_to_precip"))
    latq_to_precip = _safe_float(water_balance.get("latq_to_precip"))
    perc_to_precip = _safe_float(water_balance.get("perc_to_precip"))
    soil_degraded = bool(soil_context.get("soil_degraded")) if isinstance(soil_context, dict) else False

    domains: list[str] = []
    focus: list[str] = []
    if soil_degraded:
        domains.append("soil_provenance_limited")
        focus.append("repair_soil_provenance_before_parameter_attribution")
    if observed_class in {"observed_runoff_exceeds_precipitation", "high_observed_runoff_fraction"}:
        domains.append("forcing_or_area_high_runoff_demand")
        focus.append("audit_precipitation_gauge_area_snow_storage_and_external_inflow")
    if (
        observed_runoff_to_precip is not None
        and net_wateryld_to_precip is not None
        and net_wateryld_to_precip + 0.05 < observed_runoff_to_precip
    ):
        domains.append("swat_water_yield_below_observed_runoff")
        focus.append("increase_water_yield_only_if_physical_and_forcing_gates_support_it")
    if et_to_precip is not None and et_to_precip > 0.70:
        domains.append("et_fraction_high")
        focus.append("audit_pet_et_partition_and_soil_evaporation_controls")
    if (
        latq_to_precip is not None
        and perc_to_precip is not None
        and latq_to_precip < 0.02
        and perc_to_precip < 0.05
    ):
        domains.append("subsurface_partition_low")
        focus.append("screen_subsurface_partition_controls_after_soil_provenance_is_defensible")
    if surface_runoff_to_precip is not None and surface_runoff_to_precip > 0.55:
        domains.append("surface_runoff_partition_high")
        focus.append("audit_curve_number_landuse_soil_and_precipitation_forcing")
    if not domains:
        domains.append("process_deficit_unresolved")
        focus.append("review_water_balance_forcing_et_runoff_and_subsurface_terms")
    domains = _dedupe_text(domains)
    focus = _dedupe_text(focus)

    return {
        "available": True,
        "status": "diagnostic_only_process_or_forcing_blocker",
        "claim_authority": False,
        "temporary_metrics_allowed_as_final": False,
        "fresh_locked_rerun_required": True,
        "scope_class": scope_class,
        "selected_terminal_pbias_pct": selected_pbias,
        "all_terminal_pbias_pct": all_pbias,
        "all_terminal_abs_pbias_improvement_pct_points": abs_improvement,
        "all_terminal_kge": _safe_float(all_terminal.get("kge")),
        "all_terminal_nse": _safe_float(all_terminal.get("nse")),
        "observed_runoff_to_precip": observed_runoff_to_precip,
        "observed_runoff_fraction_class": observed_class,
        "swat_net_wateryld_to_precip": net_wateryld_to_precip,
        "swat_et_to_precip": et_to_precip,
        "swat_surface_runoff_to_precip": surface_runoff_to_precip,
        "swat_lateral_flow_to_precip": latq_to_precip,
        "swat_percolation_to_precip": perc_to_precip,
        "soil_degraded": soil_degraded,
        "soil_provenance_mode": soil_context.get("soil_provenance_mode") if isinstance(soil_context, dict) else None,
        "likely_process_domains": domains,
        "recommended_focus": focus,
        "candidate_explanations": _post_aggregation_candidate_explanations(
            domains=domains,
            observed_runoff_to_precip=observed_runoff_to_precip,
            net_wateryld_to_precip=net_wateryld_to_precip,
            et_to_precip=et_to_precip,
            surface_runoff_to_precip=surface_runoff_to_precip,
            latq_to_precip=latq_to_precip,
            perc_to_precip=perc_to_precip,
            soil_degraded=soil_degraded,
            soil_provenance_mode=soil_context.get("soil_provenance_mode") if isinstance(soil_context, dict) else None,
            observed_class=observed_class if isinstance(observed_class, str) else None,
        ),
        "required_before_claim": [
            "retain_all_terminal_metrics_as_diagnostic_only",
            "document_post_aggregation_volume_deficit_source",
            "run_fresh_locked_process_calibration_after_diagnostic_target_is_selected",
            "pass_physical_routing_sensitivity_calibration_and_metric_gates_on_locked_outputs",
        ],
        "claim_impact": "research_grade_blocked_until_post_aggregation_deficit_is_physically_explained_and_locked",
    }


def _post_aggregation_candidate_explanations(
    *,
    domains: list[str],
    observed_runoff_to_precip: float | None,
    net_wateryld_to_precip: float | None,
    et_to_precip: float | None,
    surface_runoff_to_precip: float | None,
    latq_to_precip: float | None,
    perc_to_precip: float | None,
    soil_degraded: bool,
    soil_provenance_mode: object,
    observed_class: str | None,
) -> list[dict[str, Any]]:
    explanations: list[dict[str, Any]] = []
    for domain in domains:
        if domain == "soil_provenance_limited":
            explanations.append(
                {
                    "domain": domain,
                    "status": "soil_provenance_degraded",
                    "evidence": f"soil_provenance_mode={soil_provenance_mode or 'unknown'}",
                    "next_action": "repair_soil_provenance_before_parameter_attribution",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "soil_fidelity_blocks_research_grade_until_repaired_and_rerun",
                }
            )
        elif domain == "forcing_or_area_high_runoff_demand":
            explanations.append(
                {
                    "domain": domain,
                    "status": observed_class or "high_observed_runoff_context_required",
                    "evidence": f"Qobs/P={_fmt(observed_runoff_to_precip)}",
                    "next_action": "audit_precipitation_gauge_area_snow_storage_and_external_inflow",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "forcing_area_basis_must_be_explained_before_parameter_claims",
                }
            )
        elif domain == "swat_water_yield_below_observed_runoff":
            explanations.append(
                {
                    "domain": domain,
                    "status": "swat_water_yield_below_observed_runoff",
                    "evidence": (
                        f"Qobs/P={_fmt(observed_runoff_to_precip)}; "
                        f"SWAT net wateryld/P={_fmt(net_wateryld_to_precip)}"
                    ),
                    "next_action": "increase_water_yield_only_if_physical_and_forcing_gates_support_it",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "water_yield_repair_requires_same_scope_locked_gates_before_claims",
                }
            )
        elif domain == "et_fraction_high":
            explanations.append(
                {
                    "domain": domain,
                    "status": "et_fraction_high",
                    "evidence": f"SWAT ET/P={_fmt(et_to_precip)}",
                    "next_action": "audit_pet_et_partition_and_soil_evaporation_controls",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "et_partition_controls_are_diagnostic_until_fresh_locked_gates_pass",
                }
            )
        elif domain == "subsurface_partition_low":
            explanations.append(
                {
                    "domain": domain,
                    "status": "subsurface_partition_low",
                    "evidence": (
                        f"SWAT lateral flow/P={_fmt(latq_to_precip)}; "
                        f"percolation/P={_fmt(perc_to_precip)}"
                    ),
                    "next_action": "screen_subsurface_partition_controls_after_soil_provenance_is_defensible",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "subsurface_controls_are_diagnostic_until_sensitivity_and_locked_gates_pass",
                }
            )
        elif domain == "surface_runoff_partition_high":
            explanations.append(
                {
                    "domain": domain,
                    "status": "surface_runoff_partition_high",
                    "evidence": f"SWAT surface runoff/P={_fmt(surface_runoff_to_precip)}",
                    "next_action": "audit_curve_number_landuse_soil_and_precipitation_forcing",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "runoff_generation_controls_are_diagnostic_until_locked_gates_pass",
                }
            )
        else:
            explanations.append(
                {
                    "domain": domain,
                    "status": "process_deficit_unresolved",
                    "evidence": (
                        f"Qobs/P={_fmt(observed_runoff_to_precip)}; "
                        f"SWAT net wateryld/P={_fmt(net_wateryld_to_precip)}"
                    ),
                    "next_action": "review_water_balance_forcing_et_runoff_and_subsurface_terms",
                    "fresh_locked_rerun_required": True,
                    "claim_impact": "unresolved_process_deficit_blocks_research_grade_until_explained",
                }
            )
    return explanations


def build_terminal_scope_decision_request(
    *,
    basin_id: str | None,
    blocker_domain: str | None,
    terminal_scope_resolution_plan: dict[str, Any],
    post_aggregation_process_context: dict[str, Any] | None = None,
    terminal_scope_provenance_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return package-owned typed guidance for unresolved terminal-scope decisions."""

    next_experiment = _safe_str(terminal_scope_resolution_plan.get("next_experiment"))
    decision_type = _safe_str(terminal_scope_resolution_plan.get("decision_type"))
    post_aggregation_process_context = (
        post_aggregation_process_context
        if isinstance(post_aggregation_process_context, dict)
        else {}
    )
    if blocker_domain == "provenance":
        question_basin = basin_id or "this basin"
        provenance_context = _terminal_scope_provenance_decision_context(
            terminal_scope_resolution_plan=terminal_scope_resolution_plan,
            terminal_scope_provenance_context=terminal_scope_provenance_context,
        )
        recommended_option = (
            "authorize_virtual_all_terminal_outlet"
            if provenance_context.get("virtual_all_terminal_candidate_supported") is True
            else "retain_exploratory_until_outlet_rebuilt"
        )
        return {
            "status": "needs_input",
            "question_id": f"{question_basin}_outlet_scope_authority" if basin_id else "outlet_scope_authority",
            "decision_type": decision_type or "selected_outlet_scope_authority_required",
            "question": (
                "Select the claim-authoritative outlet-scope path before any "
                f"research-grade rerun for basin {question_basin}."
            ),
            "options": [
                {
                    "id": "confirm_selected_terminal_authority",
                    "label": "Confirm selected terminal authority",
                    "claim_impact": (
                        "selected-outlet claims remain blocked until drainage area, gauge "
                        "position, and terminal inventory justify the selected terminal"
                    ),
                    "fresh_locked_rerun_required": True,
                },
                {
                    "id": "authorize_virtual_all_terminal_outlet",
                    "label": "Authorize virtual all-terminal outlet",
                    "claim_impact": (
                        "virtual all-terminal metrics remain diagnostic until explicit authority, "
                        "virtual outlet provenance, and same-scope locked gates pass"
                    ),
                    "fresh_locked_rerun_required": True,
                    "requires": [
                        "virtual_outlet_authority",
                        "virtual_outlet_scope_gate",
                        "same_scope_sensitivity_calibration_and_verification",
                    ],
                },
                {
                    "id": "retain_exploratory_until_outlet_rebuilt",
                    "label": "Retain exploratory outlet status",
                    "claim_impact": (
                        "no outlet or calibration research claim may be promoted from current "
                        "selected/all-terminal diagnostic metrics"
                    ),
                    "fresh_locked_rerun_required": False,
                },
            ],
            "recommended_option": recommended_option,
            "recommended_next_experiment": next_experiment or "resolve_claim_authoritative_outlet_then_relock",
            "accepted_by_required": "user_or_policy",
            "claim_impact": "terminal_scope_claim_blocked_until_decision_and_fresh_locked_rerun",
            "outlet_scope_evidence": provenance_context,
        }

    diagnostic_options, recommended_option = _terminal_scope_diagnostic_decision_options(
        decision_type=decision_type,
        next_experiment=next_experiment,
        post_aggregation_process_context=post_aggregation_process_context,
    )
    likely_domains = [
        str(domain)
        for domain in post_aggregation_process_context.get("likely_process_domains", [])
        if isinstance(domain, str) and domain
    ]
    recommended_focus = [
        str(focus)
        for focus in post_aggregation_process_context.get("recommended_focus", [])
        if isinstance(focus, str) and focus
    ]
    candidate_explanations = _decision_candidate_explanations(post_aggregation_process_context)
    decision = {
        "status": "diagnostic_only",
        "question_id": None,
        "decision_type": "process_or_forcing_diagnostic_selection",
        "question": (
            "No claim-authority decision is available yet; inspect the retained "
            "process, forcing, routing, and outlet-scope evidence before rerun."
        ),
        "options": diagnostic_options,
        "recommended_option": recommended_option,
        "recommended_next_experiment": next_experiment or "classify_blocker_before_rerun",
        "accepted_by_required": "agent_or_policy",
        "claim_impact": "diagnostic_plan_only_until_package_repair_and_fresh_locked_gates_pass",
    }
    if likely_domains:
        decision["likely_process_domains"] = likely_domains
    if recommended_focus:
        decision["recommended_focus"] = recommended_focus
    if candidate_explanations:
        decision["candidate_explanations"] = candidate_explanations
    return decision


def _decision_candidate_explanations(
    post_aggregation_process_context: dict[str, Any],
) -> list[dict[str, Any]]:
    explanations = post_aggregation_process_context.get("candidate_explanations")
    if not isinstance(explanations, list):
        return []
    retained: list[dict[str, Any]] = []
    for item in explanations:
        if not isinstance(item, dict):
            continue
        domain = item.get("domain")
        if not isinstance(domain, str) or not domain:
            continue
        entry = {
            "domain": domain,
            "status": _safe_str(item.get("status")) or "unknown",
            "evidence": _safe_str(item.get("evidence")) or "not_reported",
            "next_action": _safe_str(item.get("next_action")) or "classify_blocker_before_rerun",
            "fresh_locked_rerun_required": item.get("fresh_locked_rerun_required") is True,
            "claim_impact": _safe_str(item.get("claim_impact"))
            or "diagnostic_only_until_fresh_locked_gates_pass",
        }
        retained.append(entry)
    return retained


def _terminal_scope_provenance_decision_context(
    *,
    terminal_scope_resolution_plan: dict[str, Any],
    terminal_scope_provenance_context: dict[str, Any] | None,
) -> dict[str, Any]:
    source = terminal_scope_provenance_context if isinstance(terminal_scope_provenance_context, dict) else {}
    authority = source.get("terminal_authority_area_check")
    authority = authority if isinstance(authority, dict) else {}
    virtual = source.get("terminal_virtual_outlet_candidate")
    virtual = virtual if isinstance(virtual, dict) else {}
    conflict = source.get("terminal_outlet_conflict")
    conflict = conflict if isinstance(conflict, dict) else {}
    area_scope = source.get("terminal_area_scope")
    area_scope = area_scope if isinstance(area_scope, dict) else {}
    required_before_claim = [
        str(item)
        for item in virtual.get("required_before_claim", [])
        if isinstance(item, str) and item
    ]
    virtual_supported = (
        virtual.get("available") is True
        and virtual.get("claim_authority") is False
        and virtual.get("temporary_terminal_metrics_allowed_as_final") is False
        and virtual.get("fresh_locked_rerun_required") is True
        and authority.get("class") == "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
        and virtual.get("all_terminal_aggregation_valid") is True
    )
    selected_fraction = _safe_float(
        authority.get("selected_fraction")
        if authority.get("selected_fraction") is not None
        else virtual.get("selected_fraction_of_authority_area")
    )
    all_fraction = _safe_float(
        authority.get("all_terminal_fraction")
        if authority.get("all_terminal_fraction") is not None
        else virtual.get("all_terminal_fraction_of_authority_area")
    )
    terminal_gis_ids_raw = virtual.get("terminal_gis_ids")
    terminal_gis_ids = terminal_gis_ids_raw if isinstance(terminal_gis_ids_raw, list) else []
    evidence_flags = [
        "selected_terminal_partial_authoritative_area"
        if selected_fraction is not None and selected_fraction < 0.90
        else "",
        "all_terminal_matches_authoritative_area"
        if all_fraction is not None and 0.90 <= all_fraction <= 1.10
        else "",
        "virtual_all_terminal_candidate_available" if virtual_supported else "",
        "selected_outlet_not_nearest_terminal"
        if conflict.get("class") == "selected_largest_terminal_not_nearest_minor_branch_conflict"
        else "",
    ]
    return {
        "available": bool(authority or virtual or conflict or area_scope),
        "reference_area_source": authority.get("reference_area_source") or virtual.get("reference_area_source"),
        "authority_area_class": authority.get("class") or virtual.get("authority_class"),
        "terminal_area_scope_class": area_scope.get("class"),
        "selected_fraction_of_authority_area": selected_fraction,
        "all_terminal_fraction_of_authority_area": all_fraction,
        "virtual_all_terminal_candidate_supported": virtual_supported,
        "virtual_candidate_status": virtual.get("status"),
        "virtual_candidate_type": virtual.get("candidate_type"),
        "virtual_terminal_gis_ids": [
            int(item)
            for item in terminal_gis_ids
            if isinstance(item, (int, float))
        ],
        "all_terminal_aggregation_valid": virtual.get("all_terminal_aggregation_valid"),
        "all_terminal_aggregation_reason": virtual.get("all_terminal_aggregation_reason"),
        "terminal_outlet_conflict_class": conflict.get("class"),
        "evidence_flags": [flag for flag in evidence_flags if flag],
        "required_before_claim": required_before_claim
        or [
            "document_claim_authoritative_outlet_scope",
            "rerun_clean_locked_txtinout_before_reporting_metrics",
            "pass_physical_routing_sensitivity_calibration_metric_and_contract_gates",
        ],
        "claim_impact": "outlet_scope_decision_required_before_terminal_or_virtual_outlet_claims",
    }


def _terminal_scope_diagnostic_decision_options(
    *,
    decision_type: str | None,
    next_experiment: str | None,
    post_aggregation_process_context: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    options: list[dict[str, Any]] = []
    likely_domains = {
        str(domain)
        for domain in post_aggregation_process_context.get("likely_process_domains", [])
        if isinstance(domain, str) and domain
    }
    soil_degraded = bool(post_aggregation_process_context.get("soil_degraded"))

    if "soil_provenance_limited" in likely_domains:
        options.append(
            {
                "id": "repair_soil_provenance_before_parameter_attribution",
                "label": "Repair soil provenance first",
                "claim_impact": (
                    "process parameters remain diagnostic until soil provenance is defensible "
                    "and a fresh locked rerun passes normal gates"
                ),
                "fresh_locked_rerun_required": True,
                "required_artifacts": [
                    "metadata.json",
                    "reports/soil_report.json",
                    "physical_gates.json",
                ],
            }
        )
    if "forcing_or_area_high_runoff_demand" in likely_domains:
        options.append(
            {
                "id": "audit_high_observed_runoff_fraction_context",
                "label": "Audit high observed runoff demand",
                "claim_impact": (
                    "forcing, gauge-area, snow-storage, or external-inflow evidence must "
                    "explain the observed runoff demand before calibration can be interpreted"
                ),
                "fresh_locked_rerun_required": False,
                "required_artifacts": [
                    "reports/weather_forcing_summary.json",
                    "physical_gates.json",
                    "reports/terminal_trace.json",
                ],
            }
        )
    if "et_fraction_high" in likely_domains:
        options.append(
            {
                "id": "screen_pet_and_et_partition_controls",
                "label": "Screen PET and ET partition controls",
                "claim_impact": (
                    "ET-partition evidence can guide a repair, but final claims still require "
                    "same-scope sensitivity, locked calibration, and physical gates"
                ),
                "fresh_locked_rerun_required": True,
                "parameters": ["PET_CO", "ESCO", "EPCO"],
                "required_artifacts": [
                    "basin_wb_yr.txt",
                    "reports/et_partition_diagnostics.json",
                    "parameter_screen.json",
                ],
            }
        )
    if "subsurface_partition_low" in likely_domains:
        options.append(
            {
                "id": (
                    "screen_subsurface_partition_controls_after_soil_provenance"
                    if soil_degraded
                    else "screen_subsurface_partition_controls_with_retained_soil_provenance"
                ),
                "label": "Screen subsurface partition controls",
                "claim_impact": (
                    "subsurface controls remain diagnostic until soil provenance and locked "
                    "process gates support the same-scope rerun"
                ),
                "fresh_locked_rerun_required": True,
                "parameters": ["PERCO", "LATQ_CO", "ALPHA_BF", "RCHG_DP"],
                "required_artifacts": [
                    "basin_wb_yr.txt",
                    "parameter_screen.json",
                    "calibration/calibration_reports_locked/history.csv",
                ],
            }
        )
    if (
        decision_type == "post_aggregation_process_deficit"
        or next_experiment == "diagnose_weather_et_runoff_subsurface_deficit_after_terminal_scope"
        or "swat_water_yield_below_observed_runoff" in likely_domains
    ):
        options.append(
            {
                "id": "diagnose_post_aggregation_water_balance_deficit",
                "label": "Diagnose post-aggregation deficit",
                "claim_impact": (
                    "remaining all-terminal volume deficit must be explained by process, "
                    "forcing, or routing evidence before any metric promotion"
                ),
                "fresh_locked_rerun_required": True,
                "parameters": ["PET_CO", "ESCO", "EPCO", "CN2", "PERCO", "LATQ_CO", "ALPHA_BF", "RCHG_DP"],
                "required_artifacts": [
                    "basin_wb_yr.txt",
                    "reports/et_partition_diagnostics.json",
                    "parameter_screen.json",
                    "weather_forcing_summary.json",
                ],
            }
        )

    options.extend(
        [
            {
                "id": "run_source_backed_diagnostic",
                "label": "Run source-backed diagnostic",
                "claim_impact": (
                    "diagnostic evidence can identify the next package repair but cannot "
                    "promote metrics without a fresh locked rerun and normal gates"
                ),
                "fresh_locked_rerun_required": True,
            },
            {
                "id": "retain_exploratory_science_blocker",
                "label": "Retain exploratory blocker",
                "claim_impact": (
                    "current evidence remains an honest blocker until diagnostics expose "
                    "a repairable package, provenance, calibration, or parameter gap"
                ),
                "fresh_locked_rerun_required": False,
            },
        ]
    )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for option in options:
        option_id = str(option.get("id") or "")
        if not option_id or option_id in seen:
            continue
        seen.add(option_id)
        deduped.append(option)
    recommended = deduped[0]["id"] if deduped else "run_source_backed_diagnostic"
    return deduped, str(recommended)


def _terminal_resolution_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": metrics.get("available") is True,
        "pbias_pct": _safe_float(metrics.get("pbias_pct")),
        "nse": _safe_float(metrics.get("nse")),
        "kge": _safe_float(metrics.get("kge")),
        "sim_to_obs_volume_ratio": _safe_float(metrics.get("sim_to_obs_volume_ratio")),
        "kge_dominant_deficit": metrics.get("kge_dominant_deficit"),
    }


def _dedupe_text(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _next_actions(flags: list[dict[str, str]], gates: dict[str, Any], values: dict[str, Any]) -> list[str]:
    actions = []
    codes = {f["code"] for f in flags}
    soil = _soil_context(values)
    if "simulated_volume_excess" in codes:
        actions.append("Audit runoff generation and ET partitioning before any calibration search.")
    if "simulated_volume_deficit" in codes:
        actions.append("Audit ET losses, water-yield partitioning, forcing, and outlet provenance before any calibration search.")
    if "et_partition_high" in codes:
        actions.append("Run a governed sensitivity probe for PET_CO within 0.8-1.2 and ESCO/EPCO within 0.01-1.0; do not use legacy out-of-range PET_CO reductions.")
    if "soil_evaporation_dominates_et" in codes:
        actions.append("Inspect soil evaporation drivers: ESCO, canopy/plant cover, soil water availability, crop/management schedules, and weather PET forcing.")
    if "basin_water_yield_fraction_low" in codes:
        actions.append("Check why basin water yield is low relative to precipitation before accepting the simulated flow deficit.")
    if "subsurface_partition_low" in codes:
        if soil["soil_degraded"]:
            actions.append("Screen PERCO/LATQ_CO and aquifer controls only after soil provenance is acceptable.")
        else:
            actions.append("Screen PERCO/LATQ_CO and aquifer controls with retained soil provenance, then verify with a locked engine rerun.")
    if "surface_runoff_partition_high" in codes:
        actions.append("Inspect CN2/landuse/soil assignments and precipitation forcing behind high surface runoff.")
    if "hru_cn_distribution_extreme" in codes:
        actions.append("Audit HRU landuse/soil-to-curve-number mapping before calibration.")
    if "urban_landuse_dominates_runoff_response" in codes:
        actions.append("Verify developed-land NLCD handling, urban impervious assumptions, and whether the gauge basin is genuinely urban-dominated.")
    if "urban_curve_number_fixed_high" in codes:
        actions.append("Audit SWAT+ urban.urb curve-number assumptions for NLCD developed classes before treating calibration as a parameter-search problem.")
    if "outlet_provenance_needs_review" in codes or "outlet_reason_terminal_count_mismatch" in codes:
        actions.append("Review outlet selection against terminal inventory before accepting gauge-volume comparisons.")
    if "selected_terminal_partial_of_all_terminal_flow" in codes:
        actions.append("Compare observed gauge drainage area with terminal inventory and selected-vs-all terminal hydrographs before parameter calibration.")
    if "selected_terminal_not_nearest_gauge_terminal" in codes:
        actions.append("Compare selected-vs-nearest terminal hydrographs and outlet provenance before parameter calibration or claim promotion.")
    if "nearest_terminal_hydrograph_volume_closer" in codes:
        actions.append("Use the nearest-terminal hydrograph comparison to test whether volume bias is primarily an outlet-selection problem.")
    if "nearest_terminal_hydrograph_volume_gate_passes_diagnostic" in codes:
        actions.append("Do not promote nearest-terminal metrics; rerun or relock only after the gauge outlet terminal is made claim-authoritative.")
    if "all_terminal_routed_to_channel_reference_matches" in codes:
        actions.append("Keep all-terminal routed-to-channel agreement diagnostic-only until selected outlet scope is explained.")
    if "all_terminal_hydrograph_aggregation_not_claim_valid" in codes:
        actions.append("Audit terminal topology overlap before using any summed all-terminal hydrograph as an outlet-scope explanation.")
    if "all_terminal_hydrograph_volume_closer" in codes:
        actions.append("Use the selected-vs-all terminal hydrograph comparison to separate outlet-scope volume loss from hydrologic parameter error.")
    if "all_terminal_hydrograph_volume_gate_passes_diagnostic" in codes:
        actions.append("Do not promote all-terminal hydrograph metrics; first confirm gauge drainage area and terminal topology, then rerun with a claim-authoritative outlet.")
    if "all_terminal_hydrograph_volume_deficit_persists" in codes:
        actions.append("After terminal scope is reconciled, treat the remaining all-terminal volume deficit as a water-balance, forcing, or process-calibration blocker.")
    if "all_terminal_hydrograph_volume_better_skill_worse" in codes:
        actions.append("After outlet scope is resolved, diagnose timing and shape errors separately from total volume.")
    if "all_terminal_hydrograph_skill_limited_after_volume_correction" in codes:
        actions.append("Retain terminal aggregation as diagnostic-only and use KGE components to separate timing, variability, and bias limitations before any claim upgrade.")
    if "high_observed_runoff_fraction" in codes:
        actions.append("Audit snow/storage, baseflow contribution, drainage-area basis, and forcing-area representativeness before another parameter-only calibration attempt.")
        actions.append("Use the high runoff-demand interpretation flags to separate low SWAT water yield, snow/storage, aquifer release, and terminal-scope causes before extending calibration.")
    if "mass_closure_residual_high" in codes:
        actions.append("Audit basin water-balance accounting, wetland outflow treatment, storage change, and routing connectivity before treating calibration as a parameter search.")
    recommended = gates.get("recommended_next_action")
    if recommended and recommended not in actions:
        recommended_text = str(recommended)
        if not (
            "mass_closure_residual_high" in codes
            and "water-balance accounting" in recommended_text
        ):
            actions.append(recommended_text)
    return actions or ["No volume-bias-specific next action was identified."]


def _source_backed_alternatives(flags: list[dict[str, str]], values: dict[str, Any]) -> list[dict[str, Any]]:
    codes = {f["code"] for f in flags}
    soil = _soil_context(values)
    soil_degraded = bool(soil.get("soil_degraded"))
    alternatives: list[dict[str, Any]] = []

    if {"surface_runoff_partition_high", "hru_cn_distribution_extreme"} & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_curve_number_and_landuse_soil_mapping",
                "source": "SWAT+ SCS curve-number runoff documentation; CN controls rainfall excess and must preserve landuse/soil heterogeneity",
                "parameters": ["CN2"],
                "required_artifacts": ["hru_wb_aa.txt", "hru-data.hru", "landuse.lum", "cntable.lum"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_locked_rerun_physical_and_routing_gates_pass",
                "rationale": "High surface-runoff partition or extreme HRU CN distribution can explain simulated volume excess.",
            }
        )

    if {"urban_landuse_dominates_runoff_response", "urban_curve_number_fixed_high"} & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_developed_land_and_urban_curve_number_assumptions",
                "source": "SWAT+ urban landuse inputs and CN method affect impervious runoff response",
                "parameters": ["CN2"],
                "required_artifacts": ["raw/nlcd_2021.tif", "landuse.lum", "urban.urb"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_developed_land_assumptions_are_audited",
                "rationale": "Developed land dominates runoff response and fixed high urban CN can overwhelm calibration.",
            }
        )

    if {"et_partition_high", "soil_evaporation_dominates_et"} & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "screen_pet_and_et_partition_controls",
                "source": "SWAT+ soft-calibration ordering starts with ESCO and PETCO before runoff and subsurface terms",
                "parameters": ["PET_CO", "ESCO", "EPCO"],
                "required_artifacts": ["basin_wb_yr.txt", "reports/et_partition_diagnostics.json"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_basin_specific_sensitivity_and_final_gates_pass",
                "rationale": "High ET partition or soil evaporation dominance can explain simulated volume deficit.",
            }
        )

    if {"subsurface_partition_low", "basin_water_yield_fraction_low"} & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": (
                    "screen_subsurface_partition_controls_after_soil_provenance"
                    if soil_degraded
                    else "screen_subsurface_partition_controls_with_retained_soil_provenance"
                ),
                "source": "SWAT+ soft calibration includes LATQ_CO and PERCO after ET controls to rebalance water yield components",
                "parameters": ["LATQ_CO", "PERCO", "ALPHA_BF", "RCHG_DP"],
                "required_artifacts": ["basin_wb_yr.txt", "reports/soil_report.json", "parameter_screen.json"],
                "fresh_output_required": True,
                "claim_impact": (
                    "research_grade_blocked_until_soil_fidelity_sensitivity_and_locked_gates_pass"
                    if soil_degraded
                    else "diagnostic_until_basin_specific_screen_and_final_gates_pass"
                ),
                "rationale": (
                    "Low lateral/percolation/water-yield partition requires subsurface screening, but only after soil provenance is defensible."
                    if soil_degraded
                    else "Low lateral/percolation/water-yield partition persists with retained soil provenance; screen supported subsurface controls."
                ),
            }
        )

    if {
        "outlet_provenance_needs_review",
        "outlet_reason_terminal_count_mismatch",
        "selected_terminal_partial_of_all_terminal_flow",
        "selected_terminal_not_nearest_gauge_terminal",
        "nearest_terminal_hydrograph_volume_closer",
        "nearest_terminal_hydrograph_volume_gate_passes_diagnostic",
        "all_terminal_routed_to_channel_reference_matches",
        "all_terminal_hydrograph_aggregation_not_claim_valid",
        "all_terminal_hydrograph_volume_closer",
        "all_terminal_hydrograph_volume_gate_passes_diagnostic",
        "all_terminal_hydrograph_volume_deficit_persists",
        "all_terminal_hydrograph_volume_better_skill_worse",
        "all_terminal_hydrograph_skill_limited_after_volume_correction",
    } & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_outlet_selection_against_terminal_inventory",
                "source": "Project outlet provenance and terminal inventory gates require selected outlet authority before gauge-volume claims",
                "parameters": [],
                "required_artifacts": [
                    "outlet_provenance.json",
                    "reports/terminal_trace.json",
                    "routing_flow_gates.json",
                    "reports/mass_trace.json",
                    "reports/volume_bias_diagnostics.json",
                ],
                "fresh_output_required": False,
                "claim_impact": "outlet_and_routing_claims_block_research_grade_until_resolved",
                "rationale": "Volume bias may reflect selected-outlet, all-terminal aggregation, or terminal-inventory mismatch rather than hydrologic parameter error.",
            }
        )

    if {
        "selected_terminal_not_nearest_gauge_terminal",
        "nearest_terminal_hydrograph_volume_closer",
        "nearest_terminal_hydrograph_volume_gate_passes_diagnostic",
    } & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_selected_vs_nearest_terminal_hydrographs",
                "source": "Gauge-coordinate terminal ranking and SWAT+ channel output hydrographs",
                "parameters": [],
                "required_artifacts": [
                    "outputs/obs_q.csv",
                    "channel_sd_day.txt",
                    "reports/terminal_trace.json",
                    "reports/volume_bias_diagnostics.json",
                ],
                "fresh_output_required": False,
                "claim_impact": "diagnostic_only_until_selected_outlet_terminal_is_claim_authoritative",
                "rationale": "Nearest-terminal hydrograph metrics can identify an outlet-selection blocker but cannot become final evidence until outlet provenance is updated and rerun.",
            }
        )

    if "all_terminal_hydrograph_aggregation_not_claim_valid" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_terminal_topology_overlap_before_aggregation",
                "source": "Terminal trace upstream-area accounting shows overlapping terminal catchments; summed terminal hydrographs are diagnostic-only until topology is reconciled",
                "parameters": [],
                "required_artifacts": [
                    "routing_graph.graphml",
                    "reports/terminal_trace.json",
                    "channel_sd_day.txt",
                    "outlet_provenance.json",
                ],
                "fresh_output_required": False,
                "claim_impact": "terminal_scope_claim_blocks_research_grade_until_terminal_overlap_is_resolved",
                "rationale": "All-terminal hydrograph sums can double-count nested upstream areas when terminal catchments overlap.",
            }
        )

    if {
        "selected_terminal_partial_of_all_terminal_flow",
        "all_terminal_routed_to_channel_reference_matches",
        "all_terminal_hydrograph_volume_closer",
        "all_terminal_hydrograph_volume_gate_passes_diagnostic",
        "all_terminal_hydrograph_volume_deficit_persists",
        "all_terminal_hydrograph_volume_better_skill_worse",
        "all_terminal_hydrograph_skill_limited_after_volume_correction",
    } & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_selected_vs_all_terminal_hydrographs",
                "source": "Project outlet provenance, terminal inventory, and SWAT+ channel output hydrographs",
                "parameters": [],
                "required_artifacts": [
                    "outputs/obs_q.csv",
                    "channel_sd_day.txt",
                    "reports/terminal_trace.json",
                    "reports/volume_bias_diagnostics.json",
                ],
                "fresh_output_required": False,
                "claim_impact": "diagnostic_only_until_gauge_drainage_area_and_terminal_scope_are_reconciled",
                "rationale": "All-terminal hydrograph metrics can identify outlet-scope volume loss, but aggregation is not claim-authoritative until the selected terminal is reconciled with the gauge basin.",
            }
        )

    if "all_terminal_hydrograph_volume_deficit_persists" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "diagnose_post_aggregation_water_balance_deficit",
                "source": "SWAT+ calibration guidance treats streamflow as hard data and water-balance/process terms as soft evidence; residual all-terminal deficit requires process diagnosis before claim promotion",
                "parameters": ["PET_CO", "ESCO", "EPCO", "CN2", "PERCO", "LATQ_CO", "ALPHA_BF", "RCHG_DP"],
                "required_artifacts": [
                    "basin_wb_yr.txt",
                    "reports/et_partition_diagnostics.json",
                    "parameter_screen.json",
                    "calibration/calibration_reports_locked/history.csv",
                    "weather_forcing_summary.json",
                ],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_terminal_scope_process_gates_and_locked_calibration_pass",
                "rationale": "Valid all-terminal aggregation reduced outlet-scope volume loss but the aggregated hydrograph still fails the hard volume gate, so the remaining deficit must be explained by forcing, ET, runoff generation, subsurface partition, or other process evidence.",
            }
        )

    if "high_observed_runoff_fraction" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_high_observed_runoff_fraction_context",
                "source": "Hydrologic-signature and SWAT diagnostic-calibration practice uses water-balance/runoff signatures to constrain parameter search before claim promotion",
                "parameters": ["SFTMP", "SMTMP", "PERCO", "LATQ_CO", "LAT_TTIME", "ALPHA_BF", "RCHG_DP"],
                "required_artifacts": [
                    "reports/weather_forcing_summary.json",
                    "physical_gates.json",
                    "reports/terminal_trace.json",
                    "channel_sd_day.txt",
                    "snow.sno",
                ],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_high_runoff_demand_is_explained_by_snow_storage_baseflow_or_area_context",
                "rationale": "High observed runoff fraction can be physically real, but it makes residual volume deficits sensitive to snow/storage, groundwater release, drainage-area scope, and precipitation representativeness; these must be audited before treating calibration as only a parameter search.",
            }
        )

    if "mass_closure_residual_high" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_basin_water_balance_closure_terms",
                "source": "Project physical-gate policy requires mass/water-balance closure before research-grade claims",
                "parameters": [],
                "required_artifacts": [
                    "physical_gates.json",
                    "basin_wb_aa.txt",
                    "reports/mass_trace.json",
                    "wetland.wet",
                ],
                "fresh_output_required": False,
                "claim_impact": "research_grade_blocked_until_mass_closure_is_explained",
                "rationale": "Mass-closure residuals indicate accounting, wetland transfer, storage-change, or routing-connectivity issues that must be resolved before hydrologic calibration claims.",
            }
        )

    if "simulated_volume_excess" in codes and not alternatives:
        alternatives.append(
            {
                "rank": 1,
                "option": "collect_runoff_generation_context_for_volume_excess",
                "source": "Project physical-gate policy and SWAT+ surface-runoff documentation",
                "parameters": ["CN2", "SURLAG"],
                "required_artifacts": ["basin_wb_yr.txt", "hru_wb_aa.txt", "routing_flow_gates.json"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_physical_and_routing_gates_pass",
                "rationale": "Simulated volume excess requires runoff-generation context before calibration.",
            }
        )

    if "simulated_volume_deficit" in codes and not alternatives:
        alternatives.append(
            {
                "rank": 1,
                "option": "collect_et_soil_and_outlet_context_for_volume_deficit",
                "source": "Project physical-gate policy and SWAT+ water-balance calibration documentation",
                "parameters": ["PET_CO", "ESCO", "EPCO", "PERCO", "LATQ_CO"],
                "required_artifacts": ["basin_wb_yr.txt", "reports/et_partition_diagnostics.json", "outlet_provenance.json"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_physical_and_locked_calibration_gates_pass",
                "rationale": "Simulated volume deficit requires ET, soil-water, and outlet context before calibration.",
            }
        )

    return _prioritize_terminal_scope_alternatives(alternatives, codes)


def _prioritize_terminal_scope_alternatives(
    alternatives: list[dict[str, Any]],
    codes: set[str],
) -> list[dict[str, Any]]:
    terminal_scope_codes = {
        "selected_terminal_partial_of_all_terminal_flow",
        "selected_terminal_not_nearest_gauge_terminal",
        "nearest_terminal_hydrograph_volume_closer",
        "nearest_terminal_hydrograph_volume_gate_passes_diagnostic",
        "all_terminal_routed_to_channel_reference_matches",
        "all_terminal_hydrograph_aggregation_not_claim_valid",
        "all_terminal_hydrograph_volume_closer",
        "all_terminal_hydrograph_volume_gate_passes_diagnostic",
        "all_terminal_hydrograph_volume_deficit_persists",
        "all_terminal_hydrograph_volume_better_skill_worse",
        "all_terminal_hydrograph_skill_limited_after_volume_correction",
    }
    if not (terminal_scope_codes & codes):
        return alternatives

    terminal_options = {
        "audit_outlet_selection_against_terminal_inventory",
        "audit_selected_vs_nearest_terminal_hydrographs",
        "audit_terminal_topology_overlap_before_aggregation",
        "audit_selected_vs_all_terminal_hydrographs",
    }
    ranked = sorted(
        alternatives,
        key=lambda row: (
            0 if row.get("option") in terminal_options else 1,
            int(row.get("rank") or 999),
        ),
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx
    return ranked


def _recommended_probe_order(flags: list[dict[str, str]], values: dict[str, Any]) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for alt in _source_backed_alternatives(flags, values):
        parameters = alt.get("parameters")
        artifacts = alt.get("required_artifacts")
        probes.append(
            {
                "rank": alt.get("rank"),
                "diagnostic": alt.get("option"),
                "parameters": parameters if isinstance(parameters, list) else [],
                "required_artifacts": artifacts if isinstance(artifacts, list) else [],
                "fresh_output_required": bool(alt.get("fresh_output_required")),
                "claim_impact": alt.get("claim_impact"),
            }
        )
    return probes


def _render_markdown(report: dict[str, Any]) -> str:
    alignment = report.get("alignment", {})
    wb = report.get("water_balance", {})
    aquifer = report.get("aquifer_context", {})
    hru = report.get("hru_runoff", {})
    landuse = report.get("landuse_raster", {})
    urban = report.get("urban_assumptions", {})
    outlet = report.get("outlet_provenance", {})
    routing = report.get("routing_scope", {})
    terminal_hydrograph = report.get("terminal_hydrograph_scope", {})
    weather = report.get("weather_forcing_summary", {})
    high_runoff = report.get("high_runoff_demand_context", {})
    post_aggregation = report.get("post_aggregation_process_context", {})
    terminal_scope_class = report.get("terminal_hydrograph_scope_class")
    terminal_scope_flags = report.get("terminal_hydrograph_scope_flags")
    if not isinstance(terminal_scope_flags, list):
        terminal_scope_flags = []
    terminal_scope_focus = report.get("terminal_hydrograph_scope_recommended_focus")
    if not isinstance(terminal_scope_focus, list):
        terminal_scope_focus = []
    high_runoff_flags = (
        high_runoff.get("interpretation_flags", [])
        if isinstance(high_runoff, dict) and isinstance(high_runoff.get("interpretation_flags"), list)
        else []
    )
    post_aggregation_domains = (
        post_aggregation.get("likely_process_domains", [])
        if isinstance(post_aggregation, dict) and isinstance(post_aggregation.get("likely_process_domains"), list)
        else []
    )
    post_aggregation_focus = (
        post_aggregation.get("recommended_focus", [])
        if isinstance(post_aggregation, dict) and isinstance(post_aggregation.get("recommended_focus"), list)
        else []
    )
    post_aggregation_explanations = (
        post_aggregation.get("candidate_explanations", [])
        if isinstance(post_aggregation, dict) and isinstance(post_aggregation.get("candidate_explanations"), list)
        else []
    )
    observed_weather = (
        weather.get("observed_runoff", {})
        if isinstance(weather, dict) and isinstance(weather.get("observed_runoff"), dict)
        else {}
    )
    selected_hydro = terminal_hydrograph.get("selected_terminal", {}) if isinstance(terminal_hydrograph, dict) else {}
    all_hydro = terminal_hydrograph.get("all_terminal", {}) if isinstance(terminal_hydrograph, dict) else {}
    nearest_hydro = terminal_hydrograph.get("nearest_terminal", {}) if isinstance(terminal_hydrograph, dict) else {}
    if not isinstance(nearest_hydro, dict):
        nearest_hydro = {}
    lines = [
        "# Volume Bias Diagnostics",
        "",
        f"- Physical gate status: `{report.get('physical_gate_status')}`",
        f"- Dominant blocker: `{report.get('dominant_blocker')}`",
        f"- Primary issue: `{report.get('primary_issue')}`",
        "",
        "## Alignment",
        f"- Available: `{alignment.get('available')}`",
        f"- PBIAS: `{_fmt(alignment.get('pbias_pct'))}`",
        f"- Sim/obs volume ratio: `{_fmt(alignment.get('sim_to_obs_volume_ratio'))}`",
        f"- Days: `{alignment.get('n_days', 'n/a')}`",
        "",
        "## Water Balance",
        f"- P: `{_fmt(wb.get('precip_mm'))}` mm",
        f"- Water yield/P: `{_fmt(wb.get('wateryld_to_precip'))}`",
        f"- Net water yield/P: `{_fmt(wb.get('net_wateryld_to_precip'))}`",
        f"- Wetland outflow: `{_fmt(wb.get('wet_oflo_mm'))}` mm",
        f"- Snowfall/Snowmelt: `{_fmt(wb.get('snowfall_mm'))}` / `{_fmt(wb.get('snowmelt_mm'))}` mm",
        f"- Snowpack: `{_fmt(wb.get('snowpack_mm'))}` mm",
        f"- Soil water change: `{_fmt(wb.get('soil_water_change_mm'))}` mm",
        f"- Lagged lateral flow: `{_fmt(wb.get('lagged_lateral_flow_mm'))}` mm",
        f"- Surface runoff/P: `{_fmt(wb.get('surface_runoff_to_precip'))}`",
        f"- Lateral flow/P: `{_fmt(wb.get('latq_to_precip'))}`",
        f"- Percolation/P: `{_fmt(wb.get('perc_to_precip'))}`",
        f"- Mass residual/P: `{_fmt(wb.get('mass_residual_pct_of_precip'))}`%",
        f"- Mass residual basis: `{wb.get('mass_residual_basis', 'n/a')}`",
        f"- ET/P: `{_fmt(wb.get('et_to_precip'))}`",
        f"- Soil evaporation/ET: `{_fmt(wb.get('esoil_to_et'))}`",
        f"- Plant transpiration/ET: `{_fmt(wb.get('eplant_to_et'))}`",
        f"- CN: `{_fmt(wb.get('cn'))}`",
        "",
        "## Aquifer Context",
        f"- Available: `{aquifer.get('available') if isinstance(aquifer, dict) else False}`",
        f"- Aquifer count: `{aquifer.get('aquifer_count', 'n/a') if isinstance(aquifer, dict) else 'n/a'}`",
        f"- Flow mean/max: `{_fmt(aquifer.get('flow_mean_mm') if isinstance(aquifer, dict) else None)}` / `{_fmt(aquifer.get('flow_max_mm') if isinstance(aquifer, dict) else None)}` mm",
        f"- Storage mean: `{_fmt(aquifer.get('storage_mean_mm') if isinstance(aquifer, dict) else None)}` mm",
        f"- Recharge mean: `{_fmt(aquifer.get('recharge_mean_mm') if isinstance(aquifer, dict) else None)}` mm",
        f"- Revap mean: `{_fmt(aquifer.get('revap_mean_mm') if isinstance(aquifer, dict) else None)}` mm",
        "",
        "## HRU Runoff",
        f"- Available: `{hru.get('available')}`",
        f"- HRU count: `{hru.get('hru_count', 'n/a')}`",
        f"- CN mean/p90/max: `{_fmt(hru.get('cn_mean'))}` / `{_fmt(hru.get('cn_p90'))}` / `{_fmt(hru.get('cn_max'))}`",
        f"- Fraction CN >= 95: `{_fmt(hru.get('hru_fraction_cn_ge_95'))}`",
        "",
        "## Landuse Raster",
        f"- Available: `{landuse.get('available')}`",
        f"- Scope: `{landuse.get('source_scope', 'n/a')}`",
        f"- NLCD urban fraction: `{_fmt(landuse.get('urban_fraction'))}`",
        f"- NLCD water fraction: `{_fmt(landuse.get('water_fraction'))}`",
        "",
        "## Urban Assumptions",
        f"- Available: `{urban.get('available')}`",
        f"- Urban HRU fraction: `{_fmt(urban.get('urban_hru_fraction'))}`",
        f"- HRU-weighted impervious fraction: `{_fmt(urban.get('hru_weighted_frac_imp'))}`",
        f"- HRU-weighted urban CN: `{_fmt(urban.get('hru_weighted_urb_cn'))}`",
        "",
        "## Outlet",
        f"- Requested GIS ID: `{outlet.get('requested_outlet_gis_id')}`",
        f"- Selected GIS ID: `{outlet.get('selected_outlet_gis_id')}`",
        f"- Autodetected: `{outlet.get('outlet_autodetected')}`",
        f"- Terminal count: `{outlet.get('terminal_outlet_count')}`",
        "",
        "## Routing Scope",
        f"- Available: `{routing.get('available')}`",
        f"- Closure status: `{routing.get('closure_status')}`",
        f"- Selected-terminal share of all terminal flow: `{_fmt(routing.get('selected_terminal_fraction_of_all_terminal_flow'))}`",
        f"- All-terminal/routed-to-channel closure ratio: `{_fmt(routing.get('all_terminal_routed_to_channel_closure_ratio'))}`",
        f"- All-terminal/basin-water-yield closure ratio: `{_fmt(routing.get('all_terminal_mass_closure_ratio'))}`",
        f"- All-terminal aggregation valid: `{routing.get('all_terminal_aggregation_valid')}`",
        f"- Terminal failure class: `{routing.get('terminal_failure_class')}`",
        f"- Mass trace: `{routing.get('mass_trace_path')}`",
        "",
        "## Terminal Hydrograph Scope",
        f"- Available: `{terminal_hydrograph.get('available') if isinstance(terminal_hydrograph, dict) else False}`",
        f"- Diagnostic only: `{terminal_hydrograph.get('diagnostic_only') if isinstance(terminal_hydrograph, dict) else True}`",
        f"- All-terminal aggregation valid: `{terminal_hydrograph.get('all_terminal_aggregation_valid') if isinstance(terminal_hydrograph, dict) else None}`",
        f"- Aggregation reason: `{terminal_hydrograph.get('all_terminal_aggregation_reason') if isinstance(terminal_hydrograph, dict) else 'n/a'}`",
        f"- Scope class: `{terminal_scope_class}`",
        f"- Scope flags: `{', '.join(str(flag) for flag in terminal_scope_flags) or 'none'}`",
        f"- Scope recommended focus: `{', '.join(str(item) for item in terminal_scope_focus) or 'none'}`",
        f"- Terminal-scope blocker: `{report.get('terminal_scope_blocker')}`",
        f"- Selected-terminal PBIAS/NSE/KGE: `{_fmt(selected_hydro.get('pbias_pct'))}` / `{_fmt(selected_hydro.get('nse'))}` / `{_fmt(selected_hydro.get('kge'))}`",
        f"- Nearest-terminal GIS ID: `{terminal_hydrograph.get('nearest_terminal_gis_id') if isinstance(terminal_hydrograph, dict) else 'n/a'}`",
        f"- Nearest-terminal PBIAS/NSE/KGE: `{_fmt(nearest_hydro.get('pbias_pct'))}` / `{_fmt(nearest_hydro.get('nse'))}` / `{_fmt(nearest_hydro.get('kge'))}`",
        f"- All-terminal PBIAS/NSE/KGE: `{_fmt(all_hydro.get('pbias_pct'))}` / `{_fmt(all_hydro.get('nse'))}` / `{_fmt(all_hydro.get('kge'))}`",
        f"- Selected/all dominant KGE deficit: `{selected_hydro.get('kge_dominant_deficit', 'n/a')}` / `{all_hydro.get('kge_dominant_deficit', 'n/a')}`",
        f"- Absolute PBIAS improvement: `{_fmt(terminal_hydrograph.get('pbias_abs_improvement_pct_points') if isinstance(terminal_hydrograph, dict) else None)}` percentage points",
        "",
        "## Weather Forcing",
        f"- Summary path: `{report.get('weather_forcing_summary_path')}`",
        f"- Weather source: `{weather.get('weather_source') if isinstance(weather, dict) else None}`",
        f"- Precipitation available: `{weather.get('precipitation', {}).get('available') if isinstance(weather, dict) and isinstance(weather.get('precipitation'), dict) else False}`",
        f"- Station count: `{weather.get('precipitation', {}).get('station_count', 'n/a') if isinstance(weather, dict) and isinstance(weather.get('precipitation'), dict) else 'n/a'}`",
        f"- Mean areal total precipitation: `{_fmt(weather.get('precipitation', {}).get('mean_areal_total_precip_mm') if isinstance(weather, dict) and isinstance(weather.get('precipitation'), dict) else None)}` mm",
        f"- Observed-window precipitation: `{_fmt(observed_weather.get('precip_overlap_total_mm'))}` mm",
        f"- Observed runoff/P: `{_fmt(observed_weather.get('observed_runoff_to_overlap_precip_ratio'))}`",
        f"- Observed runoff/P class: `{observed_weather.get('runoff_precip_ratio_class', 'n/a')}`",
        "",
        "## High Runoff Demand Context",
        f"- Available: `{high_runoff.get('available') if isinstance(high_runoff, dict) else False}`",
        f"- Observed runoff/P: `{_fmt(high_runoff.get('observed_runoff_to_overlap_precip_ratio') if isinstance(high_runoff, dict) else None)}`",
        f"- SWAT net water yield/P: `{_fmt(high_runoff.get('swat_net_wateryld_to_precip') if isinstance(high_runoff, dict) else None)}`",
        f"- SWAT ET/P: `{_fmt(high_runoff.get('swat_et_to_precip') if isinstance(high_runoff, dict) else None)}`",
        f"- SWAT snowfall/snowmelt/P: `{_fmt(high_runoff.get('swat_snowfall_to_precip') if isinstance(high_runoff, dict) else None)}` / `{_fmt(high_runoff.get('swat_snowmelt_to_precip') if isinstance(high_runoff, dict) else None)}`",
        f"- Aquifer flow mean/max: `{_fmt(high_runoff.get('aquifer_flow_mean_mm') if isinstance(high_runoff, dict) else None)}` / `{_fmt(high_runoff.get('aquifer_flow_max_mm') if isinstance(high_runoff, dict) else None)}` mm",
        f"- Area basis ratio: `{_fmt(high_runoff.get('observed_area_to_all_terminal_area_ratio') if isinstance(high_runoff, dict) else None)}`",
        f"- Recommended probe: `{high_runoff.get('recommended_probe', 'n/a') if isinstance(high_runoff, dict) else 'n/a'}`",
        f"- Interpretation flags: `{', '.join(str(flag.get('code')) for flag in high_runoff_flags if isinstance(flag, dict) and flag.get('code')) or 'none'}`",
        "",
        "## Post-Aggregation Process Context",
        f"- Available: `{post_aggregation.get('available') if isinstance(post_aggregation, dict) else False}`",
        f"- Status: `{post_aggregation.get('status', 'n/a') if isinstance(post_aggregation, dict) else 'n/a'}`",
        f"- Claim authority: `{post_aggregation.get('claim_authority') if isinstance(post_aggregation, dict) else False}`",
        f"- All-terminal PBIAS: `{_fmt(post_aggregation.get('all_terminal_pbias_pct') if isinstance(post_aggregation, dict) else None)}`",
        f"- Observed runoff/P: `{_fmt(post_aggregation.get('observed_runoff_to_precip') if isinstance(post_aggregation, dict) else None)}`",
        f"- SWAT net water yield/P: `{_fmt(post_aggregation.get('swat_net_wateryld_to_precip') if isinstance(post_aggregation, dict) else None)}`",
        f"- SWAT ET/P: `{_fmt(post_aggregation.get('swat_et_to_precip') if isinstance(post_aggregation, dict) else None)}`",
        f"- Likely process domains: `{', '.join(str(item) for item in post_aggregation_domains) or 'none'}`",
        f"- Recommended focus: `{', '.join(str(item) for item in post_aggregation_focus) or 'none'}`",
        f"- Candidate explanations: `{', '.join(str(item.get('domain')) for item in post_aggregation_explanations if isinstance(item, dict) and item.get('domain')) or 'none'}`",
        "",
        "## Flags",
    ]
    flags = report.get("diagnostic_flags") or []
    if flags:
        lines.extend(f"- `{f.get('code')}`: {f.get('evidence')}" for f in flags)
    else:
        lines.append("- No flags.")
    lines += ["", "## Next Actions"]
    lines.extend(f"- {a}" for a in report.get("next_actions", []))
    lines += ["", "## Source-Backed Alternatives"]
    alternatives = report.get("source_backed_alternatives") or []
    if alternatives:
        for alt in alternatives:
            params = ", ".join(str(p) for p in alt.get("parameters", [])) or "none"
            artifacts = ", ".join(str(a) for a in alt.get("required_artifacts", [])) or "n/a"
            lines.append(
                f"- `{alt.get('option')}`: parameters `{params}`; artifacts `{artifacts}`; "
                f"impact `{alt.get('claim_impact')}`; source: {alt.get('source')}"
            )
    else:
        lines.append("- No source-backed alternatives.")
    lines += ["", "## Recommended Probe Order"]
    probes = report.get("recommended_probe_order") or []
    if probes:
        for probe in probes:
            params = ", ".join(str(p) for p in probe.get("parameters", [])) or "none"
            lines.append(
                f"- `{probe.get('diagnostic')}`: parameters `{params}`; "
                f"fresh_output_required=`{probe.get('fresh_output_required')}`"
            )
    else:
        lines.append("- No probe order.")
    return "\n".join(lines) + "\n"


def _read_observed_series(path: Path) -> pd.Series | None:
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty:
        return None
    date_col = None
    for candidate in ("date", "datetime", "Date"):
        if candidate in df.columns:
            date_col = candidate
            break
    if date_col is None:
        date_col = df.columns[0]
    value_col = None
    for candidate in ("obs", "q_cms", "flow_cms", "discharge", "value"):
        if candidate in df.columns and candidate != date_col:
            value_col = candidate
            break
    if value_col is None:
        numeric_cols = [c for c in df.columns if c != date_col]
        if not numeric_cols:
            return None
        value_col = numeric_cols[0]
    try:
        idx = pd.to_datetime(df[date_col]).dt.normalize()
        values = pd.to_numeric(df[value_col], errors="coerce")
    except Exception:
        return None
    series = pd.Series(values.to_numpy(dtype=float), index=idx, name="obs").dropna()
    return series if not series.empty else None


def _terminal_ids_from_values(
    values: dict[str, Any],
    routing_scope: dict[str, Any],
    outlet: dict[str, Any],
    txt: Path,
) -> list[int]:
    candidates = _first_not_none(
        values.get("terminal_outlet_ids"),
        routing_scope.get("terminal_outlet_ids"),
        outlet.get("terminal_outlet_ids"),
    )
    ids: list[int] = []
    if isinstance(candidates, list):
        for item in candidates:
            gid = _safe_int(item)
            if gid is not None:
                ids.append(gid)
    if not ids:
        ids = sorted(int(gid) for gid in _terminal_ids_from_chandeg_con(txt))
    return sorted(set(ids))


def _hydrograph_metric_summary(obs: pd.Series, sim: pd.Series) -> dict[str, Any]:
    if sim is None or sim.empty:
        return {"available": False, "reason": "sim_series_empty"}
    try:
        aligned = align_timeseries(obs, sim)
    except Exception as exc:
        return {"available": False, "reason": f"alignment_failed: {exc}"}
    if aligned.empty:
        return {"available": False, "reason": "no_overlap"}
    obs_vals = aligned["obs"].astype(float).tolist()
    sim_vals = aligned["sim"].astype(float).tolist()
    obs_sum = float(aligned["obs"].sum())
    sim_sum = float(aligned["sim"].sum())
    try:
        nse_value = float(nse(obs_vals, sim_vals))
    except Exception:
        nse_value = None
    try:
        kge_value = float(kge(obs_vals, sim_vals))
    except Exception:
        kge_value = None
    try:
        components_raw = kge_components(obs_vals, sim_vals)
        component_payload: dict[str, Any] = {"method": components_raw.get("method")}
        for key, value in components_raw.items():
            if key == "method":
                continue
            component_payload[key] = _safe_float(value)
    except Exception:
        component_payload = {}
    try:
        pbias_value = float(pbias(obs_vals, sim_vals))
    except Exception:
        pbias_value = None
    dominant_deficit = _dominant_kge_deficit(component_payload)
    return {
        "available": True,
        "n_days": int(len(aligned)),
        "start": str(pd.to_datetime(aligned.index[0]).date()),
        "end": str(pd.to_datetime(aligned.index[-1]).date()),
        "obs_sum": obs_sum,
        "sim_sum": sim_sum,
        "sim_to_obs_volume_ratio": (sim_sum / obs_sum) if obs_sum else None,
        "pbias_pct": pbias_value,
        "nse": nse_value,
        "kge": kge_value,
        "kge_components": component_payload,
        "kge_dominant_deficit": dominant_deficit,
    }


def _dominant_kge_deficit(components: dict[str, Any]) -> str | None:
    deficits = {
        "correlation": _safe_float(components.get("correlation_deficit")),
        "variability": _safe_float(components.get("variability_deficit")),
        "bias": _safe_float(components.get("bias_deficit")),
    }
    finite = {
        name: value
        for name, value in deficits.items()
        if value is not None and math.isfinite(value)
    }
    if not finite:
        return None
    return max(finite, key=finite.get)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _first_existing_path(*values: Any) -> Path | None:
    for value in values:
        if not value:
            continue
        try:
            path = Path(str(value)).expanduser().resolve()
        except (TypeError, ValueError):
            continue
        if path.is_file():
            return path
    return None


def _lookup(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _first_not_none(*items: Any) -> Any:
    for item in items:
        if item is not None:
            return item
    return None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _series_ratio(df: pd.DataFrame, num_col: str, den_col: str) -> pd.Series:
    num = pd.to_numeric(df.get(num_col), errors="coerce")
    den = pd.to_numeric(df.get(den_col), errors="coerce")
    return num / den.replace(0, pd.NA)


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    val = _safe_float(value)
    if val is None:
        return "n/a"
    return f"{val:.4g}"
