"""Tests for :mod:`swatplus_builder.soil.params`.

Pure math — all hermetic, exact numeric comparisons where possible.
Reference values come from Williams (1995) worked examples and manual
calculator runs with the published formulas (not from the code under
test).
"""

from __future__ import annotations

import math

import pytest

from swatplus_builder.errors import SwatBuilderInputError
from swatplus_builder.soil.params import (
    DEFAULT_ALBEDO_BARE,
    VAN_BEMMELEN_OC_FRACTION,
    collapse_dual_hyd_group,
    compute_albedo,
    compute_usle_k,
    horizon_from_chorizon,
    ksat_umps_to_mmph,
    om_to_oc,
)


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


class TestKsatConversion:
    def test_exact_factor(self):
        # 1 µm/s × 3600 s/h × 10^-3 mm/µm = 3.6 mm/h
        assert ksat_umps_to_mmph(1.0) == pytest.approx(3.6)

    def test_zero(self):
        assert ksat_umps_to_mmph(0.0) == 0.0

    def test_negative_rejected(self):
        with pytest.raises(SwatBuilderInputError, match="cannot be negative"):
            ksat_umps_to_mmph(-1.0)


class TestOMtoOC:
    def test_default_factor(self):
        assert om_to_oc(10.0) == pytest.approx(5.8)

    def test_zero_om(self):
        assert om_to_oc(0.0) == 0.0

    def test_custom_factor(self):
        assert om_to_oc(10.0, factor=0.5) == pytest.approx(5.0)

    def test_negative_om_rejected(self):
        with pytest.raises(SwatBuilderInputError, match="cannot be negative"):
            om_to_oc(-1.0)

    def test_invalid_factor(self):
        with pytest.raises(SwatBuilderInputError, match="must be in"):
            om_to_oc(5.0, factor=1.5)
        with pytest.raises(SwatBuilderInputError, match="must be in"):
            om_to_oc(5.0, factor=0.0)

    def test_constant_documented(self):
        # Van Bemmelen factor is 0.58 by convention. If we ever change
        # the default, this test forces us to update the ADR in the
        # same commit.
        assert VAN_BEMMELEN_OC_FRACTION == 0.58


# ---------------------------------------------------------------------------
# Hydrologic group
# ---------------------------------------------------------------------------


class TestCollapseDualHydGroup:
    @pytest.mark.parametrize("code,expected", [
        ("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"),
        (" a ", "A"),
        ("A/D", "D"), ("B/D", "D"), ("C/D", "D"),
        (None, "D"), ("", "D"),
    ])
    def test_known_codes(self, code, expected):
        assert collapse_dual_hyd_group(code) == expected

    def test_unknown_single_letter(self):
        with pytest.raises(SwatBuilderInputError, match="unrecognized"):
            collapse_dual_hyd_group("E")

    def test_unknown_dual(self):
        with pytest.raises(SwatBuilderInputError, match="unrecognized"):
            collapse_dual_hyd_group("X/Y")


# ---------------------------------------------------------------------------
# Albedo
# ---------------------------------------------------------------------------


class TestComputeAlbedo:
    def test_zero_carbon_returns_0p15(self):
        # 0.15 × exp(0) = 0.15, then clamped to [0.01, 0.25]
        assert compute_albedo(0.0) == pytest.approx(0.15)

    def test_high_carbon_clamped(self):
        # With C=50%, 0.15*exp(-12.5) ≈ 5.5e-7 → clamped to 0.01 floor.
        assert compute_albedo(50.0) == pytest.approx(0.01)

    def test_monotonically_decreases(self):
        """More organic carbon → lower albedo (darker soil)."""
        prev = compute_albedo(0.0)
        for c in [0.5, 1.0, 2.0, 5.0]:
            a = compute_albedo(c)
            assert a <= prev
            prev = a

    def test_none_returns_default(self):
        assert compute_albedo(None) == DEFAULT_ALBEDO_BARE

    def test_negative_returns_default(self):
        assert compute_albedo(-1.0) == DEFAULT_ALBEDO_BARE


# ---------------------------------------------------------------------------
# USLE K
# ---------------------------------------------------------------------------


