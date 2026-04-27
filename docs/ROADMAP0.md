# Roadmap

> Living document. Tick checkboxes as work lands. Update `PROGRESS.md` with dated notes.

**Strategic choice: Path C (Hybrid).** Pure‑Python GIS stage → writes SWAT+ `gis_*` tables → vendored SWAT+ Editor Python API translates to `TxtInOut`. No QGIS at runtime, anywhere. Rationale recorded in [`DECISIONS.md` ADR‑001](DECISIONS.md).

---

## Phase 0 — Structure & documentation  (`v0.0.1`)

**Goal:** repo scaffold, living docs, agreed API surface. No runtime code.

- [x] Archive misleading artifacts (old `swatplus_builder.py`, SWAT2012 `TxtInOut`, outdated `.docx` notes).
- [x] Create package layout (`src/swatplus_builder/{gis,db,editor,weather,run,tools,mcp}`).
- [x] `pyproject.toml` with optional extras (`gis`, `hyriver`, `mcp`, `swatplus`, `dev`, `docs`).
- [x] `README.md`, `LICENSE` (MIT), `.gitignore`.
- [x] Write `ROADMAP.md`, `PROGRESS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `SCHEMA.md`, `INTEGRATION.md`, `REFERENCES.md`.
- [x] Module skeletons with typed signatures + `NotImplementedError` + TODOs.
- [x] Map what to port from `pipeline/` and `SWAT_data_prep/` (see `REFERENCES.md §Reuse Map`).
- [ ] Init git repo, first commit.
- [ ] Open the repo on GitHub under a namespace TBD (`ai-hydro/swatplus_builder` proposed).
- [ ] CI: lint + typecheck + unit‑test skeleton (no integration tests yet).

**Exit criteria:** `pip install -e .` works; `python -c "import swatplus_builder"` succeeds; `swat --help` prints usage.

---

## Phase 1 — MVP: end‑to‑end headless SWAT+ run  (`v0.1.0`) [DONE]

**Goal:** an agent can call the 4 tool functions on a real DEM/LU/soil/weather set and get a SWAT+ run that produces non‑zero `output.cha` flows. Dominant‑HRU mode only.

### 1.1 Reference assets
- [ ] `scripts/bootstrap_reference_dbs.sh`: downloads & caches `swatplus_datasets.sqlite`, `swatplus_soils.sqlite`, `swatplus_wgn.sqlite` into `$SWATGEN_REFERENCE_DB_DIR`.
- [ ] `scripts/bootstrap_swatplus_binary.sh`: downloads the SWAT+ engine `rev60+` for Linux/Mac/Windows. Pinned URL in `REFERENCES.md`.
- [ ] Vendor `swat-model/swatplus-editor` at a pinned commit under `src/swatplus_builder/editor/vendored/`. Record commit SHA in `REFERENCES.md`.

### 1.2 GIS stage (`swatplus_builder.gis`)
- [ ] `gis/delineation.py`: WhiteboxTools pipeline
  - [ ] `BreachDepressionsLeastCost` → conditioned DEM
  - [ ] `D8Pointer` + `D8FlowAccumulation`
  - [ ] `ExtractStreams` (threshold configurable in cells)
  - [ ] `StreamLinkIdentifier` → per‑link IDs
  - [ ] `Watershed` (snap outlet, multi‑outlet support)
  - [ ] `HackStreamOrder` / `StrahlerStreamOrder`
  - [ ] Polygonize subbasins + vectorize streams → `GeoDataFrame`s
  - [ ] Build `networkx.DiGraph` of subbasin routing
- [ ] `gis/terrain.py`: slope (degrees), slope classes, elevation stats per subbasin. Port from `pipeline/02_get_terrain.py`.
- [ ] `gis/landuse.py`: clip, reclassify, zonal stats per subbasin. Port from `pipeline/03_get_landuse.py`.
- [ ] `gis/soil.py`: gNATSGO ingestion into `swatplus_soils.sqlite`‑compatible lookups. Port from `pipeline/04_get_soil.py`, extended to emit `soils_sol` / `soils_sol_layer` rows.
- [ ] `gis/hru.py`: **per‑subbasin** LU×Soil×Slope overlay (extends `pipeline/05_create_hru.py` which is basin‑global). Dominant HRU per LSU.
- [ ] `gis/topology.py`: emits `gis_routing` rows from the `networkx` graph (hyd types: `tot`, `sur`, `lat`, `til`, `aqu`).

### 1.3 Database stage (`swatplus_builder.db`)
- [ ] `db/schema.py`: DDL for `gis_points`, `gis_channels`, `gis_subbasins`, `gis_lsus`, `gis_hrus`, `gis_water`, `gis_routing`, `gis_elevationbands`, `project_config`. Copied from `QSWATPlus/DBUtils.py` (see `SCHEMA.md`).
- [ ] `db/project.py`: creates `<proj>.sqlite` from template, populates `project_config`.
- [ ] `db/writer.py`: typed writers for each `gis_*` table, validates referential integrity before commit.

### 1.4 Editor stage (`swatplus_builder.editor`)
- [ ] `editor/api.py`: subprocess wrapper around vendored `swatplus_api.py`; also supports in‑process mode (`from actions.write_files import WriteFiles`) for lower latency.
- [ ] Actions wired: `create_database`, `import_gis`, `import_weather`, `write_files`, `read_output`.

### 1.5 Weather stage (`swatplus_builder.weather`)
- [ ] `weather/gridmet.py`: GridMET → SWAT+ `.cli`/`.pcp`/`.tmp`/`.hmd`/`.wnd`/`.slr`. Port from `pipeline/06_get_forcing.py`, extended with SWAT+ formatting.
- [ ] `weather/wgn.py`: nearest‑station WGN lookup from `swatplus_wgn.sqlite`.

### 1.6 Run stage (`swatplus_builder.run`)
- [ ] `run/swatplus.py`: `subprocess.run(swatplus_exe, cwd=TxtInOut_dir)`, captures stdout/stderr, detects common failure modes, returns paths to `output.hru`, `output.cha`, etc.

### 1.7 Agent‑facing API (`swatplus_builder.tools`)
- [ ] `tools/agent.py`: the four functions from `README.md`. Pure, typed, no hidden state.
- [ ] `tools/__init__.py`: re‑exports; keeps import surface small.
- [ ] `cli.py` (Typer): `swat build-watershed`, `swat create-hrus`, `swat build-project`, `swat run`, `swat pipeline` (all‑in‑one).

### 1.8 Tests
- [ ] `tests/fixtures/marsh_creek/`: a small curated basin (USGS 01547700, ~60 km²) with DEM, NLCD tile, gNATSGO tile, GridMET timeseries.
- [ ] `test_delineation.py`: subbasin area within 2% of a hand‑delineated reference.
- [ ] `test_gis_writer.py`: writes `gis_*` tables; asserts row counts and referential integrity.
- [ ] `test_editor_roundtrip.py`: `import_gis` + `write_files` against a known project db; diff `TxtInOut` against a golden fixture.
- [ ] `test_end_to_end.py` (marked `@pytest.mark.slow`): agent API → SWAT+ engine → `output.cha` has >0 mean flow.

**Exit criteria:** `pytest -m "not slow"` green; `pytest -m slow` green when SWAT+ binary + reference DBs are installed.

---

## Phase 2 — Fidelity & multi‑HRU  (`v0.2.0`) [DONE]

**Goal:** quantitatively close the gap to QSWATPlus on a fixture basin; support realistic HRU filters.

- [ ] Percent‑filter HRU selection (area%, landuse%, soil%, slope%) ported from `QSWATPlus/hrus.py`.
- [ ] Landscape unit (LSU) split using Height‑Above‑Nearest‑Drainage (`whitebox.elevation_above_stream`) instead of naive channel buffer.
- [ ] Reservoir/pond detection from user‑supplied waterbody shapefile → `gis_water` + `RES` routing entries.
- [ ] Lakes/impoundments via `QSWATPlus` lake logic (pure‑Python port).
- [ ] `gis_routing` completeness: all hydrograph types for every subbasin.
- [ ] Elevation bands for snow (`gis_elevationbands`).
- [ ] Full `soils_sol` + `soils_sol_layer` population from gNATSGO component/chorizon joins.
- [ ] Point source (`ptsrc`) support.
- [ ] Calibration hook: `swatplus_builder.run.calibrate(project, observations, parameters, algo)` wrapping `pySWATPlus` + `SALib`/`pymoo`.
- [ ] **Benchmark vs QSWATPlus**: one fixture basin run through both pipelines; published divergence report in `docs/BENCHMARK.md`.

**Exit criteria:** NSE vs. observed within 0.05 of QSWATPlus on at least two basins; subbasin area diff < 3%; HRU count diff < 15%.

---

## Phase 3 — Agent‑native & production  (`v1.0.0`)

- [x] MCP server (`swat-mcp`) with all four tools + progress notifications.
- [ ] Content‑addressed project dirs (hash of inputs) → automatic caching / resumption.
- [ ] Deterministic, JSON‑structured logs for agent consumption.
- [ ] Optional gRPC/REST service wrapping the tool interface.
- [ ] Docker image: `ghcr.io/ai-hydro/swatplus_builder:<tag>` with reference DBs + SWAT+ binary baked in, < 500 MB.
- [ ] AI‑Hydro adapter (`ai_hydro/integrations/swatplus_builder/`): thin re‑export so the MCP server is discoverable from AI‑Hydro's tool registry.
- [ ] Documentation site (`mkdocs-material`) with tutorials.
- [ ] Example notebooks: single basin, CAMELS subset, calibration walkthrough.

**Exit criteria:** an external user (not us) can follow the README and get a working SWAT+ run in under 15 minutes with only `pip install` + one bootstrap script.

---

## Phase 4 — Hydrological Validation & Manuscript Suite (`v0.4.0`) [DONE]

**Goal:** Provide publication‑quality diagnostics and automated performance evaluation.

- [x] **USGS NWIS Integration**: Automated observed discharge fetching via Gauge ID.
- [x] **Performance Metrics**: NSE, KGE, and BFI (Baseflow Index) implemented without external dependencies.
- [x] **Standardized Plotting**: Centralized `style.py` with high‑DPI defaults (600 DPI).
- [x] **Hydrograph Suite**: Linear and Log‑scale time series with automatic metric annotation.
- [x] **Diagnostic Plots**: Flow Duration Curves (FDC), 1:1 Scatter, Residuals, and Seasonal bias charts.
- [x] **Platform Orchestrator**: One‑shot CLI/Example that handles delineation → engine run → manuscript generation.
- [x] **Python 3.9 Compatibility**: Verified stability on restrictive enterprise/academic environments.

---

## Out of scope (explicit non‑goals)

- Byte‑for‑byte parity with QSWATPlus output tables (we aim for numerical agreement, not MD5).
- Any GUI.
- Custom SWAT+ engine builds (we consume the upstream binary).
- Supporting SWAT2012 (legacy QSWAT) — the SWAT2012 `TxtInOut` currently under `_archive/` is reference only.
- Windows‑only workflows (Linux + macOS are first‑class; Windows is best‑effort).
