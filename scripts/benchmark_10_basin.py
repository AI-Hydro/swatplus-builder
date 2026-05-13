#!/usr/bin/env python3
"""Production-grade 10-basin benchmark pipeline.

For each USGS gauge:
  1. Build full-mode TxtInOut (delineation, soils, weather, editor)
  2. Apply routing fixes + 2-year warmup
  3. Run engine (native arm64 rev61)
  4. Auto-detect terminal outlet
  5. Calibrate CN2 (grid search, ±40 offset)
  6. Classify tier (water balance gate + KGE/NSE)
  7. Write provenance + evidence summary

Usage:
  python scripts/benchmark_10_basin.py --gauges 02129000,01547700,03349000
"""

from __future__ import annotations
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
SWAT_EXE = os.environ.get("SWATPLUS_EXE", str(REPO / "bin" / "swatplus_exe"))

# ── Imports from swatplus-builder ─────────────────────────────────────────

def _warmup(tio: Path, years: int = 2):
    from swatplus_builder.full_mode.warmup import apply_warmup
    return apply_warmup(tio, warmup_years=years)

def _routing_fixes(tio: Path):
    from swatplus_builder.full_mode.routing_fixes import apply_full_routing_fixes
    apply_full_routing_fixes(tio)

def _evaluate(txt_dir: Path, obs_path: Path) -> dict:
    """Run evaluate_run with auto outlet detection."""
    from swatplus_builder.output.eval import evaluate_run
    q_obs = pd.read_csv(obs_path, index_col=0, parse_dates=True)["obs"]
    sim = txt_dir / "channel_sd_day.txt"
    if not sim.exists():
        return {"nse": -999, "kge": -999, "outlet": None}
    _, metrics, diag = evaluate_run(sim, q_obs, outlet_gis_id=1,
                                     outlet_policy="auto", return_diagnostics=True)
    outlet = diag.get("selected_outlet_gis_id")
    metrics["outlet"] = outlet
    return metrics

def _classify(tio: Path, nse: float, kge: float) -> dict:
    """Run water balance gate classification."""
    from swatplus_builder.full_mode.water_balance_gate import check_water_balance
    result = check_water_balance(tio, nse=nse, kge=kge)
    return {
        "allowed_tiers": result["allowed_tiers"],
        "conditions": result["conditions"],
        "wb": result["wb"],
    }

CN2_LU = {"wood_f","wood_p","pastg_g","pastg_f","pastg_p","pasth",
          "urban","agrl_rot","rc_strow_g","rc_strow_p","fal_bare"}

def _patch_cn2(txt_dir: Path, offset: float):
    """Shift all CN2 values by offset, clamping [30, 98]."""
    f = txt_dir / "cntable.lum"
    lines = f.read_text().split("\n")
    out = []
    for ln in lines:
        parts = ln.split()
        if len(parts) >= 5 and parts[0] in CN2_LU:
            for i in range(1, 5):
                try:
                    val = float(parts[i])
                    parts[i] = f"{max(30.0, min(98.0, val + offset)):.5f}"
                except ValueError: pass
        out.append(" ".join(parts))
    f.write_text("\n".join(out))

def _run_swat(txt_dir: Path) -> bool:
    env = {**os.environ, "OMP_NUM_THREADS": "1"}
    if sys.platform == "darwin":
        env["DYLD_LIBRARY_PATH"] = str(Path(SWAT_EXE).parent)
    try:
        proc = subprocess.run([SWAT_EXE], capture_output=True, text=True,
                             cwd=str(txt_dir), env=env, timeout=600)
        return proc.returncode == 0
    except Exception:
        return False

def _build_basin(gauge: str, out_dir: Path, sim_start="2015-01-01", sim_end="2015-12-31") -> Optional[Path]:
    """Build full-mode TxtInOut for a USGS gauge. Returns TxtInOut path or None."""
    env = os.environ.copy()
    env["USGS_ID"] = gauge
    proc = subprocess.run(
        [sys.executable, str(REPO / "examples" / "build_real_basin.py"),
         str(out_dir), "--model-family", "full",
         "--start", sim_start, "--end", sim_end, "--run"],
        capture_output=True, text=True, env=env, timeout=3600,
    )
    if proc.returncode != 0:
        print(f"   BUILD FAILED: {proc.stderr[-200:]}")
        return None
    tio = out_dir / "project" / "Scenarios" / "Default" / "TxtInOut"
    return tio if tio.is_dir() else None

