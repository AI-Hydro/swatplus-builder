#!/usr/bin/env python3
"""Batch driver: run the canonical USGS workflow over many basins, verify each
run's tamper-evident ledger, and export decision-model training items only
from runs that verify.

This is the "(2) Generate episodes at scale" step deferred in
docs/AGENT_HANDOFF.md §3 and docs/DECISION_DATA_PIPELINE.md §4 ("Known
limits"). It is an orchestration layer over the existing, already-audited
CLI contract (`swat workflow run`, `swat audit verify`, `swat audit typed`)
-- it does not reimplement any of the pipeline, governance, or decision-data
logic itself.

What this script does:
  - Runs `swat workflow run` once per basin, each in its own output
    directory, each as its own subprocess (a crash or hang in one basin's
    engine calibration cannot take down the batch or another basin's run).
  - Retains every basin's result, success or failure, with a reason --
    nothing is silently dropped (readiness review P0: "retain all build
    failures and exclusion reasons").
  - Never admits a basin's decisions to the combined training-data file
    unless `swat audit verify` passes on its hash-chained ledgers first
    (readiness review P0: an unverified run must not become training data).
  - Meters cost per basin: wall-clock seconds and the number of engine
    candidate evaluations actually run (summed from
    calibration/calibration_reports_locked/phase_decisions.json and
    reports/sensitivity_screen.json when present), so foundry cost is
    visible and reported separately from any later training/deployment cost
    (readiness review P1: "costs ... are easily omitted").
  - Writes an incremental JSONL manifest as it goes (so a killed batch loses
    at most the one basin in flight, not everything before it), plus a
    final JSON+CSV summary.

What this script deliberately does NOT do (still open, see
docs/AGENT_HANDOFF.md §3 and
../Swatplus_decision/research/BUILDER_READINESS.md):
  - It does not choose which basins belong in a trusted reference set, or
    enforce any basin-inclusion protocol -- the basin list is supplied by
    the caller (--basins), as-is.
  - It does not separate a decision-development period from a withheld
    final-assessment period across basins -- each basin's own
    calibration/validation split is whatever its own --start/--end/
    calibration-window settings already encode.
  - It does not inject faults. Fault injection needs an already-built
    TxtInOut to copy and perturb (`swat fault inject`), which doesn't fit
    this driver's "one clean `workflow run` per basin" shape. That is
    docs/AGENT_HANDOFF.md §3 item 3 (combined/harder fault designs),
    deliberately left for a follow-up once this plain-batch path is proven.

Usage:
    python scripts/decision_data_batch.py --basins basins.json \\
        --out-root runs/decision_data_batch/2026-09-28 \\
        --typed-out runs/decision_data_batch/2026-09-28/typed_decisions.jsonl

basins.json is a JSON array of objects; only "usgs_id" is required:
    [
      {"usgs_id": "02177000"},
      {"usgs_id": "03339000", "start": "2010-01-01", "end": "2019-12-31",
       "warmup_years": 3, "model_family": "full", "claim_tier": "diagnostic"}
    ]
Any field accepted by `swat workflow run --help` may be set per-basin; unset
fields fall back to --default-* CLI flags, which fall back to the workflow's
own defaults.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Per-basin fields that map 1:1 onto `swat workflow run` CLI flags.
_PASSTHROUGH_FLAGS = {
    "model_family": "--model-family",
    "start": "--start",
    "end": "--end",
    "warmup_years": "--warmup-years",
    "claim_tier": "--claim-tier",
    "hru_mode": "--hru-mode",
    "min_hru_fraction": "--min-hru-fraction",
    "sensitivity_workers": "--sensitivity-workers",
    "anchor_workers": "--anchor-workers",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class BasinResult:
    usgs_id: str
    status: str  # run_failed | run_timeout | ledger_verify_failed | typed_export_failed | ok | skipped_existing
    out_dir: str
    stage: str  # which step the status refers to: workflow_run | audit_verify | audit_typed | skip
    wall_clock_s: float
    effective_claim_tier: str | None = None
    blocker_class: str | None = None
    engine_candidate_evaluations: int | None = None
    typed_decision_count: int | None = None
    error_tail: str | None = None
    started_at: str = field(default_factory=now_utc)
    finished_at: str | None = None


def _extract_json_object(stdout: str) -> dict[str, Any] | None:
    """`swat workflow run --json` prints human progress lines *and* a final
    JSON object; find the last top-level JSON object in the output."""
    start = stdout.rfind("\n{")
    candidate = stdout[start + 1 :] if start != -1 else stdout
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        # Fall back to the whole-output parse (JSON-only stdout).
        try:
            return json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return None


def _count_engine_candidate_evaluations(out_dir: Path) -> int | None:
    """Sum candidate_count across calibration phases and sensitivity bounds,
    as a proxy for the number of engine invocations this basin actually
    cost -- not exact (verification/warm-start passes add more), but the
    dominant term and cheap to compute from artifacts already on disk."""
    total = 0
    found = False
    phase_decisions = out_dir / "calibration" / "calibration_reports_locked" / "phase_decisions.json"
    if phase_decisions.is_file():
        try:
            data = json.loads(phase_decisions.read_text(encoding="utf-8"))
            for phase in data.get("phases", []):
                total += int(phase.get("candidate_count") or 0)
            found = True
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    sensitivity = out_dir / "calibration" / "sensitivity_screen_locked" / "sensitivity_screen.json"
    if sensitivity.is_file():
        try:
            data = json.loads(sensitivity.read_text(encoding="utf-8"))
            params = data.get("parameters") or data.get("results") or []
            if isinstance(params, list):
                total += len(params) * 2  # low-bound + high-bound eval per parameter
                found = True
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return total if found else None


def _run_one_basin(
    spec: dict[str, Any],
    *,
    out_root: Path,
    logs_dir: Path,
    typed_dir: Path,
    defaults: dict[str, Any],
    basin_timeout_s: float,
    skip_existing: bool,
    typed_max_chars: int,
    typed_max_options: int,
    typed_soft_target: str,
    typed_temperature: float,
) -> BasinResult:
    usgs_id = str(spec["usgs_id"])
    out_dir = out_root / f"usgs_{usgs_id}"
    started = time.monotonic()
    evidence_path = out_dir / "evidence_summary.json"

    if skip_existing and evidence_path.is_file():
        # Resuming a batch: don't re-run the engine, but still verify and
        # (re)export -- a prior crash may have stopped before those steps,
        # and both are cheap/idempotent compared to the engine run itself.
        wall_clock = 0.0
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        effective_tier = payload.get("effective_claim_tier")
        blocker = payload.get("blocker_class")
        candidate_evals = _count_engine_candidate_evaluations(out_dir)
    else:
        merged = {**defaults, **spec}
        argv = [sys.executable, "-m", "swatplus_builder.cli", "workflow", "run", "--usgs-id", usgs_id]
        for key, flag in _PASSTHROUGH_FLAGS.items():
            if key in merged and merged[key] is not None:
                argv += [flag, str(merged[key])]
        calibrate = merged.get("calibrate", True)
        argv.append("--calibrate" if calibrate else "--no-calibrate")
        argv += ["--out-dir", str(out_dir), "--json"]

        log_path = logs_dir / f"{usgs_id}.log"
        try:
            proc = subprocess.run(
                argv,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=basin_timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            log_path.write_text((exc.stdout or "") + "\n--- STDERR ---\n" + (exc.stderr or ""), encoding="utf-8")
            return BasinResult(
                usgs_id=usgs_id,
                status="run_timeout",
                out_dir=str(out_dir),
                stage="workflow_run",
                wall_clock_s=time.monotonic() - started,
                error_tail=f"exceeded {basin_timeout_s:.0f}s timeout",
                finished_at=now_utc(),
            )

        log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr, encoding="utf-8")
        wall_clock = time.monotonic() - started

        if proc.returncode != 0:
            return BasinResult(
                usgs_id=usgs_id,
                status="run_failed",
                out_dir=str(out_dir),
                stage="workflow_run",
                wall_clock_s=wall_clock,
                error_tail=(proc.stderr or proc.stdout)[-2000:],
                finished_at=now_utc(),
            )

        payload = _extract_json_object(proc.stdout) or {}
        # `swat workflow run --json`'s top-level object is RunUSGSWorkflowResult:
        # {success, run_id, artifact_dir, evidence_summary_path, blocker_class,
        # values: {...effective_claim_tier, ...}}. blocker_class is top-level;
        # effective_claim_tier is only inside "values".
        effective_tier = (payload.get("values") or {}).get("effective_claim_tier")
        blocker = payload.get("blocker_class")
        candidate_evals = _count_engine_candidate_evaluations(out_dir)

    # Never admit an unverified run's decisions as training data.
    verify = subprocess.run(
        [sys.executable, "-m", "swatplus_builder.cli", "audit", "verify", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        return BasinResult(
            usgs_id=usgs_id,
            status="ledger_verify_failed",
            out_dir=str(out_dir),
            stage="audit_verify",
            wall_clock_s=wall_clock,
            effective_claim_tier=effective_tier,
            blocker_class=blocker,
            engine_candidate_evaluations=candidate_evals,
            error_tail=(verify.stderr or verify.stdout)[-2000:],
            finished_at=now_utc(),
        )

    typed_path = typed_dir / f"{usgs_id}.jsonl"
    typed = subprocess.run(
        [
            sys.executable, "-m", "swatplus_builder.cli", "audit", "typed", str(out_dir),
            "--out", str(typed_path),
            "--max-chars", str(typed_max_chars),
            "--max-options", str(typed_max_options),
            "--soft-target", typed_soft_target,
            "--temperature", str(typed_temperature),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if typed.returncode != 0:
        return BasinResult(
            usgs_id=usgs_id,
            status="typed_export_failed",
            out_dir=str(out_dir),
            stage="audit_typed",
            wall_clock_s=wall_clock,
            effective_claim_tier=effective_tier,
            blocker_class=blocker,
            engine_candidate_evaluations=candidate_evals,
            error_tail=(typed.stderr or typed.stdout)[-2000:],
            finished_at=now_utc(),
        )

    typed_count = sum(1 for _ in typed_path.open(encoding="utf-8")) if typed_path.is_file() else 0
    return BasinResult(
        usgs_id=usgs_id,
        status="ok",
        out_dir=str(out_dir),
        stage="audit_typed",
        wall_clock_s=wall_clock,
        effective_claim_tier=effective_tier,
        blocker_class=blocker,
        engine_candidate_evaluations=candidate_evals,
        typed_decision_count=typed_count,
        finished_at=now_utc(),
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--basins", required=True, type=Path, help="JSON array of basin specs (see module docstring).")
    p.add_argument("--out-root", required=True, type=Path, help="Per-basin run directories are created under here.")
    p.add_argument("--typed-out", type=Path, default=None, help="Combined typed-decisions JSONL (default: <out-root>/typed_decisions.jsonl).")
    p.add_argument("--workers", type=int, default=1, help="Basins run concurrently (default 1 = serial; each basin's own --sensitivity-workers/--anchor-workers already parallelize inside one basin, so raise this only with enough spare cores).")
    p.add_argument("--basin-timeout-s", type=float, default=4 * 3600, help="Kill a single basin's workflow run after this many seconds (default 4h).")
    p.add_argument("--skip-existing", action="store_true", help="Skip a basin whose out-dir already has evidence_summary.json.")
    # Defaults applied to every basin unless the basin spec overrides them.
    p.add_argument("--default-model-family", default="full")
    p.add_argument("--default-start", default="2000-01-01")
    p.add_argument("--default-end", default="2019-12-31")
    p.add_argument("--default-warmup-years", type=int, default=3)
    p.add_argument("--default-claim-tier", default="diagnostic")
    p.add_argument("--default-calibrate", dest="default_calibrate", action="store_true", default=True)
    p.add_argument("--default-no-calibrate", dest="default_calibrate", action="store_false")
    p.add_argument("--default-sensitivity-workers", type=int, default=4)
    p.add_argument("--default-anchor-workers", type=int, default=4)
    # Passed through to `swat audit typed` for every admitted basin.
    p.add_argument("--typed-max-chars", type=int, default=1600)
    p.add_argument("--typed-max-options", type=int, default=16)
    p.add_argument("--typed-soft-target", choices=["none", "softmax"], default="none")
    p.add_argument("--typed-temperature", type=float, default=0.05)
    p.add_argument("--dry-run", action="store_true", help="Print the plan and exit without running anything.")
    args = p.parse_args()

    specs = json.loads(args.basins.read_text(encoding="utf-8"))
    if not isinstance(specs, list) or not specs:
        print("--basins must be a non-empty JSON array", file=sys.stderr)
        return 2
    seen_ids = set()
    for spec in specs:
        if "usgs_id" not in spec:
            print(f"basin spec missing usgs_id: {spec}", file=sys.stderr)
            return 2
        if spec["usgs_id"] in seen_ids:
            print(f"duplicate usgs_id in --basins: {spec['usgs_id']}", file=sys.stderr)
            return 2
        seen_ids.add(spec["usgs_id"])

    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    logs_dir = out_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    typed_dir = out_root / "typed"
    typed_dir.mkdir(exist_ok=True)
    typed_out = args.typed_out or (out_root / "typed_decisions.jsonl")
    manifest_path = out_root / "batch_manifest.jsonl"

    defaults = {
        "model_family": args.default_model_family,
        "start": args.default_start,
        "end": args.default_end,
        "warmup_years": args.default_warmup_years,
        "claim_tier": args.default_claim_tier,
        "calibrate": args.default_calibrate,
        "sensitivity_workers": args.default_sensitivity_workers,
        "anchor_workers": args.default_anchor_workers,
    }

    print(f"[{now_utc()}] {len(specs)} basin(s), workers={args.workers}, out_root={out_root}")
    if args.dry_run:
        for spec in specs:
            print(f"  would run usgs_id={spec['usgs_id']} spec={spec}")
        return 0

    manifest_fh = manifest_path.open("a", encoding="utf-8")
    results: list[BasinResult] = []

    def _record(result: BasinResult) -> None:
        results.append(result)
        manifest_fh.write(json.dumps(asdict(result)) + "\n")
        manifest_fh.flush()
        print(f"[{now_utc()}] usgs_id={result.usgs_id} status={result.status} stage={result.stage} "
              f"wall_clock_s={result.wall_clock_s:.0f} tier={result.effective_claim_tier}")

    run_kwargs = dict(
        out_root=out_root,
        logs_dir=logs_dir,
        typed_dir=typed_dir,
        defaults=defaults,
        basin_timeout_s=args.basin_timeout_s,
        skip_existing=args.skip_existing,
        typed_max_chars=args.typed_max_chars,
        typed_max_options=args.typed_max_options,
        typed_soft_target=args.typed_soft_target,
        typed_temperature=args.typed_temperature,
    )

    if args.workers <= 1:
        for spec in specs:
            _record(_run_one_basin(spec, **run_kwargs))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_run_one_basin, spec, **run_kwargs): spec["usgs_id"] for spec in specs}
            for fut in concurrent.futures.as_completed(futures):
                _record(fut.result())

    manifest_fh.close()

    # Concatenate every admitted (status == "ok") basin's typed-decision file
    # into the combined output. Nothing from a non-"ok" basin is included.
    admitted = [r for r in results if r.status == "ok"]
    with typed_out.open("w", encoding="utf-8") as out_fh:
        for r in admitted:
            src = typed_dir / f"{r.usgs_id}.jsonl"
            if src.is_file():
                out_fh.write(src.read_text(encoding="utf-8"))

    summary = {
        "generated_at": now_utc(),
        "n_basins_requested": len(specs),
        "n_ok": len(admitted),
        "n_failed": len(results) - len(admitted),
        "by_status": {status: sum(1 for r in results if r.status == status) for status in sorted({r.status for r in results})},
        "total_wall_clock_s": sum(r.wall_clock_s for r in results),
        "total_engine_candidate_evaluations": sum(r.engine_candidate_evaluations or 0 for r in results),
        "total_typed_decisions": sum(r.typed_decision_count or 0 for r in admitted),
        "typed_out": str(typed_out),
        "manifest": str(manifest_path),
    }
    (out_root / "batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out_root / "batch_summary.csv").open("w", newline="", encoding="utf-8") as csv_fh:
        writer = csv.DictWriter(csv_fh, fieldnames=list(asdict(results[0]).keys()) if results else [])
        if results:
            writer.writeheader()
            for r in results:
                writer.writerow(asdict(r))

    print(f"[{now_utc()}] done: {summary['n_ok']}/{summary['n_basins_requested']} basins admitted, "
          f"{summary['total_typed_decisions']} typed decisions -> {typed_out}")
    print(f"cost: {summary['total_wall_clock_s']:.0f}s wall-clock, "
          f"{summary['total_engine_candidate_evaluations']} engine candidate evaluations")
    return 0 if admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
