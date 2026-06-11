"""Weather-forcing diagnostics for retained SWAT+ run artifacts."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

import pandas as pd


def write_weather_forcing_summary(
    run_dir: Path | str,
    *,
    values: dict[str, Any] | None = None,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Write a compact precipitation/forcing summary from SWAT+ weather files."""

    run = Path(run_dir).expanduser().resolve()
    destination = Path(out_dir).expanduser().resolve() if out_dir is not None else run / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    vals = values or {}
    metadata = _read_json(run / "metadata.json")
    coverage = metadata.get("weather_coverage_flags") if isinstance(metadata, dict) else None
    txtinout = _find_txtinout(run, vals)
    pcp = _precipitation_summary(txtinout) if txtinout is not None else {"available": False, "reason": "txtinout_missing"}
    observed = _observed_runoff_summary(run, vals, pcp, txtinout)

    report = {
        "version": 1,
        "run_dir": str(run),
        "txtinout_dir": str(txtinout) if txtinout is not None else None,
        "weather_source": vals.get("weather_source") or metadata.get("weather_source"),
        "metadata_weather_coverage_flags": coverage if isinstance(coverage, dict) else {},
        "precipitation": pcp,
        "observed_runoff": observed,
        "diagnostic_flags": _diagnostic_flags(pcp, observed),
    }
    json_path = destination / "weather_forcing_summary.json"
    md_path = destination / "weather_forcing_summary.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    report["json_path"] = str(json_path)
    report["markdown_path"] = str(md_path)
    return report


def _runoff_precip_ratio_context(ratio: float | None) -> dict[str, Any]:
    if ratio is None:
        return {
            "available": False,
            "class": "not_available",
            "claim_impact": "diagnostic_context_missing",
            "rationale": "Observed runoff and overlapping precipitation were not both available.",
        }
    if ratio > 1.0:
        return {
            "available": True,
            "class": "observed_runoff_exceeds_precipitation",
            "claim_impact": "blocks_volume_process_interpretation_until_forcing_area_or_observed_flow_units_are_audited",
            "rationale": "Observed runoff depth exceeds precipitation over the comparison window, which violates a simple precipitation-runoff water-balance check unless external inflow, storage release, area mismatch, or data units explain it.",
        }
    if ratio >= 0.70:
        return {
            "available": True,
            "class": "high_observed_runoff_fraction",
            "claim_impact": "diagnostic_only_high_runoff_demand_requires_snow_storage_baseflow_or_forcing_area_context",
            "rationale": "At least 70 percent of comparison-window precipitation appears as observed runoff; this is not a gate failure, but calibration should not treat the remaining volume deficit as a parameter-only problem without checking forcing, snow/storage, and drainage-area context.",
        }
    if ratio <= 0.05:
        return {
            "available": True,
            "class": "very_low_observed_runoff_fraction",
            "claim_impact": "diagnostic_only_low_runoff_response_requires_et_abstraction_or_gauge_context_review",
            "rationale": "Five percent or less of comparison-window precipitation appears as observed runoff; this can be physically plausible in dry or highly losing basins, but it should be interpreted with ET, abstraction, and gauge-area context.",
        }
    return {
        "available": True,
        "class": "ordinary_observed_runoff_fraction",
        "claim_impact": "diagnostic_only_forcing_context_available",
        "rationale": "Observed runoff is less than precipitation and does not hit the high- or very-low-response diagnostic thresholds.",
    }


def _find_txtinout(run: Path, values: dict[str, Any]) -> Path | None:
    candidates = []
    if values.get("txtinout_dir"):
        candidates.append(Path(str(values["txtinout_dir"])))
    candidates.extend(
        [
            run / "project" / "Scenarios" / "Default" / "TxtInOut",
            run / "Scenarios" / "Default" / "TxtInOut",
            run / "TxtInOut",
        ]
    )
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "pcp.cli").is_file():
            return candidate
    return None


