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


@app.command("version")
def cmd_version() -> None:
    """Print version."""
    rprint(f"[bold]swatplus-builder[/bold] v{__version__}")


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

    param_list = [p.strip() for p in parameters.split(",") if p.strip()]
    if not param_list:
        rprint("[red]error:[/red] at least one parameter is required")
        raise typer.Exit(2)
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
        raise typer.Exit(2) from exc
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
        raise typer.Exit(2) from exc
    report = (
        _P(out_md).expanduser().resolve()
        if out_md is not None
        else (target if target.is_dir() else target.parent) / "diagnostics.md"
    )
    write_diagnostics_report(diags, report)
    rprint(f"[green]complete[/green] diagnoses={len(diags)} report={report}")


if __name__ == "__main__":
    app()
