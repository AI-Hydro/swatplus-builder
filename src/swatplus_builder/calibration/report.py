"""Calibration reporting helpers (Phase 3C.4)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..params import get_parameter
from .spotpy_adapter import CalibrationIterationResult


def write_calibration_reports(
    results: list[CalibrationIterationResult],
    outdir: Path | str,
    *,
    alignment_csv: Path | str | None = None,
) -> dict[str, str]:
    """Write calibration history tables and diagnostic plots."""
    out = Path(outdir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    history_csv = out / "history.csv"
    summary_md = out / "summary.md"

    _write_history_csv(history_csv, results)
    _write_summary_md(summary_md, results)
    _write_plots(out, results)
    comp = write_parameter_comparison(results, out)
    if alignment_csv is not None:
        write_hydrograph_comparison_from_alignment(results, alignment_csv, out)

    return {
        "outdir": str(out),
        "history_csv": str(history_csv),
        "summary_md": str(summary_md),
        **comp,
    }


def _write_history_csv(path: Path, results: list[CalibrationIterationResult]) -> None:
    param_names = sorted({k for r in results for k in r.parameters.keys()})
    metric_names = sorted({k for r in results for k in r.metrics.keys()})
    fieldnames = ["iteration", "content_hash", "cache_hit"] + [f"param_{p}" for p in param_names] + [
        f"metric_{m}" for m in metric_names
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row: dict[str, object] = {
                "iteration": r.iteration,
                "content_hash": r.content_hash,
                "cache_hit": r.cache_hit,
            }
            for p in param_names:
                row[f"param_{p}"] = r.parameters.get(p)
            for m in metric_names:
                row[f"metric_{m}"] = r.metrics.get(m)
            writer.writerow(row)


def _write_summary_md(path: Path, results: list[CalibrationIterationResult]) -> None:
    nse_vals = [r.metrics.get("nse") for r in results if isinstance(r.metrics.get("nse"), (float, int))]
    best_nse = max((float(v) for v in nse_vals), default=None)
    lines = [
        "# Calibration Summary",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Iterations: `{len(results)}`",
        f"- Cache hits: `{sum(1 for r in results if r.cache_hit)}`",
        f"- Best NSE: `{'' if best_nse is None else f'{best_nse:.3f}'}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_plots(outdir: Path, results: list[CalibrationIterationResult]) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    x = [r.iteration for r in results]
    nse = [float(r.metrics["nse"]) if "nse" in r.metrics else float("nan") for r in results]

    # Convergence plot: objective vs iteration.
    fig, ax = plt.subplots()
    ax.plot(x, nse, marker="o")
    ax.set_title("Convergence (NSE vs iteration)")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("NSE")
    fig.tight_layout()
    fig.savefig(outdir / "convergence.png", dpi=200, bbox_inches="tight")
    fig.savefig(outdir / "convergence.pdf", bbox_inches="tight")
    plt.close(fig)

    # Dotty plot: first parameter against NSE.
    param_names = sorted({k for r in results for k in r.parameters.keys()})
    if param_names:
        p0 = param_names[0]
        px = [float(r.parameters[p0]) for r in results if p0 in r.parameters]
        py = [float(r.metrics.get("nse", float("nan"))) for r in results if p0 in r.parameters]
        fig2, ax2 = plt.subplots()
        ax2.scatter(px, py, alpha=0.7)
        ax2.set_title(f"Dotty Plot ({p0} vs NSE)")
        ax2.set_xlabel(p0)
        ax2.set_ylabel("NSE")
        fig2.tight_layout()
        fig2.savefig(outdir / "dotty.png", dpi=200, bbox_inches="tight")
        fig2.savefig(outdir / "dotty.pdf", bbox_inches="tight")
        plt.close(fig2)

    # Pareto-style plot when both NSE and PBIAS exist.
    has_pareto = any("pbias" in r.metrics and "nse" in r.metrics for r in results)
    if has_pareto:
        px2 = [float(r.metrics.get("pbias", float("nan"))) for r in results]
        py2 = [float(r.metrics.get("nse", float("nan"))) for r in results]
        fig3, ax3 = plt.subplots()
        ax3.scatter(px2, py2, alpha=0.7)
        ax3.set_title("Pareto View (PBIAS vs NSE)")
        ax3.set_xlabel("PBIAS")
        ax3.set_ylabel("NSE")
        fig3.tight_layout()
        fig3.savefig(outdir / "pareto.png", dpi=200, bbox_inches="tight")
        fig3.savefig(outdir / "pareto.pdf", bbox_inches="tight")
        plt.close(fig3)


def write_parameter_comparison(
    results: list[CalibrationIterationResult],
    outdir: Path | str,
) -> dict[str, str]:
    """Write baseline-vs-best parameter comparison table and plot."""
    out = Path(outdir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    best = _best_result(results)
    rows: list[dict[str, object]] = []
    for name, val in sorted(best.parameters.items()):
        p = get_parameter(name)
        default = float(p.default)
        calibrated = float(val)
        delta = calibrated - default
        pct = (delta / default * 100.0) if default != 0 else None
        rows.append(
            {
                "parameter": name,
                "scope": p.scope.value,
                "file": p.file,
                "default": default,
                "calibrated": calibrated,
                "delta": delta,
                "delta_pct": pct,
            }
        )

    csv_path = out / "parameter_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "parameter",
                "scope",
                "file",
                "default",
                "calibrated",
                "delta",
                "delta_pct",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    meta_path = out / "best_solution.json"
    meta_path.write_text(
        json.dumps(
            {
                "iteration": best.iteration,
                "content_hash": best.content_hash,
                "metrics": best.metrics,
                "parameters": best.parameters,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        import matplotlib.pyplot as plt
    except Exception:
        return {
            "parameter_comparison_csv": str(csv_path),
            "best_solution_json": str(meta_path),
        }

    labels = [str(r["parameter"]) for r in rows]
    defaults = [float(r["default"]) for r in rows]
    calibs = [float(r["calibrated"]) for r in rows]
    x = list(range(len(labels)))
    width = 0.38
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 1.1), 4.5))
    ax.bar([i - width / 2 for i in x], defaults, width=width, label="Default")
    ax.bar([i + width / 2 for i in x], calibs, width=width, label="Calibrated")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Parameter Value")
    ax.set_title("Default vs Calibrated SWAT Parameters")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "parameter_comparison.png", dpi=220, bbox_inches="tight")
    fig.savefig(out / "parameter_comparison.pdf", bbox_inches="tight")
    plt.close(fig)

    return {
        "parameter_comparison_csv": str(csv_path),
        "best_solution_json": str(meta_path),
        "parameter_comparison_plot": str(out / "parameter_comparison.png"),
    }


def write_hydrograph_comparison_from_alignment(
    results: list[CalibrationIterationResult],
    alignment_csv: Path | str,
    outdir: Path | str,
) -> dict[str, str]:
    """Write observed vs baseline simulated vs proxy-calibrated simulated plots.

    Note: until full engine-backed calibration is wired, calibrated series here is
    a transparent proxy transformation of baseline simulated flow.
    """
    out = Path(outdir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(Path(alignment_csv), index_col=0, parse_dates=True)
    if "obs" not in df.columns or "sim" not in df.columns:
        raise ValueError("alignment.csv must contain 'obs' and 'sim' columns.")
    df = df[["obs", "sim"]].dropna()
    if df.empty:
        raise ValueError("alignment.csv has no overlapping obs/sim rows.")

    baseline_nse = _nse(df["obs"], df["sim"])
    best = _best_result(results)
    target_nse = float(best.metrics.get("nse", baseline_nse))
    w = _blend_weight(baseline_nse, target_nse)
    df["sim_calibrated_proxy"] = df["sim"] + w * (df["obs"] - df["sim"])
    proxy_nse = _nse(df["obs"], df["sim_calibrated_proxy"])

    meta = {
        "baseline_nse": baseline_nse,
        "proxy_target_nse": target_nse,
        "proxy_result_nse": proxy_nse,
        "proxy_blend_weight": w,
        "note": "Proxy calibrated hydrograph (alpha): transformation-based, not yet full engine rerun.",
    }
    (out / "hydrograph_comparison_metrics.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    try:
        import matplotlib.pyplot as plt
    except Exception:
        return {"hydrograph_metrics_json": str(out / "hydrograph_comparison_metrics.json")}

    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(df.index, df["obs"], label="Observed", linewidth=1.6)
    ax.plot(df.index, df["sim"], label=f"Baseline Sim (NSE={baseline_nse:.3f})", linewidth=1.2)
    ax.plot(
        df.index,
        df["sim_calibrated_proxy"],
        label=f"Calibrated Sim Proxy (NSE={proxy_nse:.3f})",
        linewidth=1.2,
    )
    ax.set_title("Observed vs Simulated (Baseline vs Calibrated Proxy)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Discharge")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "hydrograph_calibrated_vs_observed.png", dpi=220, bbox_inches="tight")
    fig.savefig(out / "hydrograph_calibrated_vs_observed.pdf", bbox_inches="tight")
    plt.close(fig)

    return {
        "hydrograph_metrics_json": str(out / "hydrograph_comparison_metrics.json"),
        "hydrograph_plot": str(out / "hydrograph_calibrated_vs_observed.png"),
    }


def _best_result(results: list[CalibrationIterationResult]) -> CalibrationIterationResult:
    def _score(r: CalibrationIterationResult) -> float:
        v = r.metrics.get("nse")
        if isinstance(v, (float, int)):
            return float(v)
        return float("-inf")

    if not results:
        raise ValueError("No calibration results.")
    return max(results, key=_score)


def _nse(obs: pd.Series, sim: pd.Series) -> float:
    den = float(((obs - float(obs.mean())) ** 2).sum())
    if den == 0.0:
        return float("nan")
    num = float(((obs - sim) ** 2).sum())
    return 1.0 - (num / den)


def _blend_weight(baseline_nse: float, target_nse: float) -> float:
    if not pd.notna(baseline_nse) or not pd.notna(target_nse):
        return 0.0
    if baseline_nse >= 1.0:
        return 0.0
    raw = (target_nse - baseline_nse) / (1.0 - baseline_nse)
    return float(min(1.0, max(0.0, raw)))
