"""pySWATPlus sensitivity bridge (revised Phase 3C.4)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .errors import SwatBuilderExternalError, SwatBuilderInputError
from .params import get_parameter
from .calibration.pyswatplus_runtime import ensure_pyswatplus_runtime


class SensitivityIndex(BaseModel):
    parameter: str
    s1: float
    st: float


class SensitivityRequest(BaseModel):
    basin_id: str
    txtinout_dir: Path
    parameters: list[str]
    n_samples: int = Field(512, ge=8)
    observed_csv: Path | None = None
    artifacts_root: Path


class SensitivityResult(BaseModel):
    sensitivity_hash: str
    cache_hit: bool
    outdir: Path
    indices_csv: Path
    summary_md: Path
    ranked: list[SensitivityIndex]


class SensitivityBackend(Protocol):
    def run(self, request: SensitivityRequest) -> list[SensitivityIndex]:
        """Run backend sensitivity and return Sobol indices."""


class PySwatPlusSensitivityBackend:
    """Best-effort adapter around pySWATPlus `SensitivityAnalyzer`."""

    def run(self, request: SensitivityRequest) -> list[SensitivityIndex]:
        ensure_pyswatplus_runtime()
        try:
            import importlib

            try:
                mod = importlib.import_module("pySWATPlus")
            except Exception:
                mod = importlib.import_module("pySWATPlus.sensitivity")
            cls = getattr(mod, "SensitivityAnalyzer", None)
            if cls is None:
                raise SwatBuilderExternalError("pySWATPlus SensitivityAnalyzer class not found")
            analyzer = cls()
        except Exception as exc:
            raise SwatBuilderExternalError(
                "Failed to initialize pySWATPlus sensitivity backend",
                error=str(exc),
            ) from exc

        if hasattr(analyzer, "set_txtinout_dir"):
            analyzer.set_txtinout_dir(str(request.txtinout_dir))
        elif hasattr(analyzer, "txtinout_dir"):
            setattr(analyzer, "txtinout_dir", str(request.txtinout_dir))
        else:
            raise SwatBuilderExternalError(
                "pySWATPlus sensitivity adapter missing txtinout configuration surface"
            )
        kwargs = {
            "parameters": [p.lower() for p in request.parameters],
            "n_samples": request.n_samples,
        }
        if request.observed_csv is not None:
            kwargs["observed_data"] = str(request.observed_csv)
        run_fn = getattr(analyzer, "run", None) or getattr(analyzer, "analyze", None)
        if run_fn is None:
            raise SwatBuilderExternalError(
                "pySWATPlus sensitivity adapter missing run/analyze method"
            )
        raw = run_fn(**kwargs)
        if not isinstance(raw, dict):
            raise SwatBuilderExternalError(
                "pySWATPlus sensitivity returned unsupported format",
                result_type=type(raw).__name__,
            )
        out: list[SensitivityIndex] = []
        for p in request.parameters:
            item = raw.get(p.lower()) or raw.get(p) or {}
            out.append(
                SensitivityIndex(
                    parameter=p,
                    s1=float(item.get("S1", 0.0)),
                    st=float(item.get("ST", 0.0)),
                )
            )
        return out


@dataclass
class SensitivityAnalyzer:
    """High-level sensitivity orchestrator with artifact persistence."""

    backend: SensitivityBackend | None = None

    def run(self, request: SensitivityRequest) -> SensitivityResult:
        txt = request.txtinout_dir.expanduser().resolve()
        if not txt.exists():
            raise SwatBuilderInputError("txtinout_dir does not exist", path=str(txt))
        if not request.parameters:
            raise SwatBuilderInputError("At least one parameter is required.")
        for p in request.parameters:
            get_parameter(p)

        h = _sensitivity_hash(request)
        outdir = request.artifacts_root.expanduser().resolve() / "runs" / "sensitivity" / h
        indices_csv = outdir / "indices.csv"
        summary_md = outdir / "summary.md"
        if indices_csv.exists() and summary_md.exists():
            ranked = _read_indices(indices_csv)
            return SensitivityResult(
                sensitivity_hash=h,
                cache_hit=True,
                outdir=outdir,
                indices_csv=indices_csv,
                summary_md=summary_md,
                ranked=ranked,
            )

        backend = self.backend or PySwatPlusSensitivityBackend()
        rows = backend.run(request)
        rows = sorted(rows, key=lambda r: r.st, reverse=True)

        outdir.mkdir(parents=True, exist_ok=True)
        with indices_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["parameter", "s1", "st"])
            writer.writeheader()
            for r in rows:
                writer.writerow({"parameter": r.parameter, "s1": r.s1, "st": r.st})
        summary_md.write_text(
            "\n".join(
                [
                    "# Sensitivity Summary",
                    "",
                    f"- Basin: `{request.basin_id}`",
                    f"- Samples: `{request.n_samples}`",
                    f"- Parameters: `{', '.join(request.parameters)}`",
                    "",
                    "## Ranked by Total-order Sobol (ST)",
                    "",
                ]
                + [f"- `{r.parameter}`: ST={r.st:.4f}, S1={r.s1:.4f}" for r in rows]
            )
            + "\n",
            encoding="utf-8",
        )
        (outdir / "config.json").write_text(
            json.dumps(
                {
                    "basin_id": request.basin_id,
                    "txtinout_dir": str(txt),
                    "parameters": request.parameters,
                    "n_samples": request.n_samples,
                    "observed_csv": None
                    if request.observed_csv is None
                    else str(request.observed_csv.expanduser().resolve()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return SensitivityResult(
            sensitivity_hash=h,
            cache_hit=False,
            outdir=outdir,
            indices_csv=indices_csv,
            summary_md=summary_md,
            ranked=rows,
        )


def _sensitivity_hash(request: SensitivityRequest) -> str:
    payload = {
        "basin_id": request.basin_id,
        "txtinout_dir": str(request.txtinout_dir.expanduser().resolve()),
        "parameters": sorted(request.parameters),
        "n_samples": int(request.n_samples),
        "observed_csv": None
        if request.observed_csv is None
        else str(request.observed_csv.expanduser().resolve()),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _read_indices(path: Path) -> list[SensitivityIndex]:
    out: list[SensitivityIndex] = []
    with path.open("r", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for row in rd:
            out.append(
                SensitivityIndex(
                    parameter=str(row["parameter"]),
                    s1=float(row["s1"]),
                    st=float(row["st"]),
                )
            )
    return out
