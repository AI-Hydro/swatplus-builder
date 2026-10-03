"""Real engine-backed calibration objective helpers."""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import tempfile
import threading
import time
import weakref
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from .. import __version__ as _builder_version
from ..output.eval import evaluate_run
from ..run import run as run_swat
from .evaluation_budget import STAGES, EvaluationBudget
from .policy_engine import ExactOutputPolicyAdapter, calibration_process_proxy

_OBJECTIVE_LOCKS_GUARD = threading.Lock()
_OBJECTIVE_LOCKS: weakref.WeakValueDictionary[str, Any] = weakref.WeakValueDictionary()


def _objective_lock(identity: str) -> Any:
    """Coordinate identical work paths across objective instances in this process."""
    with _OBJECTIVE_LOCKS_GUARD:
        lock = _OBJECTIVE_LOCKS.get(identity)
        if lock is None:
            lock = threading.Lock()
            _OBJECTIVE_LOCKS[identity] = lock
        return lock


@contextmanager
def _stage_duration(record: dict[str, Any], stage: str):
    started = time.monotonic()
    try:
        yield
    finally:
        record["stage_seconds"][stage] = time.monotonic() - started


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        pending.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def _finite_budget_metadata(value: Any) -> Any:
    """Keep invalid diagnostic values explicit while satisfying finite JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {str(k): _finite_budget_metadata(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_budget_metadata(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


RealObjective = Callable[[dict[str, float]], dict[str, Any]]


def make_real_objective(
    *,
    base_txtinout: Path | str,
    observed_series: pd.Series,
    work_root: Path | str,
    outlet_gis_id: int = 1,
    binary: Path | str | None = None,
    threads: int = 1,
    timeout_s: float = 3600.0,
    objective_sim_file: str = "basin_sd_cha_day.txt",
    strict_objective_file: bool = True,
    allow_outlet_autodetect: bool = False,
    objective_outlet_policy: str | None = None,
    parameter_mode: str = "lte",
    keep_workdirs: bool = True,
    force_fresh: bool = False,
    include_physical_gate: bool = False,
    nyskip_years: int = 2,
    simulation_start: str | date | None = None,
    simulation_end: str | date | None = None,
    score_start: str | date | None = None,
    score_end: str | date | None = None,
    reuse_compact_traces: bool = False,
    trace_context_sha256: str | None = None,
    telemetry_dir: Path | str | None = None,
    objective_policy: ExactOutputPolicyAdapter | None = None,
    evaluation_budget: EvaluationBudget | None = None,
    budget_stage: str = "search",
) -> RealObjective:
    """Build an objective function that runs SWAT+ per parameter vector.

    ``force_fresh`` is for audit-authoritative reruns that must not reuse a
    hashed objective workdir even when the cache marker looks compatible.
    ``nyskip_years`` strips the first N years from the observed series before
    scoring to exclude the model warm-up / spin-up period from metric
    calculation (Klemeš 1986, Abbaspour 2015).

    ``telemetry_dir`` optionally retains one atomic JSON record per call,
    including cache hits and failures. Engine timing includes receipt generation;
    this is not a solver-only profile. Identical cache paths are serialized
    within this Python process; no cross-process locking is provided. Inputs
    are sealed when the objective is constructed and must remain immutable.
    An optional calendar-bound ``objective_policy`` scores the actual aligned
    training output and verifies its source receipt. It returns explicit
    policy_utility/status/feasible/evidence fields; undefined scores have no
    utility. Its frozen observations/calendar must match the observations after
    score-window and warm-up trimming; mismatches fail during construction.
    Compact trace reuse is unsupported with a policy. A shared optional
    ``evaluation_budget`` charges requests before cache/engine work and retains
    invalid policy results as failed attempts. Final reruns still require
    ``force_fresh=True`` and their explicit reserved budget stage.
    ``engine_invoked`` records a call to the engine wrapper, including calls
    failing before a subprocess starts; it is not a process-launch receipt.
    """
    if objective_policy is not None and reuse_compact_traces:
        raise ValueError("Policy objectives require actual aligned outputs; compact trace reuse is unsupported.")
    if objective_policy is not None and not isinstance(objective_policy, ExactOutputPolicyAdapter):
        raise TypeError("objective_policy must be a calendar-bound ExactOutputPolicyAdapter.")
    if evaluation_budget is not None and (not isinstance(budget_stage, str) or budget_stage not in STAGES):
        raise ValueError(f"Unknown budget stage: {budget_stage!r}")
    base = Path(base_txtinout).expanduser().resolve()
    root = Path(work_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    obs = observed_series.copy()
    score_start_date = _coerce_date(score_start)
    score_end_date = _coerce_date(score_end)
    if score_start_date and score_end_date and score_start_date > score_end_date:
        raise ValueError("score_start must be on or before score_end.")
    simulation_start_date = _coerce_date(simulation_start)
    simulation_end_date = _coerce_date(simulation_end)
    if simulation_start_date and simulation_end_date and simulation_start_date > simulation_end_date:
        raise ValueError("simulation_start must be on or before simulation_end.")
    if simulation_start_date and score_start_date and simulation_start_date > score_start_date:
        raise ValueError("simulation_start cannot be after score_start.")
    if simulation_end_date and score_end_date and simulation_end_date < score_end_date:
        raise ValueError("simulation_end cannot be before score_end.")
    if score_start_date:
        obs = obs[pd.to_datetime(obs.index).normalize() >= pd.Timestamp(score_start_date)]
    if score_end_date:
        obs = obs[pd.to_datetime(obs.index).normalize() <= pd.Timestamp(score_end_date)]
    if obs.empty:
        raise ValueError("score window removed all observed rows.")
    # Strip warm-up (spin-up) years: Klemeš (1986) and Abbaspour (2015)
    # recommend discarding the first 1-3 years of simulation to avoid
    # contaminating metric scores with uninitialised state variables.
    warmup_years = max(0, int(nyskip_years or 0))
    if warmup_years > 0 and len(obs) > 0:
        cutoff = obs.index.min() + pd.DateOffset(years=warmup_years)
        obs = obs[obs.index >= cutoff]
        if obs.empty:
            raise ValueError(
                f"nyskip_years={warmup_years} removed all observed rows; "
                "reduce nyskip or extend the observation window."
            )
    if objective_policy is not None:
        # Score-window and warm-up trimming must agree with the frozen policy
        # before creating engine/cache identities or spending a request.
        try:
            bound_policy = ExactOutputPolicyAdapter.bind(objective_policy.policy, obs)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(
                "objective_policy training context does not match observations "
                "after score-window and nyskip trimming"
            ) from exc
        if bound_policy.sha256 != objective_policy.sha256:
            raise ValueError(
                "objective_policy training calendar does not match observations "
                "after score-window and nyskip trimming"
            )
    requested_file = str(objective_sim_file).strip()
    if not requested_file:
        raise ValueError("objective_sim_file must be a non-empty filename.")
    outlet_policy = str(
        objective_outlet_policy
        or ("auto" if allow_outlet_autodetect else "strict")
    ).strip()
    if outlet_policy not in {"auto", "strict", "all_terminal_sum"}:
        raise ValueError(
            "objective_outlet_policy must be one of: 'auto', 'strict', "
            "'all_terminal_sum'."
        )
    if outlet_policy == "auto" and not allow_outlet_autodetect:
        raise ValueError(
            "objective_outlet_policy='auto' requires allow_outlet_autodetect=True."
        )
    if reuse_compact_traces and not trace_context_sha256:
        raise ValueError("reuse_compact_traces requires trace_context_sha256.")
    if reuse_compact_traces and force_fresh:
        raise ValueError("force_fresh and reuse_compact_traces are mutually exclusive.")
    static_sha256 = _staged_input_identity(base)
    observation_sha256 = _observation_identity(obs)
    telemetry_root = Path(telemetry_dir).expanduser().resolve() if telemetry_dir is not None else None
    cache_signature = _objective_cache_signature(
        parameter_mode,
        binary=binary,
        simulation_start=simulation_start_date,
        simulation_end=simulation_end_date,
        score_start=score_start_date,
        score_end=score_end_date,
        nyskip_years=warmup_years,
        objective_sim_file=requested_file,
        outlet_gis_id=int(outlet_gis_id),
        objective_outlet_policy=outlet_policy,
        trace_context_sha256=trace_context_sha256,
        observation_sha256=observation_sha256,
        input_configuration_sha256=static_sha256,
        include_physical_gate=include_physical_gate,
        strict_objective_file=strict_objective_file,
        allow_outlet_autodetect=allow_outlet_autodetect,
        threads=threads,
        policy_adapter_sha256=objective_policy.sha256 if objective_policy is not None else None,
    )

    def _evaluate(params: dict[str, float], record: dict[str, Any]) -> dict[str, Any]:
        key = params_hash(params)
        compact_trace = root / f"{key}_objective_trace.json"
        if reuse_compact_traces:
            lookup_started = time.monotonic()
            cached_metrics = _load_reusable_objective_trace(
                compact_trace,
                params=params,
                cache_signature=cache_signature,
                requested_sim_file=requested_file,
                require_physical_gate=include_physical_gate,
            )
            record["stage_seconds"]["cache_lookup"] = time.monotonic() - lookup_started
            if cached_metrics is not None:
                record["cache_status"] = "compact_hit"
                return cached_metrics
        run_dir = (
            root / key
            if keep_workdirs
            else Path(tempfile.mkdtemp(prefix=f"swatplus_obj_{key[:12]}_"))
        )
        try:
            txt = run_dir / "TxtInOut"
            marker = run_dir / ".objective_v2_complete"
            if keep_workdirs and run_dir.exists() and (
                force_fresh or not _objective_marker_matches(marker, cache_signature)
            ):
                shutil.rmtree(run_dir)
                txt = run_dir / "TxtInOut"
            if not txt.exists():
                with _stage_duration(record, "staging"):
                    _copy_fresh_txtinout(base, txt)
            if not marker.exists():
                with _stage_duration(record, "parameter_preparation"):
                    _prepare_full_mode_txtinout_for_objective(txt, parameter_mode=parameter_mode)
                    _prepare_txtinout_for_objective(
                        txt,
                        simulation_start=simulation_start_date,
                        simulation_end=simulation_end_date,
                        score_start=score_start_date,
                        score_end=score_end_date,
                    )
                    _apply_parameters_for_mode(txt, params, parameter_mode=parameter_mode)
                record["engine_invoked"] = True
                with _stage_duration(record, "engine_and_receipt"):
                    run_swat(
                        txt,
                        threads=threads,
                        timeout_s=timeout_s,
                        binary=binary,
                    )
                marker.write_text(
                    json.dumps({"status": "ok", "cache_signature": cache_signature}, indent=2) + "\n",
                    encoding="utf-8",
                )
            if not record["engine_invoked"]:
                record["cache_status"] = "workdir_hit"
            with _stage_duration(record, "evaluation"):
                aligned, metrics, diagnostics = evaluate_run(
                    txt / requested_file,
                    obs,
                    outlet_gis_id=outlet_gis_id,
                    out_alignment_csv=txt / "alignment_calibration.csv",
                    outlet_policy=outlet_policy,
                    return_diagnostics=True,
                )
            diagnostics.setdefault("outlet_policy", outlet_policy)
            actual_file = str(diagnostics.get("sim_source_file"))
            if strict_objective_file and actual_file != requested_file:
                raise RuntimeError(
                    f"Objective source mismatch: requested '{requested_file}' "
                    f"but evaluator used '{actual_file}'."
                )
            if diagnostics.get("outlet_autodetected", False) and not allow_outlet_autodetect:
                raise RuntimeError(
                    "Outlet auto-detection occurred during calibration objective "
                    f"(requested outlet_gis_id={outlet_gis_id}, "
                    f"selected={diagnostics.get('selected_outlet_gis_id')}). "
                    "Pass allow_outlet_autodetect=True to permit this behavior."
                )
            metrics = dict(metrics)
            if include_physical_gate:
                with _stage_duration(record, "physical_gate"):
                    physical_gate = _candidate_physical_gate(txt, metrics)
                diagnostics["candidate_physical_gate"] = physical_gate
                metrics["physical_gate_passed"] = 1.0 if physical_gate.get("pass") else 0.0
                process_pass = physical_gate.get("calibration_process_gate_pass")
                if process_pass is not None:
                    metrics["calibration_process_gate_passed"] = 1.0 if process_pass else 0.0
            for metric_key in (
                "selected_terminal_fraction_of_all_terminal_flow",
                "selected_terminal_nse",
                "selected_terminal_kge",
                "selected_terminal_pbias",
                "all_terminal_nse",
                "all_terminal_kge",
                "all_terminal_pbias",
                "all_terminal_volume_gate_passes_diagnostic",
            ):
                value = diagnostics.get(metric_key)
                if isinstance(value, bool):
                    metrics[metric_key] = 1.0 if value else 0.0
                elif isinstance(value, (int, float)):
                    metrics[metric_key] = float(value)
            policy_result = None
            if objective_policy is not None:
                constraints = ()
                if include_physical_gate:
                    constraints = (calibration_process_proxy(
                        diagnostics.get("candidate_physical_gate", {}).get("calibration_process_gate_pass")
                    ),)
                # A source chosen by the evaluator must be a local output filename.
                if Path(actual_file).name != actual_file:
                    raise RuntimeError("Policy objective source must be a local output filename.")
                policy_result = objective_policy.evaluate(
                    aligned, source_path=txt / actual_file,
                    receipt_path=txt / "engine_run_receipt.json", constraints=constraints,
                )
                metrics.update(policy_result.objective.components)
                diagnostics["policy_evidence"] = policy_result.to_payload()
                record["policy_evidence"] = policy_result.to_payload()
            trace_path = run_dir / "objective_trace.json"
            _write_objective_trace(
                trace_path,
                params=params,
                requested_sim_file=requested_file,
                diagnostics=diagnostics,
                metrics=metrics,
                cache_signature=cache_signature,
            )
            if not keep_workdirs:
                with _stage_duration(record, "trace_publication"):
                    _atomic_json(compact_trace, json.loads(trace_path.read_text(encoding="utf-8")))
            result = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
            if policy_result is not None:
                result.update(policy_utility=policy_result.objective.utility,
                              policy_status=policy_result.objective.status,
                              policy_feasible=policy_result.objective.feasible,
                              policy_evidence=policy_result.to_payload())
            return result
        finally:
            if not keep_workdirs:
                with _stage_duration(record, "cleanup"):
                    shutil.rmtree(run_dir, ignore_errors=True)

    def _objective(params: dict[str, float]) -> dict[str, Any]:
        # Count every admitted request before hashing, cache lookup or engine work.
        token = evaluation_budget.reserve(budget_stage) if evaluation_budget is not None else None
        started = time.monotonic()
        invocation_id = uuid4().hex
        record: dict[str, Any] = {
            "schema": "calibration_invocation_v1",
            "invocation_id": invocation_id,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "cache_signature": cache_signature,
            "cache_status": "miss", "engine_invoked": False,
            "engine_invocation_basis": "run_swat_call", "threads": int(threads),
            "status": "running", "stage_seconds": {}, "budget_stage": budget_stage,
        }
        try:
            params = dict(params)
            record["params"] = params
            record["params_sha256"] = params_hash(params)
            # Differing contexts must also serialize on the parameter-named path.
            lock = _objective_lock(str(root / params_hash(params)))
            with lock:
                record["stage_seconds"]["lock_wait"] = time.monotonic() - started
                result = _evaluate(params, record)
            record["status"] = "failed" if result.get("policy_status") == "invalid" else "completed"
            return result
        except BaseException as exc:
            record["status"] = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["total_seconds"] = time.monotonic() - started
            record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            try:
                if telemetry_root is not None:
                    try:
                        _atomic_json(telemetry_root / f"{invocation_id}.json", record)
                    except OSError:
                        logging.getLogger(__name__).exception("Unable to persist calibration invocation telemetry")
            finally:
                if token is not None:
                    evaluation_budget.finish(
                        token, status=record["status"],
                        cache_hit=record["cache_status"] in {"compact_hit", "workdir_hit"},
                        engine_invoked=record["engine_invoked"], metadata=_finite_budget_metadata(record),
                    )

    return _objective


_TIMED_OUTPUT_RE = re.compile(r"_(?:day|mon|yr|aa)\.(?:txt|csv)$", re.IGNORECASE)
_EXACT_DYNAMIC_OUTPUTS = {
    "engine_run_receipt.json",
    "basin_carbon_all.txt",
    "basin_totc.txt",
    "diagnostics.out",
    "erosion.txt",
    "hru_orgc.txt",
    "hru_totc.txt",
    "lu_change_out.txt",
}


def _is_dynamic_swatplus_output(name: str) -> bool:
    """Return whether a TxtInOut file is generated by a SWAT+ engine run."""
    normalized = str(name).strip().lower()
    return bool(
        _TIMED_OUTPUT_RE.search(normalized)
        or normalized in _EXACT_DYNAMIC_OUTPUTS
        or normalized.startswith("alignment_") and normalized.endswith(".csv")
        or normalized.startswith("flow_duration")
    )


def _copy_fresh_txtinout(source: Path, destination: Path) -> None:
    """Stage model inputs without copying stale engine output tables."""

    def _ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if _is_dynamic_swatplus_output(name)}

    shutil.copytree(source, destination, ignore=_ignore)


def _candidate_physical_gate(txtinout_dir: Path, metrics: dict[str, Any]) -> dict[str, Any]:
    try:
        from ..full_mode.water_balance_gate import check_water_balance

        gate = check_water_balance(
            txtinout_dir,
            nse=_optional_float(metrics.get("nse")),
            kge=_optional_float(metrics.get("kge")),
            pbias=_optional_float(metrics.get("pbias")),
        )
        return _with_calibration_process_gate(gate)
    except Exception as exc:
        return {"pass": False, "status": "failed", "reason": str(exc)}


_SKILL_ONLY_GATE_CODES = {"NEGATIVE_SKILL", "BELOW_RESEARCH_SKILL"}


def _with_calibration_process_gate(gate: dict[str, Any]) -> dict[str, Any]:
    result = dict(gate)
    raw_codes = result.get("condition_codes") or []
    codes = [str(code) for code in raw_codes if str(code)]
    process_codes = [code for code in codes if code not in _SKILL_ONLY_GATE_CODES]
    result["calibration_process_gate_pass"] = not process_codes
    result["calibration_process_condition_codes"] = process_codes
    result["calibration_process_gate_basis"] = (
        "water_balance_gate_excluding_skill_threshold_codes"
    )
    return result


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    import math

    return result if math.isfinite(result) else None


def _staged_input_identity(base: Path) -> str:
    """Hash precisely the non-output files copied into a fresh objective."""
    if not base.is_dir():
        raise ValueError("TxtInOut input directory missing")
    digest = sha256()
    paths = (path for path in base.rglob("*") if path.is_file())
    for path in sorted(paths, key=lambda item: item.relative_to(base).as_posix()):
        relative = path.relative_to(base)
        # copytree's ignore function applies to both directory and file names.
        if any(_is_dynamic_swatplus_output(part) for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _observation_identity(obs: pd.Series) -> str:
    """Seal scored values and normalized dates in their evaluation order."""
    digest = sha256()
    for timestamp, value in zip(pd.to_datetime(obs.index).normalize(), obs, strict=True):
        digest.update(timestamp.isoformat().encode("utf-8"))
        digest.update(b"\0")
        digest.update(float(value).hex().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _objective_cache_signature(
    parameter_mode: str,
    *,
    binary: Path | str | None = None,
    simulation_start: date | None = None,
    simulation_end: date | None = None,
    score_start: date | None = None,
    score_end: date | None = None,
    nyskip_years: int = 0,
    objective_sim_file: str | None = None,
    outlet_gis_id: int | None = None,
    objective_outlet_policy: str | None = None,
    trace_context_sha256: str | None = None,
    observation_sha256: str | None = None,
    input_configuration_sha256: str | None = None,
    include_physical_gate: bool = False,
    strict_objective_file: bool = True,
    allow_outlet_autodetect: bool = False,
    threads: int = 1,
    policy_adapter_sha256: str | None = None,
) -> str:
    payload: dict[str, str] = {
        "semantic_cache_schema": "2",
        "policy_adapter_sha256": str(policy_adapter_sha256 or ""),
        "observation_sha256": str(observation_sha256 or ""),
        "input_configuration_sha256": str(input_configuration_sha256 or ""),
        "include_physical_gate": str(include_physical_gate),
        "strict_objective_file": str(strict_objective_file),
        "allow_outlet_autodetect": str(allow_outlet_autodetect),
        "engine_threads": str(max(1, int(threads))),
        "parameter_mode": str(parameter_mode or "lte").strip().lower(),
        "builder_version": str(_builder_version),
        "simulation_start": simulation_start.isoformat() if simulation_start else "",
        "simulation_end": simulation_end.isoformat() if simulation_end else "",
        "score_start": score_start.isoformat() if score_start else "",
        "score_end": score_end.isoformat() if score_end else "",
        "nyskip_years": str(int(nyskip_years or 0)),
        "objective_sim_file": str(objective_sim_file or ""),
        "outlet_gis_id": "" if outlet_gis_id is None else str(int(outlet_gis_id)),
        "objective_outlet_policy": str(objective_outlet_policy or ""),
        "trace_context_sha256": str(trace_context_sha256 or ""),
    }
    # Include the SWAT+ engine binary hash so cached workdirs are invalidated
    # when the executable changes (upgraded, rebuilt, or swapped).
    try:
        from ..run.swatplus import locate_binary

        resolved_binary = Path(binary).expanduser().resolve() if binary else locate_binary()
        if resolved_binary.exists():
            payload["swat_binary_sha256"] = sha256(resolved_binary.read_bytes()).hexdigest()
    except Exception:
        payload["swat_binary_sha256"] = "unavailable"
    for name, path in {
        "real_engine": Path(__file__),
        "policy_engine": Path(__file__).with_name("policy_engine.py"),
        "objective_policy": Path(__file__).with_name("objective_policy.py"),
        "parameter_bridge": Path(__file__).parents[1] / "full_mode" / "parameter_bridge.py",
        "routing_fixes": Path(__file__).parents[1] / "full_mode" / "routing_fixes.py",
        "evaluator": Path(__file__).parents[1] / "output" / "eval.py",
        "metrics": Path(__file__).parents[1] / "output" / "metrics.py",
        "output_parser": Path(__file__).parents[1] / "output" / "reader.py",
        "alignment": Path(__file__).parents[1] / "output" / "plots" / "utils.py",
        "water_balance_gate": Path(__file__).parents[1] / "full_mode" / "water_balance_gate.py",
        "parameter_registry": Path(__file__).parents[1] / "params" / "registry.py",
        "parameter_governance": Path(__file__).parents[1] / "params" / "governance.py",
    }.items():
        try:
            payload[name] = sha256(path.read_bytes()).hexdigest()
        except Exception:
            payload[name] = "unavailable"
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _objective_marker_matches(marker: Path, cache_signature: str) -> bool:
    if not marker.exists():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return False
    return payload.get("status") == "ok" and payload.get("cache_signature") == cache_signature


def _apply_parameters_for_mode(txt: Path, params: dict[str, float], *, parameter_mode: str) -> None:
    mode = str(parameter_mode or "lte").strip().lower()
    if mode == "full":
        from ..full_mode.parameter_bridge import apply_parameters_to_full_swat_txtinout

        apply_parameters_to_full_swat_txtinout(txt, params)
        return
    if mode == "lte":
        apply_parameters_to_lte_txtinout(txt, params)
        return
    raise ValueError(f"Unsupported calibration parameter_mode: {parameter_mode}")


def load_observed_from_alignment_csv(path: Path | str) -> pd.Series:
    """Load observed series from an ``alignment.csv`` file.

    The file must contain ``obs`` and be indexed by date in the first column.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"alignment.csv not found: {p}")
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if "obs" not in df.columns:
        raise ValueError(f"alignment.csv missing required 'obs' column: {p}")
    s = pd.Series(df["obs"].astype(float), index=pd.to_datetime(df.index).normalize(), name="obs")
    s = s.dropna()
    if s.empty:
        raise ValueError(f"alignment.csv has no non-null observed rows: {p}")
    return s


