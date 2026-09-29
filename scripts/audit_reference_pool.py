#!/usr/bin/env python3
"""Audit a basin-inclusion pool for contamination the original scan missed.

basin_inclusion_protocol.py scanned tests/, scripts/, basins/curated_v1.json
and runs/ for prior gauge use. That missed 03349000, the manuscript's own
negative-control basin, which is referenced only in docs, the manuscript
materials, and run trees outside the repository. This audit scans a wider set
of sources and reports every pool gauge (either group) found in them, with
citations. With --write-pool it writes a patched pool in which each hit is
moved from `included` to `excluded` with its reason. Group assignment is a
per-gauge hash, so removing a gauge does not change any other gauge's group.

Usage:
    python scripts/audit_reference_pool.py --pool basins/reference_pool_v1.json \
        --extra-root ../SWATPlus-Builder-paper --run-root ~/swatplus_runs \
        --ignore basins/prospective_eval_v1_basins.json --ignore runs/pe1 \
        --report basins/reference_pool_v1_audit.json \
        --write-pool basins/reference_pool_v1_1.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".json", ".md", ".tex", ".csv", ".txt", ".toml", ".yaml", ".yml", ".bib"}
ID = re.compile(r"(?<!\d)(\d{8,15})(?!\d)")


def scan_text_tree(root: Path, ids: set[str], ignore: list[Path], hits: dict[str, set[str]]) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {".git", "node_modules", "__pycache__", ".venv", ".venv-repro", "cache"} for part in path.parts):
            continue
        if any(path.resolve().is_relative_to(i) for i in ignore):
            continue
        try:
            if path.stat().st_size > 20_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in ID.finditer(text):
            if m.group(1) in ids:
                hits.setdefault(m.group(1), set()).add(str(path))


def scan_run_root(root: Path, ids: set[str], ignore: list[Path], hits: dict[str, set[str]]) -> None:
    for path in root.rglob("*"):
        if not path.is_dir() or any(path.resolve().is_relative_to(i) for i in ignore):
            continue
        for m in ID.finditer(path.name):
            if m.group(1) in ids:
                hits.setdefault(m.group(1), set()).add(f"run directory {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=Path, required=True)
    ap.add_argument("--extra-root", type=Path, action="append", default=[])
    ap.add_argument("--run-root", type=Path, action="append", default=[])
    ap.add_argument("--ignore", type=Path, action="append", default=[],
                    help="Paths whose references are sanctioned uses after pool generation (e.g. PE1).")
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--write-pool", type=Path)
    args = ap.parse_args()

    pool = json.loads(args.pool.read_text())
    group = {r["usgs_id"]: r["group"] for r in pool["included"]}
    ids = set(group)
    ignore = [(REPO / p).resolve() if not p.is_absolute() else p.resolve() for p in args.ignore]
    ignore.append(args.pool.resolve())
    ignore += [(REPO / "basins").resolve() / n for n in ("reference_pool_v1.json", "reference_pool_v1_1.json")]

    hits: dict[str, set[str]] = {}
    for root in [REPO, *args.extra_root]:
        scan_text_tree(root.expanduser().resolve(), ids, ignore, hits)
    for root in [REPO / "runs", *args.run_root]:
        root = root.expanduser()
        if root.is_dir():
            scan_run_root(root.resolve(), ids, ignore, hits)

    report = {
        "pool": str(args.pool),
        "sources": {"repo": str(REPO), "extra_roots": [str(p) for p in args.extra_root],
                    "run_roots": [str(p) for p in args.run_root], "ignored": [str(p) for p in ignore]},
        "n_pool_gauges": len(ids),
        "n_hits": len(hits),
        "hits": [
            {"usgs_id": uid, "group": group[uid], "n_sources": len(src), "sources": sorted(src)[:20]}
            for uid, src in sorted(hits.items())
        ],
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    for h in report["hits"]:
        print(f"{h['usgs_id']} [{h['group']}] {h['n_sources']} source(s), e.g. {h['sources'][0]}")
    print(f"{len(hits)} pool gauge(s) found in prior-use sources -> {args.report}")

    if args.write_pool:
        patched = dict(pool)
        patched["schema"] = pool["schema"]
        patched["patched_from"] = str(args.pool)
        patched["patch_reason"] = "audit_reference_pool.py: wider contamination scan"
        patched["included"] = [r for r in pool["included"] if r["usgs_id"] not in hits]
        patched["excluded"] = sorted(
            pool["excluded"] + [
                {"usgs_id": uid, "station_nm": next(r["station_nm"] for r in pool["included"] if r["usgs_id"] == uid),
                 "state_cd": next(r["state_cd"] for r in pool["included"] if r["usgs_id"] == uid),
                 "reason": "contaminated_prior_use", "detail": "; ".join(sorted(src)[:5]) + " (audit v1.1)"}
                for uid, src in hits.items()
            ],
            key=lambda r: r["usgs_id"],
        )
        args.write_pool.write_text(json.dumps(patched, indent=2))
        print(f"patched pool: {len(patched['included'])} included -> {args.write_pool}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
