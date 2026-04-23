#!/usr/bin/env python3
"""Batch real-basin SWAT+ E2E validation across multiple USGS gauges.

Writes all artifacts under tests/_artifacts/e2e_runs/<batch_dir>/ and records:
- step-by-step JSONL investigation log,
- per-site status JSON,
- CSV summary.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pynhd import NLDI

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import examples.real_basin_marsh_creek as demo


@dataclass
class SiteResult:
    usgs_id: str
    status: str
    run_dir: str
    elapsed_s: float
    basin_area_km2: float | None = None
    n_channels: int | None = None
    n_hrus: int | None = None
    object_out: int | None = None
    terminal_channels_with_flow: int | None = None
    terminal_channels_total: int | None = None
    max_terminal_flo_out: float | None = None
    mean_terminal_flo_out: float | None = None
    error: str | None = None


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def get_basin_area_km2(usgs_id: str) -> float:
    basin = NLDI().get_basins(usgs_id).to_crs("EPSG:5070")
    return float(basin.area.sum() / 1e6)


def parse_object_cnt(txtinout: Path) -> tuple[int | None, int | None]:
    p = txtinout / "object.cnt"
    if not p.exists():
        return None, None
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        return None, None
    vals = lines[2].split()
    if len(vals) < 18:
        return None, None
    # columns: ... out lcha ...
    out = int(vals[16])
    lcha = int(vals[17])
    return out, lcha


def parse_terminal_channel_ids(txtinout: Path) -> set[int]:
    p = txtinout / "chandeg.con"
    if not p.exists():
        return set()
    terminals: set[int] = set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[2:]:
        parts = line.split()
        if len(parts) < 16:
            continue
        try:
            unit_id = int(parts[0])
        except ValueError:
            continue
        obj_typ = parts[13]
        if obj_typ == "out":
            terminals.add(unit_id)
    return terminals


def parse_terminal_flow_stats(txtinout: Path, terminal_ids: set[int]) -> tuple[int, int, float, float]:
    p = txtinout / "channel_sd_day.txt"
    if not p.exists() or not terminal_ids:
        return 0, 0, 0.0, 0.0

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 4:
        return 0, 0, 0.0, 0.0

    header = lines[1].split()
    if "unit" not in header or "flo_out" not in header:
        return 0, 0, 0.0, 0.0

    uidx = header.index("unit")
    fidx = header.index("flo_out")
    vals: list[float] = []
    for line in lines[3:]:
        parts = line.split()
        if len(parts) <= max(uidx, fidx):
            continue
        try:
            unit = int(parts[uidx])
            if unit not in terminal_ids:
                continue
            vals.append(float(parts[fidx]))
        except ValueError:
            continue

    if not vals:
        return 0, len(terminal_ids), 0.0, 0.0
    return sum(1 for v in vals if v > 0), len(terminal_ids), max(vals), (sum(vals) / len(vals))


def read_optional_counts(run_dir: Path) -> tuple[int | None, int | None]:
    ws_json = run_dir / "delin" / "watershed_result.json"
    hru_json = run_dir / "delin" / "hrus" / "hru_catalog.json"

    n_channels = None
    n_hrus = None
    if ws_json.exists():
        try:
            ws = json.loads(ws_json.read_text(encoding="utf-8"))
            n_channels = int(ws.get("stats", {}).get("n_channels", 0))
        except Exception:
            pass
    if hru_json.exists():
        try:
            hru = json.loads(hru_json.read_text(encoding="utf-8"))
            n_hrus = int(hru.get("stats", {}).get("n_hrus", 0))
        except Exception:
            pass

    return n_channels, n_hrus


def run_site(usgs_id: str, out_root: Path, log_path: Path, run_engine: bool) -> SiteResult:
    started = time.time()
    site_dir = out_root / f"usgs_{usgs_id}"

    append_jsonl(log_path, {
        "timestamp_utc": now_utc(),
        "iteration": usgs_id,
        "hypothesis": "Current pipeline should run end-to-end on an unseen basin with physically connected channel routing.",
        "action_taken": "Start full real-basin run using examples.real_basin_marsh_creek main() with dynamic NLDI area guard.",
        "evidence": "Run started",
        "result": "in_progress",
        "next_step": "Compute basin area and launch pipeline",
    })

    try:
        area = get_basin_area_km2(usgs_id)
        append_jsonl(log_path, {
            "timestamp_utc": now_utc(),
            "iteration": usgs_id,
            "hypothesis": "Area guard must match snapped NLDI basin for this USGS ID.",
            "action_taken": f"Computed NLDI area for {usgs_id}",
            "evidence": {"area_km2": area},
            "result": "accepted",
            "next_step": "Run full E2E pipeline",
        })

        demo.STATION_ID = usgs_id
        demo.EXPECTED_AREA_KM2 = area
        demo.SIM_START = "2015-01-01"
        demo.SIM_END = "2015-12-31"
        demo.main(site_dir.resolve(), run_engine=run_engine)

        txtinout = site_dir / "project" / "Scenarios" / "Default" / "TxtInOut"
        object_out, _lcha = parse_object_cnt(txtinout)
        terminal_ids = parse_terminal_channel_ids(txtinout)
        nz, nt, vmax, vmean = parse_terminal_flow_stats(txtinout, terminal_ids)
        n_channels, n_hrus = read_optional_counts(site_dir)

        result = SiteResult(
            usgs_id=usgs_id,
            status="success",
            run_dir=str(site_dir),
            elapsed_s=time.time() - started,
            basin_area_km2=area,
            n_channels=n_channels,
            n_hrus=n_hrus,
            object_out=object_out,
            terminal_channels_with_flow=nz,
            terminal_channels_total=nt,
            max_terminal_flo_out=vmax,
            mean_terminal_flo_out=vmean,
        )

        append_jsonl(log_path, {
            "timestamp_utc": now_utc(),
            "iteration": usgs_id,
            "hypothesis": "Successful run should produce non-zero terminal channel flow.",
            "action_taken": "Parsed object.cnt + chandeg.con + channel_sd_day.txt",
            "evidence": asdict(result),
            "result": "accepted" if nz > 0 else "warning",
            "next_step": "Record and continue to next basin",
        })
        return result

    except Exception as exc:
        err = "".join(traceback.format_exception(exc)).strip()
        result = SiteResult(
            usgs_id=usgs_id,
            status="failed",
            run_dir=str(site_dir),
            elapsed_s=time.time() - started,
            error=err,
        )
        append_jsonl(log_path, {
            "timestamp_utc": now_utc(),
            "iteration": usgs_id,
            "hypothesis": "Pipeline failure indicates unresolved structural or data-compatibility edge case.",
            "action_taken": "Captured exception traceback",
            "evidence": {"error": str(exc)},
            "result": "rejected",
            "next_step": "Proceed to next basin and summarize failure pattern",
        })
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-basin real E2E validation.")
    parser.add_argument(
        "--sites",
        nargs="+",
        default=["01547700", "01013500", "03339000", "02087500"],
        help="USGS site IDs",
    )
    parser.add_argument(
        "--run-engine",
        action="store_true",
        help="Run SWAT+ engine (recommended)",
    )
    parser.add_argument(
        "--batch-name",
        default=f"multibasin_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Batch output folder name under tests/_artifacts/e2e_runs/",
    )

    args = parser.parse_args()

    out_root = Path("tests/_artifacts/e2e_runs") / args.batch_name
    out_root.mkdir(parents=True, exist_ok=True)

    log_path = out_root / "investigation_log.jsonl"
    append_jsonl(log_path, {
        "timestamp_utc": now_utc(),
        "iteration": 0,
        "hypothesis": "Recent routing fixes should improve out-of-sample robustness across multiple USGS basins.",
        "action_taken": "Initialize batch run",
        "evidence": {"sites": args.sites, "run_engine": args.run_engine, "batch_dir": str(out_root)},
        "result": "in_progress",
        "next_step": "Run each site independently and capture diagnostics",
    })

    results: list[SiteResult] = []
    for sid in args.sites:
        print(f"\n=== Running USGS {sid} ===")
        res = run_site(sid, out_root, log_path, run_engine=args.run_engine)
        results.append(res)
        print(f"{sid}: {res.status} ({res.elapsed_s:.1f}s)")

    summary_json = out_root / "summary.json"
    summary_csv = out_root / "summary.csv"
    summary_md = out_root / "README.md"

    summary_json.write_text(
        json.dumps([asdict(r) for r in results], indent=2),
        encoding="utf-8",
    )

    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()) if results else ["usgs_id", "status"])
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))

    n_ok = sum(1 for r in results if r.status == "success")
    lines = [
        "# Multi-Basin E2E Batch",
        "",
        f"- Generated: `{now_utc()}`",
        f"- Sites: `{', '.join(args.sites)}`",
        f"- Success: `{n_ok}/{len(results)}`",
        f"- Investigation log: `{log_path}`",
        "",
        "## Results",
        "",
        "| USGS | Status | Elapsed (s) | object_out | Terminal with flow | Terminal total | Max terminal flo_out |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.usgs_id} | {r.status} | {r.elapsed_s:.1f} | {r.object_out if r.object_out is not None else ''} | "
            f"{r.terminal_channels_with_flow if r.terminal_channels_with_flow is not None else ''} | "
            f"{r.terminal_channels_total if r.terminal_channels_total is not None else ''} | "
            f"{r.max_terminal_flo_out if r.max_terminal_flo_out is not None else ''} |"
        )
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    append_jsonl(log_path, {
        "timestamp_utc": now_utc(),
        "iteration": 999,
        "hypothesis": "Batch summary should quantify current portability across basins.",
        "action_taken": "Wrote summary artifacts",
        "evidence": {"summary_json": str(summary_json), "summary_csv": str(summary_csv), "summary_md": str(summary_md)},
        "result": "completed",
        "next_step": "Review failures and prioritize fixes",
    })

    print(f"\nBatch complete: {n_ok}/{len(results)} successful")
    print(f"Artifacts: {out_root}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
