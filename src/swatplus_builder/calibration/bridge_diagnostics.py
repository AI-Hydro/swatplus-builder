"""pySWATPlus bridge failure classification and diagnostics summary builder.

Every bridge failure produces a ``bridge_failure_diagnostic.json`` artifact via
:func:`~swatplus_builder.calibration.calibrator._write_bridge_failure_artifact`.
This module adds two things:

1. **Classification** — :func:`classify_bridge_failure` maps the raw exception
   and context into a deterministic :class:`FailureClass` with a detail string.
   The class is embedded in the artifact so agents never see an opaque error.

2. **Summary builder** — :func:`build_bridge_diagnostics_summary` scans a
   directory tree for all ``bridge_failure_diagnostic.json`` files and writes:
   - ``bridge_diagnostics.json``  — machine-readable aggregate
   - ``bridge_diagnostics_summary.md`` — human-readable markdown table
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------

class FailureClass(str, Enum):
    """Deterministic failure classes for the pySWATPlus bridge.

    Every failure must map to exactly one class. Resolution order:
    IMPORT_ERROR > BINARY_NOT_FOUND > STAGING_MISMATCH > EMPTY_HISTORY
    > OUTPUT_MISSING > RUNTIME_CRASH > UNKNOWN
    """

    IMPORT_ERROR    = "IMPORT_ERROR"       # pySWATPlus not installed / import failed
    BINARY_NOT_FOUND = "BINARY_NOT_FOUND"  # SWAT+ exe path absent or not executable
    STAGING_MISMATCH = "STAGING_MISMATCH"  # staged TxtInOut is empty or missing key files
    EMPTY_HISTORY   = "EMPTY_HISTORY"      # pySWATPlus ran but produced no evaluations
    OUTPUT_MISSING  = "OUTPUT_MISSING"     # optimization_history.json not produced
    RUNTIME_CRASH   = "RUNTIME_CRASH"      # exception during parameter_optimization()
    UNKNOWN         = "UNKNOWN"            # none of the above patterns matched


# Keywords used for classification (checked case-insensitively)
_IMPORT_KEYS     = ("no module named", "modulenotfounderror", "importerror",
                    "calibration class not found", "failed to initialize pyswatplus")
_BINARY_KEYS     = ("no such file or directory", "permission denied", "not found",
                    "binary", "swatplus_exe", "oserror", "filenotfounderror")
_STAGING_KEYS    = ("staged", "staging", "txtinout", "empty run", "no files")
_EMPTY_HIST_KEYS = ("empty evaluation history", "no evaluations", "empty history")
_OUTPUT_KEYS     = ("optimization_history.json", "did not produce", "output missing")


def classify_bridge_failure(
    error_type: str,
    error_message: str,
    staged_file_count: int,
    failure_stage: str,
    traceback_text: str = "",
) -> tuple[FailureClass, str]:
    """Classify a bridge failure into a :class:`FailureClass`.

    Args:
        error_type:        ``type(exc).__name__``
        error_message:     ``str(exc)``
        staged_file_count: number of files in the staged TxtInOut manifest
        failure_stage:     stage label when failure was caught
        traceback_text:    full traceback string (optional; aids classification)

    Returns:
        ``(FailureClass, detail_string)`` — detail is a one-line explanation.
    """
    msg_lower = (error_message + " " + traceback_text).lower()
    et_lower  = error_type.lower()

    if any(k in msg_lower or k in et_lower for k in _IMPORT_KEYS):
        return FailureClass.IMPORT_ERROR, (
            f"pySWATPlus import failed: {error_message[:200]}"
        )

    if any(k in msg_lower or k in et_lower for k in _BINARY_KEYS):
        return FailureClass.BINARY_NOT_FOUND, (
            f"SWAT+ binary not accessible: {error_message[:200]}"
        )

    if any(k in msg_lower for k in _EMPTY_HIST_KEYS):
        return FailureClass.EMPTY_HISTORY, (
            "pySWATPlus produced no evaluation records — bridge ran but history is empty"
        )

    if any(k in msg_lower for k in _OUTPUT_KEYS):
        return FailureClass.OUTPUT_MISSING, (
            f"Expected optimization_history.json not produced: {error_message[:200]}"
        )

    if staged_file_count == 0 and failure_stage in ("parameter_optimization", "unknown"):
        return FailureClass.STAGING_MISMATCH, (
            "Staged TxtInOut is empty — likely staging step failed before bridge launch"
        )

    if any(k in msg_lower for k in _STAGING_KEYS):
        return FailureClass.STAGING_MISMATCH, (
            f"Staging issue detected: {error_message[:200]}"
        )

    if failure_stage in ("parameter_optimization", "runtime") or et_lower in (
        "runtimeerror", "valueerror", "typeerror", "attributeerror",
    ):
        return FailureClass.RUNTIME_CRASH, (
            f"{error_type} during {failure_stage}: {error_message[:200]}"
        )

    return FailureClass.UNKNOWN, f"{error_type}: {error_message[:200]}"


# ---------------------------------------------------------------------------
# Summary data models
# ---------------------------------------------------------------------------

class BridgeFailureRecord(BaseModel):
    """Normalized record from one bridge_failure_diagnostic.json artifact."""

    artifact_path: str
    timestamp_utc: str
    failure_class: FailureClass
    failure_detail: str
    failure_stage: str
    error_type: str
    error_message: str
    staged_file_count: int
    basin_id: str | None = None
    calsim_dir: str | None = None


class BridgeDiagnosticsSummary(BaseModel):
    """Aggregate summary across all bridge failure artifacts in a root tree."""

    generated_at: str
    root_scanned: str
    total_failures: int
    by_class: dict[str, int] = Field(default_factory=dict)
    records: list[BridgeFailureRecord] = Field(default_factory=list)
    recommendation: str = ""


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_bridge_diagnostics_summary(
    root: Path | str,
    *,
    out_dir: Path | str | None = None,
) -> BridgeDiagnosticsSummary:
    """Scan ``root`` for bridge failure artifacts and build a diagnostic summary.

    Writes (if ``out_dir`` is provided):
    - ``bridge_diagnostics.json`` — machine-readable aggregate
    - ``bridge_diagnostics_summary.md`` — markdown table

    Args:
        root:    Directory to scan recursively for ``bridge_failure_diagnostic.json``.
        out_dir: Optional directory to write summary files (defaults to ``root``).

    Returns:
        :class:`BridgeDiagnosticsSummary`
    """
    root = Path(root).expanduser().resolve()
    out_dir_path = Path(out_dir).expanduser().resolve() if out_dir else root

    records: list[BridgeFailureRecord] = []
    by_class: dict[str, int] = {}

    for artifact_path in sorted(root.rglob("bridge_failure_diagnostic.json")):
        try:
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        error_type   = data.get("error_type", "")
        error_msg    = data.get("error_message", "")
        tb           = data.get("traceback", "")
        stage        = data.get("failure_stage", "unknown")
        file_count   = int(data.get("staged_file_count", 0))

        # Reuse embedded class if already present; else classify.
        if "failure_class" in data and data["failure_class"] in FailureClass.__members__:
            fc = FailureClass(data["failure_class"])
            detail = data.get("failure_detail", "")
        else:
            fc, detail = classify_bridge_failure(
                error_type, error_msg, file_count, stage, tb
            )

        req = data.get("request_summary", {})
        basin_id = _infer_basin_from_request(req)

        rec = BridgeFailureRecord(
            artifact_path=str(artifact_path),
            timestamp_utc=data.get("timestamp_utc", ""),
            failure_class=fc,
            failure_detail=detail,
            failure_stage=stage,
            error_type=error_type,
            error_message=error_msg[:300],
            staged_file_count=file_count,
            basin_id=basin_id,
            calsim_dir=req.get("calsim_dir"),
        )
        records.append(rec)
        by_class[fc.value] = by_class.get(fc.value, 0) + 1

    recommendation = _make_recommendation(by_class, len(records))

    summary = BridgeDiagnosticsSummary(
        generated_at=datetime.now(timezone.utc).isoformat(),
        root_scanned=str(root),
        total_failures=len(records),
        by_class=by_class,
        records=records,
        recommendation=recommendation,
    )

    if out_dir_path:
        out_dir_path.mkdir(parents=True, exist_ok=True)
        _write_json(summary, out_dir_path / "bridge_diagnostics.json")
        _write_markdown(summary, out_dir_path / "bridge_diagnostics_summary.md")

    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _infer_basin_from_request(req: dict) -> str | None:
    calsim = req.get("calsim_dir", "") or ""
    txtinout = req.get("txtinout_dir", "") or ""
    for path_str in (calsim, txtinout):
        for part in reversed(Path(path_str).parts):
            if part.startswith("usgs_") or part.startswith("basin_"):
                return part
    return None


def _make_recommendation(by_class: dict[str, int], total: int) -> str:
    if total == 0:
        return "No bridge failures found."
    if FailureClass.IMPORT_ERROR.value in by_class:
        return (
            "pySWATPlus is not installed or has an incompatible API. "
            "Run: pip install pyswatplus. Verify with: python -c 'import pySWATPlus'."
        )
    if FailureClass.BINARY_NOT_FOUND.value in by_class:
        return (
            "SWAT+ binary is not accessible at the configured path. "
            "Set SWATPLUS_EXE to a valid executable and verify with: swat health."
        )
    if FailureClass.STAGING_MISMATCH.value in by_class:
        return (
            "Staged TxtInOut is empty — the staging step failed before the bridge launched. "
            "Check that base_txtinout contains file.cio and at least one .hru file."
        )
    if FailureClass.EMPTY_HISTORY.value in by_class:
        return (
            "pySWATPlus ran but produced no evaluation history. "
            "Increase n_gen/pop_size, check observed CSV alignment, and verify "
            "the objective sim file is produced by the engine."
        )
    if FailureClass.OUTPUT_MISSING.value in by_class:
        return (
            "optimization_history.json not produced. "
            "The bridge may have exited early. Check bridge stdout/stderr in the artifact."
        )
    if FailureClass.RUNTIME_CRASH.value in by_class:
        return (
            "Runtime crash during parameter_optimization. "
            "Check traceback in bridge_failure_diagnostic.json. "
            "Common causes: incompatible pySWATPlus API version, missing observed CSV columns, "
            "or SWAT+ engine exit code != 0."
        )
    return "Review bridge_failure_diagnostic.json artifacts for individual error details."


def _write_json(summary: BridgeDiagnosticsSummary, path: Path) -> None:
    path.write_text(
        json.dumps(summary.model_dump(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _write_markdown(summary: BridgeDiagnosticsSummary, path: Path) -> None:
    lines = [
        "# Bridge Diagnostics Summary",
        "",
        f"**Generated:** {summary.generated_at}  ",
        f"**Root scanned:** `{summary.root_scanned}`  ",
        f"**Total failures:** {summary.total_failures}",
        "",
    ]

    if summary.by_class:
        lines += [
            "## Failure class breakdown",
            "",
            "| Class | Count |",
            "| --- | ---: |",
        ]
        for cls, cnt in sorted(summary.by_class.items(), key=lambda x: -x[1]):
            lines.append(f"| `{cls}` | {cnt} |")
        lines.append("")

    lines += [
        "## Recommendation",
        "",
        summary.recommendation,
        "",
    ]

    if summary.records:
        lines += [
            "## Individual failures",
            "",
            "| Basin | Class | Stage | Error | Staged files | Timestamp |",
            "| --- | --- | --- | --- | ---: | --- |",
        ]
        for r in summary.records:
            basin  = r.basin_id or "unknown"
            msg    = r.error_message[:60].replace("|", "\\|")
            lines.append(
                f"| `{basin}` | `{r.failure_class.value}` | `{r.failure_stage}` "
                f"| {msg} | {r.staged_file_count} | {r.timestamp_utc[:19]} |"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
