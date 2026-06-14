#!/usr/bin/env python
"""Phase 3G Sprint 2: outlet/topology comparability for 03339000.

Evaluates four channel_sd_day.txt files (two E2E baselines and two calibrated
best-solution runs) at outlets 255 AND 290 using authoritative evaluate_run
with strict policy.

Produces:
    tests/_artifacts/phase3g_03339000_outlet_comparability/outlet_comparison.csv
    tests/_artifacts/phase3g_03339000_outlet_comparability/outlet_comparison.md
"""

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from swatplus_builder.output.eval import evaluate_run  # noqa: E402

ARTIFACTS = REPO / "tests" / "_artifacts"
OUT_DIR = ARTIFACTS / "phase3g_03339000_outlet_comparability"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Observed discharge (shared for both E2E run trees; same USGS 03339000 data)
# ---------------------------------------------------------------------------
OBS_CSV = (
    ARTIFACTS
    / "e2e_runs"
    / "phase3f_multiyear_20260427_03339000_topology_fixed"
    / "usgs_03339000"
    / "outputs"
    / "obs_q.csv"
)


def load_obs() -> pd.Series:
    df = pd.read_csv(OBS_CSV, index_col=0, parse_dates=True)
    s = df.iloc[:, 0].rename("obs")
    s.index = pd.to_datetime(s.index).normalize()
    return s


# ---------------------------------------------------------------------------
# Run definitions
# ---------------------------------------------------------------------------
RUNS = {
    "phase3f_baseline": {
        "label": "Phase 3F Baseline (synthetic soils)",
        "soil_mode": "synthetic",
        "pct_fallback": 1.0,
        "native_outlet": 290,
        "channel_sd_day": (
            ARTIFACTS
            / "e2e_runs"
            / "phase3f_multiyear_20260427_03339000_topology_fixed"
            / "usgs_03339000"
            / "project"
            / "Scenarios"
            / "Default"
            / "TxtInOut"
            / "channel_sd_day.txt"
        ),
        "type": "baseline",
        "params": {"CN2": None, "ALPHA_BF": None},
    },
    "phase3g_baseline": {
        "label": "Phase 3G Baseline (real SDA soils, 95.1% real)",
        "soil_mode": "fallback",
        "pct_fallback": 0.049,
        "native_outlet": 255,
        "channel_sd_day": (
            ARTIFACTS
            / "e2e_runs"
            / "phase3g_03339000_sda_real_soils_e2e_20260427_v2"
            / "usgs_03339000"
            / "project"
            / "Scenarios"
            / "Default"
            / "TxtInOut"
            / "channel_sd_day.txt"
        ),
        "type": "baseline",
        "params": {"CN2": None, "ALPHA_BF": None},
    },
    "phase3f_calibrated": {
        "label": "Phase 3F Calibrated best (CN2=52.33, ALPHA_BF=0.2232)",
        "soil_mode": "synthetic",
        "pct_fallback": 1.0,
        "native_outlet": 290,
        "channel_sd_day": (
            ARTIFACTS
            / "phase3f_03339000_2013_2015_cal_quick"
            / "calibration_reports_locked"
            / "objective_runs"
            / "ef2a789ef0d3be431bbdbaf88063e3d489cbf325909084a0c590b9a1a72e2fea"
            / "TxtInOut"
            / "channel_sd_day.txt"
        ),
        "type": "calibrated",
        "params": {"CN2": 52.33, "ALPHA_BF": 0.2232},
    },
    "phase3g_calibrated": {
        "label": "Phase 3G Calibrated best (CN2=75.0, ALPHA_BF=1.0)",
        "soil_mode": "fallback",
        "pct_fallback": 0.049,
        "native_outlet": 255,
        "channel_sd_day": (
            ARTIFACTS
            / "phase3g_03339000_sda_cal_real"
            / "calibration_reports_locked"
            / "objective_runs"
            / "12e51ab1443dfe5c78ae332ae4e9cfefc037050c1e7ad98f8c076d691b4abbd5"
            / "TxtInOut"
            / "channel_sd_day.txt"
        ),
        "type": "calibrated",
        "params": {"CN2": 75.0, "ALPHA_BF": 1.0},
    },
}

OUTLETS = [255, 290]


