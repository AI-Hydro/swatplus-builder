"""Mass-balance diagnostic synthesis for physical gate failures."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_mass_balance_diagnostics(
    run_dir: Path | str,
    *,
    physical_gates: dict[str, Any] | None = None,
    values: dict[str, Any] | None = None,
    out_dir: Path | str | None = None,
    gate_context: str | None = None,
    physical_gates_source_path: str | None = None,
) -> dict[str, Any]:
    """Write JSON/Markdown diagnostics for MASS_IMBALANCE blockers."""

    run = Path(run_dir).expanduser().resolve()
    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)

    gates = physical_gates or {}
    vals = values or {}
    wb = _water_balance_summary(gates)
    flags = _classify(wb, gates)
    report = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_dir": str(run),
        "gate_context": gate_context or "unknown",
        "physical_gates_source_path": physical_gates_source_path,
        "physical_gate_status": gates.get("status"),
        "dominant_blocker": gates.get("dominant_blocker"),
        "condition_codes": gates.get("condition_codes") or [],
        "water_balance": wb,
        "diagnostic_flags": flags,
        "next_actions": _next_actions(flags),
        "source_backed_alternatives": _source_backed_alternatives(flags, vals),
        "recommended_probe_order": _recommended_probe_order(flags, vals),
    }

    json_path = destination / "mass_balance_diagnostics.json"
    md_path = destination / "mass_balance_diagnostics.md"
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
    wateryld = _safe_float(wb.get("wateryld"))
    wet_oflo = _safe_float(wb.get("wet_oflo")) or 0.0
    net_wateryld = None
    if wateryld is not None:
        net_wateryld = max(0.0, wateryld - max(0.0, wet_oflo))
    et = _safe_float(wb.get("et"))
    perc = _safe_float(wb.get("perc"))
    latq = _safe_float(wb.get("latq"))
    surq = _safe_float(wb.get("surq_gen"))
    sw_change = _safe_float(wb.get("sw_change"))
    sw_init = _safe_float(wb.get("sw_init"))
    sw_final = _safe_float(wb.get("sw_final"))
    if sw_change is None and sw_init is not None and sw_final is not None:
        sw_change = sw_final - sw_init
    residual = None
    residual_pct = None
    if None not in (precip, net_wateryld, et, perc):
        residual = float(precip) - (float(net_wateryld) + float(et) + float(perc))
        if precip:
            residual_pct = abs(residual) / float(precip) * 100.0
    return {
        "available": True,
        "precip_mm": precip,
        "wateryld_mm": wateryld,
        "wetland_outflow_mm": wet_oflo,
        "net_wateryld_mm": net_wateryld,
        "et_mm": et,
        "perc_mm": perc,
        "latq_mm": latq,
        "surface_runoff_mm": surq,
        "soil_water_change_mm": sw_change,
        "closure_residual_mm": residual,
        "closure_residual_abs_pct_of_precip": residual_pct,
        "wateryld_to_precip": _ratio(wateryld, precip),
        "net_wateryld_to_precip": _ratio(net_wateryld, precip),
        "et_to_precip": _ratio(et, precip),
        "perc_to_precip": _ratio(perc, precip),
        "latq_to_precip": _ratio(latq, precip),
        "surface_runoff_to_precip": _ratio(surq, precip),
        "wetland_outflow_to_precip": _ratio(wet_oflo, precip),
        "soil_water_change_to_precip": _ratio(sw_change, precip),
        "closure_equation": "precip - (max(wateryld - wet_oflo, 0) + et + perc)",
    }


def _classify(wb: dict[str, Any], physical_gates: dict[str, Any]) -> list[dict[str, str]]:
    if not wb.get("available"):
        return [{"code": "mass_balance_context_missing", "evidence": str(wb.get("reason"))}]
    flags: list[dict[str, str]] = []
    codes = set(physical_gates.get("condition_codes") or [])
    residual_pct = _safe_float(wb.get("closure_residual_abs_pct_of_precip"))
    if "MASS_IMBALANCE" in codes or (residual_pct is not None and residual_pct > 5.0):
        evidence = "physical gate reported MASS_IMBALANCE"
        if residual_pct is not None:
            evidence = f"|P-(net_wateryld+ET+perc)|/P={residual_pct / 100.0:.3f}"
        flags.append({"code": "mass_closure_residual_high", "evidence": evidence})
    wetland_outflow = _safe_float(wb.get("wetland_outflow_to_precip"))
    if wetland_outflow is not None and wetland_outflow > 0.05:
        flags.append({"code": "wetland_outflow_material", "evidence": f"wet_oflo/P={wetland_outflow:.3f}"})
    et_p = _safe_float(wb.get("et_to_precip"))
    if et_p is not None and et_p > 0.70:
        flags.append({"code": "et_consumes_precip_during_mass_imbalance", "evidence": f"ET/P={et_p:.3f}"})
    net_wy_p = _safe_float(wb.get("net_wateryld_to_precip"))
    if net_wy_p is not None and net_wy_p < 0.10:
        flags.append({"code": "net_water_yield_low_after_wetland_outflow", "evidence": f"net_wateryld/P={net_wy_p:.3f}"})
    soil_change_p = _safe_float(wb.get("soil_water_change_to_precip"))
    if soil_change_p is not None and abs(soil_change_p) > 0.02:
        flags.append({"code": "soil_storage_change_material", "evidence": f"deltaSW/P={soil_change_p:.3f}"})
    latq_p = _safe_float(wb.get("latq_to_precip"))
    if latq_p is not None and latq_p < 0.01:
        flags.append({"code": "lateral_flow_partition_low", "evidence": f"latq/P={latq_p:.3f}"})
    return flags or [{"code": "mass_imbalance_unclassified", "evidence": "MASS_IMBALANCE gate set without finer ratio flag"}]


def _next_actions(flags: list[dict[str, str]]) -> list[str]:
    codes = {str(flag.get("code")) for flag in flags if isinstance(flag, dict)}
    actions = [
        "Audit basin water-balance closure terms before accepting calibration candidates.",
        "Keep mass-imbalance rows exploratory until the locked physical gate passes.",
    ]
    if "wetland_outflow_material" in codes:
        actions.append("Check wetland storage/outflow accounting before treating wateryld as terminal basin yield.")
    if "et_consumes_precip_during_mass_imbalance" in codes:
        actions.append("Resolve ET partition and PET/soil evaporation drivers before another final skill search.")
    if "net_water_yield_low_after_wetland_outflow" in codes:
        actions.append("Separate wetland outflow accounting from true watershed water yield.")
    if "soil_storage_change_material" in codes:
        actions.append("Check soil-water storage change and warmup adequacy in the mass-closure window.")
    if "lateral_flow_partition_low" in codes:
        actions.append("Inspect subsurface partition controls only after mass accounting is physically closed.")
    return actions


def _source_backed_alternatives(flags: list[dict[str, str]], values: dict[str, Any]) -> list[dict[str, Any]]:
    codes = {str(flag.get("code")) for flag in flags if isinstance(flag, dict)}
    alternatives = [
        {
            "rank": 1,
            "option": "audit_basin_water_balance_closure_terms",
            "source": "Project physical-gate policy and SWAT+ basin water-balance outputs",
            "parameters": [],
            "required_artifacts": ["physical_gates.json", "basin_wb_aa.txt", "basin_wb_yr.txt"],
            "fresh_output_required": False,
            "claim_impact": "research_grade_blocked_until_mass_closure_is_explained",
            "rationale": "The mass gate failed; final hydrograph claims require a physically closed water balance.",
        }
    ]
    if "wetland_outflow_material" in codes or "net_water_yield_low_after_wetland_outflow" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_wetland_storage_and_outflow_accounting",
                "source": "Project wetland water-balance closure policy treats wetland outflow as an internal transfer unless terminal export is proven",
                "parameters": [],
                "required_artifacts": ["physical_gates.json", "wetland output tables", "routing_flow_gates.json"],
                "fresh_output_required": False,
                "claim_impact": "diagnostic_only_until_wetland_accounting_and_locked_physical_gates_pass",
                "rationale": "Material wetland outflow changes the interpretation of wateryld and residual closure.",
            }
        )
    if "et_consumes_precip_during_mass_imbalance" in codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "repair_et_partition_before_mass_claim",
                "source": "SWAT+ ET controls and project ET partition diagnostics",
                "parameters": ["PET_CO", "ESCO", "EPCO"],
                "required_artifacts": ["reports/et_partition_diagnostics.json", "parameter_screen.json"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_only_until_et_mass_and_locked_calibration_gates_pass",
                "rationale": "ET consumes most precipitation in the same gate window as the mass residual.",
            }
        )
    if {"lateral_flow_partition_low", "soil_storage_change_material"} & codes:
        alternatives.append(
            {
                "rank": len(alternatives) + 1,
                "option": "audit_soil_storage_and_subsurface_partition",
                "source": "SWAT+ water-balance partition controls and project parameter governance",
                "parameters": ["PERCO", "LATQ_CO", "LAT_TTIME"],
                "required_artifacts": ["physical_gates.json", "parameter_screen.json", "reports/mass_balance_diagnostics.json"],
                "fresh_output_required": True,
                "claim_impact": "diagnostic_until_mass_physical_and_locked_calibration_gates_pass",
                "rationale": "Mass closure is coupled to soil storage and low lateral-flow partitioning.",
            }
        )
    return alternatives


def _recommended_probe_order(flags: list[dict[str, str]], values: dict[str, Any]) -> list[dict[str, Any]]:
    order: list[dict[str, Any]] = []
    for alt in _source_backed_alternatives(flags, values):
        order.append(
            {
                "rank": alt.get("rank"),
                "diagnostic": alt.get("option"),
                "parameters": alt.get("parameters", []),
                "required_artifacts": alt.get("required_artifacts", []),
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
        ("Closure equation", wb.get("closure_equation")),
        ("Residual %P", _fmt(wb.get("closure_residual_abs_pct_of_precip"))),
        ("P", _fmt(wb.get("precip_mm"))),
        ("Net wateryld", _fmt(wb.get("net_wateryld_mm"))),
        ("ET", _fmt(wb.get("et_mm"))),
        ("Perc", _fmt(wb.get("perc_mm"))),
        ("Wetland outflow/P", _fmt(wb.get("wetland_outflow_to_precip"))),
        ("ET/P", _fmt(wb.get("et_to_precip"))),
    ]
    lines = ["# Mass Balance Diagnostics", "", "| Field | Value |", "|---|---:|"]
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
