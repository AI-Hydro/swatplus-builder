from __future__ import annotations

from textwrap import dedent

from scripts import run_multibasin_e2e
from scripts.run_multibasin_e2e import SiteResult, parse_terminal_channel_ids
from swatplus_builder.errors import SwatBuilderPipelineError


def test_parse_terminal_channel_ids_uses_gis_id(tmp_path) -> None:
    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    p = txt / "chandeg.con"
    p.write_text(
        dedent(
            """\
            chandeg.con
            id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
            100 cha0100 7 0 0 0 0 1 s 0 0 0 1 out 1 tot 1.0
            101 cha0101 8 0 0 0 0 1 s 0 0 0 1 sdc 1 tot 1.0
            """
        ),
        encoding="utf-8",
    )

    assert parse_terminal_channel_ids(txt) == {7}


def test_multibasin_cli_accepts_custom_simulation_window(monkeypatch, tmp_path) -> None:
    seen: dict[str, str] = {}

    def _fake_run_site(usgs_id, out_root, log_path, run_engine, *, sim_start, sim_end):
        seen["sim_start"] = sim_start
        seen["sim_end"] = sim_end
        return run_multibasin_e2e.SiteResult(
            usgs_id=usgs_id,
            status="success",
            run_dir=str(out_root / f"usgs_{usgs_id}"),
            elapsed_s=0.0,
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_multibasin_e2e, "run_site", _fake_run_site)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_multibasin_e2e.py",
            "--sites",
            "03339000",
            "--batch-name",
            "window_test",
            "--start",
            "2013-01-01",
            "--end",
            "2015-12-31",
        ],
    )

    assert run_multibasin_e2e.main() == 0
    assert seen == {"sim_start": "2013-01-01", "sim_end": "2015-12-31"}


# ---------------------------------------------------------------------------
# Topology gate failure classification in batch runner
# ---------------------------------------------------------------------------

class TestTopologyGateClassification:
    """run_site() must classify SwatBuilderPipelineError topology failures."""

    def _fake_area(self, usgs_id: str) -> float:
        return 3340.879

    def _make_run_site_with_exc(self, exc: Exception, monkeypatch, tmp_path) -> SiteResult:
        """Patch demo.main to raise exc and call run_site directly."""
        import examples.single_basin_workflow as demo

        monkeypatch.setattr(demo, "main", lambda *a, **kw: (_ for _ in ()).throw(exc))
        monkeypatch.setattr(run_multibasin_e2e, "get_basin_area_km2", self._fake_area)

        out_root = tmp_path / "batch"
        log_path = out_root / "log.jsonl"
        return run_multibasin_e2e.run_site(
            "03339000", out_root, log_path, run_engine=False,
            sim_start="2013-01-01", sim_end="2015-12-31",
        )

    def test_area_mismatch_classified(self, monkeypatch, tmp_path):
        exc = SwatBuilderPipelineError(
            "Delineation area mismatch: generated 0.27 km² is only 0.008% of expected 3340.9 km²",
            generated_area_km2=0.27,
            expected_area_km2=3340.879,
            area_ratio=8e-5,
            n_subbasins=1,
            n_channels=5334,
            n_terminals=20,
        )
        result = self._make_run_site_with_exc(exc, monkeypatch, tmp_path)
        assert result.status == "topology_gate_failure"
        assert result.topology_failure_class == "area_mismatch"
        assert result.topology_failure_detail is not None
        assert "0.27" in result.topology_failure_detail or "generated" in result.topology_failure_detail

    def test_channel_explosion_classified(self, monkeypatch, tmp_path):
        exc = SwatBuilderPipelineError(
            "Channel explosion: 5331 channels across 1 subbasin(s)",
            n_subbasins=1,
            n_channels=5331,
            channels_per_subbasin=5331.0,
            max_channels_per_subbasin=50.0,
        )
        result = self._make_run_site_with_exc(exc, monkeypatch, tmp_path)
        assert result.status == "topology_gate_failure"
        assert result.topology_failure_class == "channel_explosion"

    def test_generic_pipeline_error_is_still_failed(self, monkeypatch, tmp_path):
        exc = SwatBuilderPipelineError("Some other pipeline error", reason="unknown")
        result = self._make_run_site_with_exc(exc, monkeypatch, tmp_path)
        assert result.status == "failed"
        assert result.topology_failure_class is None

    def test_topology_gate_failure_appears_in_summary_md(self, monkeypatch, tmp_path):
        exc = SwatBuilderPipelineError(
            "Delineation area mismatch: generated 0.27 km² is only 0.008% of expected 3340.9 km²",
            generated_area_km2=0.27,
            expected_area_km2=3340.879,
            area_ratio=8e-5,
            n_subbasins=1,
            n_channels=5334,
            n_terminals=20,
        )
        import examples.single_basin_workflow as demo

        monkeypatch.setattr(demo, "main", lambda *a, **kw: (_ for _ in ()).throw(exc))
        monkeypatch.setattr(run_multibasin_e2e, "get_basin_area_km2", self._fake_area)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "sys.argv",
            ["run_multibasin_e2e.py", "--sites", "03339000",
             "--batch-name", "topo_test", "--start", "2015-01-01", "--end", "2015-12-31"],
        )
        run_multibasin_e2e.main()
        md = (tmp_path / "tests/_artifacts/e2e_runs/topo_test/README.md").read_text()
        assert "topology_gate_failure" in md
        assert "Topology Gate Failures" in md
        assert "area_mismatch" in md


def test_failed_site_preserves_basin_area(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(run_multibasin_e2e, "get_basin_area_km2", lambda _site: 42.5)

    def _raise_failure(*_args, **_kwargs):
        raise RuntimeError("synthetic delineation failure")

    monkeypatch.setattr(run_multibasin_e2e.demo, "main", _raise_failure)

    result = run_multibasin_e2e.run_site(
        "03339000",
        tmp_path,
        tmp_path / "investigation_log.jsonl",
        run_engine=True,
        sim_start="2013-01-01",
        sim_end="2015-12-31",
    )

    assert result.status == "failed"
    assert result.basin_area_km2 == 42.5
    assert "synthetic delineation failure" in (result.error or "")
