from __future__ import annotations
"""Fetch daily discharge data from USGS NWIS via HyRiver (pygeohydro)."""

import logging
from typing import Optional
from pathlib import Path
import pandas as pd

log = logging.getLogger(__name__)

def fetch_usgs_daily_q(
    usgs_id: str, 
    start_date: str, 
    end_date: str, 
    out_csv: Optional[Path | str] = None
) -> pd.Series:
    """Fetch daily mean discharge (parameter 00060) from NWIS and convert to cms.
    
    Args:
        usgs_id: 8-digit or longer USGS site number.
        start_date: ISO 8601 start date (e.g. '2000-01-01').
        end_date: ISO 8601 end date (e.g. '2010-12-31').
        out_csv: Optional path to cache the observed series.
        
    Returns:
        Pandas Series of Daily Discharge in m³/s with DatetimeIndex.
    """
    try:
        from pygeohydro import NWIS
    except ImportError as e:
        raise ImportError("pygeohydro is required to fetch USGS data. Install with swatplus-builder[hyriver]") from e

    log.info("Fetching USGS NWIS daily streamflow for site %s (%s to %s)", usgs_id, start_date, end_date)
    
    nwis = NWIS()
    # 00060 is discharge in cubic feet per second
    q_df = nwis.get_streamflow(usgs_id, dates=(start_date, end_date), freq="dv")
    
    if q_df.empty:
        raise ValueError(f"No streamflow data returned for site {usgs_id} in requested date range.")

    usgs_col = f"USGS-{usgs_id}"
    if usgs_col not in q_df.columns:
        # Fallback if structure changes
        usgs_col = q_df.columns[0]
        
    # Convert cfs -> cms
    q_cms = q_df[usgs_col] * 0.028316846592
    q_cms.name = "obs"
    
    # Strip timezone for cleaner alignment with SWAT
    if q_cms.index.tz is not None:
        q_cms.index = q_cms.index.tz_localize(None)

    if out_csv:
        out_csv = Path(out_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        q_cms.to_csv(out_csv, index_label="date")
        log.info("Saved observed data to %s", out_csv)

    return q_cms
