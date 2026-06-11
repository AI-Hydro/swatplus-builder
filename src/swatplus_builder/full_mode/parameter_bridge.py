"""Full SWAT+ parameter bridge.

Writes calibration parameter values into the full-mode TxtInOut. Each writer
targets one file/column with the same fail-loud contract as the LTE bridge:
raise on missing files, validate ranges, preserve column alignment.

Engine-verification gate (Phase 3L.12): a parameter is only marked ``active``
in the registry after an engine probe confirms the output channel flow series
hash changes between LOW and HIGH values for that parameter on a fixed basin.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Mapping

logger = logging.getLogger(__name__)


class ParameterBridgeError(Exception):
    """Raised when a full-mode parameter cannot be applied."""


def _require(tio: Path, fname: str) -> Path:
    p = tio / fname
    if not p.exists():
        raise ParameterBridgeError(f"Required file missing: {p}")
    return p


def _rewrite_column_for_rows(
    path: Path,
    header_token: str,
    new_value: str,
    *,
    width: int = 14,
    where: Callable[[list[str]], bool] | None = None,
) -> int:
    """Rewrite the column named ``header_token`` for matching rows.

    The header line is the second line of the file (the SWAT+ convention).
    Rewrites the value in fixed-width format right-justified in ``width`` chars.
    Returns the number of rows changed.
    """
    lines = path.read_text().split("\n")
    if len(lines) < 3:
        raise ParameterBridgeError(f"{path.name} too short")
    header_tokens = lines[1].split()
    try:
        col_idx = header_tokens.index(header_token)
    except ValueError as e:
        raise ParameterBridgeError(
            f"{path.name} has no column {header_token!r}; header={header_tokens}"
        ) from e
    changed = 0
    out = [lines[0], lines[1]]
    for ln in lines[2:]:
        if not ln.strip():
            out.append(ln)
            continue
        toks = ln.split()
        if len(toks) <= col_idx:
            out.append(ln)
            continue
        if where is not None and not where(toks):
            out.append(ln)
            continue
        toks[col_idx] = new_value.rjust(width).strip()
        # Rebuild with consistent right-justified 14-char columns after the name
        # We assume column 1 is name (variable width) — preserve original prefix
        # then re-emit numeric columns in 14-char right-justified form.
        rebuilt = _rejoin_with_widths(ln, toks, col_idx, new_value, width)
        out.append(rebuilt)
        changed += 1
    path.write_text("\n".join(out))
    return changed


def _rejoin_with_widths(
    original: str, toks: list[str], col_idx: int, new_value: str, width: int
) -> str:
    """Position-preserving column substitution within a fixed-width text row.

    Strategy: find each token's start position in the original string, replace
    the matched token in-place with new_value padded/trimmed to the same column
    width. This preserves all other columns' alignment regardless of editor
    formatting quirks.
    """
    # Locate the substring boundaries of token col_idx in the original line.
    # Tokens are whitespace-separated. We walk the original line and find the
    # col_idx-th non-whitespace run.
    i = 0
    n = len(original)
    seen = 0
    while i < n:
        # skip whitespace
        while i < n and original[i].isspace():
            i += 1
        if i >= n:
            break
        # token start
        start = i
        while i < n and not original[i].isspace():
            i += 1
        end = i
        if seen == col_idx:
            # Replace original[start:end] with new_value, preserving the
            # original token width (right-justified) so column alignment holds.
            tok_w = end - start
            new_tok = new_value.rjust(max(tok_w, len(new_value)))
            # If new value is wider than the original token, this extends the
            # line — acceptable since SWAT+ uses whitespace-separated parsing.
            return original[:start] + new_tok + original[end:]
        seen += 1
    # col_idx not found — should not happen if we already validated header
    raise ParameterBridgeError(
        f"could not locate column {col_idx} in row: {original!r}"
    )


# --- Individual parameter writers ---


def _apply_cn2(tio: Path, value: float) -> None:
    """Raise/lower CN2 for curve-number sources in full-mode TxtInOut.

    Strategy:
    - Shift cn_a, cn_b, cn_c, cn_d for referenced landuse curve-number rows
      by the delta needed to bring cn_b to ``value``. Preserves the A/B/C/D
      hydrologic-group differential structure.
    - Always include forest cover types (wood_f and any wood_*) for backward
      compatibility with the original narrow bridge.
    - If urban land uses are present, also set ``urban.urb:urb_cn`` for urban
      rows referenced by ``landuse.lum`` for provenance consistency. In
      generated full-mode TxtInOut, runtime HRU CN comes from
      ``landuse.lum:cn2`` -> ``cntable.lum``; the urban row in cntable is the
      active runoff lever.

    Range gate: [35, 98]. Values outside raise.
    """
    if not (35.0 <= value <= 98.0):
        raise ParameterBridgeError(f"CN2 out of range [35,98]: {value}")
    path = _require(tio, "cntable.lum")
    referenced_cn2 = _referenced_column_names(tio / "landuse.lum", "cn2")
    lines = path.read_text().split("\n")
    if len(lines) < 3:
        raise ParameterBridgeError("cntable.lum too short")
    out = [lines[0], lines[1]]
    changed = 0
    for ln in lines[2:]:
        if not ln.strip():
            out.append(ln)
            continue
        toks = ln.split()
        if len(toks) < 5:
            out.append(ln)
            continue
        row_name = toks[0]
        if not _is_cn2_target_row(row_name, referenced_cn2):
            out.append(ln)
            continue
        try:
            cn_a = float(toks[1])
            cn_b = float(toks[2])
            cn_c = float(toks[3])
            cn_d = float(toks[4])
        except ValueError:
            out.append(ln)
            continue
        # Preserve hydrologic-group differentials: shift all four by (value - cn_b)
        delta = value - cn_b
        new_a = max(20.0, min(98.0, cn_a + delta))
        new_b = max(20.0, min(98.0, cn_b + delta))
        new_c = max(20.0, min(98.0, cn_c + delta))
        new_d = max(20.0, min(98.0, cn_d + delta))
        # Format with 14-char right-justified columns to match editor output
        new_ln = (
            toks[0].ljust(22)
            + f"{new_a:14.5f}{new_b:14.5f}{new_c:14.5f}{new_d:14.5f}"
            + "  " + " ".join(toks[5:])
        )
        out.append(new_ln)
        changed += 1
    if changed == 0:
        logger.warning("cntable.lum had no wood_* rows — CN2 had no effect")
    path.write_text("\n".join(out))
    _apply_cn2_to_referenced_urban_rows(tio, value)


def _is_cn2_target_row(row_name: str, referenced_cn2: set[str] | None) -> bool:
    lower = row_name.lower()
    if lower.startswith("wood_"):
        return True
    return referenced_cn2 is not None and row_name in referenced_cn2


def _apply_cn2_to_referenced_urban_rows(tio: Path, value: float) -> None:
    urban_path = tio / "urban.urb"
    if not urban_path.exists():
        return

    referenced = _referenced_column_names(tio / "landuse.lum", "urban")
    if referenced is None:
        logger.warning("landuse.lum missing or unreadable; applying CN2 to all urban.urb rows")
    changed = _rewrite_column_for_rows(
        urban_path,
        "urb_cn",
        f"{value:.5f}",
        width=14,
        where=None if referenced is None else lambda toks: toks and toks[0] in referenced,
    )
    if changed == 0:
        logger.warning("urban.urb had no referenced urban rows — CN2 urban extension had no effect")


def _referenced_column_names(path: Path, column: str) -> set[str] | None:
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    if len(lines) < 3:
        return None
    header = lines[1].split()
    try:
        col_idx = header.index(column)
    except ValueError:
        return None

    names: set[str] = set()
    for ln in lines[2:]:
        if not ln.strip():
            continue
        toks = ln.split()
        if len(toks) <= col_idx:
            continue
        value = toks[col_idx]
        if value.lower() != "null":
            names.add(value)
    return names


def _apply_esco(tio: Path, value: float) -> None:
    """Set ESCO (soil evaporation compensation) for all HRUs in hydrology.hyd."""
    if not (0.01 <= value <= 1.0):
        raise ParameterBridgeError(f"ESCO out of range [0.01,1.0]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "esco", f"{value:.5f}", width=14)


def _apply_epco(tio: Path, value: float) -> None:
    """Set EPCO (plant uptake compensation) for all HRUs in hydrology.hyd."""
    if not (0.01 <= value <= 1.0):
        raise ParameterBridgeError(f"EPCO out of range [0.01,1.0]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "epco", f"{value:.5f}", width=14)


def _apply_alpha_bf(tio: Path, value: float) -> None:
    """Set baseflow alpha factor for all aquifers in aquifer.aqu."""
    if not (0.001 <= value <= 1.0):
        raise ParameterBridgeError(f"ALPHA_BF out of range [0.001,1.0]: {value}")
    path = _require(tio, "aquifer.aqu")
    _rewrite_column_for_rows(path, "alpha_bf", f"{value:.5f}", width=14)


def _apply_rchg_dp(tio: Path, value: float) -> None:
    """Set deep aquifer recharge fraction for all aquifers in aquifer.aqu."""
    if not (0.0 <= value <= 0.8):
        raise ParameterBridgeError(f"RCHG_DP out of range [0.0,0.8]: {value}")
    path = _require(tio, "aquifer.aqu")
    _rewrite_column_for_rows(path, "rchg_dp", f"{value:.5f}", width=14)


def _apply_pet_co(tio: Path, value: float) -> None:
    """Set PET correction factor for all HRUs in hydrology.hyd.

    SWAT+ documents ``pet_co`` as a linear PET adjustment with a total range
    of [0.8, 1.2]. Keep the direct TxtInOut writer inside that range; larger
    ET corrections need a researched process diagnosis rather than
    out-of-range parameter edits.
    """
    if not (0.8 <= value <= 1.2):
        raise ParameterBridgeError(f"PET_CO out of range [0.8,1.2]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "pet_co", f"{value:.5f}", width=14)


def _apply_gw_delay(tio: Path, value: float) -> None:
    """Set GW delay (days) — NOT APPLICABLE in SWAT+ full mode aquifer.aqu.

    SWAT+ full mode uses aquifer.aqu with columns: init, gw_flo, dep_bot, dep_wt,
    no3_n, sol_p, carbon, flo_dist, bf_max, alpha_bf, revap, rchg_dp, spec_yld,
    hl_no3n, flo_min, revap_min. There is NO gw_del or delay column.
    The equivalent in full mode is handled via aquifer.con routing.

    Raises ParameterBridgeError explaining the migration needed.
    """
    raise ParameterBridgeError(
        "GW_DELAY has no equivalent column in SWAT+ full mode aquifer.aqu. "
        "Groundwater delay in full mode is controlled by aquifer.con routing. "
        "Use LATQ_CO in hydrology.hyd for lateral flow timing instead."
    )


def _apply_perco(tio: Path, value: float) -> None:
    """Set percolation coefficient for all HRUs in hydrology.hyd.

    Controls fraction of soil water that percolates (vs lateral flow).
    Default 0.50; range [0.01, 1.0]. Higher → more deep drainage, less lateral flow.
    Engine-verified active on 01547700 (all-A soils, lateral-flow dominated).
    """
    if not (0.01 <= value <= 1.0):
        raise ParameterBridgeError(f"PERCO out of range [0.01,1.0]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "perco", f"{value:.5f}", width=14)


def _apply_latq_co(tio: Path, value: float) -> None:
    """Set lateral flow coefficient for all HRUs in hydrology.hyd.

    Fraction of lateral flow that reaches the channel in one day.
    Default 0.01; range [0.001, 1.0]. Higher → faster lateral flow delivery.
    CRITICAL for basins dominated by subsurface lateral flow (all-A soils).
    Engine-verified active on 01547700.
    """
    if not (0.001 <= value <= 1.0):
        raise ParameterBridgeError(f"LATQ_CO out of range [0.001,1.0]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "latq_co", f"{value:.5f}", width=14)


def _apply_lat_ttime(tio: Path, value: float) -> None:
    """Set lateral flow travel time for all HRUs in hydrology.hyd.

    SWAT+ documents ``lat_ttime`` as the lateral-flow lag time in days. A
    value of 0.0 delegates travel-time calculation to the model; positive
    values directly control the daily fraction released from lateral-flow
    storage through ``1 - exp(-1 / lat_ttime)``.
    """
    if not (0.0 <= value <= 120.0):
        raise ParameterBridgeError(f"LAT_TTIME out of range [0.0,120.0]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "lat_ttime", f"{value:.5f}", width=14)


def _apply_cn3_swf(tio: Path, value: float) -> None:
    """Set SWAT+ surface-runoff soft-calibration factor for all HRUs.

    SWAT+ soft water-balance calibration uses ``hydrology.hyd:cn3_swf`` as
    the surface-runoff process control with total limits [0, 1].
    """
    if not (0.0 <= value <= 1.0):
        raise ParameterBridgeError(f"CN3_SWF out of range [0.0,1.0]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "cn3_swf", f"{value:.5f}", width=14)


def _apply_surlag(tio: Path, value: float) -> None:
    """Set surface runoff lag coefficient in parameters.bsn.

    Controls how quickly surface runoff reaches the channel.
    SWAT+ full mode uses column ``surq_lag`` (not ``surlag`` as in SWAT2012).
    Default 4.0; documented range [1.0, 24.0]. Lower → faster peak response, higher peaks.
    """
    if not (1.0 <= value <= 24.0):
        raise ParameterBridgeError(f"SURLAG out of range [1.0,24.0]: {value}")
    path = _require(tio, "parameters.bsn")
    _rewrite_column_for_rows(path, "surq_lag", f"{value:.5f}", width=14)


def _apply_ch_n2(tio: Path, value: float) -> None:
    """Set channel Manning roughness for all full-mode LTE channel records."""
    if not (0.014 <= value <= 0.15):
        raise ParameterBridgeError(f"CH_N2 out of range [0.014,0.15]: {value}")
    path = _require(tio, "hyd-sed-lte.cha")
    _rewrite_column_for_rows(path, "mann", f"{value:.5f}", width=14)


def _apply_ch_k2(tio: Path, value: float) -> None:
    """Set effective channel alluvium hydraulic conductivity for LTE channels."""
    if not (0.0 <= value <= 500.0):
        raise ParameterBridgeError(f"CH_K2 out of range [0,500]: {value}")
    path = _require(tio, "hyd-sed-lte.cha")
    _rewrite_column_for_rows(path, "k", f"{value:.5f}", width=14)


def _apply_sftmp(tio: Path, value: float) -> None:
    """Set snowfall temperature threshold in snow.sno.

    SWAT+ full mode stores the SWAT2012/SWAT-CUP SFTMP concept as
    ``snow.sno:fall_tmp``. Lower values make precipitation stay rain at colder
    temperatures; higher values classify more near-freezing precipitation as
    snow.
    """
    if not (-5.0 <= value <= 5.0):
        raise ParameterBridgeError(f"SFTMP out of range [-5,5]: {value}")
    path = _require(tio, "snow.sno")
    _rewrite_column_for_rows(path, "fall_tmp", f"{value:.5f}", width=14)


def _apply_smtmp(tio: Path, value: float) -> None:
    """Set snowmelt base temperature in snow.sno.

    SWAT+ full mode stores the SWAT2012/SWAT-CUP SMTMP concept as
    ``snow.sno:melt_tmp``.
    """
    if not (-5.0 <= value <= 5.0):
        raise ParameterBridgeError(f"SMTMP out of range [-5,5]: {value}")
    path = _require(tio, "snow.sno")
    _rewrite_column_for_rows(path, "melt_tmp", f"{value:.5f}", width=14)


WRITERS: Mapping[str, Callable[[Path, float], None]] = {
    "CN2": _apply_cn2,
    "ESCO": _apply_esco,
    "EPCO": _apply_epco,
    "PET_CO": _apply_pet_co,
    "PERCO": _apply_perco,
    "LATQ_CO": _apply_latq_co,
    "LAT_TTIME": _apply_lat_ttime,
    "CN3_SWF": _apply_cn3_swf,
    "SURLAG": _apply_surlag,
    "CH_N2": _apply_ch_n2,
    "CH_K2": _apply_ch_k2,
    "ALPHA_BF": _apply_alpha_bf,
    "RCHG_DP": _apply_rchg_dp,
    "GW_DELAY": _apply_gw_delay,  # raises — full mode uses aquifer.con
    "SFTMP": _apply_sftmp,
    "SMTMP": _apply_smtmp,
}


# Sensitivity classification mapped from engine-backed perturbation audit.
# Updated 2026-05-12 from full-mode engine probes on 01547700.
FULL_MODE_PARAMETER_ACTIVITY: Mapping[str, str] = {
    "CN2": "active",       # ΔNSE > 0.20 across ±20% range; output hash changes
    "PERCO": "active",     # ΔNSE > 1.0; controls lateral-vs-deep partition
    "LATQ_CO": "active",   # ΔNSE > 5.0; dominant lever for all-A soil basins
    "ESCO": "weak",        # ΔNSE < 0.01 at ±20%; ET doesn't dominate water balance
    "EPCO": "not_tested",  # comparable to ESCO in physical role
    "PET_CO": "not_tested",# may be active for ET-dominated basins
    "ALPHA_BF": "not_tested", # untested with engine probes
    "RCHG_DP": "not_tested",
    "SURLAG": "not_tested",
    "CH_N2": "not_tested",   # channel Manning roughness; requires basin screen
    "CH_K2": "not_tested",   # channel bed conductivity; requires basin screen
    "GW_DELAY": "dead",    # column does not exist in full-mode aquifer.aqu
    "SFTMP": "weak",        # governed snow.sno writer; requires basin snow screen
    "SMTMP": "weak",        # governed snow.sno writer; requires basin snow screen
    "LAT_TTIME": "not_tested", # lateral-flow recession lag; requires basin screen
    "CN3_SWF": "not_tested",   # SWAT+ soft surface-runoff control; requires basin screen
}


def apply_parameters_to_full_swat_txtinout(
    txtinout: Path | str, params: Mapping[str, float]
) -> None:
    """Apply a parameter dict to a full-mode TxtInOut in place.

    Args:
        txtinout: path to the TxtInOut directory (post topology-conversion).
        params: mapping from parameter name (e.g. "CN2") to value.

    Raises:
        ParameterBridgeError: on unknown parameter, out-of-range value, or
            missing target file.
    """
    tio = Path(txtinout).expanduser().resolve()
    if not tio.is_dir():
        raise ParameterBridgeError(f"TxtInOut not found: {tio}")
    for name, value in params.items():
        writer = WRITERS.get(name)
        if writer is None:
            raise ParameterBridgeError(f"Unknown full-mode parameter: {name}")
        writer(tio, float(value))
    logger.info("Applied %d full-mode parameters to %s", len(params), tio.name)