def _precipitation_summary(txtinout: Path) -> dict[str, Any]:
    cli = txtinout / "pcp.cli"
    station_files = _station_files_from_cli(cli)
    if not station_files:
        return {"available": False, "path": str(cli), "reason": "pcp_cli_has_no_station_files"}
    series: dict[str, pd.Series] = {}
    failures: dict[str, str] = {}
    for name in station_files:
        path = txtinout / name
        parsed = _read_pcp_station(path)
        if isinstance(parsed, pd.Series):
            series[name] = parsed
        else:
            failures[name] = parsed
    if not series:
        return {
            "available": False,
            "path": str(cli),
            "station_file_count": len(station_files),
            "reason": "no_readable_pcp_station_files",
            "station_failures": failures,
        }
    frame = pd.DataFrame(series).sort_index()
    daily_mean = frame.mean(axis=1, skipna=True)
    totals = frame.sum(axis=0, skipna=True)
    nonzero_days = (frame > 0.0).sum(axis=0)
    return {
        "available": True,
        "path": str(cli),
        "station_count": int(len(series)),
        "station_file_count": int(len(station_files)),
        "station_failures": failures,
        "start": str(daily_mean.index.min().date()),
        "end": str(daily_mean.index.max().date()),
        "n_days": int(daily_mean.notna().sum()),
        "mean_daily_areal_precip_mm": float(daily_mean.mean()),
        "max_daily_areal_precip_mm": float(daily_mean.max()),
        "mean_areal_total_precip_mm": float(daily_mean.sum()),
        "station_total_precip_min_mm": float(totals.min()),
        "station_total_precip_median_mm": float(totals.median()),
        "station_total_precip_max_mm": float(totals.max()),
        "station_nonzero_days_min": int(nonzero_days.min()),
        "station_nonzero_days_max": int(nonzero_days.max()),
    }


def _daily_mean_precip_series(txtinout: Path) -> pd.Series | None:
    station_files = _station_files_from_cli(txtinout / "pcp.cli")
    series = []
    for name in station_files:
        parsed = _read_pcp_station(txtinout / name)
        if isinstance(parsed, pd.Series):
            series.append(parsed)
    if not series:
        return None
    return pd.concat(series, axis=1).sort_index().mean(axis=1, skipna=True)


