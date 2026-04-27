from __future__ import annotations

from textwrap import dedent

from scripts import run_multibasin_e2e
from scripts.run_multibasin_e2e import parse_terminal_channel_ids


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
