"""Deterministic offline integration tests.

These tests exercise the core pipeline orchestration (outlet detection,
evaluate_run, lock_benchmark) against synthetic fixtures — no network
access, no SWAT+ engine binary, no external services required.

They run in CI alongside the smoke tests and serve as a fast regression
gate for infrastructure changes (FullBuildConfig, outlet derivation,
calibration bridge contracts).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swatplus_builder.output.eval import _terminal_ids_from_chandeg_con, evaluate_run


# ---------------------------------------------------------------------------
# Helpers: synthetic data fixtures
# ---------------------------------------------------------------------------


def _make_synthetic_chandeg_con(
    path: Path,
    *,
    terminal_gis_ids: list[int] | None = None,
) -> None:
    """Write a minimal chandeg.con where channels with out_tot=0 are terminals."""
    if terminal_gis_ids is None:
        terminal_gis_ids = [7]

    header = (
        "chandeg.con: written by swatplus-builder fixture\n"
        "      id  name                gis_id          area           lat           lon          elev      lcha               wst       cst      ovfl      rule   out_tot       obj_typ    obj_id       hyd_typ          frac\n"
    )
    rows: list[str] = []
    for i in range(1, 10):
        gis = i
        out_tot = 0 if gis in terminal_gis_ids else 1
        obj_typ = "out" if out_tot == 0 else "sdc"
        obj_id = 99 if out_tot == 0 else 30 + i
        rows.append(
            f"{i:>6d}  cha{i:02d}                {gis:>10d}       1.0      40.0     -76.0         0     {i}     s99999w99999         0         0         0     {out_tot}           {obj_typ}    {obj_id}           tot       1.00000\n"
        )
    path.write_text(header + "".join(rows), encoding="utf-8")


def _make_synthetic_channel_sd_day(path: Path) -> None:
    """Write a minimal channel_sd_day.txt matching SWAT+ format (66 columns).

    Uses a small inline data block (3 days, 1 channel) so the reader parses
    correctly.
    """
    # The real file has 66 columns: 8 leading + 21 storage/area + 18 inflow
    # + 18 outflow + 1 water_temp.
    # Build rows programmatically to guarantee the column count is exact.
    header = (
        "synthetic_basin             SWAT+ 2026-01-01        MODULAR Rev 2026.61.0.2.61                                                  \n"
        "   jday   mon   day    yr     unit   gis_id   name                  area         precip           evap           seep          flo_stor       sed_stor      orgn_stor      sedp_stor       no3_stor      solp_stor      chla_stor       nh3_stor       no2_stor      cbod_stor       dox_stor       san_stor       sil_stor       cla_stor       sag_stor       lag_stor       grv_stor           null         flo_in         sed_in        orgn_in        sedp_in         no3_in        solp_in        chla_in         nh3_in         no2_in        cbod_in         dox_in         san_in         sil_in         cla_in         sag_in         lag_in         grv_in           null        flo_out        sed_out       orgn_out       sedp_out        no3_out       solp_out       chla_out        nh3_out        no2_out       cbod_out        dox_out        san_out        sil_out        cla_out        sag_out        lag_out        grv_out           null     water_temp\n"
        "                                                                      ha            m^3            m^3            m^3             m^3           tons            kgN            kgP            kgN            kgP             kg            kgN            kgN             kg             kg           tons           tons           tons           tons           tons           tons                         m^3/s           tons            kgN            kgP            kgN            kgP             kg            kgN            kgN             kg             kg           tons           tons           tons           tons           tons           tons                         m^3/s           tons            kgN            kgP            kgN            kgP             kg            kgN            kgN             kg             kg           tons           tons           tons           tons           tons           tons                          degc\n"
    )

    def _e(v: float) -> str:
        return f"{v:>21.4E}"

    # Synthetic data: 3 days for channel 1 (gis_id=1) and channel 7.
    # Each row must produce exactly 66 whitespace-delimited tokens.
    rows: list[str] = []
    for ch, flo_vals in ((1, [10.0, 12.0, 15.0]), (7, [10.0, 12.0, 15.0])):
        for jday in (1, 2, 3):
            tokens = [
                # Leading (8): jday, mon, day, yr, unit, gis_id, name
                f"{jday:>6d}", f"{1:>5d}", f"{jday:>4d}", "2010",
                f"{ch:>6d}", f"{ch:>8d}", f"cha{ch:02d}",
                # Column 8: area
                _e(100.0),
            ]
            # Columns 9-29: precip(9), evap(10), seep(11), flo_stor..grv_stor(12-28), null(29) = 21 cols
            tokens.append(_e(5.0))  # precip
            tokens.extend([_e(0.0) for _ in range(20)])  # evap..null
            # Columns 30-47: flo_in..grv_in(30-46), null(47) = 18 cols
            tokens.append(_e(8.0))  # flo_in
            tokens.extend([_e(0.0) for _ in range(16)])  # sed_in..grv_in
            tokens.append(_e(0.0))  # null
            # Columns 48-65: flo_out..grv_out(48-64), null(65) = 18 cols
            flo = flo_vals[jday - 1]
            tokens.append(_e(flo))  # flo_out
            tokens.extend([_e(0.0) for _ in range(16)])  # sed_out..grv_out
            tokens.append(_e(0.0))  # null
            # Column 66: water_temp
            tokens.append(_e(10.0))

            row = " ".join(tokens) + "\n"
            # Verify: split should give 66 tokens
            assert len(row.split()) == 66, f"row has {len(row.split())} tokens, expected 66"
            rows.append(row)

    path.write_text(header + "".join(rows), encoding="utf-8")


def _make_synthetic_obs_series() -> pd.Series:
    """Create a 3-day synthetic observed series matching the sim output."""
    return pd.Series(
        [10.0, 12.0, 15.0],
        index=pd.date_range("2010-01-01", periods=3, freq="D"),
        name="obs",
    )


def _make_fake_txtinout(
    tmp_path: Path,
    *,
    terminal_gis_ids: list[int] | None = None,
) -> Path:
    """Create a minimal TxtInOut directory with synthetic outputs.

    No file.cio or other config files are created — this fixture is designed
    for evaluate_run / outlet-detection tests, not for engine execution.
    """
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)

    if terminal_gis_ids is None:
        terminal_gis_ids = [7]

    _make_synthetic_chandeg_con(txt / "chandeg.con", terminal_gis_ids=terminal_gis_ids)
    _make_synthetic_channel_sd_day(txt / "channel_sd_day.txt")

    return txt


# ---------------------------------------------------------------------------
# Tests: outlet detection from chandeg.con
# ---------------------------------------------------------------------------


class TestTopologyOutletDetection:
    """Outlet detection from chandeg.con — the core of the orchestrate.py fix."""

    def test_detects_single_terminal(self, tmp_path: Path) -> None:
        txt = _make_fake_txtinout(tmp_path, terminal_gis_ids=[7])
        ids = sorted(_terminal_ids_from_chandeg_con(txt))
        assert ids == [7]

    def test_detects_multiple_terminals(self, tmp_path: Path) -> None:
        txt = _make_fake_txtinout(tmp_path, terminal_gis_ids=[3, 7, 9])
        ids = sorted(_terminal_ids_from_chandeg_con(txt))
        assert ids == [3, 7, 9]

    def test_returns_empty_when_no_chandeg_con(self, tmp_path: Path) -> None:
        txt = tmp_path / "TxtInOut"
        txt.mkdir()
        ids = sorted(_terminal_ids_from_chandeg_con(txt))
        assert ids == []

    def test_returns_empty_for_empty_txtinout(self, tmp_path: Path) -> None:
        txt = tmp_path / "TxtInOut"
        txt.mkdir()
        (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
        ids = sorted(_terminal_ids_from_chandeg_con(txt))
        assert ids == []

    def test_detected_id_used_by_orchestrator_pattern(self, tmp_path: Path) -> None:
        """Replicates the orchestrator's outlet-derivation logic."""
        terminal_gis_ids = [7]
        txt = _make_fake_txtinout(tmp_path, terminal_gis_ids=terminal_gis_ids)

        # This is exactly what orchestrate.py now does
        detected = sorted(_terminal_ids_from_chandeg_con(txt))
        outlet_gis_id = detected[0] if detected else 1

        assert outlet_gis_id == 7
        assert outlet_gis_id != 1  # the old hardcoded value


