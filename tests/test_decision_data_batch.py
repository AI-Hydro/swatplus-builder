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


def test_basin_result_started_at_has_no_default():
    """Regression: started_at used to be `field(default_factory=now_utc)`,
    which evaluates at BasinResult() *construction* time -- since every
    construction happens at the very end of _run_one_basin (right before
    returning), started_at and finished_at ended up identical, hiding the
    true start time entirely. A live proof run against USGS 08155240
    (2026-09-28/29) also showed wall_clock_s itself was wrong: it used
    time.monotonic(), which does not advance while macOS is asleep, so a
    basin whose real run spanned ~51 minutes (confirmed via its own
    events.jsonl timestamps and output-file mtimes) was recorded as 208s.
    Both are fixed by computing started_at/wall_clock_s from wall-clock
    (datetime.now(timezone.utc)) timestamps captured explicitly at the real
    start, not from a dataclass default or a monotonic clock. Pin that
    started_at has no default, so every call site must supply it (and a
    reviewer must actively choose what "start" means, rather than a default
    quietly picking "now").
    """
    import dataclasses

    fields_by_name = {f.name: f for f in dataclasses.fields(batch.BasinResult)}
    assert fields_by_name["started_at"].default is dataclasses.MISSING
    assert fields_by_name["started_at"].default_factory is dataclasses.MISSING


def test_extract_json_object_from_mixed_stdout():
    stdout = (
        "progress line one\n"
        "progress line two\n"
        + json.dumps({"success": True, "effective_claim_tier": "diagnostic"})
        + "\n"
    )
    result = batch._extract_json_object(stdout)
    assert result == {"success": True, "effective_claim_tier": "diagnostic"}


def test_extract_json_object_matches_real_workflow_run_shape():
    """Regression: `swat workflow run --json`'s top-level object is
    RunUSGSWorkflowResult -- blocker_class is top-level, but
    effective_claim_tier is only nested inside "values". A live batch-driver
    run against USGS 03339000 (2026-09-28) silently recorded tier=None
    because an earlier version of _run_one_basin read
    payload.get("effective_claim_tier") instead of
    payload["values"].get("effective_claim_tier"). Pin the real shape here
    so that regresses loudly."""
    stdout = "progress\n" + json.dumps(
        {
            "success": True,
            "run_id": "usgs_03339000_20150101_20191231",
            "artifact_dir": "/tmp/run",
            "evidence_summary_path": "/tmp/run/evidence_summary.json",
            "blocker_class": None,
            "values": {"effective_claim_tier": "exploratory", "nse": 0.45},
        }
    )
    payload = batch._extract_json_object(stdout)
    assert payload["blocker_class"] is None
    assert (payload.get("values") or {}).get("effective_claim_tier") == "exploratory"
    assert payload.get("effective_claim_tier") is None  # NOT at top level


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
