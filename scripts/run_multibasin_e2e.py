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

import pandas as pd
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
    n_subbasins: int | None = None
    n_channels: int | None = None
    n_terminals: int | None = None
    n_hrus: int | None = None
    object_out: int | None = None
    terminal_channels_with_flow: int | None = None
    terminal_channels_total: int | None = None
    max_terminal_flo_out: float | None = None
    mean_terminal_flo_out: float | None = None
    selected_outlet_gis_id: int | None = None
    outlet_policy: str | None = None
    outlet_selection_reason: str | None = None
    requested_outlet_is_terminal: bool | None = None
    outlet_provenance_sha256: str | None = None
    soil_mode: str | None = None
    pct_fallback_soils: float | None = None
    nse: float | None = None
    kge: float | None = None
    sim_obs_volume_ratio: float | None = None
    realism_flags: str | None = None
    topology_failure_class: str | None = None
    topology_failure_detail: str | None = None
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
    col_idx: dict[str, int] | None = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        if "gis_id" in parts and "obj_typ" in parts:
            col_idx = {c: i for i, c in enumerate(parts)}
            continue
        if col_idx is None:
            if len(parts) >= 14 and parts[0].isdigit() and parts[13] == "out":
                terminals.add(int(parts[0]))
            continue
        try:
            obj_typ = parts[col_idx["obj_typ"]]
            if obj_typ != "out":
                continue
            terminals.add(int(parts[col_idx["gis_id"]]))
        except (KeyError, IndexError, ValueError):
            continue
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


def read_optional_counts(run_dir: Path) -> tuple[int | None, int | None, int | None, int | None]:
    ws_json = run_dir / "delin" / "watershed_result.json"
    hru_json = run_dir / "delin" / "hrus" / "hru_catalog.json"

    n_subbasins = None
    n_channels = None
    n_terminals = None
    n_hrus = None
    if ws_json.exists():
        try:
            ws = json.loads(ws_json.read_text(encoding="utf-8"))
            n_subbasins = int(ws.get("stats", {}).get("n_subbasins", 0))
            n_channels = int(ws.get("stats", {}).get("n_channels", 0))
            n_terminals = int(ws.get("stats", {}).get("n_terminals", 0))
        except Exception:
            pass
    if hru_json.exists():
        try:
            hru = json.loads(hru_json.read_text(encoding="utf-8"))
            n_hrus = int(hru.get("stats", {}).get("n_hrus", 0))
        except Exception:
            pass

    return n_subbasins, n_channels, n_terminals, n_hrus


def load_eval_diagnostics(site_dir: Path) -> dict:
    md = site_dir / "metadata.json"
    m = site_dir / "reports" / "metrics.json"
    out: dict = {}
    if md.exists():
        try:
            out.update(json.loads(md.read_text(encoding="utf-8")))
        except Exception:
            pass
    if m.exists():
        try:
            out["metrics"] = json.loads(m.read_text(encoding="utf-8"))
        except Exception:
            pass
    alignment = site_dir / "outputs" / "alignment.csv"
    if alignment.exists():
        try:
            df = pd.read_csv(alignment)
            if {"obs", "sim"}.issubset(df.columns):
                obs_sum = float(df["obs"].fillna(0.0).sum())
                sim_sum = float(df["sim"].fillna(0.0).sum())
                if abs(obs_sum) > 1e-12:
                    out["sim_obs_volume_ratio"] = sim_sum / obs_sum
        except Exception:
            pass
    return out


def build_realism_flags(
    diag: dict,
    n_subbasins: int | None,
    n_channels: int | None,
    n_terminals: int | None,
    n_hrus: int | None,
) -> list[str]:
    flags: list[str] = []
    if diag.get("requested_outlet_is_terminal") is False:
        flags.append("outlet_requested_non_terminal")

    soil_mode = str(diag.get("soil_mode", ""))
    if soil_mode == "synthetic":
        flags.append("soil_synthetic_mode")
    pct_fallback = float(diag.get("pct_fallback_soils", 0.0) or 0.0)
    if pct_fallback > 0.10:
        flags.append("soil_fallback_gt_10pct")

    ratio = diag.get("sim_obs_volume_ratio")
    if isinstance(ratio, (int, float)):
        if ratio > 3.0:
            flags.append("volume_bias_high")
        elif ratio < 0.33:
            flags.append("volume_bias_low")

    if n_subbasins is not None and n_channels is not None and n_subbasins > 0:
        if n_channels > 20 * n_subbasins:
            flags.append("channels_per_subbasin_extreme")
    if n_terminals is not None and n_terminals > 1:
        flags.append("multiple_terminal_channels")
    if n_hrus is not None and n_subbasins is not None and n_subbasins > 0:
        if n_hrus <= n_subbasins:
            flags.append("hru_count_suspiciously_low")
    return flags


