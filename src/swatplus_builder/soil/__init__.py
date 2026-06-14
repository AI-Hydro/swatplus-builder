"""SWAT+ soils subpackage.

Public pieces:

* :class:`~swatplus_builder.types.SoilProfile` /
  :class:`~swatplus_builder.types.SoilHorizon` — the typed data contract.
* :mod:`.params` — pure SWAT+ parameter math (USLE K, albedo,
  unit conversions). No I/O, no optional deps.
* :mod:`.writer` — :func:`write_soils` upserts profiles into a project
  DB's ``soils_sol`` + ``soils_sol_layer`` tables.
* :mod:`.gnatsgo` — real gNATSGO adapter via Planetary Computer STAC.
  Optional dep (``pip install 'swatplus-builder[soils]'``); imports are
  lazy.
"""

from __future__ import annotations

from .gnatsgo import (
    DEFAULT_PC_STAC_URL,
    GnatsgoFetchOptions,
    SoilProfilesResult,
    fetch_gnatsgo_profiles,
    fetch_gnatsgo_profiles_result,
)
from .params import (
    DEFAULT_ALBEDO_BARE,
    VAN_BEMMELEN_OC_FRACTION,
    collapse_dual_hyd_group,
    compute_albedo,
    compute_usle_k,
    horizon_from_chorizon,
    ksat_umps_to_mmph,
    om_to_oc,
)
from .writer import SoilsWriteResult, write_soils

__all__ = [
    "DEFAULT_ALBEDO_BARE",
    "DEFAULT_PC_STAC_URL",
    "GnatsgoFetchOptions",
    "SoilsWriteResult",
    "VAN_BEMMELEN_OC_FRACTION",
    "collapse_dual_hyd_group",
    "compute_albedo",
    "compute_usle_k",
    "fetch_gnatsgo_profiles",
    "fetch_gnatsgo_profiles_result",
    "horizon_from_chorizon",
    "ksat_umps_to_mmph",
    "om_to_oc",
    "SoilProfilesResult",
    "write_soils",
]
