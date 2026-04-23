from __future__ import annotations
"""Performance evaluation by aligning simulated and observed outputs."""

import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Any

from swatplus_builder.output.reader import read_output_file
from swatplus_builder.output.metrics import nse, kge, baseflow_index

log = logging.getLogger(__name__)
_SECONDS_PER_DAY = 86400.0

def evaluate_run(
    sim_channel_path: Path | str, 
    obs_series: pd.Series, 
    outlet_gis_id: int = 1,
    out_alignment_csv: Path | str | None = None,
    return_diagnostics: bool = False,
) -> tuple[pd.DataFrame, Dict[str, float]] | tuple[pd.DataFrame, Dict[str, float], Dict[str, Any]]:
    """Align daily simulated discharge with observed discharge and compute metrics.
    
    Args:
        sim_channel_path: Path to channel_sd_day.txt (or channel_sd_day.csv if configured).
        obs_series: NWIS observed Series with DatetimeIndex from fetch_usgs_daily_q.
        outlet_gis_id: The ID of the watershed outlet channel routing line.
        out_alignment_csv: Standard cache path for wrapper outputs (outputs/alignment.csv)
        return_diagnostics: If True, include outlet/source diagnostics in return tuple.
        
    Returns:
        tuple containing:
            - Aligned DataFrame with columns ['obs', 'sim'] mapping overlapping dates.
            - Dictionary of computed hydrological metrics (nse, kge, bfi).
            - Optional diagnostics dict when ``return_diagnostics=True``.
    """
    sim_channel_path = Path(sim_channel_path)
    if not sim_channel_path.exists():
        raise FileNotFoundError(f"Missing simulation output file: {sim_channel_path}")

    sim_df, diagnostics = _read_sim_discharge(sim_channel_path, outlet_gis_id)
    if sim_df.empty:
        raise ValueError(
            f"No valid flow data found in {sim_channel_path} for GIS ID {outlet_gis_id}."
        )

    obs_series.index = pd.to_datetime(obs_series.index).normalize()

    # Intersection of dates via unified aligner
    from swatplus_builder.output.plots.utils import align_timeseries
    df = align_timeseries(obs_series, sim_df["sim"])
    log.info("Aligned %d overlapping days of observed and simulated flow", len(df))

    if df.empty:
        log.warning("No overlapping dates found between simulated and observed!")
        empty_metrics = {"nse": float("nan"), "kge": float("nan"), "bfi_obs": float("nan")}
        if return_diagnostics:
            return df, empty_metrics, diagnostics
        return df, empty_metrics

    metrics: Dict[str, float] = {}
    
    # Obs and Sim must be lists for our stdlib metrics
    obs_list = df["obs"].tolist()
    sim_list = df["sim"].tolist()

    try:
        metrics["nse"] = nse(obs_list, sim_list)
        metrics["kge"] = kge(obs_list, sim_list)
        metrics["bfi_obs"] = baseflow_index(obs_list)
        metrics["bfi_sim"] = baseflow_index(sim_list)
    except Exception as e:
        log.warning("Metric computation failed: %s", e)

    if out_alignment_csv:
        out_path = Path(out_alignment_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path)

    if return_diagnostics:
        return df, metrics, diagnostics
    return df, metrics


def _extract_flo_out_rows(table, outlet_gis_id: int) -> pd.DataFrame:
    records: list[dict[str, float | pd.Timestamp]] = []
    for row in table.rows:
        if int(row.get("gis_id", -1)) != outlet_gis_id:
            continue
        try:
            y = int(row["yr"])
            m = int(row["mon"])
            d = int(row["day"])
            flo = float(row["flo_out"])
            dt = pd.Timestamp(year=y, month=m, day=d).normalize()
            records.append({"date": dt, "sim": flo})
        except (KeyError, TypeError, ValueError):
            continue
    if not records:
        return pd.DataFrame(columns=["sim"])
    df = pd.DataFrame(records).set_index("date")
    return df


def _terminal_ids_from_chandeg_con(txtinout_dir: Path) -> set[int]:
    """Best-effort parse of terminal channel IDs from ``chandeg.con``.

    Returns IDs where ``obj_typ == out``. If unavailable/unparseable, returns empty set.
    """
    p = txtinout_dir / "chandeg.con"
    if not p.exists():
        return set()
    terminal_ids: set[int] = set()
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        if not parts[0].isdigit():
            continue
        # chandeg.con columns include "... out_tot obj_typ obj_id hyd_typ frac"
        if parts[13] == "out":
            terminal_ids.add(int(parts[0]))
    return terminal_ids


