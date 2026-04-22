# References

Upstream sources, pinned versions, reverse‑engineering notes, and the reuse map from prior work.

---

## 1. Upstream projects

| Project | URL | Role here | Pin |
|---|---|---|---|
| QSWATPlus | https://github.com/swat-model/QSWATPlus | **Reference only** — we do not import it. Algorithms in `QSWATPlus/*.py` are the specification. | commit `dc15bddaf3ef` (in local mirror under `../QSWATPlus-dc15bddaf3ef7cd82cb6653eef5c5691530bb338/`) |
| swatplus‑editor | https://github.com/swat-model/swatplus-editor | **Vendored** under `src/swatplus_builder/editor/vendored/` at install time. Drives SQLite → TxtInOut. | TBD (record on first `vendor` run) |
| swatplus‑automatic‑workflow | https://github.com/celray/swatplus-automatic-workflow | **Reference only** — we mimic its call sequence to the editor API but not its QGIS calls. | TBD |
| pySWATPlus | https://github.com/swat-model/pySWATPlus | **Optional dep** for calibration / sensitivity / file edits. We do not depend on it for `build_project`. | track latest via PyPI |
| WhiteboxTools | https://github.com/jblindsay/whitebox-tools | **Runtime dep (gis extra)** — primary delineation backend. | pip `whitebox>=2.3` |
| pyflwdir | https://github.com/Deltares/pyflwdir | **Runtime dep (gis extra)** — secondary delineation backend. | pip `pyflwdir>=0.5` |
| rasterio, geopandas, shapely, pyproj | — | GIS I/O and geometry. | versions in `pyproject.toml` |
| SWAT+ engine | https://swatplus.gitbook.io/ / Bitbucket releases | External binary, downloaded by `scripts/bootstrap_swatplus_binary.sh`. | `rev60+` or newer |
| SWAT+ reference DBs | swatplus.gitbook.io → "Datasets" | `swatplus_datasets.sqlite`, `swatplus_soils.sqlite`, `swatplus_wgn.sqlite`. Fetched by `scripts/bootstrap_reference_dbs.sh`. | TBD |

---

## 2. Reverse‑engineering findings (carried over from prior investigation)

### 2.1 QSWATPlus entry points and their QGIS coupling

| File | What it does | QGIS coupling |
|---|---|---|
| `runHUC.py` | Headless driver for HUC‑scale runs | **Hard** — `QgsApplication.initQgis()` at module load; imports `qgis.core.*` widgets. |
| `test_qswatplus.py` | ~2500‑line end‑to‑end test that drives the plugin via dialog state; asserts MD5 of `gis_*` tables. | **Hard** — exercises UI widgets. |
| `QSWATPlus/delineation.py` | DEM → streams → subbasins, via TauDEM subprocess. | **Hard** — `QgsRasterLayer`/`QgsVectorLayer`, uses `processing` module. |
| `QSWATPlus/hrus.py` | LU×Soil×Slope overlay, HRU filtering, LSU split. | **Hard** — QGIS raster and vector APIs throughout. |
| `QSWATPlus/landscape.py` | Floodplain delineation. | **Hard** — QGIS. |
| `QSWATPlus/QSWATTopology.py` | Stream topology + slope network. | **Mild** — has QGIS helpers but algorithms are replicable. |
| `QSWATPlus/TauDEMUtils.py` | subprocess wrapper for TauDEM binaries. | **None** — pure Python subprocess. |
| `QSWATPlus/DBUtils.py` | SQLite abstraction; DDL + population of `gis_*`, `soils_sol*`, `plants_plt`. | **None** — pure Python sqlite3. |
| `QSWATPlus/parameters.py` | Constants. | **None**. |
| `QSWATPlus/polygonize.py`, `QSWATPlus/polygonizeInC*` | Cython raster→vector polygonize. | **None** (compiled). |

**Consequence.** The `QSWATPlus.DBUtils` and `QSWATPlus.parameters` modules are the specification we'll port. The QGIS‑dependent modules are replaced by WhiteboxTools + `rasterio`/`geopandas`.

### 2.2 SWAT+ Editor entry points (all QGIS‑free, pure Python)

| File | What it does |
|---|---|
| `src/api/swatplus_api.py` | argparse CLI. Dispatches to action classes. |
| `src/api/actions/setup_project.py` | Creates the project sqlite from the template; populates `project_config`. |
| `src/api/actions/import_gis.py` | Reads `gis_*` tables → populates `rout_unit_*`, `channel_cha`, `hru_data_hru`, `aquifer_aqu`, `hyd_con`, `lu_mgt`, `decision_table`, etc. |
| `src/api/actions/import_weather.py` | Ingests `.cli`/`.pcp`/`.tmp`/… files + WGN station mapping. |
| `src/api/actions/write_files.py` | Orchestrates ~25 file writers in `fileio/` — serializes model tables to `TxtInOut/`. |
| `src/api/actions/read_output.py` | Parses `output.*` text files back into SQLite. |
| `src/api/fileio/*.py` | One module per output file (`simulation.sim`, `climate.cli`, `channel.cha`, `hru-data.hru`, `soil.sol`, `file.cio`, …). |
| `src/api/database/project/*.py` | Peewee models for all model tables. |

**Consequence.** Exactly this layer — `swatplus-editor/src/api/` — is what we vendor. It's ~10k lines, Apache‑2.0, has been maintained for years, and does the DB→TxtInOut serialization correctly. Rewriting is waste.

### 2.3 The SWAT+ AW playbook (reference)

From `celray/swatplus-automatic-workflow/main_stages/run_editor.py`, the call sequence is:

```bash
python swatplus_api.py create_database --db_type=project --db_file=<proj>.sqlite --db_file2=<ref>.sqlite
python swatplus_api.py import_gis      --delete_existing=y --project_db_file=<proj>.sqlite
python swatplus_api.py import_weather  --import_type=wgn      --wgn_db=<wgn>.sqlite --wgn_table=wgn_cfsr_world --project_db_file=<proj>.sqlite
python swatplus_api.py import_weather  --import_type=observed --delete_existing=y   --source_dir=<weather_dir> --project_db_file=<proj>.sqlite
python swatplus_api.py write_files     --output_files_dir=<workdir>/Scenarios/Default/TxtInOut --project_db_file=<proj>.sqlite
```

`swatplus_builder.editor.api` replays this exact sequence.

---

## 3. Reuse Map — porting from existing workspace work

### `../pipeline/` (9 numbered scripts, 1,462 LoC total)

| Script | Reuse verdict | Target module | Notes |
|---|---|---|---|
| `config.py` | **Partial port.** | `swatplus_builder.config` | Keep NLCD/slope/soil class mappings; convert to pydantic `Settings`. |
| `01_delineate_watershed.py` | **Replace.** | `gis.delineation` | Uses `pynhd.NLDI.get_basins()` which gives one polygon — insufficient for SWAT+ which needs many subbasins + channels. We replace with WhiteboxTools pipeline; NLDI remains optional for bounding‑box snap. |
| `02_get_terrain.py` | **Port with extensions.** | `gis.terrain` | DEM retrieval (py3dep), slope/aspect computation, slope classification. Add per‑subbasin zonal reduction. |
| `03_get_landuse.py` | **Port.** | `gis.landuse` | NLCD via Planetary Computer. Add per‑subbasin clip + zonal mode. |
| `04_get_soil.py` | **Port + extend.** | `gis.soil` | gNATSGO retrieval + muaggatt/component/chorizon joins. Extend to emit SWAT+ `soils_sol` + `soils_sol_layer` rows. |
| `05_create_hru.py` | **Port + restructure.** | `gis.hru` | Current script is basin‑global; restructure to per‑subbasin/per‑LSU overlay, emit `gis_hrus` rows instead of NumPy arrays. |
| `06_get_forcing.py` | **Port.** | `weather.gridmet` | GridMET retrieval; extend output format from NetCDF to SWAT+ `.cli/.pcp/.tmp/.hmd/.wnd/.slr`. |
| `07_get_streamflow.py` | **Reuse as‑is (utility).** | `swatplus_builder.utils.usgs` (optional) | USGS NWIS streamflow for validation/calibration; keep interface. |
| `08_get_vegetation.py` | **Optional port.** | `gis.vegetation` (Phase 3) | MODIS NDVI/LAI. Not required for baseline SWAT+ run; useful for calibration targets. |
| `09_assemble_dataset.py` | **Do not port.** | — | Builds PyTorch dataset for a different (GNN) model; not in `swatplus_builder` scope. |

### `../SWAT_data_prep/` (7 notebooks)

| Notebook | Reuse verdict | Target |
|---|---|---|
| `0_Chosen_observed_data_analysis.ipynb` | Mining exercise — algorithms go into `weather.observed`. Keep notebook. |
| `1_SWAT_CAMELS_weather_data.ipynb` | Algorithms into `weather.camels` (Phase 2 utility). Keep. |
| `1_SWAT_data_camels.ipynb` | Same. |
| `1_SWAT_data_preprocessing_1.ipynb`, `1_Swat_data_preprocessing_2.ipynb` | Split into `gis.*` helpers; record format quirks (e.g. SWAT date‑format gotchas) in an appendix. |
| `2_Swat_observed_data_prep.ipynb` | Use to inform `weather.observed` schema. |
| `3_Swat_results_comparison.ipynb` | Useful post‑run validation notebook; keep as an example under `examples/`. |

Notebooks remain in place; they are active research tools. What moves into `swatplus_builder` are the **pure functions** extracted from them, typed and tested.

---

## 4. QSWATPlus reference DDL (for SCHEMA.md verification)

Full DDL is in the local mirror at
`../QSWATPlus-dc15bddaf3ef7cd82cb6653eef5c5691530bb338/QSWATPlus/DBUtils.py`. The exact schemas we target in `SCHEMA.md` are taken verbatim from the `_createGisTables` group there. When a column differs across QSWATPlus releases (rare), we track the latest.

---

## 5. SWAT+ Editor vendoring recipe

```bash
# From repo root
COMMIT=<SHA>
git clone --depth=1 https://github.com/swat-model/swatplus-editor.git /tmp/swatplus-editor
( cd /tmp/swatplus-editor && git fetch --depth=1 origin "$COMMIT" && git checkout "$COMMIT" )
rsync -a --delete /tmp/swatplus-editor/src/api/ src/swatplus_builder/editor/vendored/
echo "$COMMIT" > src/swatplus_builder/editor/vendored/.VENDORED_COMMIT
```

Commit SHA is written into `vendored/.VENDORED_COMMIT` and mirrored at the top of this document when bumped.

---

## 6. External reading

- SWAT+ I/O documentation: https://swatplus.gitbook.io/
- SWAT+ input file format: https://swatplus.gitbook.io/docs/user/editor/inputs
- WhiteboxTools manual: https://www.whiteboxgeo.com/manual/wbt_book/intro.html
- pyflwdir paper: Eilander et al., 2021 — fast flow direction on huge DEMs
- Chawanda et al. 2020 — SWAT+ AW (Hydrology & Earth System Sciences Discussions)
- Original SWAT+ description: Bieger et al. 2017 (JAWRA)
