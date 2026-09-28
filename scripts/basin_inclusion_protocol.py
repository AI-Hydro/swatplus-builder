#!/usr/bin/env python3
"""Generate a reference basin pool for decision-data generation under a
documented, reproducible inclusion protocol -- see
docs/BASIN_INCLUSION_PROTOCOL.md for the full rationale and disclosed gaps.
Read that document before using this script's output for anything beyond a
first proof run.

Queries the live USGS NWIS site service (via `pygeohydro.NWIS`, already a
pinned dependency under the `hyriver` extra) per state, applies hard
inclusion filters, excludes every USGS ID already used anywhere in this
repository's development/testing history, and deterministically splits the
survivors into "development" and "held_out_final_assessment" basin groups.

Usage:
    python scripts/basin_inclusion_protocol.py --states IN OH KY \\
        --out basins/reference_pool_v1.json

    # Full CONUS (slow: ~48 live NWIS queries; expect several minutes and
    # occasional transient 503s from NWIS -- each state is retried, but a
    # state that fails twice is recorded, not silently dropped):
    python scripts/basin_inclusion_protocol.py --states all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Square miles -> square kilometers. USGS NWIS's `drain_area_va` field is
# documented (NWIS site-service RDB output) as drainage area in square
# miles; this is the standard, long-standing USGS convention, not this
# project's own unit choice.
_MI2_TO_KM2 = 2.58999

# The 48 conterminous US states + DC. AK/HI/territories are excluded because
# this pipeline's forcing/soil/terrain providers (GridMET, gNATSGO, 3DEP)
# are CONUS-only (docs/BASIN_INCLUSION_PROTOCOL.md Section 1).
CONUS_STATES = [
    "al", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "id", "il",
    "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo",
    "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or",
    "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi",
    "wy",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def find_contaminated_usgs_ids(repo_root: Path) -> dict[str, list[str]]:
    """Best-effort textual scan for USGS IDs already used in this repo's
    development/testing history. Returns {usgs_id: [source citations]}.
    See docs/BASIN_INCLUSION_PROTOCOL.md Section 4 for what this does and
    does not catch."""
    hits: dict[str, list[str]] = {}

    def _add(usgs_id: str, citation: str) -> None:
        hits.setdefault(usgs_id, []).append(citation)

    id_pattern = re.compile(r"\b(\d{8,15})\b")

    curated = repo_root / "basins" / "curated_v1.json"
    if curated.is_file():
        try:
            data = json.loads(curated.read_text(encoding="utf-8"))
            for entry in data.get("basins", []):
                usgs_id = str(entry.get("usgs_id") or "")
                if usgs_id:
                    _add(usgs_id, f"{curated.relative_to(repo_root)}")
        except (json.JSONDecodeError, OSError):
            pass

    scan_globs = [
        "tests/**/*.py",
        "scripts/**/*.py",
        "scripts/**/*.json",
    ]
    context_pattern = re.compile(r'usgs[_-]id["\']?\s*[:=]\s*["\']?(\d{8,15})|usgs_(\d{8,15})', re.IGNORECASE)
    for pattern in scan_globs:
        for path in repo_root.glob(pattern):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in context_pattern.finditer(text):
                usgs_id = m.group(1) or m.group(2)
                if usgs_id:
                    line_no = text.count("\n", 0, m.start()) + 1
                    _add(usgs_id, f"{path.relative_to(repo_root)}:{line_no}")

    runs_dir = repo_root / "runs"
    if runs_dir.is_dir():
        for child in runs_dir.rglob("usgs_*"):
            if child.is_dir():
                m = re.match(r"usgs_(\d{8,15})", child.name)
                if m:
                    _add(m.group(1), f"{child.relative_to(repo_root)}")

    # Fold in bare 8-15 digit tokens from the same scanned files too, in
    # case a usgs_id appears without the "usgs_id"/"usgs_<id>" context
    # (e.g. a bare positional CLI arg). Deliberately looser, so it can pick
    # up false positives from unrelated numbers; only use it to *widen* the
    # exclusion set (never to include a basin), which is the safe direction
    # to err in here.
    for pattern in scan_globs:
        for path in repo_root.glob(pattern):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "usgs" not in text.lower():
                continue
            for m in id_pattern.finditer(text):
                usgs_id = m.group(1)
                if usgs_id not in hits:
                    line_no = text.count("\n", 0, m.start()) + 1
                    window = text[max(0, m.start() - 40) : m.start()]
                    if "usgs" in window.lower():
                        _add(usgs_id, f"{path.relative_to(repo_root)}:{line_no} (loose match)")

    return hits


def query_state(nwis: Any, state_cd: str, retries: int = 2) -> tuple[Any | None, str | None]:
    """Query one state's active daily-discharge stream sites with period of
    record. Returns (dataframe_or_None, error_or_None). Retries transient
    failures (NWIS occasionally 503s) but never raises -- a state that
    fails after retries is recorded as a query failure, not silently
    skipped."""
    query = {
        "stateCd": state_cd,
        "siteType": "ST",
        "hasDataTypeCd": "dv",
        "parameterCd": "00060",
        "siteStatus": "active",
        "seriesCatalogOutput": "true",
    }
    last_error = None
    for attempt in range(retries + 1):
        try:
            df = nwis.get_info(query, expanded=True)
            return df, None
        except Exception as exc:  # pygeohydro/NWIS raises various HTTP/parse errors
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(2.0 * (attempt + 1))
    return None, last_error


def assign_group(usgs_id: str, *, development_fraction: float, salt: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"{salt}:{usgs_id}".encode()).hexdigest()
    u = int(digest[:12], 16) / float(16**12)
    return "development" if u < development_fraction else "held_out_final_assessment"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--states", nargs="+", default=["in", "oh", "ky"],
                    help="Two-letter state codes to query, or 'all' for full CONUS (default: in oh ky -- a small, fast first proof run; see module docstring).")
    p.add_argument("--window-start", default="2000-01-01")
    p.add_argument("--window-end", default="2019-12-31")
    p.add_argument("--min-drainage-mi2", type=float, default=50.0)
    p.add_argument("--max-drainage-mi2", type=float, default=3000.0)
    p.add_argument("--development-fraction", type=float, default=0.5)
    p.add_argument("--split-salt", default="swat-s1-basin-inclusion-v1")
    p.add_argument("--out", type=Path, default=REPO_ROOT / "basins" / "reference_pool_v1.json")
    p.add_argument("--dry-run", action="store_true", help="Query and filter, print counts, write nothing.")
    args = p.parse_args()

    states = CONUS_STATES if args.states == ["all"] else [s.lower() for s in args.states]
    unknown = sorted(set(states) - set(CONUS_STATES))
    if unknown:
        print(f"unknown state code(s): {unknown}", file=sys.stderr)
        return 2

    try:
        from pygeohydro import NWIS
    except ImportError as exc:
        print(f"pygeohydro is required (hyriver extra): {exc}", file=sys.stderr)
        return 2

    print(f"[{now_utc()}] scanning repo for already-used USGS IDs...")
    contaminated = find_contaminated_usgs_ids(REPO_ROOT)
    print(f"[{now_utc()}] {len(contaminated)} already-used USGS ID(s) found, will be excluded")

    nwis = NWIS()
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    query_failures: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for state_cd in states:
        print(f"[{now_utc()}] querying NWIS: state={state_cd}")
        df, error = query_state(nwis, state_cd)
        if df is None:
            print(f"[{now_utc()}]   query failed for {state_cd}: {error}")
            query_failures.append({"state_cd": state_cd, "error": error or "unknown"})
            continue
        if df.empty:
            continue
        discharge = df[(df.get("parm_cd") == "00060") & (df.get("data_type_cd") == "dv")].copy()
        if discharge.empty:
            continue
        import pandas as pd

        discharge["begin_date"] = pd.to_datetime(discharge["begin_date"], errors="coerce")
        discharge["end_date"] = pd.to_datetime(discharge["end_date"], errors="coerce")
        per_site = discharge.groupby("site_no").agg(
            begin_date=("begin_date", "min"),
            end_date=("end_date", "max"),
        )
        site_meta = df.drop_duplicates("site_no").set_index("site_no")

        window_start = pd.Timestamp(args.window_start)
        window_end = pd.Timestamp(args.window_end)

        for site_no, por in per_site.iterrows():
            usgs_id = str(site_no)
            if usgs_id in seen_ids:
                continue  # a site can appear once per state query only; guards accidental dupes
            seen_ids.add(usgs_id)
            meta = site_meta.loc[site_no]
            site_tp = str(meta.get("site_tp_cd") or "")
            drain_area_mi2 = meta.get("drain_area_va")
            hcdn = bool(meta.get("hcdn_2009")) if meta.get("hcdn_2009") is not None else False
            station_nm = str(meta.get("station_nm") or "")

            if usgs_id in contaminated:
                excluded.append({
                    "usgs_id": usgs_id, "station_nm": station_nm, "state_cd": state_cd,
                    "reason": "contaminated_prior_use",
                    "detail": "; ".join(contaminated[usgs_id]),
                })
                continue
            if site_tp != "ST":
                excluded.append({"usgs_id": usgs_id, "station_nm": station_nm, "state_cd": state_cd,
                                  "reason": "not_stream_type", "detail": f"site_tp_cd={site_tp!r}"})
                continue
            if pd.isna(por["begin_date"]) or pd.isna(por["end_date"]) or por["begin_date"] > window_start or por["end_date"] < window_end:
                excluded.append({
                    "usgs_id": usgs_id, "station_nm": station_nm, "state_cd": state_cd,
                    "reason": "insufficient_period_of_record",
                    "detail": f"begin={por['begin_date']}, end={por['end_date']}, "
                              f"window=[{args.window_start},{args.window_end}]",
                })
                continue
            if drain_area_mi2 is None or pd.isna(drain_area_mi2):
                excluded.append({"usgs_id": usgs_id, "station_nm": station_nm, "state_cd": state_cd,
                                  "reason": "missing_drainage_area", "detail": ""})
                continue
            drain_area_mi2 = float(drain_area_mi2)
            if not (args.min_drainage_mi2 <= drain_area_mi2 <= args.max_drainage_mi2):
                excluded.append({
                    "usgs_id": usgs_id, "station_nm": station_nm, "state_cd": state_cd,
                    "reason": "drainage_area_out_of_bounds",
                    "detail": f"drain_area_mi2={drain_area_mi2}, bounds=[{args.min_drainage_mi2},{args.max_drainage_mi2}]",
                })
                continue

            included.append({
                "usgs_id": usgs_id,
                "station_nm": station_nm,
                "state_cd": state_cd,
                "drain_area_mi2": drain_area_mi2,
                "drain_area_km2": round(drain_area_mi2 * _MI2_TO_KM2, 2),
                "hcdn_2009": hcdn,
                "begin_date": str(por["begin_date"].date()),
                "end_date": str(por["end_date"].date()),
                "group": assign_group(usgs_id, development_fraction=args.development_fraction, salt=args.split_salt),
            })

    n_dev = sum(1 for r in included if r["group"] == "development")
    n_held = len(included) - n_dev
    print(f"[{now_utc()}] included={len(included)} (development={n_dev}, held_out_final_assessment={n_held}), "
          f"excluded={len(excluded)}, query_failures={len(query_failures)}")

    if args.dry_run:
        return 0

    payload = {
        "schema": "swatplus_builder.basin_inclusion_pool/v1",
        "generated_utc": now_utc(),
        "generator": {
            "script": "scripts/basin_inclusion_protocol.py",
            "states_queried": states,
            "query_failures": query_failures,
            "window": [args.window_start, args.window_end],
            "filters": {
                "site_type": "ST",
                "min_drainage_mi2": args.min_drainage_mi2,
                "max_drainage_mi2": args.max_drainage_mi2,
                "period_of_record_must_cover_window": True,
            },
            "split": {"development_fraction": args.development_fraction, "salt": args.split_salt},
        },
        "included": sorted(included, key=lambda r: r["usgs_id"]),
        "excluded": sorted(excluded, key=lambda r: r["usgs_id"]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[{now_utc()}] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