def calibrate_cn2_gauge(tio: Path, obs_path: Path) -> dict:
    """Grid search CN2 offsets. Returns best metrics."""
    best = {"nse": -999, "kge": -999, "offset": 0}
    for offset in range(-40, 45, 5):
        work = Path(tempfile.mkdtemp(prefix="bench_cn2_"))
        shutil.copytree(tio, work, dirs_exist_ok=True)
        _patch_cn2(work, offset)

        for stale in work.glob("simulation.out"): stale.unlink()
        if not _run_swat(work):
            shutil.rmtree(work, ignore_errors=True)
            continue

        metrics = _evaluate(work, obs_path)
        nse, kge = metrics.get("nse", -999), metrics.get("kge", -999)
        if kge > best["kge"]:
            best = {"nse": nse, "kge": kge, "offset": offset, "outlet": metrics.get("outlet")}
        shutil.rmtree(work, ignore_errors=True)
    return best

def run_benchmark(gauges: list[str], root: Path = Path("multibasin_test")):
    print(f"{'='*80}")
    print(f"10-BASIN BENCHMARK — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*80}")

    results = []
    for i, gauge in enumerate(gauges):
        t0 = time.time()
        out_dir = root / f"{gauge}_bench"
        print(f"\n[{i+1}/{len(gauges)}] {gauge} — building...")

        # Step 1: Build
        tio = _build_basin(gauge, out_dir)
        if tio is None:
            results.append({"gauge": gauge, "status": "BUILD_FAILED", "elapsed_s": time.time() - t0})
            continue

        # Step 2: Apply fixes + warmup
        _routing_fixes(tio)
        _warmup(tio, years=2)

        # Step 3: Baseline evaluation
        baseline = _evaluate(tio, out_dir / "outputs" / "obs_q.csv")
        print(f"   Baseline: NSE={baseline.get('nse',-999):.3f} KGE={baseline.get('kge',-999):.3f} outlet={baseline.get('outlet')}")

        # Step 4: Calibrate
        print(f"   Calibrating CN2...")
        cal = calibrate_cn2_gauge(tio, out_dir / "outputs" / "obs_q.csv")
        print(f"   Best: CN2{cal['offset']:+d} → NSE={cal['nse']:.3f} KGE={cal['kge']:.3f}")

        # Step 5: Classify
        gate = _classify(tio, cal["nse"], cal["kge"])
        tier = "research_grade" if "research_grade" in gate["allowed_tiers"] else \
               "diagnostic" if "diagnostic" in gate["allowed_tiers"] else "exploratory"

        elapsed = time.time() - t0
        result = {
            "gauge": gauge, "status": "OK",
            "baseline_nse": baseline.get("nse"), "baseline_kge": baseline.get("kge"),
            "best_nse": cal["nse"], "best_kge": cal["kge"],
            "cn2_offset": cal["offset"], "outlet": cal.get("outlet"),
            "tier": tier, "elapsed_s": elapsed,
        }
        results.append(result)
        print(f"   → {tier} ({elapsed:.0f}s)")

    # Summary
    print(f"\n{'='*80}")
    print(f"{'Gauge':>12} {'CN2':>5} {'BaseKGE':>8} {'BestKGE':>8} {'BestNSE':>8} {'Tier':>18} {'Time'}")
    print("-" * 80)
    for r in results:
        if r["status"] == "OK":
            print(f"{r['gauge']:>12} {r['cn2_offset']:>+5d} {r['baseline_kge']:>8.3f} {r['best_kge']:>8.3f} {r['best_nse']:>8.3f} {r['tier']:>18} {r['elapsed_s']:>5.0f}s")
        else:
            print(f"{r['gauge']:>12} {'-':>5} {'-':>8} {'-':>8} {'-':>8} {r['status']:>18}")

    # Write benchmark.json
    out_path = root / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSaved: {out_path}")

    # Count tiers
    tiers = [r.get("tier") for r in results if r["status"] == "OK"]
    research = tiers.count("research_grade")
    diagnostic = tiers.count("diagnostic")
    exploratory = tiers.count("exploratory")
    print(f"Research-grade: {research}/{len(gauges)}, Diagnostic: {diagnostic}, Exploratory: {exploratory}")
    return results

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--gauges", default="02129000,01547700,03349000,01654000,01491000")
    args = p.parse_args()
    gauges = [g.strip() for g in args.gauges.split(",") if g.strip()]
    run_benchmark(gauges)
