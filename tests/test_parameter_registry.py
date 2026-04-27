from __future__ import annotations

import pytest

from swatplus_builder.params import ParameterScope, get_parameter, registry, validate_assignment, validate_value


def test_registry_contains_phase3c_required_parameters() -> None:
    required = {
        "CN2",
        "ALPHA_BF",
        "GW_DELAY",
        "ESCO",
        "EPCO",
        "SURLAG",
        "CH_N2",
        "CH_K2",
        "SOL_AWC",
        "SOL_K",
        "GWQMN",
        "REVAPMN",
        "GW_REVAP",
        "PLAPS",
        "TLAPS",
        "SFTMP",
        "SMTMP",
    }
    assert required.issubset(set(registry.keys()))


def test_get_parameter_and_bounds_validation() -> None:
    p = get_parameter("CN2")
    assert p.scope is ParameterScope.HRU
    validate_value("CN2", 75.0)
    with pytest.raises(ValueError):
        validate_value("CN2", 120.0)


def test_scope_validation_enforced() -> None:
    validate_assignment("ALPHA_BF", 0.1, ParameterScope.SUBBASIN)
    with pytest.raises(ValueError):
        validate_assignment("ALPHA_BF", 0.1, ParameterScope.HRU)


def test_registry_exposes_pyswatplus_conversion_helpers() -> None:
    p = get_parameter("CN2")
    d = p.to_pyswatplus_dict(70.0)
    b = p.to_pyswatplus_bounds_dict()
    assert d["name"] == "cn2"
    assert d["change_type"] == "absval"
    assert b["min"] == 35.0
    assert b["max"] == 98.0
