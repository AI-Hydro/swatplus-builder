"""Bounded development-only DDS / constrained-GP real-engine pilot.

Six attributed search observations plus one fresh selected-candidate rerun per
arm. Three initial evaluations are physically shared, so the maximum physical
cost is eleven calls, compared with fourteen attributed calls. Raw KGE only;
training 2010--2015, simulation 2007--2015. No withheld-year scoring or promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import subprocess
import time
from collections.abc import Callable, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any

import swatplus_builder
from swatplus_builder.calibration.locked_benchmark import _dds_search
from swatplus_builder.calibration.real_engine import (
    _copy_fresh_txtinout,
    _staged_input_identity,
    load_observed_from_alignment_csv,
    make_real_objective,
)
from swatplus_builder.calibration.surrogate_optimizer import (
    ConstrainedGPOptimizer,
    ConstrainedObservation,
)
from swatplus_builder.errors import SwatBuilderExternalError
from swatplus_builder.params.registry import get_parameter
from swatplus_builder.run.swatplus import locate_binary

PARAMETERS = ("PET_CO", "PERCO")
CONSTRAINTS = ("volume", "calibration_process")
POLICY = "raw_kge_volume30_explicit_calibration_process_v1"


def measured_observation(evaluation_id: str, metrics: Mapping[str, Any]) -> ConstrainedObservation:
    """Missing/non-finite metrics are unavailable; false process flags are infeasible."""
    try:
        nse, kge, pbias = (float(metrics[n]) for n in ("nse", "kge", "pbias"))
        flag = metrics["calibration_process_gate_passed"]
        if not all(math.isfinite(v) for v in (nse, kge, pbias)) or flag not in (0, 1):
            raise ValueError("Non-finite metric or unresolved process gate")
    except (KeyError, ValueError, TypeError):
        return ConstrainedObservation(evaluation_id, "failed")
    return ConstrainedObservation(
        evaluation_id,
        "success",
        kge,
        {"volume": abs(pbias) / 30 - 1, "calibration_process": -1.0 if flag == 1 else 1.0},
    )


def feasible(metrics: Mapping[str, Any]) -> bool:
    observation = measured_observation("feasibility-check", metrics)
    return observation.status == "success" and all(v <= 0 for v in observation.constraints.values())


def score(metrics: Mapping[str, Any]) -> float:
    observation = measured_observation("score-check", metrics)
    return observation.utility if observation.status == "success" else -math.inf


def finite_json(value: Any) -> Any:
    """Preserve missing numeric measurements as null, never emit JSON NaN/Infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(k): finite_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [finite_json(v) for v in value]
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".pending")
    temp.write_text(json.dumps(finite_json(payload), indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def run_comparison(
    evaluate: Callable[[dict[str, float], str], dict[str, Any]],
    bounds: dict[str, tuple[float, float]],
    initial_points: list[dict[str, float]],
    *,
    seed: int = 42,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
    gp: ConstrainedGPOptimizer | None = None,
) -> dict[str, Any]:
    """Independent of engine IO; physical shared evaluations are attributed twice."""
    if len(initial_points) != 3:
        raise ValueError("Pilot requires exactly three shared initial points")
    gp = gp or ConstrainedGPOptimizer(
        bounds,
        CONSTRAINTS,
        budget=6,
        initial_design_size=3,
        initial_points=initial_points,
        seed=seed,
    )
    gp.check_dependencies()  # Before every evaluator callback, even design calls.
    report: dict[str, Any] = {
        "policy": POLICY,
        "interpretation": "exploratory two-parameter development pilot; no superiority claim",
        "search_budget_per_arm": 6,
        "verification_reserve_per_arm": 1,
        "physical_call_cap": 11,
        "attributed_call_cap": 14,
        "physical_call_count_basis": "attempted evaluator callbacks, including pre-subprocess failures; not confirmed process launches",
        "process_constraint_interpretation": "signed categorical reported process-pass proxy (-1 pass/+1 fail), not a continuous conservation residual",
        "physical_calls": [],
        "arms": {},
        "status": "running",
    }
    started = time.monotonic()

    def save():
        report["elapsed_seconds"] = time.monotonic() - started
        if checkpoint:
            checkpoint(report)

    def call(point, label):
        if len(report["physical_calls"]) >= 11:
            raise RuntimeError("Physical pilot call cap exhausted")
        record = {
            "evaluation_id": label,
            "parameters": dict(point),
            "status": "attempting",
            "metrics": {},
        }
        report["physical_calls"].append(record)
        save()  # Persist reservation before invoking the engine.
        tic = time.monotonic()
        try:
            metrics = dict(evaluate(dict(point), label))
            observation = measured_observation(label, metrics)
            record.update(
                status=observation.status,
                metrics=metrics,
                utility=observation.utility,
                constraints=dict(observation.constraints),
                reason=None
                if observation.status == "success"
                else "missing/non-finite metric or unresolved gate",
            )
        except (SwatBuilderExternalError, TimeoutError, subprocess.TimeoutExpired) as error:
            metrics = {}
            observation = ConstrainedObservation(label, "failed")
            record.update(status="failed", reason=f"{type(error).__name__}: {error}")
        except Exception as error:
            record.update(
                status="adapter_error",
                reason=f"{type(error).__name__}: {error}",
                seconds=time.monotonic() - tic,
            )
            save()
            raise
        except BaseException:
            record.update(status="interrupted", seconds=time.monotonic() - tic)
            save()
            raise
        record["seconds"] = time.monotonic() - tic
        save()
        return metrics, observation

    shared = []
    for index, point in enumerate(initial_points):
        proposal = gp.ask()
        actual = dict(proposal.parameters)
        if any(not math.isclose(actual[n], point[n], rel_tol=0, abs_tol=1e-12) for n in bounds):
            raise RuntimeError("GP shared design does not match the requested point")
        metrics, observation = call(actual, f"shared_{index}")
        gp.tell(proposal.proposal_id, observation)
        shared.append((actual, metrics, observation))
    admissible = [(p, m, o.utility) for p, m, o in shared if feasible(m)]
    initial_best = max(admissible, key=lambda item: item[2]) if admissible else None
    if initial_best is not None:
        start = dict(initial_best[0])
    else:
        start = dict(initial_points[0])
    dds_ids = [f"shared_{i}" for i in range(3)]

    def dds_evaluate(point):
        label = f"dds_search_{len(dds_ids) - 3}"
        metrics, _ = call(point, label)
        dds_ids.append(label)
        return metrics

    best_params, best_metrics, _ = _dds_search(
        evaluate=dds_evaluate,
        score_fn=score,
        feasible_fn=feasible,
        phase_parameters=list(bounds),
        param_bounds=bounds,
        start_params=start,
        budget=3,
        budget_is_total=True,
        rng=random.Random(seed),
        initial_best=initial_best,
    )
    report["arms"]["dds"] = {
        "search_evaluation_ids": dds_ids,
        "parameters": best_params,
        "search_metrics": best_metrics,
    }
    gp_ids = [f"shared_{i}" for i in range(3)]
    while gp.proposals_issued < gp.budget:
        proposal = gp.ask()
        label = f"gp_search_{len(gp_ids) - 3}"
        _, observation = call(dict(proposal.parameters), label)
        gp.tell(proposal.proposal_id, observation)
        gp_ids.append(label)
    best = gp.best
    report["arms"]["gp"] = {
        "search_evaluation_ids": gp_ids,
        "proposal_methods": [r.proposal.method for r in gp.observations],
        "parameters": dict(best.proposal.parameters) if best else None,
        "search_utility": best.observation.utility if best else None,
        "search_metrics": next(
            (
                r["metrics"]
                for r in report["physical_calls"]
                if best and r["evaluation_id"] == best.observation.evaluation_id
            ),
            {},
        ),
    }
    for arm in ("dds", "gp"):
        result = report["arms"][arm]
        if len(result["search_evaluation_ids"]) != 6:
            raise RuntimeError("Attributed arm search budget mismatch")
        if result["parameters"] is not None:
            metrics, observation = call(result["parameters"], f"{arm}_fresh_final")
            result["fresh_final_metrics"] = metrics
            result["fresh_final_admissible"] = feasible(metrics)
            result["fresh_final_evaluation_id"] = observation.evaluation_id
            matches = {}
            for metric in ("nse", "kge", "pbias"):
                before, after = result["search_metrics"].get(metric), metrics.get(metric)
                matches[metric] = (
                    isinstance(before, (int, float))
                    and isinstance(after, (int, float))
                    and math.isfinite(before)
                    and math.isfinite(after)
                    and math.isclose(before, after, rel_tol=1e-10, abs_tol=1e-10)
                )
            matches["admissibility"] = feasible(result["search_metrics"]) == feasible(metrics)
            result["fresh_final_matches_search"] = all(matches.values())
            result["fresh_final_comparison"] = matches
            result["verification_status"] = (
                "fresh_training_reproduced"
                if all(matches.values()) and feasible(metrics)
                else "verification_failed"
            )
            result["fresh_minus_search"] = {
                n: float(metrics[n]) - float(result["search_metrics"][n])
                for n in ("nse", "kge", "pbias")
                if isinstance(metrics.get(n), (int, float))
                and isinstance(result["search_metrics"].get(n), (int, float))
                and math.isfinite(metrics[n])
                and math.isfinite(result["search_metrics"][n])
            }
            result["fresh_final_constraints"] = dict(observation.constraints)
            result["selected_constraints"] = dict(
                measured_observation("selected", result["search_metrics"]).constraints
            )
        else:
            result["fresh_final_evaluation_id"] = None
            result["fresh_final_admissible"] = False
            result["fresh_final_skip_reason"] = "No admissible measured search candidate"
            result["verification_status"] = "not_reached"
        result["attributed_calls"] = 6 + int(result["fresh_final_evaluation_id"] is not None)
    report.update(
        status="completed",
        shared_physical_calls=3,
        actual_physical_calls=len(report["physical_calls"]),
        attributed_calls=sum(a["attributed_calls"] for a in report["arms"].values()),
        attribution="Shared initial runs physically executed once and charged to each arm; no other cross-arm cache reuse",
    )
    save()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basin-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    ConstrainedGPOptimizer.check_dependencies()
    basin, out = args.basin_root.resolve(), args.out.resolve()
    if basin.name != "usgs_12054000":
        raise ValueError("This development pilot is restricted to USGS12054000")
    if out.exists() or out.is_relative_to(basin):
        raise ValueError("Use a new output directory outside historical basin evidence")
    source = basin / "calibration/locked_calibrated_TxtInOut"
    source_hash = _staged_input_identity(source)
    lock_path = basin / "benchmark/benchmark_lock.json"
    lock = json.loads(lock_path.read_text())
    alignment = basin / "benchmark/alignment.csv"
    if hashlib.sha256(alignment.read_bytes()).hexdigest() != lock["alignment_sha256"]:
        raise ValueError("Historical observation alignment does not match its lock")
    obs = load_observed_from_alignment_csv(alignment).loc["2010-01-01":"2015-12-31"]
    binary = args.binary.resolve() if args.binary else locate_binary()
    bounds = {n: tuple(get_parameter(n).range) for n in PARAMETERS}
    initial = json.loads(
        (basin / "calibration/calibration_reports_locked/best_solution.json").read_text()
    )["parameters"]
    points = [{n: float(initial[n]) for n in PARAMETERS}]
    points.extend({n: lo + f * (hi - lo) for n, (lo, hi) in bounds.items()} for f in (0.25, 0.75))
    gp = ConstrainedGPOptimizer(
        bounds, CONSTRAINTS, budget=6, initial_design_size=3, initial_points=points, seed=args.seed
    )
    out.mkdir(parents=True)
    snapshot = out / "input_snapshot/TxtInOut"
    snapshot.parent.mkdir(parents=True)
    _copy_fresh_txtinout(source, snapshot)
    if _staged_input_identity(snapshot) != source_hash:
        raise ValueError("Copied source configuration differs from the frozen source")
    package_root = Path(swatplus_builder.__file__).resolve().parent
    source_digests = {
        str(path.relative_to(package_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package_root.rglob("*.py"))
    }
    manifest = {
        "policy": POLICY,
        "loaded_package_root": str(package_root),
        "package_python_source_sha256": source_digests,
        "pilot_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime_versions": {
            n: version(n) for n in ("numpy", "pandas", "torch", "botorch", "gpytorch")
        },
        "platform": platform.platform(),
        "engine_threads": 1,
        "basin": "usgs_12054000",
        "source": str(source),
        "source_input_sha256": source_hash,
        "engine_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "alignment_sha256": hashlib.sha256(alignment.read_bytes()).hexdigest(),
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "simulation_dates": ["2007-01-01", "2015-12-31"],
        "score_dates": ["2010-01-01", "2015-12-31"],
        "bounds": bounds,
        "initial_points": points,
        "seed": args.seed,
        "status": "running",
        "withheld_years_used": False,
    }
    write_json(out / "manifest.json", manifest)

    def evaluate(parameters, label):
        objective = make_real_objective(
            base_txtinout=snapshot,
            observed_series=obs,
            work_root=out / "evaluations" / label,
            telemetry_dir=out / "invocations",
            outlet_gis_id=lock["outlet_gis_id"],
            objective_outlet_policy=lock["outlet_policy"],
            binary=binary,
            threads=1,
            timeout_s=300,
            objective_sim_file=lock["sim_source_file"],
            strict_objective_file=True,
            parameter_mode="full",
            keep_workdirs=True,
            force_fresh=True,
            include_physical_gate=True,
            nyskip_years=0,
            simulation_start="2007-01-01",
            simulation_end="2015-12-31",
            score_start="2010-01-01",
            score_end="2015-12-31",
        )
        return objective(parameters)

    try:
        report = run_comparison(
            evaluate,
            bounds,
            points,
            seed=args.seed,
            gp=gp,
            checkpoint=lambda payload: write_json(out / "pilot_results.json", payload),
        )
        manifest.update(
            status=report["status"], actual_physical_calls=report["actual_physical_calls"]
        )
    except BaseException as error:
        manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        manifest["historical_source_unchanged"] = _staged_input_identity(source) == source_hash
        write_json(out / "manifest.json", manifest)
        if not manifest["historical_source_unchanged"]:
            raise RuntimeError("Historical source inputs changed during pilot")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
