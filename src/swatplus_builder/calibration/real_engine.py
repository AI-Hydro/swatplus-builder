"""Real engine-backed calibration objective helpers."""

from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Callable

import pandas as pd

from ..output.eval import evaluate_run
from ..run import run as run_swat


RealObjective = Callable[[dict[str, float]], dict[str, float]]


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
) -> RealObjective:
    """Build an objective function that runs SWAT+ per parameter vector."""
    base = Path(base_txtinout).expanduser().resolve()
    root = Path(work_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    obs = observed_series.copy()
    requested_file = str(objective_sim_file).strip()
    if not requested_file:
        raise ValueError("objective_sim_file must be a non-empty filename.")

    def _objective(params: dict[str, float]) -> dict[str, float]:
        key = params_hash(params)
        run_dir = root / key
        txt = run_dir / "TxtInOut"
        marker = run_dir / ".objective_v2_complete"
        if not txt.exists():
            shutil.copytree(base, txt)
        if not marker.exists():
            _prepare_txtinout_for_objective(txt)
            apply_parameters_to_lte_txtinout(txt, params)
            run_swat(
                txt,
                threads=threads,
                timeout_s=timeout_s,
                binary=binary,
            )
            marker.write_text("ok\n", encoding="utf-8")
        _df, metrics, diagnostics = evaluate_run(
            txt / requested_file,
            obs,
            outlet_gis_id=outlet_gis_id,
            out_alignment_csv=txt / "alignment_calibration.csv",
            return_diagnostics=True,
        )
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
        _write_objective_trace(
            run_dir / "objective_trace.json",
            params=params,
            requested_sim_file=requested_file,
            diagnostics=diagnostics,
            metrics=metrics,
        )
        return {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}

    return _objective


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


def apply_parameters_to_lte_txtinout(txtinout_dir: Path | str, params: dict[str, float]) -> None:
    """Apply supported calibration parameters to active LTE input files.

    Supported mappings:
    - `CN2` -> `hru-lte.hru` column `cn2` (all rows)
    - `ALPHA_BF` -> `hru-lte.hru` column `alpha_bf` (all rows)
    - `SURLAG` -> `parameters.bsn` column `surq_lag`
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


def params_hash(params: dict[str, float]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _prepare_txtinout_for_objective(txtinout: Path) -> None:
    """Ensure objective runs produce fresh daily channel outputs."""
    _set_print_prt_for_daily_channel_outputs(txtinout / "print.prt")
    # Prevent stale copied outputs from being scored.
    for name in (
        "channel_day.txt",
        "channel_sd_day.txt",
        "basin_cha_day.txt",
        "basin_sd_cha_day.txt",
        "alignment_calibration.csv",
    ):
        (txtinout / name).unlink(missing_ok=True)


def _set_print_prt_for_daily_channel_outputs(path: Path) -> None:
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
        "outlet_autodetected": bool(diagnostics.get("outlet_autodetected", False)),
        "outlet_selection_reason": diagnostics.get("outlet_selection_reason"),
        "metrics": {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
