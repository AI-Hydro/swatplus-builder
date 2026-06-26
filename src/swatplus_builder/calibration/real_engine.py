"""Real engine-backed calibration objective helpers."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

from ..output.eval import evaluate_run
from ..run import run as run_swat
from .. import __version__ as _builder_version

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
) -> RealObjective:
    """Build an objective function that runs SWAT+ per parameter vector.

    ``force_fresh`` is for audit-authoritative reruns that must not reuse a
    hashed objective workdir even when the cache marker looks compatible.
    ``nyskip_years`` strips the first N years from the observed series before
    scoring to exclude the model warm-up / spin-up period from metric
    calculation (Klemeš 1986, Abbaspour 2015).
    """
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

    def _objective(params: dict[str, float]) -> dict[str, float]:
        key = params_hash(params)
        run_dir = (
            root / key
            if keep_workdirs
            else Path(tempfile.mkdtemp(prefix=f"swatplus_obj_{key[:12]}_"))
        )
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
                shutil.copytree(base, txt)
            if not marker.exists():
                _prepare_full_mode_txtinout_for_objective(txt, parameter_mode=parameter_mode)
                _prepare_txtinout_for_objective(
                    txt,
                    simulation_start=simulation_start_date,
                    simulation_end=simulation_end_date,
                    score_start=score_start_date,
                    score_end=score_end_date,
                )
                _apply_parameters_for_mode(txt, params, parameter_mode=parameter_mode)
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
            _df, metrics, diagnostics = evaluate_run(
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
            trace_path = run_dir / "objective_trace.json"
            _write_objective_trace(
                trace_path,
                params=params,
                requested_sim_file=requested_file,
                diagnostics=diagnostics,
                metrics=metrics,
            )
            if not keep_workdirs:
                compact_trace = root / f"{key}_objective_trace.json"
                shutil.copy2(trace_path, compact_trace)
            return {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
        finally:
            if not keep_workdirs:
                shutil.rmtree(run_dir, ignore_errors=True)

    return _objective


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
) -> str:
    payload: dict[str, str] = {
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
        "parameter_bridge": Path(__file__).parents[1] / "full_mode" / "parameter_bridge.py",
        "routing_fixes": Path(__file__).parents[1] / "full_mode" / "routing_fixes.py",
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
    # Prevent stale copied outputs from being scored.
    for name in (
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
    }
    if "candidate_physical_gate" in diagnostics:
        payload["candidate_physical_gate"] = diagnostics.get("candidate_physical_gate")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
