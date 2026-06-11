from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from swatplus_builder.calibration import real_engine
from swatplus_builder.calibration.real_engine import (
    _set_print_prt_for_daily_channel_outputs,
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


def test_set_print_prt_for_daily_channel_outputs_enables_daily_and_nyskip(tmp_path: Path) -> None:
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
    _set_print_prt_for_daily_channel_outputs(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[2].split()[0] == "0"
    rows = {ln.split()[0]: ln.split()[1:] for ln in lines if len(ln.split()) == 5}
    assert rows["channel"][0] == "y"
    assert rows["channel_sd"][0] == "y"


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
        }
        return df, metrics, diagnostics

    monkeypatch.setattr(real_engine, "evaluate_run", _fake_eval)

    obj = make_real_objective(
        base_txtinout=base,
        observed_series=pd.Series([1.0], index=pd.to_datetime(["2015-01-01"])),
        work_root=tmp_path / "work",
        objective_sim_file="basin_sd_cha_day.txt",
        allow_outlet_autodetect=False,
    )
    assert obj({})["nse"] == 0.5
    assert seen["outlet_policy"] == "strict"


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
    )
    assert obj({})["nse"] == 0.5
    assert seen["outlet_policy"] == "auto"
