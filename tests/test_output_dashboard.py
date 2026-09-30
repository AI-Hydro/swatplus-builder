from __future__ import annotations

import json
from pathlib import Path

import pytest

from swatplus_builder.output.dashboard import (
    _collect_all_data,
    _dashboard_masthead_data_uri,
    _render_html,
    _vendor_assets,
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


def test_dashboard_embeds_brand_masthead_and_accurate_license_attribution() -> None:
    masthead = _dashboard_masthead_data_uri()
    html = _render_html({"usgs_id": "01234567", "generated_at": "2026-07-12T00:00:00"})

    assert masthead.startswith("data:image/webp;base64,")
    assert masthead in html
    assert "© ' + esc(copyrightYears) + ' Mohammad Galib" in html
    assert "MIT License" in html
    assert "respective owners and terms" in html
    # Third-party notices in the inlined libraries are theirs, not ours.
    own = html
    for text in _vendor_assets().values():
        own = own.replace(text, "")
    assert "all rights reserved" not in own.lower()
    assert 'name="theme-color"' in html
    assert "Auditable SWAT+ model evidence" in html


def test_dashboard_uses_source_backed_station_name_in_hero(tmp_path: Path) -> None:
    (tmp_path / "run_config.json").write_text(
        json.dumps({"usgs_id": "01547700", "status": "SUCCESS"}),
        encoding="utf-8",
    )
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "notes": [
                    "usgs_site_metadata: station_nm=Marsh Creek at Blanchard, PA; "
                    "source=https://waterservices.usgs.gov"
                ]
            }
        ),
        encoding="utf-8",
    )

    data = _collect_all_data(tmp_path)
    html = _render_html(data)

    assert data["station_name"] == "Marsh Creek at Blanchard, PA"
    assert "Marsh Creek at Blanchard, PA" in html
    assert "USGS ' + basin" in html


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
                    "validation_metrics": {"nse": 0.25, "kge": 0.35, "pbias": 3.0},
                    "validation_period": ["2013-01-01", "2014-12-31"],
                    "validation_transfer_passed": True,
                    "sensitivity_screen_activity_classes": {"CN2": "active"},
                    "skill_diagnostics": {
                        "skill_parameter_bound_hits": {
                            "CN2": {"boundary": "upper", "value": 75.0}
                        }
                    },
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
    assert data["calibration_validation_metrics"]["nse"] == 0.25
    assert data["calibration_validation_period"] == ["2013-01-01", "2014-12-31"]
    assert data["calibration_parameter_details"][0]["activity"] == "active"
    assert data["calibration_parameter_details"][0]["boundary"] == "upper"
    assert "Calibration Method and Evidence" in html
    assert "Calibration progress" in html
    assert "calibrated locked rerun" in html
    assert "Candidate/window metrics are provisional" in html
    assert "Metric authority" in html
    assert "Verified calibration metrics" in html
    assert "Withhold and test" in html
    assert "30-day mean" in html
    assert "Daily" in html
    assert "Log" in html
    assert "Dashboard views" in html
    assert "['hydrology','Hydrology']" in html
    assert "overflow-x: auto" in html


def test_dashboard_prefers_locked_benchmark_metrics_and_alignment(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "benchmark").mkdir()
    (tmp_path / "reports" / "metrics.json").write_text(
        json.dumps({"nse": -9.0, "kge": -9.0, "pbias": -99.0}),
        encoding="utf-8",
    )
    (tmp_path / "outputs" / "alignment.csv").write_text(
        "date,obs,sim\n2010-01-01,1.0,0.0\n",
        encoding="utf-8",
    )
    (tmp_path / "benchmark" / "metrics.json").write_text(
        json.dumps({"nse": 0.3, "kge": 0.4, "pbias": 5.0}),
        encoding="utf-8",
    )
    (tmp_path / "benchmark" / "alignment.csv").write_text(
        "date,obs,sim\n2010-01-01,1.0,0.8\n",
        encoding="utf-8",
    )

    data = _collect_all_data(tmp_path)

    assert data["metrics"]["nse"] == 0.3
    assert data["alignment"]["sim"] == [0.8]
    assert data["metrics_source"].endswith("benchmark/metrics.json")
    assert data["alignment_source"].endswith("benchmark/alignment.csv")


def test_dashboard_is_self_contained_for_offline_use() -> None:
    html = _render_html({"usgs_id": "01234567"})
    vendor = _vendor_assets()

    # Plotly and Leaflet are inlined; nothing is fetched from a CDN.
    assert "<script src=" not in html
    assert '<link rel="stylesheet" href="http' not in html
    for text in vendor.values():
        assert text in html
    assert "plotly.js v3" in vendor["plotly.min.js"][:200]
    assert "Leaflet 1.9.4" in vendor["leaflet.js"][:200]
    # Plotly 3 rejects string axis titles; every title uses the object form.
    assert "title: '" not in html
    # Offline, the basemap is the only missing piece and the page says so.
    assert "basemap-offline-note" in html


