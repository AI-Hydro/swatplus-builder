"""Calibration reporting helpers (Phase 3C.4)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from .spotpy_adapter import CalibrationIterationResult


def write_calibration_reports(
    results: list[CalibrationIterationResult],
    outdir: Path | str,
) -> dict[str, str]:
    """Write calibration history tables and diagnostic plots."""
    out = Path(outdir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    history_csv = out / "history.csv"
    summary_md = out / "summary.md"

    _write_history_csv(history_csv, results)
    _write_summary_md(summary_md, results)
    _write_plots(out, results)

    return {"outdir": str(out), "history_csv": str(history_csv), "summary_md": str(summary_md)}


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

