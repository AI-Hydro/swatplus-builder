"""Tests for :mod:`swatplus_builder.run.swatplus`.

Strategy
--------

The real SWAT+ engine is a multi-MB native binary that users install
separately. We therefore cover the wrapper with a **Python shim** masquerading
as ``swatplus_exe``: it reads ``file.cio`` from CWD, writes plausible outputs,
and exits with a configurable code. That is enough to exercise:

* cwd handling (``cd TxtInOut && exec``),
* ``OMP_NUM_THREADS`` plumbing,
* timeout enforcement,
* stdout / stderr / ``diagnostics.out`` tail capture,
* output file enumeration & well-known-path mapping,
* error translation (non-zero exit → :class:`SwatBuilderExternalError`).

An opt-in ``@pytest.mark.slow`` test honors ``$SWATPLUS_EXE`` for running the
*real* engine against a synthetic ``TxtInOut/`` when a user has a binary.
"""

from __future__ import annotations

import os
import stat
import sys
import textwrap
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fake-engine fixtures
# ---------------------------------------------------------------------------


def _write_shim(
    path: Path,
    *,
    exit_code: int = 0,
    sleep_s: float = 0.0,
    emit_diagnostics: bool = True,
    echo_threads_env: bool = False,
    emit_outputs: bool = True,
    revision: str | None = "61.0.2.61",
    output_header_revision: str | None = None,
) -> Path:
    """Write an executable Python shim that pretends to be ``swatplus_exe``.

    The shim is deliberately tiny and dependency-free so it runs in whatever
    interpreter CI exposes on PATH via the shebang.
    """
    body = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import os, sys, time, pathlib
        cwd = pathlib.Path.cwd()
        # Contract check: SWAT+ engine reads file.cio from CWD.
        cio = cwd / "file.cio"
        if not cio.is_file():
            print("MISSING_FILE_CIO", file=sys.stderr)
            raise SystemExit(42)
        # Mimic the real engine's startup banner so engine_version capture is exercised.
        if {revision!r} is not None:
            print("                   SWAT+")
            print("             Revision " + {revision!r})
            print("      Soil & Water Assessment Tool")
        print("fake swatplus_exe running in", cwd)
        print("OMP_NUM_THREADS=" + os.environ.get("OMP_NUM_THREADS", "?"))
        time.sleep({sleep_s!r})
        if {emit_diagnostics!r}:
            (cwd / "diagnostics.out").write_text(
                "SWAT+ fake diagnostics\\n"
                "threads=" + os.environ.get("OMP_NUM_THREADS", "?") + "\\n"
                "OK\\n"
            )
        if {emit_outputs!r}:
            (cwd / "basin_wb_aa.txt").write_text("title\\ncols\\nunits\\n1 2 3\\n")
            (cwd / "channel_sd_aa.txt").write_text("title\\ncols\\nunits\\n")
            (cwd / "hru_wb_aa.txt").write_text("title\\ncols\\nunits\\n")
            # Stamp the engine revision into an output-file header like the real
            # engine ("MODULAR Rev <year>.<rev>"). Controlled separately so tests
            # can make the header and banner disagree.
            if {output_header_revision!r} is not None:
                (cwd / "channel_sd_day.txt").write_text(
                    "basin   SWAT+ 2026-01-16   MODULAR Rev "
                    + {output_header_revision!r} + "\\njday mon day\\nunits\\n"
                )
        if {echo_threads_env!r}:
            print("THREADS_ECHO=" + os.environ.get("OMP_NUM_THREADS", "?"), file=sys.stderr)
        raise SystemExit({exit_code!r})
        """
    )
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def shim_bin(tmp_path: Path) -> Path:
    """A happy-path shim that writes a diagnostics.out and three output files."""
    return _write_shim(tmp_path / "swatplus_exe_shim")


@pytest.fixture
def txtinout(tmp_path: Path) -> Path:
    """Minimal TxtInOut/ with just a file.cio so the runner accepts it."""
    d = tmp_path / "TxtInOut"
    d.mkdir()
    (d / "file.cio").write_text(
        "file.cio: written by test\nsimulation: time.sim\n"
    )
    return d


# ---------------------------------------------------------------------------
# engine version: parsed from banner, never operator-asserted
# ---------------------------------------------------------------------------


class TestEngineVersion:
    """The engine revision must be READ from the binary's banner, not trusted
    from an operator-typed string. A binary mislabeled ``swatplus_exe.6057``
    that is actually rev 61 must not be recordable as 60.5.7."""

    def test_parse_revision_from_real_banner_shape(self):
        from swatplus_builder.run.swatplus import parse_engine_revision

        banner = (
            "                   SWAT+\n"
            "             Revision 61.0.2.61  \n"
            "      Soil & Water Assessment Tool\n"
            "GNU (13.4.0), 2026-01-16 19:36:44, Darwin\n"
        )
        assert parse_engine_revision(banner) == "61.0.2.61"

    def test_parse_revision_handles_dotted_and_legacy_forms(self):
        from swatplus_builder.run.swatplus import parse_engine_revision

        assert parse_engine_revision("Revision 60.5.7") == "60.5.7"
        assert parse_engine_revision("revision 61.0.2.61\n") == "61.0.2.61"
        assert parse_engine_revision("no banner here") is None
        assert parse_engine_revision("") is None
        assert parse_engine_revision(None) is None

    def test_parse_revision_from_output_header_strips_build_year(self):
        from swatplus_builder.run.swatplus import parse_engine_revision

        # Output-file header form carries a 4-digit build-year prefix; both the
        # banner ("Revision 61.0.2.61") and header ("Rev 2026.61.0.2.61") must
        # normalize to the same canonical revision.
        header = "usgs_03351500   SWAT+ 2026-01-16   MODULAR Rev 2026.61.0.2.61"
        assert parse_engine_revision(header) == "61.0.2.61"
        assert parse_engine_revision("MODULAR Rev 2025.60.5.7") == "60.5.7"

    def test_engine_revision_from_outputs_reads_persisted_header(self, tmp_path):
        from swatplus_builder.run.swatplus import engine_revision_from_outputs

        txt = tmp_path / "TxtInOut"
        txt.mkdir()
        # Only the header line matters; the engine stamps every output file.
        (txt / "channel_sd_day.txt").write_text(
            "basin SWAT+ 2026-01-16 MODULAR Rev 2026.61.0.2.61\njday\nunits\n"
        )
        assert engine_revision_from_outputs(txt) == "61.0.2.61"

    def test_engine_revision_from_outputs_none_when_unstamped(self, tmp_path):
        from swatplus_builder.run.swatplus import engine_revision_from_outputs

        txt = tmp_path / "TxtInOut"
        txt.mkdir()
        (txt / "channel_sd_day.txt").write_text("no revision header here\n")
        assert engine_revision_from_outputs(txt) is None
        assert engine_revision_from_outputs(tmp_path / "absent") is None

    def test_run_prefers_persisted_output_header_over_stdout_banner(self, txtinout, tmp_path):
        from swatplus_builder.run.swatplus import run

        # Header and banner deliberately disagree: the persisted artifact wins,
        # because it is the auditable record of what actually produced outputs.
        shim = _write_shim(
            tmp_path / "swatplus_exe_shim",
            revision="99.9.9.9",  # stdout banner (weaker source)
            output_header_revision="2026.61.0.2.61",  # persisted header (authoritative)
        )
        result = run(txtinout, binary=shim, threads=1, timeout_s=30)
        assert result.engine_version == "61.0.2.61"

    def test_verify_records_banner_over_disagreeing_assertion(self):
        from swatplus_builder.run.swatplus import verify_engine_version

        verdict = verify_engine_version("60.5.7", "61.0.2.61")
        assert verdict["engine_version"] == "61.0.2.61"  # banner wins
        assert verdict["verified"] is True
        assert verdict["mismatch"] is True
        assert "disagrees" in verdict["reason"]

    def test_verify_accepts_matching_assertion(self):
        from swatplus_builder.run.swatplus import verify_engine_version

        verdict = verify_engine_version("61.0.2.61", "61.0.2.61")
        assert verdict["mismatch"] is False
        assert verdict["verified"] is True

    def test_verify_unknown_assertion_takes_banner_without_mismatch(self):
        from swatplus_builder.run.swatplus import verify_engine_version

        for asserted in ("unknown", "", None):
            verdict = verify_engine_version(asserted, "61.0.2.61")
            assert verdict["engine_version"] == "61.0.2.61"
            assert verdict["mismatch"] is False
            assert verdict["verified"] is True

    def test_verify_without_banner_is_unverified_fallback(self):
        from swatplus_builder.run.swatplus import verify_engine_version

        verdict = verify_engine_version("60.5.7", None)
        assert verdict["engine_version"] == "60.5.7"
        assert verdict["verified"] is False

    def test_run_captures_engine_version_from_banner(self, txtinout, tmp_path):
        from swatplus_builder.run.swatplus import run

        shim = _write_shim(tmp_path / "swatplus_exe_shim", revision="61.0.2.61")
        result = run(txtinout, binary=shim, threads=1, timeout_s=30)
        assert result.success
        assert result.engine_version == "61.0.2.61"

    def test_run_engine_version_none_when_banner_absent(self, txtinout, tmp_path):
        from swatplus_builder.run.swatplus import run

        shim = _write_shim(tmp_path / "swatplus_exe_noban", revision=None)
        result = run(txtinout, binary=shim, threads=1, timeout_s=30)
        assert result.success
        assert result.engine_version is None


# ---------------------------------------------------------------------------
# locate_binary
# ---------------------------------------------------------------------------


class TestLocateBinary:
    def test_settings_override_wins(self, tmp_path, monkeypatch):
        from swatplus_builder.config import DEFAULT_SETTINGS, Settings
        from swatplus_builder.run.swatplus import locate_binary

        fake = tmp_path / "engine"
        fake.write_text("")
        settings = Settings(
            **{**DEFAULT_SETTINGS.model_dump(), "swatplus_exe": fake}
        )
        # Even if env and PATH both have candidates, settings wins.
        monkeypatch.setenv("SWATPLUS_EXE", "/does/not/exist")
        assert locate_binary(settings).resolve() == fake.resolve()

    def test_env_var_used_when_no_settings_override(self, tmp_path, monkeypatch):
        from swatplus_builder.run.swatplus import locate_binary

        fake = tmp_path / "engine_env"
        fake.write_text("")
        monkeypatch.setenv("SWATPLUS_EXE", str(fake))
        assert locate_binary().resolve() == fake.resolve()

    def test_env_var_missing_file_raises_actionable(self, monkeypatch):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.run.swatplus import locate_binary

        monkeypatch.setenv("SWATPLUS_EXE", "/no/such/file")
        with pytest.raises(SwatBuilderExternalError) as ei:
            locate_binary()
        assert ei.value.context.get("source") == "env"

    def test_path_scan_last(self, tmp_path, monkeypatch):
        """When nothing else matches, we fall back to $PATH / shutil.which."""
        from swatplus_builder.run.swatplus import BINARY_CANDIDATES, locate_binary

        # Create a binary whose NAME matches one of BINARY_CANDIDATES, put its
        # dir on PATH, and make sure shutil.which picks it up.
        fake_dir = tmp_path / "bin"
        fake_dir.mkdir()
        target_name = BINARY_CANDIDATES[0]
        fake = fake_dir / target_name
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)

        monkeypatch.delenv("SWATPLUS_EXE", raising=False)
        monkeypatch.setenv("PATH", str(fake_dir))
        assert locate_binary().resolve() == fake.resolve()

    def test_not_found_raises_actionable(self, monkeypatch):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.run.swatplus import locate_binary

        monkeypatch.delenv("SWATPLUS_EXE", raising=False)
        monkeypatch.setenv("PATH", "")
        with pytest.raises(SwatBuilderExternalError) as ei:
            locate_binary()
        assert "candidates" in ei.value.context


# ---------------------------------------------------------------------------
# run() — happy and sad paths via the Python shim
# ---------------------------------------------------------------------------


class TestRunHappy:
    def test_basic_run_populates_result(self, txtinout, shim_bin):
        from swatplus_builder.run.swatplus import run

        result = run(txtinout, threads=2, binary=shim_bin)

        assert result.success
        assert result.exit_code == 0
        assert result.runtime_seconds >= 0.0
        assert result.binary == shim_bin.resolve()
        assert result.txtinout_dir == txtinout.resolve()
        assert result.command[0] == str(shim_bin.resolve())
        assert len(result.command) == 1, "engine takes no CLI args"

    def test_output_files_enumerated(self, txtinout, shim_bin):
        from swatplus_builder.run.swatplus import run

        result = run(txtinout, binary=shim_bin)
        names = {p.name for p in result.output_files}
        # Three emitted .txt + one .out from the shim
        assert names == {
            "diagnostics.out",
            "basin_wb_aa.txt",
            "channel_sd_aa.txt",
            "hru_wb_aa.txt",
        }

    def test_well_known_paths_mapped(self, txtinout, shim_bin):
        from swatplus_builder.run.swatplus import run

        result = run(txtinout, binary=shim_bin)
        assert "diagnostics" in result.paths
        assert result.paths["diagnostics"].name == "diagnostics.out"
        assert "basin_wb_aa" in result.paths
        assert result.paths["basin_wb_aa"].parent == txtinout.resolve()

    def test_diagnostics_tail_captured(self, txtinout, shim_bin):
        from swatplus_builder.run.swatplus import run

        result = run(txtinout, threads=3, binary=shim_bin)
        assert "threads=3" in result.diagnostics_tail
        assert "OK" in result.diagnostics_tail

    def test_omp_num_threads_passed_to_child(self, txtinout, tmp_path):
        """Prove OMP_NUM_THREADS is injected — the shim echoes it."""
        from swatplus_builder.run.swatplus import run

        shim = _write_shim(tmp_path / "echo_shim", echo_threads_env=True)
        result = run(txtinout, threads=7, binary=shim)
        assert "THREADS_ECHO=7" in result.stderr_tail

    def test_threads_clamped_to_minimum_one(self, txtinout, tmp_path):
        from swatplus_builder.run.swatplus import run

        shim = _write_shim(tmp_path / "clamp_shim", echo_threads_env=True)
        result = run(txtinout, threads=0, binary=shim)
        assert "THREADS_ECHO=1" in result.stderr_tail


class TestRunSad:
    def test_missing_txtinout_dir_raises_input_error(self, tmp_path, shim_bin):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.run.swatplus import run

        with pytest.raises(SwatBuilderInputError):
            run(tmp_path / "nope", binary=shim_bin)

    def test_missing_file_cio_raises_input_error(self, tmp_path, shim_bin):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.run.swatplus import run

        empty = tmp_path / "empty_txt"
        empty.mkdir()
        with pytest.raises(SwatBuilderInputError) as ei:
            run(empty, binary=shim_bin)
        assert "file.cio" in str(ei.value)

    def test_nonzero_exit_translates_to_external_error_with_context(
        self, txtinout, tmp_path
    ):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.run.swatplus import run

        shim = _write_shim(
            tmp_path / "bad_shim", exit_code=7, emit_diagnostics=True,
        )
        with pytest.raises(SwatBuilderExternalError) as ei:
            run(txtinout, binary=shim)
        assert ei.value.context["returncode"] == 7
        # Even on failure we surface the diagnostics tail the engine wrote.
        assert "OK" in ei.value.context["diagnostics_tail"]


class TestLargeBasinGuardrails:
    def _make_run_layout(self, tmp_path: Path, *, n_subbasins: int, n_hrus: int) -> tuple[Path, Path]:
        run_root = tmp_path / "run"
        txt = run_root / "project" / "Scenarios" / "Default" / "TxtInOut"
        txt.mkdir(parents=True)
        (txt / "file.cio").write_text("file.cio: test\n")

        delin = run_root / "delin"
        (delin / "hrus").mkdir(parents=True)
        (delin / "watershed_result.json").write_text(
            json.dumps({"stats": {"n_subbasins": n_subbasins}}),
            encoding="utf-8",
        )
        (delin / "hrus" / "hru_catalog.json").write_text(
            json.dumps({"stats": {"n_hrus": n_hrus}}),
            encoding="utf-8",
        )
        return run_root, txt

    def test_guardrail_warns_and_continues_when_auto_adjust_true(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from swatplus_builder.run.swatplus import run

        _root, txt = self._make_run_layout(tmp_path, n_subbasins=700, n_hrus=9000)
        shim = _write_shim(tmp_path / "ok_shim")

        with caplog.at_level("WARNING"):
            result = run(
                txt,
                binary=shim,
                max_subbasins=500,
                max_hrus=5000,
                auto_adjust=True,
            )

        assert result.success
        assert "Large-basin guardrail triggered" in caplog.text

    def test_guardrail_fails_fast_when_auto_adjust_disabled(self, tmp_path: Path) -> None:
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.run.swatplus import run

        _root, txt = self._make_run_layout(tmp_path, n_subbasins=700, n_hrus=9000)
        shim = _write_shim(tmp_path / "unused_shim")

        with pytest.raises(SwatBuilderInputError) as ei:
            run(
                txt,
                binary=shim,
                max_subbasins=500,
                max_hrus=5000,
                auto_adjust=False,
            )
        assert "guardrail triggered" in str(ei.value).lower()

    def test_timeout_raises_external_error(self, txtinout, tmp_path):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.run.swatplus import run

        shim = _write_shim(tmp_path / "slow_shim", sleep_s=3.0)
        with pytest.raises(SwatBuilderExternalError) as ei:
            run(txtinout, binary=shim, timeout_s=0.5)
        assert ei.value.context["timeout_s"] == 0.5

    def test_binary_does_not_exist_raises_external_error(self, txtinout):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.run.swatplus import run

        with pytest.raises(SwatBuilderExternalError):
            run(txtinout, binary="/surely/not/here/swatplus_exe")


# ---------------------------------------------------------------------------
# run() — post-run summary auto-population
# ---------------------------------------------------------------------------


def _write_realistic_shim(path: Path) -> Path:
    """A shim that emits *parseable* ``basin_wb_aa.txt`` and
    ``channel_sd_aa.txt`` fixtures so the runner's
    :func:`build_run_summary` integration can be exercised end-to-end.

    The content matches what SWAT+ 60.x actually writes, trimmed down
    to the headline columns and a handful of channels.
    """
    basin_wb = (
        "basin_wb_aa                              annual average values\n"
        "   jday    mon    day     yr   unit    gis_id   name           "
        "precip        et       pet   surq_gen      latq      perc   wateryld\n"
        "                                                                "
        "mm        mm        mm         mm        mm        mm         mm\n"
        "      0      0      0      0      1         0   bsn          "
        "1200.50    900.25   1100.00    150.75     30.25     80.00     180.00\n"
    )
    channel_sd = (
        "channel_sd_aa                            annual average values\n"
        "   jday    mon    day     yr   unit    gis_id   name           "
        "area    flo_out    sed_out\n"
        "                                                                "
        "ha         m3       tons\n"
        "      0      0      0      0      1         1   cha01          "
        "10.5  1000000.0       5.0\n"
        "      0      0      0      0      2         2   cha02          "
        "20.0  2500000.0      12.0\n"
        "      0      0      0      0      3         3   cha03          "
        "30.5  7500000.0      20.0\n"
    )
    body = textwrap.dedent(
        f"""\
        #!{sys.executable}
        import pathlib, sys
        cwd = pathlib.Path.cwd()
        if not (cwd / "file.cio").is_file():
            print("MISSING_FILE_CIO", file=sys.stderr)
            raise SystemExit(42)
        (cwd / "diagnostics.out").write_text("SWAT+ fake OK\\n")
        (cwd / "basin_wb_aa.txt").write_text({basin_wb!r})
        (cwd / "channel_sd_aa.txt").write_text({channel_sd!r})
        raise SystemExit(0)
        """
    )
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestRunSummaryIntegration:
    """Prove that a successful ``run()`` auto-populates ``SwatPlusRun.summary``
    from the AA output files the engine wrote — no caller-side parsing
    needed.
    """

    def test_summary_populated_on_success(self, txtinout, tmp_path):
        from swatplus_builder.run.swatplus import run

        shim = _write_realistic_shim(tmp_path / "real_outputs_shim")
        result = run(txtinout, binary=shim)

        assert result.success
        # Headline basin water-balance keys
        assert result.summary["precip_mm"] == pytest.approx(1200.50)
        assert result.summary["et_mm"] == pytest.approx(900.25)
        assert result.summary["wateryld_mm"] == pytest.approx(180.00)
        # Outlet picked from max flo_out across 3 channels.
        expected_q = 7_500_000.0 / (365.25 * 86400.0)
        assert result.summary["mean_q_at_outlet_m3_per_s"] == pytest.approx(expected_q)
        assert result.summary["channel_count"] == pytest.approx(3.0)

    def test_summary_resilient_to_placeholder_outputs(self, txtinout, shim_bin):
        """The default ``shim_bin`` emits *placeholder* output files:
        a malformed ``basin_wb_aa.txt`` (token-count mismatch) and an
        empty ``channel_sd_aa.txt`` (header-only, zero rows). The runner
        should still succeed; the summary quietly skips the malformed
        file and reports ``channel_count = 0`` for the empty one —
        never crash on downstream parse errors.
        """
        from swatplus_builder.run.swatplus import run

        result = run(txtinout, binary=shim_bin)
        assert result.success
        # basin_wb row had bad token count → basin keys absent.
        assert "precip_mm" not in result.summary
        # channel_sd had no data rows → count is 0, outlet absent.
        assert result.summary.get("channel_count") == 0.0
        assert "mean_q_at_outlet_m3_per_s" not in result.summary


# ---------------------------------------------------------------------------
# run_project — thin wrapper
# ---------------------------------------------------------------------------


def test_run_project_forwards_txtinout_dir_and_echoes_project_back(
    txtinout, shim_bin, monkeypatch
):
    """``run_project`` should forward ``project.txtinout_dir`` to ``run``
    and thread the :class:`SwatPlusProject` through to the result verbatim.

    We route binary resolution through ``$SWATPLUS_EXE`` (the documented
    override) so this test doesn't silently find a real engine on PATH.
    """
    from swatplus_builder.run.swatplus import run_project
    from swatplus_builder.types import SwatPlusProject

    monkeypatch.setenv("SWATPLUS_EXE", str(shim_bin))

    proj = SwatPlusProject(
        workdir=txtinout.parent,
        project_name="t",
        project_db=txtinout.parent / "t.sqlite",
        txtinout_dir=txtinout,
        reference_db=txtinout.parent / "ref.sqlite",
        wgn_db=txtinout.parent / "wgn.sqlite",
        sim_start="2000-01-01",
        sim_end="2000-01-02",
    )
    result = run_project(proj, threads=2, timeout_s=30)
    assert result.project is not None
    assert result.project.project_name == "t"
    assert result.txtinout_dir == txtinout.resolve()
    assert result.binary == shim_bin.resolve()
    assert result.success


# ---------------------------------------------------------------------------
# Opt-in: real engine, if available
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("SWATPLUS_EXE"),
    reason="Set SWATPLUS_EXE=<path> to run this test against a real SWAT+ engine.",
)
def test_real_engine_on_empty_txtinout_fails_gracefully(txtinout):
    """If a user has installed the real SWAT+ engine, make sure we wrap it
    correctly — a minimal ``file.cio`` is insufficient input and the engine
    is expected to error out; we just want proof that our wrapper surfaces
    a well-formed exception with a diagnostics tail.
    """
    from swatplus_builder.errors import SwatBuilderError
    from swatplus_builder.run.swatplus import run

    try:
        run(txtinout, timeout_s=60.0)
    except SwatBuilderError as exc:
        assert "returncode" in exc.context or "timeout_s" in exc.context