def _coerce_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _day_year(value: date) -> tuple[int, int]:
    return int(value.strftime("%j")), int(value.year)


def apply_parameters_to_lte_txtinout(txtinout_dir: Path | str, params: dict[str, float]) -> None:
    """Apply supported calibration parameters to active LTE input files.

    Supported mappings:
    - `CN2` -> `hru-lte.hru` column `cn2` (all rows)
    - `ALPHA_BF` -> `hru-lte.hru` column `alpha_bf` (all rows)
    - `SURLAG` -> `parameters.bsn` column `surq_lag`
    - `SOIL_SCON_SCALE` -> `soils_lte.sol` column `scon` multiplier
    - `ET_CO` -> `hru-lte.hru` column `et_co` (all rows)
    - `RCHG_DP` -> `hru-lte.hru` column `rchg_dp` (all rows)
    """
    txt = Path(txtinout_dir).expanduser().resolve()
    if "CN2" in params:
        _set_tabular_column_all_rows(
            txt / "hru-lte.hru", "cn2", float(params["CN2"]), parameter_name="CN2"
        )
    if "ALPHA_BF" in params:
        _set_tabular_column_all_rows(
            txt / "hru-lte.hru",
            "alpha_bf",
            float(params["ALPHA_BF"]),
            parameter_name="ALPHA_BF",
        )
    if "SURLAG" in params:
        _set_parameters_bsn_value(
            txt / "parameters.bsn", "surq_lag", float(params["SURLAG"]), parameter_name="SURLAG"
        )
    if "SOIL_SCON_SCALE" in params:
        _scale_lte_soil_scon(txt, float(params["SOIL_SCON_SCALE"]))
    if "ET_CO" in params:
        _set_tabular_column_all_rows(
            txt / "hru-lte.hru", "et_co", float(params["ET_CO"]), parameter_name="ET_CO"
        )
    if "RCHG_DP" in params:
        _set_tabular_column_all_rows(
            txt / "hru-lte.hru", "rchg_dp", float(params["RCHG_DP"]), parameter_name="RCHG_DP"
        )


