"""Post-converter verification gate for full-mode TxtInOut.

Checks all D1–D4 invariants that were discovered to cause silent engine failure.
Raises ``ConversionVerificationError`` loudly on any violation, preventing
downstream engine runs on malformed topology.

Invariants checked:
  D1 — codes.bsn flags:  rte_cha=1, swift_out=0, uhyd=0, soil_p=1, i_fpwet=0
  D2 — file.cio connect block: outlet.con must NOT appear at any position
  D3 — file.cio connect block: chandeg.con must appear at position 13 (1-based)
  D4 — aquifer.con: no row may have obj_typ == "cha" (must be "sdc")

These are exact engine requirements derived from engine source analysis
(input_file_module.f90:53, hyd_connect.f90:256-258).  Any deviation means the
engine silently routes zero flow or crashes with SIGSEGV.

Usage::

    from swatplus_builder.full_mode.verify_conversion import verify_conversion
    verify_conversion(tio_path)   # raises if invariants violated
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ConversionVerificationError(Exception):
    """Raised when a post-converter invariant is violated.

    The message contains the specific defect label (D1/D2/D3/D4) and exact
    remediation so agents can self-diagnose without guessing.
    """


# ── D1: codes.bsn required flag values ────────────────────────────────────────

_D1_REQUIRED: dict[str, str] = {
    "rte_cha": "1",
    "swift_out": "0",
    "uhyd": "0",
    "soil_p": "1",
    "i_fpwet": "0",
}


def _check_d1_codes_bsn(tio: Path) -> list[str]:
    """Return list of D1 violation messages (empty = pass).

    codes.bsn uses SWAT+ tabular format: line 0 = title, line 1 = headers,
    line 2 = values.  We parse header→value pairs from those two rows.
    """
    path = tio / "codes.bsn"
    if not path.exists():
        return [f"D1: codes.bsn missing from {tio}"]
    lines = path.read_text().split("\n")
    # Filter out empty lines keeping original indices
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < 3:
        return ["D1: codes.bsn too short (expected title + header + values row)"]

    headers = non_empty[1].split()
    values = non_empty[2].split()
    found: dict[str, str] = {}
    for i, h in enumerate(headers):
        if i < len(values):
            found[h] = values[i]

    violations = []
    for key, expected in _D1_REQUIRED.items():
        actual = found.get(key)
        if actual is None:
            violations.append(
                f"D1: codes.bsn missing key '{key}' (expected {expected})"
            )
        elif actual != expected:
            violations.append(
                f"D1: codes.bsn {key}={actual!r} but engine requires {expected!r}; "
                f"run _convert_codes_bsn() in topology_converter"
            )
    return violations


# ── D2/D3: file.cio connect block ─────────────────────────────────────────────

def _parse_connect_tokens(tio: Path) -> list[str] | None:
    """Return the connect-line tokens from file.cio (after 'connect'), or None."""
    path = tio / "file.cio"
    if not path.exists():
        return None
    for line in path.read_text().split("\n"):
        stripped = line.strip()
        if stripped.startswith("connect"):
            parts = stripped.split()
            return parts[1:]  # everything after the keyword 'connect'
    return None


def _check_d2_no_outlet_con(tokens: list[str]) -> list[str]:
    """Return D2 violation messages."""
    violations = []
    for i, tok in enumerate(tokens):
        if tok == "outlet.con":
            violations.append(
                f"D2: file.cio connect position {i + 1} contains 'outlet.con'; "
                f"must be nulled — run _convert_file_cio() in topology_converter"
            )
    return violations


def _check_d3_chandeg_at_position_13(tokens: list[str]) -> list[str]:
    """Return D3 violation messages.

    Engine position 13 (1-based) == tokens[12] (0-based).
    """
    violations = []
    if len(tokens) < 13:
        violations.append(
            f"D3: file.cio connect block has only {len(tokens)} tokens; "
            f"need ≥13 to place chandeg.con at position 13"
        )
        return violations
    actual = tokens[12]
    if actual != "chandeg.con":
        violations.append(
            f"D3: file.cio connect position 13 = {actual!r}; "
            f"engine requires 'chandeg.con' here "
            f"(input_file_module.f90:53) — run _convert_file_cio() in topology_converter"
        )
    # Also flag if chandeg.con appears at any other position (would be wrong AND D3)
    for i, tok in enumerate(tokens):
        if tok == "chandeg.con" and i != 12:
            violations.append(
                f"D3: 'chandeg.con' found at connect position {i + 1} (expected 13 only)"
            )
    return violations


# ── D4: aquifer.con obj_typ must not be "cha" ─────────────────────────────────

def _check_d4_aquifer_con(tio: Path) -> list[str]:
    """Return D4 violation messages."""
    path = tio / "aquifer.con"
    if not path.exists():
        return [f"D4: aquifer.con missing from {tio}"]
    violations = []
    lines = path.read_text().split("\n")
    if len(lines) < 3:
        return []
    header_tokens = lines[1].split() if len(lines) > 1 else []
    try:
        obj_typ_idx = header_tokens.index("obj_typ")
    except ValueError:
        return ["D4: aquifer.con has no 'obj_typ' column; cannot verify D4"]
    for lineno, ln in enumerate(lines[2:], start=3):
        if not ln.strip():
            continue
        toks = ln.split()
        if len(toks) <= obj_typ_idx:
            continue
        val = toks[obj_typ_idx]
        if val == "cha":
            violations.append(
                f"D4: aquifer.con line {lineno} obj_typ='cha'; "
                f"must be 'sdc' for sdc/chandeg topology "
                f"(hyd_connect.f90:256-258) — run _convert_aquifer_con() in topology_converter"
            )
    return violations


# ── Additional structural checks ──────────────────────────────────────────────

def _check_chandeg_exists(tio: Path) -> list[str]:
    """chandeg.con must exist and channel.con must not (idempotency marker)."""
    violations = []
    if not (tio / "chandeg.con").exists():
        violations.append(
            "STRUCT: chandeg.con not found in TxtInOut; "
            "topology conversion has not been run"
        )
    if (tio / "channel.con").exists():
        violations.append(
            "STRUCT: channel.con still present; "
            "_cleanup_channel_files() was not called or conversion is incomplete"
        )
    return violations


# ── Public entry point ────────────────────────────────────────────────────────

def verify_conversion(txtinout: Path | str, *, strict: bool = True) -> dict:
    """Verify all D1–D4 post-converter invariants for a full-mode TxtInOut.

    Args:
        txtinout: path to the converted TxtInOut directory.
        strict: if True (default) raise ``ConversionVerificationError`` on any
                violation.  If False, return the results dict without raising
                (useful for diagnostic reporting).

    Returns:
        dict with keys ``pass`` (bool) and ``violations`` (list[str]).

    Raises:
        ConversionVerificationError: if ``strict=True`` and any check fails.
    """
    tio = Path(txtinout).expanduser().resolve()
    if not tio.is_dir():
        raise ConversionVerificationError(f"TxtInOut not found: {tio}")

    violations: list[str] = []

    # Structural: chandeg.con present, channel.con absent
    violations += _check_chandeg_exists(tio)

    # D1 — codes.bsn flags
    violations += _check_d1_codes_bsn(tio)

    # D2 + D3 — file.cio connect block
    tokens = _parse_connect_tokens(tio)
    if tokens is None:
        violations.append("D2/D3: file.cio missing or has no 'connect' line")
    else:
        violations += _check_d2_no_outlet_con(tokens)
        violations += _check_d3_chandeg_at_position_13(tokens)

    # D4 — aquifer.con obj_typ
    violations += _check_d4_aquifer_con(tio)

    result = {"pass": len(violations) == 0, "violations": violations}

    if violations:
        summary = "\n  ".join(violations)
        msg = (
            f"Conversion verification FAILED for {tio.name} "
            f"({len(violations)} violation(s)):\n  {summary}"
        )
        logger.error(msg)
        if strict:
            raise ConversionVerificationError(msg)
    else:
        logger.info("Conversion verification passed: %s", tio.name)

    return result
