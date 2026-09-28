"""Unit tests for scripts/basin_inclusion_protocol.py's pure logic:
contamination scanning and the deterministic development/held-out split.
The live-NWIS-query path (query_state, main) needs network access and is
exercised manually against the real service instead (see
docs/BASIN_INCLUSION_PROTOCOL.md and PROGRESS.md for that validation run).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import basin_inclusion_protocol as bip  # noqa: E402


def test_find_contaminated_usgs_ids_catches_curated_v1(tmp_path):
    (tmp_path / "basins").mkdir()
    (tmp_path / "basins" / "curated_v1.json").write_text(
        json.dumps({"basins": [{"usgs_id": "01547700"}, {"usgs_id": "03339000"}]}),
        encoding="utf-8",
    )
    hits = bip.find_contaminated_usgs_ids(tmp_path)
    assert "01547700" in hits
    assert "03339000" in hits
    assert "curated_v1.json" in hits["01547700"][0]


def test_find_contaminated_usgs_ids_catches_test_and_script_literals(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_something.py").write_text(
        'req = RunUSGSWorkflowRequest(usgs_id="02177000")\n',
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_it.py").write_text(
        'argv = ["--usgs-id", "12345678"]\n',
        encoding="utf-8",
    )
    hits = bip.find_contaminated_usgs_ids(tmp_path)
    assert "02177000" in hits
    assert "12345678" in hits


def test_find_contaminated_usgs_ids_catches_prior_run_directories(tmp_path):
    (tmp_path / "runs" / "usgs_02177000").mkdir(parents=True)
    hits = bip.find_contaminated_usgs_ids(tmp_path)
    assert "02177000" in hits
    assert any("runs" in c for c in hits["02177000"])


def test_find_contaminated_usgs_ids_does_not_flag_unrelated_numbers(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "unrelated.py").write_text(
        "timeout_ms = 123456789\nport = 987654321\n",  # no "usgs" anywhere nearby
        encoding="utf-8",
    )
    hits = bip.find_contaminated_usgs_ids(tmp_path)
    assert "123456789" not in hits
    assert "987654321" not in hits


def test_assign_group_is_deterministic_and_covers_both_groups():
    ids = [f"{i:08d}" for i in range(200)]
    groups = {bip.assign_group(i, development_fraction=0.5, salt="test-salt") for i in ids}
    assert groups == {"development", "held_out_final_assessment"}
    # Deterministic: same id, same salt -> same group every time.
    for usgs_id in ids[:10]:
        first = bip.assign_group(usgs_id, development_fraction=0.5, salt="test-salt")
        second = bip.assign_group(usgs_id, development_fraction=0.5, salt="test-salt")
        assert first == second


def test_assign_group_is_independent_of_typed_decision_split_salt():
    """The basin-inclusion split must use its own salt, distinct from
    decision_data/typed.py's assign_split default salt ("swat-s1"), so the
    two partitions don't correlate and one doesn't leak into the other."""
    from swatplus_builder.decision_data.typed import assign_split

    disagreements = 0
    for i in range(50):
        usgs_id = f"{i:08d}"
        basin_group = bip.assign_group(usgs_id, development_fraction=0.5, salt="swat-s1-basin-inclusion-v1")
        episode_split = assign_split(usgs_id)
        # Different salts -> the two partitions are not forced to coincide.
        if (basin_group == "development") != (episode_split in ("train", "validation")):
            disagreements += 1
    assert disagreements > 0


def test_assign_group_respects_development_fraction():
    ids = [f"{i:08d}" for i in range(2000)]
    n_dev = sum(1 for i in ids if bip.assign_group(i, development_fraction=0.3, salt="frac-test") == "development")
    # Should land near 30% with a large enough sample; generous tolerance
    # since this is a hash-based split, not exact stratified sampling.
    assert 0.2 < n_dev / len(ids) < 0.4
