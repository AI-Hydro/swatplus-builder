"""CLI for swatplus-builder.

Entry point: ``swat``

Subcommands
-----------
swat init        — download + verify + cache the SWAT+ reference datasets DB
swat watershed   — delineate subbasins + channels from a DEM
swat hrus        — build HRUs by LU × Soil × Slope overlay
swat project     — build SWAT+ SQLite + TxtInOut from a prepared workdir
swat run         — run the SWAT+ engine on a prepared project
swat build       — full pipeline: watershed → hrus → project → run (one-shot)
swat mcp         — start the stdio MCP server (requires [mcp] extra)
swat version     — print version

Design: the command ``swat`` is what users remember, not the package name.
Subcommands are single short words — no hyphens, no underscores.
"""

from __future__ import annotations

import typer
from rich import print as rprint
import json

from . import __version__
import sys

if sys.version_info < (3, 10):
    import warnings
    warnings.warn("swatplus-builder requires Python >= 3.10. Execution will proceed but may fail.", RuntimeWarning)
    # The user suggested a strict RuntimeError, let's raise it.
    raise RuntimeError("swatplus-builder requires Python >= 3.10. Please upgrade your environment.")

app = typer.Typer(
    name="swat",
    help="swatplus-builder: headless SWAT+ project generator (no QGIS).",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)


def _git_sha(length: int = 8) -> str:
    """Return short git SHA of HEAD, or 'unknown' if git is unavailable."""
    import subprocess as _sp
    try:
        sha = _sp.check_output(
            ["git", "rev-parse", f"--short={length}", "HEAD"],
            stderr=_sp.DEVNULL,
            text=True,
        ).strip()
        return sha if sha else "unknown"
    except Exception:
        return "unknown"


@app.command("version")
def cmd_version(
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON to stdout."
    ),
) -> None:
    """Print version, git SHA, and Python runtime."""
    import platform as _pl
    sha = _git_sha()
    py = _pl.python_version()
    if json_output:
        print(json.dumps({
            "package": "swatplus-builder",
            "version": __version__,
            "git_sha": sha,
            "python": py,
        }))
    else:
        rprint(
            f"[bold]swatplus-builder[/bold] v{__version__}  "
            f"[dim]git:{sha}  python:{py}[/dim]"
        )


@app.command("health")
def cmd_health(
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON (suppresses rich output)."
    ),
) -> None:
    """Check runtime health: binary, datasets, GIS stack, MCP extras.

    Exit codes:
      0 — all checks pass
      1 — degraded (non-critical items missing or not configured)
      2 — unhealthy (critical failure: wrong Python version)
    """
    import os
    import platform as _pl
    import sys as _sys

    checks: list[dict[str, object]] = []

    def _check(name: str, critical: bool, ok: bool, detail: str) -> None:
        checks.append({"name": name, "critical": critical, "ok": ok, "detail": detail})

    # --- critical checks ---
    py_ok = _sys.version_info >= (3, 10)
    _check("python_version", critical=True, ok=py_ok, detail=_pl.python_version())

    pkg_ok = True
    try:
        import swatplus_builder  # noqa: F401
    except Exception as exc:  # pragma: no cover
        pkg_ok = False
    _check("package_import", critical=True, ok=pkg_ok, detail=f"v{__version__}" if pkg_ok else "import failed")

    # --- optional: SWAT+ binary ---
    exe_path = os.environ.get("SWATPLUS_EXE", "")
    from pathlib import Path as _P
    exe_ok = bool(exe_path) and _P(exe_path).is_file()
    _check("swatplus_exe", critical=False, ok=exe_ok,
           detail=exe_path if exe_path else "SWATPLUS_EXE not set")

    # --- optional: artifacts dir ---
    art_path = os.environ.get("SWATPLUS_BUILDER_ARTIFACTS", "")
    art_ok = bool(art_path)
    _check("artifacts_dir", critical=False, ok=art_ok,
           detail=art_path if art_path else "SWATPLUS_BUILDER_ARTIFACTS not set")

    # --- optional: datasets DB ---
    db_path = os.environ.get("SWATPLUS_DATASETS_DB", "")
    db_ok = bool(db_path) and _P(db_path).is_file()
    _check("datasets_db", critical=False, ok=db_ok,
           detail=db_path if db_path else "SWATPLUS_DATASETS_DB not set")

    # --- optional: GIS stack ---
    try:
        import rasterio  # noqa: F401
        import geopandas  # noqa: F401
        gis_ok = True
        gis_detail = "rasterio + geopandas"
    except ImportError as exc:
        gis_ok = False
        gis_detail = f"missing: {exc.name}"
    _check("gis_stack", critical=False, ok=gis_ok, detail=gis_detail)

    # --- optional: MCP extras ---
    try:
        import fastmcp  # noqa: F401
        mcp_ok = True
        mcp_detail = "fastmcp"
    except ImportError:
        mcp_ok = False
        mcp_detail = "fastmcp not installed (pip install swatplus-builder[mcp])"
    _check("mcp_extras", critical=False, ok=mcp_ok, detail=mcp_detail)

    critical_fail = any(c["critical"] and not c["ok"] for c in checks)
    optional_fail = any(not c["critical"] and not c["ok"] for c in checks)
    status = "unhealthy" if critical_fail else ("degraded" if optional_fail else "healthy")
    exit_code = 2 if critical_fail else (1 if optional_fail else 0)

    if json_output:
        print(json.dumps({
            "status": status,
            "exit_code": exit_code,
            "checks": checks,
        }, indent=2))
        raise typer.Exit(exit_code)

    status_color = {"healthy": "green", "degraded": "yellow", "unhealthy": "red"}[status]
    rprint(f"[bold]swat health[/bold]  [{status_color}]{status}[/{status_color}]")
    for c in checks:
        icon = "[green]✓[/green]" if c["ok"] else ("[red]✗[/red]" if c["critical"] else "[yellow]![/yellow]")
        label = "[bold red]CRITICAL[/bold red]" if c["critical"] and not c["ok"] else ""
        rprint(f"  {icon}  {c['name']:<24} {c['detail']}  {label}")
    raise typer.Exit(exit_code)


