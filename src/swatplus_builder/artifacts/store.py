"""Local run-artifact storage (Phase 3B.2).

Directory contract:

    <root>/runs/<content_hash>/
      manifest.json           (required; complete record and payload digests)
      config.json
      metadata.json
      metrics.json            (optional)
      provenance.json         (optional)
      timeseries.parquet      (optional)
      plots/*                 (optional)
      logs/*                  (optional)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

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
    """Immutable, checksummed artifact records rooted at `<root>/runs`.

    Legacy directories without manifests are never trusted as cache entries.
    Preserve those directories and use a new root/identity for new executions.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        if self.runs_dir.is_symlink():
            raise ValueError("Artifact runs directory must not be a symlink")

    def write(
        self,
        record: ArtifactRecord,
        *,
        timeseries_parquet: Path | None = None,
        plot_files: Iterable[Path] = (),
        log_files: Iterable[Path] = (),
    ) -> Path:
        run_dir = self._run_dir(record.content_hash)
        # Published records are immutable: a hash cannot silently change meaning.
        if run_dir.exists():
            raise FileExistsError(f"Artifact already exists; use a new identity/root: {run_dir}")
        with tempfile.TemporaryDirectory(prefix=".staging-", dir=self.runs_dir) as temp:
            stage = Path(temp) / "record"
            stage.mkdir()
            self._write_json(stage / "config.json", record.config.model_dump(mode="json"))
            self._write_json(stage / "metadata.json", record.metadata.model_dump(mode="json"))
            if record.metrics is not None:
                self._write_json(stage / "metrics.json", record.metrics.model_dump(mode="json"))
            if record.provenance is not None:
                self._write_json(stage / "provenance.json", record.provenance.model_dump(mode="json"))
            if timeseries_parquet is not None:
                shutil.copy2(timeseries_parquet, stage / "timeseries.parquet")
            self._copy_many(plot_files, stage / "plots")
            self._copy_many(log_files, stage / "logs")
            hashes = {
                p.relative_to(stage).as_posix(): self._digest(p)
                for p in stage.rglob("*") if p.is_file()
            }
            self._write_json(stage / "manifest.json", {
                "schema_version": 1, "content_hash": record.content_hash, "files": hashes,
            })
            # An exclusive mkdir serializes publishers, including on Windows.
            guard = self.runs_dir / f".{record.content_hash}.lock"
            guard.mkdir()
            try:
                if run_dir.exists() or run_dir.is_symlink():
                    raise FileExistsError(f"Artifact already exists: {run_dir}")
                stage.rename(run_dir)
            finally:
                guard.rmdir()
        return run_dir

    def read(self, content_hash: str) -> ArtifactRecord:
        run_dir = self._run_dir(content_hash)
        manifest = self._read_json(run_dir / "manifest.json")
        hashes = manifest.get("files")
        if (manifest.get("schema_version") != 1
                or manifest.get("content_hash") != content_hash
                or not isinstance(hashes, dict)
                or not {"config.json", "metadata.json"}.issubset(hashes)):
            raise ValueError(f"Invalid artifact manifest: {run_dir}")
        payloads = {}
        # Read and verify the same bytes that are parsed; never accept unchecked
        # optional files from an earlier or incomplete generation.
        for name, expected in hashes.items():
            path = run_dir / name
            if path.is_symlink() or not path.resolve().is_relative_to(run_dir.resolve()):
                raise ValueError("Artifact payload escapes record directory")
            if name in {"config.json", "metadata.json", "metrics.json", "provenance.json"}:
                blob = path.read_bytes()
                digest = hashlib.sha256(blob).hexdigest()
                payloads[name] = json.loads(blob)
            else:
                digest = self._digest(path)
            if digest != expected:
                raise ValueError(f"Artifact integrity check failed: {name}")
        return ArtifactRecord(
            content_hash=content_hash,
            config=RunConfig.model_validate(payloads["config.json"]),
            metadata=ArtifactMetadata.model_validate(payloads["metadata.json"]),
            metrics=(ArtifactMetrics.model_validate(payloads["metrics.json"])
                     if "metrics.json" in payloads else None),
            provenance=(ArtifactProvenance.model_validate(payloads["provenance.json"])
                        if "provenance.json" in payloads else None),
        )

    def exists(self, content_hash: str) -> bool:
        self._run_dir(content_hash)  # Invalid identifiers must not become misses.
        try:
            self.read(content_hash)
        except (OSError, ValueError, TypeError):
            return False
        return True

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
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise ValueError("Artifact ID must be a lowercase SHA-256 digest")
        path = self.runs_dir / content_hash
        if path.is_symlink() or not path.resolve().is_relative_to(self.runs_dir.resolve()):
            raise ValueError("Artifact directory escapes storage root")
        return path

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

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

