"""Structured hydrologic diagnostics (revised Phase 3C.5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from .errors import SwatBuilderInputError, SwatBuilderPipelineError
from .output.metrics import baseflow_index, nse


class Diagnosis(BaseModel):
    symptom: str
    hypothesis: str
    evidence: str
    suggested_parameters: list[str] = Field(default_factory=list)
    suggested_action: str
    source: str


@dataclass(frozen=True)
class _Context:
    df: pd.DataFrame
    nse: float | None
    pbias: float | None
    peak_lag_days: int
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
        lines += [
            f"## {i}. {d.symptom}",
            f"- Hypothesis: {d.hypothesis}",
            f"- Evidence: {d.evidence}",
            f"- Suggested parameters: {', '.join(d.suggested_parameters) if d.suggested_parameters else 'n/a'}",
            f"- Suggested action: {d.suggested_action}",
            f"- Source: {d.source}",
            "",
        ]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


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
    peak_obs = pd.to_datetime(df["obs"].idxmax())
    peak_sim = pd.to_datetime(df["sim"].idxmax())
    lag = int((peak_sim - peak_obs).days)
    obs_sum = float(df["obs"].sum())
    sim_sum = float(df["sim"].sum())
    vol_bias = ((sim_sum - obs_sum) / obs_sum * 100.0) if obs_sum != 0 else 0.0
    obs = df["obs"].tolist()
    sim = df["sim"].tolist()
    bfi_obs = float(baseflow_index(obs))
    bfi_sim = float(baseflow_index(sim))
    sim_flat = float(df["sim"].std()) < max(1e-6, 0.05 * float(df["obs"].mean() if len(df) else 0.0))
    recession_ratio = _recession_ratio(df)
    return _Context(
        df=df,
        nse=nse_val,
        pbias=pbias,
        peak_lag_days=lag,
        volume_bias_pct=vol_bias,
        bfi_obs=bfi_obs,
        bfi_sim=bfi_sim,
        sim_flat=sim_flat,
        recession_ratio=recession_ratio,
    )


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
            suggested_parameters=["SURLAG"],
            suggested_action="Adjust SURLAG and rerun timing-focused calibration window.",
            source="SWATdoctR-inspired hydrograph timing protocol; SWAT+ parameter guidance.",
        )
    ]


def _rule_baseflow_flashy(ctx: _Context) -> list[Diagnosis]:
    if not (ctx.bfi_sim + 0.1 < ctx.bfi_obs):
        return []
    return [
        Diagnosis(
            symptom="Simulated hydrograph is too flashy with low baseflow component",
            hypothesis="Groundwater recession and delay controls are too restrictive.",
            evidence=f"bfi_obs={ctx.bfi_obs:.3f}, bfi_sim={ctx.bfi_sim:.3f}",
            suggested_parameters=["ALPHA_BF", "GW_DELAY", "GWQMN"],
            suggested_action="Increase baseflow persistence and revisit groundwater thresholds.",
            source="SWATdoctR-inspired baseflow diagnostics; SWAT+ aquifer parameter behavior.",
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
            hypothesis="Groundwater recession is too fast.",
            evidence=f"recession_ratio={ctx.recession_ratio:.2f} (sim/obs)",
            suggested_parameters=["ALPHA_BF"],
            suggested_action="Reduce ALPHA_BF to slow simulated recession.",
            source="SWATdoctR-inspired recession analysis; SWAT+ baseflow parameter behavior.",
        )
    ]


def _rule_recession_slow(ctx: _Context) -> list[Diagnosis]:
    if ctx.recession_ratio is None or ctx.recession_ratio >= 0.8:
        return []
    return [
        Diagnosis(
            symptom="Recession limb decays too slowly",
            hypothesis="Groundwater delay/storage release is too persistent.",
            evidence=f"recession_ratio={ctx.recession_ratio:.2f} (sim/obs)",
            suggested_parameters=["GW_DELAY"],
            suggested_action="Increase GW_DELAY and reassess baseflow timing.",
            source="SWATdoctR-inspired recession analysis; SWAT+ groundwater timing behavior.",
        )
    ]
