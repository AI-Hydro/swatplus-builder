from __future__ import annotations

from pathlib import Path

from swatplus_builder.full_mode.warmup import apply_warmup, remove_warmup, reset_and_apply_warmup


def _mk(tmp: Path) -> Path:
    t = tmp / "TxtInOut"
    t.mkdir()
    (t / "time.sim").write_text(
        "time.sim\n"
        "day_start yrc_start day_end yrc_end step\n"
        "1 2015 365 2015 0\n",
        encoding="utf-8",
    )
    (t / "print.prt").write_text(
        "print.prt\n"
        "nyskip day_start yrc_start day_end yrc_end interval\n"
        "0 1 2015 365 2015 1\n",
        encoding="utf-8",
    )
    return t


def test_apply_and_remove(tmp_path: Path):
    t = _mk(tmp_path)
    out = apply_warmup(t, 2)
    assert out["yrc_start_new"] == 2013
    remove_warmup(t, 2015)
    text = (t / "time.sim").read_text(encoding="utf-8")
    assert "2015" in text


def test_reset_and_apply(tmp_path: Path):
    t = _mk(tmp_path)
    apply_warmup(t, 2)
    out = reset_and_apply_warmup(t, warmup_years=3, evaluation_start_year=2015)
    assert out["yrc_start_new"] == 2012
