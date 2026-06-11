#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from swatplus_builder.workflows.usgs_e2e import RunUSGSWorkflowRequest, run_usgs_workflow

BASINS = [
    "02129000", "01547700", "03349000", "01654000", "01491000", "01013500",
    "03351500", "03353000", "01493500", "12031000", "09504500",
]

AREA_HINTS = {
    "02129000": 17780,
    "01547700": 445,
    "03349000": 920,
    "01654000": 62,
}

def _artifact_metrics(basin: str) -> tuple[float | None, float | None, str | None]:
    """Best-effort load KGE/NSE from existing basin artifacts."""
    candidates = [
        Path(f"multibasin_test/{basin}/reports/metrics.json"),
        Path(f"multibasin_test/{basin}/workflow/reports/metrics.json"),
        Path(f"multibasin_test/{basin}/fresh_build/reports/metrics.json"),
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        k = raw.get("kge")
        n = raw.get("nse")
        if isinstance(k, (int, float)) and isinstance(n, (int, float)):
            return float(k), float(n), str(p)
    return None, None, None


@dataclass
class Row:
    basin: str
    area_km2: float | None
    build: str
    warmup: str
    engine: str
    calibration: str
    kge: float | None
    nse: float | None
    tier: str
    blocker: str
    notes: str


def run_suite(out_root: Path) -> list[Row]:
    rows: list[Row] = []
    for basin in BASINS:
        bdir = out_root / basin
        req = RunUSGSWorkflowRequest(
            usgs_id=basin,
            out_dir=bdir,
            start="2010-01-01",
            end="2019-12-31",
            warmup_years=3,
            claim_tier="diagnostic",
            contract_status="accepted",
            accepted_by="policy",
            calibrate=True,
        )
        res = run_usgs_workflow(req)
        payload = json.loads(Path(res.evidence_summary_path).read_text(encoding="utf-8"))
        values = payload.get("values", {})
        success = bool(payload.get("success"))
        blocker = str(payload.get("blocker_class") or "none")

        build = "pass" if success else "fail"
        warmup = "pass" if int(values.get("warmup_years", 0)) > 0 else "none"
        engine = "pass" if success else "classified_failed"
        cal_attempted = bool(values.get("calibration_attempted"))
        cal_success = bool(values.get("calibration_success"))
        if cal_success:
            calibration = "done"
        elif cal_attempted:
            calibration = "attempted"
        else:
            calibration = "blocked"

        # keep this honest: if orchestration returns no physics metrics, report n/a
        kge = values.get("kge") if isinstance(values.get("kge"), (int, float)) else None
        nse = values.get("nse") if isinstance(values.get("nse"), (int, float)) else None
        metric_source = None
        if kge is None or nse is None:
            kge, nse, metric_source = _artifact_metrics(basin)
        notes = ""
        if basin == "01654000" and nse is not None and float(nse) < 0.0:
            if blocker == "none":
                blocker = "urban_or_structural_limited"
            calibration = "blocked"
            notes = "negative_nse_after_calibration"
        if kge is None or nse is None:
            if blocker == "none":
                blocker = "metrics_unavailable"
            calibration = "blocked"
            notes = "no_physics_metrics_emitted"
        elif metric_source is not None:
            notes = f"metrics_from_artifact:{metric_source}"
        if blocker != "none":
            notes = (notes + "; " if notes else "") + blocker

        tier = "research_grade" if (kge is not None and nse is not None and float(kge) >= 0.40 and float(nse) >= 0.0) else "exploratory"
        if tier != "research_grade" and blocker == "none":
            blocker = "low_skill_nonresearch"
            notes = (notes + "; " if notes else "") + blocker
            if calibration not in {"done", "attempted"}:
                calibration = "blocked"

        rows.append(
            Row(
                basin=basin,
                area_km2=AREA_HINTS.get(basin),
                build=build,
                warmup=warmup,
                engine=engine,
                calibration=calibration,
                kge=kge,
                nse=nse,
                tier=tier,
                blocker=blocker,
                notes=notes or "none",
            )
        )
    return rows


def write_outputs(rows: list[Row], out_md: Path, out_json: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "date": "2026-05-12",
        "rows": [asdict(r) for r in rows],
    }
    out_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 10-Basin Objective Table (Checkout Execution)",
        "",
        "| Basin | Area | Build | Warmup | Engine | Calibration | KGE | NSE | Tier | Blocker/Notes |",
        "|---|---:|---|---|---|---|---:|---:|---|---|",
    ]
    for r in rows:
        area = "n/a" if r.area_km2 is None else f"{r.area_km2:g}"
        kge = "n/a" if r.kge is None else f"{r.kge:.3f}"
        nse = "n/a" if r.nse is None else f"{r.nse:.3f}"
        lines.append(
            f"| {r.basin} | {area} | {r.build} | {r.warmup} | {r.engine} | {r.calibration} | {kge} | {nse} | {r.tier} | {r.notes} |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    run_root = Path("demo_runs/objective_10basin").resolve()
    rows = run_suite(run_root)
    write_outputs(
        rows,
        Path("docs/BENCHMARK_10_BASIN_FINAL_2026-05-12.md"),
        Path("docs/benchmark_10_basin_final_2026-05-12.json"),
    )
    print(json.dumps({"rows": len(rows), "run_root": str(run_root)}, indent=2))


if __name__ == "__main__":
    main()
