"""Parse SWAT+ engine text outputs into typed, agent-friendly summaries.

Public API:

* :class:`OutputTable` — the in-memory representation of one ``*_aa.txt``
  (or ``*_day/_mon/_yr.txt``) file: columns, units, rows (list of dicts).
* :func:`read_output_file` — generic whitespace parser for any SWAT+
  output file that follows the ``title → headers → units → data`` layout.
* :func:`read_basin_wb_aa` / :func:`read_channel_sd_aa` — specific
  readers that return an :class:`OutputTable` or raise
  :class:`~swatplus_builder.errors.SwatBuilderExternalError` if the file
  is missing.
* :func:`build_run_summary` — scan a ``TxtInOut/`` directory for known
  AA outputs and produce the ``dict[str, float]`` that populates
  :attr:`swatplus_builder.types.SwatPlusRun.summary`.

See ADR-023 for the parser contract and the canonical summary key list.
"""

from .reader import (
    OutputTable,
    read_basin_wb_aa,
    read_channel_sd_aa,
    read_output_file,
)
from .summary import SUMMARY_KEYS, build_run_summary

__all__ = [
    "OutputTable",
    "SUMMARY_KEYS",
    "build_run_summary",
    "read_basin_wb_aa",
    "read_channel_sd_aa",
    "read_output_file",
]
