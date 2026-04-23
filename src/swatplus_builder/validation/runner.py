"""Phase 3B validation runner built on top of the artifact store."""

from __future__ import annotations

import csv
import json
import math
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from .. import __version__
from ..artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)
from ..output.metadata import try_git_sha


class BasinSpec(BaseModel):
    """One basin entry for `swat validate --basins`."""

    usgs_id: str = Field(..., min_length=1)
    basin_id: str | None = Field(default=None)
    bbox: tuple[float, float, float, float] | None = Field(default=None)
    simulation_start: date = Field(...)
    simulation_end: date = Field(...)
    expected_nse_min: float | None = Field(default=None)
    notes: str | None = Field(default=None)
    options: dict[str, str | float | int | bool] = Field(default_factory=dict)

    @property
    def resolved_basin_id(self) -> str:
        if self.basin_id:
            return self.basin_id
        return f"usgs_{self.usgs_id}"


class ValidationRunResult(BaseModel):
    """Per-basin execution result emitted by `run_validation`."""

    basin_id: str
    usgs_id: str
    content_hash: str
    status: str
    cache_hit: bool
    run_dir: str
    nse: float | None = None
    kge: float | None = None
    pbias: float | None = None
    expected_nse_min: float | None = None
    passed: bool | None = None
    error: str | None = None


class ExecutorResult(BaseModel):
    """Structured payload returned by one-basin executor."""

    status: str = "success"
    metrics: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


Executor = Callable[[BasinSpec, Path], ExecutorResult]


def load_basin_specs(path: Path | str) -> list[BasinSpec]:
    """Load basin specs from JSON file.

    Accepted formats:
    - list of basin objects
    - object with top-level `basins: [...]`
    """
    p = Path(path).expanduser().resolve()
    payload = json.loads(p.read_text(encoding="utf-8"))
    items: list[dict[str, Any]]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("basins"), list):
        items = payload["basins"]
    else:
        raise ValueError("Basins file must be a JSON list or {'basins': [...]} object.")
    return [BasinSpec.model_validate(item) for item in items]


