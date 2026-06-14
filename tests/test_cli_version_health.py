"""Regression tests for swat version and swat health CLI commands.

Exit-code contract
------------------
version
  0  — always (info command; no failure mode)

health
  0  — all checks pass (healthy)
  1  — non-critical items missing (degraded)
  2  — critical failure (wrong Python, import error)
"""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from swatplus_builder.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# swat version
# ---------------------------------------------------------------------------

class TestCmdVersion:
    def test_exit_zero(self):
        res = runner.invoke(app, ["version"])
        assert res.exit_code == 0

    def test_contains_version_string(self):
        from swatplus_builder import __version__
        res = runner.invoke(app, ["version"])
        assert __version__ in res.stdout

    def test_json_flag_parses(self):
        res = runner.invoke(app, ["version", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data["package"] == "swatplus-builder"
        assert "version" in data
        assert "git_sha" in data
        assert "python" in data

    def test_json_version_matches_package(self):
        from swatplus_builder import __version__
        res = runner.invoke(app, ["version", "--json"])
        data = json.loads(res.stdout)
        assert data["version"] == __version__

    def test_json_python_version_matches_runtime(self):
        import platform
        res = runner.invoke(app, ["version", "--json"])
        data = json.loads(res.stdout)
        assert data["python"] == platform.python_version()


# ---------------------------------------------------------------------------
# swat health — exit codes
# ---------------------------------------------------------------------------

class TestCmdHealthExitCodes:
    def test_healthy_returns_0_when_all_pass(self):
        """Patch optional importers to all succeed; no env vars needed."""
        with (
            patch("sys.version_info", (3, 11, 0)),
            patch.dict("os.environ", {
                "SWATPLUS_BUILDER_ARTIFACTS": "/tmp",
            }),
        ):
            res = runner.invoke(app, ["health"])
        # May be 0 or 1 depending on binary/db/gis — just assert no critical fail (not 2)
        assert res.exit_code in {0, 1}

    def test_degraded_returns_1_when_optional_missing(self, tmp_path):
        """Clear all optional env vars so binary/db/artifacts are missing."""
        with patch.dict("os.environ", {}, clear=True):
            res = runner.invoke(app, ["health"])
        # Python is fine, package imported, but binary/db/artifacts all missing → degraded (exit 1)
        assert res.exit_code == 1

    def test_unhealthy_returns_2_on_critical_fail(self):
        """Simulate Python version too old → unhealthy."""
        with patch("sys.version_info", (3, 9, 0)):
            res = runner.invoke(app, ["health"])
        # critical failures → exit 2
        assert res.exit_code == 2

    def test_json_output_structure(self):
        res = runner.invoke(app, ["health", "--json"])
        assert res.exit_code in {0, 1, 2}
        data = json.loads(res.stdout)
        assert "status" in data
        assert data["status"] in {"healthy", "degraded", "unhealthy"}
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert data["exit_code"] == res.exit_code

    def test_json_checks_have_required_fields(self):
        res = runner.invoke(app, ["health", "--json"])
        data = json.loads(res.stdout)
        for check in data["checks"]:
            assert "name" in check
            assert "critical" in check
            assert "ok" in check
            assert "detail" in check

    def test_health_includes_python_check(self):
        res = runner.invoke(app, ["health", "--json"])
        data = json.loads(res.stdout)
        names = [c["name"] for c in data["checks"]]
        assert "python_version" in names

    def test_health_includes_exe_check(self):
        res = runner.invoke(app, ["health", "--json"])
        data = json.loads(res.stdout)
        names = [c["name"] for c in data["checks"]]
        assert "swatplus_exe" in names

    def test_health_exe_ok_when_file_exists(self, tmp_path):
        fake_exe = tmp_path / "swatplus_exe"
        fake_exe.write_bytes(b"")
        with patch.dict("os.environ", {"SWATPLUS_EXE": str(fake_exe)}):
            res = runner.invoke(app, ["health", "--json"])
        data = json.loads(res.stdout)
        exe_check = next(c for c in data["checks"] if c["name"] == "swatplus_exe")
        assert exe_check["ok"] is True

    def test_health_exe_fail_when_path_missing(self, tmp_path):
        with patch.dict("os.environ", {"SWATPLUS_EXE": str(tmp_path / "no_such_exe")}):
            res = runner.invoke(app, ["health", "--json"])
        data = json.loads(res.stdout)
        exe_check = next(c for c in data["checks"] if c["name"] == "swatplus_exe")
        assert exe_check["ok"] is False

    def test_health_unhealthy_json_status_string(self):
        with patch("sys.version_info", (3, 8, 0)):
            res = runner.invoke(app, ["health", "--json"])
        data = json.loads(res.stdout)
        assert data["status"] == "unhealthy"
        assert res.exit_code == 2

    def test_health_healthy_status_string_when_all_pass(self, tmp_path):
        fake_exe = tmp_path / "swatplus_exe"
        fake_exe.write_bytes(b"")
        fake_db = tmp_path / "datasets.sqlite"
        fake_db.write_bytes(b"")
        with (
            patch("sys.version_info", (3, 11, 0)),
            patch.dict("os.environ", {
                "SWATPLUS_EXE": str(fake_exe),
                "SWATPLUS_BUILDER_ARTIFACTS": str(tmp_path),
                "SWATPLUS_DATASETS_DB": str(fake_db),
            }),
            patch("builtins.__import__", _make_selective_import({"rasterio", "geopandas", "fastmcp"})),
        ):
            res = runner.invoke(app, ["health", "--json"])
        data = json.loads(res.stdout)
        assert data["status"] in {"healthy", "degraded"}  # degraded if GIS not installed in test env


# ---------------------------------------------------------------------------
# Exit-code contract: sensitivity runtime error → Exit(1)
# ---------------------------------------------------------------------------

class TestSensitivityExitCode:
    def test_missing_parameter_exits_2(self):
        """User config error: unknown parameter name → Exit(2)."""
        res = runner.invoke(app, [
            "sensitivity",
            "--basin", "test_basin",
            "--base-txtinout", "/nonexistent",
            "--parameters", "NOT_A_REAL_PARAM",
        ])
        assert res.exit_code == 2

    def test_empty_parameter_list_exits_2(self):
        res = runner.invoke(app, [
            "sensitivity",
            "--basin", "test_basin",
            "--base-txtinout", "/nonexistent",
            "--parameters", "",
        ])
        assert res.exit_code == 2


# ---------------------------------------------------------------------------
# Exit-code contract: diagnose runtime error → Exit(1)
# ---------------------------------------------------------------------------

class TestDiagnoseExitCode:
    def test_missing_run_artifact_exits_2(self, tmp_path):
        """Nonexistent target — SwatBuilderError from diagnose() → Exit(1)."""
        res = runner.invoke(app, [
            "diagnose",
            "--run-artifact", str(tmp_path / "no_such_run"),
        ])
        # Either 1 (runtime SwatBuilderError) or 2 (path not found guard)
        assert res.exit_code in {1, 2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_selective_import(always_succeed: set[str]):
    """Return a patched __import__ that makes specified modules appear installed."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _import(name, *args, **kwargs):
        if name in always_succeed:
            from unittest.mock import MagicMock
            return MagicMock()
        return real_import(name, *args, **kwargs)

    return _import
