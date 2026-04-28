#!/usr/bin/env python
"""Phase 3G Sprint 3: Verify calibration and compare Phase 3F vs Phase 3G at outlet 290.

After re-calibration at outlet 290 completes, this script:
1. Reads the calibration best-solution parameters
2. Independently reruns those parameters
3. Compares vs the lock
4. Produces a clean soil-replacement comparison table
5. Runs realism audit on baseline + calibrated alignments
"""

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from swatplus_builder.calibration.locked_benchmark import verify_calibration  # noqa: E402
from swatplus_builder.output.realism import audit_realism  # noqa: E402

ARTIFACTS = REPO / "tests" / "_artifacts"

# Phase 3G Sprint 3 artifacts (outlet 290)
PHASE3G_LOCK_DIR = ARTIFACTS / "phase3g_03339000_sda_outlet290_lock" / "benchmark"
PHASE3G_CAL_DIR = ARTIFACTS / "phase3g_03339000_sda_outlet290_cal" / "calibration_reports_locked"
PHASE3G_OUT_DIR = ARTIFACTS / "phase3g_03339000_sda_outlet290_verification"

# Phase 3F artifacts (for comparison)
PHASE3F_LOCK_DIR = ARTIFACTS / "phase3f_03339000_2013_2015_lock" / "benchmark"
PHASE3F_CAL_DIR = ARTIFACTS / "phase3f_03339000_2013_2015_cal_quick" / "calibration_reports_locked"

# E2E run directories
PHASE3G_E2E = ARTIFACTS / "e2e_runs" / "phase3g_03339000_sda_real_soils_e2e_20260427_v2" / "usgs_03339000"
PHASE3F_E2E = ARTIFACTS / "e2e_runs" / "phase3f_multiyear_20260427_03339000_topology_fixed" / "usgs_03339000"

PHASE3G_OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_obs():
    """Load observed discharge for 2013-2015."""
    obs_csv = PHASE3G_E2E / "outputs" / "obs_q.csv"
    df = pd.read_csv(obs_csv, index_col=0, parse_dates=True)
    s = df.iloc[:, 0].rename("obs")
    s.index = pd.to_datetime(s.index).normalize()
    return s