def run_validation(
    *,
    basins: list[BasinSpec],
    artifacts_root: Path | str,
    runs_root: Path | str,
    executor: Executor | None = None,
    engine_version: str = "unknown",
    builder_git_sha: str | None = None,
    default_nse_min: float = -1.0,
) -> tuple[list[ValidationRunResult], Path]:
    """Run/collect validation artifacts for a basin list.

    Caching:
    - Computes content hash per basin config.
    - If run already exists in artifact store, skips execution.
    """
    artifacts = Path(artifacts_root).expanduser().resolve()
    runs_root_path = Path(runs_root).expanduser().resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    runs_root_path.mkdir(parents=True, exist_ok=True)

    store = LocalArtifactStore(artifacts)
    exec_fn = executor or _default_executor
    git_sha = builder_git_sha or try_git_sha(Path(__file__).resolve().parents[3]) or "unknown"

    results: list[ValidationRunResult] = []
    for spec in basins:
        cfg = RunConfig(
            basin_id=spec.resolved_basin_id,
            bbox=spec.bbox,
            simulation_start=spec.simulation_start,
            simulation_end=spec.simulation_end,
            parameters={},
            options=dict(spec.options),
        )
        content_hash = compute_content_hash(
            cfg, engine_version=engine_version, builder_git_sha=git_sha
        )
        run_dir = runs_root_path / spec.resolved_basin_id

        if store.exists(content_hash):
            rec = store.read(content_hash)
            nse = rec.metrics.nse if rec.metrics else None
            expected_nse = (
                float(spec.expected_nse_min)
                if spec.expected_nse_min is not None
                else default_nse_min
            )
            results.append(
                ValidationRunResult(
                    basin_id=spec.resolved_basin_id,
                    usgs_id=spec.usgs_id,
                    content_hash=content_hash,
                    status="cached",
                    cache_hit=True,
                    run_dir=str(run_dir),
                    nse=nse,
                    kge=rec.metrics.kge if rec.metrics else None,
                    pbias=rec.metrics.pbias if rec.metrics else None,
                    expected_nse_min=expected_nse,
                    passed=(nse is not None and nse >= expected_nse),
                )
            )
            continue

        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            exec_res = exec_fn(spec, run_dir)
            md = ArtifactMetadata.model_validate(
                {
                    "run_id": content_hash,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "builder_version": __version__,
                    "git_sha": git_sha,
                    **exec_res.metadata,
                }
            )
            metrics = (
                ArtifactMetrics.model_validate(exec_res.metrics)
                if exec_res.metrics
                else ArtifactMetrics()
            )
            provenance = (
                ArtifactProvenance.model_validate(exec_res.provenance)
                if exec_res.provenance
                else ArtifactProvenance()
            )
            store.write(
                ArtifactRecord(
                    content_hash=content_hash,
                    config=cfg,
                    metadata=md,
                    metrics=metrics,
                    provenance=provenance,
                )
            )
            expected_nse = (
                float(spec.expected_nse_min)
                if spec.expected_nse_min is not None
                else default_nse_min
            )
            results.append(
                ValidationRunResult(
                    basin_id=spec.resolved_basin_id,
                    usgs_id=spec.usgs_id,
                    content_hash=content_hash,
                    status=exec_res.status,
                    cache_hit=False,
                    run_dir=str(run_dir),
                    nse=metrics.nse,
                    kge=metrics.kge,
                    pbias=metrics.pbias,
                    expected_nse_min=expected_nse,
                    passed=(metrics.nse is not None and metrics.nse >= expected_nse),
                )
            )
        except Exception as exc:
            expected_nse = (
                float(spec.expected_nse_min)
                if spec.expected_nse_min is not None
                else default_nse_min
            )
            results.append(
                ValidationRunResult(
                    basin_id=spec.resolved_basin_id,
                    usgs_id=spec.usgs_id,
                    content_hash=content_hash,
                    status="failed",
                    cache_hit=False,
                    run_dir=str(run_dir),
                    expected_nse_min=expected_nse,
                    passed=False,
                    error=str(exc),
                )
            )

    report_dir = artifacts / "validation_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_report_files(report_dir, results)
    return results, report_dir


