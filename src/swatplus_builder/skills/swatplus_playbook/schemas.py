"""Typed schemas for the SWAT+ modeling playbook skill."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

PlaybookStatus = Literal["validated", "tentative", "rejected", "open", "superseded"]


class PlaybookContext(BaseModel):
    """Context used to recommend the next modeling action.

    The context intentionally mirrors known blockers in this repository:
    routing integrity, outlet selection, and calibration bridge readiness.
    """

    basin_id: str = Field(..., min_length=1)
    routing_mode: int | None = None
    outlet_gis_id: int | None = None
    metric_source: str = Field(default="evaluate_run")
    proposal_source: str = Field(default="random")
    calibration_history_unique_nse: int = Field(default=0, ge=0)
    calibration_history_rows: int = Field(default=0, ge=0)
    metrics: dict[str, float] = Field(default_factory=dict)
    sensitivity: dict[str, float] = Field(default_factory=dict)
    error_logs: list[str] = Field(default_factory=list)


class PlaybookRecommendation(BaseModel):
    """Machine-consumable next-action recommendation."""

    action: str
    rationale: str
    status: PlaybookStatus
    authoritative_metric_source: str = "evaluate_run"
    rejected_paths: list[str] = Field(default_factory=list)
    preferred_paths: list[str] = Field(default_factory=list)
    fallback_proposal_source: str | None = None


class PlaybookEvidenceEntry(BaseModel):
    """One dated evidence record appended to the human playbook."""

    title: str = Field(..., min_length=3)
    status: PlaybookStatus
    category: str = Field(..., min_length=2)
    source: str = Field(..., min_length=2)
    evidence: str = Field(..., min_length=3)
    consequence: str = Field(..., min_length=3)
    entry_date: date = Field(default_factory=date.today)
    supersedes: str | None = None