@app.command("inspect")
def cmd_inspect(
    run_id: str = typer.Argument(..., help="Run directory path or run-id path containing metadata.json."),
) -> None:
    """Inspect persisted run metadata for one run.

    Looks for ``metadata.json`` under the provided run path and prints it as JSON.
    """
    from pathlib import Path as _P
    from .output.metadata import read_metadata

    run_path = _P(run_id).expanduser().resolve()
    candidates = [run_path / "metadata.json", run_path]
    meta_path = None
    for p in candidates:
        if p.is_file() and p.name == "metadata.json":
            meta_path = p
            break
        if p.is_file() and p.name != "metadata.json":
            continue
        if p.is_dir() and (p / "metadata.json").exists():
            meta_path = p / "metadata.json"
            break
    if meta_path is None:
        rprint(f"[red]error:[/red] metadata.json not found under {run_path}")
        raise typer.Exit(1)

    md = read_metadata(meta_path)
    rprint(json.dumps(md.model_dump(), indent=2))


@app.command("init")
def cmd_init(
    datasets_version: str = typer.Option(
        None,
        "--datasets-version",
        help="Datasets DB version key (default: latest pinned in ref/catalog.py).",
    ),
    ref_dir: str = typer.Option(
        None,
        "--ref-dir",
        help="Override reference_db_dir (default: ~/.swatplus_builder/reference_dbs).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-download even if a valid cached copy exists.",
    ),
    timeout: float = typer.Option(
        120.0, "--timeout", help="HTTP timeout in seconds."
    ),
) -> None:
    """Fetch + verify ``swatplus_datasets.sqlite`` into the local cache.

    Must be run once before the first ``swat build`` so the editor can
    populate plants / soils / management defaults. Idempotent: cached
    copies with matching SHA-256 are reused.
    """
    from .config import DEFAULT_SETTINGS, Settings
    from .errors import SwatBuilderError
    from .ref import ensure_datasets_db, fetch_datasets_db, get_release

    settings = DEFAULT_SETTINGS
    if ref_dir is not None:
        from pathlib import Path as _P

        settings = Settings(**{**DEFAULT_SETTINGS.model_dump(), "reference_db_dir": _P(ref_dir)})

    try:
        release = get_release(datasets_version)
    except KeyError as exc:
        rprint(f"[red]error:[/red] {exc}")
        raise typer.Exit(2) from exc

    rprint(
        f"[bold]swat init[/bold] → datasets v{release.datasets_version} "
        f"(editor {release.editor_tag}, {release.size / 1024:.0f} KiB)"
    )
    try:
        if force:
            path = fetch_datasets_db(
                release.datasets_version, settings=settings, timeout=timeout,
            )
        else:
            path = ensure_datasets_db(
                release.datasets_version, settings=settings, timeout=timeout,
            )
    except SwatBuilderError as exc:
        rprint(f"[red]error:[/red] {exc}")
        if exc.context:
            rprint(exc.context)
        raise typer.Exit(1) from exc
    rprint(f"[green]ok[/green] {path}")
    rprint(
        "\nUse this DB by exporting the env var (optional; also auto-"
        "resolved from project_config.reference_db):\n"
        f"  export SWATPLUS_DATASETS_DB={path}"
    )


@app.command("watershed")
def cmd_watershed(
    dem: str = typer.Option(..., "--dem", help="Path to DEM GeoTIFF (any projected CRS)."),
    lon: float = typer.Option(..., "--lon", help="Outlet longitude (WGS84)."),
    lat: float = typer.Option(..., "--lat", help="Outlet latitude (WGS84)."),
    workdir: str = typer.Option("swatplus_runs/default", "--workdir", "-w"),
    threshold: int = typer.Option(500, "--threshold", help="Flow-accumulation stream threshold (cells)."),
) -> None:
    """Delineate subbasins + channels + routing from a DEM.

    Writes shapefiles, routing GraphML, and a WatershedResult manifest to WORKDIR.
    """
    raise typer.Exit("Not implemented yet (Phase 1). See docs/ROADMAP.md §1.2.")


@app.command("hrus")
def cmd_hrus(
    workdir: str = typer.Option(..., "--workdir", "-w", help="Workdir from `swat watershed`."),
    landuse: str = typer.Option(..., "--landuse", help="Landuse raster (NLCD or similar)."),
    soil: str = typer.Option(..., "--soil", help="Soil raster (gNATSGO mukey or user codes)."),
    slope_bands: str = typer.Option("5,15", "--slope-bands", help="Comma-separated slope breakpoints (degrees)."),
) -> None:
    """Build HRUs by LU × Soil × Slope overlay within each landscape unit."""
    raise typer.Exit("Not implemented yet (Phase 1). See docs/ROADMAP.md §1.2.")


@app.command("project")
def cmd_project(
    workdir: str = typer.Option(..., "--workdir", "-w"),
    weather: str = typer.Option(..., "--weather", help="Directory of GridMET (or user-supplied) weather."),
    start: str = typer.Option(..., "--start", help="Simulation start date, ISO-8601 (e.g. 2000-01-01)."),
    end: str = typer.Option(..., "--end", help="Simulation end date."),
    name: str = typer.Option(..., "--name", "-n", help="Project name (becomes <name>.sqlite)."),
) -> None:
    """Build a complete SWAT+ project: gis_* tables → import_gis → write_files → TxtInOut."""
    raise typer.Exit("Not implemented yet (Phase 1). See docs/ROADMAP.md §1.4.")


