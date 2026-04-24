from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from swatplus_builder.cli import app


def test_cli_diagnose_writes_report(tmp_path: Path) -> None:
    alignment = tmp_path / "alignment.csv"
    alignment.write_text(
        "date,obs,sim\n"
        "2015-01-01,0.1,0.1\n"
        "2015-01-02,0.2,0.2\n"
        "2015-01-03,1.5,0.3\n"
        "2015-01-04,1.0,0.4\n"
        "2015-01-05,0.5,1.8\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "diagnose",
            "--run-artifact",
            str(alignment),
        ],
    )
    assert res.exit_code == 0
    assert "swat diagnose" in res.stdout
    assert (tmp_path / "diagnostics.md").exists()
