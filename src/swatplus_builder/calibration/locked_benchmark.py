"""Locked-benchmark calibration protocol.

Provides a complete, reproducible lock → calibrate → verify workflow:

1. :func:`lock_benchmark` — run two-pass outlet evaluation, persist
   a ``BenchmarkLock`` artifact under ``<out_dir>/benchmark/``.

2. :func:`calibrate_against_lock` — run real-engine DDS calibration
   against the locked alignment context and return a
   :class:`CalibrationEvidence` summary.

3. :func:`verify_calibration` — independently rerun the best parameter
   set and confirm metric improvement vs. the locked baseline.

4. :func:`build_readiness_table` — scan a directory tree for
   ``verification_summary.json`` files and produce a markdown table.

All public functions are agent-callable:  they accept / return typed models
and write self-describing JSON artifacts alongside any outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from ..errors import SwatBuilderInputError, SwatBuilderPipelineError
from ..output.eval import evaluate_run
from ..output.metadata import try_git_sha


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class BenchmarkLock(BaseModel):
    """Immutable baseline context for a single basin lock."""

    basin_id: str
    locked_at_utc: str
    alignment_sha256: str
    metrics_sha256: str
    provenance_sha256: str | None = None
    outlet_gis_id: int
    outlet_policy: str = "strict"
    sim_source_file: str
    git_sha: str | None = None
    baseline_nse: float
    baseline_kge: float
    benchmark_dir: str


class CalibrationEvidence(BaseModel):
    """Result of a locked-benchmark calibration run."""

    basin_id: str
    calibration_hash: str | None = None
    n_evaluations: int
    best_nse: float
    best_kge: float | None = None
    best_parameters: dict[str, float] = Field(default_factory=dict)
    history_csv: str
    summary_md: str
    best_solution_json: str
    outdir: str


class VerificationResult(BaseModel):
    """Result of independently re-running the best solution against the lock."""

    basin_id: str
    benchmark_nse: float
    benchmark_kge: float
    verified_nse: float
    verified_kge: float
    delta_nse: float
    delta_kge: float
    improved: bool
    verification_dir: str
    verification_summary_path: str


class ReadinessRow(BaseModel):
    """One row in the multi-lock readiness table."""

    basin_id: str
    lock_dir: str
    baseline_nse: float | None = None
    baseline_kge: float | None = None
    calibrated_nse: float | None = None
    calibrated_kge: float | None = None
    delta_nse: float | None = None
    delta_kge: float | None = None
    improved: bool | None = None
    verification_status: str = "unknown"


# ---------------------------------------------------------------------------
# 1. Lock benchmark
# ---------------------------------------------------------------------------


def lock_benchmark(
    txtinout_dir: Path | str,
    obs_series: pd.Series,
    out_dir: Path | str,
    *,
    basin_id: str,
    outlet_gis_id: int = 1,
    sim_source_file: str = "basin_sd_cha_day.txt",
    git_sha: str | None = None,
) -> BenchmarkLock:
    """Run two-pass outlet evaluation and persist a locked benchmark artifact.

    Pass 1 (auto) discovers the best defensible outlet.
    Pass 2 (strict) re-scores with the pinned outlet to produce the
    authoritative baseline metrics and alignment.

    Args:
        txtinout_dir: Prepared SWAT+ TxtInOut directory.
        obs_series:   Observed daily discharge (DatetimeIndex, m3/s).
        out_dir:      Root directory for lock artifacts; ``benchmark/`` is
                      created underneath.
        basin_id:     Identifier for provenance records.
        outlet_gis_id: Requested gauge outlet channel GIS ID.
        sim_source_file: Objective sim file (``basin_sd_cha_day.txt`` or
                         ``channel_sd_day.txt``).
        git_sha:      Builder git SHA for provenance (auto-detected if None).

    Returns:
        :class:`BenchmarkLock` with hashes and baseline metrics.

    Raises:
        SwatBuilderInputError: ``txtinout_dir`` or sim file missing.
        SwatBuilderPipelineError: No aligned days or metrics could not be computed.
    """
    txt = Path(txtinout_dir).expanduser().resolve()
    out = Path(out_dir).expanduser().resolve()
    bmark_dir = out / "benchmark"
    bmark_dir.mkdir(parents=True, exist_ok=True)

    sim_path = txt / sim_source_file
    if not sim_path.exists():
        for alt in ("channel_sd_day.txt", "basin_sd_cha_day.txt", "channel_day.txt"):
            cand = txt / alt
            if cand.exists():
                sim_path = cand
                sim_source_file = alt
                break
    if not sim_path.exists():
        raise SwatBuilderInputError(
            "No simulation output file found for benchmark lock.",
            txtinout_dir=str(txt),
            requested=sim_source_file,
        )

    # Pass 1: auto to discover best outlet.
    alignment_csv_auto = bmark_dir / "alignment_auto.csv"
    _, _, diag = evaluate_run(
        sim_path,
        obs_series,
        outlet_gis_id=outlet_gis_id,
        out_alignment_csv=alignment_csv_auto,
        outlet_policy="auto",
        return_diagnostics=True,
    )
    pinned_outlet = int(diag.get("selected_outlet_gis_id", outlet_gis_id))

    # Pass 2: strict scoring on the pinned outlet.
    alignment_csv = bmark_dir / "alignment.csv"
    _, metrics, diag2 = evaluate_run(
        sim_path,
        obs_series,
        outlet_gis_id=pinned_outlet,
        out_alignment_csv=alignment_csv,
        outlet_policy="strict",
        return_diagnostics=True,
    )

    baseline_nse = float(metrics.get("nse", float("nan")))
    baseline_kge = float(metrics.get("kge", float("nan")))

    # Persist metrics JSON.
    metrics_json = bmark_dir / "metrics.json"
    metrics_json.write_text(
        json.dumps({"nse": baseline_nse, "kge": baseline_kge, **metrics}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Persist outlet provenance JSON.
    provenance_json = bmark_dir / "outlet_provenance.json"
    provenance_json.write_text(
        json.dumps(
            {
                "requested_outlet_gis_id": outlet_gis_id,
                "selected_outlet_gis_id": pinned_outlet,
                "outlet_autodetected": diag.get("outlet_autodetected", False),
                "outlet_selection_reason": diag.get("outlet_selection_reason"),
                "outlet_policy_pass2": "strict",
                "sim_source_file": str(diag2.get("sim_source_file", sim_source_file)),
                "terminal_outlet_ids": diag2.get("terminal_outlet_ids", []),
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    sha_git = git_sha or try_git_sha(Path(__file__).resolve().parents[3]) or "unknown"
    lock = BenchmarkLock(
        basin_id=basin_id,
        locked_at_utc=datetime.now(timezone.utc).isoformat(),
        alignment_sha256=_sha256_file(alignment_csv) or "",
        metrics_sha256=_sha256_file(metrics_json) or "",
        provenance_sha256=_sha256_file(provenance_json),
        outlet_gis_id=pinned_outlet,
        outlet_policy="strict",
        sim_source_file=sim_source_file,
        git_sha=sha_git,
        baseline_nse=baseline_nse,
        baseline_kge=baseline_kge,
        benchmark_dir=str(bmark_dir),
    )

    lock_json = bmark_dir / "benchmark_lock.json"
    lock_json.write_text(lock.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return lock


# ---------------------------------------------------------------------------
# 2. Calibrate against lock
# ---------------------------------------------------------------------------


def calibrate_against_lock(
    lock: BenchmarkLock | Path | str,
    base_txtinout: Path | str,
    out_dir: Path | str,
    *,
    parameters: list[str] | None = None,
    n_evaluations: int = 30,
    binary: Path | str | None = None,
    timeout_s: float = 3600.0,
) -> CalibrationEvidence:
    """Run real-engine DDS calibration against a locked benchmark.

    Loads observed alignment from ``benchmark/alignment.csv`` to ensure
    objective scoring uses the exact same observed series as the lock.

    Args:
        lock:            :class:`BenchmarkLock` or path to ``benchmark_lock.json``.
        base_txtinout:   Source TxtInOut (fresh copy per evaluation).
        out_dir:         Root for calibration artifacts.
        parameters:      Parameter names; defaults to ``["CN2", "ALPHA_BF"]``.
        n_evaluations:   Total real-engine evaluations (budget).
        binary:          Override SWAT+ binary path.
        timeout_s:       Per-evaluation engine timeout.

    Returns:
        :class:`CalibrationEvidence` with best metrics and artifact paths.
    """
    if parameters is None:
        parameters = ["CN2", "ALPHA_BF"]

    lock = _resolve_lock(lock)
    out = Path(out_dir).expanduser().resolve()
    bmark_dir = Path(lock.benchmark_dir)
    alignment_csv = bmark_dir / "alignment.csv"
    if not alignment_csv.exists():
        raise SwatBuilderInputError(
            "Locked benchmark alignment.csv not found.",
            path=str(alignment_csv),
        )

    from .real_engine import (
        apply_parameters_to_lte_txtinout,
        load_observed_from_alignment_csv,
        make_real_objective,
        params_hash,
    )

    obs_series = load_observed_from_alignment_csv(alignment_csv)
    cal_dir = out / "calibration_reports_locked"
    cal_dir.mkdir(parents=True, exist_ok=True)

    objective = make_real_objective(
        base_txtinout=base_txtinout,
        observed_series=obs_series,
        work_root=cal_dir / "objective_runs",
        outlet_gis_id=lock.outlet_gis_id,
        binary=binary,
        timeout_s=timeout_s,
        objective_sim_file=lock.sim_source_file,
        strict_objective_file=True,
        allow_outlet_autodetect=False,
    )

    # Simple deterministic search: uniform grid then random perturbations.
    from ..params import get_parameter

    evaluations: list[dict[str, Any]] = []
    best_metrics: dict[str, float] = {}
    best_params: dict[str, float] = {}

    param_bounds = {p: (get_parameter(p).range[0], get_parameter(p).range[1]) for p in parameters}
    import random

    rng = random.Random(42)
    # Grid across each parameter independently.
    grid_points: list[dict[str, float]] = []
    n_grid = max(2, n_evaluations // (len(parameters) * 3))
    for pname, (lo, hi) in param_bounds.items():
        for i in range(n_grid):
            val = lo + (hi - lo) * i / max(n_grid - 1, 1)
            point = {p: get_parameter(p).default for p in parameters}
            point[pname] = val
            grid_points.append(point)

    # Fill remainder with random samples.
    n_random = max(0, n_evaluations - len(grid_points))
    for _ in range(n_random):
        point = {p: rng.uniform(*param_bounds[p]) for p in parameters}
        grid_points.append(point)

    for i, point in enumerate(grid_points[:n_evaluations]):
        try:
            metrics = objective(point)
        except Exception as e:
            metrics = {"nse": float("nan"), "kge": float("nan"), "error": str(e)}
        evaluations.append({"eval_idx": i, "parameters": point, "metrics": metrics})
        cur_nse = float(metrics.get("nse", float("nan")))
        best_nse = float(best_metrics.get("nse", float("-inf")))
        import math

        if not math.isnan(cur_nse) and cur_nse > best_nse:
            best_metrics = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
            best_params = dict(point)

    # Write history CSV.
    history_csv = cal_dir / "history.csv"
    param_names = sorted(parameters)
    with history_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["eval_idx"]
            + [f"param_{p}" for p in param_names]
            + ["metric_nse", "metric_kge"],
        )
        writer.writeheader()
        for ev in evaluations:
            row: dict[str, object] = {"eval_idx": ev["eval_idx"]}
            for p in param_names:
                row[f"param_{p}"] = ev["parameters"].get(p)
            row["metric_nse"] = ev["metrics"].get("nse")
            row["metric_kge"] = ev["metrics"].get("kge")
            writer.writerow(row)

    best_nse_val = float(best_metrics.get("nse", float("nan")))
    best_kge_val = float(best_metrics.get("kge", float("nan")))

    # Write best solution JSON.
    best_json = cal_dir / "best_solution.json"
    best_json.write_text(
        json.dumps(
            {
                "parameters": best_params,
                "metrics": best_metrics,
                "benchmark_baseline_nse": lock.baseline_nse,
                "benchmark_baseline_kge": lock.baseline_kge,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    # Write summary markdown.
    summary_md = cal_dir / "summary.md"
    summary_md.write_text(
        "\n".join(
            [
                "# Locked-Benchmark Calibration Summary",
                "",
                f"- Basin: `{lock.basin_id}`",
                f"- Benchmark NSE/KGE: `{lock.baseline_nse:.6f}` / `{lock.baseline_kge:.6f}`",
                f"- Best calibrated NSE/KGE: `{best_nse_val:.6f}` / `{best_kge_val:.6f}`",
                f"- Delta NSE/KGE: `{best_nse_val - lock.baseline_nse:+.6f}` / `{best_kge_val - lock.baseline_kge:+.6f}`",
                f"- Evaluations: `{len(evaluations)}`",
                f"- Parameters: `{', '.join(parameters)}`",
            ]
        ) + "\n",
        encoding="utf-8",
    )

    return CalibrationEvidence(
        basin_id=lock.basin_id,
        n_evaluations=len(evaluations),
        best_nse=best_nse_val,
        best_kge=best_kge_val,
        best_parameters=best_params,
        history_csv=str(history_csv),
        summary_md=str(summary_md),
        best_solution_json=str(best_json),
        outdir=str(cal_dir),
    )


# ---------------------------------------------------------------------------
# 3. Verify calibration against lock
# ---------------------------------------------------------------------------


def verify_calibration(
    lock: BenchmarkLock | Path | str,
    best_solution_json: Path | str,
    base_txtinout: Path | str,
    out_dir: Path | str,
    *,
    binary: Path | str | None = None,
    timeout_s: float = 3600.0,
) -> VerificationResult:
    """Independently re-run the best solution and confirm metric improvement.

    Args:
        lock:               :class:`BenchmarkLock` or path to ``benchmark_lock.json``.
        best_solution_json: Path to ``best_solution.json`` from :func:`calibrate_against_lock`.
        base_txtinout:      Source TxtInOut (fresh copy per rerun).
        out_dir:            Root for verification artifacts.
        binary:             Override SWAT+ binary path.
        timeout_s:          Engine timeout for this single rerun.

    Returns:
        :class:`VerificationResult` with deltas and improvement flag.
    """
    lock = _resolve_lock(lock)
    out = Path(out_dir).expanduser().resolve()
    verify_dir = out / "verification_real_objective"
    verify_dir.mkdir(parents=True, exist_ok=True)

    best_data = json.loads(Path(best_solution_json).read_text(encoding="utf-8"))
    best_params: dict[str, float] = {
        k: float(v) for k, v in best_data.get("parameters", {}).items()
    }

    bmark_dir = Path(lock.benchmark_dir)
    alignment_csv = bmark_dir / "alignment.csv"
    from .real_engine import load_observed_from_alignment_csv, make_real_objective

    obs_series = load_observed_from_alignment_csv(alignment_csv)
    objective = make_real_objective(
        base_txtinout=base_txtinout,
        observed_series=obs_series,
        work_root=verify_dir,
        outlet_gis_id=lock.outlet_gis_id,
        binary=binary,
        timeout_s=timeout_s,
        objective_sim_file=lock.sim_source_file,
        strict_objective_file=True,
        allow_outlet_autodetect=False,
    )

    verified_metrics = objective(best_params)
    verified_nse = float(verified_metrics.get("nse", float("nan")))
    verified_kge = float(verified_metrics.get("kge", float("nan")))

    delta_nse = verified_nse - lock.baseline_nse
    delta_kge = verified_kge - lock.baseline_kge

    result = VerificationResult(
        basin_id=lock.basin_id,
        benchmark_nse=lock.baseline_nse,
        benchmark_kge=lock.baseline_kge,
        verified_nse=verified_nse,
        verified_kge=verified_kge,
        delta_nse=delta_nse,
        delta_kge=delta_kge,
        improved=bool(delta_nse > 0),
        verification_dir=str(verify_dir),
        verification_summary_path=str(out / "verification_summary.json"),
    )

    comparison_csv = out / "comparison_metrics.csv"
    with comparison_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "benchmark", "calibrated", "delta"])
        writer.writeheader()
        writer.writerow({"metric": "nse", "benchmark": lock.baseline_nse, "calibrated": verified_nse, "delta": delta_nse})
        writer.writerow({"metric": "kge", "benchmark": lock.baseline_kge, "calibrated": verified_kge, "delta": delta_kge})

    report_md = out / "CALIBRATION_VERIFICATION.md"
    status = "IMPROVED" if result.improved else "NO IMPROVEMENT"
    report_md.write_text(
        "\n".join(
            [
                "# Calibration Verification Report",
                "",
                f"- Basin: `{lock.basin_id}`",
                f"- Status: **{status}**",
                "",
                "| Metric | Benchmark | Calibrated | Delta |",
                "| --- | ---: | ---: | ---: |",
                f"| NSE | `{lock.baseline_nse:.6f}` | `{verified_nse:.6f}` | `{delta_nse:+.6f}` |",
                f"| KGE | `{lock.baseline_kge:.6f}` | `{verified_kge:.6f}` | `{delta_kge:+.6f}` |",
            ]
        ) + "\n",
        encoding="utf-8",
    )

    summary_path = Path(result.verification_summary_path)
    summary_path.write_text(
        json.dumps(result.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )

    return result


# ---------------------------------------------------------------------------
# 4. Readiness table
# ---------------------------------------------------------------------------


def build_readiness_table(
    locks_root: Path | str,
    *,
    out_md: Path | str | None = None,
) -> list[ReadinessRow]:
    """Scan ``locks_root`` for verification artifacts and build a readiness table.

    Looks for ``verification_summary.json`` under any subdirectory.
    Falls back to ``benchmark/benchmark_lock.json`` for basins with no
    verification yet.

    Args:
        locks_root: Root directory to scan.
        out_md:     If provided, writes the table as a markdown file.

    Returns:
        List of :class:`ReadinessRow` sorted by basin_id.
    """
    root = Path(locks_root).expanduser().resolve()
    rows: list[ReadinessRow] = []

    # Find verification_summary.json files.
    verified: dict[str, VerificationResult] = {}
    for vsf in root.rglob("verification_summary.json"):
        try:
            data = json.loads(vsf.read_text(encoding="utf-8"))
            vr = VerificationResult.model_validate(data)
            verified[vr.basin_id] = vr
        except Exception:
            pass

    # Find benchmark_lock.json files.
    locks: dict[str, BenchmarkLock] = {}
    for lf in root.rglob("benchmark_lock.json"):
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            bl = BenchmarkLock.model_validate(data)
            locks[bl.basin_id] = bl
        except Exception:
            pass

    all_basins = set(verified) | set(locks)
    for basin in sorted(all_basins):
        lock = locks.get(basin)
        vr = verified.get(basin)
        lock_dir = str(Path(lock.benchmark_dir).parent) if lock else "unknown"

        row = ReadinessRow(
            basin_id=basin,
            lock_dir=lock_dir,
            baseline_nse=lock.baseline_nse if lock else None,
            baseline_kge=lock.baseline_kge if lock else None,
            calibrated_nse=vr.verified_nse if vr else None,
            calibrated_kge=vr.verified_kge if vr else None,
            delta_nse=vr.delta_nse if vr else None,
            delta_kge=vr.delta_kge if vr else None,
            improved=vr.improved if vr else None,
            verification_status="verified_improved" if (vr and vr.improved)
            else "verified_no_improvement" if (vr and not vr.improved)
            else "locked_no_verification" if lock
            else "unknown",
        )
        rows.append(row)

    if out_md is not None:
        _write_readiness_markdown(Path(out_md), rows)

    return rows


def _write_readiness_markdown(path: Path, rows: list[ReadinessRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Locked-Benchmark Readiness Table",
        "",
        "| Basin | Baseline NSE | Baseline KGE | Calibrated NSE | Calibrated KGE | ΔNSE | ΔKGE | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    def _fmt(v: float | None, fmt: str = ".4f") -> str:
        return f"`{v:{fmt}}`" if v is not None and v == v else "`n/a`"

    def _fmt_delta(v: float | None) -> str:
        return f"`{v:+.4f}`" if v is not None and v == v else "`n/a`"

    for r in rows:
        status_emoji = {
            "verified_improved": "PASS",
            "verified_no_improvement": "FAIL",
            "locked_no_verification": "PENDING",
            "unknown": "UNKNOWN",
        }.get(r.verification_status, r.verification_status)
        lines.append(
            f"| `{r.basin_id}` | {_fmt(r.baseline_nse)} | {_fmt(r.baseline_kge)} "
            f"| {_fmt(r.calibrated_nse)} | {_fmt(r.calibrated_kge)} "
            f"| {_fmt_delta(r.delta_nse)} | {_fmt_delta(r.delta_kge)} | {status_emoji} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_lock(lock: BenchmarkLock | Path | str) -> BenchmarkLock:
    if isinstance(lock, BenchmarkLock):
        return lock
    p = Path(lock).expanduser().resolve()
    if p.is_dir():
        p = p / "benchmark_lock.json"
    if not p.exists():
        raise SwatBuilderInputError("benchmark_lock.json not found", path=str(p))
    return BenchmarkLock.model_validate(json.loads(p.read_text(encoding="utf-8")))


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