@app.command("run")
def cmd_run(
    txtinout: str = typer.Option(
        None,
        "--txtinout",
        "-t",
        help="Path to a ``TxtInOut/`` directory. Mutually exclusive with --workdir and --usgs.",
    ),
    workdir: str = typer.Option(
        None,
        "--workdir",
        "-w",
        help="Project workdir; we resolve ``<workdir>/Scenarios/Default/TxtInOut``.",
    ),
    usgs: str = typer.Option(
        None,
        "--usgs",
        help="USGS streamgage ID. If provided, triggers completely automated E2E platform generation.",
    ),
    outdir: str = typer.Option(
        "./swatplus_runs/usgs_run",
        "--outdir",
        help="Output directory when using --usgs orchestration.",
    ),
    threads: int = typer.Option(1, "--threads", "-j", help="OMP_NUM_THREADS."),
    timeout: float = typer.Option(3600.0, "--timeout", help="Kill engine after N seconds."),
    binary: str = typer.Option(
        None, "--binary", help="Override SWAT+ engine path (else settings / env / PATH)."
    ),
    max_hrus: int = typer.Option(
        5000,
        "--max-hrus",
        help="Pre-engine guardrail threshold for HRU count (when detectable).",
    ),
    max_subbasins: int = typer.Option(
        500,
        "--max-subbasins",
        help="Pre-engine guardrail threshold for subbasin count (when detectable).",
    ),
    auto_adjust: bool = typer.Option(
        True,
        "--auto-adjust/--no-auto-adjust",
        help="On guardrail breach: warn and continue (--auto-adjust) or fail fast (--no-auto-adjust).",
    ),
) -> None:
    """Run the SWAT+ engine or automate a full platform execution (--usgs).
    """
    from pathlib import Path as _P
    import json

    # Platform automation branch
    if usgs:
        rprint(f"[bold]swat automate[/bold] → Building Platform for USGS: {usgs}")
        from .orchestrate import run_pipeline
        
        try:
            summary = run_pipeline(
                usgs_id=usgs,
                outdir=_P(outdir),
                threads=threads,
                engine_timeout_s=timeout
            )
            rprint("\n[bold]Run Summary:[/bold]")
            rprint(f"- Basin: {usgs}")
            rprint(f"- Status: [green]{summary.get('status')}[/green]")
            if "nse" in summary:
                rprint(f"- NSE:  {summary['nse']:.2f}")
                rprint(f"- KGE:  {summary['kge']:.2f}")
            raise typer.Exit(0)
        except Exception as exc:
            rprint(f"[red]Pipeline failed:[/red] {exc}")
            raise typer.Exit(1)

    # Standard engine runner branch
    from .errors import SwatBuilderError
    from .run import run as _run

    if (txtinout is None) == (workdir is None):
        rprint("[red]error:[/red] specify exactly one of --txtinout, --workdir, or --usgs")
        raise typer.Exit(2)

    if txtinout is not None:
        txt_dir = _P(txtinout)
    else:
        assert workdir is not None
        txt_dir = _P(workdir) / "Scenarios" / "Default" / "TxtInOut"

    rprint(f"[bold]swat run[/bold] → {txt_dir}  (threads={threads})")
    try:
        result = _run(
            txt_dir,
            threads=threads,
            timeout_s=timeout,
            binary=binary,
            max_hrus=max_hrus,
            max_subbasins=max_subbasins,
            auto_adjust=auto_adjust,
        )
    except SwatBuilderError as exc:
        rprint(f"[red]engine failed:[/red] {exc}")
        if exc.context:
            tail = exc.context.get("diagnostics_tail") or exc.context.get("stderr_tail")
            if tail:
                rprint(f"[dim]--- tail ---[/dim]\n{tail}")
        raise typer.Exit(1) from exc

    rprint(
        f"[green]ok[/green] exit=0  runtime={result.runtime_seconds:.2f}s  "
        f"outputs={len(result.output_files)}"
    )
    for key, path in sorted(result.paths.items()):
        rprint(f"  [cyan]{key}[/cyan] → {path.name}")


@app.command("validate")
def cmd_validate(
    basins: str = typer.Option(..., "--basins", help="Path to curated basin JSON spec."),
    artifacts_root: str = typer.Option(
        "tests/_artifacts/validation",
        "--artifacts-root",
        help="Root directory for artifact store (contains runs/<content_hash>/...).",
    ),
    runs_root: str = typer.Option(
        "tests/_artifacts/validation_work",
        "--runs-root",
        help="Root directory for per-basin working run directories.",
    ),
    engine_version: str = typer.Option(
        "unknown",
        "--engine-version",
        help="Engine version string included in content hashing.",
    ),
) -> None:
    """Run benchmark validation for a basin suite and write artifacts/reports."""
    from pathlib import Path as _P
    from .validation.runner import load_basin_specs, run_validation

    basins_path = _P(basins).expanduser().resolve()
    if not basins_path.exists():
        rprint(f"[red]error:[/red] basins file not found: {basins_path}")
        raise typer.Exit(2)

    try:
        specs = load_basin_specs(basins_path)
    except Exception as exc:
        rprint(f"[red]error:[/red] failed to parse basin specs: {exc}")
        raise typer.Exit(2) from exc

    rprint(f"[bold]swat validate[/bold] → {len(specs)} basins")
    results, report_dir = run_validation(
        basins=specs,
        artifacts_root=_P(artifacts_root),
        runs_root=_P(runs_root),
        engine_version=engine_version,
    )

    ok = sum(1 for r in results if r.status in {"success", "cached"})
    cache_hits = sum(1 for r in results if r.cache_hit)
    rprint(
        f"[green]complete[/green] success={ok}/{len(results)}  cache_hits={cache_hits}  "
        f"report={report_dir}"
    )


