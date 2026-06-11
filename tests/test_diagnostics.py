from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from swatplus_builder.diagnostics import diagnose, write_diagnostics_json_report, write_diagnostics_report


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


def test_diagnose_uses_annual_peak_window_not_cross_year_global_peak(tmp_path: Path) -> None:
    idx = pd.date_range("2015-01-01", periods=730, freq="D")
    obs = [1.0] * len(idx)
    sim = [1.0] * len(idx)
    for offset in range(40):
        obs[90 + offset] = 10.0
        sim[91 + offset] = 3.0
        obs[500 + offset] = 20.0
        sim[501 + offset] = 4.0
    sim[101] = 6.0
    p = tmp_path / "alignment.csv"
    pd.DataFrame({"obs": obs, "sim": sim}, index=idx).to_csv(p)

    out = diagnose(p)

    assert not any(d.symptom == "Peak timing lag exceeds 1 day" for d in out)
    peak = next(
        d
        for d in out
        if d.symptom == "High-flow peaks are attenuated relative to observed events"
    )
    assert peak.suggested_parameters == ["SURLAG", "CN2", "CH_N2", "CH_K2"]
    assert peak.evidence_metrics["method"] == "observed_top_decile_days"
    assert peak.evidence_metrics["top_decile_sim_obs_flow_ratio"] < 0.60
    assert peak.evidence_metrics["top_decile_day_count"] > 0


def test_high_flow_attenuation_exposes_channel_routing_controls(tmp_path: Path) -> None:
    idx = pd.date_range("2015-01-01", periods=120, freq="D")
    obs = [1.0] * len(idx)
    sim = [1.0] * len(idx)
    for offset in range(12):
        obs[40 + offset] = 10.0
        sim[40 + offset] = 3.0
    p = tmp_path / "alignment.csv"
    pd.DataFrame({"obs": obs, "sim": sim}, index=idx).to_csv(p)

    payload_path = write_diagnostics_json_report(diagnose(p), tmp_path / "diagnostics.json")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    high_flow = next(
        flag
        for flag in payload["diagnostic_flags"]
        if flag["symptom"] == "High-flow peaks are attenuated relative to observed events"
    )

    assert {"CH_N2", "CH_K2"}.issubset(high_flow["parameter_governance"]["governed_parameters"])
    assert any(
        alt["option"] == "screen_channel_routing_attenuation_controls"
        and alt["parameters"] == ["CH_N2", "CH_K2"]
        for alt in payload["source_backed_alternatives"]
    )


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


def test_write_diagnostics_json_report(tmp_path: Path) -> None:
    p = tmp_path / "alignment.csv"
    _write_alignment(p, [0.1, 0.2, 1.0, 0.8, 0.4, 0.3, 0.2], [0.1, 0.2, 0.3, 0.4, 1.2, 0.9, 0.8])
    diags = diagnose(p)

    out_json = write_diagnostics_json_report(diags, tmp_path / "diagnostics.json")

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["diagnostic_count"] == len(diags)
    assert payload["diagnostic_flags"]
    assert "evidence_metrics" in payload["diagnostic_flags"][0]
    assert payload["next_actions"]
    assert payload["source_backed_alternatives"]
    assert payload["recommended_probe_order"]
    assert payload["recommended_probe_order"][0]["diagnostic"]


def test_skill_diagnostics_include_kge_component_deficit(tmp_path: Path) -> None:
    p = tmp_path / "alignment.csv"
    _write_alignment(
        p,
        [1.0, 2.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.4, 0.3, 0.2],
        [0.5, 0.6, 1.2, 1.0, 0.8, 0.6, 0.5, 0.5, 0.4, 0.3],
    )

    payload_path = write_diagnostics_json_report(diagnose(p), tmp_path / "diagnostics.json")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    kge_flag = next(
        flag
        for flag in payload["diagnostic_flags"]
        if str(flag["symptom"]).startswith("KGE below research threshold")
    )

    assert kge_flag["evidence_metrics"]["method"] == "kge_2009_components"
    assert {"r", "alpha", "beta", "kge"}.issubset(kge_flag["evidence_metrics"])
    assert kge_flag["parameter_governance"]["status"] == "governed"
    assert payload["skill_limitation_class"] == "variability_peak_scaling"
    assert "kge_dominant_variability_deficit" in payload["skill_limitation_flags"]
    assert payload["skill_limitation"]["dominant_kge_component"] == "variability"
    assert "peak_magnitude" in payload["skill_limitation"]["recommended_focus"]


