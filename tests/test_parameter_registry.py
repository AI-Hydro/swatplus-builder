from __future__ import annotations

import pytest

from swatplus_builder.full_mode.parameter_bridge import WRITERS
from swatplus_builder.params import (
    ParameterScope,
    get_parameter,
    registry,
    validate_assignment,
    validate_value,
)
from swatplus_builder.params.governance import (
    FULL_MODE_CORE_PARAMETERS,
    FULL_MODE_EXTENDED_PARAMETERS,
    FULL_MODE_PARAMETER_GOVERNANCE,
    calibration_eligible_full_mode_parameters,
)


def test_registry_contains_phase3c_required_parameters() -> None:
    required = {
        "CN2",
        "PERCO",
        "LATQ_CO",
        "PET_CO",
        "RCHG_DP",
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
        "LAT_TTIME",
        "CN3_SWF",
    }
    assert required.issubset(set(registry.keys()))


def test_get_parameter_and_bounds_validation() -> None:
    p = get_parameter("CN2")
    assert p.scope is ParameterScope.HRU
    validate_value("CN2", 75.0)
    with pytest.raises(ValueError):
        validate_value("CN2", 120.0)


def test_pet_co_uses_documented_swatplus_hydrology_range() -> None:
    p = get_parameter("PET_CO")

    assert p.range == (0.8, 1.2)
    validate_value("PET_CO", 0.8)
    validate_value("PET_CO", 1.2)
    with pytest.raises(ValueError):
        validate_value("PET_CO", 0.3)


def test_esco_epco_use_documented_swatplus_hydrology_ranges() -> None:
    esco = get_parameter("ESCO")
    epco = get_parameter("EPCO")

    assert esco.range == (0.01, 1.0)
    assert epco.range == (0.01, 1.0)
    validate_value("ESCO", 0.01)
    validate_value("EPCO", 0.01)
    with pytest.raises(ValueError):
        validate_value("ESCO", 0.0)
    with pytest.raises(ValueError):
        validate_value("EPCO", 0.0)


def test_full_mode_bridge_ranges_match_registry() -> None:
    assert get_parameter("CN2").range == (35.0, 98.0)
    assert get_parameter("SURLAG").range == (1.0, 24.0)
    assert get_parameter("ALPHA_BF").range == (0.001, 1.0)
    assert get_parameter("LAT_TTIME").range == (0.0, 120.0)
    assert get_parameter("CN3_SWF").range == (0.0, 1.0)
    assert get_parameter("CH_N2").file == "hyd-sed-lte.cha"
    assert get_parameter("CH_N2").range == (0.014, 0.15)
    assert get_parameter("CH_K2").file == "hyd-sed-lte.cha"
    assert get_parameter("CH_K2").range == (0.0, 500.0)


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


def test_full_mode_governance_registry_and_bridge_are_aligned() -> None:
    expected = {
        "CN2",
        "PERCO",
        "LATQ_CO",
        "PET_CO",
        "ESCO",
        "EPCO",
        "SURLAG",
        "ALPHA_BF",
        "RCHG_DP",
        "GW_DELAY",
    }
    assert set(FULL_MODE_CORE_PARAMETERS) == expected
    assert expected.issubset(registry)
    assert expected.issubset(WRITERS)
    expected_extended = {"SFTMP", "SMTMP", "LAT_TTIME", "CN3_SWF", "CH_N2", "CH_K2"}
    assert set(FULL_MODE_EXTENDED_PARAMETERS) == expected_extended
    assert set(FULL_MODE_PARAMETER_GOVERNANCE) == expected | set(FULL_MODE_EXTENDED_PARAMETERS)
    assert "GW_DELAY" not in calibration_eligible_full_mode_parameters()
    assert {"PET_CO", "EPCO", "SURLAG", "ALPHA_BF", "RCHG_DP"}.issubset(
        calibration_eligible_full_mode_parameters()
    )
    assert expected_extended.issubset(calibration_eligible_full_mode_parameters())
    assert expected_extended.issubset(WRITERS)
