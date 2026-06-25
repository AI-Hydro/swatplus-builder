"""Default land-use → SWAT+ plant code mappings.

The SWAT+ Editor's ``gis_hrus.landuse`` column is a foreign-key-style
reference into ``plants_plt.name`` (or ``urban_urb.name``) inside the
project database. Every HRU's landuse string MUST resolve to a row in
those tables at ``import_gis`` time, or the editor raises::

    Landuse type 'lu_82' not found in plants_plt or urban_urb tables.

Historically, agents had to build this map themselves. This module ships
a validated default for **NLCD 2021** (the National Land Cover Database
published by USGS/MRLC) so the standard workflow::

    from swatplus_builder.gis.landuse import NLCD_TO_SWATPLUS
    from swatplus_builder.gis.hru import create_hrus

    hrus = create_hrus(
        watershed, landuse_raster=nlcd_tif, soil_raster=mukey_tif,
        landuse_lookup=NLCD_TO_SWATPLUS,
    )

…just works against the default ``swatplus_datasets.sqlite``.

The codes below are the 4-letter plant/urban names that ship with
SWAT+ Editor v3.2.2's reference database (``plants_plt`` + ``urban_urb``).
They are the same codes QSWATPlus emits for its NLCD landuse templates.

If a project uses a non-standard LU classification (MODIS, ESA WorldCover,
CDL, custom) the agent can pass its own ``{int: str}`` map — but the
strings must still match plant/urban names in the target datasets DB.
"""

from __future__ import annotations

__all__ = [
    "NLCD_AVAILABLE_YEARS",
    "NLCD_CLASS_DESCRIPTIONS",
    "NLCD_TO_SWATPLUS",
    "NLCD_URBAN_CODES",
    "is_urban",
    "is_water",
    "resolve_landuse",
    "select_nlcd_year_for_simulation",
]


# ---------------------------------------------------------------------------
# Primary NLCD-2021 → SWAT+ plant/urban code map.
# ---------------------------------------------------------------------------
#
# Sources cross-referenced:
#   * USGS MRLC NLCD 2021 class legend
#     (https://www.mrlc.gov/data/type/land-cover)
#   * SWAT+ Editor v3.2.2 shipped ``plants_plt.name`` + ``urban_urb.name``
#     column values (see vendored ``swatplus_datasets.sqlite``).
#   * QSWATPlus NLCD landuse template (``QSWATPlus/TauDEM5Bin/nlcd*.csv``).
#
# Philosophy:
#   * All 20 current NLCD-2021 classes mapped. No "TBD" placeholders.
#   * Urban classes route to ``urban_urb`` codes (prefixed ``UR…`` / ``UC..``),
#     which SWAT+ recognises as urban HRUs with impervious fractions.
#   * Ambiguous classes (shrub vs. range, barren vs. rangeland) fall to the
#     most conservative rangeland or barren code so we never block import.
NLCD_TO_SWATPLUS: dict[int, str] = {
    # -- Water --
    11: "WATR",  # Open Water
    12: "WATR",  # Perennial Ice/Snow (conservative: treat as water)
    # -- Developed (urban) --
    21: "URLD",  # Developed, Open Space         → urban low density
    22: "URMD",  # Developed, Low Intensity      → urban medium density
    23: "URHD",  # Developed, Medium Intensity   → urban high density
    24: "UCOM",  # Developed, High Intensity     → urban commercial
    # -- Barren --
    31: "BSVG",  # Barren Land (Rock/Sand/Clay)  → barren/sparsely vegetated
    # -- Forest --
    41: "FRSD",  # Deciduous Forest
    42: "FRSE",  # Evergreen Forest
    43: "FRST",  # Mixed Forest
    # -- Shrubland --
    51: "RNGB",  # Dwarf Scrub (Alaska only)     → range brush
    52: "RNGB",  # Shrub/Scrub                    → range brush
    # -- Herbaceous --
    71: "RNGE",  # Grassland/Herbaceous           → range grass
    72: "RNGE",  # Sedge/Herbaceous (Alaska)
    73: "RNGE",  # Lichens (Alaska)
    74: "RNGE",  # Moss (Alaska)
    # -- Agriculture --
    81: "HAY",   # Pasture/Hay                    → hay/pasture
    82: "AGRL",  # Cultivated Crops               → generic agriculture
    # -- Wetlands --
    90: "WETF",  # Woody Wetlands                 → wetland-forested
    95: "WETN",  # Emergent Herbaceous Wetlands   → wetland-non-forested
}


