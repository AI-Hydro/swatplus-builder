from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from swatplus_builder.calibration import real_engine
from swatplus_builder.calibration.real_engine import (
    _prepare_txtinout_for_objective,
    _set_print_prt_for_daily_channel_outputs,
    _set_time_sim_window,
    apply_parameters_to_lte_txtinout,
    load_observed_from_alignment_csv,
    make_real_objective,
    params_hash,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_apply_parameters_to_lte_txtinout_updates_expected_fields(tmp_path: Path) -> None:
    _write(
        tmp_path / "hru-lte.hru",
        "name\n"
        "id cn2 alpha_bf x\n"
        "1 70.0 0.05 9\n"
        "2 75.0 0.06 9\n",
    )
    _write(
        tmp_path / "parameters.bsn",
        "name\n"
        "surq_lag x\n"
        "4.0 9\n",
    )

    apply_parameters_to_lte_txtinout(
        tmp_path,
        {"CN2": 80.0, "ALPHA_BF": 0.2, "SURLAG": 6.5},
    )

    hru = (tmp_path / "hru-lte.hru").read_text(encoding="utf-8")
    bsn = (tmp_path / "parameters.bsn").read_text(encoding="utf-8")
    assert "80.00000" in hru
    assert "0.20000" in hru
    assert "6.50000" in bsn


def test_apply_parameters_to_lte_txtinout_raises_on_missing_column(tmp_path: Path) -> None:
    _write(
        tmp_path / "hru-lte.hru",
        "name\n"
        "id cn2 x\n"
        "1 70.0 9\n",
    )
    with pytest.raises(ValueError, match="ALPHA_BF"):
        apply_parameters_to_lte_txtinout(tmp_path, {"ALPHA_BF": 0.2})


def test_load_observed_from_alignment_csv_reads_obs_series(tmp_path: Path) -> None:
    _write(
        tmp_path / "alignment.csv",
        "date,obs,sim\n"
        "2015-01-01,1.0,0.8\n"
        "2015-01-02,2.0,1.7\n",
    )
    s = load_observed_from_alignment_csv(tmp_path / "alignment.csv")
    assert len(s) == 2
    assert float(s.iloc[0]) == 1.0


def test_params_hash_is_deterministic() -> None:
    a = params_hash({"CN2": 72.0, "SURLAG": 4.0})
    b = params_hash({"SURLAG": 4.0, "CN2": 72.0})
    assert a == b


def test_set_print_prt_for_daily_channel_outputs_enables_daily_and_window(tmp_path: Path) -> None:
    p = tmp_path / "print.prt"
    p.write_text(
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
        encoding="utf-8",
    )
    _set_print_prt_for_daily_channel_outputs(
        p,
        score_start=pd.Timestamp("2007-01-01").date(),
        score_end=pd.Timestamp("2012-12-31").date(),
    )
    lines = p.read_text(encoding="utf-8").splitlines()
    top = lines[2].split()
    assert top[:5] == ["0", "1", "2007", "366", "2012"]
    rows = {ln.split()[0]: ln.split()[1:] for ln in lines if len(ln.split()) == 5}
    assert rows["channel"][0] == "y"
    assert rows["channel_sd"][0] == "y"


def test_set_time_sim_window_updates_simulation_dates(tmp_path: Path) -> None:
    p = tmp_path / "time.sim"
    p.write_text(
        "hdr\n"
        "day_start yrc_start day_end yrc_end step\n"
        "1 1997 365 2019 0\n",
        encoding="utf-8",
    )
    _set_time_sim_window(
        p,
        simulation_start=pd.Timestamp("2004-01-01").date(),
        simulation_end=pd.Timestamp("2012-12-31").date(),
    )

    assert p.read_text(encoding="utf-8").splitlines()[2].split() == [
        "1",
        "2004",
        "366",
        "2012",
        "0",
    ]


def test_prepare_txtinout_for_objective_removes_stale_morph_outputs(tmp_path: Path) -> None:
    _write(
        tmp_path / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )
    for name in (
        "channel_day.txt",
        "channel_sd_day.txt",
        "channel_sdmorph_day.txt",
        "basin_cha_day.txt",
        "basin_sd_cha_day.txt",
        "basin_sd_chamorph_day.txt",
        "alignment_calibration.csv",
    ):
        _write(tmp_path / name, "stale\n")

    _prepare_txtinout_for_objective(tmp_path)

    for name in (
        "channel_day.txt",
        "channel_sd_day.txt",
        "channel_sdmorph_day.txt",
        "basin_cha_day.txt",
        "basin_sd_cha_day.txt",
        "basin_sd_chamorph_day.txt",
        "alignment_calibration.csv",
    ):
        assert not (tmp_path / name).exists()


def test_make_real_objective_rejects_source_file_fallback(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "requested_outlet",
            "sim_source_file": "channel_sd_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        strict_objective_file=True,
        nyskip_years=0,
    )
    with pytest.raises(RuntimeError, match="Objective source mismatch"):
        obj({})


def test_make_real_objective_rejects_outlet_autodetect_when_disallowed(
    monkeypatch, tmp_path: Path
) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 3,
            "outlet_autodetected": True,
            "outlet_selection_reason": "requested_outlet_dry",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        strict_objective_file=True,
        allow_outlet_autodetect=False,
        nyskip_years=0,
    )
    with pytest.raises(RuntimeError, match="Outlet auto-detection occurred"):
        obj({})


