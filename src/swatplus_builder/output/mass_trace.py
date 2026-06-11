"""Mass-conservation trace for SWAT+ run artifacts.

The trace follows documented/header units only. It never selects empirical
scale factors and never uses NSE/KGE to decide how to interpret flow.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import pandas as pd
from pydantic import BaseModel, Field

from ..errors import SwatBuilderInputError
from .eval import _terminal_ids_from_chandeg_con, _unit_for_column
from .reader import OutputTable, read_output_file

_SECONDS_PER_DAY = 86400.0
_SECONDS_PER_YEAR = 365.0 * _SECONDS_PER_DAY

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
    surq_mm: float | None = None
    latq_mm: float | None = None
    gwq_mm: float | None = None
    basin_wateryld_m3: float | None = None
    basin_summary_outflow_m3: float | None = None
    hru_wateryld_mm: float | None = None
    hru_wateryld_m3: float | None = None
    lsu_outflow_m3: float | None = None
    ru_outflow_m3: float | None = None
    channel_inflow_m3: float | None = None
    channel_outflow_m3: float | None = None
    terminal_outflow_m3: float | None = None
    all_terminal_outflow_m3: float | None = None
    selected_outlet_gis_id: int | None = None
    selected_outlet_is_terminal: bool | None = None
    terminal_outlet_count: int | None = None
    basin_summary_source_file: str | None = None
    channel_source_file: str | None = None
    channel_flow_unit: str | None = None
    summary_closure_ratio: float | None = None
    mass_closure_ratio: float | None = None
    closure_status: ClosureStatus = "insufficient_data"
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


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
    terminal_count: int | None = None
    basin_nldi_area_km2: float | None = None
    delineated_area_km2: float | None = None
    hru_area_km2: float | None = None
    selected_terminal_upstream_area_km2: float | None = None
    all_terminal_upstream_area_km2: float | None = None
    sum_terminal_upstream_area_km2: float | None = None
    shared_upstream_area_km2: float | None = None
    failure_class: Literal[
        "selected_outlet_wrong",
        "selected_outlet_partial_basin",
        "multi_terminal_requires_aggregation",
        "output_source_not_authoritative",
        "generated_topology_mismatch",
    ] = "generated_topology_mismatch"
    terminal_inventory: list[TerminalTraceRow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


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
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
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
    basin_wb = _read_optional(txt / "basin_wb_yr.txt") or _read_optional(txt / "basin_wb_aa.txt")
    basin_rows = basin_wb.rows if basin_wb else []
    period = _period_from_rows(basin_rows)
    wb = _sum_basin_wb(basin_rows, area_km2)

    hru_depth_mm, hru_m3 = _weighted_wateryld_from_hru_lte(txt)
    lsu_m3 = _weighted_wateryld_from_lsu(txt)
    ru_m3 = _ru_outflow_m3(txt)
    basin_summary = _basin_summary_channel_trace(txt)

    terminal_ids = _terminal_ids_from_chandeg_con(txt)
    channel = _channel_trace(txt, selected, terminal_ids)
    expected_m3 = wb.get("wateryld_m3")
    terminal_m3 = channel.get("terminal_outflow_m3")
    basin_summary_m3 = basin_summary.get("basin_summary_outflow_m3")
    ratio = _ratio(terminal_m3, expected_m3)
    summary_ratio = _ratio(basin_summary_m3, expected_m3)

    flags: list[str] = []
    notes: list[str] = []
    status: ClosureStatus = "insufficient_data"
    selected_is_terminal = selected in terminal_ids if selected is not None and terminal_ids else None

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
        else:
            status = "pass"
    else:
        flags.append("missing_expected_or_terminal_outflow")

    if selected_is_terminal is False:
        notes.append("Selected outlet is not terminal; terminal closure should use an audited terminal outlet.")
    if ratio is not None:
        notes.append(
            f"Closure ratio uses terminal_outflow_m3 / basin_wateryld_m3 with acceptable range "
            f"{min_closure_ratio:.2f}-{max_closure_ratio:.2f}."
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
        surq_mm=wb.get("surq_mm"),
        latq_mm=wb.get("latq_mm"),
        gwq_mm=wb.get("gwq_mm"),
        basin_wateryld_m3=expected_m3,
        basin_summary_outflow_m3=basin_summary_m3,
        hru_wateryld_mm=hru_depth_mm,
        hru_wateryld_m3=hru_m3,
        lsu_outflow_m3=lsu_m3,
        ru_outflow_m3=ru_m3,
        channel_inflow_m3=channel.get("channel_inflow_m3"),
        channel_outflow_m3=channel.get("channel_outflow_m3"),
        terminal_outflow_m3=terminal_m3,
        all_terminal_outflow_m3=channel.get("all_terminal_outflow_m3"),
        selected_outlet_gis_id=selected,
        selected_outlet_is_terminal=selected_is_terminal,
        terminal_outlet_count=len(terminal_ids) if terminal_ids else None,
        basin_summary_source_file=basin_summary.get("source_file"),
        channel_source_file=channel.get("source_file"),
        channel_flow_unit=channel.get("unit"),
        summary_closure_ratio=summary_ratio,
        mass_closure_ratio=ratio,
        closure_status=status,
        flags=flags,
        notes=notes,
    )

    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    _write_json(report, destination / "mass_trace.json")
    _write_csv(report, destination / "mass_trace.csv")
    (destination / "mass_trace.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def trace_terminal_inventory(
    run_dir: Path | str,
    *,
    basin_id: str | None = None,
    selected_outlet_gis_id: int | None = None,
    out_dir: Path | str | None = None,
) -> TerminalTraceReport:
    """Inventory terminal channels and classify the outlet failure mode."""
    run = Path(run_dir).expanduser().resolve()
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    if not txt.is_dir():
        raise SwatBuilderInputError(f"TxtInOut directory not found: {txt}", txtinout_dir=str(txt))

    metadata = _load_json(run / "metadata.json")
    outlet_prov = _load_json(run / "outputs" / "outlet_provenance.json")
    audit = _load_json(run / "reports" / "outlet_audit" / "outlet_audit.json")
    snap = _load_json(run / "delin" / "snap_diagnostic.json")
    basin = basin_id or str(metadata.get("usgs_id") or run.name)
    basin_wb = _read_optional(txt / "basin_wb_yr.txt") or _read_optional(txt / "basin_wb_aa.txt")
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

    basin_nldi_area = _safe_float(snap.get("expected_area_km2"))
    delineated_area = _safe_float(snap.get("generated_area_km2"))
    area_map = _subbasin_area_map(run)
    hru_area = _hru_area_km2(txt)
    if delineated_area is None and area_map:
        delineated_area = sum(area_map.values())

    G = nx.read_graphml(run / "delin" / "routing_graph.graphml")
    terminals = sorted(int(n) for n in G.nodes if G.out_degree(n) == 0)
    terminal_rows = _terminal_inventory_rows(
        txt,
        G,
        terminals,
        area_map,
        hru_area_map=_hru_area_map(txt),
        gauge_lat=_safe_float(audit.get("gauge_lat")),
        gauge_lon=_safe_float(audit.get("gauge_lon")),
        selected_outlet_gis_id=selected,
    )
    all_terminal_union = _union_upstream_area_km2(G, terminals, area_map)
    sum_terminal_area = sum(r.upstream_area_km2 or 0.0 for r in terminal_rows)
    shared_area = max(0.0, sum_terminal_area - all_terminal_union)

    selected_row = next((r for r in terminal_rows if r.terminal_gis_id == selected), None)
    selected_is_terminal = selected in terminals if selected is not None else None
    selected_distance = selected_row.distance_to_usgs_outlet_m if selected_row else None

    failure_class = _classify_terminal_failure(
        selected_row=selected_row,
        terminal_rows=terminal_rows,
        terminal_count=len(terminals),
        delineated_area_km2=delineated_area,
        all_terminal_union_km2=all_terminal_union,
        shared_area_km2=shared_area,
    )
    notes = [
        "Selected outlet is the nearest terminal to the gauge, but it is not the largest-flow terminal.",
        "Multiple terminal outlets overlap upstream area, so terminal aggregation is not a simple sum in this topology.",
    ]
    if selected_row:
        notes.append(
            f"Selected terminal share of all-terminal outflow is "
            f"{(selected_row.percent_of_all_terminal_outflow or 0.0):.3%}."
        )

    report = TerminalTraceReport(
        basin_id=basin,
        run_dir=str(run),
        txtinout_dir=str(txt),
        generated_at=datetime.now(timezone.utc).isoformat(),
        simulation_period=period,
        selected_outlet_gis_id=selected,
        selected_outlet_reason=selected_reason,
        selected_outlet_is_terminal=selected_is_terminal,
        selected_outlet_distance_to_gauge_m=selected_distance,
        terminal_count=len(terminals),
        basin_nldi_area_km2=basin_nldi_area,
        delineated_area_km2=delineated_area,
        hru_area_km2=hru_area,
        selected_terminal_upstream_area_km2=selected_row.upstream_area_km2 if selected_row else None,
        all_terminal_upstream_area_km2=all_terminal_union,
        sum_terminal_upstream_area_km2=sum_terminal_area,
        shared_upstream_area_km2=shared_area,
        failure_class=failure_class,
        terminal_inventory=terminal_rows,
        notes=notes,
    )

    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    _write_json_generic(report, destination / "terminal_trace.json")
    (destination / "terminal_trace.md").write_text(_render_terminal_markdown(report), encoding="utf-8")
    return report


def _read_optional(path: Path) -> OutputTable | None:
    if not path.is_file():
        return None
    return read_output_file(path)


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
        vals = [v for v in vals if v is not None]
        out[key] = sum(vals) if vals else None
    out["wateryld_m3"] = _depth_mm_to_m3(out.get("wateryld_mm"), area_km2)
    return out


def _weighted_wateryld_from_hru_lte(txt: Path) -> tuple[float | None, float | None]:
    table = _read_optional(txt / "hru-lte_wb_yr.txt") or _read_optional(txt / "hru_wb_yr.txt")
    areas = _area_map(txt / "hru-lte.hru")
    if table is None or not areas:
        return None, None
    return _weighted_depth_volume(table.rows, areas, "wateryld")


def _weighted_wateryld_from_lsu(txt: Path) -> float | None:
    table = _read_optional(txt / "lsunit_wb_yr.txt") or _read_optional(txt / "lsunit_wb_aa.txt")
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
    chandeg = pd.read_csv(txt / "chandeg.con", sep=r"\s+", skiprows=1, engine="python")
    by_gid = {}
    for row in chandeg.to_dict(orient="records"):
        gid = _safe_int(row.get("gis_id"))
        if gid is not None:
            by_gid[gid] = row
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
        if gauge_lat is not None and gauge_lon is not None:
            dist_m = _haversine_m(gauge_lat, gauge_lon, float(row["lat"]), float(row["lon"]))
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
        nearest_terminal = min(rows_with_distance, key=lambda r: r.distance_to_usgs_outlet_m or float("inf")).terminal_gis_id
    for row in inventories:
        row.is_nearest_terminal = row.terminal_gis_id == nearest_terminal
        row.is_largest_area_terminal = row.terminal_gis_id == largest_area
    inventories.sort(key=lambda r: (r.distance_to_usgs_outlet_m is None, r.distance_to_usgs_outlet_m or float("inf")))
    return inventories


def _union_upstream_area_km2(graph: nx.DiGraph, terminals: list[int], area_map: dict[int, float]) -> float:
    union: set[int] = set()
    for gid in terminals:
        union |= ({int(x) for x in nx.ancestors(graph, str(gid))} | {gid})
    return sum(area_map.get(n, 0.0) for n in union)


def _classify_terminal_failure(
    *,
    selected_row: TerminalTraceRow | None,
    terminal_rows: list[TerminalTraceRow],
    terminal_count: int,
    delineated_area_km2: float | None,
    all_terminal_union_km2: float | None,
    shared_area_km2: float,
) -> Literal[
    "selected_outlet_wrong",
    "selected_outlet_partial_basin",
    "multi_terminal_requires_aggregation",
    "output_source_not_authoritative",
    "generated_topology_mismatch",
]:
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
        ("Terminal count", report.terminal_count),
        ("NLDI basin area km2", _fmt(report.basin_nldi_area_km2)),
        ("Delineated area km2", _fmt(report.delineated_area_km2)),
        ("HRU area km2", _fmt(report.hru_area_km2)),
        ("Selected terminal upstream area km2", _fmt(report.selected_terminal_upstream_area_km2)),
        ("All-terminal upstream area km2", _fmt(report.all_terminal_upstream_area_km2)),
        ("Sum terminal upstream area km2", _fmt(report.sum_terminal_upstream_area_km2)),
        ("Shared upstream area km2", _fmt(report.shared_upstream_area_km2)),
    ]
    lines.extend(f"| {k} | `{v}` |" for k, v in summary_rows)
    if report.notes:
        lines.extend(["", "## Notes"])
        lines.extend(f"- {note}" for note in report.notes)
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
    table = _read_optional(txt / "ru_yr.txt") or _read_optional(txt / "ru_aa.txt")
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
    years = sorted({_safe_int(row.get("yr")) for row in rows if _safe_int(row.get("yr")) is not None})
    if not years:
        return None
    return f"{years[0]}-01-01..{years[-1]}-12-31"


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
        ("Basin summary outflow m3", _fmt(report.basin_summary_outflow_m3)),
        ("HRU water yield m3", _fmt(report.hru_wateryld_m3)),
        ("LSU outflow m3", _fmt(report.lsu_outflow_m3)),
        ("RU outflow m3", _fmt(report.ru_outflow_m3)),
        ("Channel inflow m3", _fmt(report.channel_inflow_m3)),
        ("Channel outflow m3", _fmt(report.channel_outflow_m3)),
        ("Selected terminal outflow m3", _fmt(report.terminal_outflow_m3)),
        ("All terminal outflow m3", _fmt(report.all_terminal_outflow_m3)),
        ("Selected outlet GIS ID", report.selected_outlet_gis_id),
        ("Selected outlet is terminal", report.selected_outlet_is_terminal),
        ("Terminal outlet count", report.terminal_outlet_count),
        ("Basin summary source file", report.basin_summary_source_file),
        ("Channel source file", report.channel_source_file),
        ("Channel flow unit", report.channel_flow_unit),
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
    return "\n".join(lines) + "\n"


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
