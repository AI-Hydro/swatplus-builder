"""Local run-artifact storage (Phase 3B.2).

Directory contract:

    <root>/runs/<content_hash>/
      config.json
      metadata.json
      metrics.json            (optional)
      provenance.json         (optional)
      timeseries.parquet      (optional)
      plots/*                 (optional)
      logs/*                  (optional)
"""

from __future__ import annotations

import json
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from .models import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    ArtifactQuery,
    ArtifactRecord,
    ArtifactSummary,
    RunConfig,
)


class ArtifactStore(ABC):
    """Abstract artifact store backend."""

    @abstractmethod
    def write(
        self,
        record: ArtifactRecord,
        *,
        timeseries_parquet: Path | None = None,
        plot_files: Iterable[Path] = (),
        log_files: Iterable[Path] = (),
    ) -> Path:
        """Persist one artifact record and optional payload files."""

    @abstractmethod
    def read(self, content_hash: str) -> ArtifactRecord:
        """Read one artifact record by hash."""

    @abstractmethod
    def exists(self, content_hash: str) -> bool:
        """Return true when artifact directory exists."""

    @abstractmethod
    def query(self, filters: ArtifactQuery | None = None) -> list[ArtifactSummary]:
        """List artifact summaries, optionally filtered."""

    @abstractmethod
    def lineage(self, content_hash: str) -> list[str]:
        """Return parent chain starting at `content_hash`."""


class LocalArtifactStore(ArtifactStore):
    """Filesystem artifact store rooted at `<root>/runs`."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        record: ArtifactRecord,
        *,
        timeseries_parquet: Path | None = None,
        plot_files: Iterable[Path] = (),
        log_files: Iterable[Path] = (),
    ) -> Path:
        run_dir = self._run_dir(record.content_hash)
        run_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(run_dir / "config.json", record.config.model_dump(mode="json"))
        self._write_json(run_dir / "metadata.json", record.metadata.model_dump(mode="json"))
        if record.metrics is not None:
            self._write_json(run_dir / "metrics.json", record.metrics.model_dump(mode="json"))
        if record.provenance is not None:
            self._write_json(run_dir / "provenance.json", record.provenance.model_dump(mode="json"))

        if timeseries_parquet is not None:
            dst = run_dir / "timeseries.parquet"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(timeseries_parquet, dst)

        self._copy_many(plot_files, run_dir / "plots")
        self._copy_many(log_files, run_dir / "logs")
        return run_dir

    def read(self, content_hash: str) -> ArtifactRecord:
        run_dir = self._run_dir(content_hash)
        config = RunConfig.model_validate(self._read_json(run_dir / "config.json"))
        metadata = ArtifactMetadata.model_validate(self._read_json(run_dir / "metadata.json"))

        metrics_path = run_dir / "metrics.json"
        prov_path = run_dir / "provenance.json"
        metrics = (
            ArtifactMetrics.model_validate(self._read_json(metrics_path))
            if metrics_path.exists()
            else None
        )
        provenance = (
            ArtifactProvenance.model_validate(self._read_json(prov_path))
            if prov_path.exists()
            else None
        )
        return ArtifactRecord(
            content_hash=content_hash,
            config=config,
            metadata=metadata,
            metrics=metrics,
            provenance=provenance,
        )

    def exists(self, content_hash: str) -> bool:
        return self._run_dir(content_hash).is_dir()

    def query(self, filters: ArtifactQuery | None = None) -> list[ArtifactSummary]:
        q = filters or ArtifactQuery()
        out: list[ArtifactSummary] = []
        for run_dir in sorted(self.runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            try:
                record = self.read(run_dir.name)
            except Exception:
                continue
            summary = ArtifactSummary(
                content_hash=record.content_hash,
                basin_id=record.config.basin_id,
                simulation_start=record.config.simulation_start,
                simulation_end=record.config.simulation_end,
                soil_mode=record.metadata.soil_mode,
                nse=record.metrics.nse if record.metrics is not None else None,
                parent_run=record.provenance.parent_run if record.provenance is not None else None,
            )
            if not self._match(summary, q):
                continue
            out.append(summary)
        return out

    def lineage(self, content_hash: str) -> list[str]:
        chain: list[str] = []
        seen: set[str] = set()
        current = content_hash
        while current and current not in seen and self.exists(current):
            seen.add(current)
            chain.append(current)
            record = self.read(current)
            parent = record.provenance.parent_run if record.provenance is not None else None
            if not parent:
                break
            current = parent
        return chain

    def _run_dir(self, content_hash: str) -> Path:
        return self.runs_dir / content_hash

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _copy_many(files: Iterable[Path], out_dir: Path) -> None:
        copied = False
        for src in files:
            if not src.exists():
                continue
            if not copied:
                out_dir.mkdir(parents=True, exist_ok=True)
                copied = True
            shutil.copy2(src, out_dir / src.name)

    @staticmethod
    def _match(summary: ArtifactSummary, q: ArtifactQuery) -> bool:
        if q.basin_id is not None and summary.basin_id != q.basin_id:
            return False
        if q.soil_mode is not None and summary.soil_mode != q.soil_mode:
            return False
        if q.nse_min is not None:
            if summary.nse is None or summary.nse < q.nse_min:
                return False
        return True

