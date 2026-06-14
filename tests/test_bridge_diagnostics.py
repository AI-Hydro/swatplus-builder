"""Tests for pySWATPlus bridge fail-loud diagnostics artifact.

Coverage
--------
Original 4 tests:   artifact writing via _write_bridge_failure_artifact
New 5 regression tests:
  - classify_bridge_failure for each deterministic failure class
  - build_bridge_diagnostics_summary discovery, class-counting, markdown write
  - failure_class embedded in artifact by _write_bridge_failure_artifact
  - CLI swat bridge-diagnose exit codes and JSON output
"""

from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.calibration.bridge_diagnostics import (
    FailureClass,
    build_bridge_diagnostics_summary,
    classify_bridge_failure,
)
from swatplus_builder.calibration.calibrator import BackendRequest, _write_bridge_failure_artifact


def _make_dummy_request(txtinout_dir: Path, calsim_dir: Path) -> BackendRequest:
    return BackendRequest(
        txtinout_dir=txtinout_dir,
        algorithm="de",
        n_gen=2,
        pop_size=4,
        objectives=["nse"],
        parameter_bounds=[{"name": "CN2", "min": 35.0, "max": 98.0}],
        parameter_initial=[{"name": "CN2", "value": 65.0}],
        observed_csv=txtinout_dir / "obs.csv",
        calsim_dir=calsim_dir,
        sim_output_file="basin_sd_cha_day.txt",
        outlet_gis_id=1,
    )


def test_bridge_failure_artifact_written_on_exception(tmp_path):
    """_write_bridge_failure_artifact must produce a valid JSON artifact."""
    calsim = tmp_path / "calsim"
    staged = tmp_path / "staged_txtinout"
    staged.mkdir()
    (staged / "file.cio").write_text("dummy\n")
    (staged / "hru-lte.hru").write_text("dummy content\n")

    req = _make_dummy_request(tmp_path, calsim)
    exc = RuntimeError("pySWATPlus execution failed (simulated)")

    _write_bridge_failure_artifact(
        calsim_dir=calsim,
        exc=exc,
        staged_txtinout=staged,
        request=req,
        failure_stage="parameter_optimization",
    )

    artifact_path = calsim / "bridge_failure_diagnostic.json"
    assert artifact_path.exists(), "bridge_failure_diagnostic.json must be written"

    data = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert data["failure_stage"] == "parameter_optimization"
    assert data["error_type"] == "RuntimeError"
    assert "pySWATPlus execution failed" in data["error_message"]
    assert "RuntimeError" in data["traceback"]
    assert data["staged_file_count"] == 2
    # Manifest must list the two staged files.
    manifest_names = {r["path"] for r in data["staged_txtinout_manifest"]}
    assert "file.cio" in manifest_names
    assert "hru-lte.hru" in manifest_names
    # Request summary must be sanitized (no raw values, just param names).
    assert "CN2" in data["request_summary"]["parameter_bounds"]
    assert data["request_summary"]["outlet_gis_id"] == 1


def test_bridge_failure_artifact_no_staged_dir(tmp_path):
    """Must succeed even if staged_txtinout is None or missing."""
    calsim = tmp_path / "calsim_no_stage"
    req = _make_dummy_request(tmp_path, calsim)
    exc = ValueError("Some other error")

    _write_bridge_failure_artifact(
        calsim_dir=calsim,
        exc=exc,
        staged_txtinout=None,
        request=req,
        failure_stage="pre_run",
    )

    artifact_path = calsim / "bridge_failure_diagnostic.json"
    assert artifact_path.exists()
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert data["staged_file_count"] == 0
    assert data["staged_txtinout_manifest"] == []


def test_bridge_failure_artifact_contains_timestamp(tmp_path):
    """Artifact must include a valid ISO-format UTC timestamp."""
    from datetime import datetime, timezone

    calsim = tmp_path / "calsim_ts"
    req = _make_dummy_request(tmp_path, calsim)
    before = datetime.now(timezone.utc).isoformat()

    _write_bridge_failure_artifact(
        calsim_dir=calsim,
        exc=RuntimeError("ts test"),
        staged_txtinout=None,
        request=req,
    )

    data = json.loads((calsim / "bridge_failure_diagnostic.json").read_text(encoding="utf-8"))
    ts = data["timestamp_utc"]
    assert ts >= before, "Artifact timestamp must be at or after test start"


def test_swatbuilder_external_error_includes_diagnostic_path(tmp_path, monkeypatch):
    """SwatBuilderExternalError raised after bridge failure must include diagnostic path."""
    from swatplus_builder.errors import SwatBuilderExternalError

    # Simulate the error that calibrator.py raises.
    exc = SwatBuilderExternalError(
        "pySWATPlus calibration execution failed",
        error="test",
        diagnostic_artifact=str(tmp_path / "calsim" / "bridge_failure_diagnostic.json"),
    )
    assert "diagnostic_artifact" in exc.context
    assert "bridge_failure_diagnostic.json" in exc.context["diagnostic_artifact"]


