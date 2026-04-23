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
    adjustment_type: AdjustmentType
    tier: int


def _p(
    name: str,
    file: str,
    scope: ParameterScope,
    lo: float,
    hi: float,
    default: float,
    units: str,
    description: str,
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
        adjustment_type=adjustment_type,
        tier=tier,
    )


registry: dict[str, Parameter] = {
    "CN2": _p(
        "CN2",
        "hydrology.hyd",
        ParameterScope.HRU,
        35.0,
        98.0,
        75.0,
        "dimensionless",
        "SCS curve number",
        AdjustmentType.REPLACE,
        1,
    ),
    "ALPHA_BF": _p(
        "ALPHA_BF",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.0,
        1.0,
        0.048,
        "1/day",
        "Baseflow recession constant",
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
        AdjustmentType.REPLACE,
        1,
    ),
    "ESCO": _p(
        "ESCO",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.0,
        1.0,
        0.95,
        "fraction",
        "Soil evaporation compensation factor",
        AdjustmentType.REPLACE,
        2,
    ),
    "EPCO": _p(
        "EPCO",
        "hydrology.hyd",
        ParameterScope.HRU,
        0.0,
        1.0,
        1.0,
        "fraction",
        "Plant uptake compensation factor",
        AdjustmentType.REPLACE,
        2,
    ),
    "SURLAG": _p(
        "SURLAG",
        "parameters.bsn",
        ParameterScope.GLOBAL,
        0.05,
        24.0,
        4.0,
        "day",
        "Surface runoff lag coefficient",
        AdjustmentType.REPLACE,
        1,
    ),
    "CH_N2": _p(
        "CH_N2",
        "channel-lte.cha",
        ParameterScope.CHANNEL,
        0.014,
        0.15,
        0.05,
        "dimensionless",
        "Manning n for main channel",
        AdjustmentType.REPLACE,
        2,
    ),
    "CH_K2": _p(
        "CH_K2",
        "channel-lte.cha",
        ParameterScope.CHANNEL,
        0.0,
        500.0,
        50.0,
        "mm/hr",
        "Channel hydraulic conductivity",
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
        AdjustmentType.REPLACE,
        3,
    ),
    "GW_REVAP": _p(
        "GW_REVAP",
        "aquifer.aqu",
        ParameterScope.SUBBASIN,
        0.02,
        0.2,
        0.02,
        "fraction",
        "Groundwater revap coefficient",
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

