"""Tests for delineation topology preflight gate (check_topology_realism).

No WhiteboxTools or real DEM required — all tests use synthetic stats dicts
that mirror the structure produced by delineate().

The 03339000 contrast-basin failure that motivated this gate had:
  n_subbasins=1, n_channels=5331, n_terminals=19, total_area_km2=0.22
  vs NLDI expected area ~3341 km2.
"""

from __future__ import annotations

import pytest

from swatplus_builder.errors import SwatBuilderPipelineError
from swatplus_builder.gis.delineation import check_topology_realism


def _stats(
    n_subbasins: float = 43,
    n_channels: float = 80,
    n_terminals: float = 1,
    total_area_km2: float = 500.0,
) -> dict[str, float]:
    return {
        "n_subbasins": n_subbasins,
        "n_channels": n_channels,
        "n_terminals": n_terminals,
        "total_area_km2": total_area_km2,
        "mean_slope_m_m": 0.05,
        "stream_threshold_cells": 500.0,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestValidTopology:
    def test_healthy_basin_passes(self):
        check_topology_realism(_stats(), expected_area_km2=500.0)

    def test_no_expected_area_skips_area_check(self):
        # Even a tiny generated area passes when no expected area is provided.
        check_topology_realism(_stats(total_area_km2=0.1))

    def test_area_exactly_at_threshold_passes(self):
        # 10% of 1000 = 100 km2; generated 100 km2 → exactly at threshold.
        check_topology_realism(_stats(total_area_km2=100.0), expected_area_km2=1000.0)

    def test_multiple_terminals_below_max_passes(self):
        check_topology_realism(_stats(n_terminals=3), max_terminals=5)

    def test_channels_per_subbasin_below_max_passes(self):
        # 49 channels / 1 subbasin = 49 < 50 → passes.
        check_topology_realism(_stats(n_subbasins=1, n_channels=49))

    def test_custom_thresholds_accepted(self):
        # Caller loosens thresholds for a large complex basin.
        check_topology_realism(
            _stats(n_subbasins=2, n_channels=150, n_terminals=7, total_area_km2=50.0),
            expected_area_km2=100.0,
            min_area_ratio=0.4,
            max_channels_per_subbasin=200,
            max_terminals=10,
        )


# ---------------------------------------------------------------------------
# Area ratio failures
# ---------------------------------------------------------------------------

class TestAreaRatioGate:
    def test_03339000_signature_fails(self):
        """Reproduce the exact 03339000 failure: 0.22 km² vs 3341 km² expected."""
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=0.22),
                expected_area_km2=3340.879,
            )

    def test_error_contains_diagnostic_fields(self):
        with pytest.raises(SwatBuilderPipelineError) as exc_info:
            check_topology_realism(
                _stats(total_area_km2=5.0),
                expected_area_km2=1000.0,
                usgs_id="03339000",
            )
        ctx = exc_info.value.context
        assert ctx["generated_area_km2"] == pytest.approx(5.0)
        assert ctx["expected_area_km2"] == pytest.approx(1000.0)
        assert ctx["usgs_id"] == "03339000"
        assert "area_ratio" in ctx
        assert ctx["area_ratio"] == pytest.approx(0.005, rel=1e-3)

    def test_area_just_below_threshold_fails(self):
        # 9.9% of expected → below 10% threshold.
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=99.0),
                expected_area_km2=1000.0,
            )

    def test_zero_expected_area_skips_check(self):
        # Guard: if expected_area_km2=0 is passed, don't divide by zero.
        check_topology_realism(_stats(total_area_km2=0.1), expected_area_km2=0.0)

    def test_custom_min_area_ratio(self):
        # With min_area_ratio=0.5, 40% coverage fails.
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=400.0),
                expected_area_km2=1000.0,
                min_area_ratio=0.5,
            )


# ---------------------------------------------------------------------------
# Channel explosion failures
# ---------------------------------------------------------------------------

