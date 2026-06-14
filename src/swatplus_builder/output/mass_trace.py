"""Mass-conservation trace for SWAT+ run artifacts.

The trace follows documented/header units only. It never selects empirical
scale factors and never uses NSE/KGE to decide how to interpret flow.
"""

from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import pandas as pd
from pydantic import BaseModel, Field

from ..errors import SwatBuilderExternalError, SwatBuilderInputError
from .eval import _terminal_ids_from_chandeg_con, _unit_for_column
from .reader import OutputTable, read_output_file

_SECONDS_PER_DAY = 86400.0
_SECONDS_PER_YEAR = 365.0 * _SECONDS_PER_DAY
_SQMI_TO_KM2 = 2.589988110336

ClosureStatus = Literal[
    "pass",
    "fail_no_land_generation",
    "fail_hru_to_channel",
    "fail_channel_entry",
    "fail_lte_transfer_scale",
    "fail_outlet_selection",
    "fail_mass_closure",
    "insufficient_data",
]


class MassTraceReport(BaseModel):
    """Mass-conservation trace for one run directory."""

    basin_id: str = "unknown"
    run_dir: str
    txtinout_dir: str
    generated_at: str
    simulation_period: str | None = None
    evaluation_period: str | None = None
    model_area_km2: float | None = None
    precip_mm: float | None = None
    et_mm: float | None = None
    basin_wateryld_mm: float | None = None
    basin_routed_to_channel_mm: float | None = None
    surq_mm: float | None = None
    latq_mm: float | None = None
    gwq_mm: float | None = None
    basin_wateryld_m3: float | None = None
    basin_routed_to_channel_m3: float | None = None
    routed_to_channel_closure_ratio: float | None = None
    all_terminal_routed_to_channel_closure_ratio: float | None = None
    all_terminal_mass_closure_ratio: float | None = None
    selected_terminal_fraction_of_all_terminal_flow: float | None = None
    closure_reference: str = "basin_wateryld_m3"
    basin_summary_outflow_m3: float | None = None
    hru_wateryld_mm: float | None = None
    hru_wateryld_m3: float | None = None
    lsu_outflow_m3: float | None = None
    ru_outflow_m3: float | None = None
    ru_outflow_to_basin_wateryld_ratio: float | None = None
    channel_inflow_m3: float | None = None
    channel_outflow_m3: float | None = None
    terminal_outflow_m3: float | None = None
    all_terminal_outflow_m3: float | None = None
    selected_outlet_gis_id: int | None = None
    selected_outlet_is_terminal: bool | None = None
    terminal_outlet_count: int | None = None
    basin_wb_source_file: str | None = None
    basin_wb_row_count: int | None = None
    basin_wb_years: list[int] = Field(default_factory=list)
    basin_summary_source_file: str | None = None
    basin_summary_row_count: int | None = None
    basin_summary_years: list[int] = Field(default_factory=list)
    channel_source_file: str | None = None
    channel_flow_unit: str | None = None
    channel_row_count: int | None = None
    channel_years: list[int] = Field(default_factory=list)
    selected_channel_row_count: int | None = None
    selected_channel_years: list[int] = Field(default_factory=list)
    terminal_channel_row_count: int | None = None
    terminal_channel_years: list[int] = Field(default_factory=list)
    summary_closure_ratio: float | None = None
    mass_closure_ratio: float | None = None
    closure_status: ClosureStatus = "insufficient_data"
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_backed_alternatives: list[dict[str, Any]] = Field(default_factory=list)
    recommended_probe_order: list[dict[str, Any]] = Field(default_factory=list)


class TerminalTraceRow(BaseModel):
    """One terminal channel and its upstream footprint."""

    terminal_gis_id: int
    terminal_internal_id: int
    outflow_m3: float | None = None
    percent_of_all_terminal_outflow: float | None = None
    distance_to_usgs_outlet_m: float | None = None
    upstream_channel_count: int | None = None
    upstream_hru_count: int | None = None
    upstream_area_km2: float | None = None
    is_selected_evaluation_outlet: bool = False
    is_nearest_terminal: bool = False
    is_largest_flow_terminal: bool = False
    is_largest_area_terminal: bool = False


class TerminalOverlapRow(BaseModel):
    """Pairwise overlap between two terminal upstream footprints."""

    terminal_a_gis_id: int
    terminal_b_gis_id: int
    shared_upstream_area_km2: float
    terminal_a_upstream_area_km2: float | None = None
    terminal_b_upstream_area_km2: float | None = None
    fraction_of_terminal_a: float | None = None
    fraction_of_terminal_b: float | None = None
    shared_channel_count: int
    shared_channel_ids: list[int] = Field(default_factory=list)
    shared_channel_ids_truncated: bool = False


