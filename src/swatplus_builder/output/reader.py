"""Whitespace-delimited SWAT+ output file parser.

SWAT+ writes its text outputs in a remarkably simple (and undocumented)
layout that the engine's Fortran ``write(*, *)`` statements naturally
produce. Every ``*_day.txt`` / ``*_mon.txt`` / ``*_yr.txt`` / ``*_aa.txt``
file follows the same shape::

    basin_wb_aa                              annual average values                    <-- line 1: title
       jday    mon    day     yr   unit    gis_id   name    precip    snofall  ...    <-- line 2: column names
                                                            mm        mm       ...    <-- line 3: units (may have fewer tokens)
          0      0      0      0      1        0   bsn    1234.5     12.3     ...    <-- line 4+: data rows

Notes from reverse-engineering real outputs:

* Column names are always whitespace-separated tokens, one per column.
* The units line is *informational* — many columns carry ``n/a`` which
  the engine writes as nothing at all, so the units row can have fewer
  tokens than the header row. We therefore read units best-effort and
  do not let them drive column count.
* Data rows have *exactly* ``len(columns)`` whitespace-separated tokens.
  The first 7 are identifiers (``jday``, ``mon``, ``day``, ``yr``,
  ``unit``, ``gis_id``, ``name``); the rest are floats.
* Rows are never wrapped across physical lines — SWAT+ prints a single
  ``write`` per row. We can safely use ``str.split()`` per line.

The parser is deliberately permissive:

* Lines that are blank (whitespace only) are skipped.
* A malformed data row (wrong token count, unparseable numerics) raises
  :class:`~swatplus_builder.errors.SwatBuilderExternalError` with the
  offending line and its 1-indexed line number in ``.context`` — easier
  for agents to triage than silently truncating.
* ``name`` is kept as a string; every other non-identifier field is
  coerced to ``float``. Identifiers (``jday``, ``mon``, ``day``, ``yr``,
  ``unit``, ``gis_id``) become ``int``. Anything else stays ``float``.

The parser is pure-stdlib; pandas is *not* a dependency of this module.
Agents that want a DataFrame can trivially call
``pd.DataFrame(table.rows)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import SwatBuilderExternalError, SwatBuilderInputError

__all__ = [
    "OutputTable",
    "read_basin_wb_aa",
    "read_channel_sd_aa",
    "read_output_file",
]

# First seven columns in every SWAT+ object-level output file (basin, LSU,
# HRU, channel, …). Hard-coded because the engine never varies them.
_ID_COLUMNS_INT: frozenset[str] = frozenset(
    {"jday", "mon", "day", "yr", "unit", "gis_id"}
)
_ID_COLUMNS_STR: frozenset[str] = frozenset({"name"})


@dataclass
class OutputTable:
    """One parsed SWAT+ text output file.

    Attributes:
        path: Absolute path to the source file.
        title: Raw first line (sans trailing whitespace); useful for
            human-facing reports but not parsed further.
        columns: Ordered list of column names as they appeared in the
            header line (line 2).
        units: Best-effort ordered list of unit labels from line 3.
            ``len(units)`` may be less than ``len(columns)`` because
            identifier columns (e.g. ``name``) carry no unit. Missing
            entries are padded with empty strings so that
            ``units[i]`` always aligns with ``columns[i]`` when the
            unit exists.
        rows: Each row is a dict keyed by column name. ``name`` values
            stay as ``str``; identifier ints stay as ``int``; every
            other field is ``float``.
    """

    path: Path
    title: str
    columns: list[str]
    units: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)

    def column(self, name: str) -> list[Any]:
        """Return the full vertical slice for ``name`` across all rows.

        Raises:
            KeyError: if ``name`` is not a column of this table.
        """
        if name not in self.columns:
            raise KeyError(
                f"column {name!r} not found; available: {self.columns!r}"
            )
        return [row[name] for row in self.rows]


def read_output_file(path: Path | str) -> OutputTable:
    """Parse a SWAT+ text output file into an :class:`OutputTable`.

    Args:
        path: Path to a ``*.txt`` / ``*.out`` file written by the SWAT+
            engine (e.g. ``basin_wb_aa.txt``).

    Returns:
        An :class:`OutputTable` with ``columns``, ``units``, and
        ``rows`` populated.

    Raises:
        SwatBuilderInputError: the path does not exist or is not a file.
        SwatBuilderExternalError: the file is structurally invalid —
            empty, missing a header line, or containing a data row
            whose token count doesn't match ``len(columns)``.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise SwatBuilderInputError(
            f"SWAT+ output file does not exist: {p}", path=str(p)
        )

    raw_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not raw_lines:
        raise SwatBuilderExternalError(
            f"SWAT+ output file is empty: {p}", path=str(p)
        )

    title = raw_lines[0].rstrip()

    # Find the header line — the first non-blank line after the title.
    header_idx: int | None = None
    for idx in range(1, len(raw_lines)):
        if raw_lines[idx].strip():
            header_idx = idx
            break
    if header_idx is None:
        raise SwatBuilderExternalError(
            f"SWAT+ output file has a title but no header/data: {p}",
            path=str(p),
            title=title,
        )

    columns = raw_lines[header_idx].split()
    if not columns:
        raise SwatBuilderExternalError(
            f"SWAT+ output header line is blank: {p}:{header_idx + 1}",
            path=str(p),
            line_no=header_idx + 1,
        )

    # The next non-blank line *may* be a units line. We only accept it
    # as units if it has strictly fewer tokens than the header AND none
    # of its tokens parse as numbers — otherwise it's a data row (some
    # SWAT+ builds skip the units line entirely).
    cursor = header_idx + 1
    units: list[str] = []
    data_start = cursor
    while cursor < len(raw_lines) and not raw_lines[cursor].strip():
        cursor += 1
    if cursor < len(raw_lines):
        candidate = raw_lines[cursor].split()
        if candidate and _looks_like_units(candidate, len(columns)):
            units = candidate
            data_start = cursor + 1
        else:
            data_start = cursor

    # Pad units so units[i] aligns with columns[i]. SWAT+ writes the
    # units row without entries for identifier columns (``jday``,
    # ``mon``, ``day``, ``yr``, ``unit``, ``gis_id``, ``name``) — those
    # are always at the *front*. So the short units line maps to the
    # trailing numeric columns and we left-pad with empty strings.
    if units and len(units) < len(columns):
        units = [""] * (len(columns) - len(units)) + units

    rows: list[dict[str, Any]] = []
    for idx in range(data_start, len(raw_lines)):
        line = raw_lines[idx]
        if not line.strip():
            continue
        tokens = line.split()
        if len(tokens) != len(columns):
            raise SwatBuilderExternalError(
                f"SWAT+ output row has {len(tokens)} tokens but header "
                f"has {len(columns)} columns at {p}:{idx + 1}",
                path=str(p),
                line_no=idx + 1,
                expected=len(columns),
                got=len(tokens),
                sample=line[:200],
            )
        row: dict[str, Any] = {}
        for col, tok in zip(columns, tokens):
            row[col] = _coerce(col, tok, path=p, line_no=idx + 1)
        rows.append(row)

    return OutputTable(
        path=p, title=title, columns=columns, units=units, rows=rows
    )