def run_site(
    usgs_id: str,
    out_root: Path,
    log_path: Path,
    run_engine: bool,
    *,
    sim_start: str,
    sim_end: str,
) -> SiteResult:
    started = time.time()
    site_dir = out_root / f"usgs_{usgs_id}"
    area: float | None = None

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
        demo.SIM_START = sim_start
        demo.SIM_END = sim_end
        demo.main(
            site_dir.resolve(),
            run_engine=run_engine,
            sim_start=sim_start,
            sim_end=sim_end,
        )

        txtinout = site_dir / "project" / "Scenarios" / "Default" / "TxtInOut"
        object_out, _lcha = parse_object_cnt(txtinout)
        terminal_ids = parse_terminal_channel_ids(txtinout)
        nz, nt, vmax, vmean = parse_terminal_flow_stats(txtinout, terminal_ids)
        n_subbasins, n_channels, n_terminals, n_hrus = read_optional_counts(site_dir)
        eval_diag = load_eval_diagnostics(site_dir)
        metrics = eval_diag.get("metrics", {}) if isinstance(eval_diag.get("metrics"), dict) else {}
        realism_flags = build_realism_flags(eval_diag, n_subbasins, n_channels, n_terminals, n_hrus)

        result = SiteResult(
            usgs_id=usgs_id,
            status="success",
            run_dir=str(site_dir),
            elapsed_s=time.time() - started,
            basin_area_km2=area,
            n_subbasins=n_subbasins,
            n_channels=n_channels,
            n_terminals=n_terminals,
            n_hrus=n_hrus,
            object_out=object_out,
            terminal_channels_with_flow=nz,
            terminal_channels_total=nt,
            max_terminal_flo_out=vmax,
            mean_terminal_flo_out=vmean,
            selected_outlet_gis_id=(
                int(eval_diag["selected_outlet_gis_id"])
                if "selected_outlet_gis_id" in eval_diag
                else None
            ),
            outlet_policy=str(eval_diag.get("outlet_policy", "")) or None,
            outlet_selection_reason=str(eval_diag.get("outlet_selection_reason", "")) or None,
            requested_outlet_is_terminal=(
                eval_diag["requested_outlet_is_terminal"]
                if isinstance(eval_diag.get("requested_outlet_is_terminal"), bool)
                else None
            ),
            outlet_provenance_sha256=str(eval_diag.get("outlet_provenance_sha256", "")) or None,
            soil_mode=str(eval_diag.get("soil_mode", "")) or None,
            pct_fallback_soils=float(eval_diag.get("pct_fallback_soils", 0.0) or 0.0),
            nse=float(metrics["nse"]) if "nse" in metrics else None,
            kge=float(metrics["kge"]) if "kge" in metrics else None,
            sim_obs_volume_ratio=float(eval_diag["sim_obs_volume_ratio"])
            if "sim_obs_volume_ratio" in eval_diag
            else None,
            realism_flags=";".join(realism_flags) if realism_flags else "",
        )

        append_jsonl(log_path, {
            "timestamp_utc": now_utc(),
            "iteration": usgs_id,
            "hypothesis": "Successful run should produce non-zero terminal channel flow.",
            "action_taken": "Parsed object.cnt + chandeg.con + channel_sd_day.txt",
            "evidence": asdict(result),
            "result": "accepted" if nz > 0 and not realism_flags else "warning",
            "next_step": "Record and continue to next basin",
        })
        return result

    except Exception as exc:
        from swatplus_builder.errors import SwatBuilderPipelineError

        err = "".join(traceback.format_exception(exc)).strip()
        topo_class: str | None = None
        topo_detail: str | None = None
        failed_status = "failed"

        if isinstance(exc, SwatBuilderPipelineError):
            msg = str(exc).lower()
            ctx = getattr(exc, "context", {})
            if "area mismatch" in msg:
                topo_class = "area_mismatch"
                ratio = ctx.get("area_ratio", "?")
                gen = ctx.get("generated_area_km2", "?")
                exp = ctx.get("expected_area_km2", "?")
                topo_detail = f"generated={gen} km2, expected={exp} km2, ratio={ratio}"
                failed_status = "topology_gate_failure"
            elif "channel explosion" in msg:
                topo_class = "channel_explosion"
                ratio = ctx.get("channels_per_subbasin", "?")
                topo_detail = f"channels_per_subbasin={ratio}"
                failed_status = "topology_gate_failure"
            elif "terminal" in msg and "terminal" in str(ctx.get("n_terminals", "").__class__):
                topo_class = "terminal_explosion"
                topo_detail = f"n_terminals={ctx.get('n_terminals', '?')}"
                failed_status = "topology_gate_failure"

        result = SiteResult(
            usgs_id=usgs_id,
            status=failed_status,
            run_dir=str(site_dir),
            elapsed_s=time.time() - started,
            basin_area_km2=area,
            topology_failure_class=topo_class,
            topology_failure_detail=topo_detail,
            error=err,
        )
        append_jsonl(log_path, {
            "timestamp_utc": now_utc(),
            "iteration": usgs_id,
            "hypothesis": "Pipeline failure indicates unresolved structural or data-compatibility edge case.",
            "action_taken": "Captured exception traceback",
            "evidence": {
                "error": str(exc),
                "topology_failure_class": topo_class,
                "topology_failure_detail": topo_detail,
            },
            "result": "rejected",
            "next_step": (
                "Investigate outlet snapping / DEM extent for topology_gate_failure; "
                "proceed to next basin."
            ) if topo_class else "Proceed to next basin and summarize failure pattern",
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
    parser.add_argument("--start", default="2015-01-01", help="Simulation start date (YYYY-MM-DD).")
    parser.add_argument("--end", default="2015-12-31", help="Simulation end date (YYYY-MM-DD).")

    args = parser.parse_args()

    out_root = Path("tests/_artifacts/e2e_runs") / args.batch_name
    out_root.mkdir(parents=True, exist_ok=True)

    log_path = out_root / "investigation_log.jsonl"
    append_jsonl(log_path, {
        "timestamp_utc": now_utc(),
        "iteration": 0,
        "hypothesis": "Recent routing fixes should improve out-of-sample robustness across multiple USGS basins.",
        "action_taken": "Initialize batch run",
        "evidence": {
            "sites": args.sites,
            "run_engine": args.run_engine,
            "batch_dir": str(out_root),
            "start": args.start,
            "end": args.end,
        },
        "result": "in_progress",
        "next_step": "Run each site independently and capture diagnostics",
    })

    results: list[SiteResult] = []
    for sid in args.sites:
        print(f"\n=== Running USGS {sid} ===")
        res = run_site(
            sid,
            out_root,
            log_path,
            run_engine=args.run_engine,
            sim_start=args.start,
            sim_end=args.end,
        )
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
    n_topo = sum(1 for r in results if r.status == "topology_gate_failure")
    n_fail = len(results) - n_ok - n_topo
    lines = [
        "# Multi-Basin E2E Batch",
        "",
        f"- Generated: `{now_utc()}`",
        f"- Sites: `{', '.join(args.sites)}`",
        f"- Period: `{args.start}` to `{args.end}`",
        f"- Success: `{n_ok}/{len(results)}`",
        f"- Topology gate failures: `{n_topo}`",
        f"- Other failures: `{n_fail}`",
        f"- Investigation log: `{log_path}`",
        "",
        "## Results",
        "",
        "| USGS | Status | Elapsed (s) | object_out | Terminal with flow | Terminal total | Max terminal flo_out | Topology failure |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        topo_col = r.topology_failure_class or ""
        if r.topology_failure_detail:
            topo_col = f"{topo_col}: {r.topology_failure_detail}"
        lines.append(
            f"| {r.usgs_id} | {r.status} | {r.elapsed_s:.1f} | {r.object_out if r.object_out is not None else ''} | "
            f"{r.terminal_channels_with_flow if r.terminal_channels_with_flow is not None else ''} | "
            f"{r.terminal_channels_total if r.terminal_channels_total is not None else ''} | "
            f"{r.max_terminal_flo_out if r.max_terminal_flo_out is not None else ''} | "
            f"{topo_col} |"
        )

    if n_topo:
        lines += [
            "",
            "## Topology Gate Failures",
            "",
            "| USGS | Class | Detail |",
            "|---|---|---|",
        ]
        for r in results:
            if r.topology_failure_class:
                lines.append(
                    f"| {r.usgs_id} | {r.topology_failure_class} | {r.topology_failure_detail or ''} |"
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
