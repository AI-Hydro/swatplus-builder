from __future__ import annotations
"""Performance evaluation by aligning simulated and observed outputs."""

import hashlib
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Literal

from swatplus_builder.output.reader import read_output_file
from swatplus_builder.output.metrics import nse, kge, baseflow_index

log = logging.getLogger(__name__)
_SECONDS_PER_DAY = 86400.0

def evaluate_run(
    sim_channel_path: Path | str, 
    obs_series: pd.Series, 
    outlet_gis_id: int = 1,
    out_alignment_csv: Path | str | None = None,
    outlet_policy: Literal["auto", "strict", "best_terminal_nse"] = "auto",
    return_diagnostics: bool = False,
) -> tuple[pd.DataFrame, Dict[str, float]] | tuple[pd.DataFrame, Dict[str, float], Dict[str, Any]]:
    """Align daily simulated discharge with observed discharge and compute metrics.
    
    Args:
        sim_channel_path: Path to channel_sd_day.txt (or channel_sd_day.csv if configured).
        obs_series: NWIS observed Series with DatetimeIndex from fetch_usgs_daily_q.
        outlet_gis_id: The ID of the watershed outlet channel routing line.
        out_alignment_csv: Standard cache path for wrapper outputs (outputs/alignment.csv)
        outlet_policy:
            - ``"auto"``: allow dry-outlet fallback and non-terminal best-NSE upgrade.
            - ``"strict"``: never switch outlets; score requested/pinned outlet only.
            - ``"best_terminal_nse"``: always choose best terminal outlet by NSE when available.
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

    if outlet_policy not in {"auto", "strict", "best_terminal_nse"}:
        raise ValueError(
            "outlet_policy must be one of: 'auto', 'strict', 'best_terminal_nse'."
        )

    sim_df, diagnostics = _read_sim_discharge(
        sim_channel_path,
        outlet_gis_id,
        allow_dry_autodetect=(outlet_policy == "auto"),
    )
    diagnostics["outlet_policy"] = outlet_policy
    if sim_df.empty:
        raise ValueError(
            f"No valid flow data found in {sim_channel_path} for GIS ID {outlet_gis_id}."
        )

    obs_series.index = pd.to_datetime(obs_series.index).normalize()

    # Intersection of dates via unified aligner
    from swatplus_builder.output.plots.utils import align_timeseries

    if diagnostics.get("requested_outlet_is_terminal") is False and not diagnostics.get("outlet_autodetected", False):
        # Non-terminal requested outlets are common in generated projects.
        # Before scoring, try terminal outlets and switch only if fit improves.
        source_name = diagnostics.get("sim_source_file")
        if isinstance(source_name, str) and source_name:
            sim_source = sim_channel_path.parent / source_name
            best = _select_best_terminal_by_nse(
                sim_source,
                obs_series,
                requested_outlet_gis_id=int(outlet_gis_id),
            )
            if best is not None:
                best_gid, best_df, best_nse = best
                req_df = align_timeseries(obs_series, sim_df["sim"])
                req_nse = _safe_nse(req_df)
                should_switch = False
                if outlet_policy == "best_terminal_nse":
                    should_switch = True
                elif outlet_policy == "auto":
                    should_switch = bool(pd.isna(req_nse) or best_nse > (req_nse + 1e-9))
                if should_switch:
                    sim_df = best_df
                    diagnostics["selected_outlet_gis_id"] = int(best_gid)
                    diagnostics["outlet_autodetected"] = True
                    diagnostics["outlet_selection_reason"] = (
                        "policy_best_terminal_nse"
                        if outlet_policy == "best_terminal_nse"
                        else "requested_outlet_non_terminal_best_nse"
                    )
                    log.warning(
                        "Configured outlet GIS ID %s is non-terminal; selected terminal GIS ID %s by best NSE.",
                        outlet_gis_id,
                        best_gid,
                    )
                else:
                    diagnostics["outlet_selection_reason"] = (
                        "strict_requested_outlet_non_terminal"
                        if outlet_policy == "strict"
                        else "requested_outlet_non_terminal"
                    )

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
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    terminal_ids: set[int] = set()
    col_idx: dict[str, int] | None = None
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if "gis_id" in parts and "obj_typ" in parts:
            col_idx = {c: i for i, c in enumerate(parts)}
            continue
        if col_idx is None:
            # Fallback for legacy fixed-width chandeg.con layout.
            if len(parts) >= 14 and parts[0].isdigit() and parts[13] == "out":
                terminal_ids.add(int(parts[0]))
            continue
        try:
            obj_typ = parts[col_idx["obj_typ"]]
            if obj_typ != "out":
                continue
            # Use GIS IDs to match *_day.txt output tables.
            gis_id = int(parts[col_idx["gis_id"]])
            terminal_ids.add(gis_id)
        except (IndexError, KeyError, ValueError):
            continue
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
    """Convert known SWAT+ daily flow units to m³/s.

    SWAT+ 2023.60.5.7 writes daily accumulated volume in every channel
    output file regardless of what the header claims.  We divide the
    daily volume by 86 400 seconds to obtain a mean daily rate in m³/s.

    * channel_day.txt / basin_cha_day.txt: daily volume in ha-m
      → multiply by 10 000 m²/ha and divide by 86 400.
    * channel_sd_day.txt / basin_sd_cha_day.txt: daily volume in m³
      → divide by 86 400.
    """
    s = sim.astype(float)
    name = source_name.lower()

    if name in {"channel_day.txt", "basin_cha_day.txt"}:
        return s * 10000.0 / _SECONDS_PER_DAY
    if name in {"channel_sd_day.txt", "basin_sd_cha_day.txt"}:
        return s / _SECONDS_PER_DAY

    return s

def _read_sim_discharge(
    sim_channel_path: Path,
    outlet_gis_id: int,
    *,
    allow_dry_autodetect: bool,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Read daily outlet discharge, with optional dry-outlet fallback."""
    candidates = [sim_channel_path]
    txtinout_dir = sim_channel_path.parent
    terminal_ids = _terminal_ids_from_chandeg_con(txtinout_dir)
    chandeg_path = txtinout_dir / "chandeg.con"
    for alt in (
        "basin_sd_cha_day.txt",
        "channel_sd_day.txt",
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
        "requested_outlet_is_terminal": None,
        "sim_source_file": None,
        "terminal_outlet_ids": sorted(int(t) for t in terminal_ids),
        "terminal_outlet_count": int(len(terminal_ids)),
        "chandeg_con_sha256": _sha256_file(chandeg_path),
        "chandeg_con_path": str(chandeg_path),
        "sim_source_sha256": None,
        "available_sim_sources": [p.name for p in candidates if p.exists()],
    }
    for cand in candidates:
        if not cand.exists():
            continue
        log.info("Reading simulated timeseries from %s", cand)
        table = read_output_file(cand)
        if terminal_ids:
            diagnostics["requested_outlet_is_terminal"] = int(outlet_gis_id) in terminal_ids
        df = _extract_flo_out_rows(table, outlet_gis_id)
        if df.empty:
            last_df = df
            continue
        df["sim"] = _normalize_discharge_units(df["sim"], cand.name)
        # Prefer first candidate with non-zero signal.
        if float(df["sim"].abs().sum()) > 0.0:
            diagnostics["sim_source_file"] = cand.name
            diagnostics["sim_source_sha256"] = _sha256_file(cand)
            return df, diagnostics

        # Outlet series exists but is dry: auto-detect a valid flowing channel ID.
        if allow_dry_autodetect:
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
                        diagnostics["sim_source_sha256"] = _sha256_file(cand)
                        return alt, diagnostics
        last_df = df
    return last_df, diagnostics


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_nse(df: pd.DataFrame) -> float:
    """Return NSE for an aligned obs/sim dataframe, or NaN if unavailable."""
    if df.empty or "obs" not in df.columns or "sim" not in df.columns:
        return float("nan")
    try:
        return float(nse(df["obs"].tolist(), df["sim"].tolist()))
    except Exception:
        return float("nan")


