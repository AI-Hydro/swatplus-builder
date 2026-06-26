"""Fetch daily discharge data from USGS NWIS via HyRiver (pygeohydro)."""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

def fetch_usgs_daily_q(
    usgs_id: str, 
    start_date: str, 
    end_date: str, 
    out_csv: Path | str | None = None
) -> pd.Series:
    """Fetch daily mean discharge (parameter 00060) from NWIS in m3/s.
    
    Args:
        usgs_id: 8-digit or longer USGS site number.
        start_date: ISO 8601 start date (e.g. '2000-01-01').
        end_date: ISO 8601 end date (e.g. '2010-12-31').
        out_csv: Optional path to cache the observed series.
        
    Returns:
        Pandas Series of Daily Discharge in m³/s with DatetimeIndex.
    """
    cache_path = _global_cache_path(usgs_id, start_date, end_date)
    cached = _load_cached_observed(out_csv, start_date, end_date) if out_csv else None
    if cached is None:
        cached = _load_cached_observed(cache_path, start_date, end_date)
    if cached is not None:
        log.info("Using cached observed streamflow for site %s", usgs_id)
        if out_csv:
            out_csv = Path(out_csv)
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            cached.to_csv(out_csv, index_label="date")
        return cached

    try:
        from pygeohydro import NWIS
    except ImportError as e:
        raise ImportError("pygeohydro is required to fetch USGS data. Install with swatplus-builder[hyriver]") from e

    log.info("Fetching USGS NWIS daily streamflow for site %s (%s to %s)", usgs_id, start_date, end_date)
    
    nwis = NWIS()
    # 00060 is discharge in cubic feet per second in NWIS raw services.
    # pygeohydro NWIS.get_streamflow already normalizes to m3/s.
    q_df = _fetch_streamflow_with_retries(nwis, usgs_id, start_date, end_date)
    
    if q_df.empty:
        raise ValueError(f"No streamflow data returned for site {usgs_id} in requested date range.")

    usgs_col = f"USGS-{usgs_id}"
    if usgs_col not in q_df.columns:
        # Fallback if structure changes
        usgs_col = q_df.columns[0]
        
    q_cms = q_df[usgs_col].astype(float)
    q_cms.name = "obs"
    
    # Strip timezone for cleaner alignment with SWAT
    if q_cms.index.tz is not None:
        q_cms.index = q_cms.index.tz_localize(None)

    if out_csv:
        out_csv = Path(out_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        q_cms.to_csv(out_csv, index_label="date")
        log.info("Saved observed data to %s", out_csv)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    q_cms.to_csv(cache_path, index_label="date")

    return q_cms


def _fetch_streamflow_with_retries(nwis, usgs_id: str, start_date: str, end_date: str) -> pd.DataFrame:
    max_attempts = int(os.environ.get("SWATPLUS_NWIS_FETCH_MAX_ATTEMPTS", "4"))
    base_s = float(os.environ.get("SWATPLUS_NWIS_FETCH_RETRY_BASE_S", "1.0"))
    cap_s = float(os.environ.get("SWATPLUS_NWIS_FETCH_RETRY_CAP_S", "20.0"))
    attempt = 0
    while True:
        attempt += 1
        try:
            return nwis.get_streamflow(usgs_id, dates=(start_date, end_date), freq="dv")
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            delay = min(cap_s, base_s * (2 ** (attempt - 1)))
            jitter = random.uniform(0.0, max(0.1, delay * 0.25))
            sleep_s = delay + jitter
            log.warning(
                "NWIS streamflow fetch attempt %d/%d failed for %s: %s; retrying in %.1fs",
                attempt,
                max_attempts,
                usgs_id,
                exc,
                sleep_s,
            )
            time.sleep(sleep_s)


def _load_cached_observed(
    out_csv: Path | str | None,
    start_date: str,
    end_date: str,
) -> pd.Series | None:
    if out_csv is None:
        return None
    path = Path(out_csv)
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:
        return None
    if df.empty:
        return None
    column = "obs" if "obs" in df.columns else df.columns[0]
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return None
    if getattr(series.index, "tz", None) is not None:
        series.index = series.index.tz_localize(None)
    series.index = pd.to_datetime(series.index).normalize()
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    clipped = series.loc[(series.index >= start) & (series.index <= end)]
    if clipped.empty:
        return None
    if clipped.index.min() > start or clipped.index.max() < end:
        return None
    clipped = clipped.copy()
    clipped.name = "obs"
    return clipped


def _global_cache_path(usgs_id: str, start_date: str, end_date: str) -> Path:
    root = Path(os.environ.get("SWATPLUS_NWIS_CACHE_DIR", "~/.cache/swatplus-builder/nwis_daily_q")).expanduser()
    safe_id = "".join(ch for ch in str(usgs_id) if ch.isalnum() or ch in {"-", "_"})
    return root / f"{safe_id}_{start_date}_{end_date}.csv"
