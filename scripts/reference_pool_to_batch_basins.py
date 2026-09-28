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

    candidates.sort(key=lambda r: _sample_key(r["usgs_id"], args.sample_salt))
    if args.limit is not None:
        candidates = candidates[: args.limit]

    specs = [
        {
            "usgs_id": r["usgs_id"],
            "start": args.run_start,
            "end": args.run_end,
            "warmup_years": args.warmup_years,
            "claim_tier": args.claim_tier,
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
    print(f"wrote {len(specs)} basin spec(s) from group={args.group!r} to {args.out}")
    for spec in specs:
        print(f"  {spec['usgs_id']}  {spec['_station_nm']}  ({spec['_drain_area_km2']} km2, hcdn_2009={spec['_hcdn_2009']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
