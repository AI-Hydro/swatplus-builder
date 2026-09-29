#!/usr/bin/env python3
"""Convert a basin-inclusion-protocol reference pool
(`basins/reference_pool_v1.json`, from `scripts/basin_inclusion_protocol.py`)
into the basin-spec JSON that `scripts/decision_data_batch.py --basins`
expects.

By design this only ever emits basins from the `development` group. The
`held_out_final_assessment` group exists specifically so it is *not* run
until the pipeline and decision model are frozen
(docs/BASIN_INCLUSION_PROTOCOL.md Section 5) -- emitting it here by
default would make that discipline trivial to break by accident. Emitting
the held-out group requires `--group held_out_final_assessment` AND
`--i-understand-this-is-the-held-out-set` together, so it cannot happen by
a stray default or a copy-pasted command.

Selection within the chosen group is deterministic (SHA-256 hash of the
basin id under its own salt, distinct from both the basin-inclusion split
salt and the episode-level train/val/test split salt) so `--limit N` always
picks the same N basins for the same pool file and salt, without biasing
toward any particular USGS-ID numbering range (which roughly follows
hydrologic unit code, not random order) the way a plain sort would.

Usage:
    python scripts/reference_pool_to_batch_basins.py \\
        --pool basins/reference_pool_v1.json --limit 2 \\
        --out scripts/decision_data_batch_basins.proof_run.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Distinct from basin_inclusion_protocol.py's development/held-out split
# salt and from decision_data/typed.py's train/validation/test split salt --
# each partition decision in this pipeline uses its own salt so none of
# them correlate with, or leak into, another.
_DEFAULT_SAMPLE_SALT = "swat-s1-batch-basin-sample-v1"


def _sample_key(usgs_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{usgs_id}".encode()).hexdigest()


def _already_run_ids(runs_root: Path) -> set[str]:
    if not runs_root.is_dir():
        return set()
    return {
        p.name.split("_", 1)[1]
        for p in runs_root.rglob("usgs_*")
        if p.is_dir() and p.name.split("_", 1)[1].isdigit()
    }


def _window_discharge_coverage(usgs_id: str, start: str, end: str) -> tuple[float | None, str | None]:
    """Fraction of days in [start, end] with a finite observed discharge."""
    import math

    import pandas as pd

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from swatplus_builder.calibration.nwis import fetch_usgs_daily_q

    try:
        q = fetch_usgs_daily_q(usgs_id, start, end)
    except Exception as exc:  # NWIS/pygeohydro raise varied errors for empty sites
        return 0.0, f"{type(exc).__name__}: {str(exc)[:160]}"
    # Compare calendar dates, not timestamps: cached series come back with a
    # datetime64[us] index, and reindexing that against a nanosecond
    # date_range silently matches nothing (observed: 0.0 coverage for a
    # basin with a complete record).
    wanted = {d.date() for d in pd.date_range(start, end, freq="D")}
    have = {
        pd.Timestamp(ts).date()
        for ts, v in q.items()
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    }
    return round(len(wanted & have) / len(wanted), 4), None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pool", type=Path, default=REPO_ROOT / "basins" / "reference_pool_v1.json")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--group", default="development", choices=["development", "held_out_final_assessment"])
    p.add_argument("--i-understand-this-is-the-held-out-set", action="store_true",
                    help="Required in addition to --group held_out_final_assessment; see module docstring.")
    p.add_argument("--limit", type=int, default=None, help="Emit at most this many basins (deterministic sample; default: all in the group).")
    p.add_argument("--sample-salt", default=_DEFAULT_SAMPLE_SALT)
    p.add_argument("--state-cd", nargs="*", default=None, help="Restrict to these state codes (default: all).")
    p.add_argument("--hcdn-2009-only", action="store_true", help="Restrict to USGS HCDN-2009-flagged reference-quality basins.")
    # Fields written into each emitted basin spec for `swat workflow run`.
    # Deliberately a *shorter* operational window than the pool's coverage
    # window (2000-2019): the pool only guarantees the full 2000-2019 window
    # is covered by each basin's period of record, it does not mean a full
    # 20-year run is the right choice for a quick proof run. A real batch
    # for training data would likely widen this back out.
    p.add_argument("--run-start", default="2015-01-01")
    p.add_argument("--run-end", default="2019-12-31")
    p.add_argument("--warmup-years", type=int, default=2)
    p.add_argument("--claim-tier", default="diagnostic")
    p.add_argument("--hru-mode", default=None, choices=[None, "dominant_only", "full_overlay"])
    p.add_argument("--min-hru-fraction", type=float, default=None)
    p.add_argument("--contract-status", default=None, help="e.g. accepted (required with --accepted-by for research_grade).")
    p.add_argument("--accepted-by", default=None, choices=[None, "user", "policy", "agent"])
    p.add_argument("--max-drain-area-km2", type=float, default=None,
                    help="Keep only basins at or below this drainage area (runtime feasibility cap; disclose it).")
    p.add_argument("--exclude-already-run", action="store_true",
                    help="Skip basins that already have a usgs_<id> run directory anywhere under runs/.")
    p.add_argument("--verify-window-data", action="store_true",
                    help="Fetch each candidate's observed discharge for the run window (pipeline's own fetch) "
                         "and keep only basins meeting --min-window-coverage. Site period-of-record metadata "
                         "can span multi-decade gaps (docs/BASIN_INCLUSION_PROTOCOL.md Section 8).")
    p.add_argument("--min-window-coverage", type=float, default=0.95)
    args = p.parse_args()

    if args.group == "held_out_final_assessment" and not args.i_understand_this_is_the_held_out_set:
        print(
            "Refusing to emit the held_out_final_assessment group without "
            "--i-understand-this-is-the-held-out-set. This group exists so it "
            "is NOT run until the pipeline and decision model are frozen "
            "(docs/BASIN_INCLUSION_PROTOCOL.md Section 5). If you really mean to "
            "run it now, pass both flags explicitly.",
            file=sys.stderr,
        )
        return 2

    pool = json.loads(args.pool.read_text(encoding="utf-8"))
    if pool.get("schema") != "swatplus_builder.basin_inclusion_pool/v1":
        print(f"unexpected pool schema: {pool.get('schema')!r}", file=sys.stderr)
        return 2

    candidates = [r for r in pool["included"] if r["group"] == args.group]
    if args.state_cd:
        wanted = {s.lower() for s in args.state_cd}
        candidates = [r for r in candidates if r["state_cd"] in wanted]
    if args.hcdn_2009_only:
        candidates = [r for r in candidates if r["hcdn_2009"]]
    if args.max_drain_area_km2 is not None:
        candidates = [r for r in candidates if r["drain_area_km2"] <= args.max_drain_area_km2]

    candidates.sort(key=lambda r: _sample_key(r["usgs_id"], args.sample_salt))

    if args.exclude_already_run:
        already = _already_run_ids(REPO_ROOT / "runs")
        candidates = [r for r in candidates if r["usgs_id"] not in already]

    preflight_log: list[dict] = []
    if args.verify_window_data:
        # Walk candidates in sample order, keeping those whose observed
        # discharge actually covers the run window, until --limit is met.
        # Uses the pipeline's own fetch (and its cache) so the check matches
        # exactly what `swat workflow run` will see.
        kept = []
        for r in candidates:
            if args.limit is not None and len(kept) >= args.limit:
                break
            coverage, reason = _window_discharge_coverage(r["usgs_id"], args.run_start, args.run_end)
            ok = coverage is not None and coverage >= args.min_window_coverage
            preflight_log.append({"usgs_id": r["usgs_id"], "coverage": coverage, "kept": ok, "reason": reason})
            print(f"  preflight {r['usgs_id']}: coverage={coverage} {'kept' if ok else 'rejected: ' + (reason or 'below threshold')}")
            if ok:
                kept.append(r)
        candidates = kept
    elif args.limit is not None:
        candidates = candidates[: args.limit]

    specs = [
        {
            "usgs_id": r["usgs_id"],
            "start": args.run_start,
            "end": args.run_end,
            "warmup_years": args.warmup_years,
            "claim_tier": args.claim_tier,
            **{
                k: v
                for k, v in {
                    "hru_mode": args.hru_mode,
                    "min_hru_fraction": args.min_hru_fraction,
                    "contract_status": args.contract_status,
                    "accepted_by": args.accepted_by,
                }.items()
                if v is not None
            },
            # Carried through for traceability back to the pool this basin
            # came from -- decision_data_batch.py ignores unknown keys.
            "_source_pool": str(args.pool.name),
            "_source_group": args.group,
            "_station_nm": r["station_nm"],
            "_drain_area_km2": r["drain_area_km2"],
            "_hcdn_2009": r["hcdn_2009"],
        }
        for r in candidates
    ]

    if not specs:
        print("no basins matched the given filters", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(specs, indent=2), encoding="utf-8")
    if preflight_log:
        preflight_path = args.out.with_suffix(".preflight.json")
        preflight_path.write_text(json.dumps({
            "window": [args.run_start, args.run_end],
            "min_window_coverage": args.min_window_coverage,
            "checked": preflight_log,
        }, indent=2), encoding="utf-8")
        n_rej = sum(1 for p in preflight_log if not p["kept"])
        print(f"preflight: {len(preflight_log)} checked, {n_rej} rejected -> {preflight_path}")
    print(f"wrote {len(specs)} basin spec(s) from group={args.group!r} to {args.out}")
    for spec in specs:
        print(f"  {spec['usgs_id']}  {spec['_station_nm']}  ({spec['_drain_area_km2']} km2, hcdn_2009={spec['_hcdn_2009']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
