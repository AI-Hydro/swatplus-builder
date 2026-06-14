"""Locked-benchmark calibration protocol.

Provides a complete, reproducible lock → calibrate → verify workflow:

1. :func:`lock_benchmark` — run two-pass outlet evaluation, persist
   a ``BenchmarkLock`` artifact under ``<out_dir>/benchmark/``.

2. :func:`calibrate_against_lock` — run real-engine DDS calibration
   against the locked alignment context and return a
   :class:`CalibrationEvidence` summary.

3. :func:`verify_calibration` — independently rerun the best parameter
   set and confirm metric improvement vs. the locked baseline.

4. :func:`build_readiness_table` — scan a directory tree for
   ``verification_summary.json`` files and produce a markdown table.

All public functions are agent-callable:  they accept / return typed models
and write self-describing JSON artifacts alongside any outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from ..errors import SwatBuilderInputError, SwatBuilderPipelineError
from ..output.eval import evaluate_run
from ..output.metadata import try_git_sha

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class BenchmarkLock(BaseModel):
    """Immutable baseline context for a single basin lock."""

    basin_id: str
    locked_at_utc: str
    alignment_sha256: str
    metrics_sha256: str
    provenance_sha256: str | None = None
    outlet_gis_id: int
    outlet_policy: str = "strict"
    outlet_scope: str = "single_channel"
    selected_outlet_gis_ids: list[int] = Field(default_factory=list)
    virtual_outlet_authority: str | None = None
    virtual_outlet_claim_authority: bool = False
    sim_source_file: str
    git_sha: str | None = None
    baseline_nse: float
    baseline_kge: float
    benchmark_dir: str


class CalibrationEvidence(BaseModel):
    """Result of a locked-benchmark calibration run."""

    basin_id: str
    calibration_hash: str | None = None
    n_evaluations: int
    best_nse: float
    best_kge: float | None = None
    best_parameters: dict[str, float] = Field(default_factory=dict)
    history_csv: str
    summary_md: str
    best_solution_json: str
    outdir: str
    # Split-sample (Klemeš) validation fields — populated only when
    # validation_period was passed to calibrate_against_lock.
    validation_period: tuple[str, str] | None = None
    validation_nse: float | None = None
    validation_kge: float | None = None
    validation_pbias: float | None = None
    validation_transfer_passed: bool | None = None
    # Multi-seed DDS ensemble fields — populated when dds_n_seeds > 1.
    ensemble_n_seeds: int | None = None
    ensemble_best_nse_per_seed: list[float] = Field(default_factory=list)
    ensemble_best_kge_per_seed: list[float] = Field(default_factory=list)
    ensemble_nse_spread: float | None = None
    ensemble_kge_spread: float | None = None


class LockedSensitivityEvidence(BaseModel):
    """Basin-specific parameter sensitivity screen run against a benchmark lock."""

    basin_id: str
    basis: str = "basin_specific"
    parameters: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)
    json_path: str
    markdown_path: str


class VerificationResult(BaseModel):
    """Result of independently re-running the best solution against the lock."""

    basin_id: str
    benchmark_nse: float
    benchmark_kge: float
    benchmark_pbias: float | None = None
    verified_nse: float
    verified_kge: float
    verified_pbias: float | None = None
    delta_nse: float
    delta_kge: float
    improved: bool
    improvement_basis: str = "none"
    fresh_outputs: bool = True
    fresh_output_policy: str = "force_fresh_real_engine_objective"
    verification_dir: str
    verification_summary_path: str


class ReadinessRow(BaseModel):
    """One row in the multi-lock readiness table."""

    basin_id: str
    lock_dir: str
    baseline_nse: float | None = None
    baseline_kge: float | None = None
    calibrated_nse: float | None = None
    calibrated_kge: float | None = None
    delta_nse: float | None = None
    delta_kge: float | None = None
    improved: bool | None = None
    verification_status: str = "unknown"


# ---------------------------------------------------------------------------
# 1. Lock benchmark
# ---------------------------------------------------------------------------


def lock_benchmark(
    txtinout_dir: Path | str,
    obs_series: pd.Series,
    out_dir: Path | str,
    *,
    basin_id: str,
    outlet_gis_id: int = 1,
    sim_source_file: str = "basin_sd_cha_day.txt",
    git_sha: str | None = None,
    virtual_outlet_policy: str = "none",
    virtual_outlet_authority: str | None = None,
) -> BenchmarkLock:
    """Run two-pass outlet evaluation and persist a locked benchmark artifact.

    Pass 1 (auto) discovers the best defensible outlet.
    Pass 2 (strict) re-scores with the pinned outlet to produce the
    authoritative baseline metrics and alignment.

    Args:
        txtinout_dir: Prepared SWAT+ TxtInOut directory.
        obs_series:   Observed daily discharge (DatetimeIndex, m3/s).
        out_dir:      Root directory for lock artifacts; ``benchmark/`` is
                      created underneath.
        basin_id:     Identifier for provenance records.
        outlet_gis_id: Requested gauge outlet channel GIS ID.
        sim_source_file: Objective sim file (``basin_sd_cha_day.txt`` or
                         ``channel_sd_day.txt``).
        git_sha:      Builder git SHA for provenance (auto-detected if None).
        virtual_outlet_policy: ``"none"`` for normal single-channel locking or
                               ``"all_terminal_sum"`` for an explicit virtual
                               outlet formed by summing all terminal channels.
        virtual_outlet_authority: Required justification/source when locking a
                                  virtual outlet.

    Returns:
        :class:`BenchmarkLock` with hashes and baseline metrics.

    Raises:
        SwatBuilderInputError: ``txtinout_dir`` or sim file missing.
        SwatBuilderPipelineError: No aligned days or metrics could not be computed.
    """
    txt = Path(txtinout_dir).expanduser().resolve()
    out = Path(out_dir).expanduser().resolve()
    bmark_dir = out / "benchmark"
    bmark_dir.mkdir(parents=True, exist_ok=True)

    sim_path = txt / sim_source_file
    if not sim_path.exists():
        for alt in ("channel_sd_day.txt", "basin_sd_cha_day.txt", "channel_day.txt"):
            cand = txt / alt
            if cand.exists():
                sim_path = cand
                sim_source_file = alt
                break
    if not sim_path.exists():
        raise SwatBuilderInputError(
            "No simulation output file found for benchmark lock.",
            txtinout_dir=str(txt),
            requested=sim_source_file,
        )

    alignment_csv = bmark_dir / "alignment.csv"
    virtual_policy = str(virtual_outlet_policy or "none").strip().lower()
    if virtual_policy not in {"none", "all_terminal_sum"}:
        raise SwatBuilderInputError(
            "Unsupported virtual outlet policy.",
            virtual_outlet_policy=virtual_outlet_policy,
        )
    if virtual_policy == "all_terminal_sum":
        authority = str(virtual_outlet_authority or "").strip()
        if not authority:
            raise SwatBuilderInputError(
                "Virtual all-terminal outlet locks require documented authority.",
                virtual_outlet_policy=virtual_policy,
                required="virtual_outlet_authority",
            )
        _, metrics, diag2 = evaluate_run(
            sim_path,
            obs_series,
            outlet_gis_id=outlet_gis_id,
            out_alignment_csv=alignment_csv,
            outlet_policy="all_terminal_sum",
            return_diagnostics=True,
        )
        diag = dict(diag2)
        pinned_outlet = int(outlet_gis_id)
        lock_outlet_policy = "all_terminal_sum"
        outlet_scope = "virtual_all_terminal"
        selected_outlet_gis_ids = [
            int(gid)
            for gid in diag2.get("selected_outlet_gis_ids", diag2.get("terminal_outlet_ids", []))
            if isinstance(gid, int)
        ]
    else:
        # Pass 1: auto to discover best outlet.
        alignment_csv_auto = bmark_dir / "alignment_auto.csv"
        _, _, diag = evaluate_run(
            sim_path,
            obs_series,
            outlet_gis_id=outlet_gis_id,
            out_alignment_csv=alignment_csv_auto,
            outlet_policy="auto",
            return_diagnostics=True,
        )
        pinned_outlet = int(diag.get("selected_outlet_gis_id", outlet_gis_id))

        # Pass 2: strict scoring on the pinned outlet.
        _, metrics, diag2 = evaluate_run(
            sim_path,
            obs_series,
            outlet_gis_id=pinned_outlet,
            out_alignment_csv=alignment_csv,
            outlet_policy="strict",
            return_diagnostics=True,
        )
        lock_outlet_policy = "strict"
        outlet_scope = "single_channel"
        selected_outlet_gis_ids = [pinned_outlet]

    baseline_nse = float(metrics.get("nse", float("nan")))
    baseline_kge = float(metrics.get("kge", float("nan")))

    # Persist metrics JSON.
    metrics_json = bmark_dir / "metrics.json"
    metrics_json.write_text(
        json.dumps({"nse": baseline_nse, "kge": baseline_kge, **metrics}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Persist outlet provenance JSON.
    provenance_json = bmark_dir / "outlet_provenance.json"
    provenance_json.write_text(
        json.dumps(
            {
                "requested_outlet_gis_id": outlet_gis_id,
                "selected_outlet_gis_id": pinned_outlet,
                "outlet_autodetected": diag.get("outlet_autodetected", False),
                "outlet_selection_reason": diag.get("outlet_selection_reason"),
                "outlet_policy_pass2": lock_outlet_policy,
                "outlet_scope": outlet_scope,
                "selected_outlet_gis_ids": selected_outlet_gis_ids,
                "virtual_outlet_policy": virtual_policy,
                "virtual_outlet_authority": virtual_outlet_authority,
                "virtual_outlet_claim_authority": virtual_policy == "all_terminal_sum",
                "sim_source_file": str(diag2.get("sim_source_file", sim_source_file)),
                "terminal_outlet_ids": diag2.get("terminal_outlet_ids", []),
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    sha_git = git_sha or try_git_sha(Path(__file__).resolve().parents[3]) or "unknown"
    lock = BenchmarkLock(
        basin_id=basin_id,
        locked_at_utc=datetime.now(timezone.utc).isoformat(),
        alignment_sha256=_sha256_file(alignment_csv) or "",
        metrics_sha256=_sha256_file(metrics_json) or "",
        provenance_sha256=_sha256_file(provenance_json),
        outlet_gis_id=pinned_outlet,
        outlet_policy=lock_outlet_policy,
        outlet_scope=outlet_scope,
        selected_outlet_gis_ids=selected_outlet_gis_ids,
        virtual_outlet_authority=virtual_outlet_authority if virtual_policy == "all_terminal_sum" else None,
        virtual_outlet_claim_authority=virtual_policy == "all_terminal_sum",
        sim_source_file=sim_source_file,
        git_sha=sha_git,
        baseline_nse=baseline_nse,
        baseline_kge=baseline_kge,
        benchmark_dir=str(bmark_dir),
    )

    lock_json = bmark_dir / "benchmark_lock.json"
    lock_json.write_text(lock.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return lock


# ---------------------------------------------------------------------------
# 2. Calibrate against lock
# ---------------------------------------------------------------------------


def calibrate_against_lock(
    lock: BenchmarkLock | Path | str,
    base_txtinout: Path | str,
    out_dir: Path | str,
    *,
    parameters: list[str] | None = None,
    n_evaluations: int = 30,
    binary: Path | str | None = None,
    timeout_s: float = 3600.0,
    parameter_mode: str = "lte",
    calibration_phases: list[dict[str, Any]] | None = None,
    search_method: str = "dds",
    dds_r: float = 0.2,
    dds_n_seeds: int = 1,
    validation_period: tuple[str, str] | None = None,
) -> CalibrationEvidence:
    """Run real-engine DDS calibration against a locked benchmark.

    Loads observed alignment from ``benchmark/alignment.csv`` to ensure
    objective scoring uses the exact same observed series as the lock.

    Args:
        lock:            :class:`BenchmarkLock` or path to ``benchmark_lock.json``.
        base_txtinout:   Source TxtInOut (fresh copy per evaluation).
        out_dir:         Root for calibration artifacts.
        parameters:      Parameter names; defaults to ``["CN2", "ALPHA_BF"]``.
        n_evaluations:   Total real-engine evaluations (budget).
        binary:          Override SWAT+ binary path.
        timeout_s:       Per-evaluation engine timeout.

    Returns:
        :class:`CalibrationEvidence` with best metrics and artifact paths.
    """
    if parameters is None:
        parameters = ["CN2", "ALPHA_BF"]

    lock = _resolve_lock(lock)
    out = Path(out_dir).expanduser().resolve()
    bmark_dir = Path(lock.benchmark_dir)
    alignment_csv = bmark_dir / "alignment.csv"
    if not alignment_csv.exists():
        raise SwatBuilderInputError(
            "Locked benchmark alignment.csv not found.",
            path=str(alignment_csv),
        )

    from .real_engine import (
        load_observed_from_alignment_csv,
        make_real_objective,
    )

    obs_series = load_observed_from_alignment_csv(alignment_csv)

    # Split-sample (Klemeš): if a validation_period is specified, withhold those
    # dates from the calibration objective so the optimizer never sees them.
    obs_train = obs_series
    obs_val: pd.Series | None = None
    if validation_period is not None:
        val_start = pd.Timestamp(validation_period[0])
        val_end = pd.Timestamp(validation_period[1])
        mask_val = (obs_series.index >= val_start) & (obs_series.index <= val_end)
        obs_val = obs_series[mask_val]
        obs_train = obs_series[~mask_val]
        if len(obs_val) < 30:
            raise SwatBuilderInputError(
                "validation_period has fewer than 30 observed days after slicing; "
                "choose a longer held-out window.",
                path=str(alignment_csv),
            )
        if len(obs_train) < 30:
            raise SwatBuilderInputError(
                "Training period has fewer than 30 observed days after excluding "
                "validation_period; choose a shorter held-out window.",
                path=str(alignment_csv),
            )

    cal_dir = out / "calibration_reports_locked"
    cal_dir.mkdir(parents=True, exist_ok=True)

    objective = make_real_objective(
        base_txtinout=base_txtinout,
        observed_series=obs_train,
        work_root=cal_dir / "objective_runs",
        outlet_gis_id=lock.outlet_gis_id,
        binary=binary,
        timeout_s=timeout_s,
        objective_sim_file=lock.sim_source_file,
        strict_objective_file=True,
        allow_outlet_autodetect=False,
        objective_outlet_policy=_objective_outlet_policy_for_lock(lock),
        parameter_mode=parameter_mode,
        keep_workdirs=False,
        include_physical_gate=str(parameter_mode).strip().lower() == "full",
    )

    # Deterministic staged diagnostic search. Each phase only opens the
    # parameters assigned to that phase while preserving the best settings
    # carried forward from earlier phases. KGE/NSE ranking is never consulted
    # until the candidate also passes the volume gate.
    from ..params import get_parameter

    evaluations: list[dict[str, Any]] = []
    best_metrics: dict[str, float] = {}
    best_params: dict[str, float] = {}

    param_bounds = {p: (get_parameter(p).range[0], get_parameter(p).range[1]) for p in parameters}
    import random

    rng = random.Random(42)
    active_phases = _diagnostic_calibration_phases(
        parameters,
        calibration_phases,
        n_evaluations=n_evaluations,
    )
    # Full-mode calibration parameters are direct TxtInOut edits, not
    # guaranteed deltas from the basin's already-built values. Preserve a true
    # no-edit baseline candidate so the volume gate cannot exclude an otherwise
    # valid locked benchmark before any perturbation is tested.
    current_params: dict[str, float] = {}
    eval_idx = 0
    phase_failure: SwatBuilderPipelineError | None = None

    for phase_index, phase in enumerate(active_phases, start=1):
        phase_parameters = [p for p in phase["parameters"] if p in parameters]
        if _phase_requires_prior_process_gate(phase):
            prior_gate_seen = _prior_process_gate_seen(evaluations)
            prior_gate_candidate = _best_prior_process_gate_candidate(
                evaluations,
                objective=str(phase["objective"]),
            )
            if prior_gate_seen and prior_gate_candidate is None:
                evaluations.append(
                    {
                        "eval_idx": eval_idx,
                        "phase": phase["phase"],
                        "phase_order": phase_index,
                        "phase_parameters": phase_parameters,
                        "phase_objective": phase["objective"],
                        "parameters": dict(current_params),
                        "metrics": {"nse": float("nan"), "kge": float("nan"), "pbias": float("nan")},
                        "volume_gate_passed": False,
                        "physical_gate_passed": False,
                        "calibration_process_gate_passed": False,
                        "status": "blocked_preceding_process_gate",
                    }
                )
                eval_idx += 1
                phase_failure = SwatBuilderPipelineError(
                    f"Phase '{phase['phase']}' requires a prior volume-valid candidate "
                    "that passed calibration process gates.",
                    phase=phase["phase"],
                    history_csv=str(cal_dir / "history.csv"),
                    n_evaluations=len(evaluations),
                    promotion_gate=(
                        "prior abs(pbias) <= 30 candidate must pass calibration process gates "
                        "before KGE/NSE finetune"
                    ),
                )
                break
            if prior_gate_candidate is not None and not _current_params_process_gate_valid(
                current_params,
                evaluations,
            ):
                current_params = dict(prior_gate_candidate["parameters"])
                best_params = dict(current_params)
                best_metrics = {
                    k: float(v)
                    for k, v in prior_gate_candidate["metrics"].items()
                    if isinstance(v, (int, float))
                }
        if not phase_parameters:
            evaluations.append(
                {
                    "eval_idx": eval_idx,
                    "phase": phase["phase"],
                    "phase_order": phase_index,
                    "phase_parameters": [],
                    "phase_objective": phase["objective"],
                    "parameters": dict(current_params),
                    "metrics": {"nse": float("nan"), "kge": float("nan"), "pbias": float("nan")},
                    "volume_gate_passed": False,
                    "status": "skipped_no_eligible_parameters",
                }
            )
            eval_idx += 1
            continue

        phase_best_score = float("-inf")
        phase_best_params: dict[str, float] | None = None
        phase_best_metrics: dict[str, float] = {}

        phase_objective = str(phase["objective"])
        phase_budget = max(1, int(phase["budget"]))

        def _evaluate_and_record(
            point: dict[str, float],
            _phase: dict[str, Any] = phase,
            _phase_index: int = phase_index,
            _phase_parameters: list[str] = phase_parameters,
        ) -> dict[str, Any]:
            """Run one real-engine evaluation and append it to the history.

            Shared by both the DDS and grid search drivers so every evaluation
            is recorded identically (gates, condition codes, eval index).
            """
            nonlocal eval_idx
            try:
                metrics = objective(point)
            except Exception as e:
                metrics = {"nse": float("nan"), "kge": float("nan"), "pbias": float("nan"), "error": str(e)}
            volume_gate_passed = _volume_gate_passed(metrics)
            physical_gate_passed = _candidate_physical_gate_passed(metrics)
            calibration_process_gate_passed = _candidate_calibration_process_gate_passed(metrics)
            physical_context = _candidate_physical_gate_context(cal_dir / "objective_runs", point)
            evaluations.append(
                {
                    "eval_idx": eval_idx,
                    "phase": _phase["phase"],
                    "phase_order": _phase_index,
                    "phase_parameters": _phase_parameters,
                    "phase_objective": _phase["objective"],
                    "parameters": dict(point),
                    "metrics": metrics,
                    "volume_gate_passed": volume_gate_passed,
                    "physical_gate_passed": physical_gate_passed,
                    "calibration_process_gate_passed": calibration_process_gate_passed,
                    "calibration_process_condition_codes": physical_context.get(
                        "calibration_process_condition_codes"
                    ),
                    "physical_gate_condition_codes": physical_context.get("condition_codes"),
                    "physical_gate_dominant_blocker": physical_context.get("dominant_blocker"),
                    "status": "evaluated",
                }
            )
            eval_idx += 1
            return metrics

        if search_method == "dds":
            phase_best_params, phase_best_metrics, phase_best_score = _dds_search(
                evaluate=_evaluate_and_record,
                score_fn=lambda m, _obj=phase_objective: _score_candidate(m, objective=_obj),
                feasible_fn=_volume_gate_passed,
                phase_parameters=phase_parameters,
                param_bounds=param_bounds,
                start_params=current_params,
                budget=phase_budget,
                rng=rng,
                r=dds_r,
            )
        else:
            points = _phase_candidate_points(
                current_params=current_params,
                phase_parameters=phase_parameters,
                param_bounds=param_bounds,
                rng=rng,
                n_evaluations=phase_budget,
            )
            for point in points:
                metrics = _evaluate_and_record(point)
                volume_gate_passed = _volume_gate_passed(metrics)
                score = _score_candidate(metrics, objective=phase_objective)
                if not volume_gate_passed or score == float("-inf"):
                    continue
                if score > phase_best_score:
                    phase_best_score = score
                    phase_best_metrics = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
                    phase_best_params = dict(point)

        if phase_best_params is None:
            gate_reason = (
                "abs(pbias) <= 30 and candidate calibration process gates pass"
                if "rank_nse_kge" in str(phase["objective"])
                else "abs(pbias) <= 30"
            )
            phase_failure = SwatBuilderPipelineError(
                f"No calibration candidate passed the promotion gates during phase '{phase['phase']}'.",
                phase=phase["phase"],
                history_csv=str(cal_dir / "history.csv"),
                n_evaluations=len(evaluations),
                promotion_gate=gate_reason,
            )
            break

        current_params = phase_best_params
        best_params = dict(phase_best_params)
        best_metrics = dict(phase_best_metrics)

    # Write history CSV.
    history_csv = cal_dir / "history.csv"
    param_names = sorted(parameters)
    with history_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["eval_idx", "phase", "phase_order", "phase_parameters", "phase_objective", "status"]
            + [f"param_{p}" for p in param_names]
            + [
                "metric_nse",
                "metric_kge",
                "metric_pbias",
                "metric_selected_terminal_fraction_of_all_terminal_flow",
                "metric_selected_terminal_nse",
                "metric_selected_terminal_kge",
                "metric_selected_terminal_pbias",
                "metric_all_terminal_nse",
                "metric_all_terminal_kge",
                "metric_all_terminal_pbias",
                "metric_all_terminal_volume_gate_passes_diagnostic",
                "volume_gate_passed",
                "physical_gate_passed",
                "calibration_process_gate_passed",
                "calibration_process_condition_codes",
                "physical_gate_condition_codes",
                "physical_gate_dominant_blocker",
            ],
        )
        writer.writeheader()
        for ev in evaluations:
            row: dict[str, object] = {
                "eval_idx": ev["eval_idx"],
                "phase": ev.get("phase"),
                "phase_order": ev.get("phase_order"),
                "phase_parameters": ",".join(ev.get("phase_parameters") or []),
                "phase_objective": ev.get("phase_objective"),
                "status": ev.get("status"),
            }
            for p in param_names:
                row[f"param_{p}"] = ev["parameters"].get(p)
            row["metric_nse"] = ev["metrics"].get("nse")
            row["metric_kge"] = ev["metrics"].get("kge")
            row["metric_pbias"] = ev["metrics"].get("pbias")
            row["metric_selected_terminal_fraction_of_all_terminal_flow"] = ev["metrics"].get(
                "selected_terminal_fraction_of_all_terminal_flow"
            )
            row["metric_selected_terminal_nse"] = ev["metrics"].get("selected_terminal_nse")
            row["metric_selected_terminal_kge"] = ev["metrics"].get("selected_terminal_kge")
            row["metric_selected_terminal_pbias"] = ev["metrics"].get("selected_terminal_pbias")
            row["metric_all_terminal_nse"] = ev["metrics"].get("all_terminal_nse")
            row["metric_all_terminal_kge"] = ev["metrics"].get("all_terminal_kge")
            row["metric_all_terminal_pbias"] = ev["metrics"].get("all_terminal_pbias")
            row["metric_all_terminal_volume_gate_passes_diagnostic"] = ev["metrics"].get(
                "all_terminal_volume_gate_passes_diagnostic"
            )
            row["volume_gate_passed"] = ev.get("volume_gate_passed")
            row["physical_gate_passed"] = ev.get("physical_gate_passed")
            row["calibration_process_gate_passed"] = ev.get("calibration_process_gate_passed")
            row["calibration_process_condition_codes"] = ",".join(
                ev.get("calibration_process_condition_codes") or []
            )
            row["physical_gate_condition_codes"] = ",".join(ev.get("physical_gate_condition_codes") or [])
            row["physical_gate_dominant_blocker"] = ev.get("physical_gate_dominant_blocker")
            writer.writerow(row)

    if phase_failure is not None:
        raise phase_failure

    # --- Multi-seed DDS refinement ensemble (C4.4) -------------------------
    # Run additional DDS passes from the primary best_params with distinct
    # random seeds. Records per-seed KGE/NSE for uncertainty quantification
    # and updates best_params if a secondary seed finds a better feasible point.
    # Secondary evals call objective() directly (not recorded in history CSV).
    import math as _math

    ensemble_nse_per_seed: list[float] = [float(best_metrics.get("nse", float("nan")))]
    ensemble_kge_per_seed: list[float] = [float(best_metrics.get("kge", float("nan")))]

    if search_method == "dds" and dds_n_seeds > 1:
        final_phase = active_phases[-1]
        final_phase_obj = str(final_phase["objective"])
        final_phase_params = [p for p in final_phase["parameters"] if p in parameters]
        final_phase_budget = max(1, int(final_phase["budget"]))

        for seed_idx in range(1, max(2, dds_n_seeds)):
            seed_rng = random.Random(42 + seed_idx * 13)
            refine_params, refine_metrics, _s = _dds_search(
                evaluate=objective,
                score_fn=lambda m, _obj=final_phase_obj: _score_candidate(m, objective=_obj),
                feasible_fn=_volume_gate_passed,
                phase_parameters=final_phase_params,
                param_bounds=param_bounds,
                start_params=best_params,
                budget=final_phase_budget,
                rng=seed_rng,
                r=dds_r,
            )
            if refine_params is not None:
                seed_nse = float(refine_metrics.get("nse", float("nan")))
                seed_kge = float(refine_metrics.get("kge", float("nan")))
                ensemble_nse_per_seed.append(seed_nse)
                ensemble_kge_per_seed.append(seed_kge)
                refine_score = _score_candidate(refine_metrics, objective=final_phase_obj)
                primary_score = _score_candidate(best_metrics, objective=final_phase_obj)
                if _math.isfinite(refine_score) and refine_score > primary_score:
                    best_params = dict(refine_params)
                    best_metrics = dict(refine_metrics)

    def _finite_std(vals: list[float]) -> float | None:
        finite = [v for v in vals if _math.isfinite(v)]
        if len(finite) < 2:
            return None
        mean = sum(finite) / len(finite)
        return _math.sqrt(sum((v - mean) ** 2 for v in finite) / len(finite))

    # --- Split-sample transfer evaluation (Klemeš 1986) -------------------
    # Run best_params against the held-out validation period.  A fresh engine
    # eval is needed because calibration ran with keep_workdirs=False (no cache).
    val_evidence: dict[str, float] = {}
    if obs_val is not None and len(obs_val) >= 30:
        try:
            val_objective = make_real_objective(
                base_txtinout=base_txtinout,
                observed_series=obs_val,
                work_root=cal_dir / "validation_eval",
                outlet_gis_id=lock.outlet_gis_id,
                binary=binary,
                timeout_s=timeout_s,
                objective_sim_file=lock.sim_source_file,
                strict_objective_file=True,
                allow_outlet_autodetect=False,
                objective_outlet_policy=_objective_outlet_policy_for_lock(lock),
                parameter_mode=parameter_mode,
                keep_workdirs=True,
            )
            val_evidence = val_objective(best_params)
        except Exception as _e:  # noqa: BLE001
            val_evidence = {
                "nse": float("nan"),
                "kge": float("nan"),
                "pbias": float("nan"),
                "error": str(_e),
            }

    best_nse_val = float(best_metrics.get("nse", float("nan")))
    best_kge_val = float(best_metrics.get("kge", float("nan")))

    # Write best solution JSON.
    best_json = cal_dir / "best_solution.json"
    best_solution_payload: dict[str, Any] = {
        "parameters": best_params,
        "metrics": best_metrics,
        "benchmark_baseline_nse": lock.baseline_nse,
        "benchmark_baseline_kge": lock.baseline_kge,
        "selection_policy": "staged_volume_baseflow_peaks_then_nse_kge",
        "volume_gate": "abs(pbias) <= 30",
        "kge_nse_finetune_gate": (
            "candidate calibration process gates must pass when available; "
            "skill-only claim gates remain final locked-rerun gates"
        ),
        "calibration_protocol": active_phases,
    }
    if validation_period is not None:
        best_solution_payload["validation_period"] = list(validation_period)
        best_solution_payload["validation_metrics"] = val_evidence
        best_solution_payload["validation_transfer_passed"] = _volume_gate_passed(val_evidence)
    if dds_n_seeds > 1:
        best_solution_payload["ensemble_n_seeds"] = dds_n_seeds
        best_solution_payload["ensemble_best_nse_per_seed"] = ensemble_nse_per_seed
        best_solution_payload["ensemble_best_kge_per_seed"] = ensemble_kge_per_seed
        best_solution_payload["ensemble_nse_spread"] = _finite_std(ensemble_nse_per_seed)
        best_solution_payload["ensemble_kge_spread"] = _finite_std(ensemble_kge_per_seed)
    best_json.write_text(json.dumps(best_solution_payload, indent=2) + "\n", encoding="utf-8")

    # Write summary markdown.
    summary_lines = [
        "# Locked-Benchmark Calibration Summary",
        "",
        f"- Basin: `{lock.basin_id}`",
        f"- Benchmark NSE/KGE: `{lock.baseline_nse:.6f}` / `{lock.baseline_kge:.6f}`",
        f"- Best calibrated NSE/KGE: `{best_nse_val:.6f}` / `{best_kge_val:.6f}`",
        f"- Delta NSE/KGE: `{best_nse_val - lock.baseline_nse:+.6f}` / `{best_kge_val - lock.baseline_kge:+.6f}`",
        f"- Evaluations: `{len(evaluations)}`",
        f"- Parameters: `{', '.join(parameters)}`",
        "- Selection policy: `staged_volume_baseflow_peaks_then_nse_kge`",
    ]
    if validation_period is not None:
        val_nse = val_evidence.get("nse", float("nan"))
        val_kge = val_evidence.get("kge", float("nan"))
        val_pbias = val_evidence.get("pbias", float("nan"))
        val_pass = _volume_gate_passed(val_evidence)
        summary_lines += [
            "",
            "## Split-Sample Validation (Klemeš 1986)",
            f"- Validation period: `{validation_period[0]}` – `{validation_period[1]}`",
            f"- Validation NSE/KGE: `{val_nse:.6f}` / `{val_kge:.6f}`",
            f"- Validation PBIAS: `{val_pbias:.2f}%`",
            f"- Transfer passed (volume gate): `{'YES' if val_pass else 'NO'}`",
        ]
    summary_md = cal_dir / "summary.md"
    summary_md.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    return CalibrationEvidence(
        basin_id=lock.basin_id,
        n_evaluations=len(evaluations),
        best_nse=best_nse_val,
        best_kge=best_kge_val,
        best_parameters=best_params,
        history_csv=str(history_csv),
        summary_md=str(summary_md),
        best_solution_json=str(best_json),
        outdir=str(cal_dir),
        validation_period=validation_period,
        validation_nse=float(val_evidence["nse"]) if val_evidence else None,
        validation_kge=float(val_evidence.get("kge", float("nan"))) if val_evidence else None,
        validation_pbias=float(val_evidence.get("pbias", float("nan"))) if val_evidence else None,
        validation_transfer_passed=_volume_gate_passed(val_evidence) if val_evidence else None,
        ensemble_n_seeds=dds_n_seeds if (search_method == "dds" and dds_n_seeds > 1) else None,
        ensemble_best_nse_per_seed=ensemble_nse_per_seed if dds_n_seeds > 1 else [],
        ensemble_best_kge_per_seed=ensemble_kge_per_seed if dds_n_seeds > 1 else [],
        ensemble_nse_spread=_finite_std(ensemble_nse_per_seed) if dds_n_seeds > 1 else None,
        ensemble_kge_spread=_finite_std(ensemble_kge_per_seed) if dds_n_seeds > 1 else None,
    )


def screen_parameters_against_lock(
    lock: BenchmarkLock | Path | str,
    base_txtinout: Path | str,
    out_dir: Path | str,
    *,
    parameters: list[str],
    binary: Path | str | None = None,
    timeout_s: float = 3600.0,
    parameter_mode: str = "full",
) -> LockedSensitivityEvidence:
    """Run a basin-specific one-at-a-time sensitivity screen against a lock.

    Each parameter perturbation uses the same fresh real-engine objective path
    as calibration candidates, so this artifact can govern research-grade
    calibration eligibility without relying on static/global activity labels.
    """
    lock = _resolve_lock(lock)
    out = Path(out_dir).expanduser().resolve()
    screen_dir = out / "sensitivity_screen_locked"
    screen_dir.mkdir(parents=True, exist_ok=True)

    bmark_dir = Path(lock.benchmark_dir)
    alignment_csv = bmark_dir / "alignment.csv"
    if not alignment_csv.exists():
        raise SwatBuilderInputError(
            "Locked benchmark alignment.csv not found.",
            path=str(alignment_csv),
        )

    from ..params import get_parameter
    from .real_engine import load_observed_from_alignment_csv, make_real_objective

    obs_series = load_observed_from_alignment_csv(alignment_csv)
    objective = make_real_objective(
        base_txtinout=base_txtinout,
        observed_series=obs_series,
        work_root=screen_dir / "objective_runs",
        outlet_gis_id=lock.outlet_gis_id,
        binary=binary,
        timeout_s=timeout_s,
        objective_sim_file=lock.sim_source_file,
        strict_objective_file=True,
        allow_outlet_autodetect=False,
        objective_outlet_policy=_objective_outlet_policy_for_lock(lock),
        parameter_mode=parameter_mode,
        keep_workdirs=False,
    )

    defaults = {name: get_parameter(name).default for name in parameters}
    baseline_metrics = objective(defaults)
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for name in parameters:
        spec = get_parameter(name)
        lo, hi = spec.range
        default = float(spec.default)
        baseline_score = _score_candidate(
            baseline_metrics,
            objective="maintain_volume_gate_then_rank_nse_kge",
        )
        bound_values: list[tuple[str, float]] = []
        if abs(default - lo) > 1e-12:
            bound_values.append(("lower", float(lo)))
        if abs(default - hi) > 1e-12:
            bound_values.append(("upper", float(hi)))
        if not bound_values:
            bound_values.append(("default", default))
        try:
            bound_results: list[dict[str, Any]] = []
            for bound, perturbed_value in bound_values:
                point = dict(defaults)
                point[name] = perturbed_value
                metrics = objective(point)
                metric_nse = _optional_float(metrics.get("nse"))
                base_nse = _optional_float(baseline_metrics.get("nse"))
                metric_kge = _optional_float(metrics.get("kge"))
                base_kge = _optional_float(baseline_metrics.get("kge"))
                nse_effect = None if metric_nse is None or base_nse is None else metric_nse - base_nse
                kge_effect = None if metric_kge is None or base_kge is None else metric_kge - base_kge
                score = _score_candidate(
                    metrics,
                    objective="maintain_volume_gate_then_rank_nse_kge",
                )
                score_delta = (
                    score - baseline_score
                    if _is_finite_number(score) and _is_finite_number(baseline_score)
                    else None
                )
                bound_results.append(
                    {
                        "bound": bound,
                        "value": perturbed_value,
                        "metrics": metrics,
                        "delta_nse": nse_effect,
                        "delta_kge": kge_effect,
                        "score": score,
                        "score_delta": score_delta,
                    }
                )
            effect_candidates = [
                abs(float(value))
                for result in bound_results
                for value in (result.get("delta_nse"), result.get("delta_kge"))
                if isinstance(value, (int, float))
            ]
            effect_size = max(effect_candidates) if effect_candidates else None
            activity = _classify_sensitivity_effect(effect_size, tested=True)
            max_effect = max(
                bound_results,
                key=lambda result: max(
                    [
                        abs(float(value))
                        for value in (result.get("delta_nse"), result.get("delta_kge"))
                        if isinstance(value, (int, float))
                    ]
                    or [0.0]
                ),
            )
            best_score = max(
                bound_results,
                key=lambda result: (
                    float(result.get("score_delta"))
                    if isinstance(result.get("score_delta"), (int, float))
                    else float("-inf")
                ),
            )
            rows.append(
                {
                    "parameter": name,
                    "activity_class": activity,
                    "evidence": {
                        "basis": "fresh_locked_objective_two_bound_perturbation",
                        "baseline_parameters": defaults,
                        "perturbed_value": max_effect.get("value"),
                        "perturbed_bound": max_effect.get("bound"),
                        "baseline_metrics": baseline_metrics,
                        "perturbed_metrics": max_effect.get("metrics"),
                        "delta_nse": max_effect.get("delta_nse"),
                        "delta_kge": max_effect.get("delta_kge"),
                        "effect_size": effect_size,
                        "bound_results": bound_results,
                        "best_score_bound": best_score.get("bound"),
                        "best_score_value": best_score.get("value"),
                        "best_score_metrics": best_score.get("metrics"),
                        "best_score_delta": best_score.get("score_delta"),
                        "tested": True,
                    },
                }
            )
        except Exception as exc:
            warnings.append(f"{name}: {exc}")
            rows.append(
                {
                    "parameter": name,
                    "activity_class": "not_tested",
                    "evidence": {
                        "basis": "fresh_locked_objective_two_bound_perturbation",
                        "baseline_parameters": defaults,
                        "tested_bounds": bound_values,
                        "tested": False,
                        "error": str(exc),
                    },
                }
            )

    payload = {
        "basin_id": lock.basin_id,
        "basis": "basin_specific",
        "selection_policy": "one_at_a_time_default_to_lower_and_upper_bound_locked_objective",
        "parameters": rows,
        "warnings": warnings,
    }
    json_path = screen_dir / "sensitivity_screen.json"
    md_path = screen_dir / "sensitivity_screen.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Locked Sensitivity Screen",
        "",
        f"- Basin: `{lock.basin_id}`",
        "- Basis: `basin_specific`",
        "",
        "| Parameter | Activity | Effect size |",
        "|---|---|---:|",
    ]
    for row in rows:
        effect = _optional_float(_lookup_dict(row, ("evidence", "effect_size")))
        effect_text = "n/a" if effect is None else f"{effect:.6f}"
        lines.append(f"| `{row['parameter']}` | `{row['activity_class']}` | `{effect_text}` |")
    if warnings:
        lines += ["", "## Warnings"] + [f"- {w}" for w in warnings]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return LockedSensitivityEvidence(
        basin_id=lock.basin_id,
        parameters=rows,
        warnings=warnings,
        json_path=str(json_path),
        markdown_path=str(md_path),
    )


def _volume_gate_passed(metrics: dict[str, Any]) -> bool:
    try:
        pbias = float(metrics["pbias"])
    except Exception:
        return False
    import math

    return math.isfinite(pbias) and abs(pbias) <= 30.0


def _classify_sensitivity_effect(effect_size: float | None, *, tested: bool) -> str:
    if not tested or effect_size is None:
        return "not_tested"
    v = abs(float(effect_size))
    if v < 1e-9:
        return "dead"
    if v < 0.01:
        return "weak"
    return "active"


def _is_finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)):
        return False
    import math

    return math.isfinite(float(value))


def _diagnostic_calibration_phases(
    parameters: list[str],
    calibration_phases: list[dict[str, Any]] | None,
    *,
    n_evaluations: int,
) -> list[dict[str, Any]]:
    if calibration_phases is None:
        calibration_phases = [
            {
                "phase": "volume",
                "parameters": ["PET_CO", "ESCO", "EPCO", "CN3_SWF", "CN2", "LATQ_CO", "PERCO"],
                "objective": "minimize_abs_pbias_then_kge_nse",
            },
            {
                "phase": "baseflow_subsurface",
                "parameters": ["LAT_TTIME", "LATQ_CO", "PERCO", "ALPHA_BF", "RCHG_DP"],
                "objective": "maintain_volume_gate_then_improve_bfi_and_kge",
            },
            {
                "phase": "peaks_timing",
                "parameters": ["SURLAG", "CH_N2", "CH_K2", "SFTMP", "SMTMP"],
                "objective": "maintain_volume_gate_then_improve_kge_nse",
            },
            {
                "phase": "kge_nse_finetune",
                "parameters": list(parameters),
                "objective": "maintain_volume_gate_then_rank_nse_kge",
            },
        ]

    total_budget = max(1, int(n_evaluations))
    explicit_budgets = sum(int(p.get("budget", 0) or 0) for p in calibration_phases)
    remaining_budget = max(0, total_budget - explicit_budgets)
    unset_count = sum(1 for p in calibration_phases if not p.get("budget"))
    default_budget = max(1, remaining_budget // max(unset_count, 1))
    normalized: list[dict[str, Any]] = []
    for idx, phase in enumerate(calibration_phases, start=1):
        phase_parameters = [str(p) for p in phase.get("parameters", []) if str(p) in parameters]
        objective = str(phase.get("objective") or "maintain_volume_gate_then_rank_nse_kge")
        normalized.append(
            {
                "order": idx,
                "phase": str(phase.get("phase") or f"phase_{idx}"),
                "parameters": phase_parameters,
                "objective": objective,
                "budget": int(phase.get("budget") or default_budget),
                "gate": (
                    "abs(pbias) <= 30 and candidate calibration process gates pass before KGE/NSE promotion"
                    if "rank_nse_kge" in objective
                    else "abs(pbias) <= 30 before candidate promotion"
                ),
            }
        )
    return normalized


def _reflect_at_bounds(value: float, lo: float, hi: float) -> float:
    """Fold ``value`` back into ``[lo, hi]`` using DDS boundary reflection.

    Tolson & Shoemaker (2007): when a perturbed value falls outside the
    feasible range it is reflected back across the violated bound; if the
    reflection overshoots the opposite bound the value is set to that bound.
    """
    if hi <= lo:
        return lo
    if value < lo:
        reflected = lo + (lo - value)
        return hi if reflected > hi else reflected
    if value > hi:
        reflected = hi - (value - hi)
        return lo if reflected < lo else reflected
    return value


def _dds_propose(
    best_params: dict[str, float],
    *,
    phase_parameters: list[str],
    param_bounds: dict[str, tuple[float, float]],
    iteration: int,
    n_iterations: int,
    rng: Any,
    r: float = 0.2,
) -> dict[str, float]:
    """Propose one Dynamically Dimensioned Search candidate.

    Implements the neighbourhood operator of Tolson & Shoemaker (2007):

    * Each decision variable is selected for perturbation with probability
      ``P(i) = 1 - ln(i)/ln(m)`` which decays as the search progresses, so
      early iterations perturb many dimensions (exploration) and late
      iterations perturb few (exploitation). At least one variable is always
      perturbed.
    * Each selected variable receives a reflected Gaussian step with standard
      deviation ``r * (hi - lo)``.

    The candidate is built by copying ``best_params`` (so non-phase parameters
    carried forward from earlier phases are preserved) and perturbing only the
    selected phase parameters.
    """
    import math

    m = max(int(n_iterations), 1)
    i = max(int(iteration), 1)
    if m > 1:
        p_include = 1.0 - (math.log(i) / math.log(m))
    else:
        p_include = 1.0
    p_include = min(1.0, max(0.0, p_include))

    selected = [j for j in phase_parameters if rng.random() < p_include]
    if not selected and phase_parameters:
        selected = [rng.choice(phase_parameters)]

    candidate = dict(best_params)
    for name in selected:
        lo, hi = param_bounds[name]
        current = best_params.get(name, (lo + hi) / 2.0)
        step = r * (hi - lo) * rng.gauss(0.0, 1.0)
        candidate[name] = _reflect_at_bounds(current + step, lo, hi)
    return candidate


def _dds_search(
    *,
    evaluate: Any,
    score_fn: Any,
    feasible_fn: Any,
    phase_parameters: list[str],
    param_bounds: dict[str, tuple[float, float]],
    start_params: dict[str, float],
    budget: int,
    rng: Any,
    r: float = 0.2,
) -> tuple[dict[str, float] | None, dict[str, float], float]:
    """Run DDS over ``phase_parameters``, seeded from ``start_params``.

    ``evaluate(point) -> metrics`` runs (and records) one real-engine
    evaluation. ``score_fn(metrics) -> float`` ranks candidates;
    ``feasible_fn(metrics) -> bool`` is the volume gate.

    The DDS walk perturbs from the best point by a *walk score* that ranks any
    feasible candidate above any infeasible one, while still preferring lower
    ``|pbias|`` among infeasible candidates so the search gravitates toward the
    feasible region before optimising skill within it. Only feasible candidates
    (volume gate passed) are eligible to be returned — this preserves the
    volume-gate-first governance of the staged search.

    Returns ``(best_feasible_params, best_feasible_metrics, best_feasible_score)``
    or ``(None, {}, -inf)`` when no feasible candidate is found.
    """
    import math

    def _walk_score(metrics: dict[str, Any]) -> float:
        base = score_fn(metrics)
        if feasible_fn(metrics):
            # Any volume-feasible point ranks above any infeasible one. A
            # feasible point whose skill score is non-finite (e.g. a process
            # gate failed) still beats the infeasible region (floor -500).
            return base if math.isfinite(base) else -500.0
        # Infeasible: ranked below all feasible points, but prefer lower
        # |pbias| so the walk gravitates toward the feasible region.
        pbias = metrics.get("pbias")
        if isinstance(pbias, (int, float)) and math.isfinite(float(pbias)):
            return -abs(float(pbias)) / 30.0 - 1000.0
        return -1e6

    best_feasible_params: dict[str, float] | None = None
    best_feasible_metrics: dict[str, float] = {}
    best_feasible_score = float("-inf")

    # Seed evaluation: the carried-forward baseline (no perturbation).
    seed_metrics = evaluate(dict(start_params))
    walk_best_point = dict(start_params)
    walk_best_score = _walk_score(seed_metrics)
    if feasible_fn(seed_metrics):
        s = score_fn(seed_metrics)
        if math.isfinite(s):
            best_feasible_params = dict(start_params)
            best_feasible_metrics = {
                k: float(v) for k, v in seed_metrics.items() if isinstance(v, (int, float))
            }
            best_feasible_score = s

    for i in range(1, max(int(budget), 1) + 1):
        candidate = _dds_propose(
            walk_best_point,
            phase_parameters=phase_parameters,
            param_bounds=param_bounds,
            iteration=i,
            n_iterations=budget,
            rng=rng,
            r=r,
        )
        metrics = evaluate(candidate)
        ws = _walk_score(metrics)
        if ws > walk_best_score:
            walk_best_score = ws
            walk_best_point = dict(candidate)
        if feasible_fn(metrics):
            s = score_fn(metrics)
            if math.isfinite(s) and s > best_feasible_score:
                best_feasible_score = s
                best_feasible_metrics = {
                    k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))
                }
                best_feasible_params = dict(candidate)

    return best_feasible_params, best_feasible_metrics, best_feasible_score


def _phase_candidate_points(
    *,
    current_params: dict[str, float],
    phase_parameters: list[str],
    param_bounds: dict[str, tuple[float, float]],
    rng: Any,
    n_evaluations: int,
) -> list[dict[str, float]]:
    points: list[dict[str, float]] = [dict(current_params)]
    n_grid = max(5, min(7, n_evaluations // max(len(phase_parameters), 1)))
    for pname in phase_parameters:
        lo, hi = param_bounds[pname]
        for i in range(n_grid):
            val = lo + (hi - lo) * i / max(n_grid - 1, 1)
            point = dict(current_params)
            point[pname] = val
            points.append(point)

    deterministic_floor = 1 + 5 * len(phase_parameters)
    target_count = max(n_evaluations, deterministic_floor) + max(0, n_evaluations)
    while len(points) < target_count:
        point = dict(current_params)
        for pname in phase_parameters:
            point[pname] = rng.uniform(*param_bounds[pname])
        points.append(point)
    # The nominal phase budget is a floor, not permission to skip deterministic
    # one-at-a-time grid probes. When a wider basin-specific screen opens more
    # controls, each retained control still needs a dense one-at-a-time grid
    # before random candidates are considered.
    return points[:target_count]


def _score_candidate(metrics: dict[str, Any], *, objective: str) -> float:
    import math

    try:
        nse = float(metrics.get("nse", float("nan")))
        kge = float(metrics.get("kge", float("nan")))
        log_kge_val = float(metrics.get("log_kge", float("nan")))
        pbias = float(metrics.get("pbias", float("nan")))
    except Exception:
        return float("-inf")

    if not math.isfinite(pbias):
        return float("-inf")
    if "rank_nse_kge" in objective:
        process_gate = _candidate_calibration_process_gate_passed(metrics)
        if process_gate is None:
            process_gate = _candidate_physical_gate_passed(metrics)
        if process_gate is False:
            return float("-inf")
    nse_term = nse if math.isfinite(nse) else -10.0
    kge_term = kge if math.isfinite(kge) else -10.0
    # log_kge is a bonus if available; falls back to 0 (neutral) if not recorded
    # so the objective remains valid for engine runs that pre-date log_kge.
    log_kge_term = log_kge_val if math.isfinite(log_kge_val) else 0.0
    volume_term = -abs(pbias) / 30.0
    if "rank_nse_kge" in objective:
        # Blend raw KGE with log-flow KGE (Pushpalatha et al. 2012): equal
        # weight on peak-flow and recession-limb fit.  NSE has reduced weight
        # since raw NSE is dominated by flood peaks (already captured in KGE).
        combined_kge = 0.6 * kge_term + 0.4 * log_kge_term
        if nse_term >= 0.0:
            return 0.5 * combined_kge + 0.2 * nse_term + 0.005 * volume_term
        return nse_term + 0.1 * combined_kge + 0.005 * volume_term
    if "pbias" in objective or "volume" in objective:
        preferred_volume_bonus = 1.0 if abs(pbias) <= 15.0 else 0.0
        return preferred_volume_bonus + 0.5 * kge_term + 0.2 * nse_term + 0.01 * volume_term
    return nse_term + 0.1 * kge_term + 0.05 * volume_term


def _candidate_physical_gate_passed(metrics: dict[str, Any]) -> bool | None:
    if "physical_gate_passed" not in metrics:
        return None
    try:
        return bool(int(float(metrics["physical_gate_passed"])))
    except Exception:
        return False


def _candidate_calibration_process_gate_passed(metrics: dict[str, Any]) -> bool | None:
    if "calibration_process_gate_passed" not in metrics:
        return None
    try:
        return bool(int(float(metrics["calibration_process_gate_passed"])))
    except Exception:
        return False


def _phase_requires_prior_process_gate(phase: dict[str, Any]) -> bool:
    phase_name = str(phase.get("phase") or "")
    objective = str(phase.get("objective") or "")
    return phase_name == "kge_nse_finetune" or "rank_nse_kge" in objective


def _evaluation_process_gate_state(evaluation: dict[str, Any]) -> bool | None:
    value = evaluation.get("calibration_process_gate_passed")
    if value is None:
        value = evaluation.get("physical_gate_passed")
    if value is None:
        return None
    try:
        return bool(int(float(value)))
    except Exception:
        return False


def _prior_process_gate_seen(evaluations: list[dict[str, Any]]) -> bool:
    return any(
        ev.get("status") == "evaluated" and _evaluation_process_gate_state(ev) is not None
        for ev in evaluations
    )


def _best_prior_process_gate_candidate(
    evaluations: list[dict[str, Any]],
    *,
    objective: str,
) -> dict[str, Any] | None:
    candidates = [
        ev
        for ev in evaluations
        if ev.get("status") == "evaluated"
        and ev.get("volume_gate_passed") is True
        and _evaluation_process_gate_state(ev) is True
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda ev: _score_candidate(ev.get("metrics") or {}, objective=objective),
    )


def _current_params_process_gate_valid(
    current_params: dict[str, float],
    evaluations: list[dict[str, Any]],
) -> bool:
    return any(
        ev.get("status") == "evaluated"
        and ev.get("volume_gate_passed") is True
        and _evaluation_process_gate_state(ev) is True
        and ev.get("parameters") == current_params
        for ev in evaluations
    )


def _candidate_physical_gate_context(objective_runs_dir: Path, params: dict[str, float]) -> dict[str, Any]:
    try:
        from .real_engine import params_hash

        trace = objective_runs_dir / f"{params_hash(params)}_objective_trace.json"
        if not trace.is_file():
            return {}
        payload = json.loads(trace.read_text(encoding="utf-8"))
    except Exception:
        return {}
    gate = payload.get("candidate_physical_gate")
    if not isinstance(gate, dict):
        return {}
    codes = gate.get("condition_codes")
    process_codes = gate.get("calibration_process_condition_codes")
    return {
        "condition_codes": [str(code) for code in codes] if isinstance(codes, list) else [],
        "calibration_process_condition_codes": (
            [str(code) for code in process_codes] if isinstance(process_codes, list) else []
        ),
        "dominant_blocker": gate.get("dominant_blocker"),
    }


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    import math

    return result if math.isfinite(result) else None


def _lookup_dict(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _benchmark_metric(lock: BenchmarkLock, name: str) -> float | None:
    metrics_path = Path(lock.benchmark_dir) / "metrics.json"
    if not metrics_path.exists():
        return None
    try:
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _optional_float(data.get(name))


# ---------------------------------------------------------------------------
# 3. Verify calibration against lock
# ---------------------------------------------------------------------------


def verify_calibration(
    lock: BenchmarkLock | Path | str,
    best_solution_json: Path | str,
    base_txtinout: Path | str,
    out_dir: Path | str,
    *,
    binary: Path | str | None = None,
    timeout_s: float = 3600.0,
    parameter_mode: str = "lte",
) -> VerificationResult:
    """Independently re-run the best solution and confirm metric improvement.

    Args:
        lock:               :class:`BenchmarkLock` or path to ``benchmark_lock.json``.
        best_solution_json: Path to ``best_solution.json`` from :func:`calibrate_against_lock`.
        base_txtinout:      Source TxtInOut (fresh copy per rerun).
        out_dir:            Root for verification artifacts.
        binary:             Override SWAT+ binary path.
        timeout_s:          Engine timeout for this single rerun.

    Returns:
        :class:`VerificationResult` with deltas and improvement flag.
    """
    lock = _resolve_lock(lock)
    out = Path(out_dir).expanduser().resolve()
    verify_dir = out / "verification_real_objective"
    verify_dir.mkdir(parents=True, exist_ok=True)

    best_data = json.loads(Path(best_solution_json).read_text(encoding="utf-8"))
    best_params: dict[str, float] = {
        k: float(v) for k, v in best_data.get("parameters", {}).items()
    }

    bmark_dir = Path(lock.benchmark_dir)
    alignment_csv = bmark_dir / "alignment.csv"
    from .real_engine import load_observed_from_alignment_csv, make_real_objective

    obs_series = load_observed_from_alignment_csv(alignment_csv)
    objective = make_real_objective(
        base_txtinout=base_txtinout,
        observed_series=obs_series,
        work_root=verify_dir,
        outlet_gis_id=lock.outlet_gis_id,
        binary=binary,
        timeout_s=timeout_s,
        objective_sim_file=lock.sim_source_file,
        strict_objective_file=True,
        allow_outlet_autodetect=False,
        objective_outlet_policy=_objective_outlet_policy_for_lock(lock),
        parameter_mode=parameter_mode,
        keep_workdirs=True,
        force_fresh=True,
    )

    verified_metrics = objective(best_params)
    verified_nse = float(verified_metrics.get("nse", float("nan")))
    verified_kge = float(verified_metrics.get("kge", float("nan")))
    verified_pbias = _optional_float(verified_metrics.get("pbias"))
    benchmark_pbias = _benchmark_metric(lock, "pbias")

    delta_nse = verified_nse - lock.baseline_nse
    delta_kge = verified_kge - lock.baseline_kge
    improvement_basis = _improvement_basis(delta_nse=delta_nse, delta_kge=delta_kge)

    result = VerificationResult(
        basin_id=lock.basin_id,
        benchmark_nse=lock.baseline_nse,
        benchmark_kge=lock.baseline_kge,
        benchmark_pbias=benchmark_pbias,
        verified_nse=verified_nse,
        verified_kge=verified_kge,
        verified_pbias=verified_pbias,
        delta_nse=delta_nse,
        delta_kge=delta_kge,
        improved=improvement_basis != "none",
        improvement_basis=improvement_basis,
        verification_dir=str(verify_dir),
        verification_summary_path=str(out / "verification_summary.json"),
    )

    comparison_csv = out / "comparison_metrics.csv"
    with comparison_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "benchmark", "calibrated", "delta"])
        writer.writeheader()
        writer.writerow({"metric": "nse", "benchmark": lock.baseline_nse, "calibrated": verified_nse, "delta": delta_nse})
        writer.writerow({"metric": "kge", "benchmark": lock.baseline_kge, "calibrated": verified_kge, "delta": delta_kge})
        if benchmark_pbias is not None or verified_pbias is not None:
            writer.writerow({
                "metric": "pbias",
                "benchmark": benchmark_pbias,
                "calibrated": verified_pbias,
                "delta": None if benchmark_pbias is None or verified_pbias is None else verified_pbias - benchmark_pbias,
            })

    report_md = out / "CALIBRATION_VERIFICATION.md"
    status = "IMPROVED" if result.improved else "NO IMPROVEMENT"
    report_md.write_text(
        "\n".join(
            [
                "# Calibration Verification Report",
                "",
                f"- Basin: `{lock.basin_id}`",
                f"- Status: **{status}**",
                f"- Improvement basis: `{result.improvement_basis}`",
                "",
                "| Metric | Benchmark | Calibrated | Delta |",
                "| --- | ---: | ---: | ---: |",
                f"| NSE | `{lock.baseline_nse:.6f}` | `{verified_nse:.6f}` | `{delta_nse:+.6f}` |",
                f"| KGE | `{lock.baseline_kge:.6f}` | `{verified_kge:.6f}` | `{delta_kge:+.6f}` |",
            ]
        ) + "\n",
        encoding="utf-8",
    )

    summary_path = Path(result.verification_summary_path)
    summary_path.write_text(
        json.dumps(result.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )

    return result


# ---------------------------------------------------------------------------
# 4. Readiness table
# ---------------------------------------------------------------------------


def build_readiness_table(
    locks_root: Path | str,
    *,
    out_md: Path | str | None = None,
) -> list[ReadinessRow]:
    """Scan ``locks_root`` for verification artifacts and build a readiness table.

    Looks for ``verification_summary.json`` under any subdirectory.
    Falls back to ``benchmark/benchmark_lock.json`` for basins with no
    verification yet.

    Args:
        locks_root: Root directory to scan.
        out_md:     If provided, writes the table as a markdown file.

    Returns:
        List of :class:`ReadinessRow` sorted by basin_id.
    """
    root = Path(locks_root).expanduser().resolve()
    rows: list[ReadinessRow] = []

    # Find verification_summary.json files.
    verified: dict[str, VerificationResult] = {}
    for vsf in root.rglob("verification_summary.json"):
        try:
            data = json.loads(vsf.read_text(encoding="utf-8"))
            vr = VerificationResult.model_validate(data)
            verified[vr.basin_id] = vr
        except Exception:
            pass

    # Find benchmark_lock.json files.
    locks: dict[str, BenchmarkLock] = {}
    for lf in root.rglob("benchmark_lock.json"):
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            bl = BenchmarkLock.model_validate(data)
            locks[bl.basin_id] = bl
        except Exception:
            pass

    all_basins = set(verified) | set(locks)
    for basin in sorted(all_basins):
        lock = locks.get(basin)
        vr = verified.get(basin)
        lock_dir = str(Path(lock.benchmark_dir).parent) if lock else "unknown"

        row = ReadinessRow(
            basin_id=basin,
            lock_dir=lock_dir,
            baseline_nse=lock.baseline_nse if lock else None,
            baseline_kge=lock.baseline_kge if lock else None,
            calibrated_nse=vr.verified_nse if vr else None,
            calibrated_kge=vr.verified_kge if vr else None,
            delta_nse=vr.delta_nse if vr else None,
            delta_kge=vr.delta_kge if vr else None,
            improved=vr.improved if vr else None,
            verification_status="verified_improved" if (vr and vr.improved)
            else "verified_no_improvement" if (vr and not vr.improved)
            else "locked_no_verification" if lock
            else "unknown",
        )
        rows.append(row)

    if out_md is not None:
        _write_readiness_markdown(Path(out_md), rows)

    return rows


def _write_readiness_markdown(path: Path, rows: list[ReadinessRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Locked-Benchmark Readiness Table",
        "",
        "| Basin | Baseline NSE | Baseline KGE | Calibrated NSE | Calibrated KGE | ΔNSE | ΔKGE | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    def _fmt(v: float | None, fmt: str = ".4f") -> str:
        return f"`{v:{fmt}}`" if v is not None and v == v else "`n/a`"

    def _fmt_delta(v: float | None) -> str:
        return f"`{v:+.4f}`" if v is not None and v == v else "`n/a`"

    for r in rows:
        status_emoji = {
            "verified_improved": "PASS",
            "verified_no_improvement": "FAIL",
            "locked_no_verification": "PENDING",
            "unknown": "UNKNOWN",
        }.get(r.verification_status, r.verification_status)
        lines.append(
            f"| `{r.basin_id}` | {_fmt(r.baseline_nse)} | {_fmt(r.baseline_kge)} "
            f"| {_fmt(r.calibrated_nse)} | {_fmt(r.calibrated_kge)} "
            f"| {_fmt_delta(r.delta_nse)} | {_fmt_delta(r.delta_kge)} | {status_emoji} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _improvement_basis(*, delta_nse: float, delta_kge: float) -> str:
    import math

    nse_improved = math.isfinite(delta_nse) and delta_nse > 0.0
    kge_improved = math.isfinite(delta_kge) and delta_kge > 0.0
    if nse_improved and kge_improved:
        return "nse_and_kge"
    if nse_improved:
        return "nse"
    if kge_improved:
        return "kge"
    return "none"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_lock(lock: BenchmarkLock | Path | str) -> BenchmarkLock:
    if isinstance(lock, BenchmarkLock):
        return lock
    p = Path(lock).expanduser().resolve()
    if p.is_dir():
        p = p / "benchmark_lock.json"
    if not p.exists():
        raise SwatBuilderInputError("benchmark_lock.json not found", path=str(p))
    return BenchmarkLock.model_validate(json.loads(p.read_text(encoding="utf-8")))


def _objective_outlet_policy_for_lock(lock: BenchmarkLock) -> str:
    if lock.outlet_scope == "single_channel":
        return "strict"
    if (
        lock.outlet_scope == "virtual_all_terminal"
        and lock.outlet_policy == "all_terminal_sum"
        and lock.virtual_outlet_claim_authority
        and lock.virtual_outlet_authority
    ):
        return "all_terminal_sum"
    raise SwatBuilderInputError(
        "Unsupported or unauthoritative benchmark outlet scope for locked objective scoring.",
        outlet_scope=lock.outlet_scope,
        outlet_policy=lock.outlet_policy,
        virtual_outlet_claim_authority=lock.virtual_outlet_claim_authority,
    )


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