def _write_report_files(report_dir: Path, results: list[ValidationRunResult]) -> None:
    csv_path = report_dir / "summary.csv"
    md_path = report_dir / "summary.md"
    benchmark_path = report_dir / "benchmark_report.md"
    benchmark_json = report_dir / "benchmark_summary.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "basin_id",
                "usgs_id",
                "status",
                "cache_hit",
                "content_hash",
                "nse",
                "kge",
                "pbias",
                "run_dir",
                "expected_nse_min",
                "passed",
                "error",
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row.model_dump())

    lines = [
        "# Validation Summary",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Basins: `{len(results)}`",
        f"- Success: `{sum(1 for r in results if r.status in {'success', 'cached'})}`",
        "",
        "| Basin | USGS | Status | Cache | NSE | KGE | PBIAS | Pass |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.basin_id} | {r.usgs_id} | {r.status} | {str(r.cache_hit).lower()} | "
            f"{'' if r.nse is None else f'{r.nse:.3f}'} | "
            f"{'' if r.kge is None else f'{r.kge:.3f}'} | "
            f"{'' if r.pbias is None else f'{r.pbias:.3f}'} | "
            f"{'' if r.passed is None else ('yes' if r.passed else 'no')} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    aggregate = _aggregate_results(results)
    benchmark_json.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")

    report_lines = [
        "# Benchmark Report",
        "",
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Basins evaluated: `{aggregate['basin_count']}`",
        f"- Successful/cached runs: `{aggregate['success_count']}`",
        f"- Fail count: `{aggregate['fail_count']}`",
        f"- Pass count (NSE floor): `{aggregate['pass_count']}`",
        "",
        "## Cross-Basin Summary",
        "",
        f"- Median NSE: `{_fmt(aggregate.get('nse_median'))}`",
        f"- NSE p10/p90: `{_fmt(aggregate.get('nse_p10'))}` / `{_fmt(aggregate.get('nse_p90'))}`",
        f"- Median KGE: `{_fmt(aggregate.get('kge_median'))}`",
        f"- Median PBIAS: `{_fmt(aggregate.get('pbias_median'))}`",
        "",
        "## Output Artifacts",
        "",
        "- `summary.csv`",
        "- `summary.md`",
        "- `benchmark_summary.json`",
    ]
    benchmark_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    _write_comparison_plot(report_dir, results)


def _aggregate_results(results: list[ValidationRunResult]) -> dict[str, float | int | None]:
    nse_vals = [r.nse for r in results if isinstance(r.nse, (float, int)) and math.isfinite(r.nse)]
    kge_vals = [r.kge for r in results if isinstance(r.kge, (float, int)) and math.isfinite(r.kge)]
    pbias_vals = [r.pbias for r in results if isinstance(r.pbias, (float, int)) and math.isfinite(r.pbias)]

    out: dict[str, float | int | None] = {
        "basin_count": len(results),
        "success_count": sum(1 for r in results if r.status in {"success", "cached"}),
        "fail_count": sum(1 for r in results if r.status == "failed"),
        "pass_count": sum(1 for r in results if r.passed is True),
        "nse_median": _median(nse_vals),
        "nse_p10": _quantile(nse_vals, 0.1),
        "nse_p90": _quantile(nse_vals, 0.9),
        "kge_median": _median(kge_vals),
        "pbias_median": _median(pbias_vals),
    }
    return out


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    idx = int(round((len(vals) - 1) * q))
    return float(vals[idx])


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.3f}"


def _write_comparison_plot(report_dir: Path, results: list[ValidationRunResult]) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    labels = [r.basin_id for r in results]
    nse_vals = [r.nse if r.nse is not None else float("nan") for r in results]
    kge_vals = [r.kge if r.kge is not None else float("nan") for r in results]

    fig, ax = plt.subplots(figsize=(10, 4))
    x = list(range(len(labels)))
    ax.plot(x, nse_vals, marker="o", label="NSE")
    ax.plot(x, kge_vals, marker="s", label="KGE")
    ax.axhline(-1.0, linestyle="--", linewidth=1.0, color="gray", label="NSE floor")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Metric")
    ax.set_title("Cross-basin Metric Comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(report_dir / "comparison_metrics.png", dpi=200, bbox_inches="tight")
    fig.savefig(report_dir / "comparison_metrics.pdf", bbox_inches="tight")
    plt.close(fig)


def _default_executor(spec: BasinSpec, run_dir: Path) -> ExecutorResult:
    """Fallback executor for `swat validate`.

    Uses the current orchestrator hook. This keeps `swat validate`
    runnable in alpha while enabling tests to inject deterministic
    executors.
    """
    from ..orchestrate import run_pipeline

    summary = run_pipeline(
        usgs_id=spec.usgs_id,
        outdir=run_dir,
        start_date=spec.simulation_start.isoformat(),
        end_date=spec.simulation_end.isoformat(),
    )
    metrics: dict[str, float] = {}
    for key in ("nse", "kge", "pbias"):
        val = summary.get(key)
        if isinstance(val, (int, float)):
            metrics[key] = float(val)
    metadata = {
        "engine_version": str(summary.get("engine_version", "unknown")),
        "soil_mode": str(summary.get("soil_mode", "high_fidelity")),
    }
    return ExecutorResult(status=str(summary.get("status", "success")).lower(), metrics=metrics, metadata=metadata)
