"""Run the SWAT+ engine binary on a prepared ``TxtInOut/`` directory.

The SWAT+ engine has a single, quirky convention that drives this module's
design:

* **No CLI arguments.** The engine reads ``file.cio`` from its current
  working directory and writes every output file alongside it. We therefore
  spawn it with ``cwd = txtinout_dir`` and an empty args list.
* **OMP-parallel.** Control is via the ``OMP_NUM_THREADS`` env var; the
  binary itself exposes no ``--threads`` flag.
* **Noisy stderr on failure, rich ``diagnostics.out`` on success.** We
  capture the tail of both so agents can triage a crash without reading
  megabytes of text.

Locating the binary
-------------------

:func:`locate_binary` resolves, in order:

1. ``settings.swatplus_exe`` — explicit config override.
2. ``$SWATPLUS_EXE`` — env var (CI / notebook override).
3. ``shutil.which()`` over a platform-aware candidate list
   (``swatplus_exe``, ``swatplus``, plus ``.exe`` variants on Windows).

No download is performed — the engine is a large native binary and users
typically install it once via the official SWAT+ installer (see
``docs/ROADMAP.md``). We fail fast with an actionable message if nothing
is found.

Typical agent flow
------------------

.. code-block:: python

    from swatplus_builder.editor.api import write_files
    from swatplus_builder.run.swatplus import run

    wr = write_files(project_db)
    run_result = run(wr.txtinout_dir, threads=4, timeout_s=1800)
    assert run_result.success
    print(run_result.summary.get("mean_q_at_outlet"))
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import SwatBuilderExternalError, SwatBuilderInputError
from ..types import SwatPlusProject, SwatPlusRun

__all__ = [
    "BINARY_CANDIDATES",
    "engine_revision_from_outputs",
    "locate_binary",
    "parse_engine_revision",
    "run",
    "run_project",
    "run_solver_subprocess",
    "verify_engine_version",
]

# The SWAT+ engine records its revision in two places, both of which we parse so
# the version in provenance is READ FROM THE ENGINE, never asserted by whoever
# launched the run (a binary mislabeled ``swatplus_exe.6057`` that is actually
# rev 61 cannot fool either source):
#
#   1. The stdout startup banner::    "        Revision 61.0.2.61"
#   2. Every output file's header::   "... MODULAR Rev 2026.61.0.2.61"
#
# Source 2 is the stronger one — it is PERSISTED in the artifact, so any past
# run's engine version is auditable after the fact (this is how the historical
# objective suite's engine was identified retroactively).
_REVISION_RE = re.compile(r"Rev(?:ision)?\s+([0-9][0-9A-Za-z._-]*)", re.IGNORECASE)
# A leading 4-digit build year (e.g. "2026.") appears in output headers but not
# the banner; strip it so both sources yield the same canonical "61.0.2.61".
_BUILD_YEAR_PREFIX_RE = re.compile(r"^(19|20)\d{2}\.")

# Output files whose header carries the "MODULAR Rev <x>" stamp. First hit wins.
_REVISION_HEADER_FILES: tuple[str, ...] = (
    "channel_sd_day.txt",
    "channel_sd_aa.txt",
    "basin_wb_aa.txt",
    "basin_wb_day.txt",
)


def parse_engine_revision(text: str | None) -> str | None:
    """Extract the SWAT+ engine revision from banner or output-header text.

    Handles both the stdout banner form (``"Revision 61.0.2.61"``) and the
    output-file header form (``"MODULAR Rev 2026.61.0.2.61"``), normalizing a
    leading build-year prefix away so both yield ``"61.0.2.61"``.

    Args:
        text: Any text that may contain the revision — engine ``proc.stdout``
            or the header line of an output file.

    Returns:
        The canonical revision string (e.g. ``"61.0.2.61"``) or ``None``.
    """
    if not text:
        return None
    match = _REVISION_RE.search(text)
    if not match:
        return None
    revision = match.group(1).strip()
    return _BUILD_YEAR_PREFIX_RE.sub("", revision)


def engine_revision_from_outputs(txtinout: Path) -> str | None:
    """Read the engine revision stamped into a run's output-file headers.

    This is the authoritative, PERSISTED provenance source: SWAT+ writes
    ``MODULAR Rev <x>`` into the header of every output file, so the version is
    recoverable from the artifacts alone — even for a run completed long ago.

    Args:
        txtinout: Directory containing the engine's output files.

    Returns:
        The canonical revision, or ``None`` if no stamped header is found.
    """
    for name in _REVISION_HEADER_FILES:
        path = txtinout / name
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                header = fh.readline()
        except OSError:
            continue
        revision = parse_engine_revision(header)
        if revision:
            return revision
    return None


def verify_engine_version(
    asserted: str | None,
    observed: str | None,
) -> dict[str, object]:
    """Compare an operator-asserted engine version against the observed banner.

    The observed (banner-parsed) version is authoritative. This returns a typed
    verdict the workflow/CLI can record in provenance and warn on — closing the
    gap where ``--engine-version`` was trusted blindly and could silently
    disagree with the binary that actually ran.

    Args:
        asserted: The version a caller claimed (e.g. CLI ``--engine-version``).
            ``"unknown"``/empty is treated as "no assertion".
        observed: The version parsed from the engine banner (authoritative).

    Returns:
        ``{"engine_version": <authoritative or asserted>, "verified": bool,
        "mismatch": bool, "reason": str}``.
    """
    asserted_norm = (asserted or "").strip()
    if asserted_norm.lower() in {"", "unknown"}:
        asserted_norm = ""

    if observed:
        if asserted_norm and asserted_norm != observed:
            return {
                "engine_version": observed,
                "verified": True,
                "mismatch": True,
                "reason": (
                    f"asserted engine_version={asserted_norm!r} disagrees with the "
                    f"engine banner revision {observed!r}; recording the verified "
                    f"banner value"
                ),
            }
        return {
            "engine_version": observed,
            "verified": True,
            "mismatch": False,
            "reason": f"engine_version verified from banner: {observed}",
        }

    # No observed banner — fall back to the assertion, but flag it unverified.
    return {
        "engine_version": asserted_norm or "unknown",
        "verified": False,
        "mismatch": False,
        "reason": "engine banner revision not observed; engine_version is unverified",
    }

BINARY_CANDIDATES: tuple[str, ...] = (
    # Order matters: first hit wins. Conventional names before SWAT+-Editor-
    # specific ones, POSIX before Windows.
    "swatplus_exe",
    "swatplus",
    "swatplus_exe.exe",
    "swatplus.exe",
)
"""Filenames we try, in order, when scanning ``$PATH`` for the engine."""

_DIAGNOSTICS_TAIL_BYTES: int = 4000
_STDOUT_TAIL_BYTES: int = 4000
_STDERR_TAIL_BYTES: int = 4000
_DEFAULT_MAX_SUBBASINS: int = 500
_DEFAULT_MAX_HRUS: int = 5000

log = logging.getLogger(__name__)

# Output files we surface in ``SwatPlusRun.paths`` for convenience. This is a
# *whitelist of interesting names*, not an exhaustive list — the full
# enumeration lives in ``SwatPlusRun.output_files``.
_WELL_KNOWN_OUTPUTS: tuple[str, ...] = (
    "diagnostics.out",
    "basin_wb_aa.txt",
    "basin_nb_aa.txt",
    "basin_ls_aa.txt",
    "basin_pw_aa.txt",
    "channel_sd_aa.txt",
    "channel_sdmorph_aa.txt",
    "lsunit_wb_aa.txt",
    "hru_wb_aa.txt",
    "aquifer_aa.txt",
    "crop_yld_aa.txt",
)


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def locate_binary(settings: Settings = DEFAULT_SETTINGS) -> Path:
    """Find the SWAT+ engine binary.

    Resolution order: ``settings.swatplus_exe`` > ``$SWATPLUS_EXE`` env var >
    :func:`shutil.which` over :data:`BINARY_CANDIDATES`.

    Args:
        settings: Runtime settings; ``settings.swatplus_exe`` takes priority.

    Returns:
        Absolute path to an existing, executable file.

    Raises:
        SwatBuilderExternalError: binary could not be located.
    """
    # 1. explicit override via settings
    if settings.swatplus_exe is not None:
        p = Path(settings.swatplus_exe).expanduser().resolve()
        if not p.is_file():
            raise SwatBuilderExternalError(
                f"settings.swatplus_exe does not point at an existing file: {p}",
                swatplus_exe=str(p),
                source="settings",
            )
        return p

    # 2. env var
    env_override = os.environ.get("SWATPLUS_EXE")
    if env_override:
        p = Path(env_override).expanduser().resolve()
        if not p.is_file():
            raise SwatBuilderExternalError(
                f"$SWATPLUS_EXE points at a non-existent file: {p}",
                swatplus_exe=str(p),
                source="env",
            )
        return p

    # 3. PATH scan
    for name in BINARY_CANDIDATES:
        hit = shutil.which(name)
        if hit:
            return Path(hit).resolve()

    raise SwatBuilderExternalError(
        "SWAT+ engine not found. Install it (see docs/ROADMAP.md) and "
        "either export SWATPLUS_EXE=<path>, pass settings.swatplus_exe=<path>, "
        "or place one of the engine filenames on $PATH.",
        candidates=list(BINARY_CANDIDATES),
        path=os.environ.get("PATH", ""),
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run(
    txtinout_dir: Path | str,
    *,
    threads: int = 1,
    timeout_s: float | None = None,
    project: SwatPlusProject | None = None,
    binary: Path | str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
    max_subbasins: int = _DEFAULT_MAX_SUBBASINS,
    max_hrus: int = _DEFAULT_MAX_HRUS,
    auto_adjust: bool = True,
) -> SwatPlusRun:
    """Execute the SWAT+ engine in ``txtinout_dir`` and collect its outputs.

    Args:
        txtinout_dir: Directory containing ``file.cio`` and friends. Must
            already exist; this is produced by
            :func:`swatplus_builder.editor.api.write_files`.
        threads: Number of OMP threads. Passed as ``OMP_NUM_THREADS``. The
            engine is only lightly threaded; ``1-4`` is a reasonable range.
            Values ``< 1`` are clamped to ``1``.
        timeout_s: Kill the child after this many seconds, or ``None`` to
            wait forever. A timeout raises
            :class:`~swatplus_builder.errors.SwatBuilderExternalError`.
        project: Optional originating :class:`SwatPlusProject` — included
            verbatim in the return value when supplied, so downstream tools
            can stitch results back to their source.
        binary: Override the resolved engine binary. If ``None``, we call
            :func:`locate_binary`.
        settings: Runtime overrides (used only if ``binary is None``).
        max_subbasins: Guardrail threshold for pre-engine subbasin count.
            If detected count exceeds this value, behavior depends on
            ``auto_adjust``.
        max_hrus: Guardrail threshold for pre-engine HRU count.
        auto_adjust: If ``True`` (default), log warning and continue on
            threshold breach while surfacing suggested aggregation actions.
            If ``False``, fail fast with :class:`SwatBuilderInputError`.

    Returns:
        :class:`SwatPlusRun` carrying exit code, runtime, binary path,
        output file enumeration, and tail slices of stdout/stderr/diagnostics.

    Raises:
        SwatBuilderInputError: ``txtinout_dir`` doesn't exist or is missing
            ``file.cio``.
        SwatBuilderExternalError: binary couldn't be located, the process
            timed out, or the engine exited non-zero (diagnostics tail is
            attached as ``.context["diagnostics_tail"]``).
    """
    txtinout = Path(txtinout_dir).expanduser().resolve()
    if not txtinout.is_dir():
        raise SwatBuilderInputError(
            f"txtinout_dir does not exist or is not a directory: {txtinout}",
            txtinout_dir=str(txtinout),
        )
    cio = txtinout / "file.cio"
    if not cio.is_file():
        raise SwatBuilderInputError(
            f"txtinout_dir is missing file.cio: {txtinout}. Did you run "
            "editor.api.write_files() first?",
            txtinout_dir=str(txtinout),
        )

    _check_size_guardrails(
        txtinout,
        max_subbasins=max_subbasins,
        max_hrus=max_hrus,
        auto_adjust=auto_adjust,
    )

    exe = (
        Path(binary).expanduser().resolve()
        if binary is not None
        else locate_binary(settings)
    )
    if not exe.is_file():
        raise SwatBuilderExternalError(
            f"resolved SWAT+ binary does not exist: {exe}",
            binary=str(exe),
        )

    threads = max(int(threads), 1)
    env = _build_env(threads, exe)
    cmd = [str(exe)]

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(txtinout),
            env=env,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise SwatBuilderExternalError(
            f"SWAT+ engine timed out after {timeout_s}s",
            cmd=cmd,
            txtinout_dir=str(txtinout),
            timeout_s=timeout_s,
        ) from exc
    elapsed = time.monotonic() - start

    stdout_tail = (proc.stdout or "")[-_STDOUT_TAIL_BYTES:]
    stderr_tail = (proc.stderr or "")[-_STDERR_TAIL_BYTES:]
    # Engine version, in order of authority: the revision stamped into the
    # persisted output-file headers (recoverable from artifacts alone), then the
    # stdout startup banner (the banner prints at the START of stdout, so parse
    # the head — a long run may have truncated it out of the tail).
    engine_version = engine_revision_from_outputs(txtinout) or parse_engine_revision(
        (proc.stdout or "")[:_STDOUT_TAIL_BYTES]
    )
    diagnostics_tail = _read_diagnostics_tail(txtinout)
    output_files = _enumerate_output_files(txtinout)
    paths = _collect_well_known_paths(txtinout, output_files)
    # Summary population is best-effort: never fail a successful run
    # because of a parse hiccup on optional AA files. The producer
    # (``output.summary.build_run_summary``) already swallows parse
    # errors internally; the outer try/except is a belt-and-braces
    # guarantee against an ill-formed file type we haven't seen yet.
    try:
        from ..output.summary import build_run_summary

        summary = build_run_summary(txtinout) if proc.returncode == 0 else {}
    except Exception:  # pragma: no cover — defensive, should not trip
        summary = {}

    if proc.returncode != 0:
        raise SwatBuilderExternalError(
            f"SWAT+ engine exited {proc.returncode}",
            cmd=cmd,
            txtinout_dir=str(txtinout),
            binary=str(exe),
            returncode=proc.returncode,
            runtime_seconds=round(elapsed, 3),
            threads=threads,
            stderr_tail=stderr_tail,
            stdout_tail=stdout_tail,
            diagnostics_tail=diagnostics_tail,
        )

    return SwatPlusRun(
        project=project,
        binary=exe,
        engine_version=engine_version,
        txtinout_dir=txtinout,
        command=cmd,
        exit_code=proc.returncode,
        runtime_seconds=round(elapsed, 3),
        success=True,
        output_dir=txtinout,
        output_files=output_files,
        diagnostics_tail=diagnostics_tail,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        paths=paths,
        summary=summary,
    )


def run_project(
    project: SwatPlusProject,
    *,
    threads: int = 1,
    timeout_s: float | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> SwatPlusRun:
    """Convenience wrapper: run the engine on ``project.txtinout_dir``.

    This is what :func:`swatplus_builder.tools.run_swat` calls. It exists so
    that the agent-facing tool signature stays ``(project, ...)`` while the
    primitive :func:`run` keeps a directory-first signature suited to
    notebook use and CLI parity.
    """
    return run(
        project.txtinout_dir,
        threads=threads,
        timeout_s=timeout_s,
        project=project,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def run_solver_subprocess(
    exe: Path,
    txtinout: Path,
    *,
    threads: int = 1,
    timeout_s: float | None = None,
) -> tuple[int, str, str]:
    """Lightweight solver invocation for internal/bridge use.

    All solver binary calls — including pySWATPlus bridge invocations — must
    go through this function or the full :func:`run` wrapper. Direct
    ``subprocess.Popen``/``subprocess.run`` calls on the engine binary are
    forbidden outside this module.

    Args:
        exe: Absolute path to the SWAT+ engine binary (already resolved).
        txtinout: Working directory containing ``file.cio``.
        threads: OMP thread count (clamped to >= 1).
        timeout_s: Kill-and-raise after this many seconds. ``None`` waits forever.

    Returns:
        Tuple of ``(returncode, stdout_tail, stderr_tail)``.

    Raises:
        SwatBuilderExternalError: Process timed out or binary could not start.
    """
    threads = max(int(threads), 1)
    env = _build_env(threads, exe)
    try:
        proc = subprocess.run(
            [str(exe)],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(txtinout),
            env=env,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise SwatBuilderExternalError(
            f"SWAT+ engine timed out after {timeout_s}s",
            binary=str(exe),
            txtinout_dir=str(txtinout),
            timeout_s=timeout_s,
        ) from exc
    except OSError as exc:
        raise SwatBuilderExternalError(
            f"Failed to launch SWAT+ binary: {exc}",
            binary=str(exe),
            txtinout_dir=str(txtinout),
        ) from exc
    stdout_tail = (proc.stdout or "")[-_STDOUT_TAIL_BYTES:]
    stderr_tail = (proc.stderr or "")[-_STDERR_TAIL_BYTES:]
    return proc.returncode, stdout_tail, stderr_tail


def clean_and_run_solver(
    txtinout: Path | str,
    *,
    exe: Path | None = None,
    threads: int = 1,
    timeout_s: float = 3600.0,
    retry_attempts: int = 0,
    retry_backoff_s: float = 1.0,
) -> tuple[int, str, str]:
    """Delete stale outputs, run the engine, and verify fresh output.

    Guards:
    1. Deletes ``simulation.out``, ``channel_sd_day.txt``, and other daily
       output files that could mask a silent engine crash.
    2. Runs the solver via ``run_solver_subprocess``.
    3. Verifies ``simulation.out`` was regenerated and contains
       "Execution successfully completed".
    4. If return code is non-zero, raises ``SwatBuilderExternalError``.

    Returns:
        (returncode, stdout_tail, stderr_tail)
    """
    txt = Path(txtinout).expanduser().resolve()

    # Resolve binary: explicit exe param > env var > package default
    if exe is not None:
        exe_path = Path(exe).expanduser().resolve()
        if not exe_path.is_file():
            raise SwatBuilderExternalError(
                f"SWAT+ binary not found at specified path: {exe_path}",
                binary=str(exe_path),
            )
    else:
        try:
            exe_path = locate_binary()
        except Exception as exc:
            raise SwatBuilderExternalError(
                "SWAT+ engine not found. Set SWATPLUS_EXE or pass exe=<path>.",
                txtinout_dir=str(txt),
            ) from exc

    # 1. Delete stale outputs
    _stale_patterns = [
        "simulation.out",
        "channel_sd_day.txt",
        "channel_day.txt",
        "basin_sd_cha_day.txt",
        "basin_cha_day.txt",
        "basin_wb_yr.txt",
        "hydout_yr.txt",
        "hydout_aa.txt",
    ]
    last_error: SwatBuilderExternalError | None = None
    total_attempts = max(0, int(retry_attempts)) + 1
    for attempt in range(1, total_attempts + 1):
        for pattern in _stale_patterns:
            stale = txt / pattern
            if stale.exists():
                stale.unlink()

        try:
            # 2. Run solver
            rc, stdout_tail, stderr_tail = run_solver_subprocess(
                txtinout=txt,
                exe=exe_path,
                threads=threads,
                timeout_s=timeout_s,
            )
        except SwatBuilderExternalError as exc:
            last_error = SwatBuilderExternalError(
                str(exc),
                **{
                    **getattr(exc, "context", {}),
                    "failure_class": "engine_timeout_or_launch_failure",
                    "attempt": attempt,
                    "attempts_total": total_attempts,
                },
            )
            if attempt < total_attempts:
                time.sleep(max(0.0, float(retry_backoff_s)))
                continue
            raise last_error from exc

        # 3. Fail loudly on non-zero exit
        if rc != 0:
            last_error = SwatBuilderExternalError(
                f"SWAT+ engine exited with code {rc}",
                binary=str(exe_path),
                txtinout_dir=str(txt),
                returncode=rc,
                stderr_tail=stderr_tail,
                failure_class="engine_nonzero_exit",
                attempt=attempt,
                attempts_total=total_attempts,
            )
            if attempt < total_attempts:
                time.sleep(max(0.0, float(retry_backoff_s)))
                continue
            raise last_error

        # 4. Verify simulation.out was regenerated
        sim_out = txt / "simulation.out"
        if not sim_out.exists():
            last_error = SwatBuilderExternalError(
                "SWAT+ engine did not produce simulation.out — engine may not have run",
                binary=str(exe_path),
                txtinout_dir=str(txt),
                failure_class="missing_simulation_out",
                attempt=attempt,
                attempts_total=total_attempts,
            )
            if attempt < total_attempts:
                time.sleep(max(0.0, float(retry_backoff_s)))
                continue
            raise last_error
        content = sim_out.read_text(encoding="utf-8", errors="ignore")
        if "Execution successfully completed" not in content:
            last_error = SwatBuilderExternalError(
                "SWAT+ engine ran but simulation.out does not indicate successful completion",
                binary=str(exe_path),
                txtinout_dir=str(txt),
                sim_out_tail=content[-500:],
                failure_class="simulation_out_incomplete",
                attempt=attempt,
                attempts_total=total_attempts,
            )
            if attempt < total_attempts:
                time.sleep(max(0.0, float(retry_backoff_s)))
                continue
            raise last_error

        # 5. Verify channel_sd_day.txt was regenerated
        sd = txt / "channel_sd_day.txt"
        if not sd.exists():
            last_error = SwatBuilderExternalError(
                "SWAT+ engine did not produce channel_sd_day.txt",
                binary=str(exe_path),
                txtinout_dir=str(txt),
                failure_class="missing_expected_output_file",
                attempt=attempt,
                attempts_total=total_attempts,
            )
            if attempt < total_attempts:
                time.sleep(max(0.0, float(retry_backoff_s)))
                continue
            raise last_error

        return rc, stdout_tail, stderr_tail

    if last_error is not None:
        raise last_error
    raise SwatBuilderExternalError(
        "SWAT+ execution failed without a classified error",
        binary=str(exe_path),
        txtinout_dir=str(txt),
        failure_class="unclassified_engine_failure",
    )


def _check_size_guardrails(
    txtinout: Path,
    *,
    max_subbasins: int,
    max_hrus: int,
    auto_adjust: bool,
) -> None:
    """Pre-engine guardrail for large-basin runs.

    Counts are loaded from `delin/watershed_result.json` and
    `delin/hrus/hru_catalog.json` when available.
    """
    run_root = _infer_run_root(txtinout)
    counts = _load_preengine_counts(run_root) if run_root is not None else {}
    n_subbasins = _coerce_int(counts.get("n_subbasins"))
    n_hrus = _coerce_int(counts.get("n_hrus"))

    exceeded: list[str] = []
    if n_subbasins is not None and n_subbasins > max_subbasins:
        exceeded.append(f"subbasins={n_subbasins} > max_subbasins={max_subbasins}")
    if n_hrus is not None and n_hrus > max_hrus:
        exceeded.append(f"hrus={n_hrus} > max_hrus={max_hrus}")

    if not exceeded:
        return

    guidance = (
        "Suggested auto-adjustments: increase delineation stream threshold "
        "to reduce subbasins and/or enable stronger HRU aggregation "
        "(dominant-only or higher min_hru_fraction)."
    )
    msg = "Large-basin guardrail triggered: " + "; ".join(exceeded)

    if auto_adjust:
        log.warning("%s. %s Proceeding because auto_adjust=True.", msg, guidance)
        return

    raise SwatBuilderInputError(
        f"{msg}. {guidance}",
        txtinout_dir=str(txtinout),
        n_subbasins=n_subbasins,
        n_hrus=n_hrus,
        max_subbasins=max_subbasins,
        max_hrus=max_hrus,
        guidance=guidance,
    )


def _infer_run_root(txtinout: Path) -> Path | None:
    """Best-effort locate run root containing `delin/`."""
    for candidate in [txtinout, *txtinout.parents]:
        if (candidate / "delin").is_dir():
            return candidate
    return None


def _load_preengine_counts(run_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    ws = run_root / "delin" / "watershed_result.json"
    hru = run_root / "delin" / "hrus" / "hru_catalog.json"
    if ws.is_file():
        try:
            data = json.loads(ws.read_text(encoding="utf-8"))
            counts["n_subbasins"] = int(data.get("stats", {}).get("n_subbasins", 0))
        except Exception:
            pass
    if hru.is_file():
        try:
            data = json.loads(hru.read_text(encoding="utf-8"))
            counts["n_hrus"] = int(data.get("stats", {}).get("n_hrus", 0))
        except Exception:
            pass
    return counts


def _coerce_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _build_env(threads: int, exe: Path | None = None) -> dict[str, str]:
    """Child environment: mostly inherited, with OpenMP tuned.

    On macOS the SWAT+ engine ships with ``libiomp5.dylib`` bundled
    alongside the binary (as in the Mac installer's ``swat_exe/`` dir).
    We prepend the binary's own directory to ``DYLD_FALLBACK_LIBRARY_PATH``
    and ``DYLD_LIBRARY_PATH`` so dyld finds it without any manual
    ``install_name_tool`` patching. This is safe on non-macOS (the env
    vars are simply unused).
    """
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(threads)
    if sys.platform == "darwin":
        bin_dir = str(exe.parent) if exe is not None else ""
        # Prepend binary dir to both library paths for maximum robustness
        for key in ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
            existing = env.get(key, "")
            parts = [p for p in [bin_dir, existing] if p]
            env[key] = ":".join(parts) if parts else ""
    return env


def _read_diagnostics_tail(txtinout: Path) -> str:
    """Return the last ``_DIAGNOSTICS_TAIL_BYTES`` of ``diagnostics.out``.

    Returns ``""`` if the file does not exist, is empty, or can't be decoded.
    """
    diag = txtinout / "diagnostics.out"
    if not diag.is_file():
        return ""
    try:
        size = diag.stat().st_size
        with diag.open("rb") as fh:
            if size > _DIAGNOSTICS_TAIL_BYTES:
                fh.seek(-_DIAGNOSTICS_TAIL_BYTES, os.SEEK_END)
            data = fh.read()
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _enumerate_output_files(txtinout: Path) -> list[Path]:
    """List ``*.out`` and ``*.txt`` files in the TxtInOut directory.

    The engine writes every output alongside its inputs, so we take the
    union and let the consumer disambiguate. Sorted for stable output.
    """
    files: list[Path] = []
    for ext in ("*.out", "*.txt"):
        files.extend(txtinout.glob(ext))
    # Dedup in case of .txt files that are also inputs — not expected, but
    # cheap to be safe.
    return sorted(set(files))


def _collect_well_known_paths(
    txtinout: Path, output_files: list[Path]
) -> dict[str, Path]:
    """Build a ``name -> Path`` map for the diagnostics + annual-avg outputs."""
    by_name = {p.name: p for p in output_files}
    paths: dict[str, Path] = {}
    for name in _WELL_KNOWN_OUTPUTS:
        hit = by_name.get(name)
        if hit is not None:
            # Strip the ``.txt`` / ``.out`` to keep the keys agent-friendly.
            key = name.rsplit(".", 1)[0]
            paths[key] = hit
    return paths