# ---------------------------------------------------------------------------
# Tests: evaluate_run with synthetic data
# ---------------------------------------------------------------------------


class TestSyntheticEvaluateRun:
    """evaluate_run against synthetic data — no engine binary needed."""

    def test_evaluate_run_with_derived_outlet(self, tmp_path: Path) -> None:
        """Full evaluate_run using topology-derived outlet."""
        txt = _make_fake_txtinout(tmp_path, terminal_gis_ids=[7])
        obs = _make_synthetic_obs_series()

        channel_file = txt / "channel_sd_day.txt"
        df, metrics, diag = evaluate_run(
            channel_file, obs, outlet_gis_id=7,
            outlet_policy="strict", return_diagnostics=True,
        )

        assert diag["selected_outlet_gis_id"] == 7
        assert not np.isnan(metrics.get("nse", np.nan))
        assert not np.isnan(metrics.get("kge", np.nan))
        assert "pbias" in metrics

    def test_evaluate_run_auto_detects_best_terminal(self, tmp_path: Path) -> None:
        """Auto policy with a non-terminal request should detect the right outlet."""
        txt = _make_fake_txtinout(tmp_path, terminal_gis_ids=[7])
        obs = _make_synthetic_obs_series()

        channel_file = txt / "channel_sd_day.txt"
        df, metrics, diag = evaluate_run(
            channel_file, obs, outlet_gis_id=1,  # wrong — 1 is not a terminal
            outlet_policy="auto", return_diagnostics=True,
        )

        # The auto-policy should find the terminal with flow
        assert diag["selected_outlet_gis_id"] == 7


