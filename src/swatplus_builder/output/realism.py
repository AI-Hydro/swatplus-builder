"""Physical realism audit for SWAT+ alignment outputs.

Operates entirely on ``alignment.csv`` files produced by :func:`evaluate_run`
— no SWAT+ engine binary required. Provides:

1. :func:`split_cal_val`    — split an alignment DataFrame into calibration /
                              validation sub-periods.
2. :func:`audit_realism`    — compute a :class:`RealismAudit` from a single
                              alignment CSV (or DataFrame).
3. :func:`run_realism_audit` — run audit over multiple basins and write
                               ``realism_audit.json`` + ``realism_audit.md``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Cal / Val split
# ---------------------------------------------------------------------------

class CalValSplit(BaseModel):
    """Result of splitting a time series into calibration and validation periods."""

    cal_start: str
    cal_end: str
    val_start: str | None = None
    val_end: str | None = None
    cal_n: int = 0
    val_n: int = 0
    split_year: int | None = None


def split_cal_val(
    df: pd.DataFrame,
    *,
    cal_fraction: float = 0.7,
    split_year: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, CalValSplit]:
    """Split ``df`` into calibration and validation sub-periods.

    Args:
        df:            DataFrame with a DatetimeIndex and columns ``obs`` / ``sim``.
        cal_fraction:  Fraction of rows to use for calibration when ``split_year``
                       is not provided (default 0.70 → first 70%).
        split_year:    If provided, calibration = rows before Jan 1 of this year.

    Returns:
        ``(cal_df, val_df, CalValSplit)``
    """
    df = df.sort_index().dropna(subset=["obs", "sim"])
    if df.empty:
        empty = pd.DataFrame(columns=df.columns)
        split = CalValSplit(cal_start="", cal_end="", cal_n=0, val_n=0)
        return empty, empty, split

    if split_year is not None:
        cutoff = pd.Timestamp(f"{split_year}-01-01")
        cal_df = df[df.index < cutoff]
        val_df = df[df.index >= cutoff]
    else:
        n_cal = max(1, int(len(df) * cal_fraction))
        cal_df = df.iloc[:n_cal]
        val_df = df.iloc[n_cal:]

    split = CalValSplit(
        cal_start=str(cal_df.index[0].date()) if len(cal_df) else "",
        cal_end=str(cal_df.index[-1].date()) if len(cal_df) else "",
        val_start=str(val_df.index[0].date()) if len(val_df) else None,
        val_end=str(val_df.index[-1].date()) if len(val_df) else None,
        cal_n=len(cal_df),
        val_n=len(val_df),
        split_year=split_year,
    )
    return cal_df, val_df, split


# ---------------------------------------------------------------------------
# Realism metrics helpers
# ---------------------------------------------------------------------------

def _nse(obs: np.ndarray, sim: np.ndarray) -> float:
    denom = np.sum((obs - obs.mean()) ** 2)
    if denom == 0:
        return float("nan")
    return float(1.0 - np.sum((obs - sim) ** 2) / denom)


def _kge(obs: np.ndarray, sim: np.ndarray) -> float:
    if obs.std() == 0 or sim.std() == 0 or len(obs) < 2:
        return float("nan")
    r = float(np.corrcoef(obs, sim)[0, 1])
    alpha = float(sim.std() / obs.std())
    beta  = float(sim.mean() / obs.mean()) if obs.mean() != 0 else float("nan")
    if np.isnan(beta):
        return float("nan")
    return float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def _pbias(obs: np.ndarray, sim: np.ndarray) -> float:
    obs_sum = float(obs.sum())
    if obs_sum == 0:
        return float("nan")
    return float(100.0 * (sim.sum() - obs_sum) / obs_sum)


def _bfi(q: np.ndarray, alpha: float = 0.925) -> float:
    """Simple recursive digital filter baseflow index."""
    if len(q) < 3:
        return float("nan")
    bf = np.zeros_like(q, dtype=float)
    bf[0] = q[0]
    for i in range(1, len(q)):
        bf[i] = min(alpha * bf[i - 1] + (1 - alpha) / 2 * (q[i] + q[i - 1]), q[i])
    total = float(q.sum())
    return float(bf.sum() / total) if total > 0 else float("nan")


def _seasonal_nse(df: pd.DataFrame) -> dict[str, float]:
    """NSE per meteorological season (DJF, MAM, JJA, SON)."""
    season_map = {12: "DJF", 1: "DJF", 2: "DJF",
                  3: "MAM", 4: "MAM", 5: "MAM",
                  6: "JJA", 7: "JJA", 8: "JJA",
                  9: "SON", 10: "SON", 11: "SON"}
    result: dict[str, float] = {}
    df = df.copy()
    df["season"] = df.index.month.map(season_map)
    for s in ("DJF", "MAM", "JJA", "SON"):
        sub = df[df["season"] == s].dropna(subset=["obs", "sim"])
        if len(sub) >= 5:
            result[s] = _nse(sub["obs"].values, sub["sim"].values)
        else:
            result[s] = float("nan")
    return result


def _flow_ratio(obs: np.ndarray, sim: np.ndarray, pct: float) -> float:
    """Ratio sim/obs at a given percentile (e.g. 90 for high flows, 10 for low)."""
    obs_q = float(np.percentile(obs, pct))
    sim_q = float(np.percentile(sim, pct))
    if obs_q == 0:
        return float("nan")
    return sim_q / obs_q


# ---------------------------------------------------------------------------
# RealismAudit model
# ---------------------------------------------------------------------------

class PeriodMetrics(BaseModel):
    """Metrics for one time period (full, calibration, or validation)."""

    n_days: int = 0
    nse: float | None = None
    kge: float | None = None
    pbias_pct: float | None = None
    bfi_obs: float | None = None
    bfi_sim: float | None = None
    bfi_ratio: float | None = None
    q90_ratio: float | None = None
    q10_ratio: float | None = None
    seasonal_nse: dict[str, float] = Field(default_factory=dict)


class RealismAudit(BaseModel):
    """Comprehensive physical realism characterization of one basin alignment."""

    basin_id: str
    alignment_csv: str
    generated_at: str
    period_full: PeriodMetrics = Field(default_factory=PeriodMetrics)
    period_cal: PeriodMetrics | None = None
    period_val: PeriodMetrics | None = None
    cal_val_split: CalValSplit | None = None
    pathologies: list[str] = Field(default_factory=list)
    realism_verdict: str = "unknown"

    @property
    def has_validation(self) -> bool:
        return self.period_val is not None and self.period_val.n_days > 0


def _compute_period_metrics(df: pd.DataFrame) -> PeriodMetrics:
    df = df.dropna(subset=["obs", "sim"])
    if len(df) < 2:
        return PeriodMetrics(n_days=len(df))
    obs = df["obs"].values.astype(float)
    sim = df["sim"].values.astype(float)
    bfi_o = _bfi(obs)
    bfi_s = _bfi(sim)
    bfi_r = (bfi_s / bfi_o) if (not np.isnan(bfi_o) and bfi_o > 0) else float("nan")
    return PeriodMetrics(
        n_days=len(df),
        nse=_nse(obs, sim),
        kge=_kge(obs, sim),
        pbias_pct=_pbias(obs, sim),
        bfi_obs=float(bfi_o),
        bfi_sim=float(bfi_s),
        bfi_ratio=float(bfi_r) if not np.isnan(bfi_r) else None,
        q90_ratio=_flow_ratio(obs, sim, 90),
        q10_ratio=_flow_ratio(obs, sim, 10),
        seasonal_nse=_seasonal_nse(df),
    )


def _detect_pathologies(full: PeriodMetrics, val: PeriodMetrics | None) -> list[str]:
    """Return a list of detected physical pathology strings."""
    issues = []
    if full.pbias_pct is not None and abs(full.pbias_pct) > 25:
        direction = "over" if full.pbias_pct > 0 else "under"
        issues.append(f"Volume bias: model {direction}estimates by {abs(full.pbias_pct):.1f}%")
    if full.bfi_ratio is not None and full.bfi_ratio > 1.25:
        issues.append(
            f"Baseflow overestimation: BFI_sim/BFI_obs = {full.bfi_ratio:.2f} "
            f"(sim BFI={full.bfi_sim:.3f}, obs BFI={full.bfi_obs:.3f})"
        )
    if full.bfi_ratio is not None and full.bfi_ratio < 0.75:
        issues.append(
            f"Baseflow underestimation: BFI_sim/BFI_obs = {full.bfi_ratio:.2f}"
        )
    if full.q90_ratio is not None and full.q90_ratio > 1.5:
        issues.append(f"High-flow overestimation: Q90_sim/Q90_obs = {full.q90_ratio:.2f}")
    if full.q90_ratio is not None and full.q90_ratio < 0.67:
        issues.append(f"High-flow underestimation: Q90_sim/Q90_obs = {full.q90_ratio:.2f}")
    if full.q10_ratio is not None and full.q10_ratio > 2.0:
        issues.append(f"Low-flow severe overestimation: Q10_sim/Q10_obs = {full.q10_ratio:.2f}")
    if full.nse is not None and full.nse < 0.0:
        issues.append(f"NSE < 0: model worse than mean-flow benchmark (NSE={full.nse:.3f})")
    if val is not None and val.nse is not None and full.nse is not None:
        if full.nse - val.nse > 0.15:
            issues.append(
                f"Overfitting signal: cal NSE={full.nse:.3f} but val NSE={val.nse:.3f} "
                f"(drop = {full.nse - val.nse:.3f})"
            )
    seasonal = full.seasonal_nse
    for s, nse_s in seasonal.items():
        if not np.isnan(nse_s) and nse_s < -0.5:
            issues.append(f"Severe seasonal skill deficit in {s}: NSE={nse_s:.3f}")
    return issues


def _realism_verdict(pathologies: list[str], nse: float | None) -> str:
    if nse is None:
        return "insufficient_data"
    if len(pathologies) == 0 and nse >= 0.5:
        return "benchmark_grade"
    if len(pathologies) == 0 and nse >= 0.0:
        return "improving"
    if len(pathologies) <= 2 and nse >= 0.0:
        return "improving_with_pathologies"
    if nse < 0.0:
        return "below_benchmark"
    return "pathological"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def audit_realism(
    alignment_csv: Path | str,
    *,
    basin_id: str | None = None,
    split_year: int | None = None,
    cal_fraction: float = 0.7,
) -> RealismAudit:
    """Compute a :class:`RealismAudit` from an alignment CSV.

    Args:
        alignment_csv: Path to alignment CSV with columns ``obs``, ``sim`` and
                       a DatetimeIndex (or date column as first column).
        basin_id:      Optional identifier; inferred from filename if omitted.
        split_year:    If set, split calibration/validation at this year boundary.
        cal_fraction:  Calibration fraction when ``split_year`` is None (0.7).

    Returns:
        :class:`RealismAudit`
    """
    alignment_csv = Path(alignment_csv).expanduser().resolve()
    basin_id = basin_id or alignment_csv.parent.name

    df = pd.read_csv(alignment_csv, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).normalize()
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "obs" not in df.columns or "sim" not in df.columns:
        raise ValueError(f"alignment CSV must have 'obs' and 'sim' columns; found {list(df.columns)}")

    full_metrics = _compute_period_metrics(df)

    cal_df, val_df, cal_val = split_cal_val(df, split_year=split_year, cal_fraction=cal_fraction)
    cal_metrics = _compute_period_metrics(cal_df) if len(cal_df) >= 2 else None
    val_metrics = _compute_period_metrics(val_df) if len(val_df) >= 2 else None

    pathologies = _detect_pathologies(full_metrics, val_metrics)
    verdict     = _realism_verdict(pathologies, full_metrics.nse)

    return RealismAudit(
        basin_id=basin_id,
        alignment_csv=str(alignment_csv),
        generated_at=datetime.now(timezone.utc).isoformat(),
        period_full=full_metrics,
        period_cal=cal_metrics,
        period_val=val_metrics if (val_metrics and val_metrics.n_days > 0) else None,
        cal_val_split=cal_val,
        pathologies=pathologies,
        realism_verdict=verdict,
    )


def run_realism_audit(
    basin_alignments: list[tuple[str, Path]],
    *,
    out_dir: Path | str,
    split_year: int | None = None,
) -> list[RealismAudit]:
    """Run :func:`audit_realism` for multiple basins and write summary reports.

    Args:
        basin_alignments: list of ``(basin_id, alignment_csv_path)`` tuples.
        out_dir:          Directory to write ``realism_audit.json`` + ``realism_audit.md``.
        split_year:       Optional cal/val split year (applied to all basins).

    Returns:
        List of :class:`RealismAudit` results.
    """
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    audits: list[RealismAudit] = []
    for basin_id, csv_path in basin_alignments:
        try:
            audit = audit_realism(csv_path, basin_id=basin_id, split_year=split_year)
        except Exception as exc:
            # Produce a minimal failed audit rather than aborting the whole run.
            audit = RealismAudit(
                basin_id=basin_id,
                alignment_csv=str(csv_path),
                generated_at=datetime.now(timezone.utc).isoformat(),
                pathologies=[f"audit_error: {exc}"],
                realism_verdict="audit_failed",
            )
        audits.append(audit)

    _write_audit_json(audits, out_dir / "realism_audit.json")
    _write_audit_markdown(audits, out_dir / "realism_audit.md")
    return audits


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_audit_json(audits: list[RealismAudit], path: Path) -> None:
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "basin_count": len(audits),
        "audits": [a.model_dump() for a in audits],
    }
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def _write_audit_markdown(audits: list[RealismAudit], path: Path) -> None:
    lines = [
        "# Physical Realism Audit",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()[:19]}Z  ",
        f"Basins: {len(audits)}",
        "",
        "## Summary table",
        "",
        "| Basin | Period | NSE | KGE | PBIAS% | BFI obs | BFI sim | BFI ratio | Q90 ratio | Verdict |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    def _fmt(v: float | None, decimals: int = 3) -> str:
        return f"{v:.{decimals}f}" if v is not None and not np.isnan(v) else "n/a"

    for a in audits:
        f = a.period_full
        lines.append(
            f"| `{a.basin_id}` | full | {_fmt(f.nse)} | {_fmt(f.kge)} | "
            f"{_fmt(f.pbias_pct, 1)} | {_fmt(f.bfi_obs)} | {_fmt(f.bfi_sim)} | "
            f"{_fmt(f.bfi_ratio, 2)} | {_fmt(f.q90_ratio, 2)} | **{a.realism_verdict}** |"
        )
        if a.period_cal:
            c = a.period_cal
            lines.append(
                f"| `{a.basin_id}` | cal ({a.cal_val_split.cal_n}d) | {_fmt(c.nse)} | {_fmt(c.kge)} | "
                f"{_fmt(c.pbias_pct, 1)} | {_fmt(c.bfi_obs)} | {_fmt(c.bfi_sim)} | "
                f"{_fmt(c.bfi_ratio, 2)} | {_fmt(c.q90_ratio, 2)} | — |"
            )
        if a.period_val and a.period_val.n_days > 0:
            v = a.period_val
            lines.append(
                f"| `{a.basin_id}` | val ({a.cal_val_split.val_n}d) | {_fmt(v.nse)} | {_fmt(v.kge)} | "
                f"{_fmt(v.pbias_pct, 1)} | {_fmt(v.bfi_obs)} | {_fmt(v.bfi_sim)} | "
                f"{_fmt(v.bfi_ratio, 2)} | {_fmt(v.q90_ratio, 2)} | — |"
            )

    lines += ["", "## Pathologies and seasonal skill", ""]
    for a in audits:
        lines.append(f"### `{a.basin_id}`")
        if a.pathologies:
            for p in a.pathologies:
                lines.append(f"- {p}")
        else:
            lines.append("- No pathologies detected.")
        if a.period_full.seasonal_nse:
            lines.append("")
            lines.append("| Season | NSE |")
            lines.append("| --- | ---: |")
            for s, v in a.period_full.seasonal_nse.items():
                lines.append(f"| {s} | {_fmt(v)} |")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
