from __future__ import annotations

from pathlib import Path

from swatplus_builder.skills.swatplus_playbook import (
    PlaybookContext,
    PlaybookEvidenceEntry,
    append_playbook_evidence,
    recommend_next_action,
)


def test_playbook_recommends_bridge_investigation_for_flat_history() -> None:
    rec = recommend_next_action(
        PlaybookContext(
            basin_id="usgs_01547700",
            metric_source="evaluate_run",
            proposal_source="history",
            calibration_history_rows=10,
            calibration_history_unique_nse=1,
        )
    )

    assert rec.action == "investigate_calibration_bridge"
    assert "history" in rec.rejected_paths


def test_playbook_identifies_evaluate_run_as_authoritative_metric_source() -> None:
    rec = recommend_next_action(
        PlaybookContext(
            basin_id="usgs_01547700",
            metric_source="legacy_bridge",
            calibration_history_rows=5,
            calibration_history_unique_nse=2,
        )
    )

    assert rec.action == "restore_metric_authority"
    assert rec.authoritative_metric_source == "evaluate_run"


def test_playbook_update_appends_without_erasing_previous_entries(tmp_path: Path) -> None:
    playbook = tmp_path / "SWATPLUS_MODELING_PLAYBOOK.md"
    playbook.write_text("# SWAT+ Modeling Playbook\n\n## Existing\n- keep me\n\n", encoding="utf-8")

    append_playbook_evidence(
        playbook,
        [
            PlaybookEvidenceEntry(
                title="CN2 bridge trace",
                status="validated",
                category="calibration",
                source="manual_sensitivity",
                evidence="CN2 perturbation changed NSE and hydrograph.",
                consequence="Bridge must modify hydrology input files per evaluation.",
            )
        ],
    )

    text = playbook.read_text(encoding="utf-8")
    assert "keep me" in text
    assert "CN2 bridge trace" in text
    assert "status: `validated`" in text