def test_make_real_objective_scores_strict_pinned_outlet_by_default(
    monkeypatch, tmp_path: Path
) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)
    seen: dict[str, object] = {}

    def _fake_eval(*args, **kwargs):
        seen.update(kwargs)
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5, "kge": 0.4}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
            "selected_terminal_fraction_of_all_terminal_flow": 0.42,
            "all_terminal_nse": 0.7,
            "all_terminal_kge": 0.6,
            "all_terminal_pbias": -5.0,
            "all_terminal_volume_gate_passes_diagnostic": True,
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        allow_outlet_autodetect=False,
        nyskip_years=0,
    )
    result = obj({})
    assert result["nse"] == 0.5
    assert result["selected_terminal_fraction_of_all_terminal_flow"] == 0.42
    assert result["all_terminal_nse"] == 0.7
    assert result["all_terminal_kge"] == 0.6
    assert result["all_terminal_pbias"] == -5.0
    assert result["all_terminal_volume_gate_passes_diagnostic"] == 1.0
    assert seen["outlet_policy"] == "strict"


def test_make_real_objective_can_attach_candidate_physical_gate(
    monkeypatch, tmp_path: Path
) -> None:
    from swatplus_builder.full_mode import water_balance_gate

    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5, "kge": 0.6, "pbias": 4.0}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)
    monkeypatch.setattr(
        water_balance_gate,
        "check_water_balance",
        lambda txt, **kwargs: {"pass": True, "status": "passed", "received": kwargs},
    )

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        include_physical_gate=True,
        keep_workdirs=False,
        nyskip_years=0,
    )
    metrics = obj({})

    assert metrics["physical_gate_passed"] == 1.0
    assert metrics["calibration_process_gate_passed"] == 1.0
    trace = json.loads(next((tmp_path / "work").glob("*_objective_trace.json")).read_text(encoding="utf-8"))
    assert trace["candidate_physical_gate"]["status"] == "passed"
    assert trace["candidate_physical_gate"]["calibration_process_gate_pass"] is True


def test_candidate_physical_gate_separates_skill_gate_from_process_gate(
    monkeypatch, tmp_path: Path
) -> None:
    from swatplus_builder.full_mode import water_balance_gate

    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.1, "kge": 0.2, "pbias": 4.0}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)
    monkeypatch.setattr(
        water_balance_gate,
        "check_water_balance",
        lambda txt, **kwargs: {
            "pass": False,
            "status": "failed",
            "condition_codes": ["BELOW_RESEARCH_SKILL"],
            "dominant_blocker": "BELOW_RESEARCH_SKILL",
        },
    )

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        include_physical_gate=True,
        keep_workdirs=False,
        nyskip_years=0,
    )
    metrics = obj({})

    assert metrics["physical_gate_passed"] == 0.0
    assert metrics["calibration_process_gate_passed"] == 1.0
    trace = json.loads(next((tmp_path / "work").glob("*_objective_trace.json")).read_text(encoding="utf-8"))
    assert trace["candidate_physical_gate"]["condition_codes"] == ["BELOW_RESEARCH_SKILL"]
    assert trace["candidate_physical_gate"]["calibration_process_gate_pass"] is True
    assert trace["candidate_physical_gate"]["calibration_process_condition_codes"] == []