class TerminalTraceReport(BaseModel):
    """Terminal-channel inventory for one basin run directory."""

    basin_id: str = "unknown"
    run_dir: str
    txtinout_dir: str
    generated_at: str
    simulation_period: str | None = None
    selected_outlet_gis_id: int | None = None
    selected_outlet_reason: str | None = None
    selected_outlet_is_terminal: bool | None = None
    selected_outlet_distance_to_gauge_m: float | None = None
    gauge_lat: float | None = None
    gauge_lon: float | None = None
    gauge_coordinate_source: str | None = None
    terminal_count: int | None = None
    terminal_inventory_count: int | None = None
    missing_terminal_gis_ids: list[int] = Field(default_factory=list)
    orphan_terminal_gis_ids: list[int] = Field(default_factory=list)
    material_missing_terminal_gis_ids: list[int] = Field(default_factory=list)
    missing_terminal_upstream_area_km2: float | None = None
    basin_nldi_area_km2: float | None = None
    usgs_site_drainage_area_sqmi: float | None = None
    usgs_site_drainage_area_km2: float | None = None
    usgs_site_drainage_area_source: str | None = None
    usgs_site_metadata_path: str | None = None
    delineated_area_km2: float | None = None
    hru_area_km2: float | None = None
    selected_terminal_upstream_area_km2: float | None = None
    all_terminal_upstream_area_km2: float | None = None
    sum_terminal_upstream_area_km2: float | None = None
    shared_upstream_area_km2: float | None = None
    terminal_overlap_pairs: list[TerminalOverlapRow] = Field(default_factory=list)
    selected_terminal_fraction_of_nldi_area: float | None = None
    selected_terminal_fraction_of_usgs_site_area: float | None = None
    all_terminal_fraction_of_nldi_area: float | None = None
    all_terminal_fraction_of_usgs_site_area: float | None = None
    delineated_fraction_of_nldi_area: float | None = None
    selected_terminal_fraction_of_delineated_area: float | None = None
    all_terminal_fraction_of_delineated_area: float | None = None
    terminal_area_scope_class: str | None = None
    terminal_area_scope_flags: list[str] = Field(default_factory=list)
    terminal_area_scope_claim_impact: str | None = None
    terminal_authority_area_check: dict[str, Any] = Field(default_factory=dict)
    terminal_virtual_outlet_candidate: dict[str, Any] = Field(default_factory=dict)
    terminal_virtual_outlet_candidate_path: str | None = None
    terminal_outlet_conflict_class: str | None = None
    terminal_outlet_conflict_flags: list[str] = Field(default_factory=list)
    terminal_outlet_conflict_claim_impact: str | None = None
    failure_class: Literal[
        "selected_outlet_wrong",
        "selected_outlet_partial_basin",
        "multi_terminal_requires_aggregation",
        "output_source_not_authoritative",
        "routing_graph_chandeg_mismatch",
        "generated_topology_mismatch",
    ] = "generated_topology_mismatch"
    terminal_inventory: list[TerminalTraceRow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_backed_alternatives: list[dict[str, Any]] = Field(default_factory=list)
    recommended_probe_order: list[dict[str, Any]] = Field(default_factory=list)


def classify_terminal_area_scope(
    *,
    selected_terminal_fraction_of_nldi_area: object = None,
    all_terminal_fraction_of_nldi_area: object = None,
    selected_terminal_fraction_of_delineated_area: object = None,
    all_terminal_fraction_of_delineated_area: object = None,
) -> dict[str, Any]:
    """Classify whether selected/all terminal area supports gauge-scope claims."""

    selected_nldi = _safe_float(selected_terminal_fraction_of_nldi_area)
    all_nldi = _safe_float(all_terminal_fraction_of_nldi_area)
    selected_delineated = _safe_float(selected_terminal_fraction_of_delineated_area)
    all_delineated = _safe_float(all_terminal_fraction_of_delineated_area)
    flags: list[str] = []
    if selected_nldi is None or all_nldi is None:
        return {
            "class": "terminal_area_context_incomplete",
            "flags": ["terminal_area_context_incomplete"],
            "claim_impact": "terminal_scope_claim_blocked_until_terminal_area_context_exists",
        }
    if selected_nldi < 0.90:
        flags.append("selected_terminal_partial_nldi_area")
    if selected_delineated is not None and selected_delineated < 0.90:
        flags.append("selected_terminal_partial_delineated_area")
    if all_nldi >= 0.90:
        flags.append("all_terminal_matches_nldi_area")
    else:
        flags.append("all_terminal_nldi_area_deficit")
    if all_delineated is not None:
        if all_delineated >= 0.95:
            flags.append("all_terminal_matches_delineated_area")
        else:
            flags.append("all_terminal_delineated_area_deficit")

    if "selected_terminal_partial_nldi_area" in flags and "all_terminal_matches_nldi_area" in flags:
        cls = "selected_terminal_partial_basin_all_terminal_matches"
        impact = "terminal_scope_claim_blocked_until_selected_outlet_scope_is_explained"
    elif "selected_terminal_partial_nldi_area" in flags and "all_terminal_nldi_area_deficit" in flags:
        cls = "selected_and_all_terminal_area_deficit"
        impact = "terminal_scope_claim_blocked_until_basin_area_and_terminal_inventory_are_reconciled"
    elif selected_nldi >= 0.90 and all_nldi >= 0.90:
        cls = "selected_terminal_area_matches_basin"
        impact = "terminal_area_scope_does_not_block_claim_by_itself"
    else:
        cls = "terminal_area_scope_ambiguous"
        impact = "terminal_scope_claim_blocked_until_terminal_area_context_is_explained"
    return {"class": cls, "flags": flags, "claim_impact": impact}


def classify_terminal_authority_area(
    *,
    selected_terminal_fraction_of_usgs_site_area: object = None,
    all_terminal_fraction_of_usgs_site_area: object = None,
    selected_terminal_fraction_of_nldi_area: object = None,
    all_terminal_fraction_of_nldi_area: object = None,
) -> dict[str, Any]:
    """Classify terminal area support using official USGS site area first."""

    selected_usgs = _safe_float(selected_terminal_fraction_of_usgs_site_area)
    all_usgs = _safe_float(all_terminal_fraction_of_usgs_site_area)
    selected_nldi = _safe_float(selected_terminal_fraction_of_nldi_area)
    all_nldi = _safe_float(all_terminal_fraction_of_nldi_area)
    if selected_usgs is not None and all_usgs is not None:
        reference = "usgs_site_drainage_area"
        selected = selected_usgs
        all_term = all_usgs
        partial_flag = "selected_terminal_partial_usgs_site_area"
        all_match_flag = "all_terminal_matches_usgs_site_area"
        all_deficit_flag = "all_terminal_usgs_site_area_deficit"
    elif selected_nldi is not None and all_nldi is not None:
        reference = "nldi_reference_area"
        selected = selected_nldi
        all_term = all_nldi
        partial_flag = "selected_terminal_partial_nldi_area"
        all_match_flag = "all_terminal_matches_nldi_area"
        all_deficit_flag = "all_terminal_nldi_area_deficit"
    else:
        return {
            "available": False,
            "reference_area_source": None,
            "class": "terminal_authority_area_context_incomplete",
            "flags": ["terminal_authority_area_context_incomplete"],
            "claim_impact": "terminal_scope_claim_blocked_until_authoritative_area_context_exists",
        }

    flags: list[str] = []
    if selected < 0.90:
        flags.append(partial_flag)
    if all_term >= 0.90:
        flags.append(all_match_flag)
    else:
        flags.append(all_deficit_flag)

    if selected >= 0.90:
        cls = "selected_terminal_matches_authoritative_area"
        impact = "terminal_area_scope_does_not_block_claim_by_itself"
    elif all_term >= 0.90:
        cls = "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
        impact = "terminal_scope_claim_blocked_until_selected_outlet_scope_is_explained"
    else:
        cls = "selected_and_all_terminal_authoritative_area_deficit"
        impact = "terminal_scope_claim_blocked_until_basin_area_and_terminal_inventory_are_reconciled"

    return {
        "available": True,
        "reference_area_source": reference,
        "selected_fraction": selected,
        "all_terminal_fraction": all_term,
        "class": cls,
        "flags": flags,
        "claim_impact": impact,
    }


def classify_terminal_outlet_conflict(
    *,
    selected_row: TerminalTraceRow | dict[str, Any] | None,
    nearest_row: TerminalTraceRow | dict[str, Any] | None,
    gauge_coordinate_source: object = None,
) -> dict[str, Any]:
    """Classify selected-vs-nearest terminal conflicts for outlet authority."""

    flags: list[str] = []
    if selected_row is None:
        return {
            "class": "selected_terminal_missing",
            "flags": ["selected_terminal_missing"],
            "claim_impact": "terminal_scope_claim_blocked_until_selected_terminal_exists",
        }
    if nearest_row is None or not gauge_coordinate_source:
        return {
            "class": "nearest_terminal_context_missing",
            "flags": ["nearest_terminal_context_missing"],
            "claim_impact": "terminal_scope_claim_blocked_until_gauge_terminal_ranking_exists",
        }
    selected_gis_id = _row_value(selected_row, "terminal_gis_id")
    nearest_gis_id = _row_value(nearest_row, "terminal_gis_id")
    if selected_gis_id == nearest_gis_id:
        return {
            "class": "selected_terminal_is_nearest_gauge_terminal",
            "flags": ["selected_terminal_is_nearest_gauge_terminal"],
            "claim_impact": "terminal_outlet_conflict_does_not_block_claim_by_itself",
        }

    flags.append("selected_terminal_not_nearest_gauge_terminal")
    if _row_value(selected_row, "is_largest_flow_terminal") is True:
        flags.append("selected_terminal_largest_flow")
    if _row_value(selected_row, "is_largest_area_terminal") is True:
        flags.append("selected_terminal_largest_area")
    selected_area = _coerce_float(_row_value(selected_row, "upstream_area_km2"))
    nearest_area = _coerce_float(_row_value(nearest_row, "upstream_area_km2"))
    if selected_area is not None and nearest_area is not None and nearest_area > 0:
        if selected_area >= nearest_area * 2.0:
            flags.append("nearest_terminal_substantially_smaller_area")
    selected_flow = _coerce_float(_row_value(selected_row, "percent_of_all_terminal_outflow"))
    nearest_flow = _coerce_float(_row_value(nearest_row, "percent_of_all_terminal_outflow"))
    if selected_flow is not None and nearest_flow is not None and nearest_flow > 0:
        if selected_flow >= nearest_flow * 2.0:
            flags.append("nearest_terminal_substantially_smaller_flow")

    if (
        "selected_terminal_largest_flow" in flags
        and "selected_terminal_largest_area" in flags
        and (
            "nearest_terminal_substantially_smaller_area" in flags
            or "nearest_terminal_substantially_smaller_flow" in flags
        )
    ):
        cls = "selected_largest_terminal_not_nearest_minor_branch_conflict"
        impact = "terminal_scope_claim_blocked_until_hydrofabric_or_gauge_outlet_authority_resolves_conflict"
    elif "selected_terminal_largest_flow" in flags or "selected_terminal_largest_area" in flags:
        cls = "selected_largest_terminal_not_nearest_gauge_terminal"
        impact = "terminal_scope_claim_blocked_until_selected_terminal_is_justified_against_gauge_location"
    else:
        cls = "selected_terminal_not_nearest_and_not_dominant"
        impact = "terminal_scope_claim_blocked_until_outlet_selection_is_repaired_or_justified"
    return {"class": cls, "flags": flags, "claim_impact": impact}


def _row_value(row: object, name: str) -> object:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def fetch_usgs_site_metadata(usgs_id: str, *, timeout_s: float = 3.0) -> dict[str, Any]:
    """Fetch official USGS Site Service metadata for one gauge."""

    site = str(usgs_id).strip()
    if not site.isdigit():
        return {
            "available": False,
            "site_no": site,
            "source": "https://waterservices.usgs.gov/nwis/site/",
            "error": "site_number_not_numeric",
        }
    query = urllib.parse.urlencode(
        {
            "format": "rdb",
            "sites": site,
            "siteOutput": "expanded",
        }
    )
    url = f"https://waterservices.usgs.gov/nwis/site/?{query}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310  (fixed https USGS endpoint)
            text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {"available": False, "site_no": site, "source": url, "error": str(exc)}

    rows = _parse_usgs_rdb(text)
    row = next((item for item in rows if str(item.get("site_no") or "") == site), rows[0] if rows else None)
    if not row:
        return {"available": False, "site_no": site, "source": url, "error": "site_not_found"}
    drain_sqmi = _safe_float(row.get("drain_area_va"))
    contrib_sqmi = _safe_float(row.get("contrib_drain_area_va"))
    return {
        "available": True,
        "site_no": site,
        "station_nm": row.get("station_nm"),
        "site_tp_cd": row.get("site_tp_cd"),
        "dec_lat_va": _safe_float(row.get("dec_lat_va")),
        "dec_long_va": _safe_float(row.get("dec_long_va")),
        "huc_cd": row.get("huc_cd"),
        "drain_area_va_sqmi": drain_sqmi,
        "drain_area_km2": None if drain_sqmi is None else drain_sqmi * _SQMI_TO_KM2,
        "contrib_drain_area_va_sqmi": contrib_sqmi,
        "contrib_drain_area_km2": None if contrib_sqmi is None else contrib_sqmi * _SQMI_TO_KM2,
        "source": url,
    }


def _parse_usgs_rdb(text: str) -> list[dict[str, str]]:
    data_lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if len(data_lines) < 2:
        return []
    header = data_lines[0].split("\t")
    rows: list[dict[str, str]] = []
    for line in data_lines[2:]:
        values = line.split("\t")
        if not values or len(values) < 2:
            continue
        rows.append({name: values[idx].strip() if idx < len(values) else "" for idx, name in enumerate(header)})
    return rows


def trace_mass_balance(
    run_dir: Path | str,
    *,
    basin_id: str | None = None,
    selected_outlet_gis_id: int | None = None,
    out_dir: Path | str | None = None,
    min_closure_ratio: float = 0.7,
    max_closure_ratio: float = 1.3,
) -> MassTraceReport:
    """Trace water generation and routed channel output for one run artifact.

    Args:
        run_dir: Basin run directory containing ``project/Scenarios/Default/TxtInOut``.
        basin_id: Optional basin identifier for reports.
        selected_outlet_gis_id: Optional outlet override. Defaults to metadata.
        out_dir: Directory for ``mass_trace.json``, ``mass_trace.csv``, and
            ``mass_trace.md``. Defaults to ``<run_dir>/reports``.
        min_closure_ratio: Lower acceptable terminal/basin-yield ratio.
        max_closure_ratio: Upper acceptable terminal/basin-yield ratio.

    Returns:
        A typed report. It is also written to disk when ``out_dir`` is not
        ``None``.
    """
    run = Path(run_dir).expanduser().resolve()
    txt = _resolve_txtinout(run)
    if not txt.is_dir():
        raise SwatBuilderInputError(f"TxtInOut directory not found: {txt}", txtinout_dir=str(txt))

    metadata = _load_json(run / "metadata.json")
    outlet_prov = _load_json(run / "outputs" / "outlet_provenance.json")
    basin = basin_id or str(metadata.get("usgs_id") or run.name)
    selected = (
        selected_outlet_gis_id
        or _safe_int(metadata.get("selected_outlet_gis_id"))
        or _safe_int(_lookup(outlet_prov, ("pinned_pass", "diagnostics", "selected_outlet_gis_id")))
        or _safe_int(_lookup(outlet_prov, ("pinned_pass", "diagnostics", "requested_outlet_gis_id")))
    )

    area_km2 = _model_area_km2(txt)
    basin_wb = _read_water_balance_optional(txt / "basin_wb_yr.txt") or _read_water_balance_optional(txt / "basin_wb_aa.txt")
    basin_rows = basin_wb.rows if basin_wb else []
    period = _period_from_rows(basin_rows)
    wb = _sum_basin_wb(basin_rows, area_km2)

    hru_depth_mm, hru_m3 = _weighted_wateryld_from_hru_lte(txt)
    lsu_m3 = _weighted_wateryld_from_lsu(txt)
    ru_m3 = _ru_outflow_m3(txt)
    basin_summary = _basin_summary_channel_trace(txt)

    terminal_ids = _terminal_ids_from_chandeg_con(txt)
    channel = _channel_trace(txt, selected, terminal_ids)
    water_yield_m3 = wb.get("wateryld_m3")
    routed_to_channel_m3 = wb.get("routed_to_channel_m3")
    expected_m3 = water_yield_m3
    closure_reference = "basin_wateryld_m3"
    terminal_m3 = channel.get("terminal_outflow_m3")
    all_terminal_m3 = channel.get("all_terminal_outflow_m3")
    basin_summary_m3 = basin_summary.get("basin_summary_outflow_m3")
    ru_ratio = _ratio(ru_m3, expected_m3)
    ratio = _ratio(terminal_m3, expected_m3)
    routed_ratio = _ratio(terminal_m3, routed_to_channel_m3)
    all_terminal_routed_ratio = _ratio(all_terminal_m3, routed_to_channel_m3)
    all_terminal_mass_ratio = _ratio(all_terminal_m3, expected_m3)
    selected_terminal_share = _ratio(terminal_m3, all_terminal_m3)
    summary_ratio = _ratio(basin_summary_m3, expected_m3)

    flags: list[str] = []
    notes: list[str] = []
    status: ClosureStatus = "insufficient_data"
    selected_is_terminal = selected in terminal_ids if selected is not None and terminal_ids else None

    terminal_context_flags = _terminal_context_flags(
        terminal_m3=terminal_m3,
        all_terminal_m3=all_terminal_m3,
        all_terminal_routed_ratio=all_terminal_routed_ratio,
        selected_terminal_share=selected_terminal_share,
        terminal_count=len(terminal_ids) if terminal_ids else None,
        max_closure_ratio=max_closure_ratio,
        min_closure_ratio=min_closure_ratio,
    )

    if expected_m3 is not None and expected_m3 <= 0:
        status = "fail_no_land_generation"
        flags.append("no_land_generation")
    elif expected_m3:
        if selected_is_terminal is False and (channel.get("all_terminal_outflow_m3") or 0.0) > 0:
            status = "fail_outlet_selection"
            flags.append("selected_outlet_is_not_terminal")
        elif terminal_m3 is None:
            flags.append("missing_expected_or_terminal_outflow")
        elif hru_m3 and hru_m3 > 0 and (channel.get("all_terminal_outflow_m3") or 0.0) <= 0:
            status = "fail_hru_to_channel"
            flags.append("hru_wateryld_without_terminal_channel_flow")
        elif _detect_lte_transfer_scale_bug(channel, hru_m3):
            status = "fail_lte_transfer_scale"
            flags.append("lte_hru_channel_transfer_scale_bug_detected")
        elif (channel.get("channel_inflow_m3") or 0.0) <= 0 and hru_m3 and hru_m3 > 0:
            status = "fail_channel_entry"
            flags.append("selected_channel_has_no_inflow")
        elif ratio is None or ratio < min_closure_ratio or ratio > max_closure_ratio:
            status = "fail_mass_closure"
            flags.append("terminal_outflow_not_consistent_with_basin_wateryld")
            flags.extend(
                _mass_closure_context_flags(
                    expected_m3=expected_m3,
                    terminal_m3=terminal_m3,
                    all_terminal_m3=channel.get("all_terminal_outflow_m3"),
                    channel_inflow_m3=channel.get("channel_inflow_m3"),
                    ru_outflow_m3=ru_m3,
                    routed_to_channel_ratio=routed_ratio,
                    terminal_count=len(terminal_ids) if terminal_ids else None,
                    max_closure_ratio=max_closure_ratio,
                    min_closure_ratio=min_closure_ratio,
                )
            )
        else:
            status = "pass"
    else:
        flags.append("missing_expected_or_terminal_outflow")

    for flag in terminal_context_flags:
        if flag not in flags:
            flags.append(flag)

    if selected_is_terminal is False:
        notes.append("Selected outlet is not terminal; terminal closure should use an audited terminal outlet.")
    if ratio is not None:
        notes.append(
            f"Closure ratio uses terminal_outflow_m3 / {closure_reference} with acceptable range "
            f"{min_closure_ratio:.2f}-{max_closure_ratio:.2f}."
        )
    if routed_ratio is not None:
        notes.append(
            "Routed-to-channel diagnostic ratio uses terminal_outflow_m3 / basin_routed_to_channel_m3 "
            f"= {routed_ratio:.6g}. This is retained as context only because current basin evidence shows "
            "the routed-to-channel terms are not consistently authoritative across runs."
        )
    if all_terminal_routed_ratio is not None:
        notes.append(
            "All-terminal routed-to-channel diagnostic ratio uses all_terminal_outflow_m3 / "
            f"basin_routed_to_channel_m3 = {all_terminal_routed_ratio:.6g}. This helps distinguish "
            "selected-gauge outlet closure from whole-generated-routing closure in multi-terminal basins."
        )
    if selected_terminal_share is not None:
        notes.append(
            "Selected-terminal flow share uses terminal_outflow_m3 / all_terminal_outflow_m3 "
            f"= {selected_terminal_share:.6g}; low values require terminal inventory evidence before "
            "the selected terminal can support basin-wide routing claims."
        )
    if "channel_inflow_exceeds_basin_wateryld" in flags:
        notes.append(
            "Selected-channel inflow exceeds basin water yield; inspect routing-unit to channel transfer, "
            "unit interpretation, and whether basin_wb wateryld is comparable to routed channel volume."
        )
    if "multiple_terminal_outlets_present" in flags:
        notes.append(
            "Multiple terminal outlets are present; verify whether the selected terminal represents the gauge basin "
            "or whether terminal inventory/aggregation is required before research-grade claims."
        )
    if "routing_unit_outflow_unit_semantics_suspect" in flags and ru_ratio is not None:
        notes.append(
            "Routing-unit output is orders of magnitude larger than basin water yield "
            f"(ru_outflow_m3 / basin_wateryld_m3 = {ru_ratio:.6g}). Treat ru_yr/ru_aa flow units "
            "as non-authoritative for closure until the SWAT+ output semantics or generation path is audited."
        )
    if summary_ratio is not None:
        notes.append(
            "Basin-summary ratio uses basin_summary_outflow_m3 / basin_wateryld_m3 "
            f"= {summary_ratio:.6g}; compare this against the selected-terminal ratio to distinguish "
            "basin-aggregate semantics from outlet-selection semantics."
        )
    if channel.get("source_note"):
        notes.append(str(channel["source_note"]))
    if basin_summary.get("source_note"):
        notes.append(str(basin_summary["source_note"]))
    if lsu_m3 is None:
        notes.append("LSU outflow unavailable or not area-weightable in this LTE artifact.")
    if ru_m3 is None:
        notes.append("RU outflow unavailable; LTE runs may route HRU-LTE objects directly to channels.")

    if "lte_hru_channel_transfer_scale_bug_detected" in flags:
        cin = _safe_float(channel.get("channel_inflow_m3"))
        ratio_bug = cin / hru_m3 if cin and hru_m3 and hru_m3 > 0 else 0.0
        notes.append(
            f"LTE hru_lte→channel transfer-scale bug detected: channel_inflow/hru_wateryld="
            f"{ratio_bug:.3f} (expected ~1.0). Evidence strongly indicates SWAT+ v2023.60.5.7 "
            "multiplies water yield by ×1000 instead of ×10 when computing channel inflow "
            "volume. Apply SWATPLUS_LTE_HRU_CHANNEL_SCALE_CORRECTION=0.01 to cancel."
        )

    report = MassTraceReport(
        basin_id=basin,
        run_dir=str(run),
        txtinout_dir=str(txt),
        generated_at=datetime.now(timezone.utc).isoformat(),
        simulation_period=period,
        evaluation_period=_evaluation_period(run / "outputs" / "alignment.csv"),
        model_area_km2=area_km2,
        precip_mm=wb.get("precip_mm"),
        et_mm=wb.get("et_mm"),
        basin_wateryld_mm=wb.get("wateryld_mm"),
        basin_routed_to_channel_mm=wb.get("routed_to_channel_mm"),
        surq_mm=wb.get("surq_mm"),
        latq_mm=wb.get("latq_mm"),
        gwq_mm=wb.get("gwq_mm"),
        basin_wateryld_m3=water_yield_m3,
        basin_routed_to_channel_m3=routed_to_channel_m3,
        routed_to_channel_closure_ratio=routed_ratio,
        all_terminal_routed_to_channel_closure_ratio=all_terminal_routed_ratio,
        all_terminal_mass_closure_ratio=all_terminal_mass_ratio,
        selected_terminal_fraction_of_all_terminal_flow=selected_terminal_share,
        closure_reference=closure_reference,
        basin_summary_outflow_m3=basin_summary_m3,
        hru_wateryld_mm=hru_depth_mm,
        hru_wateryld_m3=hru_m3,
        lsu_outflow_m3=lsu_m3,
        ru_outflow_m3=ru_m3,
        ru_outflow_to_basin_wateryld_ratio=ru_ratio,
        channel_inflow_m3=channel.get("channel_inflow_m3"),
        channel_outflow_m3=channel.get("channel_outflow_m3"),
        terminal_outflow_m3=terminal_m3,
        all_terminal_outflow_m3=channel.get("all_terminal_outflow_m3"),
        selected_outlet_gis_id=selected,
        selected_outlet_is_terminal=selected_is_terminal,
        terminal_outlet_count=len(terminal_ids) if terminal_ids else None,
        basin_wb_source_file=basin_wb.path.name if basin_wb else None,
        basin_wb_row_count=len(basin_rows) if basin_wb else None,
        basin_wb_years=_year_list(basin_rows),
        basin_summary_source_file=basin_summary.get("source_file"),
        basin_summary_row_count=basin_summary.get("row_count"),
        basin_summary_years=basin_summary.get("years") or [],
        channel_source_file=channel.get("source_file"),
        channel_flow_unit=channel.get("unit"),
        channel_row_count=channel.get("row_count"),
        channel_years=channel.get("years") or [],
        selected_channel_row_count=channel.get("selected_row_count"),
        selected_channel_years=channel.get("selected_years") or [],
        terminal_channel_row_count=channel.get("terminal_row_count"),
        terminal_channel_years=channel.get("terminal_years") or [],
        summary_closure_ratio=summary_ratio,
        mass_closure_ratio=ratio,
        closure_status=status,
        flags=flags,
        notes=notes,
        source_backed_alternatives=_routing_source_backed_alternatives(
            status=status,
            flags=flags,
            selected_is_terminal=selected_is_terminal,
            terminal_count=len(terminal_ids) if terminal_ids else None,
            channel_source_file=channel.get("source_file"),
            channel_flow_unit=channel.get("unit"),
            basin_wb_source_file=basin_wb.path.name if basin_wb else None,
        ),
    )
    report.recommended_probe_order = _routing_recommended_probe_order(report.source_backed_alternatives)

    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    _write_json(report, destination / "mass_trace.json")
    _write_csv(report, destination / "mass_trace.csv")
    (destination / "mass_trace.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def _mass_closure_context_flags(
    *,
    expected_m3: float | None,
    terminal_m3: float | None,
    all_terminal_m3: float | None,
    channel_inflow_m3: float | None,
    ru_outflow_m3: float | None,
    routed_to_channel_ratio: float | None,
    terminal_count: int | None,
    max_closure_ratio: float,
    min_closure_ratio: float,
) -> list[str]:
    flags: list[str] = []
    if not expected_m3 or expected_m3 <= 0:
        return flags
    if channel_inflow_m3 is not None and channel_inflow_m3 / expected_m3 > max_closure_ratio:
        flags.append("channel_inflow_exceeds_basin_wateryld")
    if ru_outflow_m3 is not None and ru_outflow_m3 / expected_m3 > 1000.0:
        flags.append("routing_unit_outflow_unit_semantics_suspect")
    if terminal_m3 is not None and terminal_m3 / expected_m3 > max_closure_ratio:
        flags.append("selected_terminal_outflow_exceeds_basin_wateryld")
    if terminal_m3 is not None and terminal_m3 / expected_m3 < min_closure_ratio:
        flags.append("selected_terminal_outflow_below_basin_wateryld")
    if all_terminal_m3 is not None and all_terminal_m3 / expected_m3 > max_closure_ratio:
        flags.append("all_terminal_outflow_exceeds_basin_wateryld")
    if routed_to_channel_ratio is not None and min_closure_ratio <= routed_to_channel_ratio <= max_closure_ratio:
        flags.append("routed_to_channel_reference_matches_terminal")
    if terminal_count is not None and terminal_count > 1:
        flags.append("multiple_terminal_outlets_present")
        if all_terminal_m3 is not None and terminal_m3 is not None and abs(all_terminal_m3 - terminal_m3) > 0.05 * expected_m3:
            flags.append("all_terminal_outflow_differs_from_selected_terminal")
    return flags


def _terminal_context_flags(
    *,
    terminal_m3: float | None,
    all_terminal_m3: float | None,
    all_terminal_routed_ratio: float | None,
    selected_terminal_share: float | None,
    terminal_count: int | None,
    max_closure_ratio: float,
    min_closure_ratio: float,
) -> list[str]:
    flags: list[str] = []
    if terminal_count is not None and terminal_count > 1:
        flags.append("multiple_terminal_outlets_present")
        if all_terminal_m3 is not None and terminal_m3 is not None and selected_terminal_share is not None:
            if selected_terminal_share < 0.9:
                flags.append("selected_terminal_partial_of_all_terminal_flow")
            if abs(all_terminal_m3 - terminal_m3) > 0.05 * max(all_terminal_m3, terminal_m3, 1e-9):
                flags.append("all_terminal_outflow_differs_from_selected_terminal")
    if all_terminal_routed_ratio is not None and min_closure_ratio <= all_terminal_routed_ratio <= max_closure_ratio:
        flags.append("all_terminal_routed_to_channel_reference_matches")
    return flags


def classify_terminal_scope_blocker(
    evidence: dict[str, Any],
    *,
    min_closure_ratio: float = 0.7,
    max_closure_ratio: float = 1.3,
) -> str | None:
    """Classify selected-vs-all terminal scope evidence without promoting it."""
    flags = {str(flag) for flag in evidence.get("flags", []) if flag}
    selected_share = _coerce_float(evidence.get("selected_terminal_fraction_of_all_terminal_flow"))
    all_routed_ratio = _coerce_float(evidence.get("all_terminal_routed_to_channel_closure_ratio"))
    all_mass_ratio = _coerce_float(evidence.get("all_terminal_mass_closure_ratio"))
    terminal_count = _coerce_int(evidence.get("terminal_outlet_count"))
    overlap_pair_count = _coerce_int(evidence.get("terminal_overlap_pair_count"))
    shared_area = _coerce_float(evidence.get("terminal_shared_upstream_area_km2"))

    selected_partial = (
        "selected_terminal_partial_of_all_terminal_flow" in flags
        or (selected_share is not None and selected_share < 0.9)
    )
    multiple_terminals = "multiple_terminal_outlets_present" in flags or (
        terminal_count is not None and terminal_count > 1
    )
    all_terminal_closes = (
        "all_terminal_routed_to_channel_reference_matches" in flags
        or _ratio_in_range(all_routed_ratio, min_closure_ratio, max_closure_ratio)
        or _ratio_in_range(all_mass_ratio, min_closure_ratio, max_closure_ratio)
    )
    terminal_overlap = (
        (overlap_pair_count is not None and overlap_pair_count > 0)
        or (shared_area is not None and shared_area > 0.01)
    )

    if terminal_overlap:
        return "terminal_topology_overlap"
    if str(evidence.get("status") or "").lower() == "passed" or str(evidence.get("closure_status") or "").lower() == "pass":
        if selected_partial:
            return "outlet_scope_volume_mismatch" if all_terminal_closes else "multi_terminal_volume_deficit"
        return None
    if selected_partial:
        return "outlet_scope_volume_mismatch" if all_terminal_closes else "multi_terminal_volume_deficit"
    if multiple_terminals and all_terminal_closes:
        return "multi_terminal_volume_deficit"
    return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        return None
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    try:
        if value is not None:
            return int(value)
    except (TypeError, ValueError):
        return None
    return None


def _ratio_in_range(value: float | None, min_value: float, max_value: float) -> bool:
    return value is not None and min_value <= value <= max_value


def _routing_source_backed_alternatives(
    *,
    status: ClosureStatus,
    flags: list[str],
    selected_is_terminal: bool | None,
    terminal_count: int | None,
    channel_source_file: str | None,
    channel_flow_unit: str | None,
    basin_wb_source_file: str | None,
) -> list[dict[str, Any]]:
    flagset = set(flags)
    terminal_scope_flags = {
        "multiple_terminal_outlets_present",
        "selected_terminal_partial_of_all_terminal_flow",
        "all_terminal_outflow_differs_from_selected_terminal",
        "all_terminal_routed_to_channel_reference_matches",
    }
    if status == "pass" and not (flagset & terminal_scope_flags):
        return []
    alternatives: list[dict[str, Any]] = []

    if "missing_expected_or_terminal_outflow" in flagset or status == "insufficient_data":
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "enable_authoritative_output_tables",
                "source": "SWAT+ output configuration prints water-balance and channel outputs through print.prt selections",
                "required_artifacts": ["basin_wb_yr.txt or basin_wb_aa.txt", "channel_sdmorph_day.txt or channel_sd_day.txt"],
                "fresh_output_required": True,
                "claim_impact": "routing_flow_gate_blocks_research_grade_until_required_outputs_exist",
                "rationale": "Mass closure cannot be evaluated without both basin water yield and selected terminal channel flow.",
            }
        )

    if selected_is_terminal is False or "selected_outlet_is_not_terminal" in flagset:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "repair_or_pin_terminal_outlet_selection",
                "source": "SWAT+ chandeg.con routing connections identify terminal channel objects; gauge evaluation must use an audited terminal or justified internal outlet",
                "required_artifacts": ["chandeg.con", "outlet_provenance.json", "reports/terminal_trace.json"],
                "fresh_output_required": True,
                "claim_impact": "outlet_and_routing_claims_blocked_until_selected_outlet_is_authoritative",
                "rationale": "The selected outlet is not a terminal channel in the generated routing table.",
            }
        )

    if "multiple_terminal_outlets_present" in flagset or (terminal_count is not None and terminal_count > 1):
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_terminal_inventory_and_aggregation",
                "source": "SWAT+ routing structures can contain multiple terminal outlets; terminal inventory is required before summing or selecting outlet flows",
                "required_artifacts": ["routing_graph.graphml", "chandeg.con", "reports/terminal_trace.json"],
                "fresh_output_required": False,
                "claim_impact": "research_grade_routing_claim_blocked_until_terminal_topology_is_explained",
                "rationale": "Multiple terminal outlets are present, so selected-terminal and all-terminal closure can represent different basin footprints.",
            }
        )

    if "routing_unit_outflow_unit_semantics_suspect" in flagset:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "treat_routing_unit_outputs_as_non_authoritative_until_unit_semantics_are_audited",
                "source": "SWAT+ routing-unit documentation describes routing units as collectors of hydrographs; current run evidence shows ru output orders of magnitude above basin water yield",
                "required_artifacts": ["ru_yr.txt or ru_aa.txt", "basin_wb_yr.txt", "channel_sdmorph_day.txt"],
                "fresh_output_required": False,
                "claim_impact": "ru_outputs_cannot_drive_research_grade_mass_closure",
                "rationale": "Routing-unit output volume is not comparable to basin water yield under current parser/generation assumptions.",
            }
        )

    if {"channel_inflow_exceeds_basin_wateryld", "selected_terminal_outflow_exceeds_basin_wateryld", "all_terminal_outflow_exceeds_basin_wateryld"} & flagset:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "cross_check_channel_rate_units_and_basin_yield_semantics",
                "source": "SWAT+ channel daily flow outputs are commonly interpreted as m3/s rates, while basin water yield is a generated-depth water-balance term rather than guaranteed routed outlet flow",
                "required_artifacts": [channel_source_file or "channel_sdmorph_day.txt", basin_wb_source_file or "basin_wb_yr.txt", "basin_sd_chamorph_yr.txt"],
                "fresh_output_required": False,
                "claim_impact": "routing_flow_gate_blocks_research_grade_until_channel_and_basin_semantics_are_reconciled",
                "rationale": f"Channel source `{channel_source_file or 'unknown'}` with unit `{channel_flow_unit or 'unknown'}` is outside closure tolerance against basin water yield.",
            }
        )
    if "routed_to_channel_reference_matches_terminal" in flagset:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_basin_wateryld_vs_routed_to_channel_semantics",
                "source": "SWAT+ basin water-balance output includes generic wateryld and explicit channel-receiving components such as surq_cha and latq_cha",
                "required_artifacts": ["basin_wb_yr.txt", "channel_sdmorph_day.txt", "routing_flow_gates.json"],
                "fresh_output_required": False,
                "claim_impact": "routing_flow_gate_remains_blocking_until_reference_semantics_are_resolved",
                "rationale": "Terminal channel flow matches routed-to-channel components but not generic basin water yield; this is retained as a diagnostic ambiguity, not a pass.",
            }
        )
    if "all_terminal_routed_to_channel_reference_matches" in flagset:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_all_terminal_routed_to_channel_semantics",
                "source": "SWAT+ basin water-balance output documents channel-receiving components, while channel output documents flow leaving channels; all-terminal comparison is needed when generated routing has multiple terminals",
                "required_artifacts": ["basin_wb_yr.txt", "channel_sdmorph_day.txt", "reports/terminal_trace.json"],
                "fresh_output_required": False,
                "claim_impact": "multi_terminal_routing_claims_remain_blocked_until_selected_vs_all_terminal_scope_is_explained",
                "rationale": "All terminal outflow matches routed-to-channel components; selected terminal scope still needs outlet/terminal inventory evidence.",
            }
        )

    if status == "fail_hru_to_channel" or "hru_wateryld_without_terminal_channel_flow" in flagset:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_hru_lsu_routing_transfer_to_channels",
                "source": "SWAT+ routing connects generated landscape hydrographs through routing units and channels; nonzero landscape generation with no channel flow is a transfer-path defect",
                "required_artifacts": ["hru-lte_wb_*.txt or hru_wb_*.txt", "rout_unit.def", "channel output"],
                "fresh_output_required": True,
                "claim_impact": "calibration_and_routing_claims_blocked_until_land_to_channel_transfer_exists",
                "rationale": "Landscape water yield exists but does not reach terminal channel flow.",
            }
        )

    if status == "fail_lte_transfer_scale" or "lte_hru_channel_transfer_scale_bug_detected" in flagset:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "apply_documented_lte_hru_channel_scale_correction",
                "source": "Project-validated SWAT+ rev 60.5.7 LTE transfer-scale diagnostic",
                "required_artifacts": ["hru-lte water yield", "channel inflow", "engine revision metadata"],
                "fresh_output_required": True,
                "claim_impact": "routing_flow_gate_blocks_research_grade_until_corrected_engine_rerun_passes",
                "rationale": "Detected the known LTE HRU-to-channel scale defect.",
            }
        )

    if not alternatives:
        alternatives.append(
            {
                "rank": 1,
                "option": "retain_routing_blocker_and_collect_mass_trace_context",
                "source": "Project routing-flow gate policy",
                "required_artifacts": ["mass_trace.json", "routing_flow_gates.json", "terminal_trace.json"],
                "fresh_output_required": False,
                "claim_impact": "routing_flow_gate_blocks_research_grade",
                "rationale": f"Closure status `{status}` requires additional context before research-grade claims.",
            }
        )
    return alternatives


