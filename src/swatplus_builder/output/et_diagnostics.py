"""ET-partition diagnostic synthesis for ET-dominated physical gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_et_partition_diagnostics(
    run_dir: Path | str,
    *,
    physical_gates: dict[str, Any] | None = None,
    values: dict[str, Any] | None = None,
    out_dir: Path | str | None = None,
    gate_context: str | None = None,
    physical_gates_source_path: str | None = None,
) -> dict[str, Any]:
    """Write JSON/Markdown diagnostics for ET-dominated physical blockers."""

    run = Path(run_dir).expanduser().resolve()
    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)

    gates = physical_gates or {}
    wb = _water_balance_summary(gates)
    flags = _classify(wb)
    soil_context = _soil_context(values or {})
    report = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_dir": str(run),
        "gate_context": gate_context or "unknown",
        "physical_gates_source_path": physical_gates_source_path,
        "physical_gate_status": gates.get("status"),
        "dominant_blocker": gates.get("dominant_blocker"),
        "condition_codes": gates.get("condition_codes") or [],
        "soil_context": soil_context,
        "water_balance": wb,
        "diagnostic_flags": flags,
        "next_actions": _next_actions(flags, values or {}),
        "source_backed_alternatives": _source_backed_alternatives(flags, values or {}),
        "recommended_probe_order": _recommended_probe_order(flags, values or {}),
    }

    json_path = destination / "et_partition_diagnostics.json"
    md_path = destination / "et_partition_diagnostics.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    report["json_path"] = str(json_path)
    report["markdown_path"] = str(md_path)
    return report


def _water_balance_summary(physical_gates: dict[str, Any]) -> dict[str, Any]:
    wb = physical_gates.get("wb")
    if not isinstance(wb, dict) or not wb:
        return {"available": False, "reason": "physical_gates_wb_missing"}
    precip = _safe_float(wb.get("precip"))
    et = _safe_float(wb.get("et"))
    pet = _safe_float(wb.get("pet"))
    esoil = _safe_float(wb.get("esoil"))
    eplant = _safe_float(wb.get("eplant"))
    ecanopy = _safe_float(wb.get("ecanopy"))
    wateryld = _safe_float(wb.get("wateryld"))
    perc = _safe_float(wb.get("perc"))
    latq = _safe_float(wb.get("latq"))
    sw_init = _safe_float(wb.get("sw_init"))
    sw_final = _safe_float(wb.get("sw_final"))
    return {
        "available": True,
        "precip_mm": precip,
        "et_mm": et,
        "pet_mm": pet,
        "esoil_mm": esoil,
        "eplant_mm": eplant,
        "ecanopy_mm": ecanopy,
        "wateryld_mm": wateryld,
        "perc_mm": perc,
        "latq_mm": latq,
        "sw_init_mm": sw_init,
        "sw_final_mm": sw_final,
        "sw_change_mm": None if sw_init is None or sw_final is None else sw_final - sw_init,
        "et_to_precip": _ratio(et, precip),
        "pet_to_precip": _ratio(pet, precip),
        "et_to_pet": _ratio(et, pet),
        "esoil_to_et": _ratio(esoil, et),
        "eplant_to_et": _ratio(eplant, et),
        "ecanopy_to_et": _ratio(ecanopy, et),
        "wateryld_to_precip": _ratio(wateryld, precip),
        "perc_to_precip": _ratio(perc, precip),
        "latq_to_precip": _ratio(latq, precip),
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


def _classify(wb: dict[str, Any]) -> list[dict[str, str]]:
    if not wb.get("available"):
        return [{"code": "et_water_balance_context_missing", "evidence": str(wb.get("reason"))}]
    flags: list[dict[str, str]] = []
    et_p = _safe_float(wb.get("et_to_precip"))
    pet_p = _safe_float(wb.get("pet_to_precip"))
    et_pet = _safe_float(wb.get("et_to_pet"))
    esoil_et = _safe_float(wb.get("esoil_to_et"))
    eplant_et = _safe_float(wb.get("eplant_to_et"))
    perc_p = _safe_float(wb.get("perc_to_precip"))
    latq_p = _safe_float(wb.get("latq_to_precip"))
    wateryld_p = _safe_float(wb.get("wateryld_to_precip"))

    if et_p is not None and et_p > 0.70:
        flags.append({"code": "et_to_precip_high", "evidence": f"ET/P={et_p:.3f} > 0.70"})
    if pet_p is not None and pet_p > 1.0:
        flags.append({"code": "pet_demand_exceeds_precip", "evidence": f"PET/P={pet_p:.3f} > 1.0"})
    if et_pet is not None and et_pet > 0.65:
        flags.append({"code": "actual_et_near_pet_demand", "evidence": f"ET/PET={et_pet:.3f} > 0.65"})
    if esoil_et is not None and esoil_et > 0.50:
        flags.append({"code": "soil_evaporation_dominates_et", "evidence": f"Esoil/ET={esoil_et:.3f} > 0.50"})
    if eplant_et is not None and eplant_et < 0.25:
        flags.append({"code": "plant_transpiration_fraction_low", "evidence": f"Eplant/ET={eplant_et:.3f} < 0.25"})
    if perc_p is not None and perc_p < 0.03:
        flags.append({"code": "percolation_partition_low", "evidence": f"Perc/P={perc_p:.3f} < 0.03"})
    if latq_p is not None and latq_p < 0.01:
        flags.append({"code": "lateral_flow_partition_low", "evidence": f"LatQ/P={latq_p:.3f} < 0.01"})
    if wateryld_p is not None and wateryld_p < 0.25:
        flags.append({"code": "water_yield_partition_low", "evidence": f"WaterYld/P={wateryld_p:.3f} < 0.25"})
    return flags or [{"code": "et_dominated_unclassified", "evidence": "ET_DOMINATED gate set without finer ratio flag"}]


def _next_actions(flags: list[dict[str, str]], values: dict[str, Any]) -> list[str]:
    codes = {str(flag.get("code")) for flag in flags if isinstance(flag, dict)}
    soil = _soil_context(values)
    actions = [
        "Run a basin-specific PET_CO/ESCO/EPCO sensitivity probe from fresh outputs before calibration.",
        "Keep ET-dominated runs exploratory until ET partition, soil water, routing, and calibration gates all pass.",
    ]
    if "soil_evaporation_dominates_et" in codes:
        actions.append("Prioritize ESCO and soil-water realism checks because soil evaporation dominates ET.")
    if "plant_transpiration_fraction_low" in codes:
        actions.append("Audit EPCO, vegetation/management inputs, and plant-water uptake partitioning.")
    if {"percolation_partition_low", "lateral_flow_partition_low"} & codes:
        if soil["soil_degraded"]:
            actions.append("Screen PERCO/LATQ_CO and subsurface routing controls only after soil provenance is acceptable.")
        else:
            actions.append("Screen PERCO/LATQ_CO and subsurface routing controls with retained soil provenance evidence.")
    if soil["soil_degraded"]:
        actions.append("Resolve degraded soil provenance before using ET sensitivity results for research-grade claims.")
    return actions


def _source_backed_alternatives(flags: list[dict[str, str]], values: dict[str, Any]) -> list[dict[str, Any]]:
    codes = {str(flag.get("code")) for flag in flags if isinstance(flag, dict)}
    soil = _soil_context(values)
    pct_fallback = _safe_float(soil.get("pct_fallback_soils"))
    soil_degraded = bool(soil.get("soil_degraded"))
    alternatives: list[dict[str, Any]] = []

    if {"pet_demand_exceeds_precip", "actual_et_near_pet_demand"} & codes:
        alternatives.append(
            {
                "rank": 1,
                "option": "audit_pet_forcing_or_pet_method",
                "source": "SWAT+ PET documentation; daily PET can be supplied through weather-sta.cli when a regional method is preferred",
                "parameters": ["PET_CO"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_physical_soil_routing_and_locked_calibration_gates_pass",
                "rationale": "PET demand is high relative to precipitation or actual ET is close to PET demand.",
            }
        )

    if "soil_evaporation_dominates_et" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "screen_soil_evaporation_compensation",
                "source": "SWAT+ soil-water evaporation documentation identifies esco as the soil evaporation compensation coefficient",
                "parameters": ["ESCO"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_basin_specific_sensitivity_and_final_gates_pass",
                "rationale": "Soil evaporation is the dominant ET partition.",
            }
        )

    if "plant_transpiration_fraction_low" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "screen_plant_uptake_compensation_and_management",
                "source": "SWAT+ hydrology controls include EPCO for plant uptake compensation; vegetation and management inputs remain part of the ET partition",
                "parameters": ["EPCO"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_vegetation_management_and_sensitivity_evidence_are_audited",
                "rationale": "Plant transpiration fraction is low relative to total ET.",
            }
        )

    if {"percolation_partition_low", "lateral_flow_partition_low", "water_yield_partition_low"} & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": (
                    "defer_subsurface_partition_controls_until_soils_are_defensible"
                    if soil_degraded
                    else "screen_subsurface_partition_controls_with_retained_soil_provenance"
                ),
                "source": "SWAT+ soft-calibration guidance uses water-balance variables including latq_co and perco after ET controls",
                "parameters": ["LATQ_CO", "PERCO"],
                "fresh_output_required": True,
                "claim_impact": (
                    "research_grade_blocked_by_soil_fidelity"
                    if soil_degraded
                    else "diagnostic_until_basin_specific_screen_and_final_gates_pass"
                ),
                "rationale": (
                    "Subsurface and water-yield partitions are low; degraded soils make subsurface calibration non-authoritative."
                    if soil_degraded
                    else "Subsurface and water-yield partitions are low despite retained soil provenance; screen supported controls against fresh locked outputs."
                ),
            }
        )

    if soil_degraded:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "recover_authoritative_soil_provenance_before_et_claims",
                "source": "Project soil source-priority manifest: gNATSGO raster plus SDA horizons is the only current research-grade-eligible soil source",
                "parameters": [],
                "fresh_output_required": False,
                "claim_impact": "soil_fidelity_gate_blocks_research_grade",
                "rationale": f"Fallback soil fraction is {pct_fallback:.3f}; ET partition sensitivity cannot support research-grade claims with degraded soils.",
            }
        )

    if not alternatives:
        alternatives.append(
            {
                "rank": 1,
                "option": "collect_basin_specific_et_partition_evidence",
                "source": "SWAT+ ET documentation and project physical-gate policy",
                "parameters": ["PET_CO", "ESCO", "EPCO"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_basin_specific_sensitivity_and_final_gates_pass",
                "rationale": "ET_DOMINATED was set without a finer partition flag.",
            }
        )

    return alternatives


def _recommended_probe_order(flags: list[dict[str, str]], values: dict[str, Any]) -> list[dict[str, Any]]:
    order: list[dict[str, Any]] = []
    alternatives = _source_backed_alternatives(flags, values)
    for alt in alternatives:
        params = alt.get("parameters")
        if not isinstance(params, list) or not params:
            continue
        order.append(
            {
                "rank": alt.get("rank"),
                "parameters": params,
                "basis": alt.get("option"),
                "fresh_output_required": alt.get("fresh_output_required", True),
                "claim_impact": alt.get("claim_impact"),
            }
        )
    return order


def _render_markdown(report: dict[str, Any]) -> str:
    wb = report.get("water_balance") if isinstance(report.get("water_balance"), dict) else {}
    rows = [
        ("Gate context", report.get("gate_context")),
        ("Physical gates source", report.get("physical_gates_source_path")),
        ("Physical gate status", report.get("physical_gate_status")),
        ("Dominant blocker", report.get("dominant_blocker")),
        ("ET/P", _fmt(wb.get("et_to_precip"))),
        ("PET/P", _fmt(wb.get("pet_to_precip"))),
        ("ET/PET", _fmt(wb.get("et_to_pet"))),
        ("Esoil/ET", _fmt(wb.get("esoil_to_et"))),
        ("Eplant/ET", _fmt(wb.get("eplant_to_et"))),
        ("Perc/P", _fmt(wb.get("perc_to_precip"))),
        ("LatQ/P", _fmt(wb.get("latq_to_precip"))),
        ("WaterYld/P", _fmt(wb.get("wateryld_to_precip"))),
    ]
    lines = [
        "# ET Partition Diagnostics",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | `{value}` |" for name, value in rows)
    lines.extend(["", "## Diagnostic Flags"])
    for flag in report.get("diagnostic_flags", []):
        if isinstance(flag, dict):
            lines.append(f"- `{flag.get('code')}`: {flag.get('evidence')}")
    lines.extend(["", "## Next Actions"])
    for action in report.get("next_actions", []):
        lines.append(f"- {action}")
    lines.extend(["", "## Source-Backed Alternatives"])
    for alt in report.get("source_backed_alternatives", []):
        if not isinstance(alt, dict):
            continue
        params = ", ".join(str(p) for p in alt.get("parameters", [])) or "none"
        lines.append(
            f"- `{alt.get('option')}`: parameters `{params}`; "
            f"impact `{alt.get('claim_impact')}`; source: {alt.get('source')}"
        )
    return "\n".join(lines) + "\n"


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0.0):
        return None
    return num / den


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