def test_make_real_objective_full_mode_uses_full_parameter_bridge(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )
    _write(
        base / "hydrology.hyd",
        "hydrology.hyd\n"
        "name esco epco perco pet_co latq_co\n"
        "hyd01 0.95 0.50 0.90 1.00 0.01\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5, "kge": 0.4}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        parameter_mode="full",
        nyskip_years=0,
    )
    assert obj({"PERCO": 0.25})["nse"] == 0.5
    run_txt = tmp_path / "work" / params_hash({"PERCO": 0.25}) / "TxtInOut"
    assert "0.25000" in (run_txt / "hydrology.hyd").read_text(encoding="utf-8")


def test_make_real_objective_full_mode_normalizes_routing_before_run(
    monkeypatch, tmp_path: Path
) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )
    _write(
        base / "hydrology.hyd",
        "hydrology.hyd\n"
        "name esco epco perco pet_co latq_co\n"
        "hyd01 0.95 0.50 0.90 1.00 0.01\n",
    )
    _write(
        base / "codes.bsn",
        "codes.bsn\n"
        "rte_cha swift_out uhyd soil_p i_fpwet\n"
        "0 1 1 0 1\n",
    )
    _write(
        base / "rout_unit.def",
        "rout_unit.def\n"
        "id name elem_tot elements\n"
        "1 rtu01 1 1\n",
    )
    _write(
        base / "rout_unit.con",
        "rout_unit.con\n"
        "id name gis_id area lat lon elev rtu wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n"
        "1 rtu01 1 10 0 0 0 1 w 0 0 0 3 sdc 1 tot 1.0 sdc 1 sur 1.0 sdc 1 lat 1.0\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5, "kge": 0.4}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        parameter_mode="full",
        nyskip_years=0,
    )
    assert obj({"PERCO": 0.25})["nse"] == 0.5

    run_txt = tmp_path / "work" / params_hash({"PERCO": 0.25}) / "TxtInOut"
    rout_unit = (run_txt / "rout_unit.con").read_text(encoding="utf-8")
    assert " tot " not in rout_unit
    assert " sur " in rout_unit
    assert " lat " in rout_unit


def test_make_real_objective_can_discard_scratch_workdirs(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )
    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame({"obs": [1.0], "sim": [1.0]}, index=pd.to_datetime(["2015-01-01"]))
        metrics = {"nse": 0.5, "kge": 0.4, "pbias": 1.0}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)
    params: dict[str, float] = {}
    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        keep_workdirs=False,
        nyskip_years=0,
    )

    assert obj(params)["pbias"] == 1.0
    key = params_hash(params)
    assert not (tmp_path / "work" / key).exists()
    assert (tmp_path / "work" / f"{key}_objective_trace.json").exists()
    assert not any(path.is_dir() for path in (tmp_path / "work").iterdir())


def test_make_real_objective_invalidates_legacy_objective_cache(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )
    _write(
        base / "hydrology.hyd",
        "hydrology.hyd\n"
        "name esco epco perco pet_co latq_co\n"
        "hyd01 0.95 0.50 0.90 1.00 0.01\n",
    )
    run_dir = tmp_path / "work" / params_hash({"PERCO": 0.25})
    _write(run_dir / "TxtInOut" / "hydrology.hyd", "stale\n")
    _write(run_dir / ".objective_v2_complete", "ok\n")

    calls = {"run_swat": 0}

    def fake_run_swat(*args, **kwargs):
        calls["run_swat"] += 1

    monkeypatch.setattr(real_engine, "run_swat", fake_run_swat)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5, "kge": 0.4}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        parameter_mode="full",
        nyskip_years=0,
    )

    assert obj({"PERCO": 0.25})["nse"] == 0.5
    assert calls["run_swat"] == 1
    assert "0.25000" in (run_dir / "TxtInOut" / "hydrology.hyd").read_text(encoding="utf-8")