def test_vendored_assets_match_recorded_hashes() -> None:
    import hashlib
    import re

    vendor_dir = Path(__file__).resolve().parents[1] / "src/swatplus_builder/output/vendor"
    table = (vendor_dir / "VENDORED.md").read_text(encoding="utf-8")
    recorded = dict(re.findall(r"\| `([\w.]+)` \|.*\| `([0-9a-f]{64})` \|", table))
    assert set(recorded) == {"plotly.min.js", "leaflet.js", "leaflet.css"}
    for name, digest in recorded.items():
        assert hashlib.sha256((vendor_dir / name).read_bytes()).hexdigest() == digest, name


def _audited_run(tmp_path: Path) -> Path:
    """A minimal run directory with hash-chained ledgers, sealed like the workflow seals them."""
    from swatplus_builder.audit.decisions import file_sha256
    from swatplus_builder.audit.ledger import HashChainedLedger

    (tmp_path / "evidence_summary.json").write_text('{"success": true}\n', encoding="utf-8")
    events = HashChainedLedger(tmp_path / "events.jsonl")
    events.append({"stage": "workflow", "status": "started", "time": "2026-01-01T00:00:00Z"})
    events.append({"stage": "environment", "status": "captured", "time": "2026-01-01T00:00:01Z",
                   "package_version": "9.9.9", "engine_revision": "61.0.2.61"})
    for i in range(3):
        events.append({"stage": "weather_gridmet", "status": "station_started", "station": i})
        events.append({"stage": "weather_gridmet", "status": "station_completed", "station": i})
    events.append({"stage": "pipeline", "status": "blocked", "time": "2026-01-01T00:01:00Z",
                   "blocker_class": "full_model_build_topology_failed"})
    events.append({"stage": "evidence_sealed", "status": "completed",
                   "artifacts_sha256": {"evidence_summary.json": file_sha256(tmp_path / "evidence_summary.json")}})
    decisions = HashChainedLedger(tmp_path / "decisions.jsonl")
    decisions.append({"kind": "decision", "decision_id": "d1", "decision_point": "effective_claim_tier",
                      "chosen": "exploratory", "decided_by": "package_rule", "rationale": "blocked",
                      "options": ["exploratory", "research_grade"]})
    decisions.append({"kind": "outcome", "decision_id": "d1", "outcome": {"blocked_claims": 13}})
    manifest = {"audit_ledgers": {
        "events": {"head_sha256": events.head, "records": events.count},
        "decisions": {"head_sha256": decisions.head, "records": decisions.count},
    }}
    (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_audit_view_verifies_ledgers_and_sealed_evidence(tmp_path: Path) -> None:
    from swatplus_builder.output.dashboard import _collect_audit

    audit = _collect_audit(_audited_run(tmp_path))

    assert audit["verification"]["mode"] == "sealed"
    assert audit["verification"]["ok"] is True
    assert [a["matches"] for a in audit["sealed_artifacts"]] == [True]
    stages = [(r["stage"], r["status"]) for r in audit["trail"]]
    # The six per-station events fold into one row.
    assert stages.count(("weather_gridmet", "stations")) == 1
    assert ("pipeline", "blocked") in stages
    row = next(r for r in audit["trail"] if r["status"] == "stations")
    assert row["detail"] == "3 completed, 3 started"
    assert "blocker_class: full_model_build_topology_failed" in next(
        r["detail"] for r in audit["trail"] if r["stage"] == "pipeline")
    assert audit["environment"]["package_version"] == "9.9.9"
    assert [d["kind"] for d in audit["decisions"]] == ["decision", "outcome"]
    assert audit["decisions"][1]["point"] == "effective_claim_tier"


def test_audit_view_flags_post_run_edits(tmp_path: Path) -> None:
    from swatplus_builder.output.dashboard import _collect_audit

    run = _audited_run(tmp_path)
    (run / "evidence_summary.json").write_text('{"success": true, "edited": 1}\n', encoding="utf-8")
    lines = (run / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"exploratory"', '"research_grade"', 1)
    (run / "decisions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    audit = _collect_audit(run)

    assert audit["verification"]["ok"] is False
    assert audit["verification"]["ledgers"]["decisions"]["ok"] is False
    assert audit["verification"]["ledgers"]["events"]["ok"] is True
    assert [a["matches"] for a in audit["sealed_artifacts"]] == [False]


def test_audit_view_before_heads_are_sealed_checks_chains_only(tmp_path: Path) -> None:
    from swatplus_builder.output.dashboard import _collect_audit, _render_html

    run = _audited_run(tmp_path)
    (run / "run_manifest.json").unlink()

    audit = _collect_audit(run)

    assert audit["verification"]["mode"] == "chain_only"
    assert audit["verification"]["ok"] is True
    html = _render_html({"usgs_id": "x", "audit": audit})
    assert "['audit','Audit']" in html
    assert "swat audit verify" in html  # the chain-only view tells the modeller how to finish the check
