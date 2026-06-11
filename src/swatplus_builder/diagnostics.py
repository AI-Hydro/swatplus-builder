"""Structured hydrologic diagnostics (revised Phase 3C.5)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from .errors import SwatBuilderInputError, SwatBuilderPipelineError
from .output.metrics import baseflow_index, kge_components, nse
from .params.governance import FULL_MODE_PARAMETER_GOVERNANCE


class Diagnosis(BaseModel):
    symptom: str
    hypothesis: str
    evidence: str
    evidence_metrics: dict[str, object] = Field(default_factory=dict)
    suggested_parameters: list[str] = Field(default_factory=list)
    suggested_action: str
    source: str


@dataclass(frozen=True)
class _Context:
    df: pd.DataFrame
    nse: float | None
    pbias: float | None
    kge_components: dict[str, float]
    peak_lag_days: int
    peak_lag_metrics: dict[str, object]
    high_flow_ratio: float | None
    high_flow_metrics: dict[str, object]
    volume_bias_pct: float
    bfi_obs: float
    bfi_sim: float
    sim_flat: bool
    recession_ratio: float | None


def diagnose(run_artifact: Path | str) -> list[Diagnosis]:
    """Diagnose structural/model-behavior issues from one run artifact.

    `run_artifact` can be:
    - a directory containing `timeseries.csv` or `outputs/alignment.csv`
    - a direct path to an alignment-style CSV with `obs` and `sim`
    """

    p = Path(run_artifact).expanduser().resolve()
    df, nse_val, pbias = _load_alignment_and_metrics(p)
    if df.empty:
        raise SwatBuilderPipelineError("No overlapping rows for diagnostics", path=str(p))
    ctx = _build_context(df, nse_val=nse_val, pbias=pbias)
    out: list[Diagnosis] = []
    out.extend(_rule_peak_lag(ctx))
    out.extend(_rule_kge_component_deficit(ctx))
    out.extend(_rule_high_flow_attenuated(ctx))
    out.extend(_rule_baseflow_flashy(ctx))
    out.extend(_rule_volume_bias(ctx))
    out.extend(_rule_snow_timing(ctx))
    out.extend(_rule_flat_hydrograph(ctx))
    out.extend(_rule_high_pbias_ok_nse(ctx))
    out.extend(_rule_recession_fast(ctx))
    out.extend(_rule_recession_slow(ctx))
    return out


def write_diagnostics_report(
    diagnoses: list[Diagnosis],
    out_md: Path | str,
    *,
    title: str = "Calibration Diagnostics",
) -> Path:
    p = Path(out_md).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    if not diagnoses:
        lines += ["No rule-based issues detected.", ""]
    for i, d in enumerate(diagnoses, start=1):
        governance = _parameter_governance_summary(d.suggested_parameters)
        lines += [
            f"## {i}. {d.symptom}",
            f"- Hypothesis: {d.hypothesis}",
            f"- Evidence: {d.evidence}",
            f"- Evidence metrics: {json.dumps(d.evidence_metrics, sort_keys=True) if d.evidence_metrics else 'n/a'}",
            f"- Suggested parameters: {', '.join(d.suggested_parameters) if d.suggested_parameters else 'n/a'}",
            f"- Parameter governance: {governance['summary']}",
            f"- Suggested action: {d.suggested_action}",
            f"- Source: {d.source}",
            "",
        ]
    alternatives = _source_backed_alternatives(diagnoses)
    if alternatives:
        lines += ["## Source-Backed Alternatives", ""]
        for alternative in alternatives:
            params = alternative.get("parameters")
            param_text = ", ".join(str(p) for p in params) if isinstance(params, list) and params else "n/a"
            lines += [
                f"- `{alternative.get('option')}`",
                f"  - Parameters: {param_text}",
                f"  - Claim impact: {alternative.get('claim_impact')}",
                f"  - Source: {alternative.get('source')}",
            ]
        lines.append("")
    probe_order = _recommended_probe_order(diagnoses)
    if probe_order:
        lines += ["## Recommended Probe Order", ""]
        for probe in probe_order:
            params = probe.get("parameters")
            param_text = ", ".join(str(p) for p in params) if isinstance(params, list) and params else "n/a"
            lines.append(f"{probe.get('rank')}. `{probe.get('diagnostic')}` ({param_text})")
        lines.append("")
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def write_diagnostics_json_report(
    diagnoses: list[Diagnosis],
    out_json: Path | str,
    *,
    title: str = "Calibration Diagnostics",
) -> Path:
    p = Path(out_json).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    limitation = classify_skill_limitation(diagnoses)
    payload = {
        "title": title,
        "diagnostic_count": len(diagnoses),
        "skill_limitation": limitation,
        "skill_limitation_class": limitation.get("class"),
        "skill_limitation_flags": limitation.get("flags", []),
        "skill_limitation_claim_impact": limitation.get("claim_impact"),
        "diagnostic_flags": [
            {
                "symptom": d.symptom,
                "hypothesis": d.hypothesis,
                "evidence": d.evidence,
                "evidence_metrics": d.evidence_metrics,
                "suggested_parameters": d.suggested_parameters,
                "parameter_governance": _parameter_governance_summary(d.suggested_parameters),
                "suggested_action": d.suggested_action,
                "source": d.source,
            }
            for d in diagnoses
        ],
        "next_actions": [_governed_next_action(d) for d in diagnoses if d.suggested_action],
        "source_backed_alternatives": _source_backed_alternatives(diagnoses),
        "recommended_probe_order": _recommended_probe_order(diagnoses),
    }
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def classify_skill_limitation(diagnoses: list[Diagnosis | dict[str, object]]) -> dict[str, object]:
    """Collapse skill diagnostics into a compact blocker class."""

    flags: list[str] = []
    kge_dominant: str | None = None
    kge_metrics: dict[str, object] = {}
    peak_lag_days: float | None = None
    high_flow_ratio: float | None = None
    for item in diagnoses:
        if isinstance(item, Diagnosis):
            symptom = item.symptom
            metrics = item.evidence_metrics
        elif isinstance(item, dict):
            symptom = str(item.get("symptom") or "")
            raw_metrics = item.get("evidence_metrics")
            metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
        else:
            continue
        lower = symptom.lower()
        if "kge below research threshold" in lower:
            kge_metrics = dict(metrics)
            deficits = {
                "correlation": _num_or_none(metrics.get("correlation_deficit")),
                "variability": _num_or_none(metrics.get("variability_deficit")),
                "bias": _num_or_none(metrics.get("bias_deficit")),
            }
            finite = {key: value for key, value in deficits.items() if value is not None}
            if finite:
                kge_dominant = max(finite, key=lambda key: finite[key])
                flags.append(f"kge_dominant_{kge_dominant}_deficit")
        if "peak timing" in lower or "peak lag" in lower:
            lag = _num_or_none(metrics.get("median_lag_days"))
            if lag is not None:
                peak_lag_days = lag
            flags.append("peak_timing_lag")
        if "high-flow peaks are attenuated" in lower:
            ratio = _num_or_none(metrics.get("top_decile_sim_obs_flow_ratio"))
            if ratio is not None:
                high_flow_ratio = ratio
            flags.append("high_flow_peak_attenuation")
        if "snow" in lower and "timing" in lower:
            flags.append("snow_timing_mismatch")
        if "too flashy" in lower or "low baseflow" in lower:
            flags.append("low_baseflow_flashy_response")
        if "recession limb decays too slowly" in lower:
            flags.append("slow_recession_limb")
        if "volume bias" in lower:
            flags.append("residual_volume_bias")
    unique_flags = list(dict.fromkeys(flags))
    if "snow_timing_mismatch" in unique_flags and (
        "peak_timing_lag" in unique_flags or "high_flow_peak_attenuation" in unique_flags
    ):
        cls = "snow_timing_and_peak_response"
        focus = ["snow_thresholds", "event_timing", "peak_translation"]
    elif "kge_dominant_correlation_deficit" in unique_flags and (
        "peak_timing_lag" in unique_flags or "high_flow_peak_attenuation" in unique_flags
    ):
        cls = "correlation_timing_peak_attenuation"
        focus = ["event_alignment", "channel_attenuation", "runoff_translation"]
    elif "kge_dominant_variability_deficit" in unique_flags or "high_flow_peak_attenuation" in unique_flags:
        cls = "variability_peak_scaling"
        focus = ["peak_magnitude", "hydrograph_variability", "channel_attenuation"]
    elif "kge_dominant_bias_deficit" in unique_flags or "residual_volume_bias" in unique_flags:
        cls = "residual_volume_bias"
        focus = ["et_runoff_partition", "volume_balance", "forcing"]
    elif {"low_baseflow_flashy_response", "slow_recession_limb"} & set(unique_flags):
        cls = "baseflow_recession_partition"
        focus = ["subsurface_partition", "recession_shape", "baseflow_index"]
    elif unique_flags:
        cls = "mixed_skill_limitation"
        focus = ["hydrograph_signature_review"]
    else:
        cls = "no_rule_based_skill_limitation"
        focus = []
    return {
        "class": cls,
        "flags": unique_flags,
        "dominant_kge_component": kge_dominant,
        "kge_components": kge_metrics,
        "peak_lag_days": peak_lag_days,
        "top_decile_sim_obs_flow_ratio": high_flow_ratio,
        "recommended_focus": focus,
        "claim_impact": "diagnostic_only_until_locked_skill_gates_pass",
    }


def _parameter_governance_summary(parameters: list[str]) -> dict[str, object]:
    governed: list[str] = []
    blocked: list[str] = []
    unsupported: list[str] = []
    for parameter in parameters:
        row = FULL_MODE_PARAMETER_GOVERNANCE.get(parameter)
        if row is None:
            unsupported.append(parameter)
        elif row.activity_class == "dead":
            blocked.append(parameter)
        else:
            governed.append(parameter)
    status = "none"
    if unsupported:
        status = "unsupported"
    elif blocked:
        status = "blocked"
    elif governed:
        status = "governed"
    summary_parts = []
    if governed:
        summary_parts.append(f"governed={','.join(governed)}")
    if blocked:
        summary_parts.append(f"blocked={','.join(blocked)}")
    if unsupported:
        summary_parts.append(f"unsupported={','.join(unsupported)}")
    return {
        "status": status,
        "governed_parameters": governed,
        "blocked_parameters": blocked,
        "unsupported_parameters": unsupported,
        "summary": "; ".join(summary_parts) if summary_parts else "no parameter edits suggested",
    }


def _governed_next_action(diagnosis: Diagnosis) -> str:
    governance = _parameter_governance_summary(diagnosis.suggested_parameters)
    unsupported = governance["unsupported_parameters"]
    blocked = governance["blocked_parameters"]
    if unsupported:
        return (
            "Unsupported process-control blocker: do not tune "
            f"{', '.join(str(p) for p in unsupported)} in canonical full-mode calibration "
            "until parameter governance, bridge support, docs, and tests cover them."
        )
    if blocked:
        return (
            "Blocked parameter edit: do not tune "
            f"{', '.join(str(p) for p in blocked)} because current full-mode governance marks it unsupported."
        )
    return diagnosis.suggested_action


def _source_backed_alternatives(diagnoses: list[Diagnosis]) -> list[dict[str, object]]:
    alternatives: list[dict[str, object]] = []
    seen: set[str] = set()

    def add(row: dict[str, object]) -> None:
        option = str(row.get("option") or "")
        if not option or option in seen:
            return
        seen.add(option)
        alternatives.append(row)

    suggested = {
        parameter
        for diagnosis in diagnoses
        for parameter in diagnosis.suggested_parameters
    }
    has_structural = any(not diagnosis.suggested_parameters for diagnosis in diagnoses)

    if "SURLAG" in suggested:
        add(
            {
                "option": "audit_surface_runoff_lag_and_peak_timing",
                "parameters": ["SURLAG"],
                "required_artifacts": [
                    "calibration/hydrograph_comparison/hydrograph_comparison_metrics.json",
                    "calibration_provenance.json",
                    "parameters.bsn",
                ],
                "source": "SWAT+ surq_lag documentation",
                "source_url": "https://swatplus.gitbook.io/io-docs/introduction-1/basin-1/parameters.bsn/surq_lag",
                "claim_impact": "diagnostic until retained by basin-specific locked verification",
            }
        )
    if {"CH_N2", "CH_K2"} & suggested:
        params = [p for p in ("CH_N2", "CH_K2") if p in suggested]
        add(
            {
                "option": "screen_channel_routing_attenuation_controls",
                "parameters": params,
                "required_artifacts": [
                    "hyd-sed-lte.cha",
                    "channel-lte.cha",
                    "routing_flow_gates.json",
                    "calibration/hydrograph_comparison/hydrograph_comparison_metrics.json",
                ],
                "source": "SWAT+ channel hydrology documentation and Manning flow/velocity equations",
                "source_url": "https://swatplus.gitbook.io/io-docs/introduction-1/channels/hyd-sed-lte.cha",
                "claim_impact": "diagnostic until retained by basin-specific channel-routing screen and locked verification",
            }
        )
    if {"PET_CO", "CN2", "ESCO", "EPCO"} & suggested:
        params = [p for p in ("PET_CO", "ESCO", "EPCO", "CN2") if p in suggested]
        add(
            {
                "option": "rebalance_runoff_and_et_partition",
                "parameters": params,
                "required_artifacts": [
                    "physical_gates.json",
                    "reports/volume_bias_diagnostics.json",
                    "hydrology.hyd",
                    "cntable.lum",
                    "urban.urb",
                ],
                "source": "SWAT+ calibration water-balance guidance",
                "source_url": "https://swatplus.gitbook.io/io-docs/introduction-1/calibration",
                "claim_impact": "diagnostic until physical gates and locked calibration improve",
            }
        )
    if {"ALPHA_BF", "LATQ_CO", "LAT_TTIME", "PERCO", "RCHG_DP"} & suggested:
        params = [p for p in ("LAT_TTIME", "LATQ_CO", "PERCO", "ALPHA_BF", "RCHG_DP") if p in suggested]
        add(
            {
                "option": "audit_baseflow_recession_and_subsurface_partition",
                "parameters": params,
                "required_artifacts": [
                    "calibration/hydrograph_comparison/hydrograph_comparison_metrics.json",
                    "hydrology.hyd",
                    "aquifer.aqu",
                    "reports/soil_report.json",
                ],
                "source": "SWAT+ lateral-flow lag documentation and full-mode source-code calibration path",
                "source_url": "https://swatplus.gitbook.io/io-docs/theoretical-documentation/section-2-hydrology/chapter-2-3-soil-water/2-3.5-lateral-flow/2-3.4.1-lateral-flow-lag",
                "claim_impact": "diagnostic until soil provenance and routing gates are defensible",
            }
        )
    if "GW_DELAY" in suggested:
        add(
            {
                "option": "replace_legacy_gw_delay_advice_with_supported_alpha_and_partition_controls",
                "parameters": ["LAT_TTIME", "LATQ_CO", "PERCO", "ALPHA_BF", "RCHG_DP"],
                "blocked_parameters": ["GW_DELAY"],
                "required_artifacts": [
                    "calibration/skill_diagnostics/skill_diagnostics.json",
                    "parameter_screen.json",
                    "hydrology.hyd",
                    "aquifer.aqu",
                ],
                "source": "SWAT+ lateral-flow lag documentation and user-list guidance replacing legacy GW_DELAY advice",
                "source_url": "https://swatplus.gitbook.io/io-docs/theoretical-documentation/section-2-hydrology/chapter-2-3-soil-water/2-3.5-lateral-flow/2-3.4.1-lateral-flow-lag",
                "claim_impact": "do not tune GW_DELAY; screen supported full-mode recession controls instead",
            }
        )
    if {"SFTMP", "SMTMP"} & suggested:
        params = [p for p in ("SFTMP", "SMTMP") if p in suggested]
        add(
            {
                "option": "audit_snow_rain_partition_and_melt_thresholds",
                "parameters": params,
                "required_artifacts": [
                    "snow.sno",
                    "calibration_provenance.json",
                    "calibration/hydrograph_comparison/hydrograph_comparison_metrics.json",
                ],
                "source": "SWAT+ snow.sno documentation and governed bridge tests",
                "source_url": "https://swatplus.gitbook.io/io-docs/introduction-1/hydrologic-response-units/snow.sno",
                "claim_impact": "diagnostic until retained by basin-specific snow screen",
            }
        )
    if has_structural:
        add(
            {
                "option": "validate_outlet_routing_and_output_source_before_parameter_search",
                "parameters": [],
                "required_artifacts": [
                    "outlet_provenance.json",
                    "routing_flow_gates.json",
                    "reports/mass_trace.json",
                ],
                "source": "internal routed-flow and outlet-provenance gate contract",
                "source_url": "docs/SCIENTIFIC_CLAIM_GOVERNANCE.md",
                "claim_impact": "blocks calibration claims until structural evidence is repaired",
            }
        )
    return alternatives


def _recommended_probe_order(diagnoses: list[Diagnosis]) -> list[dict[str, object]]:
    probes: list[dict[str, object]] = []
    for index, alternative in enumerate(_source_backed_alternatives(diagnoses), start=1):
        probes.append(
            {
                "rank": index,
                "diagnostic": alternative.get("option"),
                "parameters": alternative.get("parameters", []),
                "blocked_parameters": alternative.get("blocked_parameters", []),
                "required_artifacts": alternative.get("required_artifacts", []),
                "claim_impact": alternative.get("claim_impact"),
            }
        )
    return probes


def _load_alignment_and_metrics(path: Path) -> tuple[pd.DataFrame, float | None, float | None]:
    csv_candidates: list[Path] = []
    if path.is_file():
        csv_candidates.append(path)
    else:
        csv_candidates.extend(
            [
                path / "timeseries.csv",
                path / "outputs" / "alignment.csv",
                path / "alignment.csv",
            ]
        )
    alignment = next((c for c in csv_candidates if c.exists()), None)
    if alignment is None:
        raise SwatBuilderInputError(
            "No alignment/timeseries CSV found for diagnostics", path=str(path)
        )
    df = pd.read_csv(alignment, index_col=0, parse_dates=True)
    if "obs" not in df.columns or "sim" not in df.columns:
        raise SwatBuilderInputError("Alignment CSV must contain 'obs' and 'sim'", path=str(alignment))
    df = df[["obs", "sim"]].astype(float).dropna()

    nse_val: float | None = None
    pbias: float | None = None
    metrics_path = path / "metrics.json" if path.is_dir() else None
    if metrics_path and metrics_path.exists():
        try:
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
            if isinstance(payload.get("nse"), (int, float)):
                nse_val = float(payload["nse"])
            if isinstance(payload.get("pbias"), (int, float)):
                pbias = float(payload["pbias"])
        except Exception:
            pass
    if nse_val is None and len(df) > 1:
        nse_val = float(nse(df["obs"].tolist(), df["sim"].tolist()))
    if pbias is None:
        obs_sum = float(df["obs"].sum())
        sim_sum = float(df["sim"].sum())
        pbias = ((sim_sum - obs_sum) / obs_sum * 100.0) if obs_sum != 0 else None
    return df, nse_val, pbias


def _build_context(df: pd.DataFrame, *, nse_val: float | None, pbias: float | None) -> _Context:
    peak_lag_metrics = _annual_peak_lag_summary(df)
    lag = int(peak_lag_metrics.get("median_lag_days", _global_peak_lag_days(df)))
    high_flow_metrics = _high_flow_summary(df)
    high_flow_ratio = _num_or_none(high_flow_metrics.get("top_decile_sim_obs_flow_ratio"))
    obs_sum = float(df["obs"].sum())
    sim_sum = float(df["sim"].sum())
    vol_bias = ((sim_sum - obs_sum) / obs_sum * 100.0) if obs_sum != 0 else 0.0
    obs = df["obs"].tolist()
    sim = df["sim"].tolist()
    kge_parts = kge_components(obs, sim)
    bfi_obs = float(baseflow_index(obs))
    bfi_sim = float(baseflow_index(sim))
    sim_flat = float(df["sim"].std()) < max(1e-6, 0.05 * float(df["obs"].mean() if len(df) else 0.0))
    recession_ratio = _recession_ratio(df)
    return _Context(
        df=df,
        nse=nse_val,
        pbias=pbias,
        kge_components=kge_parts,
        peak_lag_days=lag,
        peak_lag_metrics=peak_lag_metrics,
        high_flow_ratio=high_flow_ratio,
        high_flow_metrics=high_flow_metrics,
        volume_bias_pct=vol_bias,
        bfi_obs=bfi_obs,
        bfi_sim=bfi_sim,
        sim_flat=sim_flat,
        recession_ratio=recession_ratio,
    )


def _annual_peak_lag_days(df: pd.DataFrame, *, window_days: int = 7) -> int:
    return int(_annual_peak_lag_summary(df, window_days=window_days).get("median_lag_days", 0))


def _annual_peak_lag_summary(df: pd.DataFrame, *, window_days: int = 7) -> dict[str, object]:
    if len(df) < 30:
        return {
            "method": "global_peak",
            "median_lag_days": _global_peak_lag_days(df),
            "event_count": 1,
            "window_days": None,
        }
    lags: list[int] = []
    water_year = df.index.year + (df.index.month >= 10).astype(int)
    for year, group in df.groupby(water_year):
        if len(group) < 30:
            continue
        obs_peak = pd.to_datetime(group["obs"].idxmax())
        window = df.loc[
            (df.index >= obs_peak - pd.Timedelta(days=window_days))
            & (df.index <= obs_peak + pd.Timedelta(days=window_days))
        ]
        if window.empty:
            continue
        sim_peak = pd.to_datetime(window["sim"].idxmax())
        lags.append(int((sim_peak - obs_peak).days))
    if not lags:
        return {
            "method": "global_peak",
            "median_lag_days": _global_peak_lag_days(df),
            "event_count": 1,
            "window_days": None,
        }
    series = pd.Series(lags)
    return {
        "method": "annual_peak_local_window",
        "median_lag_days": int(round(float(series.median()))),
        "mean_lag_days": float(series.mean()),
        "min_lag_days": int(series.min()),
        "max_lag_days": int(series.max()),
        "event_count": int(len(lags)),
        "window_days": int(window_days),
    }


def _global_peak_lag_days(df: pd.DataFrame) -> int:
    peak_obs = pd.to_datetime(df["obs"].idxmax())
    peak_sim = pd.to_datetime(df["sim"].idxmax())
    return int((peak_sim - peak_obs).days)


def _high_flow_ratio(df: pd.DataFrame) -> float | None:
    return _num_or_none(_high_flow_summary(df).get("top_decile_sim_obs_flow_ratio"))


def _high_flow_summary(df: pd.DataFrame) -> dict[str, object]:
    if len(df) < 10:
        return {}
    threshold = float(df["obs"].quantile(0.90))
    high = df[df["obs"] >= threshold]
    if high.empty:
        return {}
    obs_mean = float(high["obs"].mean())
    if obs_mean <= 0.0:
        return {}
    sim_mean = float(high["sim"].mean())
    obs_total = float(df["obs"].sum())
    sim_total = float(df["sim"].sum())
    high_obs_total = float(high["obs"].sum())
    high_sim_total = float(high["sim"].sum())
    return {
        "method": "observed_top_decile_days",
        "obs_q90_threshold": threshold,
        "top_decile_day_count": int(len(high)),
        "top_decile_obs_mean": obs_mean,
        "top_decile_sim_mean": sim_mean,
        "top_decile_sim_obs_flow_ratio": sim_mean / obs_mean,
        "top_decile_obs_volume_fraction": (high_obs_total / obs_total) if obs_total else None,
        "top_decile_sim_volume_fraction": (high_sim_total / sim_total) if sim_total else None,
    }


def _num_or_none(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _recession_ratio(df: pd.DataFrame) -> float | None:
    if len(df) < 10:
        return None
    # Use post-peak 7-day relative decline as a simple recession proxy.
    i_obs = int(df["obs"].values.argmax())
    i_sim = int(df["sim"].values.argmax())
    if i_obs + 7 >= len(df) or i_sim + 7 >= len(df):
        return None
    o0 = float(df["obs"].iloc[i_obs])
    o7 = float(df["obs"].iloc[i_obs + 7])
    s0 = float(df["sim"].iloc[i_sim])
    s7 = float(df["sim"].iloc[i_sim + 7])
    if o0 <= 0 or s0 <= 0:
        return None
    obs_drop = (o0 - o7) / o0
    sim_drop = (s0 - s7) / s0
    if obs_drop == 0:
        return None
    return float(sim_drop / obs_drop)


def _rule_peak_lag(ctx: _Context) -> list[Diagnosis]:
    if abs(ctx.peak_lag_days) <= 1:
        return []
    return [
        Diagnosis(
            symptom="Peak timing lag exceeds 1 day",
            hypothesis="Surface runoff translation lag is mis-specified.",
            evidence=f"peak_lag_days={ctx.peak_lag_days}",
            evidence_metrics=ctx.peak_lag_metrics,
            suggested_parameters=["SURLAG"],
            suggested_action="Adjust SURLAG and rerun timing-focused calibration window.",
            source="SWATdoctR-inspired hydrograph timing protocol; SWAT+ parameter guidance.",
        )
    ]


def _rule_kge_component_deficit(ctx: _Context) -> list[Diagnosis]:
    parts = ctx.kge_components
    kge_value = _num_or_none(parts.get("kge"))
    if kge_value is None or kge_value >= 0.40:
        return []
    deficits = {
        "correlation": _num_or_none(parts.get("correlation_deficit")),
        "variability": _num_or_none(parts.get("variability_deficit")),
        "bias": _num_or_none(parts.get("bias_deficit")),
    }
    finite_deficits = {k: v for k, v in deficits.items() if v is not None}
    if not finite_deficits:
        return []
    dominant = max(finite_deficits, key=lambda key: finite_deficits[key])
    suggested = {
        "correlation": ["SURLAG", "CH_N2", "CH_K2"],
        "variability": ["CN2", "SURLAG", "CH_N2", "CH_K2"],
        "bias": ["PET_CO", "ESCO", "EPCO", "CN2"],
    }[dominant]
    action = {
        "correlation": "Prioritize timing, routing attenuation, and event alignment before widening volume controls.",
        "variability": "Prioritize peak scaling and hydrograph variability controls before additional volume matching.",
        "bias": "Prioritize ET/runoff partition controls before timing-only calibration.",
    }[dominant]
    return [
        Diagnosis(
            symptom=f"KGE below research threshold with dominant {dominant} deficit",
            hypothesis="KGE component decomposition identifies which part of the hydrograph skill is limiting the claim.",
            evidence=(
                f"kge={kge_value:.3f}, r={parts.get('r'):.3f}, "
                f"alpha={parts.get('alpha'):.3f}, beta={parts.get('beta'):.3f}"
            ),
            evidence_metrics=parts,
            suggested_parameters=suggested,
            suggested_action=action,
            source="Kling-Gupta Efficiency component decomposition (Gupta et al. 2009).",
        )
    ]


def _rule_high_flow_attenuated(ctx: _Context) -> list[Diagnosis]:
    if ctx.high_flow_ratio is None or ctx.high_flow_ratio >= 0.60:
        return []
    return [
        Diagnosis(
            symptom="High-flow peaks are attenuated relative to observed events",
            hypothesis="Runoff translation or runoff generation is smoothing peak flows after volume is matched.",
            evidence=f"top_decile_sim_obs_flow_ratio={ctx.high_flow_ratio:.3f}",
            evidence_metrics=ctx.high_flow_metrics,
            suggested_parameters=["SURLAG", "CN2", "CH_N2", "CH_K2"],
            suggested_action=(
                "Run a peak-magnitude calibration probe over SURLAG, CN2, and governed channel-routing "
                "controls, then inspect routing/channel attenuation if peaks remain muted."
            ),
            source="SWAT+ surface-runoff lag documentation and peak-flow signature diagnostics.",
        )
    ]


def _rule_baseflow_flashy(ctx: _Context) -> list[Diagnosis]:
    if not (ctx.bfi_sim + 0.1 < ctx.bfi_obs):
        return []
    return [
        Diagnosis(
            symptom="Simulated hydrograph is too flashy with low baseflow component",
            hypothesis="Subsurface partitioning and recession controls are too restrictive.",
            evidence=f"bfi_obs={ctx.bfi_obs:.3f}, bfi_sim={ctx.bfi_sim:.3f}",
            suggested_parameters=["PERCO", "LATQ_CO", "LAT_TTIME", "ALPHA_BF", "RCHG_DP"],
            suggested_action=(
                "Screen supported full-mode subsurface partition and recession controls before any "
                "baseflow calibration claim."
            ),
            source=(
                "SWATdoctR-inspired baseflow diagnostics; SWAT+ lateral-flow lag and aquifer "
                "parameter behavior under full-mode governance."
            ),
        )
    ]


def _rule_volume_bias(ctx: _Context) -> list[Diagnosis]:
    if abs(ctx.volume_bias_pct) <= 15.0:
        return []
    return [
        Diagnosis(
            symptom="Total flow volume bias exceeds 15%",
            hypothesis="Water balance partitioning is biased at runoff/ET level.",
            evidence=f"volume_bias_pct={ctx.volume_bias_pct:.1f}",
            suggested_parameters=["CN2", "ESCO", "EPCO"],
            suggested_action="Rebalance runoff generation vs ET loss with CN2/ET controls.",
            source="SWATdoctR-inspired water-balance diagnostics; SWAT+ hydrology guidance.",
        )
    ]


def _rule_snow_timing(ctx: _Context) -> list[Diagnosis]:
    # Simple seasonality proxy: compare month of annual peak.
    m_obs = int(pd.to_datetime(ctx.df["obs"].idxmax()).month)
    m_sim = int(pd.to_datetime(ctx.df["sim"].idxmax()).month)
    if abs(m_obs - m_sim) <= 1:
        return []
    return [
        Diagnosis(
            symptom="Seasonal peak timing mismatch suggests snowmelt timing error",
            hypothesis="Snow/rain partition or melt threshold parameters are off.",
            evidence=f"peak_month_obs={m_obs}, peak_month_sim={m_sim}",
            suggested_parameters=["SFTMP", "SMTMP"],
            suggested_action="Tune snowfall and snowmelt threshold temperatures.",
            source="SWATdoctR-inspired cryosphere checks; SWAT+ snow parameter docs.",
        )
    ]


def _rule_flat_hydrograph(ctx: _Context) -> list[Diagnosis]:
    if not (ctx.sim_flat and float(ctx.df["obs"].mean()) > 0.0):
        return []
    return [
        Diagnosis(
            symptom="Simulated hydrograph is near-flat while observed flow is positive",
            hypothesis="Outlet selection or routing configuration is structurally wrong.",
            evidence=f"sim_std={float(ctx.df['sim'].std()):.6f}, obs_mean={float(ctx.df['obs'].mean()):.6f}",
            suggested_parameters=[],
            suggested_action="Validate outlet GIS ID, routing connectivity, and output source file selection.",
            source="Internal structural-routing diagnostics protocol.",
        )
    ]


def _rule_high_pbias_ok_nse(ctx: _Context) -> list[Diagnosis]:
    if ctx.pbias is None or ctx.nse is None:
        return []
    if not (abs(ctx.pbias) > 15.0 and ctx.nse >= 0.3):
        return []
    return [
        Diagnosis(
            symptom="High PBIAS despite acceptable NSE",
            hypothesis="Hydrograph shape is captured but water balance is biased (often ET).",
            evidence=f"nse={ctx.nse:.3f}, pbias={ctx.pbias:.1f}",
            suggested_parameters=["ESCO", "EPCO", "CN2"],
            suggested_action="Prioritize ET and runoff partition tuning with volume-focused objective weighting.",
            source="SWATdoctR-inspired multi-metric interpretation guidance.",
        )
    ]


def _rule_recession_fast(ctx: _Context) -> list[Diagnosis]:
    if ctx.recession_ratio is None or ctx.recession_ratio <= 1.2:
        return []
    return [
        Diagnosis(
            symptom="Recession limb decays too quickly",
            hypothesis="Lateral/baseflow release is too fast.",
            evidence=f"recession_ratio={ctx.recession_ratio:.2f} (sim/obs)",
            suggested_parameters=["LAT_TTIME"],
            suggested_action="Increase LAT_TTIME and rerun recession-focused locked screening.",
            source="SWATdoctR-inspired recession analysis; SWAT+ lateral-flow lag documentation.",
        )
    ]


def _rule_recession_slow(ctx: _Context) -> list[Diagnosis]:
    if ctx.recession_ratio is None or ctx.recession_ratio >= 0.8:
        return []
    return [
        Diagnosis(
            symptom="Recession limb decays too slowly",
            hypothesis="Lateral/baseflow release is too persistent.",
            evidence=f"recession_ratio={ctx.recession_ratio:.2f} (sim/obs)",
            suggested_parameters=["LAT_TTIME"],
            suggested_action="Reduce LAT_TTIME and rerun recession-focused locked screening.",
            source="SWATdoctR-inspired recession analysis; SWAT+ lateral-flow lag documentation.",
        )
    ]
