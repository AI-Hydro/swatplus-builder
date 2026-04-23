from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from swatplus_builder.cli import app


def test_inspect_prints_metadata_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run01"
    run_dir.mkdir(parents=True)
    md_path = run_dir / "metadata.json"
    md_path.write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-04-23T00:00:00+00:00",
                "usgs_id": "01547700",
                "requested_outlet_gis_id": 1,
                "selected_outlet_gis_id": 1,
                "outlet_autodetected": False,
                "outlet_selection_reason": "requested_outlet",
                "routing_mode": "standard",
                "soil_mode": "high_fidelity",
                "pct_fallback_soils": 0.0,
                "engine_version": "/tmp/swatplus_exe",
                "builder_git_sha": "abc123",
                "input_hashes": {},
                "weather_source": "gridmet",
                "weather_coverage_flags": {},
                "notes": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    res = runner.invoke(app, ["inspect", str(run_dir)])
    assert res.exit_code == 0
    assert '"usgs_id": "01547700"' in res.stdout


def test_inspect_errors_when_missing(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["inspect", str(tmp_path)])
    assert res.exit_code == 1
    assert "metadata.json not found" in res.stdout

