from __future__ import annotations
"""Run metadata schema and persistence helpers."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RunMetadata(BaseModel):
    """Persistent metadata for one model run output directory."""

    timestamp_utc: str = Field(..., description="UTC timestamp when metadata was written.")
    usgs_id: str | None = Field(default=None)
    requested_outlet_gis_id: int | None = Field(default=None)
    selected_outlet_gis_id: int | None = Field(default=None)
    outlet_autodetected: bool = Field(default=False)
    outlet_selection_reason: str | None = Field(default=None)
    outlet_policy: str | None = Field(default=None)
    outlet_provenance_path: str | None = Field(default=None)
    outlet_provenance_sha256: str | None = Field(default=None)
    sim_source_file: str | None = Field(default=None)
    sim_source_sha256: str | None = Field(default=None)
    chandeg_con_sha256: str | None = Field(default=None)
    routing_mode: str | None = Field(default=None)
    soil_mode: str | None = Field(default=None)
    pct_fallback_soils: float | None = Field(default=None, ge=0.0, le=1.0)
    engine_version: str | None = Field(default=None)
    builder_git_sha: str | None = Field(default=None)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    weather_source: str | None = Field(default=None)
    weather_coverage_flags: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path | str) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(1024 * 64)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def try_git_sha(cwd: Path | str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(cwd)),
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        return None
    return None


def write_metadata(path: Path | str, metadata: RunMetadata) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(metadata.model_dump(), indent=2) + "\n", encoding="utf-8")
    return p


def read_metadata(path: Path | str) -> RunMetadata:
    p = Path(path)
    return RunMetadata.model_validate_json(p.read_text(encoding="utf-8"))
