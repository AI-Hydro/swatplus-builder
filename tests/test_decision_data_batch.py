"""Unit tests for scripts/decision_data_batch.py's pure logic (no engine, no
subprocess): JSON-object extraction from mixed stdout, candidate-count
metering, and CLI validation of the --basins file. The subprocess-driving
parts (_run_one_basin) are exercised by the live smoke workflow instead --
they need a real SWAT+ engine and network access, which unit tests don't
have.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import decision_data_batch as batch  # noqa: E402


def test_extract_json_object_from_mixed_stdout():
    stdout = (
        "progress line one\n"
        "progress line two\n"
        + json.dumps({"success": True, "effective_claim_tier": "diagnostic"})
        + "\n"
    )
    result = batch._extract_json_object(stdout)
    assert result == {"success": True, "effective_claim_tier": "diagnostic"}


def test_extract_json_object_pure_json():
    stdout = json.dumps({"a": 1})
    assert batch._extract_json_object(stdout) == {"a": 1}


def test_extract_json_object_returns_none_on_garbage():
    assert batch._extract_json_object("not json at all") is None


def test_count_engine_candidate_evaluations_sums_phase_candidates(tmp_path):
    reports_dir = tmp_path / "calibration" / "calibration_reports_locked"
    reports_dir.mkdir(parents=True)
    (reports_dir / "phase_decisions.json").write_text(
        json.dumps({"phases": [{"candidate_count": 8}, {"candidate_count": 9}]}),
        encoding="utf-8",
    )
    assert batch._count_engine_candidate_evaluations(tmp_path) == 17


def test_count_engine_candidate_evaluations_none_when_no_artifacts(tmp_path):
    assert batch._count_engine_candidate_evaluations(tmp_path) is None


def test_main_rejects_duplicate_usgs_ids(tmp_path, capsys):
    basins = tmp_path / "basins.json"
    basins.write_text(json.dumps([{"usgs_id": "02177000"}, {"usgs_id": "02177000"}]), encoding="utf-8")
    out_root = tmp_path / "out"
    argv = sys.argv
    sys.argv = ["decision_data_batch.py", "--basins", str(basins), "--out-root", str(out_root)]
    try:
        rc = batch.main()
    finally:
        sys.argv = argv
    assert rc == 2
    assert "duplicate" in capsys.readouterr().err


def test_main_rejects_missing_usgs_id(tmp_path, capsys):
    basins = tmp_path / "basins.json"
    basins.write_text(json.dumps([{"start": "2015-01-01"}]), encoding="utf-8")
    out_root = tmp_path / "out"
    argv = sys.argv
    sys.argv = ["decision_data_batch.py", "--basins", str(basins), "--out-root", str(out_root)]
    try:
        rc = batch.main()
    finally:
        sys.argv = argv
    assert rc == 2
    assert "usgs_id" in capsys.readouterr().err


def test_main_dry_run_does_not_create_out_dirs(tmp_path, capsys):
    basins = tmp_path / "basins.json"
    basins.write_text(json.dumps([{"usgs_id": "02177000"}, {"usgs_id": "03339000"}]), encoding="utf-8")
    out_root = tmp_path / "out"
    argv = sys.argv
    sys.argv = [
        "decision_data_batch.py", "--basins", str(basins), "--out-root", str(out_root), "--dry-run",
    ]
    try:
        rc = batch.main()
    finally:
        sys.argv = argv
    assert rc == 0
    out = capsys.readouterr().out
    assert "02177000" in out and "03339000" in out
    assert not (out_root / "usgs_02177000").exists()
