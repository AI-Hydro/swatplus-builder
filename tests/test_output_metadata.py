from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.output.metadata import RunMetadata, read_metadata, write_metadata


def test_write_and_read_metadata_roundtrip(tmp_path: Path) -> None:
    md = RunMetadata(
        timestamp_utc="2026-04-23T00:00:00+00:00",
        usgs_id="01547700",
        requested_outlet_gis_id=1,
        selected_outlet_gis_id=7,
        outlet_autodetected=True,
        outlet_selection_reason="requested_outlet_dry",
        outlet_policy="strict_pinned_from_auto",
        outlet_provenance_path="/tmp/run/outputs/outlet_provenance.json",
        outlet_provenance_sha256="f" * 64,
        sim_source_file="channel_sd_day.txt",
        sim_source_sha256="a" * 64,
        chandeg_con_sha256="b" * 64,
        routing_mode="standard",
        soil_mode="fallback",
        soil_provenance_mode="diagnostic_partial_gnatsgo_constant",
        boundary_provenance={"source": "nldi_authoritative"},
        pct_fallback_soils=0.25,
        engine_version="/tmp/swatplus_exe",
        builder_git_sha="abc123",
        input_hashes={"dem_tif": "deadbeef"},
        weather_source="gridmet",
        weather_coverage_flags={"nonzero_days": 100},
        notes=["test"],
    )
    out = tmp_path / "metadata.json"
    write_metadata(out, md)
    loaded = read_metadata(out)
    assert loaded.usgs_id == "01547700"
    assert loaded.outlet_autodetected is True
    assert loaded.outlet_policy == "strict_pinned_from_auto"
    assert loaded.soil_provenance_mode == "diagnostic_partial_gnatsgo_constant"
    assert loaded.boundary_provenance == {"source": "nldi_authoritative"}
    assert loaded.pct_fallback_soils == 0.25
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["selected_outlet_gis_id"] == 7
    assert data["outlet_provenance_sha256"] == "f" * 64
    assert data["soil_provenance_mode"] == "diagnostic_partial_gnatsgo_constant"