def test_diagnostics_mark_snow_parameters_as_governed_process_controls(tmp_path: Path) -> None:
    idx = pd.to_datetime(["2015-02-01", "2015-03-01", "2015-04-01", "2015-05-01"])
    p = tmp_path / "alignment.csv"
    pd.DataFrame({"obs": [1.0, 10.0, 2.0, 1.0], "sim": [1.0, 2.0, 3.0, 10.0]}, index=idx).to_csv(p)

    diags = diagnose(p)
    out_json = write_diagnostics_json_report(diags, tmp_path / "diagnostics.json")
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    snow = next(
        flag
        for flag in payload["diagnostic_flags"]
        if flag["symptom"] == "Seasonal peak timing mismatch suggests snowmelt timing error"
    )

    assert snow["suggested_parameters"] == ["SFTMP", "SMTMP"]
    assert snow["parameter_governance"]["status"] == "governed"
    assert snow["parameter_governance"]["governed_parameters"] == ["SFTMP", "SMTMP"]
    assert snow["parameter_governance"]["unsupported_parameters"] == []
    assert any("snow" in action.lower() or "SFTMP" in action for action in payload["next_actions"])
    assert any(
        alt["option"] == "audit_snow_rain_partition_and_melt_thresholds"
        for alt in payload["source_backed_alternatives"]
    )


def test_skill_diagnostics_use_supported_lat_ttime_for_recession_lag(tmp_path: Path) -> None:
    p = tmp_path / "alignment.csv"
    obs = [1.0, 8.0, 6.0, 4.0, 3.0, 2.5, 2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    sim = [1.0, 8.0, 7.8, 7.2, 6.8, 6.5, 6.0, 5.6, 5.2, 4.8, 4.2, 3.8]
    _write_alignment(p, obs, sim)

    diags = diagnose(p)
    out_json = write_diagnostics_json_report(diags, tmp_path / "diagnostics.json")
    payload = json.loads(out_json.read_text(encoding="utf-8"))

    assert any("LAT_TTIME" in flag["suggested_parameters"] for flag in payload["diagnostic_flags"])
    assert not any("GW_DELAY" in flag["suggested_parameters"] for flag in payload["diagnostic_flags"])
    assert any(
        alt["option"] == "audit_baseflow_recession_and_subsurface_partition"
        and "LAT_TTIME" in alt["parameters"]
        for alt in payload["source_backed_alternatives"]
    )


def test_baseflow_flashy_diagnostic_avoids_legacy_groundwater_knobs(tmp_path: Path) -> None:
    p = tmp_path / "alignment.csv"
    obs = [2.0, 2.2, 2.4, 2.3, 2.1, 2.0, 1.9, 1.8, 1.7, 1.6, 1.6, 1.5]
    sim = [0.5, 0.4, 7.5, 0.4, 0.3, 0.3, 4.8, 0.3, 0.2, 0.2, 0.2, 0.2]
    _write_alignment(p, obs, sim)

    payload_path = write_diagnostics_json_report(diagnose(p), tmp_path / "diagnostics.json")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    baseflow = next(
        flag
        for flag in payload["diagnostic_flags"]
        if flag["symptom"] == "Simulated hydrograph is too flashy with low baseflow component"
    )

    assert baseflow["suggested_parameters"] == [
        "PERCO",
        "LATQ_CO",
        "LAT_TTIME",
        "ALPHA_BF",
        "RCHG_DP",
    ]
    all_suggested = {
        parameter
        for flag in payload["diagnostic_flags"]
        for parameter in flag["suggested_parameters"]
    }
    assert "GW_DELAY" not in all_suggested
    assert "GWQMN" not in all_suggested
    assert any(
        alt["option"] == "audit_baseflow_recession_and_subsurface_partition"
        and "LAT_TTIME" in alt["parameters"]
        and "RCHG_DP" in alt["parameters"]
        for alt in payload["source_backed_alternatives"]
    )
