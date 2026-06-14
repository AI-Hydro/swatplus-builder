"""Post-editor full SWAT+ routing fixes.

Editor v3.2.0 generates sdc/chandeg routing natively but still needs
post-processing for engine rev 60.5.7 compatibility:

1. codes.bsn: rte_cha=1, swift_out=0, uhyd=0, soil_p=1, i_fpwet=0
2. rout_unit.def: two elements per RU (source HRU + sink sdc/channel)
3. rout_unit.con: split total flow into sur + lat hyd type entries
4. chandeg.con: terminal outlet connection (editor omits out routing)

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
    """Add each routing unit's own negative sdc/channel element.

    The engine requires two elements per RU: a positive source (HRU) and
    a negative sink (sdc/channel). The negative element is the routing unit's
    own sdc element, not the downstream target from ``rout_unit.con``. Reusing a
    downstream negative element across multiple RUs causes ``ru_read_elements``
    to allocate the same object twice and crash in ``hyd_connect``.
    """
    rdef = _require(tio, "rout_unit.def")

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
            out.append(
                f"      {ru_id}             {parts[1]}         2      {elem_id}     -{ru_id}"
            )
        else:
            out.append(ln)

    rdef.write_text("\n".join(out))


def _fix_rout_unit_con(tio: Path) -> None:
    """Route RU surface/lateral hydrographs explicitly without double-counting.

    Editor v3.2.0 generates a single ``tot`` route per RU. For sdc/chandeg
    routing, explicit ``sur`` and ``lat`` routes are needed for runoff and
    lateral flow to reach channels. Keeping ``tot`` alongside ``sur`` and
    ``lat`` double-routes water in current SWAT+ full-mode outputs, so collapse
    either old ``tot``-only or prior ``tot+sur+lat`` rows to ``sur+lat``.
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
            out.append(" ".join(_normalized_rout_unit_con_parts(parts)))
        else:
            out.append(ln)

    ruc.write_text("\n".join(out))


def _normalized_rout_unit_con_parts(parts: list[str]) -> list[str]:
    prefix = parts[:13]
    groups = _routing_groups(parts[13:], int(parts[12]))
    if not groups:
        return parts

    primary = next((group for group in groups if group[0] == "sdc"), groups[0])
    target = (primary[0], primary[1])
    target_groups = [group for group in groups if (group[0], group[1]) == target]
    target_hyd_types = {group[2] for group in target_groups}

    if "tot" in target_hyd_types:
        groups = [group for group in groups if not ((group[0], group[1]) == target and group[2] == "tot")]
        for hyd_typ in ("sur", "lat"):
            if hyd_typ not in {group[2] for group in groups if (group[0], group[1]) == target}:
                groups.append((target[0], target[1], hyd_typ, "1.00000"))

    prefix[12] = str(len(groups))
    flat: list[str] = []
    for group in groups:
        flat.extend(group)
    return prefix + flat


def _routing_groups(tokens: list[str], out_tot: int) -> list[tuple[str, str, str, str]]:
    groups: list[tuple[str, str, str, str]] = []
    for idx in range(0, min(len(tokens), out_tot * 4), 4):
        group = tokens[idx : idx + 4]
        if len(group) == 4:
            groups.append((group[0], group[1], group[2], group[3]))
    return groups


def _fix_chandeg_con_outlet(tio: Path) -> None:
    """Ensure chandeg.con has a terminal outlet connection.

    Editor v3.2.0 generates sdc cascade but omits the final ``out 1 tot 1.0``
    entry on the terminal channel.  This leaves water trapped in the channel
    network — it enters (surq_cha > 0) but never reaches the outlet point.

    We find the dead-end channel (referenced as a target but with no outgoing
    routing) and append an ``out 1 tot 1.0`` routing quad.
    """
    cd = _require(tio, "chandeg.con")
    lines = cd.read_text().split("\n")
    if len(lines) < 3:
        return

    # Parse routing graph — collect ALL channels, not just those with routes
    routes: dict[str, str] = {}
    all_ids: set[str] = set()
    for _i, ln in enumerate(lines[2:], start=2):
        if not ln.strip():
            continue
        parts = ln.split()
        if len(parts) < 14:
            continue
        cid = parts[0]
        all_ids.add(cid)
        out_tot = int(parts[12])
        for j in range(13, min(len(parts), 13 + out_tot * 4), 4):
            if j + 1 < len(parts):
                obj_typ = parts[j]
                obj_id = parts[j + 1]
                if obj_typ == "out":
                    return  # already has outlet — nothing to fix
                if obj_typ == "sdc":
                    routes[cid] = obj_id

    # Find terminal: referenced as a target but has no outgoing route
    referenced = set(routes.values())
    terminal = referenced - set(routes.keys())
    if not terminal:
        # Fallback: last channel by ID
        terminal = {max(all_ids, key=int)} if all_ids else set()

    if not terminal:
        raise RoutingFixError("Cannot determine terminal channel for outlet fix")

    terminal_id = sorted(terminal, key=int)[-1]

    # Append outlet routing to terminal channel
    out_lines = []
    found_terminal = False
    for ln in lines:
        if not found_terminal and ln.strip():
            parts = ln.split()
            # chandeg.con data rows: leading whitespace, parts start with id
            row_id = parts[0]
            if row_id == terminal_id:
                old_out_tot = int(parts[12])
                new_out_tot = old_out_tot + 1
                parts[12] = str(new_out_tot)
                base = " ".join(parts)
                extra = "           out         1           tot       1.00000"
                out_lines.append(base + extra)
                found_terminal = True
                continue
        out_lines.append(ln)

    if not found_terminal:
        raise RoutingFixError(f"Terminal channel {terminal_id} not found in chandeg.con")

    cd.write_text("\n".join(out_lines))


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
    negative_elements: list[str] = []
    for ln in rdef[2:]:
        if ln.strip():
            parts = ln.split()
            if len(parts) >= 3 and parts[2] != "2":
                errors.append(
                    f"rout_unit.def {parts[0]} elem_tot={parts[2]} expected 2"
                )
                break
            if len(parts) >= 5:
                neg = [p for p in parts[3:] if p.startswith("-")]
                if not neg:
                    errors.append(
                        f"rout_unit.def {parts[0]} missing negative sdc element"
                    )
                    break
                negative_elements.extend(neg)

    duplicates = sorted(
        {elem for elem in negative_elements if negative_elements.count(elem) > 1},
        key=lambda value: int(value),
    )
    if duplicates:
        errors.append(
            "rout_unit.def has duplicate negative sdc elements: "
            + ", ".join(duplicates)
        )

    # Check rout_unit.con has explicit sur/lat routes and no double-counting tot.
    ruc = (tio / "rout_unit.con").read_text()
    if " sur " not in ruc:
        errors.append("rout_unit.con missing 'sur' hyd type entries")
    if " lat " not in ruc:
        errors.append("rout_unit.con missing 'lat' hyd type entries")
    if " tot " in ruc:
        errors.append("rout_unit.con contains 'tot' hyd type entries that double-count sur/lat routing")

    if errors:
        raise RoutingFixError(
            f"Full SWAT+ routing fixes validation failed: {'; '.join(errors)}"
        )
