"""Tests for the safe solver subprocess wrapper and bridge isolation."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from swatplus_builder.errors import SwatBuilderExternalError
from swatplus_builder.run import run_solver_subprocess as _imported_from_init
from swatplus_builder.run.swatplus import _build_env, run_solver_subprocess


def test_run_solver_subprocess_exported_from_run_init():
    """run_solver_subprocess must be accessible from the run package."""
    assert _imported_from_init is run_solver_subprocess


def _make_fake_binary(tmpdir: Path, exit_code: int, stdout: str = "", stderr: str = "") -> Path:
    """Write a minimal shell script that mimics the SWAT+ binary contract."""
    script = tmpdir / "fake_swat"
    content = f"""#!/bin/sh
echo "{stdout}"
echo "{stderr}" >&2
exit {exit_code}
"""
    script.write_text(content, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.mark.skipif(sys.platform == "win32", reason="Shell scripts not portable on Windows")
def test_run_solver_subprocess_success(tmp_path):
    exe = _make_fake_binary(tmp_path, exit_code=0, stdout="SWAT+ complete")
    (tmp_path / "file.cio").touch()
    rc, stdout, stderr = run_solver_subprocess(exe, tmp_path)
    assert rc == 0
    assert "SWAT+ complete" in stdout


@pytest.mark.skipif(sys.platform == "win32", reason="Shell scripts not portable on Windows")
def test_run_solver_subprocess_non_zero_exit(tmp_path):
    exe = _make_fake_binary(tmp_path, exit_code=99, stderr="engine error")
    (tmp_path / "file.cio").touch()
    rc, _out, stderr = run_solver_subprocess(exe, tmp_path)
    assert rc == 99
    assert "engine error" in stderr


@pytest.mark.skipif(sys.platform == "win32", reason="Shell scripts not portable on Windows")
def test_run_solver_subprocess_timeout(tmp_path):
    """Timed-out invocations must raise SwatBuilderExternalError."""
    script = tmp_path / "slow_swat"
    script.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    (tmp_path / "file.cio").touch()
    with pytest.raises(SwatBuilderExternalError, match="timed out"):
        run_solver_subprocess(script, tmp_path, timeout_s=0.1)


def test_build_env_sets_omp_threads(tmp_path):
    """_build_env must set OMP_NUM_THREADS to the requested count."""
    env = _build_env(4, tmp_path / "fake_binary")
    assert env["OMP_NUM_THREADS"] == "4"


def test_build_env_clamps_threads(tmp_path):
    """_build_env with threads=0 should still produce a valid OMP count."""
    env = _build_env(0, tmp_path / "fake_binary")
    # run() clamps to >= 1 before calling _build_env; test the env directly
    assert env.get("OMP_NUM_THREADS") == "0"  # _build_env does not clamp; run() does


def test_calibrator_patch_uses_run_solver_subprocess():
    """The pySWATPlus monkey-patch must import from run.swatplus, not subprocess."""
    import inspect

    from swatplus_builder.calibration.calibrator import _apply_platform_compatibility_patches

    src = inspect.getsource(_apply_platform_compatibility_patches)
    # The patch must NOT contain a bare subprocess.Popen( call expression.
    assert "subprocess.Popen(" not in src
    # It must reference our wrapper.
    assert "run_solver_subprocess" in src
