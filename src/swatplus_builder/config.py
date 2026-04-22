"""Typed configuration.

Loaded from env vars ``SWATGEN_*`` or passed per-call via ``settings=``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HruFilters(BaseModel):
    """Minimum-area filters applied when selecting HRUs per LSU.

    All percentages are of the parent LSU's area. An HRU is kept if the
    corresponding category's percentage is >= the threshold, and dropped
    otherwise (area then redistributed to the dominant class in that category).
    """

    land_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    soil_pct: float = Field(default=10.0, ge=0.0, le=100.0)
    slope_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    # If True, use the single dominant LU×Soil×Slope per LSU (MVP default).
    dominant_only: bool = True


class Settings(BaseModel):
    """Global configuration.

    Every field has a default; override per-call via the ``settings=`` kwarg
    on any tool function, or via environment variables ``SWATGEN_*``.
    """

    # Paths
    reference_db_dir: Path = Field(
        default=Path("~/.swatplus_builder/reference_dbs").expanduser(),
        description="Directory containing swatplus_datasets.sqlite, swatplus_soils.sqlite, swatplus_wgn.sqlite.",
    )
    swatplus_exe: Path | None = Field(
        default=None,
        description="Path to the SWAT+ engine binary. If None, we look on PATH.",
    )
    workdir_base: Path = Field(
        default=Path("./swatgen_runs"),
        description="Default base directory for per-call workdirs.",
    )

    # Backends
    delineation_backend: Literal["whitebox", "pyflwdir"] = "whitebox"
    whitebox_verbose: bool = False

    # HRUs
    hru_filter: HruFilters = Field(default_factory=HruFilters)

    # Editor
    editor_mode: Literal["subprocess", "in_process"] = "subprocess"

    # Logging
    log_format: Literal["text", "json"] = "text"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        # env_prefix is honored by pydantic-settings' BaseSettings; migrate when
        # we switch to pydantic-settings in Phase 1.
    )


DEFAULT_SETTINGS = Settings()
"""Module-level default instance. Read-only; copy before mutating."""