def _pick_best_flowing_gis_id(table, preferred_gis_id: int, txtinout_dir: Path) -> int | None:
    """Pick a flowing GIS ID when the configured outlet series is dry.

    Preference order:
    1) Non-zero terminal IDs from chandeg.con (obj_typ=out), highest absolute sum.
    2) Any non-zero GIS ID in the table, highest absolute sum.
    """
    sums_by_gid: dict[int, float] = {}
    for row in table.rows:
        try:
            gid = int(row.get("gis_id", -1))
            flo = float(row.get("flo_out", 0.0))
        except (TypeError, ValueError):
            continue
        sums_by_gid[gid] = sums_by_gid.get(gid, 0.0) + abs(flo)

    if not sums_by_gid:
        return None

    terminal_ids = _terminal_ids_from_chandeg_con(txtinout_dir)
    if terminal_ids:
        term = {gid: s for gid, s in sums_by_gid.items() if gid in terminal_ids}
        if term:
            best_gid, best_sum = max(term.items(), key=lambda kv: kv[1])
            if best_sum > 0.0 and best_gid != preferred_gis_id:
                return best_gid

    best_gid, best_sum = max(sums_by_gid.items(), key=lambda kv: kv[1])
    if best_sum > 0.0 and best_gid != preferred_gis_id:
        return best_gid
    return None


def _normalize_discharge_units(sim: pd.Series, source_name: str) -> pd.Series:
    """Convert known SWAT+ daily flow units to m3/s."""
    s = sim.astype(float)
    name = source_name.lower()

    # Standard channel outputs are daily volume in ha-m.
    if name in {"channel_day.txt", "basin_cha_day.txt"}:
        return s * 10000.0 / _SECONDS_PER_DAY

    # Basin stream-discharge daily outputs in this workflow are daily volume.
    # Guard with magnitude heuristic so we do not downscale already-rate files.
    if name == "basin_sd_cha_day.txt":
        if float(s.max()) > 500.0:
            return s / _SECONDS_PER_DAY
        return s

    # channel_sd_day is expected to already be a rate in m3/s.
    return s


def _read_sim_discharge(sim_channel_path: Path, outlet_gis_id: int) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Read daily outlet discharge, with fallback when primary file is empty/zero."""
    candidates = [sim_channel_path]
    txtinout_dir = sim_channel_path.parent
    for alt in (
        "channel_sd_day.txt",
        "basin_sd_cha_day.txt",
        "basin_cha_day.txt",
        "channel_day.txt",
    ):
        p = txtinout_dir / alt
        if p not in candidates and p.exists():
            candidates.append(p)

    last_df = pd.DataFrame(columns=["sim"])
    diagnostics: Dict[str, Any] = {
        "requested_outlet_gis_id": int(outlet_gis_id),
        "selected_outlet_gis_id": int(outlet_gis_id),
        "outlet_autodetected": False,
        "outlet_selection_reason": "requested_outlet",
        "sim_source_file": None,
    }
    for cand in candidates:
        if not cand.exists():
            continue
        log.info("Reading simulated timeseries from %s", cand)
        table = read_output_file(cand)
        df = _extract_flo_out_rows(table, outlet_gis_id)
        if df.empty:
            last_df = df
            continue
        df["sim"] = _normalize_discharge_units(df["sim"], cand.name)
        # Prefer first candidate with non-zero signal.
        if float(df["sim"].abs().sum()) > 0.0:
            diagnostics["sim_source_file"] = cand.name
            return df, diagnostics

        # Outlet series exists but is dry: auto-detect a valid flowing channel ID.
        best_gid = _pick_best_flowing_gis_id(table, outlet_gis_id, txtinout_dir)
        if best_gid is not None:
            alt = _extract_flo_out_rows(table, best_gid)
            if not alt.empty:
                alt["sim"] = _normalize_discharge_units(alt["sim"], cand.name)
                if float(alt["sim"].abs().sum()) > 0.0:
                    log.warning(
                        "Configured outlet GIS ID %s is dry in %s; using GIS ID %s with non-zero flow.",
                        outlet_gis_id,
                        cand.name,
                        best_gid,
                    )
                    diagnostics["selected_outlet_gis_id"] = int(best_gid)
                    diagnostics["outlet_autodetected"] = True
                    diagnostics["outlet_selection_reason"] = "requested_outlet_dry"
                    diagnostics["sim_source_file"] = cand.name
                    return alt, diagnostics
        last_df = df
    return last_df, diagnostics
