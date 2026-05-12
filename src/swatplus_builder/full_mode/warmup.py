"""Aquifer warmup support for full-mode SWAT+ runs.

Without spin-up, the shallow aquifer fills artificially during the first
simulation year, suppressing baseflow and underestimating streamflow.
This module edits time.sim and print.prt in-place to prepend warmup years
so the aquifer reaches approximate steady state before the evaluation period.

Methodology:
  - time.sim:  yrc_start  ← yrc_start - warmup_years
               day_start  ← 1
  - print.prt: nyskip     ← warmup_years

The engine then runs (evaluation_year + warmup_years) but only writes
output for the evaluation period (nyskip skips the warmup years).

Reference: Phase 3L.12.1 diagnosis — single-year simulation (2015) produced
  simulated mean = 0.566 m³/s vs observed 1.407 m³/s (40% of observed).
  Root cause: aquifer fills during year 1, suppressing baseflow.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class WarmupConfigError(Exception):
    """Raised when time.sim or print.prt cannot be updated for warmup."""


# ── time.sim ──────────────────────────────────────────────────────────────────

def _parse_time_sim(path: Path) -> dict[str, int]:
    """Return parsed time.sim as {day_start, yrc_start, day_end, yrc_end, step}."""
    if not path.exists():
        raise WarmupConfigError(f"time.sim not found: {path}")
    lines = path.read_text().split("\n")
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < 3:
        raise WarmupConfigError(f"time.sim too short: {path}")
    header = non_empty[1].split()
    values = non_empty[2].split()
    result: dict[str, int] = {}
    for h, v in zip(header, values):
        try:
            result[h] = int(v)
        except ValueError:
            pass
    for required in ("day_start", "yrc_start", "day_end", "yrc_end"):
        if required not in result:
            raise WarmupConfigError(
                f"time.sim missing required field '{required}': {path}"
            )
    return result


def _write_time_sim(path: Path, fields: dict[str, int]) -> None:
    """Rewrite time.sim with updated fields, preserving header and title."""
    lines = path.read_text().split("\n")
    non_empty_idx = [i for i, ln in enumerate(lines) if ln.strip()]
    if len(non_empty_idx) < 3:
        raise WarmupConfigError(f"time.sim too short to rewrite: {path}")
    header_idx = non_empty_idx[1]
    data_idx = non_empty_idx[2]
    header_tokens = lines[header_idx].split()
    new_vals = [str(fields.get(h, lines[data_idx].split()[i]))
                for i, h in enumerate(header_tokens)]
    # Maintain original column widths from header for alignment
    col_widths = [max(len(h), len(v)) for h, v in zip(header_tokens, new_vals)]
    lines[data_idx] = "".join(
        v.rjust(max(w, 10)) for w, v in zip(col_widths, new_vals)
    )
    path.write_text("\n".join(lines))


# ── print.prt nyskip ──────────────────────────────────────────────────────────

def _set_print_prt_nyskip(path: Path, nyskip: int) -> None:
    """Set the nyskip value in print.prt row 3 (0-indexed)."""
    if not path.exists():
        raise WarmupConfigError(f"print.prt not found: {path}")
    lines = path.read_text().split("\n")
    non_empty_idx = [i for i, ln in enumerate(lines) if ln.strip()]
    if len(non_empty_idx) < 3:
        raise WarmupConfigError(f"print.prt too short: {path}")
    data_idx = non_empty_idx[2]
    parts = lines[data_idx].split()
    if not parts:
        raise WarmupConfigError(f"print.prt data row empty: {path}")
    parts[0] = str(nyskip)
    lines[data_idx] = "  ".join(parts)
    path.write_text("\n".join(lines))


# ── Public API ────────────────────────────────────────────────────────────────

def apply_warmup(txtinout: Path | str, warmup_years: int) -> dict:
    """Prepend warmup years to a full-mode TxtInOut simulation period.

    Edits time.sim and print.prt in-place.  The engine will run
    (original_years + warmup_years) but skip warmup output via nyskip.

    Args:
        txtinout: path to converted TxtInOut directory.
        warmup_years: number of years to prepend (1–10).

    Returns:
        dict with keys ``yrc_start_original``, ``yrc_start_new``,
        ``yrc_end``, ``nyskip``.

    Raises:
        WarmupConfigError: if files are missing or malformed.
    """
    if not (1 <= warmup_years <= 10):
        raise WarmupConfigError(f"warmup_years must be in [1, 10], got {warmup_years}")

    tio = Path(txtinout).expanduser().resolve()
    if not tio.is_dir():
        raise WarmupConfigError(f"TxtInOut not found: {tio}")

    time_sim_path = tio / "time.sim"
    print_prt_path = tio / "print.prt"

    fields = _parse_time_sim(time_sim_path)
    original_yrc_start = fields["yrc_start"]
    new_yrc_start = original_yrc_start - warmup_years

    fields["yrc_start"] = new_yrc_start
    fields["day_start"] = 1
    _write_time_sim(time_sim_path, fields)
    _set_print_prt_nyskip(print_prt_path, warmup_years)

    result = {
        "yrc_start_original": original_yrc_start,
        "yrc_start_new": new_yrc_start,
        "yrc_end": fields["yrc_end"],
        "nyskip": warmup_years,
    }
    logger.info(
        "Warmup applied: %d years prepended; simulation %d–%d, "
        "output years %d–%d (nyskip=%d)",
        warmup_years, new_yrc_start, fields["yrc_end"],
        original_yrc_start, fields["yrc_end"], warmup_years,
    )
    return result


def remove_warmup(txtinout: Path | str, original_yrc_start: int) -> None:
    """Restore time.sim and print.prt to single-year evaluation (nyskip=0).

    Used to revert after a warmup run if the TxtInOut will be reused.

    Args:
        txtinout: path to TxtInOut directory.
        original_yrc_start: the evaluation year to restore (e.g. 2015).
    """
    tio = Path(txtinout).expanduser().resolve()
    fields = _parse_time_sim(tio / "time.sim")
    fields["yrc_start"] = original_yrc_start
    fields["day_start"] = 1
    _write_time_sim(tio / "time.sim", fields)
    _set_print_prt_nyskip(tio / "print.prt", 0)
    logger.info("Warmup removed: yrc_start restored to %d, nyskip=0", original_yrc_start)


def reset_and_apply_warmup(
    txtinout: Path | str,
    *,
    warmup_years: int,
    evaluation_start_year: int,
) -> dict:
    """Clear stale warmup edits, then apply warmup deterministically.

    This prevents repeated build/rebuild runs from cumulatively shifting
    ``time.sim.yrc_start`` further backward if warmup is re-applied.
    """
    if not (1 <= warmup_years <= 10):
        raise WarmupConfigError(f"warmup_years must be in [1, 10], got {warmup_years}")
    remove_warmup(txtinout, original_yrc_start=evaluation_start_year)
    return apply_warmup(txtinout, warmup_years=warmup_years)