NLCD_CLASS_DESCRIPTIONS: dict[int, str] = {
    11: "Open Water",
    12: "Perennial Ice/Snow",
    21: "Developed, Open Space",
    22: "Developed, Low Intensity",
    23: "Developed, Medium Intensity",
    24: "Developed, High Intensity",
    31: "Barren Land (Rock/Sand/Clay)",
    41: "Deciduous Forest",
    42: "Evergreen Forest",
    43: "Mixed Forest",
    51: "Dwarf Scrub",
    52: "Shrub/Scrub",
    71: "Grassland/Herbaceous",
    72: "Sedge/Herbaceous",
    73: "Lichens",
    74: "Moss",
    81: "Pasture/Hay",
    82: "Cultivated Crops",
    90: "Woody Wetlands",
    95: "Emergent Herbaceous Wetlands",
}


NLCD_URBAN_CODES: frozenset[int] = frozenset({21, 22, 23, 24})
"""NLCD codes that route to SWAT+ ``urban_urb`` rather than ``plants_plt``.

Agents building a mock or seeded datasets DB must ensure ``urban_urb``
contains an entry for every SWAT+ code produced by these NLCD classes.
"""


# NLCD water classes — useful for waterbody subtraction (Phase 2c).
_NLCD_WATER_CODES: frozenset[int] = frozenset({11, 12})


NLCD_AVAILABLE_YEARS: tuple[int, ...] = (2001, 2004, 2006, 2008, 2011, 2013, 2016, 2019, 2021)
"""Legacy NLCD land-cover epochs currently used by the pygeohydro fetch path."""


def is_urban(nlcd_code: int) -> bool:
    """Return True if the NLCD code is an urban / developed class."""
    return int(nlcd_code) in NLCD_URBAN_CODES


def is_water(nlcd_code: int) -> bool:
    """Return True if the NLCD code is open water / ice.

    Used by the (future) waterbody-subtraction path to divert pixels from
    HRU generation to ``gis_water``.
    """
    return int(nlcd_code) in _NLCD_WATER_CODES


def resolve_landuse(
    code: int,
    lookup: dict[int, str] | None = None,
    *,
    default_lookup: dict[int, str] = NLCD_TO_SWATPLUS,
    fallback_prefix: str = "lu_",
) -> str:
    """Resolve a raster landuse code into a SWAT+ plant / urban name.

    Resolution order:
      1. ``lookup`` (caller-supplied, if provided).
      2. ``default_lookup`` (NLCD-2021 by default).
      3. ``f"{fallback_prefix}{code}"`` — lets HRU generation finish so
         the agent can see the offending code(s) in the catalog and
         either extend the mock DB or patch their raster.

    Args:
        code: Integer raster value (NLCD class, CDL class, …).
        lookup: Caller-supplied mapping. Wins over ``default_lookup``.
            If ``None``, only ``default_lookup`` is consulted.
        default_lookup: Fallback if ``lookup`` doesn't contain ``code``.
            Defaults to :data:`NLCD_TO_SWATPLUS`; pass ``{}`` to disable.
        fallback_prefix: String used to build the sentinel name when
            neither map has the code. ``"lu_"`` matches the historical
            behavior of ``gis.hru._landuse_name``.

    Returns:
        A string suitable for ``gis_hrus.landuse``. Guaranteed non-empty.
    """
    code_i = int(code)
    if lookup and code_i in lookup:
        return lookup[code_i]
    if code_i in default_lookup:
        return default_lookup[code_i]
    return f"{fallback_prefix}{code_i}"


def select_nlcd_year_for_simulation(
    sim_start: str,
    sim_end: str,
    *,
    available_years: tuple[int, ...] = NLCD_AVAILABLE_YEARS,
) -> dict[str, object]:
    """Select the NLCD epoch closest to a simulation window midpoint.

    The current acquisition path requests legacy NLCD epochs from MRLC via
    pygeohydro. This helper makes the temporal choice explicit and records the
    mismatch instead of silently using the newest raster for older simulations.
    """

    if not available_years:
        raise ValueError("available_years must contain at least one NLCD year")
    try:
        start_year = int(str(sim_start)[:4])
        end_year = int(str(sim_end)[:4])
    except Exception as exc:
        raise ValueError(f"invalid simulation dates: {sim_start!r}, {sim_end!r}") from exc
    if end_year < start_year:
        raise ValueError(f"sim_end year {end_year} is earlier than sim_start year {start_year}")

    midpoint = int(round((start_year + end_year) / 2.0))
    years = tuple(sorted(int(year) for year in available_years))
    selected = min(years, key=lambda year: (abs(year - midpoint), year))
    return {
        "selected_year": selected,
        "available_years": list(years),
        "sim_start": str(sim_start),
        "sim_end": str(sim_end),
        "sim_midpoint_year": midpoint,
        "landuse_vintage_mismatch_years": selected - midpoint,
    }
