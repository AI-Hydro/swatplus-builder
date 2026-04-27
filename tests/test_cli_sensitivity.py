from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from swatplus_builder.cli import app


def test_cli_sensitivity_requires_parameters(tmp_path: Path) -> None:
    runner = CliRunner()
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    res = runner.invoke(
        app,
        [
            "sensitivity",
            "--basin",
            "usgs_01547700",
            "--base-txtinout",
            str(txt),
            "--parameters",
            "",
            "--artifacts-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert res.exit_code == 2


def test_cli_sensitivity_happy_path_with_mock_backend(tmp_path: Path, monkeypatch) -> None:
    from swatplus_builder import sensitivity as sens_mod

    def _fake_run(self, req):  # noqa: ANN001
        outdir = req.artifacts_root / "runs" / "sensitivity" / "abc"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "indices.csv").write_text("parameter,s1,st\nCN2,0.4,0.6\n", encoding="utf-8")
        (outdir / "summary.md").write_text("# Sensitivity Summary\n", encoding="utf-8")
        return sens_mod.SensitivityResult(
            sensitivity_hash="abc",
            cache_hit=False,
            outdir=outdir,
            indices_csv=outdir / "indices.csv",
            summary_md=outdir / "summary.md",
            ranked=[sens_mod.SensitivityIndex(parameter="CN2", s1=0.4, st=0.6)],
        )

    monkeypatch.setattr(sens_mod.SensitivityAnalyzer, "run", _fake_run)

    runner = CliRunner()
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    res = runner.invoke(
        app,
        [
            "sensitivity",
            "--basin",
            "usgs_01547700",
            "--base-txtinout",
            str(txt),
            "--parameters",
            "CN2,ESCO",
            "--n-samples",
            "128",
            "--artifacts-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert res.exit_code == 0
    assert "swat sensitivity" in res.stdout
    assert "top_parameter=CN2" in res.stdout