def _station_files_from_cli(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    names = []
    for line in lines[2:]:
        value = line.strip()
        if value:
            names.append(value)
    return names


def _read_pcp_station(path: Path) -> pd.Series | str:
    if not path.is_file():
        return "missing"
    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[3:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            year = int(parts[0])
            doy = int(parts[1])
            value = float(parts[2])
            date = _dt.date(year, 1, 1) + _dt.timedelta(days=doy - 1)
        except Exception:
            continue
        dates.append(pd.Timestamp(date))
        values.append(value)
    if not dates:
        return "no_daily_rows"
    return pd.Series(values, index=pd.DatetimeIndex(dates), name=path.name).sort_index()


def _observed_runoff_summary(
    run: Path,
    values: dict[str, Any],
    pcp: dict[str, Any],
    txtinout: Path | None,
) -> dict[str, Any]:
    obs_path = _first_existing_path(
        values.get("observed_csv"),
        run / "outputs" / "obs_q.csv",
    )
    area_km2 = _basin_area_km2(run)
    if obs_path is None:
        return {"available": False, "reason": "observed_csv_missing", "area_km2": area_km2}
    try:
        df = pd.read_csv(obs_path)
    except Exception as exc:
        return {"available": False, "path": str(obs_path), "reason": str(exc), "area_km2": area_km2}
    if df.empty:
        return {"available": False, "path": str(obs_path), "reason": "observed_csv_empty", "area_km2": area_km2}
    date_col = df.columns[0]
    value_col = "obs" if "obs" in df.columns else "discharge" if "discharge" in df.columns else df.columns[-1]
    obs = pd.Series(df[value_col].astype(float).to_numpy(), index=pd.to_datetime(df[date_col]).dt.normalize())
    obs = obs.dropna()
    summary: dict[str, Any] = {
        "available": bool(not obs.empty),
        "path": str(obs_path),
        "area_km2": area_km2,
        "start": str(obs.index.min().date()) if not obs.empty else None,
        "end": str(obs.index.max().date()) if not obs.empty else None,
        "n_days": int(len(obs)),
        "mean_flow_m3s": float(obs.mean()) if not obs.empty else None,
    }
    if area_km2 and area_km2 > 0 and not obs.empty:
        runoff_depth_mm = float(obs.sum() * 86400.0 / (area_km2 * 1_000_000.0) * 1000.0)
        summary["observed_runoff_depth_mm"] = runoff_depth_mm
        if txtinout is not None:
            daily_precip = _daily_mean_precip_series(txtinout)
            if daily_precip is not None:
                overlap = daily_precip.reindex(obs.index).dropna()
                summary["precip_overlap_n_days"] = int(len(overlap))
                if not overlap.empty:
                    overlap_total = float(overlap.sum())
                    ratio = runoff_depth_mm / overlap_total if overlap_total else None
                    ratio_context = _runoff_precip_ratio_context(ratio)
                    summary.update(
                        {
                            "precip_overlap_start": str(overlap.index.min().date()),
                            "precip_overlap_end": str(overlap.index.max().date()),
                            "precip_overlap_total_mm": overlap_total,
                            "precip_overlap_mean_daily_mm": float(overlap.mean()),
                            "observed_runoff_to_overlap_precip_ratio": ratio,
                            "runoff_precip_ratio_class": ratio_context["class"],
                            "runoff_precip_ratio_claim_impact": ratio_context["claim_impact"],
                            "runoff_precip_ratio_rationale": ratio_context["rationale"],
                        }
                    )
    return summary


def _basin_area_km2(run: Path) -> float | None:
    validation = _read_json(run / "delin" / "validation_result.json")
    for key in ("reference_area_km2", "delineated_area_km2"):
        value = _safe_float(validation.get(key)) if isinstance(validation, dict) else None
        if value and value > 0:
            return value
    terminal = _read_json(run / "reports" / "terminal_trace.json")
    for key in ("terminal_basin_nldi_area_km2", "all_terminal_upstream_area_km2"):
        value = _safe_float(terminal.get(key)) if isinstance(terminal, dict) else None
        if value and value > 0:
            return value
    return None


def _diagnostic_flags(pcp: dict[str, Any], observed: dict[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    if not pcp.get("available"):
        flags.append({"code": "precipitation_weather_files_missing", "evidence": str(pcp.get("reason"))})
    if not observed.get("available"):
        flags.append({"code": "observed_runoff_context_missing", "evidence": str(observed.get("reason"))})
    overlap_days = _safe_float(observed.get("precip_overlap_n_days"))
    if observed.get("available") and (overlap_days is None or overlap_days <= 0):
        flags.append({"code": "observed_precip_overlap_missing", "evidence": "no precipitation days matched observed-flow dates"})
    ratio = _safe_float(observed.get("observed_runoff_to_overlap_precip_ratio"))
    if ratio is not None and ratio > 1.0:
        flags.append({"code": "observed_runoff_exceeds_precip", "evidence": f"Qobs/P={ratio:.3f}"})
    ratio_class = observed.get("runoff_precip_ratio_class")
    if ratio_class == "high_observed_runoff_fraction":
        flags.append({"code": "high_observed_runoff_fraction", "evidence": f"Qobs/P={ratio:.3f}"})
    elif ratio_class == "very_low_observed_runoff_fraction":
        flags.append({"code": "very_low_observed_runoff_fraction", "evidence": f"Qobs/P={ratio:.3f}"})
    station_count = _safe_float(pcp.get("station_count"))
    if station_count is not None and station_count < 2:
        flags.append({"code": "single_weather_station_forcing", "evidence": f"station_count={station_count:.0f}"})
    return flags


def _render_markdown(report: dict[str, Any]) -> str:
    pcp = report.get("precipitation", {})
    observed = report.get("observed_runoff", {})
    lines = [
        "# Weather Forcing Summary",
        "",
        f"- Weather source: `{report.get('weather_source')}`",
        f"- Precipitation available: `{pcp.get('available')}`",
        f"- Station count: `{pcp.get('station_count', 'n/a')}`",
        f"- Weather period: `{pcp.get('start', 'n/a')}` to `{pcp.get('end', 'n/a')}`",
        f"- Mean areal total precipitation: `{_fmt(pcp.get('mean_areal_total_precip_mm'))}` mm",
        f"- Mean daily areal precipitation: `{_fmt(pcp.get('mean_daily_areal_precip_mm'))}` mm/day",
        f"- Observed runoff depth: `{_fmt(observed.get('observed_runoff_depth_mm'))}` mm",
        f"- Overlap precipitation: `{_fmt(observed.get('precip_overlap_total_mm'))}` mm",
        f"- Observed runoff/overlap precipitation: `{_fmt(observed.get('observed_runoff_to_overlap_precip_ratio'))}`",
        f"- Runoff/precipitation class: `{observed.get('runoff_precip_ratio_class', 'n/a')}`",
        f"- Runoff/precipitation claim impact: `{observed.get('runoff_precip_ratio_claim_impact', 'n/a')}`",
        "",
        "## Flags",
    ]
    flags = report.get("diagnostic_flags") or []
    if flags:
        lines.extend(f"- `{flag.get('code')}`: {flag.get('evidence')}" for flag in flags)
    else:
        lines.append("- No forcing flags.")
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_existing_path(*values: object) -> Path | None:
    for value in values:
        if not value:
            continue
        path = Path(str(value))
        if path.is_file():
            return path
    return None


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: object) -> str:
    number = _safe_float(value)
    return "n/a" if number is None else f"{number:.3f}"
