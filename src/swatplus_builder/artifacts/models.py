"""Pydantic schemas for Phase 3B run artifacts.

These models correspond to the JSON files defined in `ROADMAP.md` Appendix A:
`config.json`, `metadata.json`, `metrics.json`, and `provenance.json`.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, TypeAlias

from pydantic import BaseModel, Field

JsonScalar: TypeAlias = str | int | float | bool | None


class ParameterValue(BaseModel):
    """One calibration parameter assignment within `config.parameters`."""

    value: float = Field(..., description="Numeric parameter value.")
    scope: Literal["global", "hru", "subbasin", "channel"] = Field(
        ..., description="Application scope for this parameter value."
    )


class RunConfig(BaseModel):
    """Artifact `config.json` model used for content hashing."""

    basin_id: str = Field(..., min_length=1)
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="Bounding box [minx, miny, maxx, maxy] in lon/lat.",
    )
    simulation_start: date = Field(...)
    simulation_end: date = Field(...)
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    options: dict[str, JsonScalar] = Field(default_factory=dict)


class OutletMetadata(BaseModel):
    """Outlet selection metadata in `metadata.json`."""

    gis_id: int | None = Field(default=None)
    auto_detected: bool = Field(default=False)
    reason: str | None = Field(default=None)


class ArtifactMetadata(BaseModel):
    """Artifact `metadata.json` model (provenance, non-hash inputs)."""

    run_id: str | None = Field(default=None, description="Content hash / run identifier.")
    timestamp_utc: str = Field(..., description="UTC ISO-8601 timestamp.")
    engine_version: str | None = Field(default=None)
    builder_version: str | None = Field(default=None)
    git_sha: str | None = Field(default=None)
    outlet: OutletMetadata | None = Field(default=None)
    soil_mode: Literal["high_fidelity", "fallback", "synthetic"] | None = Field(default=None)
    pct_fallback_soils: float | None = Field(default=None, ge=0.0, le=1.0)
    weather_coverage: dict[str, float] = Field(default_factory=dict)
    n_subbasins: int | None = Field(default=None, ge=0)
    n_hrus: int | None = Field(default=None, ge=0)
    runtime_seconds: float | None = Field(default=None, ge=0.0)


class MetricsPeriod(BaseModel):
    """Evaluation period included in `metrics.json`."""

    start: date = Field(...)
    end: date = Field(...)


class ArtifactMetrics(BaseModel):
    """Artifact `metrics.json` model."""

    outlet_id: int | None = Field(default=None)
    period: MetricsPeriod | None = Field(default=None)
    nse: float | None = Field(default=None)
    log_nse: float | None = Field(default=None)
    kge: float | None = Field(default=None)
    pbias: float | None = Field(default=None)
    bfi_observed: float | None = Field(default=None)
    bfi_simulated: float | None = Field(default=None)
    peak_flow_error_pct: float | None = Field(default=None)


class AgentContext(BaseModel):
    """Agent context fields in `provenance.json`."""

    agent_id: str | None = Field(default=None)
    experiment_id: str | None = Field(default=None)


class ArtifactProvenance(BaseModel):
    """Artifact `provenance.json` model."""

    parent_run: str | None = Field(default=None)
    proposal_source: str | None = Field(default=None)
    agent_context: AgentContext | None = Field(default=None)

