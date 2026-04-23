"""Build a flat ``dict[str, float]`` summary from a post-run ``TxtInOut/``.

This is the producer for :attr:`swatplus_builder.types.SwatPlusRun.summary`.
The goal is *not* to be comprehensive — full post-processing lives in
pandas/xarray downstream — but to give agents a handful of headline
numbers they can cite without opening any file themselves.

Current keys (all best-effort; missing when the source file isn't
present or the relevant column isn't in the build):

.. list-table::
   :header-rows: 1

   * - Key
     - Source
     - Unit
     - Definition
   * - ``precip_mm``
     - ``basin_wb_aa.precip``
     - mm/yr
     - Basin-average annual precipitation.
   * - ``et_mm``
     - ``basin_wb_aa.et``
     - mm/yr
     - Actual ET over the basin.
   * - ``pet_mm``
     - ``basin_wb_aa.pet``
     - mm/yr
     - Potential ET over the basin.
   * - ``surq_gen_mm``
     - ``basin_wb_aa.surq_gen``
     - mm/yr
     - Surface runoff generated.
   * - ``latq_mm``
     - ``basin_wb_aa.latq``
     - mm/yr
     - Lateral flow.
   * - ``perc_mm``
     - ``basin_wb_aa.perc``
     - mm/yr
     - Percolation below the soil profile.
   * - ``wateryld_mm``
     - ``basin_wb_aa.wateryld``
     - mm/yr
     - Water yield (surq + latq + gwq − tloss).
   * - ``mean_q_at_outlet_m3_per_s``
     - ``channel_sd_aa.flo_out``
     - m³/s
     - Max ``flo_out`` across all channels. Proxy for the basin
       outlet discharge since the engine does not tag which reach is
       the outlet; the topology guarantees the outlet channel has the
       largest cumulative flow. Divided by the number of seconds in
       a year to convert the AA ``flo_out`` (annual volume in m³)
       into a mean rate.
   * - ``channel_count``
     - ``channel_sd_aa``
     - n/a
     - Number of channel rows seen — sanity check.

Any missing source file is simply skipped; the caller sees a subset of
the canonical keys. No exception is raised — agents should treat an
empty summary as "engine ran but didn't produce AA outputs" rather
than as a crash.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..errors import SwatBuilderError
from .reader import (
    OutputTable,
    read_basin_wb_aa,
    read_channel_sd_aa,
)

log = logging.getLogger(__name__)

# Ordered canonical summary keys. Declared here so tests and
# documentation can refer to a single source of truth. This is *not*
# a schema: downstream tools must tolerate missing keys.
SUMMARY_KEYS: tuple[str, ...] = (
    "precip_mm",
    "et_mm",
    "pet_mm",
    "surq_gen_mm",
    "latq_mm",
    "perc_mm",
    "wateryld_mm",
    "mean_q_at_outlet_m3_per_s",
    "channel_count",
)

# basin_wb_aa → summary-key mapping. If a column is absent from the
# build (e.g. older engine), the key is simply skipped.
_BASIN_WB_MAP: dict[str, str] = {
    "precip": "precip_mm",
    "et": "et_mm",
    "pet": "pet_mm",
    "surq_gen": "surq_gen_mm",
    "latq": "latq_mm",
    "perc": "perc_mm",
    "wateryld": "wateryld_mm",
}

# Seconds per year (365.25 d). Matches SWAT+ engine's internal
# conversion for AA volume-to-rate calculations.
_SECONDS_PER_YEAR: float = 365.25 * 86400.0


def build_run_summary(txtinout_dir: Path | str) -> dict[str, float]:
    """Extract headline metrics from a post-run ``TxtInOut/`` directory.

    Args:
        txtinout_dir: Directory the SWAT+ engine ran in. Need not
            contain any particular output file; the function simply
            skips whichever ones aren't present.

    Returns:
        Dict whose keys are a subset of :data:`SUMMARY_KEYS`. Values
        are always ``float`` (even for counts) so consumers can round-
        trip through JSON.

    Never raises. Parser errors are logged at ``WARNING`` and the
    corresponding keys are omitted — agents should treat a crashed
    summary as recoverable, not fatal.
    """
    d = Path(txtinout_dir).expanduser().resolve()
    summary: dict[str, float] = {}

    _try_ingest_basin_wb(d, summary)
    _try_ingest_channel_sd(d, summary)

    return summary


def _try_ingest_basin_wb(txtinout: Path, summary: dict[str, float]) -> None:
    """Pull the configured set of keys from ``basin_wb_aa.txt``.

    The file normally has exactly one row (``unit=1``, the whole basin)
    but we handle multi-row builds by taking the *mean* across rows
    per column — matches what SWAT+ Editor does in its own check view.
    """
    try:
        table = read_basin_wb_aa(txtinout)
    except SwatBuilderError as exc:
        log.debug("skipping basin_wb_aa: %s", exc)
        return

    for src_col, summary_key in _BASIN_WB_MAP.items():
        if src_col not in table.columns:
            continue
        values = [
            row[src_col]
            for row in table.rows
            if isinstance(row.get(src_col), (int, float))
        ]
        if not values:
            continue
        summary[summary_key] = float(sum(values) / len(values))


def _try_ingest_channel_sd(txtinout: Path, summary: dict[str, float]) -> None:
    """Derive outlet discharge + row count from ``channel_sd_aa.txt``.

    We pick the channel with the largest ``flo_out`` as the outlet.
    This is topologically correct for well-formed SWAT+ projects (the
    outlet channel accumulates everything upstream), and sidesteps the
    fact that the engine does not emit an ``is_outlet`` flag in the
    AA output.

    ``flo_out`` in AA files is the annual volume (m³); we convert to a
    mean rate (m³/s) for caller-friendliness.
    """
    try:
        table = read_channel_sd_aa(txtinout)
    except SwatBuilderError as exc:
        log.debug("skipping channel_sd_aa: %s", exc)
        return

    summary["channel_count"] = float(len(table))

    if "flo_out" not in table.columns or not table.rows:
        return
    outlet_volume_m3 = _max_numeric(table, "flo_out")
    if outlet_volume_m3 is None:
        return
    summary["mean_q_at_outlet_m3_per_s"] = outlet_volume_m3 / _SECONDS_PER_YEAR


def _max_numeric(table: OutputTable, column: str) -> float | None:
    """Return the max numeric value in ``table[column]``, or ``None``."""
    best: float | None = None
    for row in table.rows:
        val: Any = row.get(column)
        if not isinstance(val, (int, float)):
            continue
        if best is None or float(val) > best:
            best = float(val)
    return best