def _routing_recommended_probe_order(alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for alt in alternatives:
        option = alt.get("option")
        artifacts = alt.get("required_artifacts")
        if not option or not isinstance(artifacts, list) or not artifacts:
            continue
        probes.append(
            {
                "rank": alt.get("rank"),
                "diagnostic": option,
                "required_artifacts": artifacts,
                "fresh_output_required": bool(alt.get("fresh_output_required")),
                "claim_impact": alt.get("claim_impact"),
            }
        )
    return probes


def trace_terminal_inventory(
    run_dir: Path | str,
    *,
    basin_id: str | None = None,
    selected_outlet_gis_id: int | None = None,
    out_dir: Path | str | None = None,
    fetch_usgs_site_area: bool = False,
) -> TerminalTraceReport:
    """Inventory terminal channels and classify the outlet failure mode."""
    run = Path(run_dir).expanduser().resolve()
    txt = _resolve_txtinout(run)
    if not txt.is_dir():
        raise SwatBuilderInputError(f"TxtInOut directory not found: {txt}", txtinout_dir=str(txt))

    artifact_root = _routing_artifact_root(run, txt)
    metadata = _load_json(artifact_root / "metadata.json")
    outlet_prov = _load_json(artifact_root / "outputs" / "outlet_provenance.json")
    audit = _load_json(artifact_root / "reports" / "outlet_audit" / "outlet_audit.json")
    snap = _load_json(artifact_root / "delin" / "snap_diagnostic.json")
    validation = _load_json(artifact_root / "delin" / "validation_result.json")
    basin = basin_id or str(metadata.get("usgs_id") or artifact_root.name)
    basin_wb = _read_water_balance_optional(txt / "basin_wb_yr.txt") or _read_water_balance_optional(txt / "basin_wb_aa.txt")
    basin_rows = basin_wb.rows if basin_wb else []
    period = _period_from_rows(basin_rows)
    selected = (
        selected_outlet_gis_id
        or _safe_int(metadata.get("selected_outlet_gis_id"))
        or _safe_int(_lookup(outlet_prov, ("pinned_pass", "diagnostics", "selected_outlet_gis_id")))
        or _safe_int(_lookup(outlet_prov, ("selection_pass", "diagnostics", "selected_outlet_gis_id")))
    )
    selected_reason = metadata.get("outlet_selection_reason") or _lookup(
        outlet_prov, ("pinned_pass", "diagnostics", "outlet_selection_reason")
    ) or _lookup(outlet_prov, ("selection_pass", "diagnostics", "outlet_selection_reason"))

    basin_nldi_area = _first_float(snap.get("expected_area_km2"), validation.get("reference_area_km2"))
    delineated_area = _first_float(snap.get("generated_area_km2"), validation.get("delineated_area_km2"))
    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    usgs_site_metadata = _load_json(destination / "usgs_site_metadata.json")
    if fetch_usgs_site_area and not usgs_site_metadata and str(basin).isdigit():
        usgs_site_metadata = fetch_usgs_site_metadata(str(basin))
        (destination / "usgs_site_metadata.json").write_text(
            json.dumps(usgs_site_metadata, indent=2) + "\n",
            encoding="utf-8",
        )
    usgs_drain_area_sqmi = _safe_float(usgs_site_metadata.get("drain_area_va_sqmi"))
    usgs_drain_area_km2 = _safe_float(usgs_site_metadata.get("drain_area_km2"))
    area_map = _subbasin_area_map(artifact_root)
    hru_area = _hru_area_km2(txt)
    if delineated_area is None and area_map:
        delineated_area = sum(area_map.values())

    G = _chandeg_routing_graph(txt)
    if G.number_of_nodes() == 0:
        G = nx.read_graphml(artifact_root / "delin" / "routing_graph.graphml")
    terminals = sorted(int(n) for n in G.nodes if G.out_degree(n) == 0)
    gauge_lat, gauge_lon, gauge_coordinate_source = _gauge_coordinates_from_artifacts(
        artifact_root,
        metadata=metadata,
        audit=audit,
        snap=snap,
        validation=validation,
    )
    terminal_rows = _terminal_inventory_rows(
        txt,
        G,
        terminals,
        area_map,
        hru_area_map=_hru_area_map(txt),
        gauge_lat=gauge_lat,
        gauge_lon=gauge_lon,
        selected_outlet_gis_id=selected,
    )
    inventoried_terminal_ids = {row.terminal_gis_id for row in terminal_rows}
    missing_terminal_ids = [gid for gid in terminals if gid not in inventoried_terminal_ids]
    orphan_terminal_ids = _orphan_terminal_ids(G, missing_terminal_ids, area_map)
    material_missing_terminal_ids = [gid for gid in missing_terminal_ids if gid not in set(orphan_terminal_ids)]
    missing_terminal_area = _union_upstream_area_km2(G, missing_terminal_ids, area_map) if missing_terminal_ids else None
    effective_terminal_count = len([gid for gid in terminals if gid not in set(orphan_terminal_ids)])
    all_terminal_union = _union_upstream_area_km2(G, terminals, area_map)
    sum_terminal_area = sum(r.upstream_area_km2 or 0.0 for r in terminal_rows)
    shared_area = max(0.0, sum_terminal_area - all_terminal_union)
    terminal_overlap_pairs = _terminal_overlap_pairs(G, terminal_rows, area_map)

    selected_row = next((r for r in terminal_rows if r.terminal_gis_id == selected), None)
    selected_area = selected_row.upstream_area_km2 if selected_row else None
    selected_is_terminal = selected in terminals if selected is not None else None
    selected_distance = selected_row.distance_to_usgs_outlet_m if selected_row else None

    failure_class = _classify_terminal_failure(
        selected_row=selected_row,
        terminal_rows=terminal_rows,
        terminal_count=effective_terminal_count,
        material_missing_terminal_count=len(material_missing_terminal_ids),
        delineated_area_km2=delineated_area,
        all_terminal_union_km2=all_terminal_union,
        shared_area_km2=shared_area,
    )
    notes: list[str] = []
    if material_missing_terminal_ids:
        notes.append(
            "Routing graph terminal IDs missing from chandeg.con: "
            + ", ".join(str(gid) for gid in material_missing_terminal_ids)
            + ". This indicates a generated topology/SWAT+ channel table mismatch."
        )
    if orphan_terminal_ids:
        notes.append(
            "Routing graph orphan terminal IDs ignored for material terminal mismatch classification: "
            + ", ".join(str(gid) for gid in orphan_terminal_ids)
            + ". These graph nodes have no upstream graph and no mapped subbasin area."
        )
    if terminal_rows and selected_row is not None:
        if selected_row.is_largest_flow_terminal and selected_row.is_largest_area_terminal:
            notes.append("Selected terminal is the largest-flow and largest-area inventoried terminal.")
        elif selected_row.is_nearest_terminal:
            notes.append("Selected terminal is nearest to the gauge but is not the largest-flow/largest-area terminal.")
        else:
            notes.append("Selected terminal is neither nearest-to-gauge nor the largest-flow/largest-area terminal.")
    if gauge_lat is not None and gauge_lon is not None:
        notes.append(f"Terminal distance ranking used gauge coordinates from {gauge_coordinate_source}.")
    else:
        notes.append("Gauge coordinates unavailable; nearest-terminal ranking was not computed.")
    if shared_area > 0:
        notes.append(
            "Multiple terminal outlets overlap upstream area, so terminal aggregation is not a simple sum in this topology."
        )
    if terminal_overlap_pairs:
        worst = terminal_overlap_pairs[0]
        notes.append(
            "Largest pairwise terminal overlap is "
            f"{worst.shared_upstream_area_km2:.3f} km2 between terminal "
            f"{worst.terminal_a_gis_id} and {worst.terminal_b_gis_id}."
        )
    if selected_row:
        notes.append(
            f"Selected terminal share of all-terminal outflow is "
            f"{(selected_row.percent_of_all_terminal_outflow or 0.0):.3%}."
        )
    area_scope = classify_terminal_area_scope(
        selected_terminal_fraction_of_nldi_area=_ratio(selected_area, basin_nldi_area),
        all_terminal_fraction_of_nldi_area=_ratio(all_terminal_union, basin_nldi_area),
        selected_terminal_fraction_of_delineated_area=_ratio(selected_area, delineated_area),
        all_terminal_fraction_of_delineated_area=_ratio(all_terminal_union, delineated_area),
    )
    authority_area = classify_terminal_authority_area(
        selected_terminal_fraction_of_usgs_site_area=_ratio(selected_area, usgs_drain_area_km2),
        all_terminal_fraction_of_usgs_site_area=_ratio(all_terminal_union, usgs_drain_area_km2),
        selected_terminal_fraction_of_nldi_area=_ratio(selected_area, basin_nldi_area),
        all_terminal_fraction_of_nldi_area=_ratio(all_terminal_union, basin_nldi_area),
    )
    nearest_row = next((r for r in terminal_rows if r.is_nearest_terminal), None)
    outlet_conflict = classify_terminal_outlet_conflict(
        selected_row=selected_row,
        nearest_row=nearest_row,
        gauge_coordinate_source=gauge_coordinate_source,
    )

    report = TerminalTraceReport(
        basin_id=basin,
        run_dir=str(artifact_root),
        txtinout_dir=str(txt),
        generated_at=datetime.now(timezone.utc).isoformat(),
        simulation_period=period,
        selected_outlet_gis_id=selected,
        selected_outlet_reason=selected_reason,
        selected_outlet_is_terminal=selected_is_terminal,
        selected_outlet_distance_to_gauge_m=selected_distance,
        gauge_lat=gauge_lat,
        gauge_lon=gauge_lon,
        gauge_coordinate_source=gauge_coordinate_source,
        terminal_count=len(terminals),
        terminal_inventory_count=len(terminal_rows),
        missing_terminal_gis_ids=missing_terminal_ids,
        orphan_terminal_gis_ids=orphan_terminal_ids,
        material_missing_terminal_gis_ids=material_missing_terminal_ids,
        missing_terminal_upstream_area_km2=missing_terminal_area,
        basin_nldi_area_km2=basin_nldi_area,
        usgs_site_drainage_area_sqmi=usgs_drain_area_sqmi,
        usgs_site_drainage_area_km2=usgs_drain_area_km2,
        usgs_site_drainage_area_source=(
            str(usgs_site_metadata.get("source")) if usgs_site_metadata.get("source") else None
        ),
        usgs_site_metadata_path=str(destination / "usgs_site_metadata.json")
        if (destination / "usgs_site_metadata.json").is_file()
        else None,
        delineated_area_km2=delineated_area,
        hru_area_km2=hru_area,
        selected_terminal_upstream_area_km2=selected_area,
        all_terminal_upstream_area_km2=all_terminal_union,
        sum_terminal_upstream_area_km2=sum_terminal_area,
        shared_upstream_area_km2=shared_area,
        terminal_overlap_pairs=terminal_overlap_pairs,
        selected_terminal_fraction_of_nldi_area=_ratio(selected_area, basin_nldi_area),
        selected_terminal_fraction_of_usgs_site_area=_ratio(selected_area, usgs_drain_area_km2),
        all_terminal_fraction_of_nldi_area=_ratio(all_terminal_union, basin_nldi_area),
        all_terminal_fraction_of_usgs_site_area=_ratio(all_terminal_union, usgs_drain_area_km2),
        delineated_fraction_of_nldi_area=_ratio(delineated_area, basin_nldi_area),
        selected_terminal_fraction_of_delineated_area=_ratio(selected_area, delineated_area),
        all_terminal_fraction_of_delineated_area=_ratio(all_terminal_union, delineated_area),
        terminal_area_scope_class=str(area_scope.get("class")),
        terminal_area_scope_flags=[
            str(flag) for flag in area_scope.get("flags", []) if isinstance(flag, str) and flag
        ],
        terminal_area_scope_claim_impact=str(area_scope.get("claim_impact")),
        terminal_authority_area_check=authority_area,
        terminal_outlet_conflict_class=str(outlet_conflict.get("class")),
        terminal_outlet_conflict_flags=[
            str(flag) for flag in outlet_conflict.get("flags", []) if isinstance(flag, str) and flag
        ],
        terminal_outlet_conflict_claim_impact=str(outlet_conflict.get("claim_impact")),
        failure_class=failure_class,
        terminal_inventory=terminal_rows,
        notes=notes,
    )
    report.source_backed_alternatives = _terminal_source_backed_alternatives(report)
    report.recommended_probe_order = _terminal_recommended_probe_order(report.source_backed_alternatives)
    report.terminal_virtual_outlet_candidate = _terminal_virtual_outlet_candidate(report)
    if report.terminal_virtual_outlet_candidate.get("available") is True:
        candidate_path = destination / "terminal_virtual_outlet_candidate.json"
        candidate_path.write_text(
            json.dumps(report.terminal_virtual_outlet_candidate, indent=2) + "\n",
            encoding="utf-8",
        )
        report.terminal_virtual_outlet_candidate_path = str(candidate_path)
        (destination / "terminal_virtual_outlet_candidate.md").write_text(
            _render_terminal_virtual_outlet_candidate_markdown(report.terminal_virtual_outlet_candidate),
            encoding="utf-8",
        )

    _write_json_generic(report, destination / "terminal_trace.json")
    (destination / "terminal_trace.md").write_text(_render_terminal_markdown(report), encoding="utf-8")
    return report


def _resolve_txtinout(run: Path) -> Path:
    if run.is_dir() and (run / "file.cio").is_file():
        return run
    return run / "project" / "Scenarios" / "Default" / "TxtInOut"


def _routing_artifact_root(run: Path, txt: Path) -> Path:
    if (run / "metadata.json").is_file() and (run / "delin").is_dir():
        return run
    for parent in [txt.parent, *txt.parents]:
        if (parent / "metadata.json").is_file() and (parent / "delin").is_dir():
            return parent
    return run


def _read_optional(path: Path) -> OutputTable | None:
    if not path.is_file():
        return None
    return read_output_file(path)


def _read_water_balance_optional(path: Path) -> OutputTable | None:
    """Read SWAT+ water-balance output for routing evidence.

    SWAT+ text water-balance rows can omit trailing blank/text bookkeeping
    fields such as ``mgt_ops`` while still carrying the hydrologic columns
    needed for mass tracing. Keep the generic parser strict, but tolerate
    those trailing water-balance quirks here because this gate only consumes
    early numeric water-balance fields.
    """
    if not path.is_file():
        return None
    try:
        return read_output_file(path)
    except SwatBuilderExternalError:
        return _read_water_balance_relaxed(path)


def _read_water_balance_relaxed(path: Path) -> OutputTable:
    p = path.expanduser().resolve()
    raw_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(raw_lines) < 2:
        raise SwatBuilderExternalError(
            f"SWAT+ water-balance output is missing a header: {p}", path=str(p)
        )

    title = raw_lines[0].rstrip()
    header_idx = next((i for i in range(1, len(raw_lines)) if raw_lines[i].strip()), None)
    if header_idx is None:
        raise SwatBuilderExternalError(
            f"SWAT+ water-balance output has no header/data: {p}", path=str(p)
        )
    columns = raw_lines[header_idx].split()
    data_start = header_idx + 1
    units: list[str] = []
    while data_start < len(raw_lines) and not raw_lines[data_start].strip():
        data_start += 1
    if data_start < len(raw_lines):
        candidate = raw_lines[data_start].split()
        if candidate and all(_safe_float(tok) is None for tok in candidate):
            units = [""] * max(0, len(columns) - len(candidate)) + candidate
            data_start += 1

    rows: list[dict[str, Any]] = []
    for idx in range(data_start, len(raw_lines)):
        tokens = raw_lines[idx].split()
        if not tokens:
            continue
        row = _parse_water_balance_row_relaxed(columns, tokens, path=p, line_no=idx + 1)
        if row:
            rows.append(row)
    return OutputTable(path=p, title=title, columns=columns, units=units, rows=rows)


def _parse_water_balance_row_relaxed(
    columns: list[str],
    tokens: list[str],
    *,
    path: Path,
    line_no: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for idx, col in enumerate(columns):
        if idx >= len(tokens):
            row[col] = None
            continue
        tok = tokens[idx]
        if col in {"jday", "mon", "day", "yr", "unit", "gis_id"}:
            value = _safe_int(tok)
            if value is None:
                raise SwatBuilderExternalError(
                    f"SWAT+ water-balance output: expected int for {col!r} at {path}:{line_no}, got {tok!r}",
                    path=str(path),
                    line_no=line_no,
                    column=col,
                    token=tok,
                )
            row[col] = value
        elif col == "name":
            row[col] = tok
        else:
            value = _safe_float(tok)
            row[col] = value
            if value is None:
                # Remaining tokens are bookkeeping text (for example mgt_ops);
                # hydrologic mass-trace fields precede this in SWAT+ WB output.
                for rest in columns[idx + 1 :]:
                    row.setdefault(rest, None)
                break
    return row


def _read_routing_unit_optional(path: Path) -> OutputTable | None:
    if not path.is_file():
        return None
    try:
        return read_output_file(path)
    except SwatBuilderExternalError:
        return _read_routing_unit_relaxed(path)


def _read_routing_unit_relaxed(path: Path) -> OutputTable:
    p = path.expanduser().resolve()
    raw_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(raw_lines) < 2:
        raise SwatBuilderExternalError(
            f"SWAT+ routing-unit output is missing a header: {p}", path=str(p)
        )
    title = raw_lines[0].rstrip()
    header_idx = next((i for i in range(1, len(raw_lines)) if raw_lines[i].strip()), None)
    if header_idx is None:
        raise SwatBuilderExternalError(
            f"SWAT+ routing-unit output has no header/data: {p}", path=str(p)
        )
    columns = raw_lines[header_idx].split()
    data_start = header_idx + 1
    units: list[str] = []
    while data_start < len(raw_lines) and not raw_lines[data_start].strip():
        data_start += 1
    if data_start < len(raw_lines):
        candidate = raw_lines[data_start].split()
        if candidate and all(_safe_float(tok) is None for tok in candidate):
            units = [""] * max(0, len(columns) - len(candidate)) + candidate
            data_start += 1

    rows: list[dict[str, Any]] = []
    string_columns = {"name", "type"}
    int_columns = {"jday", "mon", "day", "yr", "unit", "gis_id"}
    for idx in range(data_start, len(raw_lines)):
        tokens = raw_lines[idx].split()
        if not tokens:
            continue
        if len(tokens) < len(columns):
            tokens = tokens + [""] * (len(columns) - len(tokens))
        row: dict[str, Any] = {}
        for col, tok in zip(columns, tokens):
            if col in string_columns:
                row[col] = tok
            elif col in int_columns:
                row[col] = _safe_int(tok)
            else:
                row[col] = _safe_float(tok)
        rows.append(row)
    return OutputTable(path=p, title=title, columns=columns, units=units, rows=rows)


def _model_area_km2(txt: Path) -> float | None:
    object_cnt = txt / "object.cnt"
    if object_cnt.is_file():
        for line in object_cnt.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] not in {"name", "object.cnt:"}:
                area_ha = _safe_float(parts[1])
                if area_ha and area_ha > 0:
                    return area_ha / 100.0
    hru_areas = _area_map(txt / "hru-lte.hru")
    if hru_areas:
        return sum(hru_areas.values()) / 100.0
    return None


def _sum_basin_wb(rows: list[dict[str, Any]], area_km2: float | None) -> dict[str, float | None]:
    fields = {
        "precip_mm": "precip",
        "et_mm": "et",
        "wateryld_mm": "wateryld",
        "surq_mm": "surq_gen",
        "latq_mm": "latq",
        "gwq_mm": "gwtranq",
    }
    out: dict[str, float | None] = {}
    for key, col in fields.items():
        vals = [_safe_float(row.get(col)) for row in rows]
        if key == "gwq_mm" and not any(v is not None for v in vals):
            vals = [_safe_float(row.get("gwsoilq")) for row in rows]
        vals = [v for v in vals if v is not None]
        out[key] = sum(vals) if vals else None
    routed_terms: list[float] = []
    for col in ("surq_cha", "latq_cha", "satex_chan"):
        vals = [_safe_float(row.get(col)) for row in rows]
        routed_terms.extend(v for v in vals if v is not None)
    out["routed_to_channel_mm"] = sum(routed_terms) if routed_terms else None
    out["wateryld_m3"] = _depth_mm_to_m3(out.get("wateryld_mm"), area_km2)
    out["routed_to_channel_m3"] = _depth_mm_to_m3(out.get("routed_to_channel_mm"), area_km2)
    return out


def _weighted_wateryld_from_hru_lte(txt: Path) -> tuple[float | None, float | None]:
    table = _read_water_balance_optional(txt / "hru-lte_wb_yr.txt") or _read_water_balance_optional(txt / "hru_wb_yr.txt")
    areas = _area_map(txt / "hru-lte.hru")
    if table is None or not areas:
        return None, None
    return _weighted_depth_volume(table.rows, areas, "wateryld")


def _weighted_wateryld_from_lsu(txt: Path) -> float | None:
    table = _read_water_balance_optional(txt / "lsunit_wb_yr.txt") or _read_water_balance_optional(txt / "lsunit_wb_aa.txt")
    areas = _area_map(txt / "lsunit.ele") or _area_map(txt / "lsunit.con")
    if table is None or not areas:
        return None
    _depth, volume = _weighted_depth_volume(table.rows, areas, "wateryld")
    return volume


def _subbasin_area_map(run: Path) -> dict[int, float]:
    path = run / "delin" / "shapes" / "subbasins.gpkg"
    if not path.is_file():
        return {}
    try:
        import geopandas as gpd
    except Exception:
        return {}
    gdf = gpd.read_file(path)
    if "sub_id" not in gdf.columns or "area_km2" not in gdf.columns:
        return {}
    return {int(row.sub_id): float(row.area_km2) for row in gdf.itertuples(index=False)}


def _gauge_coordinates_from_artifacts(
    run: Path,
    *,
    metadata: dict[str, Any],
    audit: dict[str, Any],
    snap: dict[str, Any],
    validation: dict[str, Any],
) -> tuple[float | None, float | None, str | None]:
    candidates: list[tuple[str, Any, Any]] = [
        ("outlet_audit", audit.get("gauge_lat"), audit.get("gauge_lon")),
        ("metadata.gauge", metadata.get("gauge_lat"), metadata.get("gauge_lon")),
        ("metadata.outlet", metadata.get("outlet_lat"), metadata.get("outlet_lon")),
        ("validation_result.gauge", validation.get("gauge_lat"), validation.get("gauge_lon")),
        ("validation_result.outlet", validation.get("outlet_lat"), validation.get("outlet_lon")),
        (
            "snap_diagnostic.outlet_raw",
            _lookup(snap, ("outlet_raw", "lat")),
            _lookup(snap, ("outlet_raw", "lon")),
        ),
        (
            "snap_diagnostic.outlet_snapped",
            _lookup(snap, ("outlet_snapped", "lat")),
            _lookup(snap, ("outlet_snapped", "lon")),
        ),
    ]
    for source, lat_value, lon_value in candidates:
        lat = _safe_float(lat_value)
        lon = _safe_float(lon_value)
        if lat is not None and lon is not None:
            return lat, lon, source

    for source, path in (
        ("delin/shapes/outlets.gpkg", run / "delin" / "shapes" / "outlets.gpkg"),
        ("delin/shapes/outlet_raw.shp", run / "delin" / "shapes" / "outlet_raw.shp"),
        ("delin/shapes/outlet_snapped.shp", run / "delin" / "shapes" / "outlet_snapped.shp"),
    ):
        lat_lon = _point_lat_lon_from_vector(path)
        if lat_lon is not None:
            return lat_lon[0], lat_lon[1], source
    return None, None, None


def _point_lat_lon_from_vector(path: Path) -> tuple[float, float] | None:
    if not path.is_file():
        return None
    try:
        import geopandas as gpd
    except Exception:
        return None
    try:
        gdf = gpd.read_file(path)
    except Exception:
        return None
    if gdf.empty:
        return None

    row = gdf.iloc[0]
    lat = _safe_float(row.get("lat")) if hasattr(row, "get") else None
    lon = _safe_float(row.get("lon")) if hasattr(row, "get") else None
    if lat is not None and lon is not None:
        return lat, lon

    geom = row.geometry
    if geom is None or geom.is_empty:
        return None
    try:
        point_gdf = gdf.iloc[[0]]
        if point_gdf.crs is not None and str(point_gdf.crs).upper() not in {"EPSG:4326", "WGS84"}:
            point_gdf = point_gdf.to_crs(4326)
        point = point_gdf.geometry.iloc[0]
    except Exception:
        point = geom
    if point is None or point.is_empty:
        return None
    centroid = point.centroid
    return float(centroid.y), float(centroid.x)


def _hru_area_map(txt: Path) -> dict[int, float]:
    for name in ("hru-lte.hru", "hru.hru"):
        path = txt / name
        if not path.is_file():
            continue
        try:
            df = pd.read_csv(path, sep=r"\s+", skiprows=1, engine="python")
        except Exception:
            continue
        if "id" in df.columns and "area" in df.columns:
            out: dict[int, float] = {}
            for _, row in df.iterrows():
                obj_id = _safe_int(row.get("id"))
                area = _safe_float(row.get("area"))
                if obj_id is None or area is None:
                    continue
                out[obj_id] = area / 100.0
            return out
    return {}


def _hru_area_km2(txt: Path) -> float | None:
    areas = _hru_area_map(txt)
    if not areas:
        return None
    return sum(areas.values())


def _chandeg_routing_graph(txt: Path) -> nx.DiGraph:
    """Return the actual emitted SWAT+ channel routing graph keyed by GIS ID.

    The delineation graph can retain alternate downstream candidates. SWAT+
    claim evidence must follow the single routing table that was actually run.
    """
    path = txt / "chandeg.con"
    G: nx.DiGraph = nx.DiGraph()
    if not path.is_file():
        return G

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header_idx: int | None = None
    col_idx: dict[str, int] | None = None
    for idx, line in enumerate(lines):
        parts = line.split()
        if {"id", "gis_id", "out_tot"}.issubset(parts):
            header_idx = idx
            col_idx = {name: pos for pos, name in enumerate(parts)}
            break

    rows: list[list[str]] = []
    internal_to_gis: dict[int, int] = {}
    if header_idx is not None and col_idx is not None:
        id_idx = col_idx["id"]
        gis_idx = col_idx["gis_id"]
        for line in lines[header_idx + 1:]:
            parts = line.split()
            if not parts:
                continue
            internal_id = _safe_int(parts[id_idx] if len(parts) > id_idx else None)
            gis_id = _safe_int(parts[gis_idx] if len(parts) > gis_idx else None)
            if internal_id is None or gis_id is None:
                continue
            rows.append(parts)
            internal_to_gis[internal_id] = gis_id
            G.add_node(str(gis_id))
    else:
        for line in lines[2:]:
            parts = line.split()
            if len(parts) < 13:
                continue
            internal_id = _safe_int(parts[0])
            gis_id = _safe_int(parts[2])
            if internal_id is None or gis_id is None:
                continue
            rows.append(parts)
            internal_to_gis[internal_id] = gis_id
            G.add_node(str(gis_id))

    if col_idx is None:
        id_idx = 0
        gis_idx = 2
        out_tot_idx = 12
        route_start_idx = 13
    else:
        id_idx = col_idx["id"]
        gis_idx = col_idx["gis_id"]
        out_tot_idx = col_idx["out_tot"]
        route_start_idx = col_idx.get("obj_typ", out_tot_idx + 1)

    for parts in rows:
        gis_id = _safe_int(parts[gis_idx] if len(parts) > gis_idx else None)
        out_tot = _safe_int(parts[out_tot_idx] if len(parts) > out_tot_idx else None) or 0
        if gis_id is None or out_tot <= 0:
            continue
        for idx in range(route_start_idx, min(len(parts), route_start_idx + out_tot * 4), 4):
            group = parts[idx : idx + 4]
            if len(group) != 4:
                continue
            obj_typ, obj_id = group[0], _safe_int(group[1])
            if obj_typ != "sdc" or obj_id is None:
                continue
            target_gis = internal_to_gis.get(obj_id, obj_id)
            if target_gis != gis_id:
                G.add_edge(str(gis_id), str(target_gis))
    return G


def _terminal_inventory_rows(
    txt: Path,
    graph: nx.DiGraph,
    terminals: list[int],
    area_map: dict[int, float],
    *,
    hru_area_map: dict[int, float],
    gauge_lat: float | None,
    gauge_lon: float | None,
    selected_outlet_gis_id: int | None,
) -> list[TerminalTraceRow]:
    by_gid = _chandeg_records_by_gis(txt)
    source = _read_optional(txt / "channel_sdmorph_day.txt") or _read_optional(txt / "channel_sd_day.txt") or _read_optional(txt / "channel_sd_yr.txt")
    source_unit = _unit_for_column(source, "flo_out") if source is not None else None
    all_terminal_outflow = 0.0
    out_by_terminal: dict[int, float] = {}
    if source is not None:
        for gid in terminals:
            rows = [r for r in source.rows if _safe_int(r.get("gis_id")) == gid]
            out = sum(_flow_value_to_m3(r.get("flo_out"), source_unit, r) or 0.0 for r in rows)
            out_by_terminal[gid] = out
        all_terminal_outflow = sum(out_by_terminal.values())
    selected = selected_outlet_gis_id
    inventories: list[TerminalTraceRow] = []
    largest_flow = max(out_by_terminal, key=out_by_terminal.get) if out_by_terminal else None
    largest_area: int | None = None
    largest_area_value = float("-inf")
    for gid in terminals:
        row = by_gid.get(gid)
        if row is None:
            continue
        ancestors = {int(x) for x in nx.ancestors(graph, str(gid))} | {gid}
        upstream_area = sum(area_map.get(n, 0.0) for n in ancestors)
        if upstream_area > largest_area_value:
            largest_area_value = upstream_area
            largest_area = gid
        upstream_hru_count = sum(1 for hid in hru_area_map if hid in ancestors)
        dist_m = None
        row_lat = _safe_float(row.get("lat"))
        row_lon = _safe_float(row.get("lon"))
        if gauge_lat is not None and gauge_lon is not None and row_lat is not None and row_lon is not None:
            dist_m = _haversine_m(gauge_lat, gauge_lon, row_lat, row_lon)
        out_m3 = out_by_terminal.get(gid)
        inventories.append(
            TerminalTraceRow(
                terminal_gis_id=gid,
                terminal_internal_id=int(row["id"]),
                outflow_m3=out_m3,
                percent_of_all_terminal_outflow=(out_m3 / all_terminal_outflow) if all_terminal_outflow > 0 and out_m3 is not None else None,
                distance_to_usgs_outlet_m=dist_m,
                upstream_channel_count=len(ancestors),
                upstream_hru_count=upstream_hru_count,
                upstream_area_km2=upstream_area,
                is_selected_evaluation_outlet=(selected == gid),
                is_largest_flow_terminal=(largest_flow == gid),
            )
        )
    nearest_terminal = None
    rows_with_distance = [r for r in inventories if r.distance_to_usgs_outlet_m is not None]
    if rows_with_distance:
        nearest_terminal = min(rows_with_distance, key=lambda r: _distance_sort_value(r.distance_to_usgs_outlet_m)).terminal_gis_id
    for row in inventories:
        row.is_nearest_terminal = row.terminal_gis_id == nearest_terminal
        row.is_largest_area_terminal = row.terminal_gis_id == largest_area
    inventories.sort(key=lambda r: (r.distance_to_usgs_outlet_m is None, _distance_sort_value(r.distance_to_usgs_outlet_m)))
    return inventories


def _distance_sort_value(distance_m: float | None) -> float:
    return distance_m if distance_m is not None else float("inf")


def _terminal_source_backed_alternatives(report: TerminalTraceReport) -> list[dict[str, Any]]:
    alternatives: list[dict[str, Any]] = []
    selected = next((row for row in report.terminal_inventory if row.is_selected_evaluation_outlet), None)
    nearest = next((row for row in report.terminal_inventory if row.is_nearest_terminal), None)
    if (
        selected is not None
        and nearest is not None
        and selected.terminal_gis_id != nearest.terminal_gis_id
        and report.gauge_coordinate_source
    ):
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_selected_terminal_against_nearest_gauge_terminal",
                "source": "USGS gauge-coordinate terminal ranking from terminal_trace.json",
                "required_artifacts": [
                    "reports/terminal_trace.json",
                    "chandeg.con",
                    "delin/shapes/outlets.gpkg or outlet_raw.shp",
                ],
                "fresh_output_required": False,
                "claim_impact": "terminal_scope_claim_blocks_research_grade_until_selected_terminal_matches_or_justifies_gauge_terminal",
                "rationale": (
                    f"Selected terminal `{selected.terminal_gis_id}` is "
                    f"{_fmt(selected.distance_to_usgs_outlet_m)} m from the recovered gauge point, "
                    f"while terminal `{nearest.terminal_gis_id}` is nearest."
                ),
                "selected_terminal_gis_id": selected.terminal_gis_id,
                "nearest_terminal_gis_id": nearest.terminal_gis_id,
                "selected_outlet_distance_to_gauge_m": selected.distance_to_usgs_outlet_m,
                "nearest_terminal_distance_to_gauge_m": nearest.distance_to_usgs_outlet_m,
                "selected_terminal_is_largest_flow_terminal": selected.is_largest_flow_terminal,
                "selected_terminal_is_largest_area_terminal": selected.is_largest_area_terminal,
                "selected_terminal_upstream_area_km2": selected.upstream_area_km2,
                "nearest_terminal_upstream_area_km2": nearest.upstream_area_km2,
                "selected_terminal_percent_of_all_terminal_outflow": selected.percent_of_all_terminal_outflow,
                "nearest_terminal_percent_of_all_terminal_outflow": nearest.percent_of_all_terminal_outflow,
                "terminal_outlet_conflict_class": report.terminal_outlet_conflict_class,
                "terminal_outlet_conflict_flags": report.terminal_outlet_conflict_flags,
                "gauge_coordinate_source": report.gauge_coordinate_source,
            }
        )
    if report.failure_class == "multi_terminal_requires_aggregation":
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_terminal_inventory_and_aggregation",
                "source": "SWAT+ chandeg.con terminal inventory and upstream terminal footprint",
                "required_artifacts": ["reports/terminal_trace.json", "chandeg.con", "routing_graph.graphml"],
                "fresh_output_required": False,
                "claim_impact": "terminal_scope_claim_blocks_research_grade_until_multi_terminal_scope_is_explained",
                "rationale": "Multiple emitted terminal outlets require explicit selected-vs-all terminal scope justification.",
            }
        )
    return alternatives


