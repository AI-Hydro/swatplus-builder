from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from swatplus_builder.calibration.forward import (
    BasinSpec,
    ForwardRequest,
    ParameterVector,
    extract_surrogate_dataset,
    forward_simulate,
    verify_forward_artifact,
)
from swatplus_builder.calibration.real_engine import params_hash


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_objective_factory(*, work_root: Path, observed_series: pd.Series, **kwargs):
    calls = _fake_objective_factory.calls
    calls["n"] += 1

    def _objective(theta: dict[str, float]) -> dict[str, float]:
        out = work_root / params_hash(theta) / "TxtInOut"
        out.mkdir(parents=True, exist_ok=True)
        obs = observed_series.astype(float).copy()
        # deterministic perturbation from theta so different vectors produce different sims
        offset = sum(theta.values()) / max(len(theta), 1) / 1000.0 if theta else 0.0
        sim = obs + offset
        df = pd.DataFrame({"obs": obs.values, "sim": sim.values}, index=obs.index)
        df.to_csv(out / "alignment_calibration.csv")
        den = float(((df["obs"] - float(df["obs"].mean())) ** 2).sum())
        nse = float("nan") if den == 0.0 else 1.0 - float(((df["obs"] - df["sim"]) ** 2).sum()) / den
        trace = {
            "actual_sim_file": kwargs.get("objective_sim_file", "basin_sd_cha_day.txt"),
            "requested_outlet_gis_id": kwargs.get("outlet_gis_id", 1),
            "selected_outlet_gis_id": kwargs.get("outlet_gis_id", 1),
            "outlet_autodetected": False,
        }
        (work_root / params_hash(theta) / "objective_trace.json").write_text(
            json.dumps(trace) + "\n", encoding="utf-8"
        )
        return {"nse": nse, "kge": 0.4 - offset}

    return _objective


_fake_objective_factory.calls = {"n": 0}


def _make_request(tmp_path: Path, *, theta: dict[str, float]) -> ForwardRequest:
    base_txt = tmp_path / "TxtInOut"
    base_txt.mkdir(parents=True, exist_ok=True)
    alignment = tmp_path / "alignment.csv"
    _write(
        alignment,
        "date,obs,sim\n"
        "2015-01-01,1.0,0.8\n"
        "2015-01-02,2.0,1.7\n"
        "2015-01-03,0.5,0.6\n",
    )
    return ForwardRequest(
        basin=BasinSpec(
            basin_id="usgs_01547700",
            simulation_start=date(2015, 1, 1),
            simulation_end=date(2015, 12, 31),
            base_txtinout=base_txt,
            alignment_csv=alignment,
            outlet_gis_id=1,
            objective_sim_file="basin_sd_cha_day.txt",
            strict_objective_file=True,
            allow_outlet_autodetect=False,
        ),
        theta=ParameterVector(values=theta),
        artifacts_root=tmp_path / "artifacts",
        engine_version="test-engine",
        builder_git_sha="abc123",
        warm_start=True,
    )


def test_forward_simulate_cache_short_circuit(tmp_path: Path) -> None:
    _fake_objective_factory.calls["n"] = 0
    req = _make_request(tmp_path, theta={"CN2": 70.0, "ALPHA_BF": 0.1, "SURLAG": 3.0})
    first = forward_simulate(req, _objective_factory=_fake_objective_factory)
    second = forward_simulate(req, _objective_factory=_fake_objective_factory)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.content_hash == second.content_hash
    assert _fake_objective_factory.calls["n"] == 1
    assert first.simulated == second.simulated


def test_extract_surrogate_dataset_from_forward_artifacts(tmp_path: Path) -> None:
    _fake_objective_factory.calls["n"] = 0
    req1 = _make_request(tmp_path, theta={"CN2": 72.0, "ALPHA_BF": 0.2, "SURLAG": 4.0})
    req2 = _make_request(tmp_path, theta={"CN2": 75.0, "ALPHA_BF": 0.05, "SURLAG": 2.0})
    forward_simulate(req1, _objective_factory=_fake_objective_factory)
    forward_simulate(req2, _objective_factory=_fake_objective_factory)

    ds = extract_surrogate_dataset(req1.artifacts_root)
    assert len(ds.rows) == 2
    assert set(ds.parameter_names) >= {"CN2", "ALPHA_BF", "SURLAG"}
    assert all(r.n_days > 0 for r in ds.rows)


def test_verify_forward_artifact_checks_output_truth(tmp_path: Path) -> None:
    _fake_objective_factory.calls["n"] = 0
    req = _make_request(tmp_path, theta={"CN2": 68.0, "ALPHA_BF": 0.12, "SURLAG": 5.0})
    res = forward_simulate(req, _objective_factory=_fake_objective_factory)
    ver = verify_forward_artifact(
        req.artifacts_root,
        res.content_hash,
        expected_objective_sim_file="basin_sd_cha_day.txt",
        expected_outlet_gis_id=1,
        allow_outlet_autodetect=False,
        min_days=1,
    )
    assert ver.passed is True
    assert ver.checks["objective_source_match"] is True
    assert ver.checks["nse_match"] is True