class TestComputeUsleK:
    def test_loam_matches_manual_calc(self):
        """Soil: sand=40, silt=40, clay=20, OC=1.0. Manual value
        ≈ 0.27 t·ha·h / (ha·MJ·mm)."""
        k = compute_usle_k(sand_pct=40, silt_pct=40, clay_pct=20, carbon_pct=1.0)
        # Recomputed by hand from the Williams formula.
        sn1 = 1 - 40/100
        f_csand = 0.2 + 0.3 * math.exp(-0.0256 * 40 * (1 - 40/100))
        f_clsi = (40 / (20 + 40)) ** 0.3
        f_orgc = 1 - (0.25 * 1.0) / (1.0 + math.exp(3.72 - 2.95 * 1.0))
        f_hisand = 1 - (0.7 * sn1) / (sn1 + math.exp(-5.51 + 22.9 * sn1))
        expected = f_csand * f_clsi * f_orgc * f_hisand
        assert k == pytest.approx(expected, abs=1e-6)

    def test_clamped_to_065_upper(self):
        """Pure silt with zero OC is the high-K extreme; cap at 0.65."""
        k = compute_usle_k(sand_pct=0, silt_pct=100, clay_pct=0, carbon_pct=0)
        assert k <= 0.65

    def test_clamped_to_001_lower(self):
        """A degenerate combo shouldn't fall below 0.01."""
        k = compute_usle_k(sand_pct=100, silt_pct=0, clay_pct=0, carbon_pct=50)
        assert k >= 0.01

    def test_negative_fraction_rejected(self):
        with pytest.raises(SwatBuilderInputError, match="cannot be negative"):
            compute_usle_k(sand_pct=-1, silt_pct=50, clay_pct=50, carbon_pct=1)

    def test_nonsensical_sum_rejected(self):
        with pytest.raises(SwatBuilderInputError, match=r"expected ~100"):
            compute_usle_k(sand_pct=10, silt_pct=10, clay_pct=10, carbon_pct=1)

    def test_tolerates_small_rounding_slop(self):
        # Sum = 101 — within ±20 tolerance, must succeed.
        compute_usle_k(sand_pct=40.3, silt_pct=40.3, clay_pct=20.4, carbon_pct=1)

    def test_oc_decreases_k(self):
        """More organic carbon → more aggregate stability → lower K."""
        base = compute_usle_k(sand_pct=40, silt_pct=40, clay_pct=20, carbon_pct=0.5)
        enriched = compute_usle_k(sand_pct=40, silt_pct=40, clay_pct=20, carbon_pct=4.0)
        assert enriched < base


# ---------------------------------------------------------------------------
# horizon_from_chorizon
# ---------------------------------------------------------------------------


class TestHorizonFromChorizon:
    def test_happy_path_values(self):
        h = horizon_from_chorizon(
            layer_num=1,
            hzdepb_cm=20.0,          # → dp=200 mm
            sandtotal_r=40.0,
            silttotal_r=40.0,
            claytotal_r=20.0,
            ksat_umps=10.0,          # → soil_k=36 mm/h
            dbthirdbar=1.4,
            wthirdbar_pct=30.0,      # FC
            wfifteenbar_pct=15.0,    # WP → AWC = 0.15
            om_r=2.0,                # → OC=1.16
        )
        assert h.layer_num == 1
        assert h.dp == 200.0
        assert h.soil_k == pytest.approx(36.0)
        assert h.awc == pytest.approx(0.15)
        assert h.carbon == pytest.approx(1.16)
        assert h.bd == pytest.approx(1.4)
        assert 0.01 <= h.alb <= 0.25
        assert 0.01 <= h.usle_k <= 0.65

    def test_inverted_fc_wp_swapped(self):
        h = horizon_from_chorizon(
            layer_num=1, hzdepb_cm=20,
            sandtotal_r=40, silttotal_r=40, claytotal_r=20,
            ksat_umps=10, dbthirdbar=1.4,
            wthirdbar_pct=15.0,     # INVERTED — FC < WP
            wfifteenbar_pct=30.0,
            om_r=1.0,
        )
        assert h.awc == pytest.approx(0.15)

    def test_rock_default_2pct(self):
        h = horizon_from_chorizon(
            layer_num=1, hzdepb_cm=20,
            sandtotal_r=40, silttotal_r=40, claytotal_r=20,
            ksat_umps=10, dbthirdbar=1.4,
            wthirdbar_pct=30, wfifteenbar_pct=15,
            om_r=1,
        )
        assert h.rock == 2.0

    def test_rock_explicit_override(self):
        h = horizon_from_chorizon(
            layer_num=1, hzdepb_cm=20,
            sandtotal_r=40, silttotal_r=40, claytotal_r=20,
            ksat_umps=10, dbthirdbar=1.4,
            wthirdbar_pct=30, wfifteenbar_pct=15,
            om_r=1, rock_pct=15.0,
        )
        assert h.rock == 15.0

    def test_clamps_bd_to_physical_range(self):
        """A SSURGO placeholder row might carry bd=0.2 (impossible).
        We clamp to [0.5, 2.5] so the engine's validator doesn't reject
        it."""
        h = horizon_from_chorizon(
            layer_num=1, hzdepb_cm=20,
            sandtotal_r=40, silttotal_r=40, claytotal_r=20,
            ksat_umps=10, dbthirdbar=0.2,
            wthirdbar_pct=30, wfifteenbar_pct=15,
            om_r=1,
        )
        assert h.bd == 0.5

    def test_hzdepb_floored_to_1mm(self):
        h = horizon_from_chorizon(
            layer_num=1, hzdepb_cm=0.0,
            sandtotal_r=40, silttotal_r=40, claytotal_r=20,
            ksat_umps=10, dbthirdbar=1.4,
            wthirdbar_pct=30, wfifteenbar_pct=15,
            om_r=1,
        )
        assert h.dp == 1.0  # min floor so Pydantic gt=0 holds