def _set_tabular_column_all_rows(path: Path, column: str, value: float, *, parameter_name: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{parameter_name}: required file not found: {path}")
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        raise ValueError(f"{parameter_name}: malformed file (expected >=3 lines): {path}")
    header = lines[1].split()
    if column not in header:
        raise ValueError(
            f"{parameter_name}: required column '{column}' missing in {path.name}; "
            f"available={header}"
        )
    idx = header.index(column)
    out: list[str] = []
    updated_rows = 0
    for i, ln in enumerate(lines):
        if i < 2 or not ln.strip():
            out.append(ln)
            continue
        parts = ln.split()
        if len(parts) <= idx:
            out.append(ln)
            continue
        parts[idx] = f"{value:.5f}"
        updated_rows += 1
        out.append("  " + "       ".join(parts))
    if updated_rows == 0:
        raise ValueError(f"{parameter_name}: no data rows updated in {path}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _set_parameters_bsn_value(path: Path, column: str, value: float, *, parameter_name: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{parameter_name}: required file not found: {path}")
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        raise ValueError(f"{parameter_name}: malformed file (expected >=3 lines): {path}")
    header = lines[1].split()
    if column not in header:
        raise ValueError(
            f"{parameter_name}: required column '{column}' missing in {path.name}; "
            f"available={header}"
        )
    idx = header.index(column)
    vals = lines[2].split()
    if len(vals) <= idx:
        raise ValueError(f"{parameter_name}: data row missing '{column}' value in {path.name}")
    vals[idx] = f"{value:.5f}"
    lines[2] = "  " + "       ".join(vals)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scale_lte_soil_scon(txtinout_dir: Path, scale: float) -> int:
    """Scale LTE soil saturated-conductivity values in ``soils_lte.sol``."""
    p = Path(txtinout_dir) / "soils_lte.sol"
    if not p.exists() or abs(scale - 1.0) < 1e-9:
        return 0
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        return 0
    header = lines[1].split()
    if "scon" not in header:
        return 0
    idx = header.index("scon")
    out: list[str] = []
    updated = 0
    for i, ln in enumerate(lines):
        if i < 2 or not ln.strip():
            out.append(ln)
            continue
        parts = ln.split()
        if len(parts) <= idx:
            out.append(ln)
            continue
        scon = float(parts[idx])
        parts[idx] = f"{max(0.05, min(250.0, scon * scale)):.5f}"
        updated += 1
        out.append("  " + "       ".join(parts))
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return updated


def params_hash(params: dict[str, float]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _prepare_txtinout_for_objective(
    txtinout: Path,
    *,
    simulation_start: date | None = None,
    simulation_end: date | None = None,
    score_start: date | None = None,
    score_end: date | None = None,
) -> None:
    """Ensure objective runs produce fresh daily channel outputs."""
    if simulation_start or simulation_end:
        _set_time_sim_window(
            txtinout / "time.sim",
            simulation_start=simulation_start,
            simulation_end=simulation_end,
        )
    _set_print_prt_for_daily_channel_outputs(
        txtinout / "print.prt",
        score_start=score_start,
        score_end=score_end,
    )
    # Prevent stale copied outputs from being scored. basin_wb_aa.txt feeds the
    # candidate physical/water-balance gate; a copy left over from the base
    # run would otherwise be judged if the candidate run did not rewrite it.
    for name in (
        "basin_wb_aa.txt",
        "channel_day.txt",
        "channel_sd_day.txt",
        "channel_sdmorph_day.txt",
        "basin_cha_day.txt",
        "basin_sd_cha_day.txt",
        "basin_sd_chamorph_day.txt",
        "alignment_calibration.csv",
    ):
        (txtinout / name).unlink(missing_ok=True)


def _prepare_full_mode_txtinout_for_objective(txtinout: Path, *, parameter_mode: str) -> None:
    """Normalize full-mode routing before any candidate engine run is scored."""
    if str(parameter_mode or "lte").strip().lower() != "full":
        return
    required = [txtinout / name for name in ("codes.bsn", "rout_unit.def", "rout_unit.con")]
    if not any(path.exists() for path in required):
        return

    from ..full_mode.routing_fixes import apply_full_routing_fixes

    apply_full_routing_fixes(txtinout)


def _set_time_sim_window(
    path: Path,
    *,
    simulation_start: date | None = None,
    simulation_end: date | None = None,
) -> None:
    if not path.exists():
        raise FileNotFoundError(f"required file not found: {path}")
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        raise ValueError(f"malformed time.sim: {path}")
    parts = lines[2].split()
    if len(parts) < 5:
        raise ValueError(f"malformed time.sim data row: {path}")
    if simulation_start is not None:
        day_start, yrc_start = _day_year(simulation_start)
        parts[0] = str(day_start)
        parts[1] = str(yrc_start)
    if simulation_end is not None:
        day_end, yrc_end = _day_year(simulation_end)
        parts[2] = str(day_end)
        parts[3] = str(yrc_end)
    lines[2] = "  ".join(parts)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _set_print_prt_for_daily_channel_outputs(
    path: Path,
    *,
    score_start: date | None = None,
    score_end: date | None = None,
) -> None:
    if not path.exists():
        raise FileNotFoundError(f"required file not found: {path}")
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 10:
        raise ValueError(f"malformed print.prt: {path}")

    # Set nyskip=0 so one-year calibration windows still emit outputs.
    top_idx = 2 if len(lines) > 2 else None
    if top_idx is not None:
        parts = lines[top_idx].split()
        if len(parts) >= 1 and parts[0].isdigit():
            parts[0] = "0"
            if score_start is not None and len(parts) >= 3:
                day_start, yrc_start = _day_year(score_start)
                parts[1] = str(day_start)
                parts[2] = str(yrc_start)
            if score_end is not None and len(parts) >= 5:
                day_end, yrc_end = _day_year(score_end)
                parts[3] = str(day_end)
                parts[4] = str(yrc_end)
            lines[top_idx] = "  ".join(parts)

    # Ensure daily output for channel metrics used in objective evaluation.
    wanted = {"channel", "channel_sd", "basin_cha", "basin_sd_cha"}
    found: set[str] = set()
    for i, ln in enumerate(lines):
        parts = ln.split()
        if len(parts) != 5:
            continue
        obj = parts[0]
        if obj in wanted:
            parts[1] = "y"
            lines[i] = "  ".join(parts)
            found.add(obj)
    missing = wanted - found
    if missing:
        raise ValueError(f"print.prt missing required object rows: {sorted(missing)}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_objective_trace(
    path: Path,
    *,
    params: dict[str, float],
    requested_sim_file: str,
    diagnostics: dict[str, object],
    metrics: dict[str, float],
    cache_signature: str,
) -> None:
    payload = {
        "params": {k: float(v) for k, v in sorted(params.items())},
        "requested_sim_file": requested_sim_file,
        "actual_sim_file": diagnostics.get("sim_source_file"),
        "requested_outlet_gis_id": diagnostics.get("requested_outlet_gis_id"),
        "selected_outlet_gis_id": diagnostics.get("selected_outlet_gis_id"),
        "selected_outlet_gis_ids": diagnostics.get("selected_outlet_gis_ids"),
        "outlet_scope": diagnostics.get("outlet_scope", "single_channel"),
        "outlet_policy": diagnostics.get("outlet_policy"),
        "outlet_autodetected": bool(diagnostics.get("outlet_autodetected", False)),
        "outlet_selection_reason": diagnostics.get("outlet_selection_reason"),
        "metrics": {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))},
        "cache_signature": cache_signature,
    }
    if "policy_evidence" in diagnostics:
        payload["policy_evidence"] = diagnostics["policy_evidence"]
    if "candidate_physical_gate" in diagnostics:
        payload["candidate_physical_gate"] = diagnostics.get("candidate_physical_gate")
    payload["payload_sha256"] = _objective_trace_payload_sha256(payload)
    _atomic_json(path, payload)


def _objective_trace_payload_sha256(payload: dict[str, Any]) -> str:
    sealed = {key: value for key, value in payload.items() if key != "payload_sha256"}
    return sha256(json.dumps(sealed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _load_reusable_objective_trace(
    path: Path,
    *,
    params: dict[str, float],
    cache_signature: str,
    requested_sim_file: str,
    require_physical_gate: bool,
) -> dict[str, float] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("cache_signature") != cache_signature:
        return None
    if payload.get("payload_sha256") != _objective_trace_payload_sha256(payload):
        return None
    expected_params = {key: float(value) for key, value in sorted(params.items())}
    if payload.get("params") != expected_params:
        return None
    if payload.get("requested_sim_file") != requested_sim_file:
        return None
    if payload.get("actual_sim_file") != requested_sim_file:
        return None
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return None
    if require_physical_gate and not isinstance(payload.get("candidate_physical_gate"), dict):
        return None
    required = {"nse", "kge", "pbias"}
    if not required.issubset(metrics):
        return None
    if not all(isinstance(value, (int, float)) for value in metrics.values()):
        return None
    import math

    if not all(math.isfinite(float(metrics[key])) for key in required):
        return None
    return {key: float(value) for key, value in metrics.items()}
