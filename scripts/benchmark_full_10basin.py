#!/usr/bin/env python3
"""Research-grade 10-basin full-mode benchmark.

Build → Fix → Warmup → Calibrate → Gate-classify → Provenance
Target: ≥7/10 basins reach KGE ≥ 0.40 (research_grade).

Usage:
  python scripts/benchmark_full_10basin.py
"""

from __future__ import annotations
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from datetime import datetime
import numpy as np, pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
SWAT_EXE = os.environ.get("SWATPLUS_EXE", str(REPO / "bin" / "swatplus_exe"))

# ── 10 basin suite ─────────────────────────────────────────────────────
BASINS = [
    "02129000", "01547700", "03349000", "01654000", "01491000",
    "01013500", "03351500", "03353000", "01493500", "12031000",
]

CN2_LU = {"wood_f","wood_p","pastg_g","pastg_f","pastg_p","pasth",
          "urban","agrl_rot","rc_strow_g","rc_strow_p","fal_bare"}

# ── Core functions ─────────────────────────────────────────────────────

def build_basin(gauge: str, out_dir: Path) -> bool:
    """Build full-mode TxtInOut. Returns True on success."""
    env = os.environ.copy()
    env["USGS_ID"] = gauge
    proc = subprocess.run(
        [sys.executable, str(REPO / "examples" / "build_real_basin.py"),
         str(out_dir), "--model-family", "full",
         "--start", "2010-01-01", "--end", "2019-12-31", "--run", "--warmup-years", "0"],
        capture_output=True, text=True, env=env, timeout=3600,
    )
    ok = proc.returncode == 0
    if not ok:
        print(f"   BUILD FAILED: {proc.stderr[-300:]}")
    return ok

def fix_and_warmup(tio: Path, warmup_years: int = 3):
    """Apply routing fixes and warmup."""
    from swatplus_builder.full_mode.routing_fixes import apply_full_routing_fixes
    apply_full_routing_fixes(tio)
    if warmup_years > 0:
        from swatplus_builder.full_mode.warmup import apply_warmup
        apply_warmup(tio, warmup_years=warmup_years)

def run_engine(tio: Path) -> bool:
    env = {**os.environ, "OMP_NUM_THREADS": "1"}
    if sys.platform == "darwin":
        env["DYLD_LIBRARY_PATH"] = str(Path(SWAT_EXE).parent)
    proc = subprocess.run([SWAT_EXE], capture_output=True, text=True,
                         cwd=str(tio), env=env, timeout=600)
    return proc.returncode == 0

def patch_cn2(tio: Path, offset: float):
    f = tio / "cntable.lum"
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

def evaluate(tio: Path, obs_path: Path) -> dict:
    from swatplus_builder.output.eval import evaluate_run
    q_obs = pd.read_csv(obs_path, index_col=0, parse_dates=True)["obs"]
    sim = tio / "channel_sd_day.txt"
    if not sim.exists():
        return {"nse": -999, "kge": -999, "outlet": None}
    _, metrics, diag = evaluate_run(sim, q_obs, outlet_gis_id=1,
                                     outlet_policy="auto", return_diagnostics=True)
    return {"nse": metrics.get("nse", -999), "kge": metrics.get("kge", -999),
            "outlet": diag.get("selected_outlet_gis_id")}

def classify(tio: Path, nse: float, kge: float) -> str:
    from swatplus_builder.full_mode.water_balance_gate import check_water_balance
    result = check_water_balance(tio, nse=nse, kge=kge)
    tiers = result["allowed_tiers"]
    return "research_grade" if "research_grade" in tiers else \
           "diagnostic" if "diagnostic" in tiers else "exploratory"

def calibrate_cn2(tio: Path, obs_path: Path) -> dict:
    """Grid-search CN2 offsets, return best metrics."""
    best = {"nse": -999, "kge": -999, "offset": 0, "outlet": None}
    for offset in range(-30, 40, 5):
        work = Path(tempfile.mkdtemp(prefix="cal_cn2_"))
        shutil.copytree(tio, work, dirs_exist_ok=True)
        patch_cn2(work, offset)
        for stale in work.glob("simulation.out"): stale.unlink()
        if not run_engine(work):
            shutil.rmtree(work, ignore_errors=True)
            continue
        m = evaluate(work, obs_path)
        if m["kge"] > best["kge"]:
            best = {**m, "offset": offset}
        shutil.rmtree(work, ignore_errors=True)
    return best

# ── Main ────────────────────────────────────────────────────────────────

def main():
    root = Path("multibasin_test/bench_full")
    root.mkdir(parents=True, exist_ok=True)
    results = []

    print(f"FULL-MODE 10-BASIN RESEARCH-GRADE BENCHMARK")
    print(f"Engine: {SWAT_EXE}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*80}")

    for i, gauge in enumerate(BASINS):
        t0 = time.time()
        out_dir = root / gauge
        print(f"\n[{i+1}/{len(BASINS)}] {gauge}")

        # 1. Build
        tio = out_dir / "project" / "Scenarios" / "Default" / "TxtInOut"
        obs = out_dir / "outputs" / "obs_q.csv"
        if not tio.is_dir():
            print(f"   Building...")
            if not build_basin(gauge, out_dir):
                results.append({"gauge": gauge, "status": "BUILD_FAILED"})
                continue
        else:
            print(f"   Using existing build")

        # 2. Fix + Warmup (only if not already applied)
        time_sim = tio / "time.sim"
        need_warmup = True
        if time_sim.exists():
            ts_lines = time_sim.read_text().split("\n")
            if len(ts_lines) >= 3 and "2010" in ts_lines[2] or "2007" in ts_lines[2] or "2008" in ts_lines[2]:
                need_warmup = False
        if need_warmup:
            fix_and_warmup(tio, warmup_years=3)

        # 3. Baseline
        base = evaluate(tio, obs)
        print(f"   Baseline: NSE={base['nse']:.3f} KGE={base['kge']:.3f}")

        # 4. Calibrate
        cal = calibrate_cn2(tio, obs)
        print(f"   Cal: CN2{cal['offset']:+d} → NSE={cal['nse']:.3f} KGE={cal['kge']:.3f}")

        # 5. Classify
        tier = classify(tio, cal["nse"], cal["kge"])
        elapsed = time.time() - t0

        result = {
            "gauge": gauge, "status": "OK",
            "cn2_offset": cal["offset"], "outlet": cal.get("outlet"),
            "baseline_nse": base["nse"], "baseline_kge": base["kge"],
            "best_nse": cal["nse"], "best_kge": cal["kge"],
            "tier": tier, "elapsed_s": elapsed,
        }
        results.append(result)
        print(f"   → {tier} ({elapsed:.0f}s)")

    # Summary
    print(f"\n{'='*80}")
    print(f"{'Gauge':>12} {'CN2':>5} {'BaseKGE':>8} {'BestKGE':>8} {'Tier':>18} {'Time'}")
    print("-" * 80)
    for r in results:
        if r["status"] == "OK":
            print(f"{r['gauge']:>12} {r['cn2_offset']:>+5d} {r['baseline_kge']:>8.3f} {r['best_kge']:>8.3f} {r['tier']:>18} {r['elapsed_s']:>5.0f}s")
        else:
            print(f"{r['gauge']:>12} {'-':>5} {'-':>8} {'-':>8} {r['status']:>18}")

    research = sum(1 for r in results if r.get("tier") == "research_grade")
    print(f"\nResearch-grade: {research}/{len(BASINS)}")
    
    out_path = root / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Saved: {out_path}")

if __name__ == "__main__":
    main()