def test_make_real_objective_force_fresh_discards_matching_cache(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )
    _write(
        base / "hydrology.hyd",
        "hydrology.hyd\n"
        "name esco epco perco pet_co latq_co\n"
        "hyd01 0.95 0.50 0.90 1.00 0.01\n",
    )
    params = {"PERCO": 0.25}
    run_dir = tmp_path / "work" / params_hash(params)
    _write(run_dir / "TxtInOut" / "hydrology.hyd", "stale\n")
    marker_payload = {
        "status": "ok",
        "cache_signature": real_engine._objective_cache_signature("full"),
    }
    _write(run_dir / ".objective_v2_complete", json.dumps(marker_payload))

    calls = {"run_swat": 0}

    def fake_run_swat(*args, **kwargs):
        calls["run_swat"] += 1

    monkeypatch.setattr(real_engine, "run_swat", fake_run_swat)

    def _fake_eval(*args, **kwargs):
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5, "kge": 0.4}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "outlet_autodetected": False,
            "outlet_selection_reason": "strict_requested_outlet",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        parameter_mode="full",
        force_fresh=True,
        nyskip_years=0,
    )

    assert obj(params)["nse"] == 0.5
    assert calls["run_swat"] == 1
    assert "0.25000" in (run_dir / "TxtInOut" / "hydrology.hyd").read_text(encoding="utf-8")


def test_make_real_objective_can_allow_outlet_autodetect_explicitly(
    monkeypatch, tmp_path: Path
) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)
    seen: dict[str, object] = {}

    def _fake_eval(*args, **kwargs):
        seen.update(kwargs)
        df = pd.DataFrame(
            {"obs": [1.0], "sim": [1.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 0.5, "kge": 0.4}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 3,
            "outlet_autodetected": True,
            "outlet_selection_reason": "requested_outlet_non_terminal_best_nse",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        allow_outlet_autodetect=True,
        nyskip_years=0,
    )
    assert obj({})["nse"] == 0.5
    assert seen["outlet_policy"] == "auto"


def test_make_real_objective_can_score_explicit_virtual_all_terminal_scope(
    monkeypatch, tmp_path: Path
) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    _write(
        base / "print.prt",
        "hdr\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "1 0 0 0 0 1\n"
        "aa_int_cnt\n"
        "0\n"
        "csvout dbout cdfout\n"
        "n n n\n"
        "objects daily monthly yearly avann\n"
        "channel n n y y\n"
        "channel_sd n n y y\n"
        "basin_cha n n y y\n"
        "basin_sd_cha n n y y\n",
    )

    monkeypatch.setattr(real_engine, "run_swat", lambda *args, **kwargs: None)
    seen: dict[str, object] = {}

    def _fake_eval(*args, **kwargs):
        seen.update(kwargs)
        df = pd.DataFrame(
            {"obs": [3.0], "sim": [3.0]},
            index=pd.to_datetime(["2015-01-01"]),
        )
        metrics = {"nse": 1.0, "kge": 1.0, "pbias": 0.0}
        diagnostics = {
            "requested_outlet_gis_id": 1,
            "selected_outlet_gis_id": 1,
            "selected_outlet_gis_ids": [7, 8],
            "outlet_scope": "virtual_all_terminal",
            "outlet_autodetected": False,
            "outlet_selection_reason": "explicit_virtual_all_terminal_sum",
            "sim_source_file": "basin_sd_cha_day.txt",
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([3.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        objective_outlet_policy="all_terminal_sum",
        nyskip_years=0,
    )

    assert obj({})["pbias"] == 0.0
    assert seen["outlet_policy"] == "all_terminal_sum"
    trace = json.loads(
        (tmp_path / "work" / params_hash({}) / "objective_trace.json").read_text(encoding="utf-8")
    )
    assert trace["outlet_scope"] == "virtual_all_terminal"
    assert trace["outlet_policy"] == "all_terminal_sum"
    assert trace["selected_outlet_gis_ids"] == [7, 8]


def test_make_real_objective_rejects_auto_policy_without_autodetect(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="requires allow_outlet_autodetect"):
        make_real_objective(
            base_txtinout=base,
            observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
            work_root=tmp_path / "work",
            objective_outlet_policy="auto",
            nyskip_years=0,
        )