class TestChannelExplosionGate:
    def test_03339000_channel_explosion_fails(self):
        """5331 channels / 1 subbasin >>> 50 threshold."""
        with pytest.raises(SwatBuilderPipelineError, match="[Cc]hannel explosion"):
            check_topology_realism(_stats(n_subbasins=1, n_channels=5331))

    def test_error_contains_ratio(self):
        with pytest.raises(SwatBuilderPipelineError) as exc_info:
            check_topology_realism(_stats(n_subbasins=2, n_channels=200))
        ctx = exc_info.value.context
        assert ctx["channels_per_subbasin"] == pytest.approx(100.0)
        assert ctx["max_channels_per_subbasin"] == 50.0

    def test_exactly_at_limit_passes(self):
        # 50 channels / 1 subbasin = 50.0 → NOT above threshold, passes.
        check_topology_realism(_stats(n_subbasins=1, n_channels=50))

    def test_one_above_limit_fails(self):
        with pytest.raises(SwatBuilderPipelineError, match="[Cc]hannel explosion"):
            check_topology_realism(_stats(n_subbasins=1, n_channels=51))

    def test_custom_max_channels_per_subbasin(self):
        # Caller allows up to 200; 150 passes.
        check_topology_realism(
            _stats(n_subbasins=1, n_channels=150),
            max_channels_per_subbasin=200,
        )


# ---------------------------------------------------------------------------
# Terminal explosion failures
# ---------------------------------------------------------------------------

class TestTerminalExplosionGate:
    def test_19_terminals_fails(self):
        """Small basin (43 subbasins): effective threshold = max(5, 3) = 5 → 19 fails."""
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(_stats(n_terminals=19))

    def test_error_contains_terminal_count(self):
        with pytest.raises(SwatBuilderPipelineError) as exc_info:
            check_topology_realism(_stats(n_terminals=10))
        ctx = exc_info.value.context
        assert ctx["n_terminals"] == 10
        # effective_max_terminals = max(5, int(43 * 0.08)) = max(5, 3) = 5
        assert ctx["max_terminals"] == 5

    def test_exactly_at_limit_passes(self):
        check_topology_realism(_stats(n_terminals=5))

    def test_one_above_limit_fails(self):
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(_stats(n_terminals=6))

    def test_custom_max_terminals(self):
        check_topology_realism(_stats(n_terminals=8), max_terminals=10)

    def test_03339000_large_basin_258_terminals_passes(self):
        """03339000 after snap fix: 4023 subbasins, 258 terminals.

        Rate-based threshold: max(5, int(4023 * 0.08)) = 321 → 258 passes.
        These are boundary terminals from DEM truncation, not fragmentation.
        """
        check_topology_realism(
            _stats(n_subbasins=4023, n_channels=5333, n_terminals=258, total_area_km2=2513.8),
            expected_area_km2=3340.879,
        )

    def test_truly_fragmented_large_basin_fails(self):
        """Even a large basin fails when terminal rate exceeds 8%."""
        # 4023 subbasins × 8% = 321 effective threshold; 400 > 321 → fails.
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(
                _stats(n_subbasins=4023, n_channels=5333, n_terminals=400, total_area_km2=2513.8),
                expected_area_km2=3340.879,
            )

    def test_rate_based_threshold_scales_with_basin_size(self):
        """Effective threshold = max(abs, n_sub * rate)."""
        # 1000 subbasins × 8% = 80; terminal count of 70 passes.
        check_topology_realism(_stats(n_subbasins=1000, n_channels=1200, n_terminals=70))
        # Terminal count of 85 fails.
        with pytest.raises(SwatBuilderPipelineError, match="[Tt]erminal"):
            check_topology_realism(_stats(n_subbasins=1000, n_channels=1200, n_terminals=85))


# ---------------------------------------------------------------------------
# Priority: area check fires before channel check
# ---------------------------------------------------------------------------

class TestCheckPriority:
    def test_area_check_fires_first(self):
        """When both area ratio and channel explosion are bad, area error is raised."""
        with pytest.raises(SwatBuilderPipelineError, match="area mismatch"):
            check_topology_realism(
                _stats(total_area_km2=0.1, n_subbasins=1, n_channels=5000),
                expected_area_km2=3000.0,
            )
