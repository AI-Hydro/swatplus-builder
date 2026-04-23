from __future__ import annotations

from pathlib import Path

from swatplus_builder.validation.runner import load_basin_specs


def test_curated_v1_schema_and_minimum_count() -> None:
    root = Path(__file__).resolve().parents[1]
    curated = root / "basins" / "curated_v1.json"
    specs = load_basin_specs(curated)

    assert len(specs) >= 6
    for spec in specs:
        assert spec.usgs_id
        assert spec.bbox is not None
        assert spec.expected_nse_min is not None
        assert spec.notes is not None and spec.notes.strip() != ""

