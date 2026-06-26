"""Typed SWAT+ parameter registry for calibration workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ParameterScope(str, Enum):
    """Supported parameter application scopes."""

    GLOBAL = "global"
    HRU = "hru"
    SUBBASIN = "subbasin"
    CHANNEL = "channel"


class AdjustmentType(str, Enum):
    """Parameter adjustment semantics."""

    REPLACE = "replace"
    MULTIPLY = "multiply"
    ADD = "add"


class ChangeType(str, Enum):
    """pySWATPlus/SWAT+ calibration change-type semantics."""

    ABSVAL = "absval"
    PCTCHG = "pctchg"
    ABSCHG = "abschg"


@dataclass(frozen=True)
class Parameter:
    """Calibration parameter specification."""

    name: str
    file: str
    scope: ParameterScope
    range: tuple[float, float]
    default: float
    units: str
    description: str
    physical_meaning: str
    change_type: ChangeType
    adjustment_type: AdjustmentType
    tier: int

    def to_pyswatplus_dict(self, value: float) -> dict[str, object]:
        """Convert one parameter assignment to pySWATPlus-friendly mapping."""
        validate_value(self.name, float(value))
        return {
            "name": self.name.lower(),
            "value": float(value),
            "change_type": self.change_type.value,
        }

    def to_pyswatplus_bounds_dict(self) -> dict[str, object]:
        """Convert parameter bounds to pySWATPlus-friendly mapping."""
        lo, hi = self.range
        return {
            "name": self.name.lower(),
            "min": float(lo),
            "max": float(hi),
            "change_type": self.change_type.value,
        }


def _p(
    name: str,
    file: str,
    scope: ParameterScope,
    lo: float,
    hi: float,
    default: float,
    units: str,
    description: str,
    physical_meaning: str,
    change_type: ChangeType,
    adjustment_type: AdjustmentType,
    tier: int,
) -> Parameter:
    if lo > hi:
        raise ValueError(f"Invalid range for {name}: [{lo}, {hi}]")
    if not (lo <= default <= hi):
        raise ValueError(f"Default for {name} must be within [{lo}, {hi}]")
    if tier not in {1, 2, 3}:
        raise ValueError(f"Tier for {name} must be 1, 2, or 3.")
    return Parameter(
        name=name,
        file=file,
        scope=scope,
        range=(lo, hi),
        default=default,
        units=units,
        description=description,
        physical_meaning=physical_meaning,
        change_type=change_type,
        adjustment_type=adjustment_type,
        tier=tier,
    )


registry: dict[str, Parameter] = {
    "CN2": _p(
        "CN2",
        "cntable.lum",
        ParameterScope.HRU,
        35.0,
        98.0,
        75.0,
        "dimensionless",
        "SCS curve number",
        "Runoff generation potential; higher CN2 generally increases direct runoff.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "PERCO": _p(
        "PERCO",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.01,
        1.0,
        0.5,
        "fraction",
        "Percolation coefficient",
        "Controls soil-water percolation versus lateral-flow partitioning.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "LATQ_CO": _p(
        "LATQ_CO",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.001,
        1.0,
        0.01,
        "fraction/day",
        "Lateral flow delivery coefficient",
        "Controls the fraction of lateral flow delivered to channels per day.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "LAT_TTIME": _p(
        "LAT_TTIME",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.0,
        120.0,
        0.0,
        "day",
        "Lateral flow travel time",
        "Controls lagged lateral-flow release to channels; zero lets SWAT+ calculate travel time.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "CN3_SWF": _p(
        "CN3_SWF",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.0,
        1.0,
        0.95,
        "fraction",
        "Curve-number soil-water factor",
        "SWAT+ soft-calibration control for surface-runoff response.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "PET_CO": _p(
        "PET_CO",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.8,
        1.2,
        1.0,
        "dimensionless",
        "PET correction coefficient",
        "Scales potential evapotranspiration demand in full-mode HRU hydrology.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "RCHG_DP": _p(
        "RCHG_DP",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.0,
        0.8,
        0.05,
        "fraction",
        "Deep aquifer recharge fraction",
        "Controls fraction of recharge routed to deep aquifer storage.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "ALPHA_BF": _p(
        "ALPHA_BF",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.001,
        1.0,
        0.048,
        "1/day",
        "Baseflow recession constant",
        "Controls baseflow recession response speed in groundwater contribution.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "GW_DELAY": _p(
        "GW_DELAY",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.0,
        500.0,
        31.0,
        "day",
        "Groundwater delay time",
        "Delay between recharge and groundwater return flow to channels.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "ESCO": _p(
        "ESCO",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.01,
        1.0,
        0.95,
        "fraction",
        "Soil evaporation compensation factor",
        "Controls depth distribution of soil evaporation demand.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        2,
    ),
    "EPCO": _p(
        "EPCO",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.01,
        1.0,
        1.0,
        "fraction",
        "Plant uptake compensation factor",
        "Controls soil-profile compensation for plant water uptake.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        2,
    ),
    "SURLAG": _p(
        "SURLAG",
        "parameters.bsn",
        ParameterScope.GLOBAL,
        1.0,
        24.0,
        4.0,
        "day",
        "Surface runoff lag coefficient",
        "Controls runoff routing lag from land phase to channel network.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        1,
    ),
    "CH_N2": _p(
        "CH_N2",
        "hyd-sed-lte.cha",
        ParameterScope.CHANNEL,
        0.014,
        0.15,
        0.05,
        "dimensionless",
        "Manning n for main channel",
        "Channel roughness controlling velocity and attenuation in routing.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        2,
    ),
    "CH_K2": _p(
        "CH_K2",
        "hyd-sed-lte.cha",
        ParameterScope.CHANNEL,
        0.0,
        500.0,
        50.0,
        "mm/hr",
        "Channel hydraulic conductivity",
        "Channel bed seepage potential to groundwater.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        2,
    ),
    "SOL_AWC": _p(
        "SOL_AWC",
        "soils.sol",
        ParameterScope.HRU,
        0.0,
        1.0,
        0.2,
        "fraction",
        "Available water capacity",
        "Soil available water storage capacity affecting runoff/ET partitioning.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        2,
    ),
    "SOL_K": _p(
        "SOL_K",
        "soils.sol",
        ParameterScope.HRU,
        0.0,
        2000.0,
        50.0,
        "mm/hr",
        "Saturated hydraulic conductivity",
        "Soil saturated conductivity controlling infiltration and percolation.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        2,
    ),
    "GWQMN": _p(
        "GWQMN",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.0,
        5000.0,
        0.0,
        "mm",
        "Threshold water depth for return flow",
        "Groundwater threshold for initiating baseflow return.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        2,
    ),
    "REVAPMN": _p(
        "REVAPMN",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.0,
        500.0,
        0.0,
        "mm",
        "Threshold water depth for revap",
        "Threshold groundwater storage for revap to unsaturated zone.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        3,
    ),
    "GW_REVAP": _p(
        "GW_REVAP",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.0,
        1.0,
        0.02,
        "fraction",
        "Groundwater revap coefficient",
        "Fractional rate of upward groundwater movement (revap).",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        3,
    ),
    "PLAPS": _p(
        "PLAPS",
        "basin.bsn",
        ParameterScope.GLOBAL,
        -100.0,
        100.0,
        0.0,
        "mm/km",
        "Precipitation lapse rate",
        "Adjusts precipitation with elevation gradient.",
        ChangeType.ABSCHG,
        AdjustmentType.ADD,
        3,
    ),
    "TLAPS": _p(
        "TLAPS",
        "basin.bsn",
        ParameterScope.GLOBAL,
        -10.0,
        10.0,
        0.0,
        "degC/km",
        "Temperature lapse rate",
        "Adjusts temperature with elevation gradient.",
        ChangeType.ABSCHG,
        AdjustmentType.ADD,
        3,
    ),
    "SFTMP": _p(
        "SFTMP",
        "snow.sno",
        ParameterScope.GLOBAL,
        -5.0,
        5.0,
        1.0,
        "degC",
        "Snowfall temperature",
        "Temperature threshold controlling snow vs rain partitioning.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        3,
    ),
    "SMTMP": _p(
        "SMTMP",
        "snow.sno",
        ParameterScope.GLOBAL,
        -5.0,
        5.0,
        0.5,
        "degC",
        "Snow melt base temperature",
        "Base temperature threshold for snowmelt onset.",
        ChangeType.ABSVAL,
        AdjustmentType.REPLACE,
        3,
    ),
}


def get_parameter(name: str) -> Parameter:
    """Return one parameter spec by name."""
    try:
        return registry[name]
    except KeyError as exc:
        raise KeyError(f"Unknown parameter: {name}") from exc


def validate_value(name: str, value: float) -> None:
    """Validate numeric bounds for a parameter value."""
    p = get_parameter(name)
    lo, hi = p.range
    if not (lo <= value <= hi):
        raise ValueError(f"{name}={value} outside bounds [{lo}, {hi}]")


def validate_assignment(name: str, value: float, scope: ParameterScope) -> None:
    """Validate value bounds and assignment scope compatibility."""
    p = get_parameter(name)
    validate_value(name, value)
    if p.scope != scope:
        raise ValueError(f"{name} requires scope '{p.scope.value}', got '{scope.value}'")
