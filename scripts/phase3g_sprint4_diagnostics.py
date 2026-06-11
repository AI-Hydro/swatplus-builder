#!/usr/bin/env python
"""Phase 3G Sprint 4: Structural diagnostics for 03339000.

Tests three hypotheses for the Phase 3G baseline NSE collapse at outlet 290:
  1. Calibration overfitting (cal NSE >> val NSE on held-out year)
  2. Volume bias / PBIAS (systematic over/under-simulation)
  3. Year-specific anomaly (one bad year driving collapse vs. uniform degradation)

Uses only existing artifacts — no new model runs needed.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from swatplus_builder.output.realism import split_cal_val  # noqa: E402

ARTIFACTS = REPO / "tests" / "_artifacts"
OUT_DIR = ARTIFACTS / "phase3g_sprint4_diagnostics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Lock baselines (outlet 290, both soils)
PHASE3F_LOCK = ARTIFACTS / "phase3f_03339000_2013_2015_lock" / "benchmark"
PHASE3G_LOCK = ARTIFACTS / "phase3g_03339000_sda_outlet290_lock" / "benchmark"

# Calibration objective_runs (to locate best-solution alignment)
PHASE3F_CAL_RUNS = ARTIFACTS / "phase3f_03339000_2013_2015_cal_quick" / "calibration_reports_locked" / "objective_runs"
PHASE3G_CAL_RUNS = ARTIFACTS / "phase3g_03339000_sda_outlet290_cal" / "calibration_reports_locked" / "objective_runs"
PHASE3F_BEST = ARTIFACTS / "phase3f_03339000_2013_2015_cal_quick" / "calibration_reports_locked" / "best_solution.json"
PHASE3G_BEST = ARTIFACTS / "phase3g_03339000_sda_outlet290_cal" / "calibration_reports_locked" / "best_solution.json"

SPLIT_YEAR = 2015  # cal=2013-2014, val=2015


def _nse(obs: np.ndarray, sim: np.ndarray) -> float:
    denom = np.sum((obs - obs.mean()) ** 2)
    if denom == 0:
        return float("nan")
    return float(1.0 - np.sum((obs - sim) ** 2) / denom)


def _kge(obs: np.ndarray, sim: np.ndarray) -> float:
    if obs.std() == 0 or sim.std() == 0 or len(obs) < 2:
        return float("nan")
    r = float(np.corrcoef(obs, sim)[0, 1])
    alpha = float(sim.std() / obs.std())
    beta = float(sim.mean() / obs.mean()) if obs.mean() != 0 else float("nan")
    if np.isnan(beta):
        return float("nan")
    return float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def _pbias(obs: np.ndarray, sim: np.ndarray) -> float:
    obs_sum = float(obs.sum())
    if obs_sum == 0:
        return float("nan")
    return float(100.0 * (sim.sum() - obs_sum) / obs_sum)


def load_alignment(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).normalize()
    return df.dropna(subset=["obs", "sim"])


def metrics_for(df: pd.DataFrame) -> dict:
    obs = df["obs"].values
    sim = df["sim"].values
    return {
        "n": len(df),
        "nse": _nse(obs, sim),
        "kge": _kge(obs, sim),
        "pbias_pct": _pbias(obs, sim),
    }


def annual_decomposition(df: pd.DataFrame, label: str) -> list[dict]:
    rows = []
    for year in sorted(df.index.year.unique()):
        sub = df[df.index.year == year]
        m = metrics_for(sub)
        rows.append({"label": label, "year": year, **m})
    return rows


def find_best_alignment(cal_runs_dir: Path, best_json: Path) -> pd.DataFrame | None:
    best = json.loads(best_json.read_text())
    best_params = best["parameters"]

    for hash_dir in cal_runs_dir.iterdir():
        trace_path = hash_dir / "objective_trace.json"
        if not trace_path.exists():
            continue
        trace = json.loads(trace_path.read_text())
        tp = trace.get("params", {})
        if all(abs(tp.get(k, 999) - v) < 0.001 for k, v in best_params.items()):
            align_path = hash_dir / "TxtInOut" / "alignment_calibration.csv"
            if align_path.exists():
                df = load_alignment(align_path)
                if df["sim"].abs().sum() > 0:
                    return df
    return None


def cal_val_split_metrics(df: pd.DataFrame, label: str) -> list[dict]:
    cal_df, val_df, split = split_cal_val(df, split_year=SPLIT_YEAR)
    rows = []
    for period, sub in [("full", df), ("cal_2013-2014", cal_df), ("val_2015", val_df)]:
        if sub.empty:
            continue
        m = metrics_for(sub)
        rows.append({"label": label, "period": period, **m})
    return rows


def main():
    print("=" * 80)
    print("Phase 3G Sprint 4: Structural Diagnostics at Outlet 290")
    print("=" * 80)

    # --- Load baselines ---
    print("\nLoading baseline alignments...")
    phase3f_base = load_alignment(PHASE3F_LOCK / "alignment.csv")
    phase3g_base = load_alignment(PHASE3G_LOCK / "alignment.csv")
    print(f"  Phase 3F baseline: {len(phase3f_base)} days")
    print(f"  Phase 3G baseline: {len(phase3g_base)} days")

    # --- Annual decomposition ---
    print("\n--- Annual NSE Decomposition (Hypothesis 3: year-specific anomaly?) ---")
    annual_rows = []
    annual_rows += annual_decomposition(phase3f_base, "3F_synthetic_baseline")
    annual_rows += annual_decomposition(phase3g_base, "3G_real_SDA_baseline")

    # Find calibrated alignments
    print("\nLocating best-solution calibrated alignments...")
    phase3f_cal = find_best_alignment(PHASE3F_CAL_RUNS, PHASE3F_BEST)
    phase3g_cal = find_best_alignment(PHASE3G_CAL_RUNS, PHASE3G_BEST)

    if phase3f_cal is not None:
        print(f"  Phase 3F calibrated: {len(phase3f_cal)} days (found)")
        annual_rows += annual_decomposition(phase3f_cal, "3F_synthetic_calibrated")
    else:
        print("  Phase 3F calibrated: NOT FOUND in objective_runs")

    if phase3g_cal is not None:
        print(f"  Phase 3G calibrated: {len(phase3g_cal)} days (found)")
        annual_rows += annual_decomposition(phase3g_cal, "3G_real_SDA_calibrated")
    else:
        print("  Phase 3G calibrated: NOT FOUND in objective_runs")

    annual_df = pd.DataFrame(annual_rows)
    print("\n" + annual_df.to_string(index=False))
    annual_df.to_csv(OUT_DIR / "annual_decomposition.csv", index=False)

    # --- Cal/val split ---
    print("\n--- Cal/Val Split (Hypothesis 1: overfitting? split_year=2015) ---")
    cal_val_rows = []
    cal_val_rows += cal_val_split_metrics(phase3f_base, "3F_synthetic_baseline")
    cal_val_rows += cal_val_split_metrics(phase3g_base, "3G_real_SDA_baseline")
    if phase3f_cal is not None:
        cal_val_rows += cal_val_split_metrics(phase3f_cal, "3F_synthetic_calibrated")
    if phase3g_cal is not None:
        cal_val_rows += cal_val_split_metrics(phase3g_cal, "3G_real_SDA_calibrated")

    cal_val_df = pd.DataFrame(cal_val_rows)
    print("\n" + cal_val_df.to_string(index=False))
    cal_val_df.to_csv(OUT_DIR / "cal_val_split.csv", index=False)

    # --- PBIAS full-period summary (Hypothesis 2: volume bias?) ---
    print("\n--- PBIAS Summary (Hypothesis 2: volume bias?) ---")
    pbias_rows = []
    for label, df in [
        ("3F_synthetic_baseline", phase3f_base),
        ("3G_real_SDA_baseline", phase3g_base),
    ]:
        obs, sim = df["obs"].values, df["sim"].values
        pbias_rows.append({
            "label": label,
            "pbias_pct": _pbias(obs, sim),
            "obs_mean_m3s": float(obs.mean()),
            "sim_mean_m3s": float(sim.mean()),
        })
    if phase3f_cal is not None:
        obs, sim = phase3f_cal["obs"].values, phase3f_cal["sim"].values
        pbias_rows.append({
            "label": "3F_synthetic_calibrated",
            "pbias_pct": _pbias(obs, sim),
            "obs_mean_m3s": float(obs.mean()),
            "sim_mean_m3s": float(sim.mean()),
        })
    if phase3g_cal is not None:
        obs, sim = phase3g_cal["obs"].values, phase3g_cal["sim"].values
        pbias_rows.append({
            "label": "3G_real_SDA_calibrated",
            "pbias_pct": _pbias(obs, sim),
            "obs_mean_m3s": float(obs.mean()),
            "sim_mean_m3s": float(sim.mean()),
        })
    pbias_df = pd.DataFrame(pbias_rows)
    print("\n" + pbias_df.to_string(index=False))

    # --- Write diagnostic report ---
    _write_report(annual_df, cal_val_df, pbias_df, phase3f_cal, phase3g_cal)

    print(f"\n✓ Sprint 4 diagnostics complete. Outputs in {OUT_DIR}")
    return True


def _write_report(annual_df, cal_val_df, pbias_df, phase3f_cal, phase3g_cal):
    lines = [
        "# Phase 3G Sprint 4: Structural Diagnostics Report",
        "",
        "**Date:** 2026-04-28  ",
        "**Outlet:** GIS ID 290 (main-stem, 862 ha)  ",
        f"**Cal/Val split year:** {SPLIT_YEAR} (cal=2013-2014, val=2015)  ",
        "",
        "## Annual NSE Decomposition",
        "",
        "Tests **Hypothesis 3**: Is skill collapse driven by one anomalous year or uniform?",
        "",
        annual_df.to_markdown(index=False),
        "",
        "### Interpretation",
    ]

    # Auto-interpret annual decomposition
    phase3g_annual = annual_df[annual_df["label"] == "3G_real_SDA_baseline"]
    if not phase3g_annual.empty:
        min_nse = phase3g_annual["nse"].min()
        max_nse = phase3g_annual["nse"].max()
        spread = max_nse - min_nse
        if spread < 0.15:
            lines.append(f"- Phase 3G NSE range across years: {min_nse:.3f}–{max_nse:.3f} (spread={spread:.3f}). **UNIFORM degradation** — not anomalous year.")
            lines.append("- Hypothesis 3 **rejected**: all years are similarly bad. Structural issue is systematic.")
        else:
            worst_year = phase3g_annual.loc[phase3g_annual["nse"].idxmin(), "year"]
            lines.append(f"- Phase 3G NSE range: {min_nse:.3f}–{max_nse:.3f} (spread={spread:.3f}). **One year dominates** (worst: {worst_year}).")
            lines.append(f"- Hypothesis 3 **supported**: year {worst_year} anomaly may explain collapse. Investigate precip/routing for that year.")

    lines += [
        "",
        "## Cal/Val Split (Overfitting Test)",
        "",
        "Tests **Hypothesis 1**: Does calibration overfit to 2013-2014?",
        "",
        cal_val_df.to_markdown(index=False),
        "",
        "### Interpretation",
    ]

    # Auto-interpret cal/val
    for label in ["3F_synthetic_calibrated", "3G_real_SDA_calibrated"]:
        sub = cal_val_df[cal_val_df["label"] == label]
        if sub.empty:
            lines.append(f"- {label}: calibrated alignment not found — skipped.")
            continue
        cal_row = sub[sub["period"] == "cal_2013-2014"]
        val_row = sub[sub["period"] == "val_2015"]
        if cal_row.empty or val_row.empty:
            continue
        cal_nse = float(cal_row["nse"].iloc[0])
        val_nse = float(val_row["nse"].iloc[0])
        drop = cal_nse - val_nse
        tag = "3G" if "3G" in label else "3F"
        if drop > 0.15:
            lines.append(f"- **{tag}**: cal NSE={cal_nse:.3f}, val NSE={val_nse:.3f} (drop={drop:.3f}). **OVERFITTING** detected — calibration exploits 2013-2014 patterns not present in 2015.")
        elif drop > 0.05:
            lines.append(f"- **{tag}**: cal NSE={cal_nse:.3f}, val NSE={val_nse:.3f} (drop={drop:.3f}). Mild generalization gap. Skill is partially transferable.")
        else:
            lines.append(f"- **{tag}**: cal NSE={cal_nse:.3f}, val NSE={val_nse:.3f} (drop={drop:.3f}). **GENERALIZES** — calibrated params are transferable to 2015. Ceiling is real.")

    lines += [
        "",
        "## PBIAS and Volume Balance",
        "",
        "Tests **Hypothesis 2**: Is there a systematic volume bias?",
        "",
        pbias_df.to_markdown(index=False),
        "",
        "### Interpretation",
    ]

    # Auto-interpret PBIAS
    for _, row in pbias_df.iterrows():
        pb = row["pbias_pct"]
        label = row["label"]
        if abs(pb) > 25:
            lines.append(f"- **{label}**: PBIAS={pb:+.1f}% — **severe volume bias**. Simulated volume {'exceeds' if pb > 0 else 'underestimates'} observed by {abs(pb):.1f}%.")
        elif abs(pb) > 10:
            lines.append(f"- **{label}**: PBIAS={pb:+.1f}% — moderate volume bias.")
        else:
            lines.append(f"- **{label}**: PBIAS={pb:+.1f}% — volume balance acceptable (±10%).")

    # Check if Phase 3G PBIAS >> Phase 3F PBIAS
    pb_3f_base = pbias_df[pbias_df["label"] == "3F_synthetic_baseline"]["pbias_pct"].iloc[0] if not pbias_df[pbias_df["label"] == "3F_synthetic_baseline"].empty else None
    pb_3g_base = pbias_df[pbias_df["label"] == "3G_real_SDA_baseline"]["pbias_pct"].iloc[0] if not pbias_df[pbias_df["label"] == "3G_real_SDA_baseline"].empty else None
    if pb_3f_base is not None and pb_3g_base is not None:
        diff = abs(pb_3g_base) - abs(pb_3f_base)
        if diff > 15:
            lines.append(f"- Phase 3G PBIAS is {diff:.1f}% worse than Phase 3F in absolute terms. Real soils are generating systematic volume error — likely excess baseflow routing (documented: BFI_sim 0.661 vs BFI_obs 0.537).")
        else:
            lines.append(f"- PBIAS difference between soils is small ({diff:+.1f}%). Volume bias is not the primary discriminator — timing/phase error is more likely the driver.")

    lines += [
        "",
        "## Summary",
        "",
        "| Hypothesis | Status |",
        "|---|---|",
    ]

    # Summary auto-build
    phase3g_annual_nse = annual_df[annual_df["label"] == "3G_real_SDA_baseline"]["nse"] if not annual_df.empty else pd.Series(dtype=float)
    h3_status = "REJECTED (uniform)" if (not phase3g_annual_nse.empty and phase3g_annual_nse.max() - phase3g_annual_nse.min() < 0.15) else "SUPPORTED (anomalous year)"
    lines.append(f"| H3: Year-specific anomaly | {h3_status} |")

    # H1 (overfitting)
    phase3g_cv = cal_val_df[cal_val_df["label"] == "3G_real_SDA_calibrated"]
    if not phase3g_cv.empty:
        c = phase3g_cv[phase3g_cv["period"] == "cal_2013-2014"]["nse"]
        v = phase3g_cv[phase3g_cv["period"] == "val_2015"]["nse"]
        if not c.empty and not v.empty:
            drop = float(c.iloc[0]) - float(v.iloc[0])
            h1_status = f"OVERFITTING (drop={drop:.3f})" if drop > 0.15 else f"REJECTED (drop={drop:.3f} — generalizes)"
        else:
            h1_status = "INCOMPLETE (alignment not found)"
    else:
        h1_status = "INCOMPLETE (alignment not found)"
    lines.append(f"| H1: Calibration overfitting | {h1_status} |")

    if pb_3g_base is not None:
        h2_status = f"SUPPORTED (PBIAS={pb_3g_base:+.1f}%)" if abs(pb_3g_base) > 25 else f"WEAK (PBIAS={pb_3g_base:+.1f}%)"
    else:
        h2_status = "INCOMPLETE"
    lines.append(f"| H2: Volume bias / PBIAS | {h2_status} |")

    lines += ["", "---", "Generated by `scripts/phase3g_sprint4_diagnostics.py`"]

    (OUT_DIR / "diagnostic_report.md").write_text("\n".join(lines))
    print(f"\n  Report written to {OUT_DIR / 'diagnostic_report.md'}")


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
