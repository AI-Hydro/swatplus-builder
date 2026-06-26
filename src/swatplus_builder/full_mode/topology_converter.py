"""Full SWAT+ topology converter: cha/channel.con → sdc/chandeg.con.

Converts editor v3.2.2 full-mode TxtInOut from the cha-based routing schema
(rte_cha=0, channel.con, cha objects) to the sdc-based routing schema that
engine rev 60.5.7 actually routes (rte_cha=1, chandeg.con, lcha objects).

Reference: Tordera v6 (tests/_artifacts/phase3l8/tordera_reference_copy/)
Schema rule: Phase 3L.9 (docs/FULL_MODE_ROUTING_SCHEMA_SPEC.md)
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .routing_fixes import _normalized_rout_unit_con_parts

logger = logging.getLogger(__name__)


class TopologyConversionError(Exception):
    """Raised when a required input file is missing or malformed."""


def convert_topology(
    txtinout: Path,
    *,
    backup: bool = True,
    reference_tordera: Path | None = None,
) -> Path:
    """Convert full-mode TxtInOut from cha to sdc/chandeg routing.

    Returns the path to the converted TxtInOut (same directory).

    Raises TopologyConversionError if a required file is missing.
    """
    tio = Path(txtinout).expanduser().resolve()
    if not tio.is_dir():
        raise TopologyConversionError(f"TxtInOut not found: {tio}")

    # Idempotency: if already converted, return early
    if (tio / "chandeg.con").exists() and not (tio / "channel.con").exists():
        _convert_rout_unit_con(tio)
        logger.info("Topology already converted — skipping: %s", tio)
        return tio

    if backup:
        _backup(tio)

    _convert_codes_bsn(tio)
    _convert_channel_con_to_chandeg(tio)
    _convert_rout_unit_con(tio)
    _convert_channel_cha_to_lte(tio)
    _convert_hydrology_cha_to_lte(tio)
    _convert_aquifer_con(tio)
    _convert_object_cnt(tio)
    _convert_file_cio(tio)
    _cleanup_channel_files(tio)

    logger.info("Topology conversion complete: %s", tio)
    return tio


def _backup(tio: Path) -> None:
    backup_dir = tio.parent / (tio.name + "_cha_original")
    if not backup_dir.exists():
        shutil.copytree(tio, backup_dir, symlinks=True)
        logger.info("Backup saved: %s", backup_dir)


def _require(tio: Path, fname: str) -> Path:
    p = tio / fname
    if not p.exists():
        raise TopologyConversionError(f"Required file missing: {p}")
    return p


# --- individual file converters ---


def _convert_codes_bsn(tio: Path) -> None:
    """Set routing flags for sdc/chandeg channel routing.

    rte_cha=1 enables channel routing. The editor v3.2.2 defaults for
    swift_out(=1), uhyd(=1), soil_p(=0), and i_fpwet(=1) block channel flow.
    We override them to match the working reference (editor v3.2.0) values.
    """
    path = _require(tio, "codes.bsn")
    lines = path.read_text().split("\n")
    if len(lines) < 3:
        raise TopologyConversionError("codes.bsn too short")

    headers = lines[1].split()
    data = lines[2].split()

    required_overrides = {
        "rte_cha": "1",
        "swift_out": "0",
        "uhyd": "0",
        "soil_p": "1",
        "i_fpwet": "0",
    }

    for flag, value in required_overrides.items():
        if flag not in headers:
            raise TopologyConversionError(f"{flag} column not found in codes.bsn")
        idx = headers.index(flag)
        data[idx] = value

    lines[2] = " ".join(data)
    path.write_text("\n".join(lines))


def _convert_channel_con_to_chandeg(tio: Path) -> None:
    """Convert channel.con to chandeg.con with sdc routing."""
    src = _require(tio, "channel.con")
    lines = src.read_text().split("\n")
    if len(lines) < 3:
        raise TopologyConversionError("channel.con too short")

    # Rewrite banner
    lines[0] = lines[0].replace("channel.con", "chandeg.con")

    # Replace column header: 'cha' → 'lcha' (landscape channel)
    if " cha " in lines[1]:
        lines[1] = lines[1].replace(" cha ", " lcha ")

    # Process data rows: replace internal 'cha' routing → 'sdc'
    new_lines = [lines[0], lines[1]]
    for ln in lines[2:]:
        if not ln.strip():
            new_lines.append(ln)
            continue
        parts = ln.split()
        if len(parts) >= 13:
            out_tot = int(parts[12])
            if out_tot > 0:
                # Replace cha→sdc in routing quads
                for i in range(13, len(parts)):
                    if parts[i] == "cha":
                        parts[i] = "sdc"
            new_lines.append(" ".join(parts))
        else:
            new_lines.append(ln)

    dest = tio / "chandeg.con"
    dest.write_text("\n".join(new_lines))


def _convert_rout_unit_con(tio: Path) -> None:
    """Replace cha->sdc and avoid double-counted routing-unit water routes."""
    src = _require(tio, "rout_unit.con")
    lines = src.read_text().split("\n")
    if len(lines) < 3:
        raise TopologyConversionError("rout_unit.con too short")

    new_lines = [lines[0], lines[1]]
    for ln in lines[2:]:
        if not ln.strip():
            new_lines.append(ln)
            continue
        parts = ln.split()
        if len(parts) >= 13:
            out_tot = int(parts[12])
            if out_tot > 0:
                for i in range(13, len(parts)):
                    if parts[i] == "cha":
                        parts[i] = "sdc"
                parts = _normalized_rout_unit_con_parts(parts)
            new_lines.append(" ".join(parts))
        else:
            new_lines.append(ln)

    src.write_text("\n".join(new_lines))


def _convert_channel_cha_to_lte(tio: Path) -> None:
    """Generate channel-lte.cha from channel.cha (null sed column)."""
    src = _require(tio, "channel.cha")
    lines = src.read_text().split("\n")
    if len(lines) < 3:
        raise TopologyConversionError("channel.cha too short")

    new_lines = [lines[0].replace("channel.cha", "channel-lte.cha"), lines[1]]
    for ln in lines[2:]:
        if not ln.strip():
            new_lines.append(ln)
            continue
        parts = ln.split()
        if len(parts) >= 5:
            # Reference format: id name init hyd null nut
            new_lines.append(
                f"      {parts[0]}  {parts[1]}                       {parts[2]}           {parts[3]}              null           {parts[4]}"
            )
        else:
            new_lines.append(ln)

    (tio / "channel-lte.cha").write_text("\n".join(new_lines))


def _convert_hydrology_cha_to_lte(tio: Path) -> None:
    """Generate hyd-sed-lte.cha from hydrology.cha with expanded column schema.

    The engine's channel routing (rte_cha=1) requires hyd-sed-lte.cha with a
    specific column schema that includes order, erod_fact, cov_fact, sinu,
    eq_slp, d50, clay, carbon, dry_bd, bankfull_flo, fps, fpn, n_conc, p_conc,
    p_bio — columns not present in the full-mode hydrology.cha.

    We fill missing columns with reference defaults.
    """
    src = _require(tio, "hydrology.cha")
    lines = src.read_text().split("\n")
    if len(lines) < 3:
        raise TopologyConversionError("hydrology.cha too short")

    # Parse hydrology.cha rows
    hyd_data = {}
    for ln in lines[2:]:
        if ln.strip():
            parts = ln.split()
            if len(parts) >= 7:
                hyd_data[parts[0]] = parts

    # Build hyd-sed-lte.cha with reference-compatible column schema
    out_lines = [
        "hyd-sed-lte.cha: builder-generated for engine rev 60.5.7",
        "name                         order            wd            dp"
        "           slp           len          mann             k"
        "     erod_fact      cov_fact          sinu        eq_slp"
        "           d50          clay        carbon        dry_bd"
        "      side_slp  bankfull_flo           fps           fpn"
        "        n_conc        p_conc         p_bio  description",
    ]

    # In the converted sdc/chandeg topology, SWAT+ treats hyd-sed-lte.cha:len
    # as part of the LTE transfer representation. Real channel lengths from
    # hydrology.cha over-delay small-basin event pulses in this engine/topology
    # combination; prior validated LTE runs used a near-zero transfer length.
    # Preserve physical channel geometry in the source GIS/channel tables, but
    # use the stabilized transfer length for this compatibility file.
    lte_transfer_len = "0.00050"

    for name, parts in sorted(hyd_data.items()):
        wd = parts[1] if len(parts) > 1 else "75.0"
        dp = parts[2] if len(parts) > 2 else "2.0"
        slp = parts[3] if len(parts) > 3 else "0.003"
        mann = parts[5] if len(parts) > 5 else "0.05"
        k = parts[6] if len(parts) > 6 else "1.0"
        out_lines.append(
            f"{name}                        5"
            f"      {wd:>12}"
            f"    {dp:>12}"
            f"    {slp:>12}"
            f"    {lte_transfer_len:>12}"
            f"    {mann:>12}"
            f"    {k:>12}"
            f"       0.01000       0.00500       1.05000       0.00100"
            f"      12.00000      45.00000       0.04000       1.00000"
            f"       0.50000       0.50000       0.00001       0.10000"
            f"       0.00000       0.00000       0.00000  "
        )

    (tio / "hyd-sed-lte.cha").write_text("\n".join(out_lines))


def _convert_object_cnt(tio: Path) -> None:
    """Move cha count to lcha; cha=0."""
    src = _require(tio, "object.cnt")
    lines = src.read_text().split("\n")
    if len(lines) < 3:
        raise TopologyConversionError("object.cnt too short")

    headers = lines[1].split()
    data = lines[2].split()
    if "lcha" in headers and "cha" in headers:
        lcha_idx = headers.index("lcha")
        cha_idx = headers.index("cha")
        if len(data) > max(lcha_idx, cha_idx):
            data[lcha_idx] = data[cha_idx]
            data[cha_idx] = "0"
            lines[2] = " ".join(data)

    src.write_text("\n".join(lines))


def _convert_file_cio(tio: Path) -> None:
    """Update connect and channel lines for sdc/chandeg topology.

    Engine rev 60.5.7 reads channel connections from the connect block by
    FIXED POSITION (not by filename):
      Position 7  → in_con%chan_con (regular channels, must be null)
      Position 13 → in_con%chandeg_con (swat-deg channels, from chandeg.con)

    The reference (editor v3.2.0) has:
      Position  7 = null
      Position 13 = chandeg.con

    Our editor v3.2.2 puts channel.con at position 7. We must move it to
    position 13 and null position 7. Also remove outlet.con (position 12
    in some editor versions) which blocks channel routing.
    """
    src = _require(tio, "file.cio")
    lines = src.read_text().split("\n")

    for i, ln in enumerate(lines):
        if ln.strip().startswith("connect"):
            tokens = ln.strip().split()
            # Ensure at least 14 tokens (connect + 13 file slots)
            while len(tokens) < 14:
                tokens.append("null")
            # Position 7 (0-indexed after 'connect' keyword) → null (no regular channels)
            tokens[7] = "null"
            # Position 13 → chandeg.con (swat-deg channel connections)
            tokens[13] = "chandeg.con"
            # Replace outlet.con with null instead of removing (preserves position count)
            tokens = ["null" if t == "outlet.con" else t for t in tokens]
            # Remove any duplicate chandeg.con entries from earlier positions
            for j in range(0, 13):
                if j != 13 and tokens[j] == "chandeg.con":
                    tokens[j] = "null"
            lines[i] = " ".join(tokens)

        if ln.strip().startswith("channel"):
            lines[i] = (
                "channel           initial.cha       null              null"
                "              null              nutrients.cha     channel-lte.cha"
                "   hyd-sed-lte.cha   null             "
            )

    src.write_text("\n".join(lines))


def _convert_aquifer_con(tio: Path) -> None:
    """Replace cha→sdc in aquifer.con routing quads.

    The engine's hyd_connect dispatches on obj_typ tokens across the
    entire routing graph.  If rout_unit.con and chandeg.con use sdc
    but aquifer.con still references cha objects, the engine segfaults
    at hyd_connect.f90:377 when trying to resolve the mismatched object
    type.

    """
    src = _require(tio, "aquifer.con")
    lines = src.read_text().split("\n")
    if len(lines) < 3:
        return  # empty or minimal aquifer.con

    new_lines = [lines[0], lines[1]]
    for ln in lines[2:]:
        if not ln.strip():
            new_lines.append(ln)
            continue
        parts = ln.split()
        if len(parts) >= 13:
            out_tot = int(parts[12])
            if out_tot > 0:
                for i in range(13, len(parts)):
                    if parts[i] == "cha":
                        parts[i] = "sdc"
            new_lines.append(" ".join(parts))
        else:
            new_lines.append(ln)

    src.write_text("\n".join(new_lines))


def _cleanup_channel_files(tio: Path) -> None:
    """Remove files not needed in sdc/chandeg topology."""
    for fname in ["channel.cha", "hydrology.cha", "sediment.cha", "channel.con"]:
        p = tio / fname
        if p.exists():
            p.unlink(missing_ok=True)
