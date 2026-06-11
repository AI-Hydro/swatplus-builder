from __future__ import annotations
"""Performance evaluation by aligning simulated and observed outputs."""

import hashlib
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Literal

from swatplus_builder.output.reader import read_output_file
from swatplus_builder.output.metrics import nse, kge, pbias, baseflow_index

log = logging.getLogger(__name__)
_SECONDS_PER_DAY = 86400.0

def evaluate_run(
    sim_channel_path: Path | str, 
    obs_series: pd.Series, 
    outlet_gis_id: int = 1,
    out_alignment_csv: Path | str | None = None,
    outlet_policy: Literal["auto", "strict", "best_terminal_nse", "all_terminal_sum"] = "auto",
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
            - ``"all_terminal_sum"``: explicitly score a virtual outlet made
              by summing every non-empty terminal outlet. This is provenance-
              sensitive and should only be used by callers that record the
              virtual outlet authority.
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

    if outlet_policy not in {"auto", "strict", "best_terminal_nse", "all_terminal_sum"}:
        raise ValueError(
            "outlet_policy must be one of: 'auto', 'strict', 'best_terminal_nse', "
            "'all_terminal_sum'."
        )

    if outlet_policy == "all_terminal_sum":
        sim_df, diagnostics = _read_all_terminal_sum_discharge(sim_channel_path, outlet_gis_id)
    else:
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

    if (
        outlet_policy != "all_terminal_sum"
        and diagnostics.get("requested_outlet_is_terminal") is False
        and not diagnostics.get("outlet_autodetected", False)
    ):
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
        metrics["pbias"] = pbias(obs_list, sim_list)
        metrics["bfi_obs"] = baseflow_index(obs_list)
        metrics["bfi_sim"] = baseflow_index(sim_list)
    except Exception as e:
        log.warning("Metric computation failed: %s", e)

    if return_diagnostics:
        source_name = diagnostics.get("sim_source_file")
        source_path = sim_channel_path.parent / str(source_name) if isinstance(source_name, str) else sim_channel_path
        diagnostics.update(
            _terminal_scope_metric_diagnostics(
                source_path,
                obs_series,
                selected_outlet_gis_id=int(diagnostics.get("selected_outlet_gis_id", outlet_gis_id)),
            )
        )

    if out_alignment_csv:
        out_path = Path(out_alignment_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path)

    if return_diagnostics:
        return df, metrics, diagnostics
    return df, metrics


def _terminal_scope_metric_diagnostics(
    sim_source_path: Path,
    obs_series: pd.Series,
    *,
    selected_outlet_gis_id: int,
) -> dict[str, Any]:
    """Diagnostic-only selected-vs-all terminal metrics for multi-terminal runs."""

    txtinout_dir = sim_source_path.parent
    terminal_ids = sorted(int(gid) for gid in _terminal_ids_from_chandeg_con(txtinout_dir))
    if len(terminal_ids) < 2 or not sim_source_path.exists():
        return {}
    try:
        table = read_output_file(sim_source_path)
    except Exception as exc:
        return {
            "terminal_scope_metrics_available": False,
            "terminal_scope_metric_reason": f"sim_source_unreadable: {exc}",
        }

    def _series_for(gid: int) -> pd.Series:
        df = _extract_flo_out_rows(table, gid)
        if df.empty:
            return pd.Series(dtype=float)
        return _normalize_discharge_units(df["sim"], sim_source_path.name)

    selected_series = _series_for(int(selected_outlet_gis_id))
    terminal_series = [
        series.rename(str(gid))
        for gid in terminal_ids
        if not (series := _series_for(gid)).empty and float(series.abs().sum()) > 0.0
    ]
    if not terminal_series:
        return {
            "terminal_scope_metrics_available": False,
            "terminal_scope_metric_reason": "terminal_series_empty",
            "terminal_scope_metric_terminal_ids": terminal_ids,
        }
    all_terminal = pd.concat(terminal_series, axis=1).sum(axis=1)
    selected_summary = _metric_summary(obs_series, selected_series)
    all_summary = _metric_summary(obs_series, all_terminal)
    selected_sum = float(selected_series.sum()) if not selected_series.empty else 0.0
    all_sum = float(all_terminal.sum()) if not all_terminal.empty else 0.0
    selected_fraction = selected_sum / all_sum if all_sum else None
    all_pbias = all_summary.get("pbias")
    return {
        "terminal_scope_metrics_available": bool(selected_summary.get("available") and all_summary.get("available")),
        "terminal_scope_metric_claim_impact": "diagnostic_only_not_final_claim_evidence",
        "terminal_scope_metric_source_file": sim_source_path.name,
        "terminal_scope_metric_terminal_ids": terminal_ids,
        "selected_terminal_fraction_of_all_terminal_flow": selected_fraction,
        "selected_terminal_nse": selected_summary.get("nse"),
        "selected_terminal_kge": selected_summary.get("kge"),
        "selected_terminal_pbias": selected_summary.get("pbias"),
        "all_terminal_nse": all_summary.get("nse"),
        "all_terminal_kge": all_summary.get("kge"),
        "all_terminal_pbias": all_summary.get("pbias"),
        "all_terminal_volume_gate_passes_diagnostic": (
            abs(float(all_pbias)) <= 30.0 if isinstance(all_pbias, (int, float)) else None
        ),
    }


def _metric_summary(obs_series: pd.Series, sim_series: pd.Series) -> dict[str, Any]:
    from swatplus_builder.output.plots.utils import align_timeseries

    if sim_series.empty:
        return {"available": False}
    aligned = align_timeseries(obs_series, sim_series)
    if aligned.empty:
        return {"available": False}
    obs = aligned["obs"].tolist()
    sim = aligned["sim"].tolist()
    summary: dict[str, Any] = {"available": True}
    for name, fn in (("nse", nse), ("kge", kge), ("pbias", pbias)):
        try:
            summary[name] = float(fn(obs, sim))
        except Exception:
            summary[name] = float("nan")
    return summary


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

    Returns IDs where ``obj_typ == out`` OR where ``out_tot == 0``
    (dead-end channel is the implicit terminal in editor v3.2.0).
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
            elif len(parts) >= 14 and parts[0].isdigit() and parts[12] == "0":
                # out_tot=0 means this channel has no downstream routing
                terminal_ids.add(int(parts[2]))  # gis_id at col 2
            continue
        try:
            # Check out_tot=0 FIRST — terminal channels may lack obj_typ/obj_id columns
            if "out_tot" in col_idx:
                out_tot_val = int(parts[col_idx["out_tot"]])
                if out_tot_val == 0:
                    gis_id = int(parts[col_idx["gis_id"]])
                    terminal_ids.add(gis_id)
                    continue
            obj_typ = parts[col_idx["obj_typ"]]
            if obj_typ == "out":
                gis_id = int(parts[col_idx["gis_id"]])
                terminal_ids.add(gis_id)
        except (IndexError, KeyError, ValueError):
            continue
    return terminal_ids


def _candidate_sim_paths(sim_channel_path: Path) -> list[Path]:
    candidates = [sim_channel_path]
    txtinout_dir = sim_channel_path.parent
    for alt in (
        "basin_sd_cha_day.txt",
        "channel_sd_day.txt",
        "basin_cha_day.txt",
        "channel_day.txt",
    ):
        p = txtinout_dir / alt
        if p not in candidates and p.exists():
            candidates.append(p)
    return candidates


def _read_all_terminal_sum_discharge(
    sim_channel_path: Path,
    outlet_gis_id: int,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Read a virtual all-terminal outlet formed by summing terminal flows."""
    txtinout_dir = sim_channel_path.parent
    terminal_ids = sorted(int(gid) for gid in _terminal_ids_from_chandeg_con(txtinout_dir))
    chandeg_path = txtinout_dir / "chandeg.con"
    diagnostics: Dict[str, Any] = {
        "requested_outlet_gis_id": int(outlet_gis_id),
        "selected_outlet_gis_id": int(outlet_gis_id),
        "selected_outlet_gis_ids": terminal_ids,
        "outlet_scope": "virtual_all_terminal",
        "outlet_autodetected": False,
        "outlet_selection_reason": "explicit_virtual_all_terminal_sum",
        "requested_outlet_is_terminal": int(outlet_gis_id) in set(terminal_ids),
        "sim_source_file": None,
        "terminal_outlet_ids": terminal_ids,
        "terminal_outlet_count": int(len(terminal_ids)),
        "chandeg_con_sha256": _sha256_file(chandeg_path),
        "chandeg_con_path": str(chandeg_path),
        "sim_source_sha256": None,
        "available_sim_sources": [p.name for p in _candidate_sim_paths(sim_channel_path) if p.exists()],
        "virtual_outlet_evaluation": True,
        "virtual_outlet_claim_authority": False,
    }
    if not terminal_ids:
        diagnostics["terminal_scope_metric_reason"] = "terminal_inventory_empty"
        return pd.DataFrame(columns=["sim"]), diagnostics

    last_df = pd.DataFrame(columns=["sim"])
    for cand in _candidate_sim_paths(sim_channel_path):
        if not cand.exists():
            continue
        table = read_output_file(cand)
        terminal_series: list[pd.Series] = []
        for gid in terminal_ids:
            terminal_df = _extract_flo_out_rows(table, gid)
            if not terminal_df.empty:
                terminal_series.append(terminal_df["sim"].rename(str(gid)))
        if not terminal_series:
            continue
        normalized = [
            _normalize_discharge_units(series.astype(float), cand.name)
            for series in terminal_series
        ]
        all_terminal = pd.concat(normalized, axis=1).sum(axis=1).to_frame("sim")
        last_df = all_terminal
        if float(all_terminal["sim"].abs().sum()) > 0.0:
            diagnostics["sim_source_file"] = cand.name
            diagnostics["sim_source_sha256"] = _sha256_file(cand)
            return all_terminal, diagnostics
    return last_df, diagnostics


def _unit_for_column(source, column: str) -> str | None:
    """Read the documented unit for ``column`` from a SWAT+ output file header.

    ``source`` can be a Path, a str, or an ``OutputTable`` with a ``.path``
    attribute.  The unit row immediately follows the column-name header row in
    well-formed SWAT+ output files (``*_day.txt``, ``*_yr.txt``, etc.).
    Returns ``"m^3/s"`` or ``"m^3"`` when the header is legible; returns
    ``None`` when the file is missing or the unit row cannot be parsed.
    """
    if source is None:
        return None
    if hasattr(source, "columns") and hasattr(source, "units"):
        try:
            cols = list(source.columns)
            units = list(source.units)
        except Exception:
            cols = []
            units = []
        if column in cols:
            idx = cols.index(column)
            if idx < len(units):
                unit = str(units[idx]).strip()
                if unit:
                    return unit
    if hasattr(source, "path"):
        p = Path(source.path)
    else:
        p = Path(source)
    if not p.is_file():
        return None
    try:
        with p.open(encoding="utf-8", errors="replace") as fh:
            fh.readline()  # title
            header = fh.readline()
            unit_line = fh.readline()
    except OSError:
        return None
    header_cols = header.split()
    unit_cols = unit_line.split()
    if column not in header_cols:
        return None
    idx = header_cols.index(column)
    if idx < len(unit_cols):
        return unit_cols[idx].strip()
    return None


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


def _pick_best_flowing_gis_id_unrestricted(table) -> int | None:
    """Pick the GIS ID with the highest absolute flow, ignoring terminal topology."""
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
    best_gid, best_sum = max(sums_by_gid.items(), key=lambda kv: kv[1])
    return best_gid if best_sum > 0 else None


def _non_terminal_upgrade_reason(terminal_ids: set[int]) -> str:
    if len(terminal_ids) == 1:
        return "requested_outlet_non_terminal_single_terminal"
    if len(terminal_ids) > 1:
        return "requested_outlet_non_terminal_largest_terminal_flow"
    return "requested_outlet_non_terminal"


def _normalize_discharge_units(sim: pd.Series, source_name: str) -> pd.Series:
    """Convert known SWAT+ daily flow units to m³/s.

    SWAT+ 2023.60.5.7 ``channel_sd_day.txt`` and ``channel_sdmorph_day.txt``
    are documented as m³/s (rate). ``channel_day.txt`` and
    ``basin_cha_day.txt`` are daily volume in ha-m.
    """
    s = sim.astype(float)
    name = source_name.lower()

    if name in {"channel_day.txt", "basin_cha_day.txt"}:
        return s * 10000.0 / _SECONDS_PER_DAY
    if name in {"channel_sd_day.txt", "basin_sd_cha_day.txt", "channel_sdmorph_day.txt"}:
        # Already in m³/s — no conversion needed.
        return s

    return s

def _read_sim_discharge(
    sim_channel_path: Path,
    outlet_gis_id: int,
    *,
    allow_dry_autodetect: bool,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Read daily outlet discharge, with optional dry-outlet fallback."""
    txtinout_dir = sim_channel_path.parent
    candidates = _candidate_sim_paths(sim_channel_path)
    terminal_ids = _terminal_ids_from_chandeg_con(txtinout_dir)
    chandeg_path = txtinout_dir / "chandeg.con"

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
            # If the requested outlet is not a terminal, and we're in auto
            # mode, the user likely doesn't know the correct outlet yet.
            # Prefer the terminal with the largest flow instead of silently
            # accepting a non-terminal upstream channel.
            requested_is_terminal = (
                terminal_ids and int(outlet_gis_id) in terminal_ids
            )
            if allow_dry_autodetect and not requested_is_terminal and terminal_ids:
                best_gid = _pick_best_flowing_gis_id(table, outlet_gis_id, txtinout_dir)
                if best_gid is not None:
                    alt = _extract_flo_out_rows(table, best_gid)
                    if not alt.empty:
                        alt["sim"] = _normalize_discharge_units(alt["sim"], cand.name)
                        if float(alt["sim"].abs().sum()) > 0.0:
                            log.warning(
                                "Requested outlet GIS %s is non-terminal (%s); "
                                "auto-upgrading to terminal GIS %s.",
                                outlet_gis_id,
                                "has flow" if float(df["sim"].abs().sum()) > 0 else "dry",
                                best_gid,
                            )
                            diagnostics["selected_outlet_gis_id"] = int(best_gid)
                            diagnostics["outlet_autodetected"] = True
                            diagnostics["outlet_selection_reason"] = _non_terminal_upgrade_reason(terminal_ids)
                            diagnostics["sim_source_file"] = cand.name
                            diagnostics["sim_source_sha256"] = _sha256_file(cand)

                            # Check if the terminal is truly isolated (zero flow)
                            # vs just low during spin-up. Only upgrade when
                            # the terminal has absolutely zero cumulative flow.
                            term_sum = float(alt["sim"].abs().sum())
                            if term_sum < 1e-10:
                                max_gid = _pick_best_flowing_gis_id_unrestricted(table)
                                if max_gid is not None and int(max_gid) != int(best_gid):
                                    max_alt = _extract_flo_out_rows(table, max_gid)
                                    if not max_alt.empty:
                                        max_alt["sim"] = _normalize_discharge_units(max_alt["sim"], cand.name)
                                        max_sum = float(max_alt["sim"].abs().sum())
                                        if max_sum > 0:
                                            log.warning(
                                                "Terminal outlet GIS %s has zero flow; "
                                                "using highest-flow channel GIS %s.",
                                                best_gid, max_gid,
                                            )
                                            diagnostics["selected_outlet_gis_id"] = int(max_gid)
                                            diagnostics["outlet_selection_reason"] = "isolated_terminal_upgrade"
                                            return max_alt, diagnostics

                            return alt, diagnostics
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
