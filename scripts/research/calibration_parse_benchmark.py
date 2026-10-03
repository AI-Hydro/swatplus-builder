"""Paired training-only evaluator timing on retained development outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from swatplus_builder.calibration.real_engine import load_observed_from_alignment_csv
from swatplus_builder.output import eval as evaluator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basin-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    basin = args.basin_root.resolve()
    source = basin / "calibration/locked_calibrated_TxtInOut/channel_sd_day.txt"
    obs = load_observed_from_alignment_csv(basin / "benchmark/alignment.csv").loc[
        "2010-01-01":"2015-12-31"
    ]
    lock = json.loads((basin / "benchmark/benchmark_lock.json").read_text())
    shared = evaluator._evaluation_table
    original_reader = evaluator.read_output_file
    records = []
    baseline = None
    try:
        for mode in ("uncached", "shared", "shared", "uncached"):
            reads = []

            def counted(path, _reads=reads):
                _reads.append(str(path))
                return original_reader(path)

            evaluator.read_output_file = counted
            evaluator._evaluation_table = (
                (lambda path, tables: counted(path)) if mode == "uncached" else shared
            )
            started = time.monotonic()
            result = evaluator.evaluate_run(
                source, obs, lock["outlet_gis_id"], outlet_policy="strict", return_diagnostics=True
            )
            elapsed = time.monotonic() - started
            if baseline is None:
                baseline = result
            else:
                pd.testing.assert_frame_equal(baseline[0], result[0])
                assert baseline[1] == result[1]
                assert baseline[2] == result[2]
            records.append({"mode": mode, "seconds": elapsed, "source_reads": len(reads)})
    finally:
        evaluator._evaluation_table = shared
        evaluator.read_output_file = original_reader
    report = {
        "purpose": "parse refactor only; no engines or optimizer speedup inference",
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "evaluator_sha256": hashlib.sha256(Path(evaluator.__file__).read_bytes()).hexdigest(),
        "score_dates": ["2010-01-01", "2015-12-31"],
        "equality": "exact",
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
