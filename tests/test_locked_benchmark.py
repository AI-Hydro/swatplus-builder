"""Tests for the locked-benchmark calibration protocol."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from swatplus_builder.calibration.locked_benchmark import (
    BenchmarkLock,
    CalibrationEvidence,
    ReadinessRow,
    VerificationResult,
    _resolve_lock,
    _write_readiness_markdown,
    build_readiness_table,
    lock_benchmark,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def obs_series() -> pd.Series:
    idx = pd.date_range("2010-01-01", periods=365, freq="D")
    import numpy as np

    rng = np.random.default_rng(42)
    vals = rng.uniform(0.1, 5.0, size=365)
    return pd.Series(vals, index=idx, name="obs")


def _make_fake_sim_file(txtinout: Path, gis_id: int = 1, n_days: int = 365) -> Path:
    """Write a minimal channel_sd_day.txt that evaluate_run can parse."""
    lines = ["channel_sd        Daily output: channel", ""]
    header = "gis_id  yr  mon  day  flo_out"
    lines.append(header)
    start = pd.Timestamp("2010-01-01")
    for i in range(n_days):
        d = start + pd.Timedelta(days=i)
        flo = 1.0 + i * 0.001
        lines.append(f"       {gis_id}   {d.year}    {d.month}    {d.day}     {flo:.4f}")
    p = txtinout / "channel_sd_day.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _make_chandeg_con(txtinout: Path, terminal_gis_id: int = 1) -> None:
    content = (
        "chandeg.con\n"
        "id  gis_id  obj_typ\n"
        f"1   {terminal_gis_id}   out\n"
    )
    (txtinout / "chandeg.con").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# lock_benchmark
# ---------------------------------------------------------------------------


def test_lock_benchmark_produces_artifact(tmp_path, obs_series):
    """lock_benchmark must write benchmark_lock.json + alignment.csv + metrics.json."""
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout, terminal_gis_id=1)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_out",
        basin_id="usgs_test01",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )

    bmark_dir = Path(lock.benchmark_dir)
    assert (bmark_dir / "benchmark_lock.json").exists()
    assert (bmark_dir / "alignment.csv").exists()
    assert (bmark_dir / "metrics.json").exists()
    assert (bmark_dir / "outlet_provenance.json").exists()


def test_lock_benchmark_metrics_finite(tmp_path, obs_series):
    """Locked benchmark must produce finite NSE/KGE values."""
    import math

    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_out",
        basin_id="usgs_test02",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )

    assert not math.isnan(lock.baseline_nse)
    assert not math.isnan(lock.baseline_kge)
    assert lock.alignment_sha256 != ""
    assert lock.outlet_gis_id == 1
    assert lock.outlet_policy == "strict"


def test_lock_benchmark_hash_determinism(tmp_path, obs_series):
    """Two calls on the same inputs must produce identical alignment SHA-256."""
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock1 = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_a",
        basin_id="usgs_test03",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )
    lock2 = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_b",
        basin_id="usgs_test03",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )

    assert lock1.alignment_sha256 == lock2.alignment_sha256
    assert lock1.baseline_nse == lock2.baseline_nse


def test_lock_benchmark_missing_sim_file_raises(tmp_path, obs_series):
    """lock_benchmark must raise SwatBuilderInputError when no sim file exists."""
    from swatplus_builder.errors import SwatBuilderInputError

    txtinout = tmp_path / "empty_txt"
    txtinout.mkdir()

    with pytest.raises(SwatBuilderInputError, match="No simulation output file"):
        lock_benchmark(
            txtinout_dir=txtinout,
            obs_series=obs_series,
            out_dir=tmp_path / "lock_out",
            basin_id="usgs_fail",
            outlet_gis_id=1,
        )


# ---------------------------------------------------------------------------
# _resolve_lock
# ---------------------------------------------------------------------------


def test_resolve_lock_from_benchmark_lock_object(tmp_path, obs_series):
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock",
        basin_id="usgs_resolve_test",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )
    resolved = _resolve_lock(lock)
    assert resolved.basin_id == lock.basin_id


def test_resolve_lock_from_json_path(tmp_path, obs_series):
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock",
        basin_id="usgs_path_test",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )
    json_path = Path(lock.benchmark_dir) / "benchmark_lock.json"
    resolved = _resolve_lock(json_path)
    assert resolved.basin_id == "usgs_path_test"


# ---------------------------------------------------------------------------
# build_readiness_table
# ---------------------------------------------------------------------------


def _make_verification_summary(root: Path, basin: str, improved: bool) -> None:
    lock_dir = root / basin
    lock_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "basin_id": basin,
        "benchmark_nse": 0.1,
        "benchmark_kge": 0.0,
        "verified_nse": 0.25 if improved else 0.05,
        "verified_kge": 0.15 if improved else -0.05,
        "delta_nse": 0.15 if improved else -0.05,
        "delta_kge": 0.15 if improved else -0.05,
        "improved": improved,
        "verification_dir": str(lock_dir / "verification"),
        "verification_summary_path": str(lock_dir / "verification_summary.json"),
    }
    (lock_dir / "verification_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def _make_benchmark_lock(root: Path, basin: str) -> None:
    bdir = root / basin / "benchmark"
    bdir.mkdir(parents=True, exist_ok=True)
    lock = {
        "basin_id": basin,
        "locked_at_utc": "2026-04-24T00:00:00+00:00",
        "alignment_sha256": "abc123",
        "metrics_sha256": "def456",
        "provenance_sha256": None,
        "outlet_gis_id": 1,
        "outlet_policy": "strict",
        "sim_source_file": "basin_sd_cha_day.txt",
        "git_sha": None,
        "baseline_nse": 0.1,
        "baseline_kge": 0.0,
        "benchmark_dir": str(bdir),
    }
    (bdir / "benchmark_lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def test_build_readiness_table_finds_verified_basins(tmp_path):
    """Readiness table must find and classify verified basins."""
    _make_verification_summary(tmp_path, "usgs_01547700", improved=True)
    _make_verification_summary(tmp_path, "usgs_03339000", improved=False)

    rows = build_readiness_table(tmp_path)
    assert len(rows) == 2
    statuses = {r.basin_id: r.verification_status for r in rows}
    assert statuses["usgs_01547700"] == "verified_improved"
    assert statuses["usgs_03339000"] == "verified_no_improvement"


def test_build_readiness_table_pending_locks(tmp_path):
    """Basins with a lock but no verification must appear as PENDING."""
    _make_benchmark_lock(tmp_path, "usgs_pending_01")
    rows = build_readiness_table(tmp_path)
    assert len(rows) >= 1
    pending = [r for r in rows if r.basin_id == "usgs_pending_01"]
    assert len(pending) == 1
    assert pending[0].verification_status == "locked_no_verification"


def test_build_readiness_table_empty_root(tmp_path):
    """Empty directory must return an empty list without raising."""
    rows = build_readiness_table(tmp_path / "nonexistent")
    assert rows == []


def test_build_readiness_table_writes_markdown(tmp_path):
    """out_md parameter must produce a readable markdown file."""
    _make_verification_summary(tmp_path, "usgs_01547700", improved=True)
    out_md = tmp_path / "readiness_table.md"
    build_readiness_table(tmp_path, out_md=out_md)
    assert out_md.exists()
    content = out_md.read_text(encoding="utf-8")
    assert "usgs_01547700" in content
    assert "PASS" in content


def test_write_readiness_markdown_structure(tmp_path):
    """Markdown output must include required headers and data rows."""
    rows = [
        ReadinessRow(
            basin_id="usgs_X",
            lock_dir="/some/dir",
            baseline_nse=0.12,
            baseline_kge=-0.05,
            calibrated_nse=0.25,
            calibrated_kge=0.10,
            delta_nse=0.13,
            delta_kge=0.15,
            improved=True,
            verification_status="verified_improved",
        ),
        ReadinessRow(
            basin_id="usgs_Y",
            lock_dir="/other/dir",
            baseline_nse=0.05,
            baseline_kge=-0.10,
            verification_status="locked_no_verification",
        ),
    ]
    out = tmp_path / "table.md"
    _write_readiness_markdown(out, rows)
    content = out.read_text(encoding="utf-8")
    assert "usgs_X" in content
    assert "PASS" in content
    assert "PENDING" in content
    assert "Baseline NSE" in content
