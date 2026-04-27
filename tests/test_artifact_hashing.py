from __future__ import annotations

from swatplus_builder.artifacts.hashing import canonical_config_json, compute_content_hash


def _config_a() -> dict[str, object]:
    return {
        "basin_id": "usgs_01594440",
        "bbox": [-77.0, 39.0, -76.5, 39.5],
        "simulation_start": "2010-01-01",
        "simulation_end": "2019-12-31",
        "parameters": {
            "CN2": {"value": 75.0, "scope": "hru"},
            "ALPHA_BF": {"value": 0.048, "scope": "subbasin"},
        },
        "options": {
            "routing_mode": "lte_stable",
            "weather_source": "gridmet",
            "soil_source": "stac",
        },
    }


def _config_a_reordered() -> dict[str, object]:
    # Intentionally reordered keys; canonical hash should match _config_a.
    return {
        "options": {
            "soil_source": "stac",
            "weather_source": "gridmet",
            "routing_mode": "lte_stable",
        },
        "simulation_end": "2019-12-31",
        "parameters": {
            "ALPHA_BF": {"scope": "subbasin", "value": 0.048},
            "CN2": {"scope": "hru", "value": 75.0},
        },
        "bbox": [-77.0, 39.0, -76.5, 39.5],
        "simulation_start": "2010-01-01",
        "basin_id": "usgs_01594440",
    }


def test_canonical_config_json_is_deterministic_across_key_order() -> None:
    a = canonical_config_json(_config_a())
    b = canonical_config_json(_config_a_reordered())
    assert a == b


def test_content_hash_changes_when_engine_version_changes() -> None:
    cfg = _config_a()
    h1 = compute_content_hash(cfg, engine_version="swatplus-61.0.6", builder_git_sha="abc123")
    h2 = compute_content_hash(cfg, engine_version="swatplus-61.0.7", builder_git_sha="abc123")
    assert h1 != h2


def test_content_hash_changes_when_config_changes() -> None:
    cfg = _config_a()
    h1 = compute_content_hash(cfg, engine_version="swatplus-61.0.6", builder_git_sha="abc123")
    cfg2 = _config_a()
    cfg2["options"] = {**cfg2["options"], "routing_mode": "muskingum"}  # type: ignore[arg-type]
    h2 = compute_content_hash(cfg2, engine_version="swatplus-61.0.6", builder_git_sha="abc123")
    assert h1 != h2


def test_content_hash_changes_when_git_sha_changes() -> None:
    cfg = _config_a()
    h1 = compute_content_hash(cfg, engine_version="swatplus-61.0.6", builder_git_sha="abc123")
    h2 = compute_content_hash(cfg, engine_version="swatplus-61.0.6", builder_git_sha="def456")
    assert h1 != h2

