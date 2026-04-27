from __future__ import annotations

from pathlib import Path

import pandas as pd

from swatplus_builder.diagnostics import diagnose, write_diagnostics_report


def _write_alignment(path: Path, obs: list[float], sim: list[float]) -> None:
    idx = pd.date_range("2015-01-01", periods=len(obs), freq="D")
    df = pd.DataFrame({"obs": obs, "sim": sim}, index=idx)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)


def test_diagnose_peak_lag_and_volume_bias(tmp_path: Path) -> None:
    obs = [0.1, 0.2, 1.5, 1.0, 0.5, 0.3, 0.2]
    sim = [0.1, 0.2, 0.3, 0.4, 1.8, 1.2, 0.9]  # delayed and high volume
    p = tmp_path / "alignment.csv"
    _write_alignment(p, obs, sim)
    out = diagnose(p)
    symptoms = [d.symptom for d in out]
    assert any("Peak timing lag" in s for s in symptoms)
    assert any("volume bias" in s.lower() for s in symptoms)


def test_diagnose_flat_hydrograph_rule(tmp_path: Path) -> None:
    obs = [0.2, 0.25, 0.3, 0.28, 0.26, 0.24, 0.22]
    sim = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]
    p = tmp_path / "alignment.csv"
    _write_alignment(p, obs, sim)
    out = diagnose(p)
    assert any("near-flat" in d.symptom for d in out)


def test_write_diagnostics_report(tmp_path: Path) -> None:
    obs = [0.1, 0.2, 1.0, 0.8, 0.4, 0.3, 0.2]
    sim = [0.1, 0.2, 0.3, 0.4, 1.2, 0.9, 0.8]
    p = tmp_path / "alignment.csv"
    _write_alignment(p, obs, sim)
    diags = diagnose(p)
    out_md = write_diagnostics_report(diags, tmp_path / "diagnostics.md")
    assert out_md.exists()
    txt = out_md.read_text(encoding="utf-8")
    assert "Calibration Diagnostics" in txt
