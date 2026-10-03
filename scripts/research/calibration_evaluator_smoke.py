"""Two real runs plus one cache replay on an existing development model.

Uses copies only, scores 2010--2015, and never changes historical evidence.
This tests evaluator behavior, not optimizer performance or model promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from swatplus_builder.calibration.real_engine import (
    _staged_input_identity,
    load_observed_from_alignment_csv,
    make_real_objective,
)
from swatplus_builder.run.swatplus import locate_binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basin-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Use a new output directory to avoid mixing attempts")
    out.mkdir(parents=True)
    basin = args.basin_root.resolve()
    base = basin / "calibration/locked_calibrated_TxtInOut"
    before = _staged_input_identity(base)
    alignment = basin / "benchmark/alignment.csv"
    lock = json.loads((basin / "benchmark/benchmark_lock.json").read_text())
    obs = load_observed_from_alignment_csv(alignment).loc["2010-01-01":"2015-12-31"]
    binary = locate_binary()
    context = hashlib.sha256(alignment.read_bytes()).hexdigest()
    options = dict(
        base_txtinout=base,
        observed_series=obs,
        outlet_gis_id=lock["outlet_gis_id"],
        binary=binary,
        threads=1,
        timeout_s=300,
        objective_sim_file=lock["sim_source_file"],
        objective_outlet_policy=lock["outlet_policy"],
        parameter_mode="full",
        keep_workdirs=False,
        include_physical_gate=True,
        nyskip_years=0,
        simulation_start="2007-01-01",
        simulation_end="2015-12-31",
        score_start="2010-01-01",
        score_end="2015-12-31",
    )
    manifest = {
        "purpose": "evaluator smoke test, not optimization or promotion",
        "basin_root": str(basin),
        "source_input_sha256": before,
        "alignment_sha256": context,
        "engine_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "score_dates": ["2010-01-01", "2015-12-31"],
        "status": "running",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        objective = make_real_objective(
            **options,
            work_root=out / "search",
            telemetry_dir=out / "invocations",
            reuse_compact_traces=True,
            trace_context_sha256=context,
        )
        first = objective({})
        replay = objective({})
        fresh = make_real_objective(
            **options, work_root=out / "fresh", telemetry_dir=out / "invocations", force_fresh=True
        )({})
        for key in ("nse", "kge", "pbias"):
            assert math.isfinite(first[key])
            assert first[key] == replay[key]
            assert math.isclose(first[key], fresh[key], rel_tol=1e-10, abs_tol=1e-10)
        records = [json.loads(p.read_text()) for p in (out / "invocations").glob("*.json")]
        assert len(records) == 3
        assert sum(bool(r["engine_invoked"]) for r in records) == 2
        assert sum(r["cache_status"] == "compact_hit" for r in records) == 1
        assert _staged_input_identity(base) == before
        manifest.update(
            status="passed",
            metrics=first,
            fresh_metrics=fresh,
            engine_wrapper_calls=2,
            cache_hits=1,
            call_seconds=[r["total_seconds"] for r in records],
        )
    except BaseException as error:
        manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