def evaluate_one(run_key: str, run_def: dict, outlet_id: int, obs: pd.Series) -> dict:
    channel_path = run_def["channel_sd_day"]
    native = run_def["native_outlet"]

    if not channel_path.exists():
        return {
            "run": run_key,
            "outlet_gis_id": outlet_id,
            "is_native_outlet": outlet_id == native,
            "available": False,
            "nse": None,
            "kge": None,
            "bfi_obs": None,
            "bfi_sim": None,
            "aligned_days": None,
            "note": f"MISSING: {channel_path}",
        }

    out_align = (
        OUT_DIR
        / f"alignment_{run_key}_outlet{outlet_id}.csv"
    )

    try:
        df, metrics, diag = evaluate_run(
            sim_channel_path=channel_path,
            obs_series=obs.copy(),
            outlet_gis_id=outlet_id,
            out_alignment_csv=out_align,
            outlet_policy="strict",
            return_diagnostics=True,
        )
        note = ""
        if diag.get("outlet_autodetected"):
            note = f"WARN: outlet switched to {diag.get('selected_outlet_gis_id')}"
        is_terminal = diag.get("requested_outlet_is_terminal")
        if is_terminal is False:
            note = "non-terminal in this topology"
        return {
            "run": run_key,
            "outlet_gis_id": outlet_id,
            "is_native_outlet": outlet_id == native,
            "available": True,
            "nse": round(metrics.get("nse", float("nan")), 6),
            "kge": round(metrics.get("kge", float("nan")), 6),
            "bfi_obs": round(metrics.get("bfi_obs", float("nan")), 4),
            "bfi_sim": round(metrics.get("bfi_sim", float("nan")), 4),
            "aligned_days": len(df),
            "requested_outlet_is_terminal": is_terminal,
            "selected_outlet_gis_id": diag.get("selected_outlet_gis_id"),
            "note": note,
        }
    except Exception as e:
        return {
            "run": run_key,
            "outlet_gis_id": outlet_id,
            "is_native_outlet": outlet_id == native,
            "available": False,
            "nse": None,
            "kge": None,
            "bfi_obs": None,
            "bfi_sim": None,
            "aligned_days": None,
            "note": f"ERROR: {e}",
        }


def main():
    obs = load_obs()
    print(f"Loaded {len(obs)} observed days for USGS 03339000")

    rows = []
    for run_key, run_def in RUNS.items():
        for outlet_id in OUTLETS:
            print(f"  evaluating {run_key} @ outlet {outlet_id} (strict) ...")
            result = evaluate_one(run_key, run_def, outlet_id, obs)
            result.update({
                "run_label": run_def["label"],
                "soil_mode": run_def["soil_mode"],
                "pct_fallback": run_def["pct_fallback"],
                "run_type": run_def["type"],
                "native_outlet": run_def["native_outlet"],
                "cn2": run_def["params"]["CN2"],
                "alpha_bf": run_def["params"]["ALPHA_BF"],
            })
            rows.append(result)
            status = f"NSE={result['nse']}" if result["nse"] is not None else result["note"]
            print(f"    → {status}")

    df_out = pd.DataFrame(rows)

    # Reorder columns for readability
    col_order = [
        "run", "run_type", "soil_mode", "pct_fallback",
        "native_outlet", "outlet_gis_id", "is_native_outlet",
        "cn2", "alpha_bf",
        "nse", "kge", "bfi_obs", "bfi_sim",
        "aligned_days", "requested_outlet_is_terminal",
        "selected_outlet_gis_id", "note",
    ]
    col_order = [c for c in col_order if c in df_out.columns]
    df_out = df_out[col_order]

    csv_path = OUT_DIR / "outlet_comparison.csv"
    df_out.to_csv(csv_path, index=False)
    print(f"\nWrote {csv_path}")

    # Write provenance JSON
    provenance = {
        "purpose": "Phase 3G Sprint 2: outlet/topology comparability for 03339000",
        "runs_evaluated": {k: str(v["channel_sd_day"]) for k, v in RUNS.items()},
        "outlets_evaluated": OUTLETS,
        "outlet_policy": "strict",
        "obs_source": str(OBS_CSV),
        "note": (
            "All metrics computed via authoritative evaluate_run with outlet_policy='strict'. "
            "Cross-outlet comparisons (is_native_outlet=False) reveal the outlet-selection effect "
            "independently of the soil-replacement effect."
        ),
    }
    prov_path = OUT_DIR / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2))
    print(f"Wrote {prov_path}")

    # Write Markdown report
    _write_markdown(df_out, OUT_DIR / "outlet_comparison.md")
    print(f"Wrote {OUT_DIR / 'outlet_comparison.md'}")

    return df_out