# ---------------------------------------------------------------------------
# Regression tests: known failure signatures
# ---------------------------------------------------------------------------

class TestClassifyBridgeFailure:
    """classify_bridge_failure must return deterministic FailureClass for known patterns."""

    def test_import_error_from_module_not_found(self):
        fc, detail = classify_bridge_failure(
            error_type="ModuleNotFoundError",
            error_message="No module named 'pySWATPlus'",
            staged_file_count=5,
            failure_stage="initialization",
        )
        assert fc == FailureClass.IMPORT_ERROR
        assert "pySWATPlus" in detail or "import" in detail.lower()

    def test_import_error_from_calibration_class_not_found(self):
        fc, detail = classify_bridge_failure(
            error_type="SwatBuilderExternalError",
            error_message="pySWATPlus Calibration class not found",
            staged_file_count=5,
            failure_stage="initialization",
        )
        assert fc == FailureClass.IMPORT_ERROR

    def test_binary_not_found_from_oserror(self):
        fc, detail = classify_bridge_failure(
            error_type="OSError",
            error_message="[Errno 2] No such file or directory: '/opt/swatplus/swatplus_exe'",
            staged_file_count=12,
            failure_stage="parameter_optimization",
        )
        assert fc == FailureClass.BINARY_NOT_FOUND

    def test_empty_history_pattern(self):
        fc, detail = classify_bridge_failure(
            error_type="SwatBuilderExternalError",
            error_message="pySWATPlus produced empty evaluation history",
            staged_file_count=15,
            failure_stage="parameter_optimization",
        )
        assert fc == FailureClass.EMPTY_HISTORY

    def test_staging_mismatch_from_empty_staged_dir(self):
        fc, detail = classify_bridge_failure(
            error_type="RuntimeError",
            error_message="pySWATPlus calibration execution failed",
            staged_file_count=0,  # empty staging = staging mismatch
            failure_stage="parameter_optimization",
        )
        assert fc == FailureClass.STAGING_MISMATCH

    def test_runtime_crash_from_exception_during_optimization(self):
        fc, detail = classify_bridge_failure(
            error_type="RuntimeError",
            error_message="Engine returned non-zero exit code 1",
            staged_file_count=20,
            failure_stage="parameter_optimization",
        )
        assert fc == FailureClass.RUNTIME_CRASH

    def test_output_missing_pattern(self):
        fc, detail = classify_bridge_failure(
            error_type="SwatBuilderExternalError",
            error_message="pySWATPlus did not produce optimization_history.json",
            staged_file_count=10,
            failure_stage="post_run",
        )
        assert fc == FailureClass.OUTPUT_MISSING


class TestBridgeDiagnosticsSummary:
    """build_bridge_diagnostics_summary must scan tree, classify, and write reports."""

    def _make_artifact(self, path: Path, error_msg: str, stage: str, file_count: int, failure_class: str | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "timestamp_utc": "2026-04-25T00:00:00+00:00",
            "failure_stage": stage,
            "error_type": "RuntimeError",
            "error_message": error_msg,
            "traceback": f"RuntimeError: {error_msg}",
            "request_summary": {
                "algorithm": "de", "n_gen": 10, "pop_size": 8,
                "objectives": ["nse"], "parameter_bounds": ["CN2"],
                "sim_output_file": "basin_sd_cha_day.txt",
                "outlet_gis_id": 1, "seed": 42,
                "txtinout_dir": "/tmp/usgs_01547700/TxtInOut",
                "calsim_dir": "/tmp/usgs_01547700/calsim",
                "staged_txtinout": None,
            },
            "staged_txtinout_manifest": [{"path": f"file{i}.txt", "size_bytes": 100} for i in range(file_count)],
            "staged_file_count": file_count,
        }
        if failure_class:
            data["failure_class"] = failure_class
            data["failure_detail"] = "pre-classified"
        path.write_text(json.dumps(data, indent=2))

    def test_finds_no_artifacts_in_empty_dir(self, tmp_path):
        summary = build_bridge_diagnostics_summary(tmp_path)
        assert summary.total_failures == 0
        assert summary.by_class == {}

    def test_finds_and_classifies_two_artifacts(self, tmp_path):
        self._make_artifact(
            tmp_path / "run_a" / "bridge_failure_diagnostic.json",
            error_msg="No module named 'pySWATPlus'",
            stage="initialization",
            file_count=5,
        )
        self._make_artifact(
            tmp_path / "run_b" / "bridge_failure_diagnostic.json",
            error_msg="pySWATPlus produced empty evaluation history",
            stage="parameter_optimization",
            file_count=12,
        )
        summary = build_bridge_diagnostics_summary(tmp_path)
        assert summary.total_failures == 2
        assert summary.by_class.get(FailureClass.IMPORT_ERROR.value, 0) >= 1
        assert summary.by_class.get(FailureClass.EMPTY_HISTORY.value, 0) >= 1

    def test_respects_pre_classified_failure_class(self, tmp_path):
        self._make_artifact(
            tmp_path / "run_c" / "bridge_failure_diagnostic.json",
            error_msg="some error",
            stage="parameter_optimization",
            file_count=5,
            failure_class="BINARY_NOT_FOUND",
        )
        summary = build_bridge_diagnostics_summary(tmp_path)
        assert summary.by_class.get("BINARY_NOT_FOUND", 0) == 1

    def test_writes_json_and_markdown_to_out_dir(self, tmp_path):
        self._make_artifact(
            tmp_path / "run_d" / "bridge_failure_diagnostic.json",
            error_msg="pySWATPlus calibration execution failed",
            stage="parameter_optimization",
            file_count=0,
        )
        out = tmp_path / "reports"
        build_bridge_diagnostics_summary(tmp_path, out_dir=out)
        assert (out / "bridge_diagnostics.json").exists()
        assert (out / "bridge_diagnostics_summary.md").exists()

    def test_markdown_contains_failure_class(self, tmp_path):
        self._make_artifact(
            tmp_path / "run_e" / "bridge_failure_diagnostic.json",
            error_msg="No module named 'pySWATPlus'",
            stage="initialization",
            file_count=5,
        )
        out = tmp_path / "out"
        build_bridge_diagnostics_summary(tmp_path, out_dir=out)
        md = (out / "bridge_diagnostics_summary.md").read_text()
        assert "IMPORT_ERROR" in md
        assert "Recommendation" in md


