"""Offline unit-scaling probe; never runs the simulator or selects parameters.

Run from repository root with PYTHONPATH=src .venv/bin/python
scripts/research/calibration_objective_probe.py --output <path>.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from swatplus_builder.output.metrics import kge, log_kge, log_kge_v2, nse


def transformed_nse(obs: list[float], sim: list[float], kind: str) -> float:
    if not obs or len(obs) != len(sim):
        raise ValueError("Aligned nonempty series required")
    if any(not math.isfinite(x) or x < 0 for x in obs + sim):
        raise ValueError("Finite nonnegative flows required")
    mean = sum(obs) / len(obs)
    if mean <= 0 or len(set(obs)) < 2:
        raise ValueError("Positive observed mean and nonconstant observations required")
    if kind == "sqrt":
        transform = math.sqrt
    else:
        # Both arrays use observed TRAINING mean; never a validation mean.
        epsilon = 0.01 * mean

        def transform(x):
            return math.log(x + epsilon)

    value = nse([transform(x) for x in obs], [transform(x) for x in sim])
    if not math.isfinite(value):
        raise ValueError("Undefined transformed NSE")
    return value


def probe(obs: list[float], sim: list[float]) -> dict:
    scores = {}
    for factor in (0.001, 1.0, 1000.0, 1000000.0):
        o, s = [x * factor for x in obs], [x * factor for x in sim]
        scores[str(factor)] = {
            "kge": float(kge(o, s)),
            "legacy_log_kge": float(log_kge(o, s)),
            "relative_log_kge": float(log_kge_v2(o, s)),
            "sqrt_nse": transformed_nse(o, s, "sqrt"),
            "relative_log_nse": transformed_nse(o, s, "log"),
        }
    for metric in ("kge", "sqrt_nse", "relative_log_nse"):
        values = [row[metric] for row in scores.values()]
        if not all(math.isclose(v, values[0], rel_tol=1e-10, abs_tol=1e-10) for v in values):
            raise AssertionError(f"Unit invariance failed: {metric}")
    return {"n": len(obs), "scores_by_unit_factor": scores}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figure-inputs", type=Path)
    args = parser.parse_args()
    report = {
        "purpose": "unit invariance only; not calibration or low-flow validation",
        "engine_calls": 0,
        "cases": {},
        "invalid_cases_rejected": [],
    }
    report["cases"]["synthetic_positive"] = probe(
        [0.1, 0.2, 0.5, 1, 2, 4, 8], [0.15, 0.25, 0.4, 1.2, 1.8, 3.8, 7.5]
    )
    report["cases"]["synthetic_intermittent"] = probe(
        [0, 0, 0.1, 0.5, 1, 2, 4], [0, 0.01, 0.15, 0.4, 1.2, 1.8, 3.8]
    )
    for name, obs, sim in (
        ("all_zero", [0, 0], [0, 0]),
        ("constant", [1, 1], [1, 2]),
        ("negative", [-1, 2], [1, 2]),
        ("nonfinite", [1, float("nan")], [1, 2]),
    ):
        for kind in ("sqrt", "log"):
            try:
                transformed_nse(obs, sim, kind)
            except ValueError:
                report["invalid_cases_rejected"].append(f"{name}:{kind}")
            else:
                raise AssertionError(f"Invalid case accepted: {name}:{kind}")
    if args.figure_inputs:
        for filename in ("positive_01547700_daily.csv", "negative_03349000_daily.csv"):
            path = args.figure_inputs / filename
            with path.open(newline="") as handle:
                rows = [
                    r for r in csv.DictReader(handle) if "2010-01-01" <= r["date"] <= "2015-12-31"
                ]
            obs = [float(r["observed"]) for r in rows]
            for column in ("benchmark", "verification"):
                result = probe(obs, [float(r[column]) for r in rows])
                result.update(
                    source=str(path.resolve()),
                    source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    start=rows[0]["date"],
                    end=rows[-1]["date"],
                    note="Existing development data; dates after 2015 excluded",
                )
                report["cases"][f"{filename}:{column}"] = result
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        f"Passed unit-invariance and rejection checks; {len(report['cases'])} cases; zero engine calls"
    )


if __name__ == "__main__":
    main()
