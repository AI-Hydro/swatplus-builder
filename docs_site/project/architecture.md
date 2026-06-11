# Architecture

swatplus-builder is real software: a layered Python package with a typed public
API, a governed end-to-end workflow, a vendored SWAT+ editor, and a test suite.

## One-screen view

```
┌───────────────────────────────────────────────────────────────────┐
│  Caller   (AI agent via MCP  │  direct Python import  │  Typer CLI) │
└───────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌───────────────────────────────────────────────────────────────────┐
│  swatplus_builder.tools.agent     (4 typed functions — public API)  │
│    build_watershed · create_hrus · generate_swat_project · run_swat │
└───────────────────────────────────────────────────────────────────┘
       │                    │                        │
       ▼                    ▼                        ▼
┌──────────────┐   ┌──────────────────┐   ┌────────────────────┐
│ ...gis       │   │ ...db            │   │ ...run             │
│  delineation │   │  schema          │   │  swatplus          │
│  terrain     │──▶│  project         │──▶│  (subprocess)      │
│  landuse     │   │  writer (gis_*)  │   │                    │
│  soil        │──┐│  editor.api ── vendored swat-model/        │
│  hru         │  ││              swatplus-editor               │
│  topology    │  │└──────────────────┘   └────────────────────┘
└──────────────┘  │
                  ▼
        evidence bundle (JSON / JSONL)
```

## Module map

| Package | Responsibility |
|---|---|
| `tools` | the 4-function public build API (`tools/agent.py`) |
| `gis` | delineation, terrain, land use, soil, HRU, topology |
| `db` | SWAT+ SQLite schema + project assembly (`gis_*` tables) |
| `editor` | vendored `swat-model/swatplus-editor` (SQLite → `TxtInOut`) |
| `run` | engine invocation (subprocess) |
| `calibration` | locked-benchmark protocol, real-engine DDS, bridge diagnostics |
| `evaluation` | `evaluate_run` — the authoritative metric source |
| `workflows` | `usgs_e2e.py` (governed E2E + claim logic), `contracts.py`, `full_build.py` |
| `mcp` | FastMCP server exposing the 11-tool surface |
| `output` | diagnostics writers (mass / volume / ET partition) |
| `soil`, `weather`, `ref`, `params`, `validation`, `sensitivity` | supporting stages |

## Governance lives in the workflow layer

Claim logic — check evaluation, tier emission, and the allowed/blocked claim
lists — lives in the `workflows` package. The SWAT+ checks are *implementations*
registered against a general governance pattern; the longer-term direction (see
[Six invariants](../concepts/invariants.md)) is to separate a hydrology-free
governance core from these SWAT+ check implementations.

## What this package does **not** do

- **No QGIS / PyQGIS / QSWATPlus plugin.** GIS uses WhiteboxTools + rasterio +
  geopandas. We aim for numerical agreement within a few percent of QSWATPlus,
  not byte-for-byte parity.
- **No pySWATPlus replacement.** pySWATPlus edits an existing `TxtInOut` and
  runs calibrations; swatplus-builder *builds* the `TxtInOut`. They are
  complementary. The pySWATPlus bridge here is optional and non-authoritative.
- **No bundled SWAT+ engine.** Bring your own `swatplus_exe` and mount it.

For upstream sources and pinned versions, see
[Citing & references](citing.md).
