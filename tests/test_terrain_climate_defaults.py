from __future__ import annotations

from pathlib import Path


def _write_d3_artifacts(run: Path) -> None:
    txt = run / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    (txt / "topography.hyd").write_text(
        "\n".join(
            [
                "topography.hyd",
                "name slp slp_len lat_len dist_cha depos",
                "topohru01 0.20 10.0 10.0 121.0 0.0",
                "topohru02 0.30 10.0 10.0 121.0 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (txt / "codes.bsn").write_text(
        "\n".join(
            [
                "codes.bsn",
                "pet lapse rte_cha",
                "1 0 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (txt / "parameters.bsn").write_text(
        "\n".join(
            [
                "parameters.bsn",
                "surq_lag plaps tlaps",
                "4.0 0.0 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_build_terrain_climate_defaults_block_discloses_defaults(tmp_path: Path) -> None:
    from swatplus_builder.output.terrain_climate_defaults import build_terrain_climate_defaults_block

    run = tmp_path / "run"
    _write_d3_artifacts(run)

    block = build_terrain_climate_defaults_block(run)

    assert block["status"] == "evaluated"
    assert block["topography_hyd"]["row_count"] == 2
    assert block["topography_hyd"]["slp_len_unique"] == [10.0]
    assert block["topography_hyd"]["lat_len_unique"] == [10.0]
    assert block["topography_hyd"]["dist_cha_unique"] == [121.0]
    assert block["topography_hyd"]["constant_slp_len"] is True
    assert block["topography_hyd"]["constant_lat_len"] is True
    assert block["topography_hyd"]["constant_dist_cha"] is True
    assert block["climate_lapse"]["lapse"] == 0.0
    assert block["climate_lapse"]["plaps"] == 0.0
    assert block["climate_lapse"]["tlaps"] == 0.0
    assert block["climate_lapse"]["lapse_enabled"] is False
    assert "constant_slp_len" in block["diagnostic_flags"]
    assert "lapse_disabled" in block["diagnostic_flags"]