# ---------------------------------------------------------------------------
# Specific readers
# ---------------------------------------------------------------------------


def read_basin_wb_aa(txtinout_dir: Path | str) -> OutputTable:
    """Parse ``<txtinout_dir>/basin_wb_aa.txt`` (basin water balance, AA).

    Convenience wrapper around :func:`read_output_file` with a clearer
    error message if the file is missing — usually a sign that
    ``print.prt`` didn't enable ``basin_wb`` with ``AVANN=y``.
    """
    return _read_named(txtinout_dir, "basin_wb_aa.txt")


def read_channel_sd_aa(txtinout_dir: Path | str) -> OutputTable:
    """Parse ``<txtinout_dir>/channel_sd_aa.txt`` (channel stream-discharge, AA)."""
    return _read_named(txtinout_dir, "channel_sd_aa.txt")


def _read_named(txtinout_dir: Path | str, name: str) -> OutputTable:
    d = Path(txtinout_dir).expanduser().resolve()
    if not d.is_dir():
        raise SwatBuilderInputError(
            f"txtinout_dir does not exist or is not a directory: {d}",
            txtinout_dir=str(d),
        )
    path = d / name
    if not path.is_file():
        raise SwatBuilderExternalError(
            f"{name} not found under {d}. Enable it in print.prt "
            "(AVANN=y for the matching print object) and re-run the engine.",
            txtinout_dir=str(d),
            missing=name,
        )
    return read_output_file(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _looks_like_units(tokens: list[str], n_columns: int) -> bool:
    """Heuristic: is ``tokens`` a units row or a data row?

    Units rows are short strings like ``mm``, ``ha-m``, ``m3``, ``kg``,
    ``m3/s`` — never pure numbers. Data rows always start with two
    integers (``jday mon``). We therefore classify as units iff no
    token parses as a number *and* token count is ``<=`` column count.
    """
    if len(tokens) > n_columns:
        return False
    for tok in tokens:
        try:
            float(tok)
        except ValueError:
            continue
        return False
    return True


def _coerce(col: str, tok: str, *, path: Path, line_no: int) -> Any:
    """Coerce ``tok`` to the right type for column ``col``.

    Identifier columns (``jday``, ``mon``, ``day``, ``yr``, ``unit``,
    ``gis_id``) become ``int``. ``name`` stays ``str``. Everything else
    becomes ``float``. Parse errors surface as
    :class:`SwatBuilderExternalError`.
    """
    if col in _ID_COLUMNS_STR:
        return tok
    if col in _ID_COLUMNS_INT:
        try:
            return int(tok)
        except ValueError as exc:
            raise SwatBuilderExternalError(
                f"SWAT+ output: expected int for {col!r} at "
                f"{path}:{line_no}, got {tok!r}",
                path=str(path),
                line_no=line_no,
                column=col,
                token=tok,
            ) from exc
    try:
        return float(tok)
    except ValueError as exc:
        raise SwatBuilderExternalError(
            f"SWAT+ output: expected float for {col!r} at "
            f"{path}:{line_no}, got {tok!r}",
            path=str(path),
            line_no=line_no,
            column=col,
            token=tok,
        ) from exc
