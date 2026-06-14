"""Tests for max-accumulation outlet snapping and adaptive snap radius.

No WhiteboxTools or real DEM required — all tests use small synthetic
rasters written with rasterio.

Root cause that motivated these tests (usgs_03339000):
  - flow_acc at raw outlet cell: 321 cells (~0.22 km²)  ← tiny tributary
  - flow_acc at main stem:  3,642,542 cells (~2520 km²)
  - distance to main stem: 782 m  — just beyond the 500 m default snap radius
  - WBT snap_pour_points found the nearest stream (321-cell tributary),
    not the main stem (3.6M-cell channel).
  - Fix: _snap_to_max_accumulation() finds highest-acc cell in radius.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from swatplus_builder.gis.delineation import _adaptive_snap_dist, _snap_to_max_accumulation

# ---------------------------------------------------------------------------
# Helpers: build synthetic flow-accumulation rasters
# ---------------------------------------------------------------------------

_RES = 30.0   # metres per pixel (approximate 30-m DEM)
_EPSG = "EPSG:5070"


def _write_flow_acc(path: Path, data: np.ndarray, res: float = _RES) -> tuple[float, float, float, float]:
    """Write a float32 flow-accumulation GeoTIFF. Returns (left, bottom, right, top) bounds."""
    rows, cols = data.shape
    left, top = 0.0, rows * res
    right, bottom = cols * res, 0.0
    transform = from_bounds(left, bottom, right, top, cols, rows)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=rows, width=cols,
        count=1, dtype="float32",
        crs=_EPSG, transform=transform, nodata=-1.0,
    ) as dst:
        dst.write(data.astype("float32"), 1)
    return left, bottom, right, top


# ---------------------------------------------------------------------------
# _adaptive_snap_dist
# ---------------------------------------------------------------------------

class TestAdaptiveSnapDist:
    def test_no_expected_area_returns_default(self):
        assert _adaptive_snap_dist(500.0, None) == 500.0

    def test_small_basin_floored_to_default(self):
        # sqrt(100) * 30 = 300 < 500 → clamped to 500
        assert _adaptive_snap_dist(500.0, 100.0) == 500.0

    def test_large_basin_scaled_up(self):
        # sqrt(3340) * 30 ≈ 1733 > 500
        result = _adaptive_snap_dist(500.0, 3340.0)
        assert result == pytest.approx(math.sqrt(3340.0) * 30.0, rel=1e-5)
        assert result > 500.0

    def test_03339000_signature(self):
        """Adaptive radius for 03339000 must exceed 782 m (actual main-stem distance)."""
        radius = _adaptive_snap_dist(500.0, 3340.879)
        assert radius > 782.0

    def test_zero_expected_area_returns_default(self):
        assert _adaptive_snap_dist(500.0, 0.0) == 500.0

    def test_custom_default_respected(self):
        # If custom default > scaled value, keep default
        assert _adaptive_snap_dist(2000.0, 100.0) == 2000.0


# ---------------------------------------------------------------------------
# _snap_to_max_accumulation — synthetic raster tests
# ---------------------------------------------------------------------------

class TestSnapToMaxAccumulation:
    def test_finds_high_acc_cell_over_nearest_low_acc(self, tmp_path):
        """Core correctness test mirroring the 03339000 failure.

        Grid layout (5×5, 30 m cells):
          Outlet raw is at pixel (2,2) — flow_acc = 50 (tiny tributary).
          High-acc cell at (2,4) — flow_acc = 5000 (main stem), 60 m away.
          Nearest stream at (2,3) — flow_acc = 100, 30 m away.

        WBT nearest-stream snap would pick (2,3) [nearest].
        Max-acc snap should pick (2,4) [highest acc within radius].
        """
        data = np.zeros((5, 5), dtype=np.float32)
        data[2, 2] = 50      # raw outlet — low acc
        data[2, 3] = 100     # nearest stream — medium acc
        data[2, 4] = 5000    # main stem — highest acc, 60 m away

        tif = tmp_path / "facc.tif"
        _write_flow_acc(tif, data)

        # Outlet centre at pixel (2,2): x = 2.5*30 = 75, y = (5-2-0.5)*30 = 75
        px, py = 75.0, 75.0
        snapped_px, snapped_py, acc_raw, acc_snapped, dist_m = (
            _snap_to_max_accumulation(tif, px, py, radius_m=150.0)
        )

        assert acc_snapped == pytest.approx(5000.0)
        assert acc_raw == pytest.approx(50.0)
        # Snapped cell is (2,4): centre x = 4.5*30 = 135, y = 75
        assert snapped_px == pytest.approx(135.0, abs=1.0)
        assert snapped_py == pytest.approx(75.0,  abs=1.0)
        assert dist_m == pytest.approx(60.0, abs=2.0)

    def test_03339000_numbers(self, tmp_path):
        """Reproduce 03339000 scale: 321-cell outlet, 3.6M-cell main stem at 782 m."""
        res = 26.3  # actual DEM resolution used for 03339000
        cols, rows = 100, 100
        data = np.zeros((rows, cols), dtype=np.float32)

        # Outlet at centre (50, 50)
        r_out, c_out = 50, 50
        data[r_out, c_out] = 321.0

        # Main stem at 30 cells away (≈782 m)
        r_stem, c_stem = 50, 80
        data[r_stem, c_stem] = 3_642_542.0

        path = tmp_path / "facc_03339000.tif"
        _write_flow_acc(path, data, res=res)

        centre_x = (c_out + 0.5) * res
        centre_y = (rows - r_out - 0.5) * res

        # Default 500 m snap: main stem is ~788 m away → not found
        _, _, _, acc_500, _ = _snap_to_max_accumulation(path, centre_x, centre_y, radius_m=500.0)
        assert acc_500 < 3_000_000, "500m snap should NOT reach the main stem"

        # Adaptive snap ~1733 m: main stem IS found
        _, _, _, acc_adaptive, dist_adaptive = _snap_to_max_accumulation(
            path, centre_x, centre_y, radius_m=1733.0
        )
        assert acc_adaptive == pytest.approx(3_642_542.0)
        assert dist_adaptive == pytest.approx(30 * res, abs=res)   # 30 cells × 26.3 m

    def test_fallback_when_no_valid_cells(self, tmp_path):
        """When the search window is all nodata, returns raw outlet unchanged."""
        data = np.full((5, 5), -1.0)   # all nodata
        data[2, 2] = 100.0             # only the raw outlet cell has data
        tif = tmp_path / "facc_nodata.tif"
        _write_flow_acc(tif, data)

        px, py = 75.0, 75.0
        snapped_px, snapped_py, acc_raw, acc_snapped, dist_m = (
            _snap_to_max_accumulation(tif, px, py, radius_m=30.0)
        )
        # radius_m=30 → only 1 cell radius; in a 5×5 grid that's just the centre
        assert snapped_px == pytest.approx(px, abs=1.0)
        assert dist_m == pytest.approx(0.0, abs=1.0)

    def test_highest_acc_is_selected_not_nearest(self, tmp_path):
        """When two streams are in radius, the higher-acc one wins."""
        data = np.zeros((10, 10), dtype=np.float32)
        data[5, 5] = 10     # raw outlet
        data[5, 6] = 200    # near stream (30 m)
        data[5, 8] = 9000   # far main stem (90 m)
        tif = tmp_path / "two_streams.tif"
        _write_flow_acc(tif, data)

        px, py = 5.5 * _RES, (10 - 5 - 0.5) * _RES
        _, _, _, acc_snapped, _ = _snap_to_max_accumulation(tif, px, py, radius_m=150.0)
        assert acc_snapped == pytest.approx(9000.0)

    def test_radius_constrains_search(self, tmp_path):
        """High-acc cell outside radius must not be selected."""
        data = np.zeros((10, 10), dtype=np.float32)
        data[5, 5] = 10     # raw outlet
        data[5, 9] = 99999  # very high acc but 120 m away
        tif = tmp_path / "constrained.tif"
        _write_flow_acc(tif, data)

        px, py = 5.5 * _RES, (10 - 5 - 0.5) * _RES
        _, _, _, acc_snapped, _ = _snap_to_max_accumulation(tif, px, py, radius_m=90.0)
        # 99999-cell is 120 m away; radius is 90 m → should not be selected
        assert acc_snapped < 99999.0

    def test_snap_diagnostic_fields_returned(self, tmp_path):
        """All five return values are populated and physically sensible."""
        data = np.zeros((5, 5), dtype=np.float32)
        data[2, 2] = 50
        data[2, 4] = 5000
        tif = tmp_path / "diag.tif"
        _write_flow_acc(tif, data)

        px, py = 75.0, 75.0
        snapped_px, snapped_py, acc_raw, acc_snapped, dist_m = (
            _snap_to_max_accumulation(tif, px, py, radius_m=200.0)
        )
        assert isinstance(snapped_px, float)
        assert isinstance(dist_m, float)
        assert acc_raw >= 0
        assert acc_snapped >= acc_raw
        assert dist_m >= 0.0