def _write_markdown(df: pd.DataFrame, out_path: Path) -> None:
    lines = [
        "# Phase 3G Sprint 2: Outlet Comparability Report — usgs_03339000",
        "",
        "**Generated:** 2026-04-27  ",
        "**Basin:** USGS 03339000 (Wabash at Terre Haute, IN)  ",
        "**Period:** 2013-01-01 to 2015-12-31 (1095 days)  ",
        "**Evaluation:** `evaluate_run` with `outlet_policy='strict'` at outlets 255 and 290  ",
        "",
        "---",
        "",
        "## Background",
        "",
        "Phase 3F used **outlet 290** (auto-detected as best-NSE terminal channel) with synthetic soils.",
        "Phase 3G used **outlet 255** (auto-detected as best-NSE terminal channel) with real SDA soils (95.1% real SSURGO).",
        "Both outlets are confirmed terminal in both topologies.",
        "Direct comparison of Phase 3F vs Phase 3G metrics is confounded by the simultaneous change of (a) soil source and (b) outlet selection.",
        "This report disentangles those two effects by evaluating each simulation at **both** outlets.",
        "",
        "---",
        "",
        "## Raw Metrics Table",
        "",
        "| Run | Type | Soil mode | Native outlet | Eval outlet | Native? | CN2 | ALPHA_BF | NSE | KGE | BFI_obs | BFI_sim | Days | Terminal? | Note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]

    def _fmt(v, fmt=".4f"):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "—"
        return format(v, fmt)

    for _, row in df.iterrows():
        native_marker = "✓" if row.get("is_native_outlet") else "✗"
        terminal_marker = (
            "yes" if row.get("requested_outlet_is_terminal") is True
            else ("no" if row.get("requested_outlet_is_terminal") is False else "?")
        )
        cn2 = _fmt(row.get("cn2"), ".1f") if row.get("cn2") is not None else "default"
        alpha = _fmt(row.get("alpha_bf"), ".4f") if row.get("alpha_bf") is not None else "default"
        note = row.get("note", "")
        lines.append(
            f"| {row['run']} | {row['run_type']} | {row['soil_mode']} | {row['native_outlet']} "
            f"| {row['outlet_gis_id']} | {native_marker} | {cn2} | {alpha} "
            f"| {_fmt(row.get('nse'))} | {_fmt(row.get('kge'))} "
            f"| {_fmt(row.get('bfi_obs'))} | {_fmt(row.get('bfi_sim'))} "
            f"| {row.get('aligned_days', '—')} | {terminal_marker} | {note} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Analysis: Decomposing Outlet-Selection vs Soil-Replacement Effects",
        "",
        "### Outlet-selection effect (same simulation, different outlet)",
        "",
        "Compare rows with the same run but different `outlet_gis_id`.",
        "Any NSE difference here is caused purely by **outlet selection**, not by soil changes.",
        "",
    ]

    for run_key in ["phase3f_baseline", "phase3f_calibrated", "phase3g_baseline", "phase3g_calibrated"]:
        sub = df[df["run"] == run_key]
        if len(sub) < 2:
            continue
        r255 = sub[sub["outlet_gis_id"] == 255].iloc[0] if len(sub[sub["outlet_gis_id"] == 255]) > 0 else None
        r290 = sub[sub["outlet_gis_id"] == 290].iloc[0] if len(sub[sub["outlet_gis_id"] == 290]) > 0 else None
        if r255 is None or r290 is None:
            continue
        nse255 = r255.get("nse")
        nse290 = r290.get("nse")
        if nse255 is None or nse290 is None:
            continue
        delta = (nse255 - nse290) if (isinstance(nse255, float) and isinstance(nse290, float)) else None
        delta_str = f"{delta:+.4f}" if delta is not None else "—"
        lines.append(
            f"- **{run_key}**: NSE@255={_fmt(nse255)} vs NSE@290={_fmt(nse290)} → Δ(255−290)={delta_str}"
        )

    lines += [
        "",
        "### Soil-replacement effect (same outlet, different soil source)",
        "",
        "Compare Phase 3F vs Phase 3G rows at the **same** outlet.",
        "Any NSE difference here is caused purely by **soil replacement**, holding outlet constant.",
        "",
    ]

    for outlet_id in [255, 290]:
        sub_f_base = df[(df["run"] == "phase3f_baseline") & (df["outlet_gis_id"] == outlet_id)]
        sub_g_base = df[(df["run"] == "phase3g_baseline") & (df["outlet_gis_id"] == outlet_id)]
        sub_f_cal = df[(df["run"] == "phase3f_calibrated") & (df["outlet_gis_id"] == outlet_id)]
        sub_g_cal = df[(df["run"] == "phase3g_calibrated") & (df["outlet_gis_id"] == outlet_id)]

        lines.append(f"**Outlet {outlet_id}:**")
        for label, sub_f, sub_g in [("baseline", sub_f_base, sub_g_base), ("calibrated", sub_f_cal, sub_g_cal)]:
            if sub_f.empty or sub_g.empty:
                continue
            nse_f = sub_f.iloc[0].get("nse")
            nse_g = sub_g.iloc[0].get("nse")
            if nse_f is None or nse_g is None:
                continue
            delta = (nse_g - nse_f) if (isinstance(nse_f, float) and isinstance(nse_g, float)) else None
            delta_str = f"{delta:+.4f}" if delta is not None else "—"
            lines.append(
                f"- {label}: Phase3F NSE={_fmt(nse_f)}, Phase3G NSE={_fmt(nse_g)} → Δ(3G−3F)={delta_str}"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## Findings and Interpretation",
        "",
        "### 1. Are outlets 255 and 290 both valid terminal outlets?",
        "",
        "Both outlets are confirmed terminal in both topologies (appear in `terminal_outlet_ids` of all four outlet provenance files).",
        "Both were auto-detected by different E2E runs as the best-NSE terminal outlet for their respective simulations.",
        "",
        "### 2. What caused the different outlet selection?",
        "",
        "Phase 3F auto-detected outlet 290 as best-NSE terminal. Phase 3G v2 auto-detected outlet 255 as best-NSE terminal.",
        "The root cause is one of:",
        "- **Soil replacement**: Different hydraulic properties produce different flow distributions across the 1065-subbasin network, so the best-NSE terminal outlet shifts.",
        "- **Topology regeneration**: The Phase 3G v2 E2E rebuilt the routing graph from scratch; minor delineation noise can shift which terminal outlet captures the most correlated flow.",
        "- **Both**: Most likely a combination, with soil replacement being the dominant driver given the large change in hydraulic properties (synthetic vs 95.1% real SSURGO).",
        "",
        "### 3. What is the soil-replacement effect when outlet is held constant?",
        "",
        "See the 'Soil-replacement effect' table above. If NSE(Phase3G) > NSE(Phase3F) at the **same** outlet, the real SDA soils genuinely improved skill.",
        "If NSE is lower, the different soil hydraulics degrade correlation at that specific outlet.",
        "",
        "### 4. Calibration comparability",
        "",
        "Phase 3F calibrated best (NSE=0.4528) was achieved with CN2=52.33, ALPHA_BF=0.2232 at outlet 290 (synthetic soils).",
        "Phase 3G calibrated best (NSE=0.2736) was achieved with CN2=75.0, ALPHA_BF=1.0 at outlet 255 (real SDA soils).",
        "**These calibrated metrics cannot be compared directly** because they target different outlets.",
        "The cross-outlet evaluation rows above provide the apples-to-apples comparison.",
        "",
        "### 5. Actionable conclusion",
        "",
        "Before running new calibration, the key decision is: **which outlet is the correct one?**",
        "The USGS gauge 03339000 is at Terre Haute, IN. The 'correct' outlet is whichever terminal channel in the SWAT+ model drains the watershed area that contributes flow to that gauge.",
        "This is a GIS question (compare channel endpoints to gauge coordinates), not a calibration question.",
        "Until outlet identity is resolved, new calibration at outlet 255 and at outlet 290 will produce non-comparable results.",
        "",
        "---",
        "",
        "## Provenance",
        "",
        "| Item | Value |",
        "| --- | --- |",
        "| Phase 3F E2E channel_sd_day.txt | `phase3f_multiyear_20260427_03339000_topology_fixed/usgs_03339000/project/Scenarios/Default/TxtInOut/channel_sd_day.txt` |",
        "| Phase 3F channel SHA256 | `87cfb2b5c45727401364fd5caa73e4655bd3c37a48d1c0bb6481ddbb524e6756` |",
        "| Phase 3G v2 E2E channel_sd_day.txt | `phase3g_03339000_sda_real_soils_e2e_20260427_v2/usgs_03339000/project/Scenarios/Default/TxtInOut/channel_sd_day.txt` |",
        "| Phase 3G channel SHA256 | `5ea82954058f872810e5d405784192cff6f0b90f717bdab5b32d5ddb9c64a22a` |",
        "| Phase 3F soil_mode | `synthetic` (pct_fallback=1.0) |",
        "| Phase 3G soil_mode | `fallback` (pct_fallback=0.049, i.e., 95.1% real SSURGO) |",
        "| Evaluation method | `evaluate_run(outlet_policy='strict')` |",
        "| Observed discharge | USGS NWIS 03339000, 2013-01-01 to 2015-12-31 |",
        "",
    ]

    out_path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
