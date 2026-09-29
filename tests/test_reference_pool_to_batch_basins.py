"""Unit tests for scripts/reference_pool_to_batch_basins.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import reference_pool_to_batch_basins as conv  # noqa: E402


def _make_pool(tmp_path: Path) -> Path:
    pool = {
        "schema": "swatplus_builder.basin_inclusion_pool/v1",
        "included": [
            {"usgs_id": "11111111", "station_nm": "A", "state_cd": "in", "drain_area_km2": 100.0, "hcdn_2009": False, "group": "development"},
            {"usgs_id": "22222222", "station_nm": "B", "state_cd": "oh", "drain_area_km2": 200.0, "hcdn_2009": True, "group": "development"},
            {"usgs_id": "33333333", "station_nm": "C", "state_cd": "ky", "drain_area_km2": 300.0, "hcdn_2009": False, "group": "held_out_final_assessment"},
        ],
        "excluded": [],
    }
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(pool), encoding="utf-8")
    return path


def _run(argv):
    old = sys.argv
    sys.argv = ["reference_pool_to_batch_basins.py"] + argv
    try:
        return conv.main()
    finally:
        sys.argv = old


def test_default_group_is_development_only(tmp_path):
    pool = _make_pool(tmp_path)
    out = tmp_path / "out.json"
    rc = _run(["--pool", str(pool), "--out", str(out)])
    assert rc == 0
    specs = json.loads(out.read_text())
    assert {s["usgs_id"] for s in specs} == {"11111111", "22222222"}


def test_held_out_group_refused_without_ack_flag(tmp_path, capsys):
    pool = _make_pool(tmp_path)
    out = tmp_path / "out.json"
    rc = _run(["--pool", str(pool), "--out", str(out), "--group", "held_out_final_assessment"])
    assert rc == 2
    assert not out.exists()
    assert "held_out_final_assessment" in capsys.readouterr().err


def test_held_out_group_allowed_with_explicit_ack(tmp_path):
    pool = _make_pool(tmp_path)
    out = tmp_path / "out.json"
    rc = _run([
        "--pool", str(pool), "--out", str(out),
        "--group", "held_out_final_assessment",
        "--i-understand-this-is-the-held-out-set",
    ])
    assert rc == 0
    specs = json.loads(out.read_text())
    assert {s["usgs_id"] for s in specs} == {"33333333"}


def test_limit_is_deterministic_across_runs(tmp_path):
    pool = _make_pool(tmp_path)
    out1, out2 = tmp_path / "out1.json", tmp_path / "out2.json"
    _run(["--pool", str(pool), "--out", str(out1), "--limit", "1"])
    _run(["--pool", str(pool), "--out", str(out2), "--limit", "1"])
    assert json.loads(out1.read_text()) == json.loads(out2.read_text())


def test_hcdn_2009_only_filter(tmp_path):
    pool = _make_pool(tmp_path)
    out = tmp_path / "out.json"
    _run(["--pool", str(pool), "--out", str(out), "--hcdn-2009-only"])
    specs = json.loads(out.read_text())
    assert {s["usgs_id"] for s in specs} == {"22222222"}


def test_state_filter(tmp_path):
    pool = _make_pool(tmp_path)
    out = tmp_path / "out.json"
    _run(["--pool", str(pool), "--out", str(out), "--state-cd", "oh"])
    specs = json.loads(out.read_text())
    assert {s["usgs_id"] for s in specs} == {"22222222"}


def test_emitted_specs_are_consumable_by_decision_data_batch_arg_shape():
    """Every key decision_data_batch.py's _PASSTHROUGH_FLAGS looks for must
    either be present with a sane value or simply absent (it merges with
    defaults) -- this just pins the emitted key names decision_data_batch.py
    actually understands, so a rename on either side breaks a test instead
    of silently producing an empty argv flag."""
    import decision_data_batch as batch

    emitted_keys = {"usgs_id", "start", "end", "warmup_years", "claim_tier"}
    passthrough_keys = set(batch._PASSTHROUGH_FLAGS.keys()) | {"usgs_id"}
    assert emitted_keys <= passthrough_keys | {"claim_tier"}
    assert "claim_tier" in batch._PASSTHROUGH_FLAGS


def test_no_basins_matched_returns_error(tmp_path, capsys):
    pool = _make_pool(tmp_path)
    out = tmp_path / "out.json"
    rc = _run(["--pool", str(pool), "--out", str(out), "--state-cd", "zz_nonexistent"])
    assert rc != 0


def _patch_fetch(monkeypatch, series):
    import swatplus_builder.calibration.nwis as nwis

    monkeypatch.setattr(nwis, "fetch_usgs_daily_q", lambda *a, **k: series)


def test_window_coverage_handles_microsecond_index(monkeypatch):
    """Regression: cached NWIS series carry a datetime64[us] index; an
    earlier version reindexed against a ns date_range and reported 0.0
    coverage for a complete record (USGS 01197000)."""
    import pandas as pd

    idx = pd.date_range("2015-01-01", "2015-12-31", freq="D").as_unit("us")
    _patch_fetch(monkeypatch, pd.Series(1.0, index=idx))
    cov, reason = conv._window_discharge_coverage("x", "2015-01-01", "2015-12-31")
    assert cov == 1.0 and reason is None


def test_window_coverage_detects_record_gap(monkeypatch):
    """USGS 04077400's site metadata advertises 1985-2026, but it has no
    daily values 2001-07..2026-08; the pre-flight must see the gap."""
    import pandas as pd

    idx = pd.date_range("2015-01-01", "2015-06-30", freq="D")
    _patch_fetch(monkeypatch, pd.Series(1.0, index=idx))
    cov, _ = conv._window_discharge_coverage("x", "2015-01-01", "2015-12-31")
    assert 0.49 < cov < 0.5


def test_window_coverage_reports_fetch_error(monkeypatch):
    import swatplus_builder.calibration.nwis as nwis

    def boom(*a, **k):
        raise ValueError("Discharge is not available for the requested query.")

    monkeypatch.setattr(nwis, "fetch_usgs_daily_q", boom)
    cov, reason = conv._window_discharge_coverage("x", "2015-01-01", "2015-12-31")
    assert cov == 0.0 and "not available" in reason


def test_already_run_ids(tmp_path):
    (tmp_path / "batch_a" / "usgs_02363000").mkdir(parents=True)
    (tmp_path / "usgs_01197000").mkdir()
    (tmp_path / "usgs_notanid").mkdir()
    assert conv._already_run_ids(tmp_path) == {"02363000", "01197000"}
