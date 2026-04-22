# Integration Guide

`swatplus_builder` is designed to be plugged into any agent framework with **zero coupling to AI‑Hydro's code**. This document shows how.

---

## 1. AI‑Hydro (first‑class integration)

AI‑Hydro already exposes MCP tool servers under `ai_hydro/mcp/`. Integrating is a three‑line change.

### 1.1 As a sibling MCP server

Add `swatplus_builder` to AI‑Hydro's MCP registry:

```python
# ai_hydro/mcp/registry.py (or equivalent)
from ai_hydro.mcp import register_server

register_server(
    name="swatplus_builder",
    command="swat-mcp",        # installed by `pip install swatplus_builder[mcp]`
    env={
        "SWATGEN_REFERENCE_DB_DIR": "~/.swatplus_builder/reference_dbs",
        "SWATPLUS_EXE": "/usr/local/bin/swatplus",
    },
    description="Generate SWAT+ project inputs headlessly.",
    tags=["swatplus", "watershed", "hru", "physical-model"],
)
```

The AI‑Hydro agent now has four new tools discoverable via its regular tool listing:
`build_watershed`, `create_hrus`, `generate_swat_project`, `run_swat`.

### 1.2 As a direct Python import (no MCP indirection)

For in‑process use (e.g. from AI‑Hydro's `modelling/` subpackage):

```python
# ai_hydro/integrations/swatplus_builder/__init__.py
from swatplus_builder.tools import (
    build_watershed,
    create_hrus,
    generate_swat_project,
    run_swat,
)

__all__ = [
    "build_watershed",
    "create_hrus",
    "generate_swat_project",
    "run_swat",
]
```

AI‑Hydro's existing data layers (`ai_hydro.data.streamflow`, `ai_hydro.data.forcing`, …) compose cleanly because `swatplus_builder` accepts plain file paths and paths are already how AI‑Hydro moves data.

### 1.3 As an MCP *and* direct import simultaneously

Both are supported. Prefer direct import when your agent is already Python and latency matters; prefer MCP when the agent is a remote LLM or when tool isolation is desirable.

---

## 2. Any MCP‑compatible host (Claude Desktop, Cursor, Continue, etc.)

Standard MCP config:

```json
{
  "mcpServers": {
    "swatplus_builder": {
      "command": "swat-mcp",
      "args": [],
      "env": {
        "SWATGEN_REFERENCE_DB_DIR": "/home/user/.swatplus_builder/reference_dbs",
        "SWATPLUS_EXE": "/usr/local/bin/swatplus"
      }
    }
  }
}
```

Tools exposed (names stable from v0.1 onward):

- `build_watershed(dem_path: str, outlet: Outlet, stream_threshold_cells?: int, workdir?: str) -> WatershedResult`
- `create_hrus(watershed: WatershedResult, landuse_raster: str, soil_raster: str, slope_bands?: list[float], filters?: HruFilters) -> HRUResult`
- `generate_swat_project(watershed: WatershedResult, hrus: HRUResult, weather_dir: str, sim_start: str, sim_end: str, project_name: str) -> SwatPlusProject`
- `run_swat(project: SwatPlusProject, threads?: int) -> SwatPlusRun`

JSON schemas are generated automatically from pydantic models (ADR‑005).

---

## 3. LangChain / LangGraph / CrewAI / AutoGen

Wrap each tool with the agent framework's tool decorator:

```python
# LangChain example
from langchain_core.tools import tool
from swatplus_builder.tools import build_watershed as _bw

@tool
def build_watershed(dem_path: str, outlet_lon: float, outlet_lat: float) -> dict:
    """Delineate a watershed from a DEM and a lon/lat outlet. Returns paths to subbasins, channels, and the routing topology."""
    return _bw(dem_path=dem_path, outlet=(outlet_lon, outlet_lat)).model_dump()
```

For LangGraph, a state‑machine wrapper is available at `swatplus_builder.tools.langgraph_nodes` (Phase 3).

---

## 4. Plain Python / Jupyter

```python
from swatplus_builder.tools import build_watershed, create_hrus, generate_swat_project, run_swat

ws = build_watershed(dem_path="dem.tif", outlet=(-77.1, 41.5))
hrus = create_hrus(watershed=ws, landuse_raster="nlcd.tif", soil_raster="mukey.tif")
proj = generate_swat_project(watershed=ws, hrus=hrus, weather_dir="weather/",
                             sim_start="2000-01-01", sim_end="2010-12-31",
                             project_name="demo")
run = run_swat(proj)
print(run.paths.output_cha)
```

Same functions, same signatures, agent or not.

---

## 5. CLI (Typer)

For CI pipelines and quick experiments:

```bash
swat build-watershed --dem dem.tif --outlet -77.1 41.5 --workdir runs/demo/
swat create-hrus     --workdir runs/demo/ --landuse nlcd.tif --soil mukey.tif
swat build-project   --workdir runs/demo/ --weather weather/ \
                        --start 2000-01-01 --end 2010-12-31 --name demo
swat run             --workdir runs/demo/
# Or all-in-one:
swat pipeline        --dem dem.tif --outlet -77.1 41.5 \
                        --landuse nlcd.tif --soil mukey.tif --weather weather/ \
                        --start 2000-01-01 --end 2010-12-31 --workdir runs/demo/
```

---

## 6. Versioning & stability promises

- **Semver from v0.1 onward.** Patch = bug fixes, minor = new features (backward‑compatible), major = API breaks.
- **Tool signatures** are part of the public contract and change only on major bumps.
- **Project SQLite schema** is frozen from v0.1; migrations provided for any future bumps.
- **Vendored SWAT+ Editor commit** is recorded in `REFERENCES.md` and only bumped on minor/major releases.

---

## 7. Isolation from AI‑Hydro's other dependencies

`swatplus_builder` depends on **none** of AI‑Hydro's packages. It is publishable independently to PyPI, usable in non‑Python runtimes via MCP, and testable without the AI‑Hydro monorepo checked out.

Reverse direction: AI‑Hydro depends on `swatplus_builder` via `pyproject.toml` (optional extra) and/or its MCP registry — never by reaching into `swatplus_builder`'s internals.
