"""SWAT+ soil-parameter derivations.

Pure math — no I/O, no external deps. Every function is deterministic
and side-effect-free so unit tests can pin exact values.

References:
    * Williams 1995 (EPIC model), §"USLE Soil Erodibility Factor".
    * Post & Klein 1977 / Post et al. 2000 — soil albedo vs. organic C.
    * van Bemmelen 1890 — organic-matter → organic-carbon factor 0.58.
    * SSURGO Metadata, ``chorizon`` table — field units.

All SWAT+ unit conventions (mm/hour, % of mass, fraction 0–1, etc.)
match the :class:`~swatplus_builder.types.SoilHorizon` contract.
"""

from __future__ import annotations

import math

from ..errors import SwatBuilderInputError
from ..types import HydGroup, SoilHorizon

__all__ = [
    "DEFAULT_ALBEDO_BARE",
    "VAN_BEMMELEN_OC_FRACTION",
    "collapse_dual_hyd_group",
    "compute_albedo",
    "compute_usle_k",
    "ksat_umps_to_mmph",
    "om_to_oc",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


VAN_BEMMELEN_OC_FRACTION: float = 0.58
"""Conventional OM→OC factor. Assumes OM is 58% carbon by mass.

The "true" factor varies ±5 percentage points by soil type, but 0.58
(1.724 reciprocal) is the USDA/IPCC convention and what SSURGO's
`om_r` → "organic carbon" implicitly assumes. Over-precise alternatives
(Pribyl 2010: 0.50) matter little for SWAT+ outputs; flag it as a
tuning knob only if calibration demands it.
"""

DEFAULT_ALBEDO_BARE: float = 0.15
"""Fallback for horizons with unknown OC. Pure mineral surfaces range
0.10 (dark clay) to 0.25 (dry sand); 0.15 is a neutral mid-value that
SWAT+ tolerates without spurious radiation imbalance."""


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


def ksat_umps_to_mmph(ksat_umps: float) -> float:
    """Convert SSURGO's ``ksat_r`` (µm/s) to SWAT+'s ``soil_k`` (mm/hour).

    The factor is exact: 1 µm/s = 3.6 mm/hour = 3600 × 10⁻³ mm/hour.

    Raises:
        SwatBuilderInputError: negative input — SSURGO flags missing
            values as ``NULL``/NaN, callers should handle that upstream.
    """
    if ksat_umps < 0:
        raise SwatBuilderInputError(
            f"ksat cannot be negative: got {ksat_umps!r}", ksat_umps=ksat_umps
        )
    return ksat_umps * 3.6


def om_to_oc(om_pct: float, factor: float = VAN_BEMMELEN_OC_FRACTION) -> float:
    """Organic matter (%) → organic carbon (%).

    SSURGO reports ``om_r`` as OM; SWAT+ ``soils_sol_layer.carbon`` is OC.
    Default factor 0.58 (van Bemmelen). Override with 0.50 (Pribyl 2010)
    or a site-specific ratio if calibration requires it.
    """
    if om_pct < 0:
        raise SwatBuilderInputError(
            f"om_pct cannot be negative: got {om_pct!r}", om_pct=om_pct
        )
    if not (0 < factor <= 1):
        raise SwatBuilderInputError(
            f"factor must be in (0, 1]: got {factor!r}", factor=factor
        )
    return om_pct * factor


# ---------------------------------------------------------------------------
# Hydrologic group
# ---------------------------------------------------------------------------


def collapse_dual_hyd_group(code: str | None) -> HydGroup:
    """Convert SSURGO ``hydgrpdcd`` to a single-letter SWAT+ code.

    SSURGO uses dual codes for drained vs. undrained state
    (``A/D``, ``B/D``, ``C/D``). SWAT+ expects one letter. Convention
    (and editor validator): **take the worst-drainage member**. Rationale:
    most USGS watersheds we target are **undrained**, so ``A/D`` behaves
    like ``D`` hydrologically during design storms.

    Null / unknown → ``"D"`` (conservative: highest runoff potential).
    Single-letter codes pass through unchanged after upper-casing.

    Raises:
        SwatBuilderInputError: unrecognized code (e.g. ``"E"``).
    """
    if code is None or code == "":
        return "D"
    code = code.strip().upper()
    if code in {"A", "B", "C", "D"}:
        return code  # type: ignore[return-value]
    if "/" in code:
        # Last letter is the worst-drainage half in every SSURGO dual code.
        tail = code.split("/")[-1]
        if tail in {"A", "B", "C", "D"}:
            return tail  # type: ignore[return-value]
    raise SwatBuilderInputError(
        f"unrecognized hydrologic group code: {code!r}",
        code=code,
        expected=["A", "B", "C", "D", "A/D", "B/D", "C/D", None],
    )


# ---------------------------------------------------------------------------
# Albedo (Post et al. 2000)
# ---------------------------------------------------------------------------


def compute_albedo(carbon_pct: float | None) -> float:
    """Soil albedo (wet, bare surface) from organic carbon content.

    Empirical fit (Post 2000):

    .. math::
        \\alpha = 0.15 \\cdot \\exp(-0.25 \\cdot C)

    where :math:`C` is organic carbon %. Returns
    :data:`DEFAULT_ALBEDO_BARE` if ``carbon_pct`` is None or < 0 (which
    SSURGO sometimes reports for rock/gravel horizons).

    Clamped to ``[0.01, 0.25]`` so the engine never sees degenerate
    values.
    """
    if carbon_pct is None or carbon_pct < 0:
        return DEFAULT_ALBEDO_BARE
    alb = 0.15 * math.exp(-0.25 * carbon_pct)
    return max(0.01, min(0.25, alb))


# ---------------------------------------------------------------------------
# USLE K (Williams 1995 / EPIC formulation)
# ---------------------------------------------------------------------------


def compute_usle_k(
    *,
    sand_pct: float,
    silt_pct: float,
    clay_pct: float,
    carbon_pct: float,
) -> float:
    """Soil erodibility factor K, per Williams (1995) / EPIC.

    Units: t·ha·h / (ha·MJ·mm) — dimensionless when scaled; matches what
    SWAT+ expects for ``soils_sol_layer.usle_k``.

    Formula:

    .. math::
        K = f_{csand} \\cdot f_{clsi} \\cdot f_{orgc} \\cdot f_{hisand}

    where:

    .. math::
        f_{csand} = 0.2 + 0.3 \\exp\\left(-0.0256 \\cdot \\text{sand} \\cdot
                      (1 - \\frac{\\text{silt}}{100})\\right)

    .. math::
        f_{clsi} = \\left(\\frac{\\text{silt}}{\\text{clay} + \\text{silt}}
                   \\right)^{0.3}

    .. math::
        f_{orgc} = 1 - \\frac{0.25 C}{C + \\exp(3.72 - 2.95 C)}

    .. math::
        f_{hisand} = 1 - \\frac{0.7 \\cdot SN_1}
                      {SN_1 + \\exp(-5.51 + 22.9 \\cdot SN_1)},
                      \\quad SN_1 = 1 - \\frac{\\text{sand}}{100}

    Raises:
        SwatBuilderInputError: negative fractions or ``sand + silt + clay``
            not in ``[80, 120]`` (allowing rounding slop).
    """
    for name, v in (("sand_pct", sand_pct), ("silt_pct", silt_pct),
                    ("clay_pct", clay_pct), ("carbon_pct", carbon_pct)):
        if v < 0:
            raise SwatBuilderInputError(
                f"{name} cannot be negative: {v!r}",
                **{name: v},
            )

    total = sand_pct + silt_pct + clay_pct
    if not (80.0 <= total <= 120.0):
        raise SwatBuilderInputError(
            f"sand + silt + clay = {total:.1f}; expected ~100 ± 20 "
            "(horizons with massive organic or rock content should "
            "be screened upstream, not patched here)",
            sand_pct=sand_pct,
            silt_pct=silt_pct,
            clay_pct=clay_pct,
            total=total,
        )

    # f_csand — coarse-sand factor
    f_csand = 0.2 + 0.3 * math.exp(-0.0256 * sand_pct * (1.0 - silt_pct / 100.0))

    # f_cl-si — clay-silt ratio factor. Guard degenerate clay+silt==0
    # (pure sand) with a tiny epsilon so we return a finite number.
    cs_sum = clay_pct + silt_pct
    if cs_sum <= 0:
        f_clsi = 0.0
    else:
        f_clsi = (silt_pct / cs_sum) ** 0.3

    # f_orgc — organic carbon factor
    if carbon_pct <= 0:
        f_orgc = 1.0  # no reduction at zero OC — pure mineral soil.
    else:
        f_orgc = 1.0 - (0.25 * carbon_pct) / (
            carbon_pct + math.exp(3.72 - 2.95 * carbon_pct)
        )

    # f_hisand — very-high-sand factor
    sn1 = 1.0 - sand_pct / 100.0
    f_hisand = 1.0 - (0.7 * sn1) / (sn1 + math.exp(-5.51 + 22.9 * sn1))

    k = f_csand * f_clsi * f_orgc * f_hisand
    # Real-world USLE K falls in roughly [0.01, 0.65]. Clamp so a weird
    # horizon (e.g. clay_pct=0, silt_pct=100, carbon=50) doesn't emit a
    # value the engine's validator rejects.
    return max(0.01, min(0.65, k))


# ---------------------------------------------------------------------------
# Horizon derivation helper
# ---------------------------------------------------------------------------


def horizon_from_chorizon(
    *,
    layer_num: int,
    hzdepb_cm: float,
    sandtotal_r: float,
    silttotal_r: float,
    claytotal_r: float,
    ksat_umps: float,
    dbthirdbar: float,
    wthirdbar_pct: float,
    wfifteenbar_pct: float,
    om_r: float,
    rock_pct: float | None = None,
    caco3_pct: float | None = None,
    ph_value: float | None = None,
    ec_dsm: float = 0.0,
) -> SoilHorizon:
    """Build a :class:`SoilHorizon` from one SSURGO ``chorizon`` row.

    Computes:
        * ``dp``       = ``hzdepb_cm × 10`` (cm → mm).
        * ``carbon``   = ``om_to_oc(om_r)``.
        * ``awc``      = ``(wthirdbar - wfifteenbar) / 100`` (% → fraction).
        * ``soil_k``   = ``ksat_umps_to_mmph(ksat_umps)``.
        * ``alb``      = ``compute_albedo(carbon)``.
        * ``usle_k``   = ``compute_usle_k(sand, silt, clay, carbon)``.

    ``rock_pct`` defaults to ``2.0`` (typical SSURGO horizons without a
    ``chfrags`` entry are effectively rock-free but 2% is a safer
    non-zero default for SWAT+'s percolation calculator).

    Designed to take the **exact column names** that
    :mod:`swatplus_builder.soil.gnatsgo` pulls from the ``chorizon``
    table, so the fetcher can do:

    .. code-block:: python

        SoilHorizon = horizon_from_chorizon(layer_num=n, **row_as_kwargs)
    """
    if wfifteenbar_pct > wthirdbar_pct:
        # Field capacity must exceed wilting point; swap to keep physical
        # sanity instead of erroring — a few SSURGO horizons ship
        # inverted values in edge cases.
        wthirdbar_pct, wfifteenbar_pct = wfifteenbar_pct, wthirdbar_pct
    awc = max(0.0, (wthirdbar_pct - wfifteenbar_pct) / 100.0)

    carbon = om_to_oc(max(0.0, om_r))
    sand = max(0.0, min(100.0, sandtotal_r))
    silt = max(0.0, min(100.0, silttotal_r))
    clay = max(0.0, min(100.0, claytotal_r))
    rock = max(0.0, min(100.0, rock_pct if rock_pct is not None else 2.0))

    return SoilHorizon(
        layer_num=layer_num,
        dp=max(1.0, hzdepb_cm * 10.0),
        bd=max(0.5, min(2.5, dbthirdbar)),
        awc=awc,
        soil_k=ksat_umps_to_mmph(max(0.0, ksat_umps)),
        carbon=carbon,
        clay=clay,
        silt=silt,
        sand=sand,
        rock=rock,
        alb=compute_albedo(carbon),
        usle_k=compute_usle_k(
            sand_pct=sand, silt_pct=silt, clay_pct=clay, carbon_pct=carbon,
        ),
        ec=max(0.0, ec_dsm),
        caco3=caco3_pct,
        ph=ph_value,
    )
