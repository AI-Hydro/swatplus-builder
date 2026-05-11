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
    """Raise/lower CN2 for forest landuse in cntable.lum.

    Strategy: shift cn_a, cn_b, cn_c, cn_d for forest cover types (wood_f and
    any wood_*) by the delta needed to bring cn_b to ``value``. Preserves the
    A/B/C/D hydrologic-group differential structure.

    Range gate: [30, 95]. Values outside raise.
    """
    if not (30.0 <= value <= 95.0):
        raise ParameterBridgeError(f"CN2 out of range [30,95]: {value}")
    path = _require(tio, "cntable.lum")
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
        if len(toks) < 5 or not toks[0].startswith("wood"):
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

    Dominant ET lever: default pet_co=1.0 produces ET/P=73% (unrealistic).
    Range [0.1, 1.5]; values 0.3–0.6 typically bring ET/P to 30–50%.
    Engine-verified active: PET_CO is the strongest single lever for
    closing simulated vs observed volume gap (Phase 3L.12 sweep finding).
    """
    if not (0.1 <= value <= 1.5):
        raise ParameterBridgeError(f"PET_CO out of range [0.1,1.5]: {value}")
    path = _require(tio, "hydrology.hyd")
    _rewrite_column_for_rows(path, "pet_co", f"{value:.5f}", width=14)


def _apply_gw_delay(tio: Path, value: float) -> None:
    """Set GW delay (days) — note: aquifer.aqu column may differ; verify."""
    if not (0.0 <= value <= 500.0):
        raise ParameterBridgeError(f"GW_DELAY out of range [0,500]: {value}")
    path = _require(tio, "aquifer.aqu")
    # Column name in editor v3.2.2: "delay" (need to verify per file)
    _rewrite_column_for_rows(path, "delay", f"{value:.5f}", width=14)


WRITERS: Mapping[str, Callable[[Path, float], None]] = {
    "CN2": _apply_cn2,
    "ESCO": _apply_esco,
    "EPCO": _apply_epco,
    "PET_CO": _apply_pet_co,
    "ALPHA_BF": _apply_alpha_bf,
    "RCHG_DP": _apply_rchg_dp,
    "GW_DELAY": _apply_gw_delay,
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