def _select_best_terminal_by_nse(
    sim_source_path: Path,
    obs_series: pd.Series,
    requested_outlet_gis_id: int,
) -> tuple[int, pd.DataFrame, float] | None:
    """Select terminal outlet with best NSE against observed discharge."""
    if not sim_source_path.exists():
        return None
    txtinout_dir = sim_source_path.parent
    terminal_ids = _terminal_ids_from_chandeg_con(txtinout_dir)
    if not terminal_ids:
        return None

    table = read_output_file(sim_source_path)
    from swatplus_builder.output.plots.utils import align_timeseries

    best_gid: int | None = None
    best_df: pd.DataFrame | None = None
    best_nse = float("nan")
    for gid in terminal_ids:
        if int(gid) == int(requested_outlet_gis_id):
            continue
        cand = _extract_flo_out_rows(table, int(gid))
        if cand.empty:
            continue
        cand["sim"] = _normalize_discharge_units(cand["sim"], sim_source_path.name)
        if float(cand["sim"].abs().sum()) <= 0.0:
            continue
        aligned = align_timeseries(obs_series, cand["sim"])
        score = _safe_nse(aligned)
        if pd.isna(score):
            continue
        if pd.isna(best_nse) or float(score) > float(best_nse):
            best_gid = int(gid)
            best_df = cand
            best_nse = float(score)

    if best_gid is None or best_df is None or pd.isna(best_nse):
        return None
    return best_gid, best_df, best_nse
