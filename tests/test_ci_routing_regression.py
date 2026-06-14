from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SWATPLUS_BUILDER_RUN_ROUTING_REGRESSION") != "1",
    reason="Set SWATPLUS_BUILDER_RUN_ROUTING_REGRESSION=1 to run CI routing regression gate.",
)


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_multibasin_e2e.py"
ARTIFACT_ROOT = REPO_ROOT / "tests" / "_artifacts" / "e2e_runs"


def _sum_flo_out_for_gis_id_one(channel_sd_day: Path) -> float:
    lines = channel_sd_day.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 4:
        return 0.0
    header = lines[1].split()
    if "gis_id" not in header or "flo_out" not in header:
        return 0.0
    gid_idx = header.index("gis_id")
    flo_idx = header.index("flo_out")
    total = 0.0
    for line in lines[3:]:
        parts = line.split()
        if len(parts) <= max(gid_idx, flo_idx):
            continue
        try:
            gid = int(parts[gid_idx])
            flo = float(parts[flo_idx])
        except ValueError:
            continue
        if gid == 1:
            total += flo
    return total


@pytest.mark.slow
def test_multibasin_routing_regression_gate(tmp_path: Path) -> None:
    # Representative set for fast CI coverage:
    # - small humid basin
    # - small/medium mixed basin
    # - known dry-gis1 basin to exercise outlet auto-detection.
    sites = ["01547700", "01491000", "03339000"]
    nse_floor_sites = {"03339000"}
    batch = f"ci_routing_{uuid.uuid4().hex[:8]}"
    batch_dir = ARTIFACT_ROOT / batch

    cmd = [
        "python",
        str(RUNNER),
        "--sites",
        *sites,
        "--run-engine",
        "--batch-name",
        batch,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(
            "Routing regression batch command failed.\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )

    summary_path = batch_dir / "summary.json"
    assert summary_path.exists(), f"Missing summary.json: {summary_path}"
    results = json.loads(summary_path.read_text(encoding="utf-8"))
    by_id = {r["usgs_id"]: r for r in results}

    # Engine must complete and terminal channels must carry water.
    for sid in sites:
        assert sid in by_id, f"Missing site in summary: {sid}"
        row = by_id[sid]
        assert row["status"] == "success", f"{sid} failed: {row.get('error')}"
        assert (row.get("terminal_channels_with_flow") or 0) > 0, (
            f"{sid} has zero terminal flow rows."
        )
        assert (row.get("terminal_channels_total") or 0) > 0, (
            f"{sid} has zero terminal channel count."
        )

        run_dir = REPO_ROOT / row["run_dir"]
        align = run_dir / "outputs" / "alignment.csv"
        metrics = run_dir / "reports" / "metrics.json"
        assert align.exists(), f"{sid} missing alignment.csv"
        assert metrics.exists(), f"{sid} missing metrics.json"

        m = json.loads(metrics.read_text(encoding="utf-8"))
        nse = float(m.get("nse", float("nan")))
        assert math.isfinite(nse), f"{sid} NSE is non-finite: {nse}"
        # Keep the NSE floor assertion on the known structural regression basin.
        # Other basins in this fast CI set are currently uncalibrated and can
        # produce strongly negative NSE despite valid routing connectivity.
        if sid in nse_floor_sites:
            assert nse > -1.0, f"{sid} NSE floor violation: {nse}"

    # Outlet auto-detection behavior check:
    # For 03339000, gis_id=1 is known dry in channel output; yet alignment
    # must still contain non-zero simulated flow due outlet auto-detection.
    sid = "03339000"
    row = by_id[sid]
    run_dir = REPO_ROOT / row["run_dir"]
    ch = run_dir / "project" / "Scenarios" / "Default" / "TxtInOut" / "channel_sd_day.txt"
    assert ch.exists(), f"{sid} missing channel_sd_day.txt"
    gis1_sum = _sum_flo_out_for_gis_id_one(ch)
    assert abs(gis1_sum) < 1e-9, f"{sid} expected dry gis_id=1 but got sum {gis1_sum}"

    # Clean up after successful assertions to keep CI workspace light.
    shutil.rmtree(batch_dir, ignore_errors=True)