@app.command("calibrate")
def cmd_calibrate(
    basin: str = typer.Option(..., "--basin", help="Basin identifier (e.g., usgs_01547700)."),
    start: str = typer.Option(..., "--start", help="Simulation start date (YYYY-MM-DD)."),
    end: str = typer.Option(..., "--end", help="Simulation end date (YYYY-MM-DD)."),
    algo: str = typer.Option("dds", "--algo", help="Calibration algorithm label: dds|sceua|random."),
    n_iter: int = typer.Option(50, "--n-iter", help="Number of calibration iterations."),
    objectives: str = typer.Option(
        "nse,log_nse,pbias",
        "--objectives",
        help="Comma-separated objectives subset of: nse,log_nse,pbias,kge.",
    ),
    parameters: str = typer.Option(
        "CN2,ALPHA_BF,SURLAG",
        "--parameters",
        help="Comma-separated parameter names from registry.",
    ),
    artifacts_root: str = typer.Option(
        "tests/_artifacts/calibration",
        "--artifacts-root",
        help="Root directory for calibration artifacts.",
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed for reproducible sampling."),
    engine_version: str = typer.Option(
        "unknown", "--engine-version", help="Engine version string for content hashing."
    ),
    report_dir: str = typer.Option(
        None,
        "--report-dir",
        help="Optional calibration report directory (defaults to <artifacts-root>/calibration_reports).",
    ),
    alignment_csv: str = typer.Option(
        None,
        "--alignment-csv",
        help="Optional outputs/alignment.csv for observed-vs-simulated calibration comparison plots.",
    ),
    real_engine: bool = typer.Option(
        False,
        "--real-engine/--proxy-objective",
        help="Use true SWAT+ engine-backed objective (requires --base-txtinout and --alignment-csv).",
    ),
    base_txtinout: str = typer.Option(
        None,
        "--base-txtinout",
        help="Base TxtInOut directory for real-engine calibration.",
    ),
    binary: str = typer.Option(
        None,
        "--binary",
        help="Optional SWAT+ executable path override for real-engine calibration.",
    ),
    outlet_gis_id: int = typer.Option(
        1,
        "--outlet-gis-id",
        help="Outlet GIS ID used for objective scoring in real-engine mode.",
    ),
    real_work_root: str = typer.Option(
        None,
        "--real-work-root",
        help="Optional working directory for real-engine sample reruns.",
    ),
    objective_sim_file: str = typer.Option(
        "basin_sd_cha_day.txt",
        "--objective-sim-file",
        help="Simulation output filename used for objective scoring in real-engine mode.",
    ),
    strict_objective_file: bool = typer.Option(
        True,
        "--strict-objective-file/--allow-objective-fallback",
        help="Require evaluator to use exactly --objective-sim-file (fail on fallback).",
    ),
    allow_outlet_autodetect: bool = typer.Option(
        False,
        "--allow-outlet-autodetect/--require-explicit-outlet",
        help="Allow objective scoring to auto-switch outlet when requested outlet is dry.",
    ),
    min_improvement_nse: float = typer.Option(
        None,
        "--min-improvement-nse",
        help="Optional minimum NSE improvement (best_nse - baseline_nse) required to pass.",
    ),
    calibration_engine: str = typer.Option(
        "spotpy",
        "--calibration-engine",
        help="Calibration backend: spotpy (legacy) | pyswatplus (revised 3C path).",
    ),
    n_gen: int = typer.Option(
        30,
        "--n-gen",
        help="Generations for pySWATPlus calibration engine.",
    ),
    pop_size: int = typer.Option(
        32,
        "--pop-size",
        help="Population size for pySWATPlus calibration engine.",
    ),
    preset: str = typer.Option(
        None,
        "--preset",
        help=(
            "Calibration preset: quick|standard|thorough. "
            "Applies opinionated defaults; explicit advanced flags can still be set after review."
        ),
    ),
) -> None:
    """Run calibration sampling with artifact persistence (alpha skeleton)."""
    from datetime import date
    from pathlib import Path as _P

    from .calibration import CalibrationRequest, run_calibration, write_calibration_reports
    from .params import get_parameter

    allowed = {"nse", "log_nse", "pbias", "kge"}
    objective_list = [o.strip().lower() for o in objectives.split(",") if o.strip()]
    if not objective_list:
        rprint("[red]error:[/red] at least one objective is required")
        raise typer.Exit(2)
    bad = [o for o in objective_list if o not in allowed]
    if bad:
        rprint(f"[red]error:[/red] invalid objectives: {', '.join(bad)}")
        raise typer.Exit(2)

    param_list = [p.strip() for p in parameters.split(",") if p.strip()]
    if not param_list:
        rprint("[red]error:[/red] at least one parameter is required")
        raise typer.Exit(2)
    try:
        for p in param_list:
            get_parameter(p)
    except KeyError as exc:
        rprint(f"[red]error:[/red] {exc}")
        raise typer.Exit(2) from exc

    engine = calibration_engine.strip().lower()
    if engine not in {"spotpy", "pyswatplus"}:
        rprint("[red]error:[/red] --calibration-engine must be one of: spotpy, pyswatplus")
        raise typer.Exit(2)

    if preset is not None:
        preset_key = preset.strip().lower()
        if preset_key not in {"quick", "standard", "thorough"}:
            rprint("[red]error:[/red] --preset must be one of: quick, standard, thorough")
            raise typer.Exit(2)
        if engine == "pyswatplus":
            if preset_key == "quick":
                algo = "de"
                n_gen = 10
                pop_size = 16
                objective_list = ["nse"]
            elif preset_key == "standard":
                algo = "nsga2"
                n_gen = 30
                pop_size = 32
                objective_list = ["nse"]
            else:
                algo = "nsga2"
                n_gen = 80
                pop_size = 64
                objective_list = ["nse"]
            rprint(
                f"[cyan]preset[/cyan] {preset_key} applied "
                f"(engine=pyswatplus algo={algo} n_gen={n_gen} pop_size={pop_size} objectives={','.join(objective_list)})"
            )
        else:
            if preset_key == "quick":
                algo = "dds"
                n_iter = 10
                objective_list = ["nse"]
            elif preset_key == "standard":
                algo = "sceua"
                n_iter = 30
                objective_list = ["nse", "kge", "pbias"]
            else:
                algo = "sceua"
                n_iter = 80
                objective_list = ["nse", "kge", "pbias"]
            rprint(
                f"[cyan]preset[/cyan] {preset_key} applied "
                f"(engine=spotpy algo={algo} n_iter={n_iter} objectives={','.join(objective_list)})"
            )

    if engine == "pyswatplus":
        from .calibration import Calibrator, CalibratorRequest

        if base_txtinout is None:
            rprint("[red]error:[/red] --base-txtinout is required with --calibration-engine pyswatplus")
            raise typer.Exit(2)
        if alignment_csv is None:
            rprint("[red]error:[/red] --alignment-csv is required with --calibration-engine pyswatplus")
            raise typer.Exit(2)
        algo_key = algo.strip().lower()
        if algo_key not in {"ga", "de", "nsga2"}:
            rprint("[red]error:[/red] --algo for pyswatplus must be one of: ga,de,nsga2")
            raise typer.Exit(2)
        if len(objective_list) != 1:
            rprint(
                "[red]error:[/red] pyswatplus bridge currently supports one objective per run "
                "(use --objectives nse or --objectives kge)"
            )
            raise typer.Exit(2)
        rprint(
            f"[bold]swat calibrate[/bold] → basin={basin} engine=pyswatplus "
            f"algo={algo_key} n_gen={n_gen} pop_size={pop_size}"
        )
        req = CalibratorRequest(
            basin_id=basin,
            simulation_start=date.fromisoformat(start),
            simulation_end=date.fromisoformat(end),
            txtinout_dir=_P(base_txtinout),
            observed_csv=_P(alignment_csv),
            parameters=param_list,
            objectives=objective_list,
            algorithm=algo_key,
            n_gen=int(n_gen),
            pop_size=int(pop_size),
            seed=int(seed),
            artifacts_root=_P(artifacts_root),
            engine_version=engine_version,
            builder_git_sha=None,
            warm_start=True,
            sim_output_file=objective_sim_file,
            outlet_gis_id=int(outlet_gis_id),
            binary=_P(binary).expanduser().resolve() if binary is not None else None,
        )
        from .errors import SwatBuilderError

        try:
            summary = Calibrator().run(req)
        except SwatBuilderError as exc:
            msg = str(exc)
            hint = exc.context.get("hint")
            if hint:
                msg = f"{msg}. {hint}"
            rprint(f"[red]error:[/red] {msg}")
            raise typer.Exit(2) from exc
        rprint(
            f"[green]complete[/green] engine=pyswatplus cache_hit={summary.cache_hit} "
            f"evaluations={summary.n_evaluations} "
            f"best_nse={'' if summary.best_nse is None else f'{float(summary.best_nse):.3f}'} "
            f"report={summary.outdir}"
        )
        return

    objective_mode = "real_engine" if real_engine else "proxy"
    req = CalibrationRequest(
        basin_id=basin,
        simulation_start=date.fromisoformat(start),
        simulation_end=date.fromisoformat(end),
        parameters=param_list,
        n_iter=n_iter,
        algorithm=algo,
        objective_mode=objective_mode,
        seed=seed,
        engine_version=engine_version,
        warm_start=True,
    )

    obs = None
    objective = None
    real_runs_dir = None
    baseline_alignment_for_report = _P(alignment_csv) if alignment_csv is not None else None
    baseline_nse_real: float | None = None
    if real_engine:
        from .calibration.real_engine import (
            load_observed_from_alignment_csv,
            make_real_objective,
            params_hash,
        )

        if base_txtinout is None:
            rprint("[red]error:[/red] --base-txtinout is required with --real-engine")
            raise typer.Exit(2)
        if alignment_csv is None:
            rprint("[red]error:[/red] --alignment-csv is required with --real-engine")
            raise typer.Exit(2)

        obs = load_observed_from_alignment_csv(alignment_csv)
        real_runs_dir = (
            _P(real_work_root).expanduser().resolve()
            if real_work_root is not None
            else _P(artifacts_root).expanduser().resolve() / "real_engine_runs"
        )
        objective = make_real_objective(
            base_txtinout=_P(base_txtinout),
            observed_series=obs,
            work_root=real_runs_dir,
            outlet_gis_id=int(outlet_gis_id),
            binary=_P(binary) if binary is not None else None,
            threads=1,
            timeout_s=3600.0,
            objective_sim_file=objective_sim_file,
            strict_objective_file=bool(strict_objective_file),
            allow_outlet_autodetect=bool(allow_outlet_autodetect),
        )
        # Generate an apples-to-apples baseline from the same rerun stack.
        baseline_metrics = objective({})
        baseline_nse_real = (
            float(baseline_metrics["nse"])
            if isinstance(baseline_metrics.get("nse"), (int, float))
            else None
        )
        baseline_alignment_for_report = (
            real_runs_dir / params_hash({}) / "TxtInOut" / "alignment_calibration.csv"
        )
    else:
        def _objective(theta: dict[str, float]) -> dict[str, float]:
            # Alpha deterministic proxy objective.
            if not theta:
                score = 0.0
            else:
                score = sum(float(v) for v in theta.values()) / float(len(theta))
            score = score % 1.0
            out: dict[str, float] = {}
            if "nse" in objective_list:
                out["nse"] = score
            if "kge" in objective_list:
                out["kge"] = score - 0.05
            if "pbias" in objective_list:
                out["pbias"] = (score - 0.5) * 20.0
            if "log_nse" in objective_list:
                out["log_nse"] = max(-1.0, score - 0.1)
            return out
        objective = _objective

    rprint(f"[bold]swat calibrate[/bold] → basin={basin} algo={algo} n_iter={n_iter}")
    results = run_calibration(
        req,
        artifacts_root=_P(artifacts_root),
        objective_fn=objective,
    )
    report_path = _P(report_dir) if report_dir is not None else _P(artifacts_root) / "calibration_reports"
    calibrated_alignment = None
    if real_engine and alignment_csv is not None and real_runs_dir is not None and obs is not None:
        from .calibration.real_engine import params_hash
        from .output.eval import evaluate_run

        best = max(results, key=lambda r: float(r.metrics.get("nse", float("-inf"))))
        best_run_txt = real_runs_dir / params_hash(best.parameters) / "TxtInOut"
        if best_run_txt.exists():
            calibrated_alignment = best_run_txt / "alignment_calibration.csv"
            if not calibrated_alignment.exists():
                evaluate_run(
                    best_run_txt / "basin_sd_cha_day.txt",
                    obs,
                    outlet_gis_id=int(outlet_gis_id),
                    out_alignment_csv=calibrated_alignment,
                )

    rep = write_calibration_reports(
        results,
        report_path,
        alignment_csv=baseline_alignment_for_report,
        calibrated_alignment_csv=calibrated_alignment,
    )
    cache_hits = sum(1 for r in results if r.cache_hit)
    best_nse = max(
        (r.metrics.get("nse") for r in results if isinstance(r.metrics.get("nse"), (int, float))),
        default=None,
    )
    if (
        real_engine
        and min_improvement_nse is not None
        and baseline_nse_real is not None
        and isinstance(best_nse, (int, float))
    ):
        improvement = float(best_nse) - float(baseline_nse_real)
        if improvement < float(min_improvement_nse):
            rprint(
                "[red]error:[/red] calibration improvement gate failed: "
                f"best_nse={float(best_nse):.3f}, baseline_nse={float(baseline_nse_real):.3f}, "
                f"improvement={improvement:.3f} < required={float(min_improvement_nse):.3f}"
            )
            raise typer.Exit(3)

    if real_engine:
        import json

        context_path = report_path / "calibration_run_context.json"
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(
            json.dumps(
                {
                    "objective_mode": "real_engine",
                    "objective_sim_file": objective_sim_file,
                    "strict_objective_file": bool(strict_objective_file),
                    "allow_outlet_autodetect": bool(allow_outlet_autodetect),
                    "requested_outlet_gis_id": int(outlet_gis_id),
                    "baseline_nse_real": baseline_nse_real,
                    "best_nse": None if best_nse is None else float(best_nse),
                    "min_improvement_nse": min_improvement_nse,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    rprint(
        f"[green]complete[/green] samples={len(results)} cache_hits={cache_hits} "
        f"best_nse={'' if best_nse is None else f'{float(best_nse):.3f}'} "
        f"report={rep['outdir']}"
    )


@app.command("build")
def cmd_build(
    dem: str = typer.Option(..., "--dem"),
    lon: float = typer.Option(..., "--lon"),
    lat: float = typer.Option(..., "--lat"),
    landuse: str = typer.Option(..., "--landuse"),
    soil: str = typer.Option(..., "--soil"),
    weather: str = typer.Option(..., "--weather"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    name: str = typer.Option(..., "--name", "-n"),
    workdir: str = typer.Option("swatplus_runs/default", "--workdir", "-w"),
    threads: int = typer.Option(1, "--threads", "-j"),
    run: bool = typer.Option(True, "--run/--no-run", help="Run engine after building project."),
) -> None:
    """Full pipeline: watershed → hrus → project → [run].

    The one-liner for agents and CI. Equivalent to calling each subcommand in sequence.
    """
    raise typer.Exit("Not implemented yet (Phase 1). See docs/ROADMAP.md §1.7.")


@app.command("sensitivity")
def cmd_sensitivity(
    basin: str = typer.Option(..., "--basin", help="Basin identifier (e.g., usgs_01547700)."),
    base_txtinout: str = typer.Option(..., "--base-txtinout", help="TxtInOut directory to analyze."),
    parameters: str = typer.Option(
        "CN2,ESCO,ALPHA_BF,SURLAG",
        "--parameters",
        help="Comma-separated parameter names from registry.",
    ),
    n_samples: int = typer.Option(512, "--n-samples", help="Sobol sample count."),
    observed_csv: str = typer.Option(
        None,
        "--observed-csv",
        help="Optional observed/alignment CSV for backend sensitivity scoring.",
    ),
    artifacts_root: str = typer.Option(
        "tests/_artifacts/sensitivity",
        "--artifacts-root",
        help="Root directory for sensitivity artifacts.",
    ),
) -> None:
    """Run pySWATPlus-backed Sobol sensitivity analysis and persist ranked indices."""
    from pathlib import Path as _P

    from .errors import SwatBuilderError
    from .sensitivity import SensitivityAnalyzer, SensitivityRequest

    from .params import get_parameter as _gp
    param_list = [p.strip() for p in parameters.split(",") if p.strip()]
    if not param_list:
        rprint("[red]error:[/red] at least one parameter is required")
        raise typer.Exit(2)
    try:
        for p in param_list:
            _gp(p)
    except KeyError as exc:
        rprint(f"[red]error:[/red] unknown parameter {exc}")
        raise typer.Exit(2) from exc
    rprint(f"[bold]swat sensitivity[/bold] → basin={basin} n_samples={n_samples}")
    req = SensitivityRequest(
        basin_id=basin,
        txtinout_dir=_P(base_txtinout),
        parameters=param_list,
        n_samples=int(n_samples),
        observed_csv=_P(observed_csv) if observed_csv is not None else None,
        artifacts_root=_P(artifacts_root),
    )
    try:
        res = SensitivityAnalyzer().run(req)
    except SwatBuilderError as exc:
        msg = str(exc)
        hint = exc.context.get("hint")
        if hint:
            msg = f"{msg}. {hint}"
        rprint(f"[red]error:[/red] {msg}")
        raise typer.Exit(1) from exc
    top = res.ranked[0].parameter if res.ranked else "n/a"
    rprint(
        f"[green]complete[/green] cache_hit={res.cache_hit} top_parameter={top} "
        f"report={res.outdir}"
    )


@app.command("mcp")
def cmd_mcp() -> None:
    """Start the stdio MCP server (install [mcp] extra first)."""
    from .mcp.server import main
    main()


@app.command("diagnose")
def cmd_diagnose(
    run_artifact: str = typer.Option(
        ...,
        "--run-artifact",
        help="Run artifact directory or alignment CSV path.",
    ),
    out_md: str = typer.Option(
        None,
        "--out-md",
        help="Optional markdown report path (defaults to <run-artifact>/diagnostics.md).",
    ),
) -> None:
    """Run rule-based diagnostics over a run artifact/alignment output."""
    from pathlib import Path as _P

    from .diagnostics import diagnose, write_diagnostics_report
    from .errors import SwatBuilderError

    target = _P(run_artifact).expanduser().resolve()
    rprint(f"[bold]swat diagnose[/bold] → target={target}")
    try:
        diags = diagnose(target)
    except SwatBuilderError as exc:
        rprint(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    report = (
        _P(out_md).expanduser().resolve()
        if out_md is not None
        else (target if target.is_dir() else target.parent) / "diagnostics.md"
    )
    write_diagnostics_report(diags, report)
    rprint(f"[green]complete[/green] diagnoses={len(diags)} report={report}")


@app.command("bridge-diagnose")
def cmd_bridge_diagnose(
    root: str = typer.Option(
        ...,
        "--root",
        help="Directory to scan for bridge_failure_diagnostic.json artifacts.",
    ),
    out_dir: str = typer.Option(
        None,
        "--out-dir",
        "-o",
        help="Directory to write bridge_diagnostics.json + bridge_diagnostics_summary.md (defaults to --root).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON to stdout (suppresses rich output)."
    ),
) -> None:
    """Classify and summarize pySWATPlus bridge failures across a run tree.

    Scans ``--root`` recursively for ``bridge_failure_diagnostic.json`` artifacts,
    classifies each failure into a deterministic class (IMPORT_ERROR,
    BINARY_NOT_FOUND, STAGING_MISMATCH, RUNTIME_CRASH, OUTPUT_MISSING,
    EMPTY_HISTORY, UNKNOWN), and writes a summary report.

    Exit codes:
      0 — no failures found (or summary written successfully)
      1 — failures found (check report for details)
    """
    from pathlib import Path as _P

    from .calibration.bridge_diagnostics import build_bridge_diagnostics_summary

    root_path   = _P(root).expanduser().resolve()
    out_path    = _P(out_dir).expanduser().resolve() if out_dir else None

    if not json_output:
        rprint(f"[bold]swat bridge-diagnose[/bold] → scanning {root_path}")

    summary = build_bridge_diagnostics_summary(root_path, out_dir=out_path or root_path)

    if json_output:
        print(json.dumps(summary.model_dump(), indent=2, default=str))
        raise typer.Exit(1 if summary.total_failures else 0)

    if summary.total_failures == 0:
        rprint("[green]ok[/green] no bridge failure artifacts found.")
        return

    rprint(f"[yellow]failures={summary.total_failures}[/yellow]  by class:")
    for cls, cnt in sorted(summary.by_class.items(), key=lambda x: -x[1]):
        rprint(f"  [cyan]{cls:<20}[/cyan] {cnt}")
    rprint(f"\n[bold]Recommendation:[/bold] {summary.recommendation}")
    written = (out_path or root_path) / "bridge_diagnostics_summary.md"
    rprint(f"\n[green]report[/green] → {written}")
    raise typer.Exit(1)


@app.command("lock-benchmark")
def cmd_lock_benchmark(
    txtinout: str = typer.Option(..., "--txtinout", help="Prepared TxtInOut directory."),
    observed_csv: str = typer.Option(
        ...,
        "--observed-csv",
        help="Observed daily discharge CSV (DatetimeIndex + 'discharge' column).",
    ),
    out_dir: str = typer.Option(..., "--out-dir", "-o", help="Root directory for lock artifacts."),
    basin_id: str = typer.Option(..., "--basin-id", help="Basin identifier (e.g., usgs_01547700)."),
    outlet_gis_id: int = typer.Option(1, "--outlet-gis-id", help="Gauge outlet channel GIS ID."),
    sim_source_file: str = typer.Option(
        "basin_sd_cha_day.txt",
        "--sim-source-file",
        help="Objective sim output file name inside TxtInOut.",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON to stdout (suppresses rich output)."
    ),
) -> None:
    """Lock a baseline benchmark: two-pass outlet evaluation → artifact.

    Runs auto-outlet selection then strict-pinned scoring. Persists
    ``benchmark/benchmark_lock.json``, ``alignment.csv``, ``metrics.json``,
    and ``outlet_provenance.json`` under ``--out-dir``.
    """
    from pathlib import Path as _P

    import pandas as pd

    from .calibration.locked_benchmark import lock_benchmark
    from .errors import SwatBuilderError

    if not json_output:
        rprint(f"[bold]swat lock-benchmark[/bold] → basin={basin_id} outlet={outlet_gis_id}")
    try:
        obs_df = pd.read_csv(observed_csv, index_col=0, parse_dates=True)
        obs_col = "discharge" if "discharge" in obs_df.columns else obs_df.columns[0]
        obs_series = pd.Series(
            obs_df[obs_col].astype(float).values,
            index=pd.to_datetime(obs_df.index).normalize(),
            name="obs",
        ).dropna()
        lock = lock_benchmark(
            txtinout_dir=_P(txtinout),
            obs_series=obs_series,
            out_dir=_P(out_dir),
            basin_id=basin_id,
            outlet_gis_id=outlet_gis_id,
            sim_source_file=sim_source_file,
        )
    except SwatBuilderError as exc:
        if json_output:
            import sys
            print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        else:
            rprint(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    if json_output:
        print(json.dumps(lock.model_dump()))
    else:
        rprint(
            f"[green]locked[/green] nse={lock.baseline_nse:.4f} kge={lock.baseline_kge:.4f} "
            f"outlet={lock.outlet_gis_id} artifact={lock.benchmark_dir}"
        )


@app.command("locked-calibrate")
def cmd_locked_calibrate(
    benchmark_dir: str = typer.Option(
        ..., "--benchmark-dir", help="Directory containing benchmark_lock.json."
    ),
    base_txtinout: str = typer.Option(
        ..., "--base-txtinout", help="Source TxtInOut directory (fresh copy per evaluation)."
    ),
    out_dir: str = typer.Option(..., "--out-dir", "-o", help="Root for calibration + verification artifacts."),
    parameters: str = typer.Option(
        "CN2,ALPHA_BF",
        "--parameters",
        help="Comma-separated effective parameter names.",
    ),
    n_evaluations: int = typer.Option(30, "--n-evals", help="Total real-engine evaluations."),
    binary: str = typer.Option(None, "--binary", help="Override SWAT+ engine binary path."),
    timeout_s: float = typer.Option(3600.0, "--timeout-s", help="Per-evaluation engine timeout."),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip independent verification step."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON to stdout (suppresses rich output)."
    ),
) -> None:
    """Lock → calibrate → verify workflow in one command.

    Loads an existing benchmark lock, runs real-engine DDS calibration
    against the locked alignment, then independently re-runs the best
    solution to confirm metric improvement. Writes:
    ``calibration_reports_locked/``, ``verification_summary.json``,
    ``comparison_metrics.csv``, and ``CALIBRATION_VERIFICATION.md``.
    """
    from pathlib import Path as _P

    from .calibration.locked_benchmark import (
        CalibrationEvidence,
        calibrate_against_lock,
        verify_calibration,
    )
    from .errors import SwatBuilderError

    param_list = [p.strip() for p in parameters.split(",") if p.strip()]
    if not param_list:
        if not json_output:
            rprint("[red]error:[/red] at least one parameter is required")
        raise typer.Exit(2)

    if not json_output:
        rprint(
            f"[bold]swat locked-calibrate[/bold] → params={','.join(param_list)} "
            f"n_evals={n_evaluations}"
        )
    try:
        evidence: CalibrationEvidence = calibrate_against_lock(
            lock=_P(benchmark_dir),
            base_txtinout=_P(base_txtinout),
            out_dir=_P(out_dir),
            parameters=param_list,
            n_evaluations=n_evaluations,
            binary=_P(binary) if binary else None,
            timeout_s=timeout_s,
        )
    except SwatBuilderError as exc:
        if not json_output:
            rprint(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if not json_output:
        rprint(
            f"[green]calibrated[/green] n={evidence.n_evaluations} "
            f"best_nse={evidence.best_nse:.4f} report={evidence.outdir}"
        )

    verification_result = None
    if not skip_verify:
        try:
            verification_result = verify_calibration(
                lock=_P(benchmark_dir),
                best_solution_json=_P(evidence.best_solution_json),
                base_txtinout=_P(base_txtinout),
                out_dir=_P(out_dir),
                binary=_P(binary) if binary else None,
                timeout_s=timeout_s,
            )
        except SwatBuilderError as exc:
            if not json_output:
                rprint(f"[yellow]warning:[/yellow] verification failed: {exc}")

    if json_output:
        out: dict[str, object] = {
            "status": "success",
            "calibration": evidence.model_dump(),
            "verification": verification_result.model_dump() if verification_result else None,
        }
        print(json.dumps(out))
    elif verification_result is not None:
        status = "IMPROVED" if verification_result.improved else "NO IMPROVEMENT"
        rprint(
            f"[green]verified[/green] status={status} "
            f"delta_nse={verification_result.delta_nse:+.4f} "
            f"delta_kge={verification_result.delta_kge:+.4f} "
            f"report={verification_result.verification_summary_path}"
        )


@app.command("readiness-table")
def cmd_readiness_table(
    locks_root: str = typer.Option(
        ..., "--locks-root", help="Root directory to scan for verification_summary.json files."
    ),
    out_md: str = typer.Option(
        None,
        "--out-md",
        help="Optional path to write the markdown readiness table.",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON to stdout (suppresses rich output)."
    ),
) -> None:
    """Build a compact multi-lock readiness table.

    Scans ``--locks-root`` recursively for ``verification_summary.json`` and
    ``benchmark_lock.json`` artifacts, then prints a markdown table of
    baseline vs calibrated NSE/KGE deltas and verification status.
    """
    from pathlib import Path as _P

    from .calibration.locked_benchmark import build_readiness_table

    if not json_output:
        rprint(f"[bold]swat readiness-table[/bold] → root={locks_root}")
    rows = build_readiness_table(
        _P(locks_root),
        out_md=_P(out_md) if out_md else None,
    )
    if json_output:
        print(json.dumps({"row_count": len(rows), "rows": [r.model_dump() for r in rows]}))
        return
    if not rows:
        rprint("[yellow]warning:[/yellow] no lock or verification artifacts found under root.")
        return

    rprint(
        f"\n| {'Basin':<20} | {'Baseline NSE':>12} | {'Cal. NSE':>10} | {'ΔNSE':>8} | {'Status':<25} |"
    )
    rprint(f"| {'-'*20} | {'-'*12} | {'-'*10} | {'-'*8} | {'-'*25} |")
    for r in rows:
        b = f"{r.baseline_nse:>12.4f}" if r.baseline_nse is not None else f"{'n/a':>12}"
        c = f"{r.calibrated_nse:>10.4f}" if r.calibrated_nse is not None else f"{'n/a':>10}"
        d = f"{r.delta_nse:>+8.4f}" if r.delta_nse is not None else f"{'n/a':>8}"
        rprint(f"| {r.basin_id:<20} | {b} | {c} | {d} | {r.verification_status:<25} |")
    if out_md:
        rprint(f"\n[green]table written[/green] → {out_md}")


@app.command("realism-audit")
def cmd_realism_audit(
    alignment_csvs: str = typer.Option(
        ...,
        "--alignment-csvs",
        help=(
            "Comma-separated list of alignment CSV paths, each prefixed with "
            "basin_id:: (e.g. 'usgs_01547700::path/to/alignment.csv,...')."
        ),
    ),
    out_dir: str = typer.Option(
        "tests/_artifacts/realism_audit",
        "--out-dir",
        "-o",
        help="Directory to write realism_audit.json + realism_audit.md.",
    ),
    split_year: int = typer.Option(
        None,
        "--split-year",
        help="Year boundary for calibration/validation split (e.g. 2018 → cal<2018, val>=2018).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON to stdout."
    ),
) -> None:
    """Physical realism audit from alignment CSV files (no binary required).

    Computes NSE, KGE, PBIAS, BFI ratio, Q90/Q10 ratios, seasonal NSE,
    and cal/val split metrics. Detects volume bias, baseflow pathology,
    and peak/low-flow mismatch. Writes ``realism_audit.json`` + ``realism_audit.md``.
    """
    from pathlib import Path as _P

    from .output.realism import audit_realism, run_realism_audit

    entries = [e.strip() for e in alignment_csvs.split(",") if e.strip()]
    basin_alignments = []
    for entry in entries:
        if "::" in entry:
            basin_id, csv_path = entry.split("::", 1)
            basin_alignments.append((basin_id.strip(), _P(csv_path.strip())))
        else:
            p = _P(entry.strip())
            basin_alignments.append((p.parent.name, p))

    if not basin_alignments:
        rprint("[red]error:[/red] no alignment CSVs provided")
        raise typer.Exit(2)

    if not json_output:
        rprint(f"[bold]swat realism-audit[/bold] → {len(basin_alignments)} basin(s)")

    audits = run_realism_audit(basin_alignments, out_dir=_P(out_dir), split_year=split_year)

    if json_output:
        print(json.dumps({"audits": [a.model_dump() for a in audits]}, indent=2, default=str))
        return

    for a in audits:
        f = a.period_full
        verdict_color = "green" if "benchmark" in a.realism_verdict else (
            "yellow" if "improving" in a.realism_verdict else "red"
        )
        rprint(
            f"  [{verdict_color}]{a.basin_id}[/{verdict_color}]  "
            f"NSE={f.nse:.3f if f.nse is not None else 'n/a'}  "
            f"KGE={f.kge:.3f if f.kge is not None else 'n/a'}  "
            f"PBIAS={f.pbias_pct:.1f if f.pbias_pct is not None else 'n/a'}%  "
            f"BFI_ratio={f.bfi_ratio:.2f if f.bfi_ratio is not None else 'n/a'}  "
            f"verdict={a.realism_verdict}"
        )
        for p in a.pathologies:
            rprint(f"    [yellow]![/yellow] {p}")
    rprint(f"\n[green]report[/green] → {out_dir}")


if __name__ == "__main__":
    app()
