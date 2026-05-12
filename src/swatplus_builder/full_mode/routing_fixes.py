"""Post-editor full SWAT+ routing fixes.

Editor v3.2.0 generates sdc/chandeg routing natively but still needs
post-processing for engine rev 60.5.7 compatibility:

1. codes.bsn: rte_cha=1, swift_out=0, uhyd=0, soil_p=1, i_fpwet=0
2. rout_unit.def: two elements per RU (source HRU + sink sdc/channel)
3. rout_unit.con: sur + lat hyd type entries alongside tot

All three fixes are engine-verified active on 01547700 (Phase 3L.13).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class RoutingFixError(Exception):
    """Raised when a required fix cannot be applied."""


def apply_full_routing_fixes(txtinout: Path) -> None:
    """Apply all post-editor routing fixes to a full SWAT+ TxtInOut.

    Idempotent — safe to call multiple times.
    Raises RoutingFixError if a required file is missing or malformed.
    """
    tio = Path(txtinout).expanduser().resolve()
    if not tio.is_dir():
        raise RoutingFixError(f"TxtInOut not found: {tio}")

    _fix_codes_bsn(tio)
    _fix_rout_unit_def(tio)
    _fix_rout_unit_con(tio)
    _validate_fixes(tio)

    logger.info("Full routing fixes applied to %s", tio.name)


def _require(tio: Path, fname: str) -> Path:
    p = tio / fname
    if not p.exists():
        raise RoutingFixError(f"Required file missing: {p}")
    return p


def _fix_codes_bsn(tio: Path) -> None:
    """Set rte_cha=1 and companion flags for engine rev 60.5.7."""
    path = _require(tio, "codes.bsn")
    lines = path.read_text().split("\n")
    if len(lines) < 3:
        raise RoutingFixError("codes.bsn too short")
    h = lines[1].split()
    d = lines[2].split()
    overrides = {
        "rte_cha": "1",
        "swift_out": "0",
        "uhyd": "0",
        "soil_p": "1",
        "i_fpwet": "0",
    }
    for flag, val in overrides.items():
        if flag not in h:
            raise RoutingFixError(f"codes.bsn missing column: {flag}")
        idx = h.index(flag)
        if d[idx] != val:
            d[idx] = val
    lines[2] = " ".join(d)
    path.write_text("\n".join(lines))


def _fix_rout_unit_def(tio: Path) -> None:
    """Add negative sdc/channel sink element to each routing unit.

    The engine requires two elements per RU: a positive source (HRU) and
    a negative sink (sdc/channel). Editor v3.2.0 generates only the source.
    """
    rdef = _require(tio, "rout_unit.def")
    ruc = _require(tio, "rout_unit.con")

    # Read sdc target IDs from rout_unit.con
    ru_targets: dict[str, str] = {}
    for ln in ruc.read_text().split("\n")[2:]:
        if ln.strip():
            parts = ln.split()
            if len(parts) >= 15:
                ru_targets[parts[0]] = parts[14]

    lines = rdef.read_text().split("\n")
    if len(lines) < 3:
        raise RoutingFixError("rout_unit.def too short")

    out = [lines[0], lines[1]]
    for ln in lines[2:]:
        if not ln.strip() or ln.strip().startswith("rout_unit"):
            out.append(ln)
            continue
        parts = ln.split()
        if len(parts) >= 4:
            ru_id = parts[0]
            elem_id = parts[3]
            sdc_target = ru_targets.get(ru_id, ru_id)
            out.append(
                f"      {ru_id}             {parts[1]}         2      {elem_id}     -{sdc_target}"
            )
        else:
            out.append(ln)

    rdef.write_text("\n".join(out))


def _fix_rout_unit_con(tio: Path) -> None:
    """Add sur + lat hyd type entries to rout_unit.con.

    The reference (Tordera v6) has tot + sur + lat routing per RU.
    Editor v3.2.0 generates only tot. Surface runoff requires explicit
    sur routing to reach channels.
    """
    ruc = _require(tio, "rout_unit.con")
    lines = ruc.read_text().split("\n")
    if len(lines) < 3:
        raise RoutingFixError("rout_unit.con too short")

    out = [lines[0], lines[1]]
    for ln in lines[2:]:
        if not ln.strip():
            out.append(ln)
            continue
        parts = ln.split()
        if len(parts) >= 17:
            out_tot = int(parts[12]) + 2
            parts[12] = str(out_tot)
            sdc_id = parts[14]
            extra = (
                f"           sdc        {sdc_id}           sur       1.00000"
                f"           sdc        {sdc_id}           lat       1.00000"
            )
            out.append(" ".join(parts) + extra)
        else:
            out.append(ln)

    ruc.write_text("\n".join(out))


def _validate_fixes(tio: Path) -> None:
    """Fail loudly if any fix is missing or incorrect."""
    errors = []

    # Check codes.bsn
    codes = (tio / "codes.bsn").read_text().split("\n")
    h = codes[1].split()
    d = codes[2].split()
    for flag, expected in {
        "rte_cha": "1",
        "swift_out": "0",
        "uhyd": "0",
        "soil_p": "1",
        "i_fpwet": "0",
    }.items():
        if flag in h and d[h.index(flag)] != expected:
            errors.append(f"codes.bsn {flag}={d[h.index(flag)]} expected {expected}")

    # Check rout_unit.def has elem_tot=2
    rdef = (tio / "rout_unit.def").read_text().split("\n")
    for ln in rdef[2:]:
        if ln.strip():
            parts = ln.split()
            if len(parts) >= 3 and parts[2] != "2":
                errors.append(
                    f"rout_unit.def {parts[0]} elem_tot={parts[2]} expected 2"
                )
                break

    # Check rout_unit.con has sur entries
    ruc = (tio / "rout_unit.con").read_text()
    if " sur " not in ruc:
        errors.append("rout_unit.con missing 'sur' hyd type entries")

    if errors:
        raise RoutingFixError(
            f"Full SWAT+ routing fixes validation failed: {'; '.join(errors)}"
        )
