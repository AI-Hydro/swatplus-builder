"""Soil-specific models and configurations."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

# Re-export core types for backward compatibility and internal soil module use.
from swatplus_builder.types import SoilProfile, SoilHorizon

class SoilConfig(BaseModel):
    """Configuration for rigorous SWAP+ soil generation."""
    use_sda: bool = Field(default=True, description="Enable Tier 2 high-fidelity horizon fetch via USDA SDA.")
    max_sda_mukeys: int = Field(default=500, description="Max mukeys to query from SDA in a single API batch.")
    enable_cache: bool = Field(default=True, description="Save/load SDA payloads to local disk cache.")
    reproducible: bool = Field(default=False, description="Enforce strict cache-only mode/disable dynamic fetching.")

    @classmethod
    def fast(cls) -> "SoilConfig":
        """PC-only (tier 1), fast generation without calling SDA."""
        return cls(use_sda=False)
        
    @classmethod
    def high_fidelity(cls) -> "SoilConfig":
        """Tier 2 (SDA), fetching from or loading into cache dynamically."""
        return cls(use_sda=True, reproducible=False)
        
    @classmethod
    def reproducible_mode(cls) -> "SoilConfig":
        """Tier 2 (SDA), but completely bypasses live networking — strict cache-only mode."""
        return cls(use_sda=True, reproducible=True)

class SoilProfilesResult(BaseModel):
    """Structured output for soil generation."""
    profiles: list[SoilProfile]
    soil_report: dict[str, Any]
    stats: dict[str, float]
