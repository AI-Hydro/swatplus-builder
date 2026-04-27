# swatplus-builder

> Headless, agent‑friendly generator for SWAT+ project inputs (SQLite + `TxtInOut`) — **no QGIS required**.

`swatplus-builder` is a standalone Python package that produces valid SWAT+ model inputs from GIS primitives (DEM, land use, soil, weather) entirely in Python. It is designed to be called as a set of typed tool functions by AI agents (via MCP or direct function calls) or from the `swat` CLI in notebooks and CI pipelines.

The package deliberately **avoids QGIS, PyQGIS, and the QSWATPlus plugin at runtime**. It replaces the GIS stage with pure‑Python tooling (WhiteboxTools, pyflwdir, rasterio, geopandas) and delegates the SQLite → `TxtInOut` translation to the vendored, open‑source [SWAT+ Editor Python API](https://github.com/swat-model/swatplus-editor) (Peewee ORM + SQLite).

---

## Status

**Alpha, v0.4.0 — Feature-complete for single-basin hydrological workflows.**
- [x] Pure-Python GIS (WhiteboxTools)
- [x] Automated SWAT+ Project Generation
- [x] Weather (GridMET / Synthetic)
- [x] **USGS NWIS Validation**: Automated observed discharge fetching.
- [x] **Evaluation Suite**: Dependency-free NSE, KGE, and BFI metrics.
- [x] **Manuscript Suite**: 7+ publication-ready figure types in PNG/PDF.

See:

- [`ROADMAP.md`](ROADMAP.md) — phased plan with checkboxes
- [`PROGRESS.md`](PROGRESS.md) — running progress journal
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architecture + diagrams
- [`DECISIONS.md`](DECISIONS.md) — architecture decision records (ADRs)
- [`docs/SCHEMA.md`](docs/SCHEMA.md) — SWAT+ `gis_*` table contracts
- [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — plugging into AI‑Hydro and other agent frameworks
- [`docs/REFERENCES.md`](docs/REFERENCES.md) — reverse‑engineering notes on QSWATPlus / SWAT+ Editor

---

## Soil Fidelity Flags

Every run now persists explicit soil realism metadata in `metadata.json`:

- `soil_mode`: `high_fidelity` | `fallback` | `synthetic`
- `pct_fallback_soils`: fraction of basin polygons that used fallback soil profiles

Behavior:

- If fallback usage exceeds 25% (default), the run emits a warning.
- Threshold is configurable via `SWATPLUS_SOIL_FALLBACK_WARN_THRESHOLD`.
- Generated figures include a visible quality annotation for fallback/synthetic runs.

Use `swat inspect <run_path>` to inspect persisted metadata for any run.

---

## Install

```bash
# Core only
pip install swatplus-builder

# With the GIS stack (recommended for actually running anything)
pip install "swatplus-builder[gis]"

# With HyRiver helpers (USGS gauges, NHDPlus, py3dep, GridMET)
pip install "swatplus-builder[gis,hyriver]"

# Full dev environment
pip install -e ".[all]"
```

SWAT+ engine binary and reference databases are fetched by bootstrap scripts (see `scripts/`). They are **not** pip dependencies.

---

## CLI (`swat`)

The command is **`swat`** — not `swatplus-builder`, not `swatgen`. What users remember.

```bash
# Full pipeline (one‑liner)
swat build \
  --dem dem.tif \
  --lon -77.12 --lat 41.45 \
  --landuse nlcd.tif --soil mukey.tif \
  --weather weather/ \
  --start 2000-01-01 --end 2010-12-31 \
  --name marsh_creek -w runs/marsh_creek/

# Or step by step
swat watershed --dem dem.tif --lon -77.12 --lat 41.45  -w runs/marsh_creek/
swat hrus      --landuse nlcd.tif --soil mukey.tif      -w runs/marsh_creek/
swat project   --weather weather/ --start 2000-01-01 --end 2010-12-31 --name marsh_creek -w runs/marsh_creek/
swat run       -w runs/marsh_creek/

# Launch MCP server
swat-mcp

# Benchmark validation over a basin suite JSON
swat validate --basins basins/curated_v1.json
```

---

## Agent‑facing API (4 tools)

```python
from swatplus_builder.tools import (
    build_watershed,
    create_hrus,
    generate_swat_project,
    run_swat,
)

ws = build_watershed(
    dem_path="data/dem.tif",
    outlet=(-77.123, 41.456),         # or usgs_id="01547700"
    stream_threshold_cells=500,
    workdir="runs/marsh_creek/",
)

hrus = create_hrus(
    watershed=ws,
    landuse_raster="data/nlcd_2019.tif",
    soil_raster="data/gnatsgo_mukey.tif",
)

project = generate_swat_project(
    watershed=ws,
    hrus=hrus,
    weather_dir="data/weather/",
    sim_start="2000-01-01",
    sim_end="2010-12-31",
    project_name="marsh_creek_v1",
)

result = run_swat(project, threads=4)
print(result.summary)
```

Every function is **pure, stateless, file‑system‑side‑effect‑only**. No Qt event loop, no global QGIS init, no hidden state. Safe to call concurrently on different `workdir`s.

---

## MCP server (plug into any MCP host)

```bash
pip install "swatplus-builder[mcp]"
swat-mcp   # stdio transport
```

MCP client config (Claude Desktop / Cursor / Continue / any MCP host):

```json
{
  "mcpServers": {
    "swatplus-builder": {
      "command": "swat-mcp",
      "args": [],
      "env": {
        "SWATGEN_REFERENCE_DB_DIR": "~/.swatplus-builder/reference_dbs",
        "SWATPLUS_EXE": "/usr/local/bin/swatplus"
      }
    }
  }
}
```

See `docs/INTEGRATION.md` for AI‑Hydro‑specific wiring and LangChain / LangGraph adapters.

---

## What this package does NOT do

- **It does not wrap QGIS.** If you need byte‑for‑byte QSWATPlus parity, use QSWATPlus. We aim for numerical agreement within a few percent.
- **It does not replace `pySWATPlus`.** `pySWATPlus` reads/edits an existing `TxtInOut` and runs calibrations. `swatplus-builder` builds the `TxtInOut` in the first place. They are complementary.
- **It does not ship the SWAT+ engine.** You bring your own `swatplus` executable.

---

## License

MIT. See [LICENSE](LICENSE).

Vendored: [`swat-model/swatplus-editor`](https://github.com/swat-model/swatplus-editor) (Apache‑2.0, pinned commit in `docs/REFERENCES.md`). Reference databases downloaded at install time from the `ai-hydro/swatplus-reference-data` mirror.
