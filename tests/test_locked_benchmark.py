"""Tests for the locked-benchmark calibration protocol."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from swatplus_builder.calibration.locked_benchmark import (
    BenchmarkLock,
    ReadinessRow,
    _diagnostic_calibration_phases,
    _phase_candidate_points,
    _resolve_lock,
    _score_candidate,
    _volume_gate_passed,
    _write_readiness_markdown,
    build_readiness_table,
    calibrate_against_lock,
    lock_benchmark,
    screen_parameters_against_lock,
    verify_calibration,
)
from swatplus_builder.calibration.real_engine import params_hash
from swatplus_builder.errors import SwatBuilderInputError, SwatBuilderPipelineError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def obs_series() -> pd.Series:
    idx = pd.date_range("2010-01-01", periods=365, freq="D")
    import numpy as np

    rng = np.random.default_rng(42)
    vals = rng.uniform(0.1, 5.0, size=365)
    return pd.Series(vals, index=idx, name="obs")


def _make_fake_sim_file(txtinout: Path, gis_id: int = 1, n_days: int = 365) -> Path:
    """Write a minimal channel_sd_day.txt that evaluate_run can parse."""
    lines = ["channel_sd        Daily output: channel", ""]
    header = "gis_id  yr  mon  day  flo_out"
    lines.append(header)
    start = pd.Timestamp("2010-01-01")
    for i in range(n_days):
        d = start + pd.Timedelta(days=i)
        flo = 1.0 + i * 0.001
        lines.append(f"       {gis_id}   {d.year}    {d.month}    {d.day}     {flo:.4f}")
    p = txtinout / "channel_sd_day.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _make_chandeg_con(txtinout: Path, terminal_gis_id: int = 1) -> None:
    content = (
        "chandeg.con\n"
        "id  gis_id  obj_typ\n"
        f"1   {terminal_gis_id}   out\n"
    )
    (txtinout / "chandeg.con").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# lock_benchmark
# ---------------------------------------------------------------------------


def test_lock_benchmark_produces_artifact(tmp_path, obs_series):
    """lock_benchmark must write benchmark_lock.json + alignment.csv + metrics.json."""
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout, terminal_gis_id=1)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_out",
        basin_id="usgs_test01",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )

    bmark_dir = Path(lock.benchmark_dir)
    assert (bmark_dir / "benchmark_lock.json").exists()
    assert (bmark_dir / "alignment.csv").exists()
    assert (bmark_dir / "metrics.json").exists()
    assert (bmark_dir / "outlet_provenance.json").exists()


def test_lock_benchmark_metrics_finite(tmp_path, obs_series):
    """Locked benchmark must produce finite NSE/KGE values."""
    import math

    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_out",
        basin_id="usgs_test02",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )

    assert not math.isnan(lock.baseline_nse)
    assert not math.isnan(lock.baseline_kge)
    assert lock.alignment_sha256 != ""
    assert lock.outlet_gis_id == 1
    assert lock.outlet_policy == "strict"


def test_lock_benchmark_hash_determinism(tmp_path, obs_series):
    """Two calls on the same inputs must produce identical alignment SHA-256."""
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock1 = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_a",
        basin_id="usgs_test03",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )
    lock2 = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock_b",
        basin_id="usgs_test03",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )

    assert lock1.alignment_sha256 == lock2.alignment_sha256
    assert lock1.baseline_nse == lock2.baseline_nse


def test_lock_benchmark_missing_sim_file_raises(tmp_path, obs_series):
    """lock_benchmark must raise SwatBuilderInputError when no sim file exists."""
    from swatplus_builder.errors import SwatBuilderInputError

    txtinout = tmp_path / "empty_txt"
    txtinout.mkdir()

    with pytest.raises(SwatBuilderInputError, match="No simulation output file"):
        lock_benchmark(
            txtinout_dir=txtinout,
            obs_series=obs_series,
            out_dir=tmp_path / "lock_out",
            basin_id="usgs_fail",
            outlet_gis_id=1,
        )


def test_lock_benchmark_can_lock_authorized_all_terminal_virtual_outlet(tmp_path: Path) -> None:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    (txtinout / "channel_sd_day.txt").write_text(
        "\n".join(
            [
                "channel_sd_day",
                "jday mon day yr unit gis_id name flo_out",
                "n/a n/a n/a n/a n/a n/a n/a m3/s",
                "1 1 1 2015 7 7 cha07 1.0",
                "1 1 1 2015 8 8 cha08 2.0",
                "2 1 2 2015 7 7 cha07 2.0",
                "2 1 2 2015 8 8 cha08 3.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (txtinout / "chandeg.con").write_text(
        "\n".join(
            [
                "chandeg.con",
                "id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac",
                "7 cha0007 7 0 0 0 0 7 s 0 0 0 0 out 1 tot 1.0",
                "8 cha0008 8 0 0 0 0 8 s 0 0 0 0 out 2 tot 1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    obs = pd.Series([3.0, 5.0], index=pd.to_datetime(["2015-01-01", "2015-01-02"]), name="obs")

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs,
        out_dir=tmp_path / "lock_out",
        basin_id="usgs_virtual",
        outlet_gis_id=7,
        sim_source_file="channel_sd_day.txt",
        virtual_outlet_policy="all_terminal_sum",
        virtual_outlet_authority=(
            "official_usgs_site_area_matches_all_terminal_no_overlap_candidate"
        ),
    )

    assert lock.outlet_policy == "all_terminal_sum"
    assert lock.outlet_scope == "virtual_all_terminal"
    assert lock.selected_outlet_gis_ids == [7, 8]
    assert lock.virtual_outlet_claim_authority is True
    assert lock.baseline_nse == pytest.approx(1.0)
    provenance = json.loads((Path(lock.benchmark_dir) / "outlet_provenance.json").read_text())
    assert provenance["outlet_scope"] == "virtual_all_terminal"
    assert provenance["virtual_outlet_policy"] == "all_terminal_sum"
    assert provenance["virtual_outlet_claim_authority"] is True


def test_lock_benchmark_requires_authority_for_virtual_outlet(tmp_path: Path) -> None:
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)
    obs = pd.Series([1.0], index=pd.to_datetime(["2010-01-01"]), name="obs")

    with pytest.raises(SwatBuilderInputError, match="Virtual all-terminal outlet locks require"):
        lock_benchmark(
            txtinout_dir=txtinout,
            obs_series=obs,
            out_dir=tmp_path / "lock_out",
            basin_id="usgs_virtual_missing_authority",
            outlet_gis_id=1,
            sim_source_file="channel_sd_day.txt",
            virtual_outlet_policy="all_terminal_sum",
        )


def test_calibrate_against_lock_scores_virtual_outlet_lock_with_same_scope(
    monkeypatch, tmp_path: Path
) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0], "sim": [1.0, 2.0]},
        index=pd.date_range("2010-01-01", periods=2, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_virtual",
        locked_at_utc="2026-05-22T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        outlet_policy="all_terminal_sum",
        outlet_scope="virtual_all_terminal",
        selected_outlet_gis_ids=[1, 2],
        virtual_outlet_authority="official_area_match",
        virtual_outlet_claim_authority=True,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=1.0,
        baseline_kge=1.0,
        benchmark_dir=str(benchmark_dir),
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    seen: dict[str, object] = {}

    def fake_make_real_objective(**kwargs):
        seen.update(kwargs)

        def objective(params: dict[str, float]) -> dict[str, float]:
            cn2 = float(params.get("CN2", 75.0))
            return {
                "nse": 0.1 + (cn2 / 1000.0),
                "kge": 0.2 + (cn2 / 1000.0),
                "pbias": 10.0,
            }

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    evidence = calibrate_against_lock(
        lock,
        txt,
        tmp_path / "cal",
        parameters=["CN2"],
        n_evaluations=3,
        calibration_phases=[
            {"phase": "volume", "parameters": ["CN2"], "budget": 3},
        ],
    )

    assert seen["objective_outlet_policy"] == "all_terminal_sum"
    assert seen["outlet_gis_id"] == 1
    assert Path(evidence.best_solution_json).is_file()


def test_verify_calibration_scores_virtual_outlet_lock_with_same_scope(
    monkeypatch, tmp_path: Path
) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0], "sim": [0.9, 2.1]},
        index=pd.date_range("2010-01-01", periods=2, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_virtual",
        locked_at_utc="2026-05-22T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        outlet_policy="all_terminal_sum",
        outlet_scope="virtual_all_terminal",
        selected_outlet_gis_ids=[1, 2],
        virtual_outlet_authority="official_area_match",
        virtual_outlet_claim_authority=True,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.0,
        baseline_kge=0.0,
        benchmark_dir=str(benchmark_dir),
    )
    best_solution = tmp_path / "best_solution.json"
    best_solution.write_text(
        json.dumps({"parameters": {"CN2": 80.0}}) + "\n",
        encoding="utf-8",
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    seen: dict[str, object] = {}

    def fake_make_real_objective(**kwargs):
        seen.update(kwargs)

        def objective(params: dict[str, float]) -> dict[str, float]:
            return {"nse": 0.2, "kge": 0.3, "pbias": 5.0}

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    result = verify_calibration(lock, best_solution, txt, tmp_path / "verify")

    assert seen["objective_outlet_policy"] == "all_terminal_sum"
    assert result.improved is True
    assert Path(result.verification_summary_path).is_file()


def test_volume_gate_requires_finite_pbias_within_threshold() -> None:
    assert _volume_gate_passed({"pbias": 0.0, "nse": 0.5})
    assert _volume_gate_passed({"pbias": -30.0, "nse": 0.5})
    assert not _volume_gate_passed({"pbias": 30.1, "nse": 0.9})
    assert not _volume_gate_passed({"nse": 0.9})


def test_calibrate_against_lock_writes_staged_protocol(monkeypatch, tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0, 3.0], "sim": [1.1, 1.9, 3.2]},
        index=pd.date_range("2010-01-01", periods=3, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_stage_test",
        locked_at_utc="2026-05-13T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.0,
        baseline_kge=0.0,
        benchmark_dir=str(benchmark_dir),
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    calls: list[dict[str, float]] = []

    def fake_make_real_objective(**kwargs):
        def objective(params: dict[str, float]) -> dict[str, float]:
            calls.append(dict(params))
            pbias = 20.0 - (float(params.get("CN2", 75.0)) - 75.0) / 10.0
            nse = 0.1 + float(params.get("LATQ_CO", 0.01)) / 10.0
            kge = 0.2 + float(params.get("PERCO", 0.5)) / 10.0
            return {
                "nse": nse,
                "kge": kge,
                "pbias": pbias,
                "selected_terminal_fraction_of_all_terminal_flow": 0.42,
                "all_terminal_nse": nse + 0.1,
                "all_terminal_kge": kge + 0.1,
                "all_terminal_pbias": pbias + 1.0,
                "all_terminal_volume_gate_passes_diagnostic": 1.0,
            }

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    evidence = calibrate_against_lock(
        lock,
        txt,
        tmp_path / "cal",
        parameters=["CN2", "PERCO", "LATQ_CO", "ESCO"],
        n_evaluations=12,
        calibration_phases=[
            {"phase": "volume", "parameters": ["CN2", "PERCO"], "budget": 4},
            {"phase": "baseflow_subsurface", "parameters": ["LATQ_CO"], "budget": 3},
            {"phase": "peaks_timing", "parameters": ["SURLAG"], "budget": 1},
            {"phase": "kge_nse_finetune", "parameters": ["CN2", "PERCO", "LATQ_CO", "ESCO"], "budget": 4},
        ],
    )

    assert calls
    assert calls[0] == {}
    history = pd.read_csv(evidence.history_csv)
    assert "metric_all_terminal_nse" in history.columns
    assert "metric_all_terminal_pbias" in history.columns
    assert "metric_selected_terminal_fraction_of_all_terminal_flow" in history.columns
    assert history["metric_selected_terminal_fraction_of_all_terminal_flow"].dropna().iloc[0] == pytest.approx(0.42)
    assert list(history["phase"].drop_duplicates()) == [
        "volume",
        "baseflow_subsurface",
        "peaks_timing",
        "kge_nse_finetune",
    ]
    assert set(history.loc[history["phase"] == "volume", "phase_parameters"]) == {"CN2,PERCO"}
    assert set(history.loc[history["phase"] == "baseflow_subsurface", "phase_parameters"]) == {"LATQ_CO"}
    assert set(history.loc[history["phase"] == "peaks_timing", "status"]) == {"skipped_no_eligible_parameters"}
    best = json.loads(Path(evidence.best_solution_json).read_text(encoding="utf-8"))
    assert best["selection_policy"] == "staged_volume_baseflow_peaks_then_nse_kge"
    assert [p["phase"] for p in best["calibration_protocol"]] == [
        "volume",
        "baseflow_subsurface",
        "peaks_timing",
        "kge_nse_finetune",
    ]
    assert "calibration process gates" in best["kge_nse_finetune_gate"]
    assert "calibration process gates pass" in best["calibration_protocol"][-1]["gate"]


def test_phase_candidate_points_keep_dense_probe_for_each_parameter() -> None:
    points = _phase_candidate_points(
        current_params={},
        phase_parameters=["CN2", "PERCO", "PET_CO", "ESCO"],
        param_bounds={
            "CN2": (35.0, 98.0),
            "PERCO": (0.01, 1.0),
            "PET_CO": (0.8, 1.2),
            "ESCO": (0.01, 1.0),
        },
        rng=MagicMock(),
        n_evaluations=7,
    )

    assert len(points) == 28
    assert {"ESCO": 0.01} in points
    assert {"ESCO": 0.505} in points
    assert {"ESCO": 1.0} in points
    assert any(set(point) == {"CN2", "PERCO", "PET_CO", "ESCO"} for point in points)


def test_default_diagnostic_phases_include_soft_surface_runoff_lat_ttime_channel_and_snow_controls() -> None:
    phases = _diagnostic_calibration_phases(
        [
            "CN2",
            "CN3_SWF",
            "PERCO",
            "LATQ_CO",
            "PET_CO",
            "ESCO",
            "EPCO",
            "LAT_TTIME",
            "ALPHA_BF",
            "RCHG_DP",
            "SURLAG",
            "CH_N2",
            "CH_K2",
            "SFTMP",
            "SMTMP",
        ],
        None,
        n_evaluations=20,
    )

    volume = next(row for row in phases if row["phase"] == "volume")
    baseflow = next(row for row in phases if row["phase"] == "baseflow_subsurface")
    peaks = next(row for row in phases if row["phase"] == "peaks_timing")
    assert volume["parameters"] == ["PET_CO", "ESCO", "EPCO", "CN3_SWF", "CN2", "LATQ_CO", "PERCO"]
    assert baseflow["parameters"] == ["LAT_TTIME", "LATQ_CO", "PERCO", "ALPHA_BF", "RCHG_DP"]
    assert peaks["parameters"] == ["SURLAG", "CH_N2", "CH_K2", "SFTMP", "SMTMP"]


def test_score_candidate_rank_nse_kge_prioritizes_skill_after_volume_gate() -> None:
    high_skill = {"nse": -0.0443, "kge": 0.0910, "pbias": -6.17}
    closer_volume_lower_skill = {"nse": -0.0873, "kge": 0.1776, "pbias": 2.26}

    assert _score_candidate(
        high_skill,
        objective="maintain_volume_gate_then_rank_nse_kge",
    ) > _score_candidate(
        closer_volume_lower_skill,
        objective="maintain_volume_gate_then_rank_nse_kge",
    )


def test_score_candidate_rank_nse_kge_prefers_kge_when_nse_is_positive() -> None:
    better_kge = {"nse": 0.0438, "kge": -0.0256, "pbias": -24.41}
    slightly_better_nse_worse_kge = {"nse": 0.0532, "kge": -0.0815, "pbias": -29.55}

    assert _score_candidate(
        better_kge,
        objective="maintain_volume_gate_then_rank_nse_kge",
    ) > _score_candidate(
        slightly_better_nse_worse_kge,
        objective="maintain_volume_gate_then_rank_nse_kge",
    )


def test_score_candidate_volume_phase_preserves_skill_inside_preferred_volume_gate() -> None:
    better_skill_preferred_volume = {"nse": 0.1985, "kge": 0.3278, "pbias": -13.48}
    near_zero_pbias_low_skill = {"nse": 0.1043, "kge": 0.0437, "pbias": -4.24}

    assert _score_candidate(
        better_skill_preferred_volume,
        objective="minimize_abs_pbias_then_kge_nse",
    ) > _score_candidate(
        near_zero_pbias_low_skill,
        objective="minimize_abs_pbias_then_kge_nse",
    )


def test_score_candidate_volume_phase_prefers_preferred_volume_tier() -> None:
    preferred_volume_modest_skill = {"nse": 0.05, "kge": 0.10, "pbias": 14.9}
    minimum_volume_better_skill = {"nse": 0.25, "kge": 0.35, "pbias": 25.0}

    assert _score_candidate(
        preferred_volume_modest_skill,
        objective="minimize_abs_pbias_then_kge_nse",
    ) > _score_candidate(
        minimum_volume_better_skill,
        objective="minimize_abs_pbias_then_kge_nse",
    )


def test_score_candidate_rank_nse_kge_requires_physical_gate_when_available() -> None:
    high_skill_physical_failure = {
        "nse": 0.50,
        "kge": 0.75,
        "pbias": 1.0,
        "physical_gate_passed": 0.0,
    }
    lower_skill_physical_pass = {
        "nse": 0.10,
        "kge": 0.45,
        "pbias": 5.0,
        "physical_gate_passed": 1.0,
    }

    assert _score_candidate(
        high_skill_physical_failure,
        objective="maintain_volume_gate_then_rank_nse_kge",
    ) == float("-inf")
    assert _score_candidate(
        lower_skill_physical_pass,
        objective="maintain_volume_gate_then_rank_nse_kge",
    ) > float("-inf")


def test_score_candidate_rank_nse_kge_uses_process_gate_before_skill_gate() -> None:
    skill_limited_process_valid = {
        "nse": -0.05,
        "kge": 0.20,
        "pbias": 5.0,
        "physical_gate_passed": 0.0,
        "calibration_process_gate_passed": 1.0,
    }
    process_failure = {
        "nse": 0.50,
        "kge": 0.75,
        "pbias": 5.0,
        "physical_gate_passed": 0.0,
        "calibration_process_gate_passed": 0.0,
    }

    assert _score_candidate(
        skill_limited_process_valid,
        objective="maintain_volume_gate_then_rank_nse_kge",
    ) > float("-inf")
    assert _score_candidate(
        process_failure,
        objective="maintain_volume_gate_then_rank_nse_kge",
    ) == float("-inf")


def test_calibrate_against_lock_writes_history_before_phase_blocker(monkeypatch, tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0, 3.0], "sim": [1.1, 1.9, 3.2]},
        index=pd.date_range("2010-01-01", periods=3, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_stage_fail",
        locked_at_utc="2026-05-13T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.0,
        baseline_kge=0.0,
        benchmark_dir=str(benchmark_dir),
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    def fake_make_real_objective(**kwargs):
        work_root = Path(kwargs["work_root"])

        def objective(params: dict[str, float]) -> dict[str, float]:
            trace = work_root / f"{params_hash(params)}_objective_trace.json"
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.write_text(
                json.dumps(
                    {
                        "params": params,
                        "metrics": {"nse": 0.5, "kge": 0.5, "pbias": 80.0, "physical_gate_passed": 0.0},
                        "candidate_physical_gate": {
                            "pass": False,
                            "condition_codes": ["VOLUME_BIAS"],
                            "dominant_blocker": "VOLUME_BIAS",
                            "calibration_process_gate_pass": False,
                            "calibration_process_condition_codes": ["VOLUME_BIAS"],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return {
                "nse": 0.5,
                "kge": 0.5,
                "pbias": 80.0,
                "physical_gate_passed": 0.0,
                "calibration_process_gate_passed": 0.0,
            }

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    with pytest.raises(SwatBuilderPipelineError) as exc:
        calibrate_against_lock(
            lock,
            txt,
            tmp_path / "cal",
            parameters=["CN2"],
            n_evaluations=3,
            calibration_phases=[{"phase": "volume", "parameters": ["CN2"], "budget": 3}],
        )

    history_csv = Path(exc.value.context["history_csv"])
    assert history_csv.exists()
    assert (
        exc.value.context["promotion_gate"]
        == "abs(pbias) <= 30 and candidate calibration process gates pass"
    )
    history = pd.read_csv(history_csv)
    # DDS: 1 seed evaluation + budget=3 iterations = 4 total
    assert len(history) == 4
    assert pd.isna(history.iloc[0]["param_CN2"])
    assert set(history["volume_gate_passed"]) == {False}
    assert set(history["calibration_process_gate_passed"]) == {False}
    assert set(history["calibration_process_condition_codes"]) == {"VOLUME_BIAS"}
    assert set(history["physical_gate_condition_codes"]) == {"VOLUME_BIAS"}
    assert set(history["physical_gate_dominant_blocker"]) == {"VOLUME_BIAS"}


def test_rank_nse_kge_phase_blocker_reports_process_gate(monkeypatch, tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0, 3.0], "sim": [1.1, 1.9, 3.2]},
        index=pd.date_range("2010-01-01", periods=3, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_rank_fail",
        locked_at_utc="2026-05-13T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.0,
        baseline_kge=0.0,
        benchmark_dir=str(benchmark_dir),
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    def fake_make_real_objective(**kwargs):
        work_root = Path(kwargs["work_root"])

        def objective(params: dict[str, float]) -> dict[str, float]:
            trace = work_root / f"{params_hash(params)}_objective_trace.json"
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.write_text(
                json.dumps(
                    {
                        "params": params,
                        "metrics": {
                            "nse": 0.4,
                            "kge": 0.5,
                            "pbias": 5.0,
                            "physical_gate_passed": 0.0,
                            "calibration_process_gate_passed": 0.0,
                        },
                        "candidate_physical_gate": {
                            "pass": False,
                            "condition_codes": ["ET_DOMINATED"],
                            "dominant_blocker": "ET_DOMINATED",
                            "calibration_process_gate_pass": False,
                            "calibration_process_condition_codes": ["ET_DOMINATED"],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return {
                "nse": 0.4,
                "kge": 0.5,
                "pbias": 5.0,
                "physical_gate_passed": 0.0,
                "calibration_process_gate_passed": 0.0,
            }

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    with pytest.raises(SwatBuilderPipelineError) as exc:
        calibrate_against_lock(
            lock,
            txt,
            tmp_path / "cal",
            parameters=["CN2"],
            n_evaluations=3,
            calibration_phases=[
                {
                    "phase": "kge_nse_finetune",
                    "parameters": ["CN2"],
                    "budget": 3,
                    "objective": "maintain_volume_gate_then_rank_nse_kge",
                }
            ],
        )

    assert (
        exc.value.context["promotion_gate"]
        == "abs(pbias) <= 30 and candidate calibration process gates pass"
    )


def test_kge_nse_phase_requires_prior_process_gate_when_available(monkeypatch, tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0, 3.0], "sim": [1.1, 1.9, 3.2]},
        index=pd.date_range("2010-01-01", periods=3, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_rank_entry_fail",
        locked_at_utc="2026-05-13T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.0,
        baseline_kge=0.0,
        benchmark_dir=str(benchmark_dir),
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    def fake_make_real_objective(**kwargs):
        work_root = Path(kwargs["work_root"])

        def objective(params: dict[str, float]) -> dict[str, float]:
            trace = work_root / f"{params_hash(params)}_objective_trace.json"
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.write_text(
                json.dumps(
                    {
                        "params": params,
                        "metrics": {
                            "nse": 0.4,
                            "kge": 0.5,
                            "pbias": 5.0,
                            "physical_gate_passed": 0.0,
                            "calibration_process_gate_passed": 0.0,
                        },
                        "candidate_physical_gate": {
                            "pass": False,
                            "condition_codes": ["ET_DOMINATED"],
                            "dominant_blocker": "ET_DOMINATED",
                            "calibration_process_gate_pass": False,
                            "calibration_process_condition_codes": ["ET_DOMINATED"],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return {
                "nse": 0.4,
                "kge": 0.5,
                "pbias": 5.0,
                "physical_gate_passed": 0.0,
                "calibration_process_gate_passed": 0.0,
            }

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    with pytest.raises(SwatBuilderPipelineError) as exc:
        calibrate_against_lock(
            lock,
            txt,
            tmp_path / "cal",
            parameters=["CN2"],
            n_evaluations=3,
            calibration_phases=[
                {
                    "phase": "volume",
                    "parameters": ["CN2"],
                    "budget": 3,
                    "objective": "minimize_abs_pbias_then_kge_nse",
                },
                {
                    "phase": "kge_nse_finetune",
                    "parameters": ["CN2"],
                    "budget": 3,
                    "objective": "maintain_volume_gate_then_rank_nse_kge",
                },
            ],
        )

    assert (
        exc.value.context["promotion_gate"]
        == "prior abs(pbias) <= 30 candidate must pass calibration process gates before KGE/NSE finetune"
    )
    history = pd.read_csv(exc.value.context["history_csv"])
    final_phase = history.loc[history["phase"] == "kge_nse_finetune"]
    assert list(final_phase["status"]) == ["blocked_preceding_process_gate"]
    assert set(history.loc[history["phase"] == "volume", "status"]) == {"evaluated"}
    assert set(history.loc[history["phase"] == "volume", "volume_gate_passed"]) == {True}
    assert set(history.loc[history["phase"] == "volume", "calibration_process_gate_passed"]) == {False}


def test_verify_calibration_records_kge_only_improvement(monkeypatch, tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0, 3.0], "sim": [1.1, 1.9, 3.2]},
        index=pd.date_range("2010-01-01", periods=3, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_kge_improve",
        locked_at_utc="2026-05-13T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.25,
        baseline_kge=0.10,
        benchmark_dir=str(benchmark_dir),
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    best_json = tmp_path / "best_solution.json"
    best_json.write_text(
        json.dumps({"parameters": {"CN2": 70.0}, "metrics": {"nse": 0.20, "kge": 0.45, "pbias": 5.0}}),
        encoding="utf-8",
    )

    captured_kwargs: dict[str, object] = {}

    def fake_make_real_objective(**kwargs):
        captured_kwargs.update(kwargs)
        return lambda params: {"nse": 0.20, "kge": 0.45, "pbias": 5.0}

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    result = verify_calibration(lock, best_json, txt, tmp_path / "cal", parameter_mode="full")

    assert result.improved is True
    assert result.delta_nse < 0.0
    assert result.delta_kge > 0.0
    assert result.improvement_basis == "kge"
    assert result.fresh_outputs is True
    assert result.fresh_output_policy == "force_fresh_real_engine_objective"
    assert captured_kwargs["keep_workdirs"] is True
    assert captured_kwargs["force_fresh"] is True
    persisted = json.loads(Path(result.verification_summary_path).read_text(encoding="utf-8"))
    assert persisted["improvement_basis"] == "kge"
    assert persisted["fresh_outputs"] is True


def test_screen_parameters_against_lock_writes_basin_specific_artifact(monkeypatch, tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    pd.DataFrame(
        {"obs": [1.0, 2.0, 3.0], "sim": [1.1, 1.9, 3.2]},
        index=pd.date_range("2010-01-01", periods=3, freq="D"),
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_sens",
        locked_at_utc="2026-05-13T00:00:00+00:00",
        alignment_sha256="alignment",
        metrics_sha256="metrics",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.10,
        baseline_kge=0.10,
        benchmark_dir=str(benchmark_dir),
    )
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    calls: list[dict[str, float]] = []

    def fake_make_real_objective(**kwargs):
        def objective(params: dict[str, float]) -> dict[str, float]:
            calls.append(dict(params))
            cn2 = float(params.get("CN2", 75.0))
            return {"nse": 0.10 + (cn2 - 75.0) / 100.0, "kge": 0.20, "pbias": 5.0}

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    evidence = screen_parameters_against_lock(
        lock,
        txt,
        tmp_path / "cal",
        parameters=["CN2"],
        parameter_mode="full",
    )

    assert calls
    assert evidence.basis == "basin_specific"
    assert evidence.parameters[0]["activity_class"] == "active"
    payload = json.loads(Path(evidence.json_path).read_text(encoding="utf-8"))
    assert payload["basis"] == "basin_specific"
    assert payload["parameters"][0]["evidence"]["tested"] is True
    assert Path(evidence.markdown_path).exists()
    progress = json.loads(
        (tmp_path / "cal" / "sensitivity_screen_locked" / "sensitivity_screen_progress.json").read_text(
            encoding="utf-8"
        )
    )
    assert progress["status"] == "complete"
    assert progress["completed_parameters"] == 1
    assert progress["total_parameters"] == 1
    assert progress["parameters"][0]["parameter"] == "CN2"


# ---------------------------------------------------------------------------
# _resolve_lock
# ---------------------------------------------------------------------------


def test_resolve_lock_from_benchmark_lock_object(tmp_path, obs_series):
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock",
        basin_id="usgs_resolve_test",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )
    resolved = _resolve_lock(lock)
    assert resolved.basin_id == lock.basin_id


def test_resolve_lock_from_json_path(tmp_path, obs_series):
    txtinout = tmp_path / "TxtInOut"
    txtinout.mkdir()
    _make_fake_sim_file(txtinout)
    _make_chandeg_con(txtinout)

    lock = lock_benchmark(
        txtinout_dir=txtinout,
        obs_series=obs_series,
        out_dir=tmp_path / "lock",
        basin_id="usgs_path_test",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
    )
    json_path = Path(lock.benchmark_dir) / "benchmark_lock.json"
    resolved = _resolve_lock(json_path)
    assert resolved.basin_id == "usgs_path_test"


# ---------------------------------------------------------------------------
# build_readiness_table
# ---------------------------------------------------------------------------


def _make_verification_summary(root: Path, basin: str, improved: bool) -> None:
    lock_dir = root / basin
    lock_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "basin_id": basin,
        "benchmark_nse": 0.1,
        "benchmark_kge": 0.0,
        "verified_nse": 0.25 if improved else 0.05,
        "verified_kge": 0.15 if improved else -0.05,
        "delta_nse": 0.15 if improved else -0.05,
        "delta_kge": 0.15 if improved else -0.05,
        "improved": improved,
        "verification_dir": str(lock_dir / "verification"),
        "verification_summary_path": str(lock_dir / "verification_summary.json"),
    }
    (lock_dir / "verification_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def _make_benchmark_lock(root: Path, basin: str) -> None:
    bdir = root / basin / "benchmark"
    bdir.mkdir(parents=True, exist_ok=True)
    lock = {
        "basin_id": basin,
        "locked_at_utc": "2026-04-24T00:00:00+00:00",
        "alignment_sha256": "abc123",
        "metrics_sha256": "def456",
        "provenance_sha256": None,
        "outlet_gis_id": 1,
        "outlet_policy": "strict",
        "sim_source_file": "basin_sd_cha_day.txt",
        "git_sha": None,
        "baseline_nse": 0.1,
        "baseline_kge": 0.0,
        "benchmark_dir": str(bdir),
    }
    (bdir / "benchmark_lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def test_build_readiness_table_finds_verified_basins(tmp_path):
    """Readiness table must find and classify verified basins."""
    _make_verification_summary(tmp_path, "usgs_01547700", improved=True)
    _make_verification_summary(tmp_path, "usgs_03339000", improved=False)

    rows = build_readiness_table(tmp_path)
    assert len(rows) == 2
    statuses = {r.basin_id: r.verification_status for r in rows}
    assert statuses["usgs_01547700"] == "verified_improved"
    assert statuses["usgs_03339000"] == "verified_no_improvement"


def test_build_readiness_table_pending_locks(tmp_path):
    """Basins with a lock but no verification must appear as PENDING."""
    _make_benchmark_lock(tmp_path, "usgs_pending_01")
    rows = build_readiness_table(tmp_path)
    assert len(rows) >= 1
    pending = [r for r in rows if r.basin_id == "usgs_pending_01"]
    assert len(pending) == 1
    assert pending[0].verification_status == "locked_no_verification"


def test_build_readiness_table_empty_root(tmp_path):
    """Empty directory must return an empty list without raising."""
    rows = build_readiness_table(tmp_path / "nonexistent")
    assert rows == []


def test_build_readiness_table_writes_markdown(tmp_path):
    """out_md parameter must produce a readable markdown file."""
    _make_verification_summary(tmp_path, "usgs_01547700", improved=True)
    out_md = tmp_path / "readiness_table.md"
    build_readiness_table(tmp_path, out_md=out_md)
    assert out_md.exists()
    content = out_md.read_text(encoding="utf-8")
    assert "usgs_01547700" in content
    assert "PASS" in content


def test_write_readiness_markdown_structure(tmp_path):
    """Markdown output must include required headers and data rows."""
    rows = [
        ReadinessRow(
            basin_id="usgs_X",
            lock_dir="/some/dir",
            baseline_nse=0.12,
            baseline_kge=-0.05,
            calibrated_nse=0.25,
            calibrated_kge=0.10,
            delta_nse=0.13,
            delta_kge=0.15,
            improved=True,
            verification_status="verified_improved",
        ),
        ReadinessRow(
            basin_id="usgs_Y",
            lock_dir="/other/dir",
            baseline_nse=0.05,
            baseline_kge=-0.10,
            verification_status="locked_no_verification",
        ),
    ]
    out = tmp_path / "table.md"
    _write_readiness_markdown(out, rows)
    content = out.read_text(encoding="utf-8")
    assert "usgs_X" in content
    assert "PASS" in content
    assert "PENDING" in content


# ---------------------------------------------------------------------------
# Split-sample (Klemeš) validation
# ---------------------------------------------------------------------------


def _make_lock_and_alignment(tmp_path: Path, n_days: int = 120) -> tuple:
    """Create a benchmark lock with a synthetic n_days alignment CSV."""
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    dates = pd.date_range("2010-01-01", periods=n_days, freq="D")
    pd.DataFrame(
        {"obs": [float(i % 5 + 1) for i in range(n_days)], "sim": [float(i % 5 + 1.1) for i in range(n_days)]},
        index=dates,
    ).to_csv(benchmark_dir / "alignment.csv")
    lock = BenchmarkLock(
        basin_id="usgs_split_test",
        locked_at_utc="2026-05-13T00:00:00+00:00",
        alignment_sha256="x",
        metrics_sha256="y",
        outlet_gis_id=1,
        sim_source_file="channel_sd_day.txt",
        baseline_nse=0.0,
        baseline_kge=0.0,
        benchmark_dir=str(benchmark_dir),
    )
    return lock, benchmark_dir


def test_split_sample_validation_fields_populated(monkeypatch, tmp_path: Path) -> None:
    """When validation_period is given, CalibrationEvidence carries validation metrics."""
    lock, _ = _make_lock_and_alignment(tmp_path, n_days=120)
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    call_log: list[dict] = []

    def fake_make_real_objective(**kwargs):
        obs = kwargs["observed_series"]
        call_log.append({"n_obs": len(obs), "work_root": str(kwargs["work_root"])})

        def objective(params: dict[str, float]) -> dict[str, float]:
            # Always returns a feasible + passing result
            trace = Path(kwargs["work_root"]) / f"{params_hash(params)}_objective_trace.json"
            trace.parent.mkdir(parents=True, exist_ok=True)
            result = {"nse": 0.6, "kge": 0.55, "pbias": 12.0}
            trace.write_text(json.dumps({"params": params, "metrics": result, "candidate_physical_gate": {
                "pass": True, "condition_codes": [], "dominant_blocker": None,
                "calibration_process_gate_pass": True, "calibration_process_condition_codes": [],
            }}) + "\n", encoding="utf-8")
            return result

        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    evidence = calibrate_against_lock(
        lock,
        txt,
        tmp_path / "cal",
        parameters=["CN2"],
        n_evaluations=5,
        calibration_phases=[{"phase": "volume", "parameters": ["CN2"], "budget": 5}],
        # validation = last 30 days of 120-day alignment (2010-04-01..04-30) → training = first 90 days
        validation_period=("2010-04-01", "2010-04-30"),
    )

    # make_real_objective should have been called twice: once for calibration, once for validation
    assert len(call_log) == 2
    # Validation obs should be shorter than training obs (30 vs 90)
    assert call_log[1]["n_obs"] < call_log[0]["n_obs"]
    # "validation_eval" must appear in the second call's work_root
    assert "validation_eval" in call_log[1]["work_root"]

    assert evidence.validation_period == ("2010-04-01", "2010-04-30")
    assert evidence.validation_nse is not None
    assert evidence.validation_kge is not None
    assert evidence.validation_pbias is not None
    # Our fake objective always returns pbias=12.0, so volume gate passes
    assert evidence.validation_transfer_passed is True

    # Validation fields must also be present in best_solution.json
    best = json.loads(Path(evidence.best_solution_json).read_text(encoding="utf-8"))
    assert "validation_period" in best
    assert best["validation_transfer_passed"] is True

    # Summary markdown must mention the Klemeš section
    summary = Path(evidence.summary_md).read_text(encoding="utf-8")
    assert "Klemeš" in summary
    assert "Transfer passed" in summary

    assert evidence.validation_period == ("2010-04-01", "2010-04-30")


def test_multi_seed_ensemble_fields_populated(monkeypatch, tmp_path: Path) -> None:
    """With dds_n_seeds=3, CalibrationEvidence carries ensemble NSE/KGE spread."""
    lock, _ = _make_lock_and_alignment(tmp_path, n_days=120)
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    def fake_make_real_objective(**kwargs):
        def objective(params: dict[str, float]) -> dict[str, float]:
            trace = Path(kwargs["work_root"]) / f"{params_hash(params)}_objective_trace.json"
            trace.parent.mkdir(parents=True, exist_ok=True)
            result = {"nse": 0.55, "kge": 0.50, "pbias": 8.0}
            trace.write_text(json.dumps({"params": params, "metrics": result, "candidate_physical_gate": {
                "pass": True, "condition_codes": [], "dominant_blocker": None,
                "calibration_process_gate_pass": True, "calibration_process_condition_codes": [],
            }}) + "\n", encoding="utf-8")
            return result
        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    evidence = calibrate_against_lock(
        lock,
        txt,
        tmp_path / "cal",
        parameters=["CN2"],
        n_evaluations=5,
        calibration_phases=[{"phase": "volume", "parameters": ["CN2"], "budget": 5}],
        dds_n_seeds=3,
    )

    assert evidence.ensemble_n_seeds == 3
    # With 3 seeds (all returning same metrics), spread should be 0
    assert evidence.ensemble_nse_spread is not None
    assert evidence.ensemble_kge_spread is not None
    assert len(evidence.ensemble_best_nse_per_seed) >= 1
    assert len(evidence.ensemble_best_kge_per_seed) >= 1

    best = json.loads(Path(evidence.best_solution_json).read_text(encoding="utf-8"))
    assert "ensemble_n_seeds" in best
    assert "ensemble_nse_spread" in best


def test_split_sample_raises_on_too_short_validation_period(monkeypatch, tmp_path: Path) -> None:
    """A validation_period with <30 observed days raises SwatBuilderInputError."""
    lock, _ = _make_lock_and_alignment(tmp_path, n_days=120)
    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    def fake_make_real_objective(**kwargs):
        def objective(params):
            return {"nse": 0.6, "kge": 0.55, "pbias": 12.0}
        return objective

    monkeypatch.setattr("swatplus_builder.calibration.real_engine.make_real_objective", fake_make_real_objective)

    with pytest.raises(SwatBuilderInputError, match="fewer than 30 observed days"):
        calibrate_against_lock(
            lock,
            txt,
            tmp_path / "cal",
            parameters=["CN2"],
            n_evaluations=5,
            calibration_phases=[{"phase": "volume", "parameters": ["CN2"], "budget": 5}],
            validation_period=("2010-03-01", "2010-03-05"),  # only 5 days
        )
