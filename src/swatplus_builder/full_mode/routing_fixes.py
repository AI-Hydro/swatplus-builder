"""Post-editor full SWAT+ routing fixes.

Editor v3.2.0 generates sdc/chandeg routing natively but still needs
post-processing for engine rev 60.5.7 compatibility:

1. codes.bsn: rte_cha=1, swift_out=0, uhyd=0, soil_p=1, i_fpwet=0
2. rout_unit.def: two elements per RU (source HRU + sink sdc/channel)
3. rout_unit.con: route surface/lateral flow to channels and recharge to aquifers
4. aquifer.con: route deep recharge from shallow to deep aquifers
5. chandeg.con: terminal outlet connection (editor omits out routing)

The channel fixes are engine-verified on ``01547700``; the groundwater
recharge repair is independently engine-verified on ``03349000``.
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
    _fix_groundwater_recharge_routes(tio)
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
    """Add routing-unit HRU elements and each unit's own negative sdc element.

    In dominant-HRU mode, each routing unit has one positive ``rout_unit.ele``
    source element plus one negative sdc/channel element. In full-overlay mode,
    one routing unit can own many HRU elements; keeping only the first source
    silently disconnects the remaining HRUs from the routing network. The
    negative element is still the routing unit's own sdc element, not the
    downstream target from ``rout_unit.con``.
    """
    rdef = _require(tio, "rout_unit.def")

    lines = rdef.read_text().split("\n")
    if len(lines) < 3:
        raise RoutingFixError("rout_unit.def too short")

    hru_element_ids = _hru_element_ids(tio)
    data_rows: list[tuple[list[str], int | None]] = []
    starts: list[int | None] = []
    for ln in lines[2:]:
        if not ln.strip() or ln.strip().startswith("rout_unit"):
            data_rows.append(([ln], None))
            starts.append(None)
            continue
        parts = ln.split()
        start = _first_positive_int(parts[3:]) if len(parts) >= 4 else None
        data_rows.append((parts, start))
        starts.append(start)

    row_starts = [start for start in starts if start is not None]
    out = [lines[0], lines[1]]
    for parts_or_line, start in data_rows:
        if start is None:
            out.append(parts_or_line[0])
            continue

        parts = parts_or_line
        ru_id = parts[0]
        next_start = _next_start(row_starts, start)
        positive_elements = _positive_elements_for_range(
            hru_element_ids,
            start=start,
            next_start=next_start,
        )
        if not positive_elements:
            positive_elements = [start]

        elements = [str(value) for value in positive_elements] + [f"-{ru_id}"]
        out.append(
            f"      {ru_id}             {parts[1]}         {len(elements)}      "
            + "     ".join(elements)
        )

    rdef.write_text("\n".join(out))


def _hru_element_ids(tio: Path) -> list[int]:
    ele = tio / "rout_unit.ele"
    if not ele.exists():
        return []
    ids: list[int] = []
    for ln in ele.read_text().splitlines()[2:]:
        parts = ln.split()
        if len(parts) >= 4 and parts[2].lower() == "hru":
            try:
                ids.append(int(parts[0]))
            except ValueError:
                continue
    return sorted(set(ids))


def _first_positive_int(tokens: list[str]) -> int | None:
    for token in tokens:
        try:
            value = int(token)
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _next_start(starts: list[int], current: int) -> int | None:
    later = [value for value in starts if value > current]
    return min(later) if later else None


def _positive_elements_for_range(
    hru_element_ids: list[int],
    *,
    start: int,
    next_start: int | None,
) -> list[int]:
    if not hru_element_ids:
        return []
    return [
        value
        for value in hru_element_ids
        if value >= start and (next_start is None or value < next_start)
    ]


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


def _with_route(
    parts: list[str],
    route: tuple[str, str, str, str],
) -> list[str]:
    groups = _routing_groups(parts[13:], int(parts[12]))
    if any(group[:3] == route[:3] for group in groups):
        return parts
    groups.append(route)
    prefix = parts[:13]
    prefix[12] = str(len(groups))
    return prefix + [token for group in groups for token in group]


def _fix_groundwater_recharge_routes(tio: Path) -> None:
    """Connect routing-unit percolation to shallow and deep aquifers.

    Builder full mode creates one routing unit, shallow aquifer, and deep
    aquifer per subbasin. SWAT+ uses the ``rhg`` hydrologic type for both
    routing-unit recharge and the shallow fraction sent to the deep aquifer.
    Missing these routes leaves ``aquifer_*.txt`` recharge and flow at zero
    even when HRU percolation is positive.
    """
    aquifer_con = tio / "aquifer.con"
    if not aquifer_con.exists():
        return

    rout_unit_con = _require(tio, "rout_unit.con")
    ru_lines = rout_unit_con.read_text().split("\n")
    ru_rows = [line for line in ru_lines[2:] if line.strip()]
    ru_count = len(ru_rows)
    if ru_count == 0:
        return

    fixed_ru = [ru_lines[0], ru_lines[1]]
    for line in ru_lines[2:]:
        if not line.strip():
            fixed_ru.append(line)
            continue
        parts = line.split()
        if len(parts) < 17:
            raise RoutingFixError("Malformed rout_unit.con row while adding recharge")
        fixed_ru.append(" ".join(_with_route(parts, ("aqu", parts[0], "rhg", "1.00000"))))
    rout_unit_con.write_text("\n".join(fixed_ru))

    aqu_lines = aquifer_con.read_text().split("\n")
    aqu_rows = [line for line in aqu_lines[2:] if line.strip()]
    if len(aqu_rows) < ru_count:
        raise RoutingFixError(
            f"aquifer.con has {len(aqu_rows)} rows for {ru_count} routing units"
        )

    # Deep aquifers follow shallow aquifers in the Editor's internal ids.
    has_deep_aquifers = len(aqu_rows) >= 2 * ru_count
    fixed_aqu = [aqu_lines[0], aqu_lines[1]]
    shallow_index = 0
    for line in aqu_lines[2:]:
        if not line.strip():
            fixed_aqu.append(line)
            continue
        parts = line.split()
        shallow_index += 1
        if has_deep_aquifers and shallow_index <= ru_count:
            deep_id = str(ru_count + shallow_index)
            parts = _with_route(parts, ("aqu", deep_id, "rhg", "1.00000"))
        fixed_aqu.append(" ".join(parts))
    aquifer_con.write_text("\n".join(fixed_aqu))


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

    # Check rout_unit.def has internally consistent element lists and exactly
    # one own negative sdc element per routing unit.
    rdef = (tio / "rout_unit.def").read_text().split("\n")
    negative_elements: list[str] = []
    positive_elements: list[int] = []
    for ln in rdef[2:]:
        if ln.strip():
            parts = ln.split()
            if len(parts) < 4:
                errors.append(f"rout_unit.def malformed row: {ln}")
                break
            try:
                elem_tot = int(parts[2])
            except ValueError:
                errors.append(f"rout_unit.def {parts[0]} elem_tot={parts[2]} is not an integer")
                break
            elements = parts[3:]
            if elem_tot != len(elements):
                errors.append(
                    f"rout_unit.def {parts[0]} elem_tot={parts[2]} but has {len(elements)} elements"
                )
                break
            neg = [p for p in elements if p.startswith("-")]
            if neg != [f"-{parts[0]}"]:
                errors.append(
                    f"rout_unit.def {parts[0]} expected own negative sdc element -{parts[0]}, got {neg or 'none'}"
                )
                break
            negative_elements.extend(neg)
            for elem in elements:
                try:
                    value = int(elem)
                except ValueError:
                    continue
                if value > 0:
                    positive_elements.append(value)

    duplicates = sorted(
        {elem for elem in negative_elements if negative_elements.count(elem) > 1},
        key=lambda value: int(value),
    )
    if duplicates:
        errors.append(
            "rout_unit.def has duplicate negative sdc elements: "
            + ", ".join(duplicates)
        )

    hru_elements = _hru_element_ids(tio)
    if hru_elements:
        missing = sorted(set(hru_elements) - set(positive_elements))
        extra = sorted(set(positive_elements) - set(hru_elements))
        duplicate_positive = sorted(
            {elem for elem in positive_elements if positive_elements.count(elem) > 1}
        )
        if missing:
            preview = ", ".join(str(v) for v in missing[:10])
            suffix = "..." if len(missing) > 10 else ""
            errors.append(f"rout_unit.def missing HRU routing elements: {preview}{suffix}")
        if extra:
            preview = ", ".join(str(v) for v in extra[:10])
            suffix = "..." if len(extra) > 10 else ""
            errors.append(f"rout_unit.def references non-HRU positive elements: {preview}{suffix}")
        if duplicate_positive:
            preview = ", ".join(str(v) for v in duplicate_positive[:10])
            suffix = "..." if len(duplicate_positive) > 10 else ""
            errors.append(f"rout_unit.def duplicates HRU routing elements: {preview}{suffix}")

        # Every routing unit represents its full LSU. Editor writes each HRU's
        # LSU fraction directly from gis_hrus.arslp/arlsu; a sum below one
        # silently removes land area and its generated water from the model.
        ele_path = tio / "rout_unit.ele"
        fractions: dict[int, float] = {}
        for line in ele_path.read_text().splitlines()[2:]:
            parts = line.split()
            if len(parts) < 5 or parts[2].lower() != "hru":
                continue
            try:
                fractions[int(parts[0])] = float(parts[4])
            except ValueError:
                continue

        for line in rdef[2:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            element_ids: list[int] = []
            for value in parts[3:]:
                try:
                    element_id = int(value)
                except ValueError:
                    continue
                if element_id > 0:
                    element_ids.append(element_id)
            fraction_sum = sum(fractions.get(element_id, 0.0) for element_id in element_ids)
            if abs(fraction_sum - 1.0) > 1.0e-4:
                errors.append(
                    f"rout_unit.ele fractions for routing unit {parts[0]} sum to "
                    f"{fraction_sum:.6f}, expected 1.0"
                )
                break

    # Check rout_unit.con has explicit sur/lat routes and no double-counting tot.
    ruc_path = tio / "rout_unit.con"
    ruc = ruc_path.read_text()
    if " sur " not in ruc:
        errors.append("rout_unit.con missing 'sur' hyd type entries")
    if " lat " not in ruc:
        errors.append("rout_unit.con missing 'lat' hyd type entries")
    if " tot " in ruc:
        errors.append("rout_unit.con contains 'tot' hyd type entries that double-count sur/lat routing")

    aquifer_con = tio / "aquifer.con"
    if aquifer_con.exists():
        ru_rows = [line.split() for line in ruc.splitlines()[2:] if line.strip()]
        for parts in ru_rows:
            groups = _routing_groups(parts[13:], int(parts[12]))
            expected = ("aqu", parts[0], "rhg")
            if not any(group[:3] == expected for group in groups):
                errors.append(
                    f"rout_unit.con {parts[0]} missing recharge route to aquifer {parts[0]}"
                )
                break

        aqu_rows = [
            line.split()
            for line in aquifer_con.read_text().splitlines()[2:]
            if line.strip()
        ]
        ru_count = len(ru_rows)
        if len(aqu_rows) >= 2 * ru_count:
            for index, parts in enumerate(aqu_rows[:ru_count], start=1):
                groups = _routing_groups(parts[13:], int(parts[12]))
                expected = ("aqu", str(ru_count + index), "rhg")
                if not any(group[:3] == expected for group in groups):
                    errors.append(
                        f"aquifer.con {parts[0]} missing deep recharge route to aquifer {expected[1]}"
                    )
                    break

    if errors:
        raise RoutingFixError(
            f"Full SWAT+ routing fixes validation failed: {'; '.join(errors)}"
        )