def _terminal_virtual_outlet_candidate(report: TerminalTraceReport) -> dict[str, Any]:
    authority = report.terminal_authority_area_check or {}
    terminal_ids = sorted(row.terminal_gis_id for row in report.terminal_inventory)
    selected_fraction = _safe_float(authority.get("selected_fraction"))
    all_fraction = _safe_float(authority.get("all_terminal_fraction"))
    overlap = _safe_float(report.shared_upstream_area_km2) or 0.0
    available = (
        authority.get("class") == "selected_terminal_partial_basin_all_terminal_matches_authoritative_area"
        and bool(terminal_ids)
        and len(terminal_ids) >= 2
        and overlap <= 1e-9
    )
    return {
        "available": available,
        "status": "diagnostic_only_authority_required" if available else "not_available",
        "candidate_type": "all_terminal_virtual_outlet",
        "claim_authority": False,
        "temporary_terminal_metrics_allowed_as_final": False,
        "fresh_locked_rerun_required": True,
        "reference_area_source": authority.get("reference_area_source"),
        "authority_class": authority.get("class"),
        "terminal_gis_ids": terminal_ids,
        "selected_outlet_gis_id": report.selected_outlet_gis_id,
        "selected_fraction_of_authority_area": selected_fraction,
        "all_terminal_fraction_of_authority_area": all_fraction,
        "all_terminal_aggregation_valid": overlap <= 1e-9,
        "all_terminal_aggregation_reason": (
            "no_material_terminal_upstream_overlap"
            if overlap <= 1e-9
            else "terminal_upstream_overlap_requires_topology_repair"
        ),
        "required_before_claim": [
            "document_gauge_outlet_is_represented_by_all_terminal_aggregation",
            "make_virtual_outlet_selection_explicit_in_outlet_provenance",
            "relock_benchmark_against_virtual_all_terminal_outlet",
            "rerun_clean_locked_txtinout_before_reporting_metrics",
            "run_physical_routing_sensitivity_calibration_and_metric_gates_on_locked_virtual_outlet",
        ],
        "claim_impact": (
            "diagnostic_candidate_only_until_virtual_outlet_is_authorized_and_locked"
            if available
            else "no_virtual_outlet_candidate_without_authoritative_area_match_and_valid_aggregation"
        ),
        "rationale": (
            "Official gauge drainage area matches the all-terminal footprint while the selected terminal "
            "is partial; a virtual all-terminal outlet is the next diagnostic experiment, not final evidence."
            if available
            else "Virtual outlet candidate unavailable under current terminal authority evidence."
        ),
    }


