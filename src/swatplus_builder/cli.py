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


@app.command("mcp")
def cmd_mcp() -> None:
    """Start the stdio MCP server (install [mcp] extra first)."""
    from .mcp.server import main
    main()


if __name__ == "__main__":
    app()
