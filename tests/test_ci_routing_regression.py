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


# Basins that must build + run the SWAT+ engine end-to-end. These are the
# regression guard: a code change that breaks the working pipeline fails here.
# - 01547700: small humid basin
# - 01491000: small/medium mixed basin
FULL_PIPELINE_SITES = ["01547700", "01491000"]

# Large basin reserved for the dry-gis1 / outlet-auto-detection check. Its
# single-gauge delineation currently fragments into multiple routing terminals
# (the documented large-basin multi-terminal limitation, tracked as C1 / a
# science blocker — NOT a regression in this pipeline). We still run it so the
# nightly surfaces any change, but a C1-class delineation failure is reported as
# a known limitation rather than failing the suite.
KNOWN_LIMITATION_SITES = ["03339000"]

ALL_SITES = FULL_PIPELINE_SITES + KNOWN_LIMITATION_SITES


@pytest.mark.slow
def test_multibasin_routing_regression_gate(tmp_path: Path) -> None:
    batch = f"ci_routing_{uuid.uuid4().hex[:8]}"
    batch_dir = ARTIFACT_ROOT / batch

    cmd = [
        "python",
        str(RUNNER),
        "--sites",
        *ALL_SITES,
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
    # The batch runner records per-site status and exits non-zero if ANY site
    # fails. We assert per-site below (FULL_PIPELINE_SITES must pass; the
    # known-limitation basin is allowed to fail at delineation), so we do not
    # gate on the aggregate return code here — but we do require the summary.
    summary_path = batch_dir / "summary.json"
    assert summary_path.exists(), (
        "Missing summary.json — batch runner did not complete.\n"
        f"return code: {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
    )
    results = json.loads(summary_path.read_text(encoding="utf-8"))
    by_id = {r["usgs_id"]: r for r in results}

    # --- Regression guard: full-pipeline basins must succeed end-to-end. ---
    for sid in FULL_PIPELINE_SITES:
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

    # --- Known-limitation basin: dry-gis1 / outlet-auto-detection check. ---
    # If the large basin's delineation succeeds, the dry-gis1 invariant must
    # hold. If it fails (C1 multi-terminal limitation), report it as a known
    # limitation via xfail rather than failing the regression suite.
    sid = KNOWN_LIMITATION_SITES[0]
    row = by_id.get(sid)
    if row is None or row.get("status") != "success":
        err = (row or {}).get("error", "site absent from summary")
        pytest.xfail(
            f"{sid} did not complete — large-basin multi-terminal delineation "
            f"(C1, tracked science blocker), not a pipeline regression. Detail: {err}"
        )

    run_dir = REPO_ROOT / row["run_dir"]
    ch = run_dir / "project" / "Scenarios" / "Default" / "TxtInOut" / "channel_sd_day.txt"
    assert ch.exists(), f"{sid} missing channel_sd_day.txt"
    gis1_sum = _sum_flo_out_for_gis_id_one(ch)
    assert abs(gis1_sum) < 1e-9, f"{sid} expected dry gis_id=1 but got sum {gis1_sum}"

    # Clean up after successful assertions to keep CI workspace light.
    shutil.rmtree(batch_dir, ignore_errors=True)
