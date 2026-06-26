from __future__ import annotations

import json
from pathlib import Path

import pytest

from swatplus_builder.output.dashboard import (
    _collect_all_data,
    _render_html,
    build_dashboard,
)


def test_dashboard_separates_engine_completion_from_governance(tmp_path: Path) -> None:
    (tmp_path / "run_config.json").write_text(
        json.dumps({"usgs_id": "01234567", "status": "SUCCESS"}),
        encoding="utf-8",
    )

    data = _collect_all_data(tmp_path)

    assert data["execution_status"] == "SUCCESS"
    assert data["status"] == "SUCCESS"
    assert data["governance_evaluated"] is False
    html = _render_html(data)
    assert "Engine completed" in html
    assert "Scientific claim governance was not evaluated" in html
    assert "Scientific Status" in html


def test_dashboard_evidence_block_overrides_engine_success(tmp_path: Path) -> None:
    (tmp_path / "run_config.json").write_text(
        json.dumps({"usgs_id": "01234567", "status": "SUCCESS"}),
        encoding="utf-8",
    )
    (tmp_path / "evidence_summary.json").write_text(
        json.dumps({"success": False, "status": "pipeline_blocked"}),
        encoding="utf-8",
    )

    data = _collect_all_data(tmp_path)

    assert data["execution_status"] == "SUCCESS"
    assert data["status"] == "BLOCKED"
    assert data["governance_evaluated"] is True


def test_dashboard_json_payload_cannot_close_script_element() -> None:
    html = _render_html({"usgs_id": "x", "note": "</script><script>alert(1)</script>"})

    assert "</script><script>alert(1)</script>" not in html
    assert "<\\/script><script>alert(1)<\\/script>" in html


def test_dashboard_embeds_spatial_model_layers(tmp_path: Path) -> None:
    gpd = pytest.importorskip("geopandas")
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    from rasterio.transform import from_bounds
    from shapely.geometry import LineString, Point, box

    vector_data = [
        ("raw/basin_boundary.gpkg", [box(-86.2, 40.0, -86.0, 40.2)]),
        ("delin/shapes/subbasins.gpkg", [box(-86.15, 40.05, -86.05, 40.15)]),
        ("delin/shapes/channels.gpkg", [LineString([(-86.15, 40.15), (-86.05, 40.05)])]),
        ("delin/shapes/outlets.gpkg", [Point(-86.05, 40.05)]),
        ("delin/hrus/hrus.gpkg", [box(-86.14, 40.06, -86.06, 40.14)]),
    ]
    for relative, geometries in vector_data:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame({"name": [path.stem]}, geometry=geometries, crs="EPSG:4326").to_file(
            path,
            driver="GPKG",
        )

    dem = tmp_path / "delin" / "rasters" / "dem_conditioned.tif"
    dem.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        width=8,
        height=8,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(-86.2, 40.0, -86.0, 40.2, 8, 8),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.arange(64, dtype="float32").reshape(8, 8), 1)

    (tmp_path / "run_config.json").write_text(
        json.dumps({"usgs_id": "01234567", "status": "SUCCESS"}),
        encoding="utf-8",
    )
    out = build_dashboard(tmp_path)
    html = out.read_text(encoding="utf-8")

    assert "Basin and model spatial inspector" in html
    assert "Reference basin (1)" in html
    assert "Stream network (1)" in html
    assert '"type": "raster"' in html
    assert "L.control.scale" in html


def test_dashboard_collects_locked_calibration_artifacts(tmp_path: Path) -> None:
    cal_dir = tmp_path / "calibration" / "calibration_reports_locked"
    cal_dir.mkdir(parents=True)
    history = cal_dir / "history.csv"
    history.write_text(
        "eval_idx,metric_nse,metric_kge,metric_pbias\n0,0.1,0.2,5.0\n1,0.3,0.4,2.0\n",
        encoding="utf-8",
    )
    best = cal_dir / "best_solution.json"
    best.write_text(
        json.dumps(
            {
                "parameters": {"CN2": 75.0},
                "selection_policy": "staged_volume_baseflow_peaks_then_nse_kge",
                "screening_window": {"score_start": "2010-01-01", "score_end": "2012-12-31"},
                "calibration_protocol": [{"phase": "volume", "parameters": ["CN2"]}],
            }
        ),
        encoding="utf-8",
    )
    progress = cal_dir / "calibration_progress.json"
    progress.write_text(
        json.dumps(
            {
                "status": "complete",
                "phase": "volume",
                "completed_evaluations": 2,
                "total_budget": 4,
                "updated_at_utc": "2026-06-26T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    locked_txt = tmp_path / "calibration" / "locked_calibrated_TxtInOut"
    locked_txt.mkdir(parents=True)
    locked_alignment = locked_txt / "alignment_calibration.csv"
    locked_alignment.write_text("date,obs,sim\n2010-01-01,1.0,1.2\n", encoding="utf-8")
    (tmp_path / "benchmark").mkdir()
    (tmp_path / "benchmark" / "alignment.csv").write_text("date,obs,sim\n2010-01-01,1.0,0.8\n", encoding="utf-8")
    (tmp_path / "calibration_provenance.json").write_text(
        json.dumps(
            {
                "status": "done",
                "success": True,
                "provenance": {
                    "calibration_strategy": "diagnostic_guided_dds_window_screen_then_locked_verify",
                    "screening_window": {"score_start": "2010-01-01", "score_end": "2012-12-31"},
                    "benchmark_metrics": {"nse": 0.1, "kge": 0.2, "pbias": 5.0},
                    "verification_metrics": {"nse": 0.3, "kge": 0.4, "pbias": 2.0},
                    "verification_delta_metrics": {"nse": 0.2, "kge": 0.2, "pbias": -3.0},
                    "history_csv": str(history),
                    "best_solution_json": str(best),
                    "locked_calibrated_txtinout": str(locked_txt),
                    "final_metrics_authority": "verification_summary.json",
                    "temporary_candidate_metrics_allowed_as_final": False,
                },
            }
        ),
        encoding="utf-8",
    )

    data = _collect_all_data(tmp_path)
    html = _render_html(data)

    assert data["calibration_history"][0]["nse"] == 0.1
    assert data["best_solution"]["parameters"] == {"CN2": 75.0}
    assert data["calibration_progress"]["status"] == "complete"
    assert data["calibrated_alignment"]["sim"] == [1.2]
    assert data["calibration_verification_metrics"]["nse"] == 0.3
    assert "Calibration Method and Evidence" in html
    assert "Calibration progress" in html
    assert "Calibrated locked rerun" in html
    assert "Candidate/window metrics are provisional" in html