def _render_terminal_virtual_outlet_candidate_markdown(candidate: dict[str, Any]) -> str:
    lines = [
        "# Terminal Virtual Outlet Candidate",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for key in (
        "available",
        "status",
        "candidate_type",
        "claim_authority",
        "reference_area_source",
        "authority_class",
        "selected_outlet_gis_id",
        "selected_fraction_of_authority_area",
        "all_terminal_fraction_of_authority_area",
        "all_terminal_aggregation_valid",
        "all_terminal_aggregation_reason",
        "claim_impact",
    ):
        lines.append(f"| {key} | `{candidate.get(key)}` |")
    terminal_ids = candidate.get("terminal_gis_ids")
    if isinstance(terminal_ids, list):
        lines.append(f"| terminal_gis_ids | `{','.join(str(v) for v in terminal_ids)}` |")
    required = candidate.get("required_before_claim")
    if isinstance(required, list) and required:
        lines.extend(["", "## Required Before Claim"])
        lines.extend(f"- `{item}`" for item in required)
    rationale = candidate.get("rationale")
    if rationale:
        lines.extend(["", "## Rationale", str(rationale)])
    return "\n".join(lines) + "\n"


def _terminal_recommended_probe_order(alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for alt in alternatives:
        option = alt.get("option")
        artifacts = alt.get("required_artifacts")
        if not option or not isinstance(artifacts, list) or not artifacts:
            continue
        probes.append(
            {
                "rank": alt.get("rank"),
                "diagnostic": option,
                "required_artifacts": artifacts,
                "fresh_output_required": bool(alt.get("fresh_output_required")),
                "claim_impact": alt.get("claim_impact"),
            }
        )
    return probes


def _chandeg_records_by_gis(txt: Path) -> dict[int, dict[str, Any]]:
    path = txt / "chandeg.con"
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header_idx: int | None = None
    columns: list[str] = []
    for idx, line in enumerate(lines):
        parts = line.split()
        if "gis_id" in parts and "out_tot" in parts:
            header_idx = idx
            columns = parts
            break
    if header_idx is None:
        return {}

    out: dict[int, dict[str, Any]] = {}
    for line in lines[header_idx + 1:]:
        parts = line.split()
        if not parts:
            continue
        row = {col: parts[idx] for idx, col in enumerate(columns) if idx < len(parts)}
        gid = _safe_int(row.get("gis_id"))
        if gid is not None:
            out[gid] = row
    return out


def _union_upstream_area_km2(graph: nx.DiGraph, terminals: list[int], area_map: dict[int, float]) -> float:
    union: set[int] = set()
    for gid in terminals:
        union |= ({int(x) for x in nx.ancestors(graph, str(gid))} | {gid})
    return sum(area_map.get(n, 0.0) for n in union)


def _terminal_overlap_pairs(
    graph: nx.DiGraph,
    terminal_rows: list[TerminalTraceRow],
    area_map: dict[int, float],
) -> list[TerminalOverlapRow]:
    upstream_sets = {
        row.terminal_gis_id: _upstream_node_set(graph, row.terminal_gis_id)
        for row in terminal_rows
    }
    area_by_terminal = {
        row.terminal_gis_id: row.upstream_area_km2
        for row in terminal_rows
    }
    pairs: list[TerminalOverlapRow] = []
    terminal_ids = sorted(upstream_sets)
    for idx, left in enumerate(terminal_ids):
        for right in terminal_ids[idx + 1:]:
            shared_nodes = upstream_sets[left] & upstream_sets[right]
            shared_area = sum(area_map.get(node, 0.0) for node in shared_nodes)
            if shared_area <= 0.0:
                continue
            left_area = area_by_terminal.get(left)
            right_area = area_by_terminal.get(right)
            shared_ids = sorted(shared_nodes)
            pairs.append(
                TerminalOverlapRow(
                    terminal_a_gis_id=left,
                    terminal_b_gis_id=right,
                    shared_upstream_area_km2=shared_area,
                    terminal_a_upstream_area_km2=left_area,
                    terminal_b_upstream_area_km2=right_area,
                    fraction_of_terminal_a=_ratio(shared_area, left_area),
                    fraction_of_terminal_b=_ratio(shared_area, right_area),
                    shared_channel_count=len(shared_nodes),
                    shared_channel_ids=shared_ids[:25],
                    shared_channel_ids_truncated=len(shared_ids) > 25,
                )
            )
    pairs.sort(
        key=lambda row: (
            -row.shared_upstream_area_km2,
            row.terminal_a_gis_id,
            row.terminal_b_gis_id,
        )
    )
    return pairs


def _upstream_node_set(graph: nx.DiGraph, terminal_gis_id: int) -> set[int]:
    node = str(terminal_gis_id)
    if node not in graph:
        return {terminal_gis_id}
    return {int(x) for x in nx.ancestors(graph, node)} | {terminal_gis_id}


def _orphan_terminal_ids(graph: nx.DiGraph, terminal_ids: list[int], area_map: dict[int, float]) -> list[int]:
    orphans: list[int] = []
    for gid in terminal_ids:
        node = str(gid)
        if graph.in_degree(node) == 0 and not nx.ancestors(graph, node) and (area_map.get(gid) or 0.0) <= 0.0:
            orphans.append(gid)
    return orphans


def _classify_terminal_failure(
    *,
    selected_row: TerminalTraceRow | None,
    terminal_rows: list[TerminalTraceRow],
    terminal_count: int,
    material_missing_terminal_count: int,
    delineated_area_km2: float | None,
    all_terminal_union_km2: float | None,
    shared_area_km2: float,
) -> Literal[
    "selected_outlet_wrong",
    "selected_outlet_partial_basin",
    "multi_terminal_requires_aggregation",
    "output_source_not_authoritative",
    "routing_graph_chandeg_mismatch",
    "generated_topology_mismatch",
]:
    if material_missing_terminal_count > 0:
        return "routing_graph_chandeg_mismatch"
    if selected_row is None:
        return "selected_outlet_wrong"
    if not selected_row.is_selected_evaluation_outlet:
        return "selected_outlet_wrong"
    if terminal_count <= 1:
        return "generated_topology_mismatch"
    selected_share = selected_row.percent_of_all_terminal_outflow or 0.0
    basin_share = None
    if delineated_area_km2 and selected_row.upstream_area_km2 is not None:
        basin_share = selected_row.upstream_area_km2 / delineated_area_km2
    if selected_row.is_nearest_terminal and selected_share < 0.1 and (basin_share is not None and basin_share < 0.95):
        return "selected_outlet_partial_basin"
    if all_terminal_union_km2 is not None and delineated_area_km2 is not None:
        if abs(all_terminal_union_km2 - delineated_area_km2) / max(delineated_area_km2, 1e-9) > 0.05:
            return "generated_topology_mismatch"
    if shared_area_km2 > 0:
        return "generated_topology_mismatch"
    return "multi_terminal_requires_aggregation"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import atan2, cos, radians, sin, sqrt

    r = 6371000.0
    p1 = radians(lat1)
    p2 = radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2.0) ** 2 + cos(p1) * cos(p2) * sin(dlon / 2.0) ** 2
    return 2.0 * r * atan2(sqrt(a), sqrt(1.0 - a))


def _write_json_generic(report: BaseModel, path: Path) -> None:
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _render_terminal_markdown(report: TerminalTraceReport) -> str:
    lines = [
        f"# Terminal Trace Diagnostic - {report.basin_id}",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    summary_rows = [
        ("Failure class", report.failure_class),
        ("Selected outlet GIS ID", report.selected_outlet_gis_id),
        ("Selected outlet reason", report.selected_outlet_reason),
        ("Selected outlet is terminal", report.selected_outlet_is_terminal),
        ("Selected outlet distance to gauge m", _fmt(report.selected_outlet_distance_to_gauge_m)),
        ("Gauge lat", _fmt(report.gauge_lat)),
        ("Gauge lon", _fmt(report.gauge_lon)),
        ("Gauge coordinate source", report.gauge_coordinate_source or "n/a"),
        ("Terminal count", report.terminal_count),
        ("Terminal inventory count", report.terminal_inventory_count),
        ("Missing terminal GIS IDs", ",".join(str(v) for v in report.missing_terminal_gis_ids) or "none"),
        ("Orphan terminal GIS IDs", ",".join(str(v) for v in report.orphan_terminal_gis_ids) or "none"),
        (
            "Material missing terminal GIS IDs",
            ",".join(str(v) for v in report.material_missing_terminal_gis_ids) or "none",
        ),
        ("Missing terminal upstream area km2", _fmt(report.missing_terminal_upstream_area_km2)),
        ("NLDI basin area km2", _fmt(report.basin_nldi_area_km2)),
        ("USGS site drainage area sqmi", _fmt(report.usgs_site_drainage_area_sqmi)),
        ("USGS site drainage area km2", _fmt(report.usgs_site_drainage_area_km2)),
        ("Delineated area km2", _fmt(report.delineated_area_km2)),
        ("HRU area km2", _fmt(report.hru_area_km2)),
        ("Selected terminal upstream area km2", _fmt(report.selected_terminal_upstream_area_km2)),
        ("All-terminal upstream area km2", _fmt(report.all_terminal_upstream_area_km2)),
        ("Sum terminal upstream area km2", _fmt(report.sum_terminal_upstream_area_km2)),
        ("Shared upstream area km2", _fmt(report.shared_upstream_area_km2)),
        ("Terminal overlap pair count", len(report.terminal_overlap_pairs)),
        ("Selected terminal fraction of NLDI area", _fmt(report.selected_terminal_fraction_of_nldi_area)),
        (
            "Selected terminal fraction of USGS site area",
            _fmt(report.selected_terminal_fraction_of_usgs_site_area),
        ),
        ("All-terminal fraction of NLDI area", _fmt(report.all_terminal_fraction_of_nldi_area)),
        ("All-terminal fraction of USGS site area", _fmt(report.all_terminal_fraction_of_usgs_site_area)),
        ("Delineated fraction of NLDI area", _fmt(report.delineated_fraction_of_nldi_area)),
        (
            "Selected terminal fraction of delineated area",
            _fmt(report.selected_terminal_fraction_of_delineated_area),
        ),
        ("All-terminal fraction of delineated area", _fmt(report.all_terminal_fraction_of_delineated_area)),
        ("Terminal authority area class", report.terminal_authority_area_check.get("class") or "n/a"),
        (
            "Terminal authority area source",
            report.terminal_authority_area_check.get("reference_area_source") or "n/a",
        ),
        (
            "Terminal virtual outlet candidate",
            report.terminal_virtual_outlet_candidate.get("status") or "n/a",
        ),
        ("Terminal outlet conflict class", report.terminal_outlet_conflict_class or "n/a"),
        ("Terminal outlet conflict flags", ",".join(report.terminal_outlet_conflict_flags) or "none"),
    ]
    lines.extend(f"| {k} | `{v}` |" for k, v in summary_rows)
    if report.notes:
        lines.extend(["", "## Notes"])
        lines.extend(f"- {note}" for note in report.notes)
    if report.source_backed_alternatives:
        lines.extend(["", "## Source-Backed Alternatives"])
        for alt in report.source_backed_alternatives:
            lines.append(
                f"- `{alt.get('option')}`: {alt.get('rationale')} "
                f"(claim impact: `{alt.get('claim_impact')}`)"
            )
    if report.recommended_probe_order:
        lines.extend(["", "## Recommended Probe Order"])
        for probe in report.recommended_probe_order:
            lines.append(
                f"- `{probe.get('rank')}` `{probe.get('diagnostic')}` "
                f"(fresh output required: `{probe.get('fresh_output_required')}`)"
            )
    if report.terminal_overlap_pairs:
        lines.extend(
            [
                "",
                "## Terminal Overlap Pairs",
                "",
                "| Terminal A | Terminal B | Shared area km2 | Fraction of A | Fraction of B | Shared channels |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in report.terminal_overlap_pairs:
            shared_ids = ",".join(str(v) for v in row.shared_channel_ids)
            if row.shared_channel_ids_truncated:
                shared_ids += ",..."
            lines.append(
                f"| {row.terminal_a_gis_id} | {row.terminal_b_gis_id} | "
                f"{_fmt(row.shared_upstream_area_km2)} | {_fmt(row.fraction_of_terminal_a)} | "
                f"{_fmt(row.fraction_of_terminal_b)} | {shared_ids or 'none'} |"
            )
    lines.extend(["", "## Terminals", "", "| GIS ID | Internal ID | Outflow m3 | Share | Dist to gauge m | Upstream channels | Upstream HRUs | Upstream area km2 | Selected | Nearest | Largest flow | Largest area |", "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|"])
    for row in report.terminal_inventory:
        lines.append(
            f"| {row.terminal_gis_id} | {row.terminal_internal_id} | {_fmt(row.outflow_m3)} | "
            f"{_fmt(row.percent_of_all_terminal_outflow)} | {_fmt(row.distance_to_usgs_outlet_m)} | "
            f"{row.upstream_channel_count or 'n/a'} | {row.upstream_hru_count or 'n/a'} | "
            f"{_fmt(row.upstream_area_km2)} | {row.is_selected_evaluation_outlet} | {row.is_nearest_terminal} | "
            f"{row.is_largest_flow_terminal} | {row.is_largest_area_terminal} |"
        )
    return "\n".join(lines) + "\n"


def _weighted_depth_volume(
    rows: list[dict[str, Any]],
    areas_ha: dict[int, float],
    column: str,
) -> tuple[float | None, float | None]:
    volume = 0.0
    area_m2 = 0.0
    for row in rows:
        unit = _safe_int(row.get("unit")) or _safe_int(row.get("gis_id"))
        depth = _safe_float(row.get(column))
        area_ha = areas_ha.get(int(unit)) if unit is not None else None
        if depth is None or area_ha is None:
            continue
        volume += depth / 1000.0 * area_ha * 10000.0
        area_m2 += area_ha * 10000.0
    if area_m2 <= 0:
        return None, None
    return volume / area_m2 * 1000.0, volume


def _area_map(path: Path) -> dict[int, float]:
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header: list[str] | None = None
    out: dict[int, float] = {}
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if "id" in parts and "area" in parts:
            header = parts
            continue
        if header is None:
            continue
        try:
            idx_id = header.index("id")
            idx_area = header.index("area")
            obj_id = int(parts[idx_id])
            area = float(parts[idx_area])
        except (ValueError, IndexError):
            continue
        out[obj_id] = area
    return out


def _ru_outflow_m3(txt: Path) -> float | None:
    table = _read_routing_unit_optional(txt / "ru_yr.txt") or _read_routing_unit_optional(txt / "ru_aa.txt")
    if table is None:
        return None
    if not table.rows:
        return 0.0
    unit = _unit_for_column(table, "flo")
    return sum(_flow_value_to_m3(row.get("flo"), unit, row) or 0.0 for row in table.rows)


def _basin_summary_channel_trace(txt: Path) -> dict[str, Any]:
    for name in (
        "basin_sd_chamorph_day.txt",
        "basin_sd_chamorph_yr.txt",
        "basin_sd_cha_day.txt",
        "basin_sd_cha_yr.txt",
        "basin_sd_chamorph_aa.txt",
        "basin_sd_cha_aa.txt",
    ):
        source = _read_optional(txt / name)
        if source is not None:
            break
    else:
        return {"source_note": "No basin-summary channel output file available for mass trace."}

    unit = _unit_for_column(source, "flo_out")
    rows = source.rows
    outflow = sum(_flow_value_to_m3(r.get("flo_out"), unit, r) or 0.0 for r in rows)
    source_note = "Using basin-summary channel output with header units for aggregate closure comparison."
    return {
        "source_file": source.path.name,
        "unit": unit,
        "source_note": source_note,
        "row_count": len(rows),
        "years": _year_list(rows),
        "basin_summary_outflow_m3": outflow,
    }


def _channel_trace(txt: Path, selected: int | None, terminal_ids: set[int]) -> dict[str, Any]:
    source = _read_optional(txt / "channel_sdmorph_day.txt")
    source_file = "channel_sdmorph_day.txt" if source is not None else None
    source_note = "Using morphology daily channel rates (`m3/s`) for mass trace."
    if source is None:
        source = _read_optional(txt / "channel_sd_day.txt") or _read_optional(txt / "channel_sd_yr.txt")
        source_file = source.path.name if source is not None else None
        source_note = "Morphology daily output unavailable; using general channel output with header units."
    if source is None:
        return {"source_note": "No channel output file available for mass trace."}

    unit = _unit_for_column(source, "flo_out")
    selected_rows = [r for r in source.rows if selected is not None and _safe_int(r.get("gis_id")) == int(selected)]
    terminal_rows = [r for r in source.rows if _safe_int(r.get("gis_id")) in terminal_ids]
    return {
        "source_file": source_file,
        "unit": unit,
        "source_note": source_note,
        "row_count": len(source.rows),
        "years": _year_list(source.rows),
        "selected_row_count": len(selected_rows),
        "selected_years": _year_list(selected_rows),
        "terminal_row_count": len(terminal_rows),
        "terminal_years": _year_list(terminal_rows),
        "channel_inflow_m3": sum(_flow_value_to_m3(r.get("flo_in"), _unit_for_column(source, "flo_in"), r) or 0.0 for r in selected_rows)
        if selected_rows
        else None,
        "channel_outflow_m3": sum(_flow_value_to_m3(r.get("flo_out"), unit, r) or 0.0 for r in selected_rows)
        if selected_rows
        else None,
        "terminal_outflow_m3": sum(_flow_value_to_m3(r.get("flo_out"), unit, r) or 0.0 for r in selected_rows)
        if selected is not None and selected in terminal_ids and selected_rows
        else None,
        "all_terminal_outflow_m3": sum(_flow_value_to_m3(r.get("flo_out"), unit, r) or 0.0 for r in terminal_rows)
        if terminal_rows
        else None,
    }


def _flow_value_to_m3(value: object, unit: str | None, row: dict[str, Any]) -> float | None:
    val = _safe_float(value)
    if val is None:
        return None
    unit_norm = (unit or "").lower().replace("³", "^3").replace(" ", "")
    if unit_norm in {"m^3/s", "m3/s"}:
        return val * _row_seconds(row)
    if unit_norm in {"m^3", "m3"}:
        return val
    if unit_norm in {"ha-m", "ham"}:
        return val * 10000.0
    return val


def _row_seconds(row: dict[str, Any]) -> float:
    day = _safe_int(row.get("day"))
    mon = _safe_int(row.get("mon"))
    if day and mon:
        return _SECONDS_PER_DAY
    return _SECONDS_PER_YEAR


def _depth_mm_to_m3(depth_mm: float | None, area_km2: float | None) -> float | None:
    if depth_mm is None or area_km2 is None or area_km2 <= 0:
        return None
    return depth_mm / 1000.0 * area_km2 * 1_000_000.0


def _period_from_rows(rows: list[dict[str, Any]]) -> str | None:
    years = _year_list(rows)
    if not years:
        return None
    return f"{years[0]}-01-01..{years[-1]}-12-31"


def _year_list(rows: list[dict[str, Any]]) -> list[int]:
    return sorted({year for row in rows if (year := _safe_int(row.get("yr"))) is not None and year > 0})


def _evaluation_period(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    date_col = next((c for c in df.columns if "date" in c.lower()), df.columns[0] if len(df.columns) else None)
    if date_col is None:
        return None
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None
    return f"{dates.min().date()}..{dates.max().date()}"


def _lookup(data: dict, path: tuple[str, ...]) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _first_float(*values: object) -> float | None:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _detect_lte_transfer_scale_bug(
    channel: dict[str, object],
    hru_wateryld_m3: float | None,
) -> bool:
    """Detect SWAT+ v2023.60.5.7 LTE hru_lte→channel ×100 transfer-scale bug.

    If ``channel_inflow_m3 / hru_wateryld_m3 ≈ 100`` (within ±5%), the engine
    is multiplying water yield by 1000 instead of 10 when computing channel
    inflow volume.  The pipeline should apply a 0.01 frac correction to
    ``hru-lte.con`` before the engine run.
    """
    cin = _safe_float(channel.get("channel_inflow_m3"))
    if cin is None or hru_wateryld_m3 is None or hru_wateryld_m3 <= 0:
        return False
    ratio = cin / hru_wateryld_m3
    return 95.0 <= ratio <= 105.0


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_json(report: MassTraceReport, path: Path) -> None:
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _write_csv(report: MassTraceReport, path: Path) -> None:
    data = report.model_dump()
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(data.keys()))
        writer.writeheader()
        writer.writerow(data)


def _render_markdown(report: MassTraceReport) -> str:
    rows = [
        ("Closure status", report.closure_status),
        ("Flags", ", ".join(report.flags) if report.flags else "none"),
        ("Simulation period", report.simulation_period),
        ("Evaluation period", report.evaluation_period),
        ("Model area km2", _fmt(report.model_area_km2)),
        ("Precip mm", _fmt(report.precip_mm)),
        ("ET mm", _fmt(report.et_mm)),
        ("Basin water yield mm", _fmt(report.basin_wateryld_mm)),
        ("Basin water yield m3", _fmt(report.basin_wateryld_m3)),
        ("Basin routed-to-channel mm", _fmt(report.basin_routed_to_channel_mm)),
        ("Basin routed-to-channel m3", _fmt(report.basin_routed_to_channel_m3)),
        ("Routed-to-channel closure ratio", _fmt(report.routed_to_channel_closure_ratio)),
        ("All-terminal routed-to-channel closure ratio", _fmt(report.all_terminal_routed_to_channel_closure_ratio)),
        ("All-terminal mass closure ratio", _fmt(report.all_terminal_mass_closure_ratio)),
        ("Selected-terminal share of all terminal flow", _fmt(report.selected_terminal_fraction_of_all_terminal_flow)),
        ("Closure reference", report.closure_reference),
        ("Basin summary outflow m3", _fmt(report.basin_summary_outflow_m3)),
        ("HRU water yield m3", _fmt(report.hru_wateryld_m3)),
        ("LSU outflow m3", _fmt(report.lsu_outflow_m3)),
        ("RU outflow m3", _fmt(report.ru_outflow_m3)),
        ("RU/basin wateryld ratio", _fmt(report.ru_outflow_to_basin_wateryld_ratio)),
        ("Channel inflow m3", _fmt(report.channel_inflow_m3)),
        ("Channel outflow m3", _fmt(report.channel_outflow_m3)),
        ("Selected terminal outflow m3", _fmt(report.terminal_outflow_m3)),
        ("All terminal outflow m3", _fmt(report.all_terminal_outflow_m3)),
        ("Selected outlet GIS ID", report.selected_outlet_gis_id),
        ("Selected outlet is terminal", report.selected_outlet_is_terminal),
        ("Terminal outlet count", report.terminal_outlet_count),
        ("Basin water-balance source file", report.basin_wb_source_file),
        ("Basin water-balance rows", report.basin_wb_row_count),
        ("Basin water-balance years", ",".join(map(str, report.basin_wb_years)) or "n/a"),
        ("Basin summary source file", report.basin_summary_source_file),
        ("Basin summary rows", report.basin_summary_row_count),
        ("Basin summary years", ",".join(map(str, report.basin_summary_years)) or "n/a"),
        ("Channel source file", report.channel_source_file),
        ("Channel flow unit", report.channel_flow_unit),
        ("Channel rows", report.channel_row_count),
        ("Channel years", ",".join(map(str, report.channel_years)) or "n/a"),
        ("Selected-channel rows", report.selected_channel_row_count),
        ("Selected-channel years", ",".join(map(str, report.selected_channel_years)) or "n/a"),
        ("Terminal-channel rows", report.terminal_channel_row_count),
        ("Terminal-channel years", ",".join(map(str, report.terminal_channel_years)) or "n/a"),
        ("Basin summary closure ratio", _fmt(report.summary_closure_ratio)),
        ("Mass closure ratio", _fmt(report.mass_closure_ratio)),
    ]
    lines = [
        f"# Mass Trace Diagnostic - {report.basin_id}",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    lines.extend(f"| {k} | `{v}` |" for k, v in rows)
    if report.notes:
        lines.extend(["", "## Notes"])
        lines.extend(f"- {note}" for note in report.notes)
    if report.source_backed_alternatives:
        lines.extend(["", "## Source-Backed Alternatives"])
        for alt in report.source_backed_alternatives:
            artifacts = ", ".join(str(a) for a in alt.get("required_artifacts", [])) or "n/a"
            lines.append(
                f"- `{alt.get('option')}`: artifacts `{artifacts}`; "
                f"impact `{alt.get('claim_impact')}`; source: {alt.get('source')}"
            )
    if report.recommended_probe_order:
        lines.extend(["", "## Recommended Probe Order"])
        for probe in report.recommended_probe_order:
            artifacts = ", ".join(str(a) for a in probe.get("required_artifacts", [])) or "n/a"
            lines.append(
                f"- `{probe.get('diagnostic')}`: artifacts `{artifacts}`; "
                f"fresh_output_required=`{probe.get('fresh_output_required')}`"
            )
    return "\n".join(lines) + "\n"


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
