# Architecture

## 1. One‑screen view

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Caller  (AI agent via MCP  │  direct Python import  │  Typer CLI)      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  swatplus_builder.tools.agent       (4 typed functions — the public API)     │
│    build_watershed · create_hrus · generate_swat_project · run_swat     │
└─────────────────────────────────────────────────────────────────────────┘
          │                        │                         │
          ▼                        ▼                         ▼
┌──────────────────┐    ┌──────────────────────┐    ┌────────────────────┐
│ swatplus_builder.gis  │    │ swatplus_builder.db       │    │ swatplus_builder.run    │
│  delineation     │    │  schema              │    │  swatplus          │
│  terrain         │───▶│  project             │───▶│  (subprocess)      │
│  landuse         │    │  writer (gis_*)      │    │                    │
│  soil            │───┐│                      │    │                    │
│  hru             │   ││  editor.api  ─── vendored swat-model/          │
│  topology        │   ││                 swatplus-editor/src/api        │
└──────────────────┘   │└──────────────────────┘    └────────────────────┘
          │            │           │                         │
          │            └───────────┼─────────────────────────┘
          ▼                        ▼
┌──────────────────┐    ┌──────────────────────┐    ┌────────────────────┐
│ weather.gridmet  │    │ calibration.nwis     │    │ output.plots       │
│ weather.synthetic│───▶│ output.eval (metrics)│───▶│ (manuscript suite) │
└──────────────────┘    └──────────────────────┘    └────────────────────┘
          │                        │                         │
          ▼                        ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Project workdir (content-addressed, stateless between calls)           │
│   ├ <project>.sqlite             ← gis_* + editor-populated model tables│
│   ├ reference_dbs/               ← symlinks to shared cache             │
│   ├ Watershed/                                                          │
│   │   ├ Shapes/  (subbasins, channels, outlets, hrus, lsus)             │
│   │   └ Rasters/ (dem, flow_dir, flow_acc, slope, landuse, soil)        │
│   └ Scenarios/Default/TxtInOut/  ← SWAT+ inputs + outputs               │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2. Layering rules

- **Pure.** Every module accepts explicit inputs and returns explicit outputs or writes to the caller‑owned `workdir`. No globals, no singletons, no process‑wide init.
- **Import direction.** `tools` → `gis | db | editor | weather | run`. Layers never import upward.
- **No cross‑layer QGIS.** Neither `tools` nor any helper imports `qgis*`. Static check in CI: `grep -r "import qgis" src/` must be empty.
- **Vendored code is isolated.** `editor/vendored/swatplus_editor/` is imported only from `editor/api.py`. Do not reach into its internals from elsewhere.

## 3. Data flow for `generate_swat_project`

```
WatershedResult + HRUResult + weather_dir
   │
   ├─▶ db.project.create(project_name, workdir)         # copies sqlite template
   │       └─ writes project_config row
   │
   ├─▶ db.writer.write_all(watershed, hrus, project_db) # gis_* tables
   │       ├─ gis_points          (outlets, inlets, ptsrc, reservoirs)
   │       ├─ gis_channels        (one per stream link)
   │       ├─ gis_subbasins       (one per subbasin)
   │       ├─ gis_lsus            (floodplain + upslope per subbasin)
   │       ├─ gis_hrus            (one per unique LU×Soil×Slope within LSU)
   │       ├─ gis_water           (reservoirs/ponds/wetlands)
   │       └─ gis_routing         (source_cat/sink_cat/hyd_typ graph)
   │
   ├─▶ weather.gridmet.write(weather_dir, workdir/weather/)   # .cli/.pcp/.tmp/…
   │
   ├─▶ editor.api.run("create_database", db_type="project", …)
   ├─▶ editor.api.run("import_gis",     project_db_file=…, delete_existing=y)
   ├─▶ editor.api.run("import_weather", import_type="wgn",      …)
   ├─▶ editor.api.run("import_weather", import_type="observed", …)
   └─▶ editor.api.run("write_files",    project_db_file=…)
           └─ produces Scenarios/Default/TxtInOut/
```

## 4. Configuration

Configuration is typed, explicit, and injectable. No YAML sprawl, no env‑var stew.

```python
from swatplus_builder.config import Settings

s = Settings(
    reference_db_dir="~/.swatplus_builder/reference_dbs",
    swatplus_exe="/usr/local/bin/swatplus",
    whitebox_verbose=False,
    delineation_backend="whitebox",          # or "pyflwdir"
    hru_filter={"land_pct": 20, "soil_pct": 10, "slope_pct": 5},
)
```

Settings is a `pydantic.BaseSettings` subclass; every field has a default, an env‑var alias (`SWATGEN_*`), and a validator. Tools accept an optional `settings=` kwarg for per‑call overrides.

## 5. Errors

Three error classes, all in `swatplus_builder.errors`:

- `SwatgenesisInputError` — bad user input (missing DEM, outlet outside basin, unsupported CRS).
- `SwatgenesisPipelineError` — a GIS/DB stage produced invalid output (e.g. empty subbasin set, cycle in routing graph).
- `SwatgenesisExternalError` — SWAT+ engine crashed, editor API returned non‑zero, WhiteboxTools binary missing.

Every error has a `.context: dict` attached (inputs, intermediate paths, stderr tail) for agent‑side debugging.

## 6. Observability

- Logger: `logging.getLogger("swatplus_builder")`. Structured JSON when `SWATGEN_LOG_FORMAT=json`, rich‑formatted text otherwise.
- Each tool emits three events per stage: `start`, `progress(pct, message)`, `done(artifact_paths, metrics)`.
- An MCP client receives `progress` as MCP notifications.

## 7. Concurrency

- Single tool call = single project workdir. Safe to run many in parallel on one machine (no global state, no Qt).
- The SWAT+ engine itself is OpenMP‑threaded via the `threads` argument to `run_swat`.
- Editor API is subprocessed in Phase 1 (simple, robust). Phase 3 may switch to in‑process (`from actions.write_files import WriteFiles`) for lower latency.

## 8. Content‑addressed runs (Phase 3)

`workdir = base / sha256(inputs)[:16]`. Rerunning the same inputs finds the cached run and returns its artifacts. Agents can query `has_run(inputs) -> bool` before paying for compute.
