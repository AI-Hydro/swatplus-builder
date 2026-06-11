"""Full-mode water balance gate — blocks tier claims when hydrology is unphysical.

Reads ``basin_wb_aa.txt`` after an engine run and classifies the run against
physical plausibility bounds.  Each check maps to a named condition that
blocks specific tier claims.

Gate hierarchy (most fundamental → least):
  ZERO_SURFACE_RUNOFF  — surq_gen == 0 (or < 0.001 mm) on a basin with P > 0
                         Blocks: diagnostic, research_grade
                         Cause: CN too low, converter defect undetected, ET anomaly
  ET_DOMINATED         — ET/P > 0.70
                         Blocks: diagnostic, research_grade
                         Cause: unrealistically high ET demand/soil evaporation
  NEGATIVE_SKILL       — NSE < 0 (requires obs-series input)
                         Blocks: research_grade
                         Cause: model worse than mean-flow predictor
  MASS_IMBALANCE       — |P - (wateryld + ET + perc + ΔS)| / P > 0.05
                         Blocks: research_grade
  VOLUME_BIAS          — |PBIAS| > 30% when observed/simulated discharge is
                         available. Blocks: diagnostic, research_grade

Usage::

    from swatplus_builder.full_mode.water_balance_gate import check_water_balance
    result = check_water_balance(tio_path, precip_mm=450.0)
    if not result["pass"]:
        for msg in result["blocked_tiers"]:
            print(msg)

Note: NSE check is optional — only evaluated when ``nse`` is supplied.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class WaterBalanceGateError(Exception):
    """Raised on missing or malformed basin_wb_aa.txt."""


# ── Physical bounds ────────────────────────────────────────────────────────────

_SURQ_MIN_MM = 0.001          # mm; below this → zero-surq condition
_ET_P_MAX = 0.70              # ET/P above this → ET-dominated
_MASS_CLOSURE_TOL = 0.05      # fractional tolerance (5 %)
_PBIAS_MAX = 30.0             # percent; sim/obs volume bias gate
_NSE_DIAGNOSTIC_MIN = 0.0     # NSE must be ≥ 0 to claim diagnostic tier
_NSE_RESEARCH_MIN = 0.40      # NSE must be ≥ 0.40 for research_grade
_KGE_RESEARCH_MIN = 0.40      # KGE must be ≥ 0.40 for research_grade (alternative to NSE)


# ── Parser ─────────────────────────────────────────────────────────────────────

def _parse_basin_wb_aa(tio: Path) -> dict[str, float]:
    """Parse basin_wb_aa.txt annual-average row into a flat float dict.

    Expects SWAT+ standard format:
        Line 0: title
        Line 1: header tokens
        Line 2: units row
        Line 3: data row (annual averages for the simulation period)

    Returns empty dict if file is absent or malformed.
    """
    path = tio / "basin_wb_aa.txt"
    if not path.exists():
        return {}
    lines = [ln for ln in path.read_text().split("\n") if ln.strip()]
    if len(lines) < 4:
        return {}
    header = lines[1].split()
    data = lines[3].split()
    result: dict[str, float] = {}
    for i, col in enumerate(header):
        if i < len(data):
            try:
                result[col] = float(data[i])
            except ValueError:
                pass
    return result


# ── Individual checks ──────────────────────────────────────────────────────────

def _check_zero_surq(wb: dict[str, float]) -> list[str]:
    surq = wb.get("surq_gen", wb.get("surq", None))
    precip = wb.get("precip", 0.0)
    conditions = []
    if surq is not None and precip > 1.0 and surq < _SURQ_MIN_MM:
        conditions.append(
            f"ZERO_SURFACE_RUNOFF: surq_gen={surq:.4f} mm with P={precip:.1f} mm; "
            f"CN likely < 30 or converter defect (D1–D4). "
            f"Blocks: diagnostic, research_grade."
        )
    return conditions


def _check_et_dominated(wb: dict[str, float]) -> list[str]:
    et = wb.get("et", wb.get("et_act", None))
    precip = wb.get("precip", 0.0)
    conditions = []
    if et is not None and precip > 1.0:
        ratio = et / precip
        if ratio > _ET_P_MAX:
            conditions.append(
                f"ET_DOMINATED: ET/P={ratio:.2f} > {_ET_P_MAX}; "
                f"diagnose PET_CO/ESCO/EPCO, soil water, weather, and management drivers within documented SWAT+ ranges. "
                f"Blocks: diagnostic, research_grade."
            )
    return conditions


def _check_mass_closure(wb: dict[str, float]) -> list[str]:
    precip = wb.get("precip", 0.0)
    if precip < 1.0:
        return []
    wateryld = wb.get("wateryld", 0.0)
    wet_oflo = max(0.0, wb.get("wet_oflo", 0.0))
    net_wateryld = max(0.0, wateryld - wet_oflo) if wet_oflo > 0.0 else wateryld
    et = wb.get("et", wb.get("et_act", 0.0))
    perc = wb.get("perc", 0.0)
    # Wetland outflow is an internal transfer in the basin water-balance row;
    # do not double-count it as terminal basin water yield for land-phase closure.
    residual = abs(precip - (net_wateryld + et + perc))
    frac = residual / precip
    conditions = []
    if frac > _MASS_CLOSURE_TOL:
        adjustment = (
            f" wet_oflo={wet_oflo:.1f} net_wateryld={net_wateryld:.1f}."
            if wet_oflo > 0.0
            else ""
        )
        conditions.append(
            f"MASS_IMBALANCE: |P - (wateryld+ET+perc)|/P = {frac:.3f} > {_MASS_CLOSURE_TOL}; "
            f"P={precip:.1f} wateryld={wateryld:.1f} ET={et:.1f} perc={perc:.1f}."
            f"{adjustment} "
            f"Blocks: research_grade."
        )
    return conditions


def _check_skill(
    nse: float,
    kge: Optional[float] = None,
    *,
    timing_limitation_documented: bool = False,
    timing_limitation_basis: str | None = None,
) -> list[str]:
    conditions = []
    if nse < _NSE_DIAGNOSTIC_MIN:
        if kge is not None and kge >= _KGE_RESEARCH_MIN and timing_limitation_documented:
            return conditions
        timing_note = (
            f" Timing limitation basis: {timing_limitation_basis}."
            if timing_limitation_basis
            else " No timing limitation was documented."
        )
        conditions.append(
            f"NEGATIVE_SKILL: NSE={nse:.3f} < 0; model worse than mean-flow predictor. "
            f"Blocks: diagnostic, research_grade.{timing_note}"
        )
    elif nse < _NSE_RESEARCH_MIN:
        # Check KGE as alternative: if KGE≥0.40, allow research_grade
        if kge is not None and kge >= _KGE_RESEARCH_MIN:
            pass  # KGE passes research_grade threshold — no block
        else:
            kge_str = f"{kge:.3f}" if kge is not None else "N/A"
            conditions.append(
                f"BELOW_RESEARCH_SKILL: NSE={nse:.3f} < {_NSE_RESEARCH_MIN} "
                f"(KGE={kge_str}); "
                f"insufficient for research_grade claim. "
                f"Blocks: research_grade."
            )
    return conditions


def _check_pbias(pbias: Optional[float]) -> list[str]:
    if pbias is None or not math.isfinite(pbias):
        return []
    if abs(pbias) <= _PBIAS_MAX:
        return []
    direction = "overpredicts" if pbias > 0 else "underpredicts"
    return [
        f"VOLUME_BIAS: PBIAS={pbias:.1f}% exceeds +/-{_PBIAS_MAX:.0f}%; "
        f"simulated discharge volume {direction} observed flow. "
        f"Blocks: diagnostic, research_grade."
    ]


# ── Tier classification ────────────────────────────────────────────────────────

_TIER_BLOCKS: dict[str, list[str]] = {
    "ZERO_SURFACE_RUNOFF": ["diagnostic", "research_grade"],
    "ET_DOMINATED": ["diagnostic", "research_grade"],
    "MASS_IMBALANCE": ["research_grade"],
    "VOLUME_BIAS": ["diagnostic", "research_grade"],
    "NEGATIVE_SKILL": ["diagnostic", "research_grade"],
    "BELOW_RESEARCH_SKILL": ["research_grade"],
}


def _condition_key(msg: str) -> str:
    return msg.split(":")[0].strip()


_RECOMMENDED_ACTIONS: dict[str, str] = {
    "ZERO_SURFACE_RUNOFF": "Inspect curve-number assignment, landuse mapping, and runoff generation before calibration.",
    "ET_DOMINATED": "Audit PET/ET controls and evapotranspiration partitioning before calibration.",
    "MASS_IMBALANCE": "Audit basin water-balance accounting and routing connectivity before calibration.",
    "VOLUME_BIAS": "Diagnose simulated/observed volume mismatch before calibration; parameter search is blocked.",
    "NEGATIVE_SKILL": "Diagnose hydrograph skill failure before calibration; model is worse than mean-flow predictor.",
    "BELOW_RESEARCH_SKILL": "Treat calibration metrics as diagnostic until research skill thresholds are met.",
}


_CONDITION_PRIORITY: tuple[str, ...] = (
    "ZERO_SURFACE_RUNOFF",
    "MASS_IMBALANCE",
    "VOLUME_BIAS",
    "ET_DOMINATED",
    "NEGATIVE_SKILL",
    "BELOW_RESEARCH_SKILL",
)


def _dominant_condition(codes: list[str]) -> str | None:
    for code in _CONDITION_PRIORITY:
        if code in codes:
            return code
    return codes[0] if codes else None


# ── Public entry point ────────────────────────────────────────────────────────

def check_water_balance(
    txtinout: Path | str,
    *,
    nse: Optional[float] = None,
    kge: Optional[float] = None,
    pbias: Optional[float] = None,
    strict_surq: bool = True,
    timing_limitation_documented: bool = False,
    timing_limitation_basis: str | None = None,
) -> dict:
    """Read basin_wb_aa.txt and evaluate water balance gates.

    Args:
        txtinout: path to TxtInOut directory after engine run.
        nse: Nash-Sutcliffe efficiency, if known (from post-processing).
             Pass None to skip NSE gates (e.g. no observed data).
        pbias: Percent simulated/observed discharge volume bias, if known.
        strict_surq: if True (default) treat surq_gen = 0 as a hard gate
                     violation.  Set False for forested/semi-arid basins where
                     zero surface runoff is physically plausible.
        timing_limitation_documented: Allow the negative-NSE/KGE exception only
                     when an explicit timing limitation has been written to
                     evidence.

    Returns:
        dict with keys:
          ``pass`` (bool) — True if no conditions triggered
          ``wb`` (dict) — parsed water balance values
          ``conditions`` (list[str]) — triggered gate messages
          ``blocked_tiers`` (dict[str, list[str]]) — {tier: [reasons]}
          ``allowed_tiers`` (list[str]) — tiers not blocked
    """
    tio = Path(txtinout).expanduser().resolve()
    if not tio.is_dir():
        raise WaterBalanceGateError(f"TxtInOut not found: {tio}")

    wb = _parse_basin_wb_aa(tio)
    if not wb:
        raise WaterBalanceGateError(
            f"basin_wb_aa.txt missing or empty in {tio}; "
            f"engine may not have run successfully"
        )

    conditions: list[str] = []
    if strict_surq:
        conditions += _check_zero_surq(wb)
    conditions += _check_et_dominated(wb)
    conditions += _check_mass_closure(wb)
    conditions += _check_pbias(pbias)
    if nse is not None:
        conditions += _check_skill(
            nse,
            kge,
            timing_limitation_documented=timing_limitation_documented,
            timing_limitation_basis=timing_limitation_basis,
        )

    # Aggregate blocked tiers
    all_tiers = ["exploratory", "diagnostic", "research_grade"]
    blocked: dict[str, list[str]] = {t: [] for t in all_tiers}
    condition_codes = [_condition_key(msg) for msg in conditions]
    for msg in conditions:
        key = _condition_key(msg)
        for tier in _TIER_BLOCKS.get(key, []):
            blocked[tier].append(msg)

    allowed = [t for t in all_tiers if not blocked[t]]
    passed = len(conditions) == 0
    dominant = _dominant_condition(condition_codes)

    result = {
        "pass": passed,
        "wb": wb,
        "conditions": conditions,
        "condition_codes": condition_codes,
        "dominant_blocker": dominant,
        "recommended_next_action": _RECOMMENDED_ACTIONS.get(dominant, "No physical-gate action required."),
        "timing_limitation_documented": timing_limitation_documented,
        "timing_limitation_basis": timing_limitation_basis,
        "blocked_tiers": {t: v for t, v in blocked.items() if v},
        "allowed_tiers": allowed,
    }

    if conditions:
        summary = "\n  ".join(conditions)
        logger.warning(
            "Water balance gate triggered %d condition(s) for %s:\n  %s",
            len(conditions), tio.name, summary,
        )
    else:
        logger.info("Water balance gate passed: %s", tio.name)

    return result


def assert_tier_allowed(
    txtinout: Path | str,
    tier: str,
    *,
    nse: Optional[float] = None,
    pbias: Optional[float] = None,
) -> None:
    """Raise ``WaterBalanceGateError`` if claiming ``tier`` is not allowed.

    Convenience wrapper for use in pipeline steps that want a hard stop
    before writing any claim about model skill.
    """
    result = check_water_balance(txtinout, nse=nse, pbias=pbias)
    if tier in result["blocked_tiers"]:
        reasons = result["blocked_tiers"][tier]
        raise WaterBalanceGateError(
            f"Cannot claim tier '{tier}' for {Path(txtinout).name}: "
            + "; ".join(reasons)
        )
