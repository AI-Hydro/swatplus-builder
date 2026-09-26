"""Tests for decision-model data preparation: faults, state serialization, typed export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swatplus_builder.audit import RunAuditTrail, export_decision_episodes, iter_records
from swatplus_builder.cli import app
from swatplus_builder.decision_data.faults import (
    DEFAULT_FAULTS,
    FaultSpec,
    fault_effect,
    inject_fault,
    load_fault_manifest,
)
from swatplus_builder.decision_data.state import serialize_state
from swatplus_builder.decision_data.typed import (
    FAULT_FAMILY_OPTIONS,
    assign_split,
    compile_typed_decisions,
    episode_to_typed_decisions,
)
from swatplus_builder.workflows.usgs_e2e import _record_calibration_phase_decisions

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PCP_ROWS = [3.0, 0.0, -99.0, 40.0, 1.0, 0.0, 12.0, 80.0, 0.5, 5.0]


def _station(path: Path, header_title: str, rows: list[list[float]]) -> None:
    lines = [
        f"{header_title}: fixture",
        "nbyr     tstep       lat       lon      elev",
        "   1         0    41.000   -77.000   300.000",
    ]
    for i, vals in enumerate(rows, start=1):
        lines.append(f"2010{str(i).rjust(5)} " + "".join(f"{v:.5f}".rjust(10) + "  " for v in vals))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_txtinout(root: Path) -> Path:
    txt = root / "base"
    txt.mkdir(parents=True)
    (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
    _station(txt / "s1.pcp", "s1.pcp", [[v] for v in _PCP_ROWS])
    _station(txt / "s1.tmp", "s1.tmp", [[20.0, 5.0], [-99.0, -99.0], [25.0, 10.0]])
    (txt / "hydrology.hyd").write_text(
        "hydrology.hyd: test fixture\n"
        "name                 lat_ttime       lat_sed       can_max          esco          epco   orgn_enrich   orgp_enrich       cn3_swf       bio_mix         perco      lat_orgn      lat_orgp        pet_co       latq_co\n"
        "hyd01                  0.00000       0.00000       1.00000       0.95000       0.50000       0.00000       0.00000       0.95000       0.20000       0.90000       0.00000       0.00000       1.00000       0.01000\n",
        encoding="utf-8",
    )
    # Outputs of an earlier engine run must not be copied into a faulted model.
    (txt / "channel_sd_day.txt").write_text("stale output\n", encoding="utf-8")
    return txt


def _pcp_values(txt: Path) -> list[float]:
    return [float(ln.split()[2]) for ln in (txt / "s1.pcp").read_text().splitlines()[3:]]


def _spec(fault_id: str) -> FaultSpec:
    return next(f for f in DEFAULT_FAULTS if f.fault_id == fault_id)


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------


def test_precip_scale_fault_preserves_missing_and_writes_manifest(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    txt = inject_fault(base, tmp_path / "run", _spec("precip_minus_30pct"))

    values = _pcp_values(txt)
    assert values == pytest.approx([v * 0.7 if v >= 0 else v for v in _PCP_ROWS])
    assert _pcp_values(base) == pytest.approx(_PCP_ROWS)  # base untouched
    assert not (txt / "channel_sd_day.txt").exists()

    manifest = load_fault_manifest(tmp_path / "run")
    assert manifest is not None
    assert manifest["latent_fault_family"] == "forcing"
    assert manifest["edited_files"] == ["s1.pcp"]
    assert set(manifest["changed_files"]) == {"s1.pcp"}
    assert manifest["input_fingerprint_before"] != manifest["input_fingerprint_after"]


def test_storm_removal_only_affects_largest_wet_days(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    spec = FaultSpec("storms", "forcing", "precip_storm_removal", 1.0, quantile=0.8)
    values = _pcp_values(inject_fault(base, tmp_path / "run", spec))
    # 7 wet days; the 80th-percentile threshold is 40 mm, so 40 and 80 are removed.
    assert values == pytest.approx([3.0, 0.0, -99.0, 0.0, 1.0, 0.0, 12.0, 0.0, 0.5, 5.0])


def test_precip_time_shift_delays_series(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    values = _pcp_values(inject_fault(base, tmp_path / "run", FaultSpec("lag", "forcing", "precip_time_shift", 2)))
    assert values == pytest.approx([0.0, 0.0, *_PCP_ROWS[:-2]])


def test_temperature_shift_skips_missing(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    txt = inject_fault(base, tmp_path / "run", _spec("temperature_plus_3c"))
    rows = [ln.split()[2:] for ln in (txt / "s1.tmp").read_text().splitlines()[3:]]
    assert rows == [["23.00000", "8.00000"], ["-99.00000", "-99.00000"], ["28.00000", "13.00000"]]


def test_parameter_fault_uses_bridge(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    txt = inject_fault(base, tmp_path / "run", _spec("esco_low"))
    row = (txt / "hydrology.hyd").read_text().splitlines()[2].split()
    header = (txt / "hydrology.hyd").read_text().splitlines()[1].split()
    assert float(row[header.index("esco")]) == pytest.approx(0.05)
    assert load_fault_manifest(tmp_path / "run")["edited_files"] == ["hydrology.hyd"]


def test_fault_without_observed_data_fails_and_cleans_up(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    (base / "s1.tmp").write_text("", encoding="utf-8")  # weather generator in use
    with pytest.raises(ValueError, match="weather generator"):
        inject_fault(base, tmp_path / "run", _spec("temperature_plus_3c"))
    assert not (tmp_path / "run" / "TxtInOut").exists()
    assert load_fault_manifest(tmp_path / "run") is None


def test_inject_refuses_to_overwrite(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    inject_fault(base, tmp_path / "run", _spec("precip_minus_30pct"))
    with pytest.raises(FileExistsError):
        inject_fault(base, tmp_path / "run", _spec("precip_plus_30pct"))


def _write_wb(txt: Path, **values: float) -> None:
    txt.mkdir(parents=True, exist_ok=True)
    names = list(values)
    (txt / "basin_wb_aa.txt").write_text(
        "basin_wb_aa\n"
        + "jday mon day yr unit gis_id name " + " ".join(names) + "\n"
        + "0 0 0 0 0 0 basin " + " ".join(str(values[n]) for n in names) + "\n",
        encoding="utf-8",
    )


def test_fault_effect_flags_ineffective_faults(tmp_path: Path) -> None:
    _write_wb(tmp_path / "base", precip=1000.0, wateryld=300.0, perc=0.0)
    _write_wb(tmp_path / "same", precip=1000.0, wateryld=300.5, perc=0.0)
    _write_wb(tmp_path / "moved", precip=700.0, wateryld=150.0, perc=0.0)

    assert fault_effect(tmp_path / "base", tmp_path / "same")["effective"] is False
    moved = fault_effect(tmp_path / "base", tmp_path / "moved")
    assert moved["effective"] is True
    assert moved["ratios"]["precip"] == pytest.approx(0.7)
    assert moved["ratios"]["perc"] is None


# ---------------------------------------------------------------------------
# State serialization
# ---------------------------------------------------------------------------


def test_serialize_state_is_deterministic_and_prioritized() -> None:
    state = {
        "incoming_parameters": {"CN2": 75.0},
        "objective": "minimize_abs_pbias",
        "incoming_metrics": {"nse": 0.123456, "kge": None, "pbias": float("nan")},
        "flag": True,
    }
    a = serialize_state(state)
    b = serialize_state(dict(reversed(list(state.items()))))
    assert a.text == b.text
    assert a.text == "objective=minimize_abs_pbias; incoming_metrics.nse=0.123; incoming_parameters.CN2=75; flag=yes"
    assert not a.truncated


def test_serialize_state_trims_lowest_priority_to_budget() -> None:
    state = {"objective": "x" * 20, "incoming_parameters": {f"P{i}": float(i) for i in range(50)}}
    out = serialize_state(state, max_chars=60)
    assert len(out.text) <= 60
    assert out.text.startswith("objective=")
    assert out.truncated and all(k.startswith("incoming_parameters.") for k in out.dropped_keys)


def test_serialize_state_refuses_hidden_labels() -> None:
    with pytest.raises(ValueError, match="label leakage"):
        serialize_state({"metrics": {"nse": 0.2}, "context": {"latent_fault_family": "runoff"}})


# ---------------------------------------------------------------------------
# Splits and typed decisions
# ---------------------------------------------------------------------------


def test_assign_split_is_basin_deterministic() -> None:
    assert assign_split("01547700") == assign_split("01547700")
    splits = {assign_split(f"{i:08d}") for i in range(200)}
    assert splits == {"train", "validation", "test"}
    with pytest.raises(ValueError):
        assign_split("x", fractions=(0.5, 0.5, 0.5))


def _phase_episode(n_candidates: int = 4) -> dict:
    ids = [f"eval:{i}" for i in range(n_candidates)]
    outcomes = {
        f"eval:{i}": {"phase_score": float(i) if i % 2 == 0 else None, "feasible": i % 2 == 0}
        for i in range(n_candidates)
    }
    best = max(i for i in range(n_candidates) if i % 2 == 0)
    return {
        "episode_id": "r@a:calibration_phase:volume:1",
        "basin_id": "01547700",
        "split_group": "01547700",
        "decision_point": "calibration_phase:volume",
        "state_before": {
            "objective": "minimize_abs_pbias_then_kge_nse",
            "incoming_parameters": {"CN2": 75.0, "PERCO": 0.5},
            "incoming_metrics": {"nse": 0.1, "pbias": -35.0},
        },
        "candidate_actions": [*ids, "no_promotion"],
        "chosen_action": f"eval:{best}",
        "outcome_vector": {
            "candidate_outcomes": outcomes,
            "candidate_parameters": {f"eval:{i}": {"CN2": 70.0 + i, "PERCO": 0.5} for i in range(n_candidates)},
        },
        "source": "natural",
    }


def test_phase_episode_compiles_to_bounded_choice() -> None:
    (item,) = episode_to_typed_decisions(_phase_episode(40), max_options=6)
    ids = item["meta"]["option_ids"]
    assert len(ids) == 6 and item["meta"]["options_truncated"] is True
    assert "eval:38" in ids and "no_promotion" in ids  # chosen and abstain always kept
    assert ids[-1] == "no_promotion"
    assert item["target"]["probabilities"][ids.index("eval:38")] == 1.0
    assert "CN2 75->108" in item["question"]["options"][ids.index("eval:38")]
    assert item["meta"]["split"] == assign_split("01547700")


def test_phase_softmax_target_ignores_infeasible_candidates() -> None:
    (item,) = episode_to_typed_decisions(_phase_episode(4), soft_target="softmax", temperature=1.0)
    ids, probs = item["meta"]["option_ids"], item["target"]["probabilities"]
    assert sum(probs) == pytest.approx(1.0)
    assert probs[ids.index("eval:1")] == 0.0 and probs[ids.index("no_promotion")] == 0.0
    assert probs[ids.index("eval:2")] > probs[ids.index("eval:0")]


def test_fault_episode_adds_diagnosis_item_without_leaking_label() -> None:
    episode = {
        "episode_id": "r@a:effective_claim_tier:3",
        "split_group": "01547700",
        "decision_point": "effective_claim_tier",
        "state_before": {"metrics": {"nse": 0.2, "pbias": -30.0}, "blocker_class": None},
        "candidate_actions": ["blocked", "exploratory", "diagnostic", "publication_grade", "research_grade"],
        "chosen_action": "diagnostic",
        "latent_fault": {"family": "forcing", "fault_manifest_sha256": "abc"},
        "source": "injected_fault",
    }
    items = episode_to_typed_decisions(episode)
    assert [i["meta"]["decision_point"] for i in items] == ["effective_claim_tier", "dominant_failure"]
    diagnosis = items[1]
    assert diagnosis["question"]["options"] == list(FAULT_FAMILY_OPTIONS)
    assert diagnosis["target"]["probabilities"][FAULT_FAMILY_OPTIONS.index("forcing")] == 1.0
    assert "forcing" not in diagnosis["state"]


# ---------------------------------------------------------------------------
# Calibration phase decisions -> ledger -> episodes -> typed items
# ---------------------------------------------------------------------------


def _phase_decisions_payload() -> dict:
    return {
        "schema": "swatplus_builder.calibration_phase_decisions/v1",
        "phases": [
            {
                "order": 1,
                "phase": "volume",
                "objective": "minimize_abs_pbias_then_kge_nse",
                "budget": 3,
                "parameters_opened": ["CN2"],
                "incoming_parameters": {},
                "incoming_metrics": {},
                "status": "promoted",
                "promoted_score": 0.4,
                "promoted_eval_idx": 1,
                "feasible_candidate_count": 1,
                "candidates": [
                    {"eval_idx": 0, "parameters": {"CN2": 60.0}, "metrics": {"nse": -0.2}, "feasible": False, "phase_score": None},
                    {"eval_idx": 1, "parameters": {"CN2": 70.0}, "metrics": {"nse": 0.4}, "feasible": True, "phase_score": 0.4},
                ],
            },
            {"order": 2, "phase": "baseflow_subsurface", "status": "not_reached"},
        ],
    }


def test_phase_decisions_flow_into_ledger_and_typed_items(tmp_path: Path) -> None:
    cal_dir = tmp_path / "calibration_reports_locked"
    cal_dir.mkdir()
    (cal_dir / "history.csv").write_text("eval_idx\n0\n1\n", encoding="utf-8")
    (cal_dir / "phase_decisions.json").write_text(json.dumps(_phase_decisions_payload()), encoding="utf-8")
    run = tmp_path / "run"
    audit = RunAuditTrail(run, run_id="r", basin_id="01547700", attempt_id="a")

    _record_calibration_phase_decisions(audit, {"history_csv": str(cal_dir / "history.csv")})

    decisions = [r for r in iter_records(run / "decisions.jsonl") if r["kind"] == "decision"]
    assert [d["decision_point"] for d in decisions] == ["calibration_phase:volume"]  # not_reached skipped
    assert decisions[0]["options"] == ["eval:0", "eval:1", "no_promotion"]
    assert decisions[0]["chosen"] == "eval:1"
    assert decisions[0]["evidence"]["phase_decisions_sha256"]

    (episode,) = export_decision_episodes(run)
    assert episode["outcome_vector"]["candidate_outcomes"]["eval:0"]["feasible"] is False
    (item,) = compile_typed_decisions([episode])
    assert item["question"]["options"][item["meta"]["option_ids"].index("eval:1")] == "CN2=70"


def test_episode_export_marks_injected_fault_runs(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    run = tmp_path / "run"
    inject_fault(base, run, _spec("precip_minus_30pct"))
    audit = RunAuditTrail(run, run_id="r", basin_id="01547700", attempt_id="a")
    audit.decision("effective_claim_tier", state={"metrics": {"nse": 0.1}}, options=["diagnostic"], chosen="diagnostic", policy="p")

    (episode,) = export_decision_episodes(run)
    assert episode["source"] == "injected_fault"
    assert episode["latent_fault"]["family"] == "forcing"
    assert "latent_fault" not in json.dumps(episode["state_before"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_fault_inject_and_typed_export(tmp_path: Path) -> None:
    base = _base_txtinout(tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["fault", "inject", str(base), str(tmp_path / "run"), "--fault", "precip_plus_30pct"])
    assert res.exit_code == 0, res.output
    assert load_fault_manifest(tmp_path / "run")["fault"]["fault_id"] == "precip_plus_30pct"

    res = runner.invoke(app, ["fault", "inject", str(base), str(tmp_path / "x"), "--fault", "nope"])
    assert res.exit_code != 0

    audit = RunAuditTrail(tmp_path / "run", run_id="r", basin_id="01547700", attempt_id="a")
    audit.decision(
        "effective_claim_tier",
        state={"metrics": {"nse": 0.1}},
        options=["exploratory", "diagnostic"],
        chosen="diagnostic",
        policy="p",
    )
    out = tmp_path / "typed.jsonl"
    res = runner.invoke(app, ["audit", "typed", str(tmp_path / "run"), "--out", str(out)])
    assert res.exit_code == 0, res.output
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert {r["meta"]["decision_point"] for r in rows} == {"effective_claim_tier", "dominant_failure"}
