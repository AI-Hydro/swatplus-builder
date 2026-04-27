"""Tests for physical realism audit module (output/realism.py).

No SWAT+ binary required — all tests operate on alignment CSV files only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swatplus_builder.output.realism import (
    CalValSplit,
    PeriodMetrics,
    RealismAudit,
    audit_realism,
    run_realism_audit,
    split_cal_val,
    _nse,
    _kge,
    _pbias,
    _bfi,
    _detect_pathologies,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_alignment_csv(path: Path, obs: list[float], sim: list[float],
                         start: str = "2015-01-01") -> Path:
    idx = pd.date_range(start=start, periods=len(obs), freq="D")
    pd.DataFrame({"obs": obs, "sim": sim}, index=idx).to_csv(path, index_label="date")
    return path


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

class TestMetricHelpers:
    def test_nse_perfect(self):
        a = np.array([1.0, 2.0, 3.0, 4.0])
        assert _nse(a, a) == pytest.approx(1.0)

    def test_nse_mean_predictor_is_zero(self):
        a = np.array([1.0, 2.0, 3.0, 4.0])
        mean_pred = np.full_like(a, a.mean())
        assert _nse(a, mean_pred) == pytest.approx(0.0, abs=1e-10)

    def test_kge_perfect(self):
        a = np.array([1.0, 2.0, 3.0, 4.0])
        assert _kge(a, a) == pytest.approx(1.0)

    def test_pbias_overestimate(self):
        obs = np.array([1.0, 2.0, 3.0])
        sim = np.array([1.5, 3.0, 4.5])  # 50% over
        assert _pbias(obs, sim) == pytest.approx(50.0, rel=1e-3)

    def test_bfi_all_baseflow(self):
        # Constant flow → BFI ≈ 1
        bfi = _bfi(np.ones(200))
        assert bfi > 0.99

    def test_bfi_impulse(self):
        # Spike followed by zeros → very low BFI
        q = np.zeros(200)
        q[100] = 100.0
        bfi = _bfi(q)
        assert bfi < 0.5


# ---------------------------------------------------------------------------
# Cal/Val split
# ---------------------------------------------------------------------------

class TestCalValSplit:
    def _make_df(self, n: int = 365) -> pd.DataFrame:
        idx = pd.date_range("2015-01-01", periods=n, freq="D")
        return pd.DataFrame({"obs": np.random.rand(n), "sim": np.random.rand(n)}, index=idx)

    def test_fraction_split_default_70(self):
        df = self._make_df(100)
        cal, val, split = split_cal_val(df)
        assert split.cal_n == 70
        assert split.val_n == 30

    def test_year_split(self):
        df = self._make_df(730)  # 2 years
        cal, val, split = split_cal_val(df, split_year=2016)
        assert split.split_year == 2016
        assert all(cal.index < pd.Timestamp("2016-01-01"))
        assert all(val.index >= pd.Timestamp("2016-01-01"))

    def test_empty_df_returns_empty(self):
        df = pd.DataFrame({"obs": [], "sim": []})
        cal, val, split = split_cal_val(df)
        assert split.cal_n == 0
        assert split.val_n == 0


# ---------------------------------------------------------------------------
# audit_realism
# ---------------------------------------------------------------------------

class TestAuditRealism:
    def test_basic_structure(self, tmp_path):
        csv = _make_alignment_csv(tmp_path / "alignment.csv",
                                   obs=[1.0] * 100, sim=[1.2] * 100)
        audit = audit_realism(csv, basin_id="test_basin")
        assert audit.basin_id == "test_basin"
        assert audit.period_full.n_days == 100
        assert audit.realism_verdict in {
            "benchmark_grade", "improving", "improving_with_pathologies",
            "below_benchmark", "pathological", "insufficient_data",
        }

    def test_detects_volume_bias_over(self, tmp_path):
        # sim is 50% over obs → PBIAS ≈ +50%
        obs = [1.0] * 200
        sim = [1.5] * 200
        csv = _make_alignment_csv(tmp_path / "align.csv", obs, sim)
        audit = audit_realism(csv)
        assert any("Volume bias" in p or "over" in p.lower() for p in audit.pathologies)

    def test_detects_volume_bias_under(self, tmp_path):
        obs = [2.0] * 200
        sim = [1.0] * 200  # 50% under
        csv = _make_alignment_csv(tmp_path / "align.csv", obs, sim)
        audit = audit_realism(csv)
        assert any("underestimates" in p or "under" in p.lower() for p in audit.pathologies)

    def test_detects_baseflow_overestimation(self, tmp_path):
        # Constant low flow (high BFI) vs spiky obs (lower BFI)
        rng = np.random.default_rng(42)
        obs = np.abs(rng.exponential(1.0, 200))  # spiky → lower BFI
        sim = np.ones(200) * obs.mean()           # constant → high BFI
        csv = _make_alignment_csv(tmp_path / "align.csv", obs.tolist(), sim.tolist())
        audit = audit_realism(csv)
        assert audit.period_full.bfi_ratio is not None
        # BFI ratio should be > 1 (constant sim has higher BFI than spiky obs)
        assert audit.period_full.bfi_ratio > 1.0

    def test_cal_val_split_created(self, tmp_path):
        csv = _make_alignment_csv(tmp_path / "align.csv",
                                   obs=[1.0] * 365, sim=[1.0] * 365)
        audit = audit_realism(csv, cal_fraction=0.7)
        assert audit.cal_val_split is not None
        assert audit.period_cal is not None
        assert audit.period_val is not None

    def test_missing_columns_raises(self, tmp_path):
        bad = tmp_path / "bad.csv"
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}, index=pd.date_range("2015-01-01", periods=2)).to_csv(bad)
        with pytest.raises(ValueError, match="obs.*sim"):
            audit_realism(bad)

    def test_nse_matches_standalone_metric(self, tmp_path):
        rng = np.random.default_rng(7)
        obs = rng.normal(2.0, 0.5, 200).tolist()
        sim = (rng.normal(2.0, 0.5, 200) * 1.1).tolist()
        csv = _make_alignment_csv(tmp_path / "align.csv", obs, sim)
        audit = audit_realism(csv)
        expected_nse = _nse(np.array(obs), np.array(sim))
        assert audit.period_full.nse == pytest.approx(expected_nse, rel=1e-5)


# ---------------------------------------------------------------------------
# run_realism_audit (multi-basin)
# ---------------------------------------------------------------------------

class TestRunRealismAudit:
    def test_writes_json_and_markdown(self, tmp_path):
        csv1 = _make_alignment_csv(tmp_path / "b1.csv", [1.0] * 100, [1.1] * 100)
        csv2 = _make_alignment_csv(tmp_path / "b2.csv", [2.0] * 100, [1.8] * 100)
        out = tmp_path / "out"
        run_realism_audit([("basin_a", csv1), ("basin_b", csv2)], out_dir=out)
        assert (out / "realism_audit.json").exists()
        assert (out / "realism_audit.md").exists()

    def test_json_contains_both_basins(self, tmp_path):
        csv = _make_alignment_csv(tmp_path / "align.csv", [1.0] * 100, [1.0] * 100)
        out = tmp_path / "out"
        results = run_realism_audit([("b1", csv), ("b2", csv)], out_dir=out)
        assert len(results) == 2
        data = json.loads((out / "realism_audit.json").read_text())
        assert data["basin_count"] == 2

    def test_markdown_contains_verdict(self, tmp_path):
        rng = np.random.default_rng(99)
        obs = (rng.normal(2.0, 0.3, 200) + 0.1).tolist()
        sim = (np.array(obs) * 1.01).tolist()
        csv = _make_alignment_csv(tmp_path / "align.csv", obs=obs, sim=sim)
        out = tmp_path / "out"
        run_realism_audit([("perfect_basin", csv)], out_dir=out)
        md = (out / "realism_audit.md").read_text()
        assert "perfect_basin" in md
        valid_verdicts = {
            "benchmark_grade", "improving", "improving_with_pathologies",
            "below_benchmark", "pathological", "insufficient_data",
        }
        assert any(v in md for v in valid_verdicts)

    def test_survives_bad_csv_path(self, tmp_path):
        out = tmp_path / "out"
        results = run_realism_audit(
            [("missing_basin", tmp_path / "no_such_file.csv")],
            out_dir=out,
        )
        assert len(results) == 1
        assert results[0].realism_verdict == "audit_failed"
        assert any("audit_error" in p for p in results[0].pathologies)
