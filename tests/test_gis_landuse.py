"""Unit tests for :mod:`swatplus_builder.gis.landuse`."""

from __future__ import annotations

import pytest

from swatplus_builder.gis.landuse import (
    NLCD_CLASS_DESCRIPTIONS,
    NLCD_TO_SWATPLUS,
    NLCD_URBAN_CODES,
    is_urban,
    is_water,
    resolve_landuse,
)


class TestNlcdLookup:
    """The shipped NLCD 2021 map is complete and covers all legal codes."""

    def test_every_legal_nlcd_code_is_mapped(self) -> None:
        # NLCD 2021 legal codes as published by USGS/MRLC.
        legal = {11, 12, 21, 22, 23, 24, 31, 41, 42, 43,
                 51, 52, 71, 72, 73, 74, 81, 82, 90, 95}
        assert set(NLCD_TO_SWATPLUS) == legal

    def test_every_mapped_value_is_a_4_letter_swatplus_code(self) -> None:
        for code, name in NLCD_TO_SWATPLUS.items():
            assert isinstance(name, str)
            assert 3 <= len(name) <= 4, f"unexpected length for {code!r}: {name!r}"
            assert name.isupper()
            assert name.isalpha()

    def test_class_descriptions_keys_match_lookup_keys(self) -> None:
        assert set(NLCD_CLASS_DESCRIPTIONS) == set(NLCD_TO_SWATPLUS)

    def test_urban_codes_are_a_subset_of_the_lookup(self) -> None:
        assert NLCD_URBAN_CODES <= set(NLCD_TO_SWATPLUS)

    def test_urban_codes_map_to_urban_like_names(self) -> None:
        for code in NLCD_URBAN_CODES:
            name = NLCD_TO_SWATPLUS[code]
            assert name.startswith("U"), f"{code} → {name} does not look urban"

    def test_water_and_ice_map_to_watr(self) -> None:
        assert NLCD_TO_SWATPLUS[11] == "WATR"
        assert NLCD_TO_SWATPLUS[12] == "WATR"

    def test_forest_mapping_specificity(self) -> None:
        assert NLCD_TO_SWATPLUS[41] == "FRSD"  # deciduous
        assert NLCD_TO_SWATPLUS[42] == "FRSE"  # evergreen
        assert NLCD_TO_SWATPLUS[43] == "FRST"  # mixed

    def test_agriculture_split_between_hay_and_cropland(self) -> None:
        assert NLCD_TO_SWATPLUS[81] == "HAY"
        assert NLCD_TO_SWATPLUS[82] == "AGRL"


class TestPredicates:
    def test_is_urban_true_for_developed_classes(self) -> None:
        assert is_urban(21) and is_urban(22) and is_urban(23) and is_urban(24)

    def test_is_urban_false_for_everything_else(self) -> None:
        assert not is_urban(11)
        assert not is_urban(41)
        assert not is_urban(82)

    def test_is_water_true_only_for_water_and_ice(self) -> None:
        assert is_water(11)
        assert is_water(12)
        assert not is_water(31)  # barren
        assert not is_water(90)  # wetland


class TestResolveLanduse:
    def test_default_path_uses_nlcd_lookup(self) -> None:
        assert resolve_landuse(82) == "AGRL"
        assert resolve_landuse(41) == "FRSD"
        assert resolve_landuse(11) == "WATR"

    def test_caller_lookup_wins_over_default(self) -> None:
        custom = {82: "CORN"}
        assert resolve_landuse(82, custom) == "CORN"
        # Codes not in custom fall through to NLCD default.
        assert resolve_landuse(41, custom) == "FRSD"

    def test_missing_code_falls_back_to_sentinel(self) -> None:
        # 999 is not an NLCD class.
        assert resolve_landuse(999) == "lu_999"

    def test_custom_fallback_prefix(self) -> None:
        assert resolve_landuse(999, fallback_prefix="unk_") == "unk_999"

    def test_disabling_default_lookup_with_empty_dict(self) -> None:
        # Pass default_lookup={} → only caller-lookup is considered.
        assert resolve_landuse(82, default_lookup={}) == "lu_82"

    def test_coerces_numpy_like_ints(self) -> None:
        # A numpy integer scalar should be accepted.
        pytest.importorskip("numpy")
        import numpy as np

        assert resolve_landuse(np.int32(82)) == "AGRL"
        assert resolve_landuse(np.int64(999)) == "lu_999"

    def test_empty_custom_lookup_is_transparent(self) -> None:
        assert resolve_landuse(82, {}) == "AGRL"

    def test_none_custom_lookup_is_transparent(self) -> None:
        assert resolve_landuse(82, None) == "AGRL"


class TestIntegrationWithHru:
    """The gis.hru module consumes the default lookup out of the box."""

    def test_import_chain(self) -> None:
        from swatplus_builder.gis.hru import _landuse_name

        assert _landuse_name(82, None) == "AGRL"
        assert _landuse_name(41, None) == "FRSD"

    def test_user_override_wins(self) -> None:
        from swatplus_builder.gis.hru import _landuse_name

        assert _landuse_name(82, {82: "CORN"}) == "CORN"
