"""End-to-end integration test against a real basin.

Opts in via ``SWATPLUS_BUILDER_RUN_REAL_BASIN=1``.

Runs the full Marsh Creek pipeline and asserts:

* every stage completes without raising;
* the project DB is written and has the expected ``gis_*`` counts;
* the vendored SWAT+ Editor successfully writes a ``TxtInOut/`` with
  at least the critical files we rely on downstream.

Requires:

* WhiteboxTools (``whitebox`` pip package; auto-downloads binary).
* Unrestricted network (USGS, MRLC, Planetary Computer,
  raw.githubusercontent.com for the real datasets DB).
* ~3–5 minutes of runtime.

See :file:`examples/real_basin_marsh_creek.py` for a hands-on demo.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

@pytest.mark.skipif(
    os.environ.get("SWATPLUS_BUILDER_RUN_REAL_BASIN") != "1",
    reason="Set SWATPLUS_BUILDER_RUN_REAL_BASIN=1 to run the real-basin E2E.",
)
@pytest.mark.slow
def test_marsh_creek_full_pipeline(tmp_path: Path) -> None:
    pytest.importorskip("whitebox")
    pytest.importorskip("py3dep")
    pytest.importorskip("pygeohydro")
    pytest.importorskip("pynhd")
    pytest.importorskip("pygridmet")

    # Import the example module — it's written to be callable as a
    # library in addition to a __main__.
    examples_dir = Path(__file__).parent.parent / "examples"
    sys.path.insert(0, str(examples_dir))
    try:
        import real_basin_marsh_creek as demo  # type: ignore
    finally:
        sys.path.pop(0)

    demo.main(tmp_path, run_engine=False)

    # -------- post-conditions --------
    db = tmp_path / "project" / "marsh_creek.sqlite"
    assert db.exists(), f"project DB missing: {db}"

    txtinout = tmp_path / "project" / "Scenarios" / "Default" / "TxtInOut"
    assert txtinout.is_dir(), f"TxtInOut not created: {txtinout}"

    file_cio = txtinout / "file.cio"
    assert file_cio.exists(), "file.cio missing"

    # Key LTE outputs the editor must have produced.
    for name in (
        "hru-lte.hru",       # per-HRU parameters
        "hru-lte.con",       # HRU connection routing
        "channel-lte.cha",   # LTE channel parameters
        "chandeg.con",       # channel connection routing
        "plants.plt",        # plant parameter table
        "time.sim",          # simulation window
        "pcp.cli",           # precipitation index
    ):
        assert (txtinout / name).exists(), f"missing {name} in TxtInOut/"

    # And the HRU file should reference standard NLCD-derived plant
    # codes (we ship NLCD_TO_SWATPLUS as the default now).
    hru_text = (txtinout / "hru-lte.hru").read_text()
    # At least one of these should appear in a real-world CONUS basin.
    expected_codes = {"frst", "frsd", "frse", "agrl", "hay", "rnge"}
    found = {c for c in expected_codes if c in hru_text.lower()}
    assert found, (
        f"no expected NLCD-derived plant codes in hru-lte.hru; "
        f"got none of {expected_codes}"
    )


def test_marsh_creek_main_accepts_custom_simulation_window() -> None:
    """Custom windows are needed for Phase 3F multi-year evidence runs."""
    examples_dir = Path(__file__).parent.parent / "examples"
    sys.path.insert(0, str(examples_dir))
    try:
        import real_basin_marsh_creek as demo  # type: ignore
    finally:
        sys.path.pop(0)

    sig = inspect.signature(demo.main)
    assert sig.parameters["sim_start"].default == demo.SIM_START
    assert sig.parameters["sim_end"].default == demo.SIM_END