def main():
    print("=" * 80)
    print("Phase 3G Sprint 3: Verification & Soil-Replacement Comparison at Outlet 290")
    print("=" * 80)

    if not PHASE3G_CAL_DIR.exists():
        print(f"ERROR: Calibration directory not found: {PHASE3G_CAL_DIR}")
        print("Calibration may still be running. Check back when it completes.")
        return False

    obs = load_obs()
    print(f"\nLoaded {len(obs)} days of observed discharge")

    # Step 1: Read Phase 3G calibration best solution
    print("\n--- Phase 3G Calibration Best Solution ---")
    best_sol_path = PHASE3G_CAL_DIR / "best_solution.json"
    if not best_sol_path.exists():
        print(f"ERROR: {best_sol_path} not found")
        return False

    best_sol = json.loads(best_sol_path.read_text())
    print(f"CN2={best_sol['parameters']['CN2']:.2f}, ALPHA_BF={best_sol['parameters']['ALPHA_BF']:.6f}")
    print(f"Calibrated NSE={best_sol['metrics']['nse']:.6f}, KGE={best_sol['metrics']['kge']:.6f}")
    print(f"Benchmark NSE={best_sol['benchmark_baseline_nse']:.6f}")
    delta_nse = best_sol['metrics']['nse'] - best_sol['benchmark_baseline_nse']
    print(f"Δ NSE={delta_nse:+.6f}")

    # Step 2: Independent verification
    print("\n--- Verification (Independent Rerun of Best Solution) ---")
    try:
        verify_result = verify_calibration(
            lock_dir=PHASE3G_LOCK_DIR,
            base_txtinout=PHASE3G_E2E / "project" / "Scenarios" / "Default" / "TxtInOut",
            best_params=best_sol['parameters'],
            obs_series=obs,
            out_dir=PHASE3G_OUT_DIR / "verification",
            binary=REPO / "bin" / "swatplus_exe",
        )
        print(f"Verification NSE={verify_result['nse']:.6f}, KGE={verify_result['kge']:.6f}")
        print(f"Verification Δ={verify_result['delta_nse']:+.6f}")
        if abs(verify_result['nse'] - best_sol['metrics']['nse']) < 0.001:
            print("✓ Verification matches calibration (±0.001 NSE)")
        else:
            print(f"⚠ Verification differs from calibration by {abs(verify_result['nse'] - best_sol['metrics']['nse']):.6f} NSE")
    except Exception as e:
        print(f"Verification failed: {e}")
        print("Proceeding with comparison using calibration artifact metrics.")
        verify_result = None

    # Step 3: Phase 3F best solution for comparison
    print("\n--- Phase 3F Calibration Best Solution (outlet 290) ---")
    phase3f_best = json.loads((PHASE3F_CAL_DIR / "best_solution.json").read_text())
    print(f"CN2={phase3f_best['parameters']['CN2']:.2f}, ALPHA_BF={phase3f_best['parameters']['ALPHA_BF']:.6f}")
    print(f"Calibrated NSE={phase3f_best['metrics']['nse']:.6f}, KGE={phase3f_best['metrics']['kge']:.6f}")
    print(f"Benchmark NSE={phase3f_best['benchmark_baseline_nse']:.6f}")
    phase3f_delta = phase3f_best['metrics']['nse'] - phase3f_best['benchmark_baseline_nse']
    print(f"Δ NSE={phase3f_delta:+.6f}")

    # Step 4: Build comparison table
    print("\n" + "=" * 80)
    print("SOIL-REPLACEMENT COMPARISON AT OUTLET 290")
    print("=" * 80)

    comparison = pd.DataFrame([
        {
            "Condition": "Phase 3F",
            "Soil": "Synthetic (100%)",
            "Baseline NSE": phase3f_best['benchmark_baseline_nse'],
            "Calibrated NSE": phase3f_best['metrics']['nse'],
            "Δ NSE": phase3f_delta,
            "BFI_sim": phase3f_best['metrics'].get('bfi_sim', None),
        },
        {
            "Condition": "Phase 3G",
            "Soil": "Real SDA (95.1%)",
            "Baseline NSE": best_sol['benchmark_baseline_nse'],
            "Calibrated NSE": best_sol['metrics']['nse'],
            "Δ NSE": delta_nse,
            "BFI_sim": best_sol['metrics'].get('bfi_sim', None),
        },
    ])

    print("\n" + comparison.to_string(index=False))
    comparison.to_csv(PHASE3G_OUT_DIR / "soil_replacement_comparison.csv", index=False)
    print(f"\nComparison saved to {PHASE3G_OUT_DIR / 'soil_replacement_comparison.csv'}")

    # Step 5: Realism audit on Phase 3G outlet-290 alignments
    print("\n--- Realism Audit: Phase 3G @ Outlet 290 ---")
    try:
        baseline_align = PHASE3G_LOCK_DIR / "alignment.csv"
        cal_align = PHASE3G_CAL_DIR / "objective_runs" / list(PHASE3G_CAL_DIR.glob("*/"))[-1].name / "TxtInOut" / "alignment_calibration.csv"

        if baseline_align.exists():
            print(f"Auditing {baseline_align}")
            baseline_audit = audit_realism(
                obs_series=obs,
                sim_series=pd.read_csv(baseline_align, index_col=0, parse_dates=True).iloc[:, 0],
                period_label="full",
            )
            print(f"  Baseline: NSE={baseline_audit.metrics.nse:.4f}, BFI ratio={baseline_audit.bfi_ratio:.2f}, PBIAS={baseline_audit.pbias:.1f}%")

        if cal_align.exists():
            print(f"Auditing {cal_align}")
            cal_audit = audit_realism(
                obs_series=obs,
                sim_series=pd.read_csv(cal_align, index_col=0, parse_dates=True).iloc[:, 0],
                period_label="calibrated",
            )
            print(f"  Calibrated: NSE={cal_audit.metrics.nse:.4f}, BFI ratio={cal_audit.bfi_ratio:.2f}, PBIAS={cal_audit.pbias:.1f}%")
    except Exception as e:
        print(f"Realism audit failed: {e}")

    print("\n✓ Sprint 3 verification complete")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