class TestBridgeFailureArtifactEmbedsFatureClass:
    """_write_bridge_failure_artifact must embed failure_class in the artifact JSON."""

    def test_artifact_contains_failure_class_field(self, tmp_path):
        calsim = tmp_path / "calsim"
        req = _make_dummy_request(tmp_path, calsim)
        _write_bridge_failure_artifact(
            calsim_dir=calsim,
            exc=RuntimeError("pySWATPlus produced empty evaluation history"),
            staged_txtinout=None,
            request=req,
            failure_stage="parameter_optimization",
        )
        data = json.loads((calsim / "bridge_failure_diagnostic.json").read_text())
        assert "failure_class" in data, "artifact must embed failure_class"
        assert data["failure_class"] in {fc.value for fc in FailureClass}
        assert "failure_detail" in data

    def test_import_error_classified_in_artifact(self, tmp_path):
        calsim = tmp_path / "calsim"
        req = _make_dummy_request(tmp_path, calsim)
        _write_bridge_failure_artifact(
            calsim_dir=calsim,
            exc=ModuleNotFoundError("No module named 'pySWATPlus'"),
            staged_txtinout=None,
            request=req,
            failure_stage="initialization",
        )
        data = json.loads((calsim / "bridge_failure_diagnostic.json").read_text())
        assert data["failure_class"] == FailureClass.IMPORT_ERROR.value


class TestBridgeDiagnoseCLI:
    """swat bridge-diagnose CLI must return correct exit codes."""

    def test_exit_0_when_no_failures(self, tmp_path):
        from typer.testing import CliRunner

        from swatplus_builder.cli import app
        runner = CliRunner()
        res = runner.invoke(app, ["bridge-diagnose", "--root", str(tmp_path), "--json"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data["total_failures"] == 0

    def test_exit_1_when_failures_found(self, tmp_path):
        from typer.testing import CliRunner

        from swatplus_builder.cli import app
        # Drop a minimal artifact
        art = tmp_path / "run" / "bridge_failure_diagnostic.json"
        art.parent.mkdir()
        art.write_text(json.dumps({
            "timestamp_utc": "2026-04-25T00:00:00+00:00",
            "failure_stage": "parameter_optimization",
            "error_type": "RuntimeError",
            "error_message": "pySWATPlus produced empty evaluation history",
            "traceback": "",
            "request_summary": {"algorithm": "de", "n_gen": 2, "pop_size": 4,
                                "objectives": ["nse"], "parameter_bounds": ["CN2"],
                                "sim_output_file": "basin_sd_cha_day.txt",
                                "outlet_gis_id": 1, "seed": 42,
                                "txtinout_dir": "/tmp", "calsim_dir": "/tmp",
                                "staged_txtinout": None},
            "staged_txtinout_manifest": [],
            "staged_file_count": 0,
        }))
        runner = CliRunner()
        res = runner.invoke(app, ["bridge-diagnose", "--root", str(tmp_path), "--json"])
        assert res.exit_code == 1
        data = json.loads(res.stdout)
        assert data["total_failures"] == 1
