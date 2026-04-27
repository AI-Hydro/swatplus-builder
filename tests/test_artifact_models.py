from __future__ import annotations

import pytest
from pydantic import ValidationError

from swatplus_builder.artifacts.models import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    RunConfig,
)


def test_run_config_validates_core_fields() -> None:
    cfg = RunConfig.model_validate(
        {
            "basin_id": "usgs_01594440",
            "bbox": [-77.0, 39.0, -76.5, 39.5],
            "simulation_start": "2010-01-01",
            "simulation_end": "2019-12-31",
            "parameters": {
                "CN2": {"value": 75.0, "scope": "hru"},
                "ALPHA_BF": {"value": 0.048, "scope": "subbasin"},
            },
            "options": {"routing_mode": "lte_stable", "weather_source": "gridmet"},
        }
    )
    assert cfg.basin_id == "usgs_01594440"
    assert cfg.parameters["CN2"].scope == "hru"


def test_run_config_rejects_invalid_parameter_scope() -> None:
    with pytest.raises(ValidationError):
        RunConfig.model_validate(
            {
                "basin_id": "x",
                "simulation_start": "2010-01-01",
                "simulation_end": "2010-12-31",
                "parameters": {"CN2": {"value": 75.0, "scope": "invalid"}},
            }
        )


def test_artifact_metadata_validates_fallback_bounds() -> None:
    md = ArtifactMetadata.model_validate(
        {
            "timestamp_utc": "2026-04-23T14:32:10Z",
            "soil_mode": "fallback",
            "pct_fallback_soils": 0.34,
            "outlet": {"gis_id": 12, "auto_detected": True, "reason": "configured outlet was dry"},
        }
    )
    assert md.soil_mode == "fallback"
    assert md.pct_fallback_soils == pytest.approx(0.34)


def test_artifact_metrics_and_provenance_models_roundtrip() -> None:
    metrics = ArtifactMetrics.model_validate(
        {
            "outlet_id": 12,
            "period": {"start": "2015-01-01", "end": "2019-12-31"},
            "nse": 0.62,
            "kge": 0.71,
        }
    )
    prov = ArtifactProvenance.model_validate(
        {
            "parent_run": "b4e2a1",
            "proposal_source": "dds_iteration_47",
            "agent_context": {"agent_id": "mcp-agent-v0.3", "experiment_id": "exp_1"},
        }
    )
    assert metrics.period is not None
    assert metrics.period.start.isoformat() == "2015-01-01"
    assert prov.agent_context is not None
    assert prov.agent_context.agent_id == "mcp-agent-v0.3"

