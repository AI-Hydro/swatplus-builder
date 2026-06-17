from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from swatplus_builder.types import SoilHorizon, SoilProfile
from swatplus_builder.workflows import full_build


def _load_basin_workflow_module():
    path = Path(__file__).resolve().parents[1] / "examples" / "usgs_basin_workflow.py"
    spec = importlib.util.spec_from_file_location("usgs_basin_workflow_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_weather_station_sampling_is_even_and_bounded() -> None:
    module = _load_basin_workflow_module()

    assert module._sample_evenly(list(range(10)), 4) == [0, 3, 6, 9]
    assert module._sample_evenly(list(range(10)), 1) == [5]
    assert module._sample_evenly([1, 2, 3], 5) == [1, 2, 3]


def test_basin_workflow_writes_successful_soil_report_artifact(tmp_path: Path) -> None:
    module = _load_basin_workflow_module()

    path = module._write_soil_report(
        tmp_path,
        {
            "soil_mode": "fallback",
            "soil_provenance_mode": "diagnostic_partial_gnatsgo_constant",
            "pct_fallback_soils": 1.0,
        },
    )

    assert path == tmp_path / "reports" / "soil_report.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["soil_mode"] == "fallback"
    assert payload["pct_fallback_soils"] == 1.0
    assert payload["source_priority"][0]["source"] == "gNATSGO_raster_plus_SDA_horizons"
    assert payload["source_priority"][0]["research_grade_eligible"] is True
    assert payload["source_priority"][-1]["source"] == "synthetic_minimal_soils"
    assert payload["source_priority"][-1]["research_grade_eligible"] is False


def test_basin_workflow_replaces_partial_default_soils_with_soilgrids(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_basin_workflow_module()

    def profile(name: str, source: str) -> SoilProfile:
        return SoilProfile(
            name=name,
            hyd_grp="B",
            source=source,
            layers=[
                SoilHorizon(
                    layer_num=1,
                    dp=1000.0,
                    bd=1.35,
                    awc=0.12,
                    soil_k=10.0,
                    carbon=1.0,
                    clay=25.0,
                    silt=35.0,
                    sand=40.0,
                    rock=0.0,
                    alb=0.13,
                    usle_k=0.28,
                    ec=0.0,
                )
            ],
        )

    def fake_soilgrids(mukeys, outdir, boundary_provenance):
        assert mukeys == [222]
        return [profile("gnatsgo_222", "soilgrids_v2_coarse")], 0

    monkeypatch.setattr(module, "_try_soilgrids_fallback", fake_soilgrids)

    profiles, replaced, failed = module._replace_default_profiles_with_soilgrids(
        [profile("gnatsgo_111", "sda_horizon"), profile("gnatsgo_222", "synthetic_default")],
        tmp_path,
        {},
    )

    assert replaced == 1
    assert failed == 0
    assert [p.source for p in profiles] == ["sda_horizon", "soilgrids_v2_coarse"]


def test_fetch_dem_reuses_same_gauge_authoritative_cache(monkeypatch, tmp_path: Path) -> None:
    module = _load_basin_workflow_module()
    monkeypatch.setattr(module, "STATION_ID", "01013500")

    class _Py3dep(types.ModuleType):
        def get_dem(self, *_args, **_kwargs):
            raise RuntimeError("Could not resolve host: prd-tnm.s3.amazonaws.com")

    monkeypatch.setitem(sys.modules, "py3dep", _Py3dep("py3dep"))

    cached = tmp_path / "swatplus_runs" / "objective_01013500" / "raw" / "dem.tif"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cached authoritative 3dep dem")
    out = tmp_path / "swatplus_runs" / "post_hardening_01013500_network" / "raw" / "dem.tif"

    class _Geometry:
        @property
        def iloc(self):
            return [object()]

    basin = SimpleNamespace(geometry=_Geometry())

    result = module.fetch_dem(basin, out, resolution_m=30)

    assert result == out
    assert out.read_bytes() == cached.read_bytes()
    sidecar = out.with_suffix(".source.json")
    assert sidecar.exists()
    assert "local_authoritative_3dep_cache" in sidecar.read_text(encoding="utf-8")


def test_datasets_db_reuses_local_authoritative_cache(monkeypatch, tmp_path: Path) -> None:
    module = _load_basin_workflow_module()
    monkeypatch.setattr(module, "STATION_ID", "01013500")

    def fail_fetch(*_args, **_kwargs):
        from swatplus_builder.errors import SwatBuilderExternalError

        raise SwatBuilderExternalError("Network error fetching datasets DB: urlopen error")

    monkeypatch.setattr("swatplus_builder.ref.bootstrap.ensure_datasets_db", fail_fetch)

    cached = (
        tmp_path
        / "swatplus_runs"
        / "objective_01013500"
        / "reference_dbs"
        / "swatplus_datasets-3.2.0.sqlite"
    )
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cached datasets sqlite")
    outdir = tmp_path / "swatplus_runs" / "post_hardening_01013500_network"

    settings = SimpleNamespace(reference_db_dir=outdir / "reference_dbs")
    result = module._ensure_datasets_db_with_local_cache(settings, outdir)

    assert result == outdir / "reference_dbs" / "swatplus_datasets.sqlite"
    assert result.read_bytes() == cached.read_bytes()
    sidecar = outdir / "reference_dbs" / "swatplus_datasets.source.json"
    assert sidecar.exists()
    assert "local_authoritative_swatplus_datasets_cache" in sidecar.read_text(encoding="utf-8")


def test_build_full_model_sets_usgs_id_before_loading_builder(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, str | None] = {}

    def fake_load_builder():
        seen["during_load"] = os.environ.get("USGS_ID")

        def main(outdir, **kwargs):
            seen["during_main"] = os.environ.get("USGS_ID")
            txt = Path(outdir) / "project" / "Scenarios" / "Default" / "TxtInOut"
            txt.mkdir(parents=True)
            (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")

        return SimpleNamespace(main=main)

    monkeypatch.delenv("USGS_ID", raising=False)
    monkeypatch.setattr(full_build, "_load_example_builder", fake_load_builder)

    result = full_build.build_full_model(
        usgs_id="01654000",
        outdir=tmp_path,
        start_date="2010-01-01",
        end_date="2010-01-10",
        warmup_years=3,
    )

    assert result.success is True
    assert seen["during_load"] == "01654000"
    assert seen["during_main"] == "01654000"
    assert os.environ.get("USGS_ID") is None


def test_build_full_model_allows_diagnostic_fallbacks_with_scoped_env(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, str | None] = {}

    def fake_load_builder():
        def main(outdir, **kwargs):
            seen["allow_synthetic"] = os.environ.get("SWATPLUS_ALLOW_SYNTHETIC_SOILS")
            seen["max_fallback"] = os.environ.get("SWATPLUS_MAX_SOIL_FALLBACK_RATIO")
            seen["hru_mode"] = os.environ.get("SWATPLUS_HRU_MODE")
            seen["min_hru_fraction"] = os.environ.get("SWATPLUS_MIN_HRU_FRACTION")
            txt = Path(outdir) / "project" / "Scenarios" / "Default" / "TxtInOut"
            txt.mkdir(parents=True)
            (txt / "file.cio").write_text("file.cio\n", encoding="utf-8")

        return SimpleNamespace(main=main)

    monkeypatch.delenv("SWATPLUS_ALLOW_SYNTHETIC_SOILS", raising=False)
    monkeypatch.delenv("SWATPLUS_MAX_SOIL_FALLBACK_RATIO", raising=False)
    monkeypatch.delenv("SWATPLUS_HRU_MODE", raising=False)
    monkeypatch.delenv("SWATPLUS_MIN_HRU_FRACTION", raising=False)
    monkeypatch.setattr(full_build, "_load_example_builder", fake_load_builder)

    result = full_build.build_full_model(
        usgs_id="03353000",
        outdir=tmp_path,
        start_date="2010-01-01",
        end_date="2010-01-10",
        warmup_years=3,
        allow_diagnostic_fallbacks=True,
        hru_mode="full_overlay",
        min_hru_fraction=0.001,
    )

    assert result.success is True
    assert seen == {
        "allow_synthetic": "1",
        "max_fallback": "1.0",
        "hru_mode": "full_overlay",
        "min_hru_fraction": "0.001",
    }
    assert os.environ.get("SWATPLUS_ALLOW_SYNTHETIC_SOILS") is None
    assert os.environ.get("SWATPLUS_MAX_SOIL_FALLBACK_RATIO") is None
    assert os.environ.get("SWATPLUS_HRU_MODE") is None
    assert os.environ.get("SWATPLUS_MIN_HRU_FRACTION") is None


def test_classify_dem_dns_failure_as_provider_unreachable() -> None:
    err = RuntimeError("fetch_dem failed after 4 attempts: CURL error: Could not resolve host")

    assert full_build._classify_build_error(err) == "external_data_provider_unreachable"


def test_classify_datasets_db_dns_failure_as_provider_unreachable() -> None:
    err = RuntimeError("Network error fetching datasets DB: <urlopen error [Errno 8] nodename nor servname provided>")

    assert full_build._classify_build_error(err) == "external_data_provider_unreachable"


def test_classify_planetary_computer_stac_timeout_as_provider_unreachable() -> None:
    err = RuntimeError(
        "fetch_mukey_raster failed after 4 attempts: Planetary Computer STAC "
        "query failed: The request exceeded the maximum allowed time"
    )

    assert full_build._classify_build_error(err) == "external_data_provider_unreachable"


def test_classify_missing_flow_accumulation_as_topology_failure() -> None:
    err = RuntimeError("delin/rasters/d8_flow_acc.tif: No such file or directory")

    assert full_build._classify_build_error(err) == "full_model_build_topology_failed"


def test_classify_whitebox_missing_output_as_topology_failure() -> None:
    err = RuntimeError("WhiteboxTools 'D8FlowAccumulation' did not create expected output.")

    assert full_build._classify_build_error(err) == "full_model_build_topology_failed"


def test_classify_gridmet_date_gap_as_weather_provider_gap() -> None:
    err = RuntimeError("GridMET returned 1105 rows for station 'x', expected 1106. The server may have clamped the date range.")

    assert full_build._classify_build_error(err) == "weather_provider_data_gap"


def test_classify_network_unreachable_as_external_provider() -> None:
    err = RuntimeError(
        "pydaymet.get_bycoords failed after 3 attempts: "
        "Cannot connect to host daymet.ornl.gov:443 ssl:default [Network is unreachable]"
    )

    assert full_build._classify_build_error(err) == "external_data_provider_unreachable"


def test_classify_hru_overlay_realism_gate() -> None:
    err = RuntimeError("HRU realism gate failed: too many delineated subbasins have no valid landuse/soil overlay.")

    assert full_build._classify_build_error(err) == "hru_overlay_realism_failed"


def test_classify_soil_realism_gate() -> None:
    err = RuntimeError("Soil realism gate failed: soil_mode=fallback, pct_fallback_soils=100.00%")

    assert full_build._classify_build_error(err) == "soil_realism_gate_failed"


class _EngineError(Exception):
    def __init__(self) -> None:
        super().__init__("SWAT+ engine exited 151")
        self.context = {
            "stdout_tail": "forrtl: severe (151): allocatable array is already allocated\n"
            "swatplus_exe _ru_read_elements 179 ru_read_elements.f90\n"
            "swatplus_exe _hyd_connect_ 141 hyd_connect.f90",
            "stderr_tail": "",
        }


def test_classify_hyd_connect_engine_failure_from_context() -> None:
    assert full_build._classify_build_error(_EngineError()) == "engine_hyd_connect_failed_during_build"


def test_build_full_model_preserves_external_error_context(monkeypatch, tmp_path: Path) -> None:
    def fake_load_builder():
        def main(*args, **kwargs):
            raise _EngineError()

        return SimpleNamespace(main=main)

    monkeypatch.setattr(full_build, "_load_example_builder", fake_load_builder)

    result = full_build.build_full_model(
        usgs_id="03351500",
        outdir=tmp_path,
        start_date="2010-01-01",
        end_date="2019-12-31",
        warmup_years=3,
    )

    assert result.success is False
    assert result.blocker_class == "engine_hyd_connect_failed_during_build"
    assert result.stdout_tail is not None
    assert "hyd_connect" in result.stdout_tail


def test_build_full_model_promotes_overlay_repair_report_on_failure(monkeypatch, tmp_path: Path) -> None:
    def fake_load_builder():
        def main(outdir, **kwargs):
            report = Path(outdir) / "reports" / "overlay_repair" / "overlay_repair_report.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"reason":"categorical_overlay_gap_too_large"}\n', encoding="utf-8")
            raise RuntimeError("HRU realism gate failed: overlay_repair_reason=categorical_overlay_gap_too_large")

        return SimpleNamespace(main=main)

    monkeypatch.setattr(full_build, "_load_example_builder", fake_load_builder)

    result = full_build.build_full_model(
        usgs_id="01013500",
        outdir=tmp_path,
        start_date="2010-01-01",
        end_date="2019-12-31",
        warmup_years=3,
    )

    assert result.success is False
    assert result.blocker_class == "hru_overlay_realism_failed"
    assert result.diagnostic_artifacts is not None
    assert result.diagnostic_artifacts["overlay_repair_report"].endswith("overlay_repair_report.json")
    assert result.to_dict()["diagnostic_artifacts"] == result.diagnostic_artifacts


def test_build_full_model_promotes_soil_acquisition_report_on_failure(monkeypatch, tmp_path: Path) -> None:
    def fake_load_builder():
        def main(outdir, **kwargs):
            report = Path(outdir) / "reports" / "soil_acquisition_report.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"soil_mode":"failed"}\n', encoding="utf-8")
            raise RuntimeError("Soil acquisition failed and synthetic soil fallback is disabled")

        return SimpleNamespace(main=main)

    monkeypatch.setattr(full_build, "_load_example_builder", fake_load_builder)

    result = full_build.build_full_model(
        usgs_id="09504500",
        outdir=tmp_path,
        start_date="2010-01-01",
        end_date="2019-12-31",
        warmup_years=3,
    )

    assert result.success is False
    assert result.blocker_class == "soil_realism_gate_failed"
    assert result.diagnostic_artifacts is not None
    assert result.diagnostic_artifacts["soil_acquisition_report"].endswith("soil_acquisition_report.json")


def test_build_full_model_writes_soil_realism_diagnostics_when_report_missing(monkeypatch, tmp_path: Path) -> None:
    def fake_main(outdir, **kwargs):
        raise RuntimeError("Soil realism gate failed: soil_mode=fallback, pct_fallback_soils=100.00%")

    monkeypatch.setattr(full_build, "_load_example_builder", lambda: SimpleNamespace(main=fake_main))
    result = full_build.build_full_model(
        usgs_id="02129000",
        outdir=tmp_path,
        start_date="2010-01-01",
        end_date="2019-12-31",
        warmup_years=3,
    )

    assert result.blocker_class == "soil_realism_gate_failed"
    assert result.diagnostic_artifacts is not None
    path = Path(result.diagnostic_artifacts["soil_realism_diagnostics"])
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["blocker_class"] == "soil_realism_gate_failed"
    assert payload["next_actions"]
    alternatives = {row["option"]: row for row in payload["source_backed_alternatives"]}
    assert "recover_gnatsgo_raster_plus_sda_horizons" in alternatives
    assert alternatives["recover_gnatsgo_raster_plus_sda_horizons"]["claim_impact"].startswith("research_grade")
    assert "query_usda_sda_spatial_representative_mukey" in alternatives
    assert "use_soilgrids_v2_coarse_gap_fill" in alternatives
    assert "allow_synthetic_or_constant_soils_for_engine_diagnostics_only" in alternatives
    assert payload["recommended_probe_order"][0]["diagnostic"] == "recover_gnatsgo_raster_plus_sda_horizons"
    assert payload["source_priority"][0]["source"] == "gNATSGO_raster_plus_SDA_horizons"
    assert payload["source_priority"][0]["research_grade_eligible"] is True
    assert any(row["source"] == "SoilGrids_v2_coarse" for row in payload["source_priority"])
    assert payload["source_priority"][-1]["source"] == "synthetic_minimal_soils"
    assert payload["source_priority"][-1]["research_grade_eligible"] is False
