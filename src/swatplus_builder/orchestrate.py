"""End-to-End Orchestration Platform.

Automates the entire SWAT+ workflow from a single USGS streamgage ID.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

def run_pipeline(
    usgs_id: str, 
    outdir: Path | str, 
    start_date: str = "2000-01-01", 
    end_date: str = "2010-12-31",
    engine_timeout_s: float = 3600.0,
    threads: int = 4,
    model_family: str = "full",
    warmup_years: int = 3,
    allow_diagnostic_fallbacks: bool = False,
    hru_mode: str = "dominant_only",
    min_hru_fraction: float = 0.0,
) -> dict[str, Any]:
    """Execute the full end-to-end validation platform for a basin.
    
    Args:
        usgs_id: USGS streamgage ID (e.g. "01547700").
        outdir: Directory to save all outputs, metrics, and plots.
        start_date: Simulation start.
        end_date: Simulation end.
        
    Returns:
        JSON-serializable dict containing the run summary and metrics.
    """
    outdir = Path(outdir).resolve()
    
    # 0. Output standard directories
    reports_dir = outdir / "reports"
    plots_dir = outdir / "plots"
    outputs_dir = outdir / "outputs"
    for d in [reports_dir, plots_dir, outputs_dir]:
        d.mkdir(parents=True, exist_ok=True)
        
    log.info("Starting Platform Run | USGS: %s | Outdir: %s", usgs_id, outdir)
    
    # Run configuration tracking guarantees reproducibility
    run_config = {
        "usgs_id": usgs_id,
        "soil_mode": "high_fidelity",
        "timestamp": datetime.now().isoformat(),
        "start_date": start_date,
        "end_date": end_date,
        "threads": threads,
        "model_family": model_family,
        "warmup_years": int(warmup_years),
        "hru_mode_requested": hru_mode,
        "min_hru_fraction_requested": float(min_hru_fraction),
        "status": "FAILED"
    }

    try:
        txtinout = _find_prepared_txtinout(outdir)
        run_config.update(_load_run_metadata_fields(outdir))
        if txtinout is None:
            from .workflows.full_build import build_full_model

            build_result = build_full_model(
                usgs_id=usgs_id,
                outdir=outdir,
                start_date=start_date,
                end_date=end_date,
                warmup_years=warmup_years,
                allow_diagnostic_fallbacks=allow_diagnostic_fallbacks,
                hru_mode=hru_mode,
                min_hru_fraction=min_hru_fraction,
            )
            run_config["build"] = build_result.to_dict()
            if not build_result.success:
                run_config.update(
                    {
                        "status": "BLOCKED",
                        "blocker_class": build_result.blocker_class or "full_model_build_failed",
                        "recommended_next_action": (
                            "Resolve the package-owned full-mode build blocker before "
                            "calibration or claim-tier evaluation."
                        ),
                        "locked_calibration_ready": False,
                    }
                )
                if build_result.blocker_class == "soil_realism_gate_failed":
                    run_config.update(
                        {
                            "soil_mode": "not_verified",
                            "soil_provenance_mode": "soil_realism_gate_failed",
                            "pct_fallback_soils": None,
                        }
                    )
                with open(outdir / "run_config.json", "w") as f:
                    json.dump(run_config, f, indent=2)
                return run_config
            run_config.update(_load_run_metadata_fields(outdir))
            txtinout = _find_prepared_txtinout(outdir)
            if txtinout is None:
                run_config.update(
                    {
                        "status": "BLOCKED",
                        "blocker_class": "full_model_build_missing_txtinout",
                        "recommended_next_action": "Inspect full model build artifacts.",
                        "locked_calibration_ready": False,
                    }
                )
                with open(outdir / "run_config.json", "w") as f:
                    json.dump(run_config, f, indent=2)
                return run_config

        from .calibration.locked_benchmark import lock_benchmark
        from .calibration.nwis import fetch_usgs_daily_q
        from .output.eval import _terminal_ids_from_chandeg_con
        from .full_mode.routing_fixes import apply_full_routing_fixes
        from .full_mode.subsurface_priors import (
            apply_subsurface_prior_correction,
            finalize_subsurface_prior_correction,
        )
        from .run.swatplus import clean_and_run_solver

        if model_family == "full":
            try:
                apply_full_routing_fixes(txtinout)
                run_config["full_routing_fixes_applied"] = True
                run_config["full_routing_fixes_txtinout"] = str(txtinout)
            except Exception as exc:
                run_config.update(
                    {
                        "status": "BLOCKED",
                        "blocker_class": "full_routing_fixes_failed",
                        "txtinout_dir": str(txtinout),
                        "locked_calibration_ready": False,
                        "recommended_next_action": (
                            "Inspect prepared full-mode TxtInOut routing files before fresh engine execution."
                        ),
                        "error": str(exc),
                    }
                )
                with open(outdir / "run_config.json", "w") as f:
                    json.dump(run_config, f, indent=2)
                return run_config

        rc, stdout_tail, stderr_tail = clean_and_run_solver(
            txtinout,
            threads=threads,
            timeout_s=engine_timeout_s,
        )
        obs_csv = outputs_dir / "obs_q.csv"
        obs_series = _load_observed_series(obs_csv)
        if obs_series is None:
            obs_series = fetch_usgs_daily_q(usgs_id, start_date, end_date, obs_csv)

        if model_family == "full":
            subsurface_prior = apply_subsurface_prior_correction(
                outdir,
                txtinout,
                obs_series=obs_series,
            )
            run_config["subsurface_prior_correction"] = subsurface_prior
            run_config["subsurface_prior_correction_path"] = subsurface_prior.get("report_path")
            run_config["subsurface_prior_correction_status"] = subsurface_prior.get("status")
            if subsurface_prior.get("status") == "applied":
                rc, stdout_tail, stderr_tail = clean_and_run_solver(
                    txtinout,
                    threads=threads,
                    timeout_s=engine_timeout_s,
                )
                subsurface_prior = finalize_subsurface_prior_correction(
                    outdir,
                    txtinout,
                    subsurface_prior,
                )
                run_config["subsurface_prior_correction"] = subsurface_prior
                run_config["subsurface_prior_correction_status"] = subsurface_prior.get("status")

        sim_source = _find_sim_source_file(txtinout)
        if sim_source is None:
            run_config.update(
                {
                    "status": "BLOCKED",
                    "blocker_class": "fresh_simulation_output_missing",
                    "txtinout_dir": str(txtinout),
                    "locked_calibration_ready": False,
                    "recommended_next_action": "Inspect SWAT+ print.prt output settings and engine logs.",
                }
            )
            with open(outdir / "run_config.json", "w") as f:
                json.dump(run_config, f, indent=2)
            return run_config

        # Derive the terminal outlet from generated topology (chandeg.con)
        # rather than hardcoding a possibly-invalid GIS ID.  Fall back to 1 if
        # the file doesn't exist yet — lock_benchmark with outlet_policy="auto"
        # will still discover the correct terminal.
        terminal_ids = sorted(_terminal_ids_from_chandeg_con(txtinout))
        outlet_gis_id = terminal_ids[0] if terminal_ids else 1

        lock = lock_benchmark(
            txtinout_dir=txtinout,
            obs_series=obs_series,
            out_dir=outdir,
            basin_id=f"usgs_{usgs_id}",
            outlet_gis_id=outlet_gis_id,
            sim_source_file=sim_source.name,
        )
        metrics_path = Path(lock.benchmark_dir) / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
        outlet_prov_path = Path(lock.benchmark_dir) / "outlet_provenance.json"
        outlet_prov = (
            json.loads(outlet_prov_path.read_text(encoding="utf-8"))
            if outlet_prov_path.exists()
            else {}
        )
        terminal_ids = outlet_prov.get("terminal_outlet_ids") or []

        run_config.update(
            {
                "status": "SUCCESS",
                "txtinout_dir": str(txtinout),
                "observed_csv": str(obs_csv),
                "benchmark_lock_path": str(Path(lock.benchmark_dir) / "benchmark_lock.json"),
                "benchmark_dir": lock.benchmark_dir,
                "requested_outlet_gis_id": outlet_prov.get("requested_outlet_gis_id", 1),
                "selected_outlet_gis_id": lock.outlet_gis_id,
                "outlet_autodetected": outlet_prov.get("outlet_autodetected"),
                "outlet_selection_reason": outlet_prov.get("outlet_selection_reason"),
                "terminal_outlet_ids": terminal_ids,
                "terminal_outlet_count": len(terminal_ids),
                "sim_source_file": lock.sim_source_file,
                "baseline_nse": lock.baseline_nse,
                "baseline_kge": lock.baseline_kge,
                "metrics": metrics,
                "locked_calibration_ready": True,
                "fresh_engine_run": True,
                "engine_returncode": rc,
                "engine_stdout_tail": stdout_tail,
                "engine_stderr_tail": stderr_tail,
            }
        )
        with open(outdir / "run_config.json", "w") as f:
            json.dump(run_config, f, indent=2)

        # Generate interactive HTML dashboard
        try:
            from .output.dashboard import build_dashboard
            dashboard_path = build_dashboard(outdir)
            run_config["dashboard_html"] = str(dashboard_path)
        except Exception as dashboard_exc:
            log.warning("Dashboard generation failed (non-fatal): %s", dashboard_exc)

        return run_config
        
    except Exception as e:
        run_config["error"] = str(e)
        with open(outdir / "run_config.json", "w") as f:
            json.dump(run_config, f, indent=2)
        raise


def _load_run_metadata_fields(outdir: Path) -> dict[str, Any]:
    metadata_path = outdir / "metadata.json"
    if not metadata_path.is_file():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not load run metadata from %s: %s", metadata_path, exc)
        return {}
    fields: dict[str, Any] = {}
    for key in ("soil_mode", "soil_provenance_mode", "pct_fallback_soils"):
        if key in metadata:
            fields[key] = metadata[key]
    notes = metadata.get("notes")
    if not fields.get("soil_provenance_mode") and isinstance(notes, list):
        for note in notes:
            if not isinstance(note, str) or not note.startswith("soil_provenance_mode="):
                continue
            _, value = note.split("=", 1)
            value = value.strip()
            if value and value.lower() not in {"none", "null", "n/a"}:
                fields["soil_provenance_mode"] = value
                break
    if fields:
        fields["metadata_path"] = str(metadata_path)
    return fields


def _find_prepared_txtinout(outdir: Path) -> Path | None:
    candidates = [
        outdir / "project" / "Scenarios" / "Default" / "TxtInOut",
        outdir / "Scenarios" / "Default" / "TxtInOut",
        outdir / "TxtInOut",
    ]
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "file.cio").exists():
            return candidate
    return None


def _find_sim_source_file(txtinout: Path) -> Path | None:
    for name in ("basin_sd_cha_day.txt", "channel_sd_day.txt", "channel_day.txt"):
        candidate = txtinout / name
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def _load_observed_series(obs_csv: Path) -> pd.Series | None:
    if not obs_csv.exists():
        return None
    df = pd.read_csv(obs_csv, index_col=0, parse_dates=True)
    if df.empty:
        return None
    column = "obs" if "obs" in df.columns else "discharge" if "discharge" in df.columns else df.columns[0]
    series = pd.Series(
        df[column].astype(float).to_numpy(),
        index=pd.to_datetime(df.index).normalize(),
        name="obs",
    )
    series = series.dropna()
    return series if not series.empty else None
