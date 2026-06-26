from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from swatplus_builder.orchestrate import _load_observed_series, run_pipeline


def _write_prepared_run(root: Path) -> Path:
    txt = root / "project" / "Scenarios" / "Default" / "TxtInOut"
    txt.mkdir(parents=True)
    (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")
    (txt / "codes.bsn").write_text(
        "codes.bsn\n"
        "rte_cha swift_out uhyd soil_p i_fpwet\n"
        "0 1 1 0 1\n",
        encoding="utf-8",
    )
    (txt / "rout_unit.def").write_text(
        "rout_unit.def\n"
        "id name elem_tot elem1 elem2\n"
        "1 rtu1 1 1\n",
        encoding="utf-8",
    )
    (txt / "rout_unit.con").write_text(
        "rout_unit.con\n"
        "id name gis_id area lat lon elev wst name2 ovn_len something something out_tot obj id hyd frac\n"
        "1 rtu1 1 1 0 0 0 1 wst 0 0 0 3 sdc 1 tot 1.00000 sdc 1 sur 1.00000 sdc 1 lat 1.00000\n",
        encoding="utf-8",
    )
    (txt / "chandeg.con").write_text("chandeg.con\nid gis_id obj_typ\n1 1 out\n", encoding="utf-8")
    lines = ["channel_sd Daily", "", "gis_id yr mon day flo_out"]
    start = pd.Timestamp("2010-01-01")
    for i in range(10):
        d = start + pd.Timedelta(days=i)
        lines.append(f"1 {d.year} {d.month} {d.day} {1.0 + i * 0.1:.3f}")
    (txt / "channel_sd_day.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    outputs = root / "outputs"
    outputs.mkdir(exist_ok=True)
    obs = pd.Series(
        [1.0 + i * 0.05 for i in range(10)],
        index=pd.date_range("2010-01-01", periods=10, freq="D"),
        name="obs",
    )
    obs.to_csv(outputs / "obs_q.csv", index_label="date")
    return txt


def test_load_observed_series_preserves_values_when_normalizing_times(tmp_path: Path) -> None:
    obs_csv = tmp_path / "obs_q.csv"
    obs_csv.write_text(
        "date,obs\n"
        "2010-01-01 05:00:00,1.25\n"
        "2010-01-02 05:00:00,2.50\n",
        encoding="utf-8",
    )

    series = _load_observed_series(obs_csv)

    assert series is not None
    assert list(series.index.strftime("%Y-%m-%d")) == ["2010-01-01", "2010-01-02"]
    assert series.tolist() == [1.25, 2.50]


def test_run_pipeline_blocks_when_package_build_fails(monkeypatch, tmp_path: Path) -> None:
    from swatplus_builder.workflows.full_build import FullModelBuildResult

    seen = {}

    def fake_build_full_model(**kwargs):
        seen["hru_mode"] = kwargs.get("hru_mode")
        seen["min_hru_fraction"] = kwargs.get("min_hru_fraction")
        report = tmp_path / "reports" / "overlay_repair" / "overlay_repair_report.json"
        report.parent.mkdir(parents=True)
        report.write_text('{"reason":"categorical_overlay_gap_too_large"}\n', encoding="utf-8")
        return FullModelBuildResult(
            success=False,
            status="BLOCKED",
            outdir=str(tmp_path),
            blocker_class="external_data_provider_unreachable",
            message="provider unavailable",
            diagnostic_artifacts={"overlay_repair_report": str(report)},
        )

    monkeypatch.setattr("swatplus_builder.workflows.full_build.build_full_model", fake_build_full_model)

    summary = run_pipeline(
        "01654000",
        tmp_path,
        start_date="2010-01-01",
        end_date="2010-01-10",
        hru_mode="full_overlay",
        min_hru_fraction=0.001,
    )

    assert summary["status"] == "BLOCKED"
    assert seen == {"hru_mode": "full_overlay", "min_hru_fraction": 0.001}
    assert summary["blocker_class"] == "external_data_provider_unreachable"
    assert summary["build"]["blocker_class"] == "external_data_provider_unreachable"
    assert summary["build"]["diagnostic_artifacts"]["overlay_repair_report"].endswith(
        "overlay_repair_report.json"
    )
    assert summary["locked_calibration_ready"] is False
    run_config = json.loads((tmp_path / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["build"]["diagnostic_artifacts"] == summary["build"]["diagnostic_artifacts"]


def test_run_pipeline_builds_when_txtinout_missing(monkeypatch, tmp_path: Path) -> None:
    from swatplus_builder.workflows.full_build import FullModelBuildResult

    def fake_build_full_model(**kwargs):
        txt = _write_prepared_run(Path(kwargs["outdir"]))
        return FullModelBuildResult(
            success=True,
            status="SUCCESS",
            outdir=str(kwargs["outdir"]),
            txtinout_dir=str(txt),
        )

    def fake_clean_and_run_solver(txtinout, **kwargs):
        return 0, "ok", ""

    monkeypatch.setattr("swatplus_builder.workflows.full_build.build_full_model", fake_build_full_model)
    monkeypatch.setattr("swatplus_builder.run.swatplus.clean_and_run_solver", fake_clean_and_run_solver)

    summary = run_pipeline("01654000", tmp_path, start_date="2010-01-01", end_date="2010-01-10")

    assert summary["status"] == "SUCCESS"
    assert summary["build"]["status"] == "SUCCESS"
    assert summary["locked_calibration_ready"] is True
    assert Path(summary["benchmark_lock_path"]).exists()


def test_run_pipeline_promotes_builder_soil_metadata(monkeypatch, tmp_path: Path) -> None:
    from swatplus_builder.workflows.full_build import FullModelBuildResult

    def fake_build_full_model(**kwargs):
        txt = _write_prepared_run(Path(kwargs["outdir"]))
        (Path(kwargs["outdir"]) / "metadata.json").write_text(
            json.dumps(
                {
                    "soil_mode": "fallback",
                    "soil_provenance_mode": "diagnostic_partial_gnatsgo_constant",
                    "pct_fallback_soils": 1.0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return FullModelBuildResult(
            success=True,
            status="SUCCESS",
            outdir=str(kwargs["outdir"]),
            txtinout_dir=str(txt),
        )

    def fake_clean_and_run_solver(txtinout, **kwargs):
        return 0, "ok", ""

    monkeypatch.setattr("swatplus_builder.workflows.full_build.build_full_model", fake_build_full_model)
    monkeypatch.setattr("swatplus_builder.run.swatplus.clean_and_run_solver", fake_clean_and_run_solver)

    summary = run_pipeline(
        "03353000",
        tmp_path,
        start_date="2010-01-01",
        end_date="2010-01-10",
        allow_diagnostic_fallbacks=True,
    )

    assert summary["status"] == "SUCCESS"
    assert summary["soil_mode"] == "fallback"
    assert summary["soil_provenance_mode"] == "diagnostic_partial_gnatsgo_constant"
    assert summary["pct_fallback_soils"] == 1.0
    assert summary["metadata_path"].endswith("metadata.json")


def test_run_pipeline_backfills_soil_provenance_from_metadata_notes(monkeypatch, tmp_path: Path) -> None:
    from swatplus_builder.workflows.full_build import FullModelBuildResult

    def fake_build_full_model(**kwargs):
        txt = _write_prepared_run(Path(kwargs["outdir"]))
        (Path(kwargs["outdir"]) / "metadata.json").write_text(
            json.dumps(
                {
                    "soil_mode": "fallback",
                    "soil_provenance_mode": None,
                    "pct_fallback_soils": 1.0,
                    "notes": [
                        "hru_soil_overlay_source=constant_representative_after_partial_gnatsgo_gap",
                        "soil_provenance_mode=diagnostic_partial_gnatsgo_constant",
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return FullModelBuildResult(
            success=True,
            status="SUCCESS",
            outdir=str(kwargs["outdir"]),
            txtinout_dir=str(txt),
        )

    def fake_clean_and_run_solver(txtinout, **kwargs):
        return 0, "ok", ""

    monkeypatch.setattr("swatplus_builder.workflows.full_build.build_full_model", fake_build_full_model)
    monkeypatch.setattr("swatplus_builder.run.swatplus.clean_and_run_solver", fake_clean_and_run_solver)

    summary = run_pipeline(
        "03353000",
        tmp_path,
        start_date="2010-01-01",
        end_date="2010-01-10",
        allow_diagnostic_fallbacks=True,
    )

    assert summary["soil_mode"] == "fallback"
    assert summary["soil_provenance_mode"] == "diagnostic_partial_gnatsgo_constant"
    assert summary["pct_fallback_soils"] == 1.0


def test_run_pipeline_clean_rerun_locks_existing_prepared_outputs(monkeypatch, tmp_path: Path) -> None:
    txt = _write_prepared_run(tmp_path)

    def fake_clean_and_run_solver(txtinout, **kwargs):
        assert Path(txtinout) == txt
        return 0, "ok", ""

    monkeypatch.setattr("swatplus_builder.run.swatplus.clean_and_run_solver", fake_clean_and_run_solver)

    summary = run_pipeline("01654000", tmp_path, start_date="2010-01-01", end_date="2010-01-10")

    assert summary["status"] == "SUCCESS"
    assert summary["full_routing_fixes_applied"] is True
    assert summary["fresh_engine_run"] is True
    assert summary["locked_calibration_ready"] is True
    assert Path(summary["dashboard_html"]).is_file()
    persisted = json.loads((tmp_path / "run_config.json").read_text(encoding="utf-8"))
    assert persisted["dashboard_html"] == summary["dashboard_html"]
    assert " tot " not in (txt / "rout_unit.con").read_text(encoding="utf-8")
    assert Path(summary["benchmark_lock_path"]).exists()
    lock = json.loads(Path(summary["benchmark_lock_path"]).read_text(encoding="utf-8"))
    assert lock["basin_id"] == "usgs_01654000"
    assert lock["outlet_policy"] == "strict"


def test_run_pipeline_promotes_prepared_run_soil_metadata(monkeypatch, tmp_path: Path) -> None:
    _write_prepared_run(tmp_path)
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "soil_mode": "fallback",
                "soil_provenance_mode": None,
                "pct_fallback_soils": 1.0,
                "notes": ["soil_provenance_mode=diagnostic_partial_gnatsgo_constant"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_clean_and_run_solver(txtinout, **kwargs):
        return 0, "ok", ""

    monkeypatch.setattr("swatplus_builder.run.swatplus.clean_and_run_solver", fake_clean_and_run_solver)

    summary = run_pipeline("03353000", tmp_path, start_date="2010-01-01", end_date="2010-01-10")

    assert summary["status"] == "SUCCESS"
    assert summary["soil_mode"] == "fallback"
    assert summary["soil_provenance_mode"] == "diagnostic_partial_gnatsgo_constant"
    assert summary["pct_fallback_soils"] == 1.0
    assert summary["metadata_path"].endswith("metadata.json")