# ---------------------------------------------------------------------------
# Tests: lock_benchmark with topology-derived outlet
# ---------------------------------------------------------------------------


class TestTopologyOutletWithLockBenchmark:
    """lock_benchmark with topology-derived outlet — contracts-only test."""

    def test_lock_benchmark_accepts_derived_outlet(self, tmp_path: Path) -> None:
        from swatplus_builder.calibration.locked_benchmark import lock_benchmark

        txt = _make_fake_txtinout(tmp_path, terminal_gis_ids=[7])
        obs = _make_synthetic_obs_series()

        # Derive outlet from topology (same as orchestrate.py now does)
        detected = sorted(_terminal_ids_from_chandeg_con(txt))
        outlet_gis_id = detected[0]

        lock = lock_benchmark(
            txtinout_dir=txt,
            obs_series=obs,
            out_dir=tmp_path / "benchmark",
            basin_id="synthetic_test",
            outlet_gis_id=outlet_gis_id,
            sim_source_file="channel_sd_day.txt",
        )

        assert lock.outlet_gis_id == 7
        assert lock.basin_id == "synthetic_test"
        assert isinstance(lock.baseline_nse, float) and not np.isnan(lock.baseline_nse)
        assert isinstance(lock.baseline_kge, float) and not np.isnan(lock.baseline_kge)

        # Verify the benchmark lock file records the correct outlet
        lock_json_path = Path(lock.benchmark_dir) / "benchmark_lock.json"
        assert lock_json_path.exists(), f"missing {lock_json_path}"
        lock_json = json.loads(lock_json_path.read_text(encoding="utf-8"))
        assert lock_json.get("outlet_gis_id") == 7
