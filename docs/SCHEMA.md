# SWAT+ `gis_*` Schema Contract

This document is the **stable contract** between the `swatplus_builder.gis` stage
and the SWAT+ Editor backend. If this schema is correct,
`swatplus_api.py import_gis` will accept our output and downstream `write_files`
will produce a valid `TxtInOut/`.

## Source of truth

Ground truth comes from the **QSWATPlus source code**, not from the shipped
template DBs. We extracted:

1. **DDL constants** in `QSWATPlus/DBUtils.py` (`_HRUSCREATESQL`,
   `_LSUSCREATESQL`, `_SUBBASINSCREATESQL`, `_CHANNELSCREATESQL`,
   `_WATERCREATESQL`, `_ROUTINGCREATESQL`, `_POINTSCREATESQL`,
   `_CREATEPROJECTCONFIG`, `_CREATEAQUIFERS`, `_CREATEADEEPQUIFERS`).
2. **INSERT call-sites** that show the exact value tuple written for each row:
   - `hrus.py:3434` — `_HRUSINSERTSQL`
   - `hrus.py:4016` — `_SUBBASINSINSERTSQL`
   - `hrus.py:4083` — `_LSUSINSERTSQL`
   - `hrus.py:4713` / `4760` — `_WATERINSERTSQL`
   - `QSWATTopology.py:3213` — inline channels INSERT
   - `DBUtils.py:431` (`addToRouting`) — `_ROUTINGINSERTSQL`
   - `QSWATTopology.py:2726+` — `writePointsTable` (via `_POINTSCREATESQL`)

> **Warning — template drift.** The `QSWATPlusProj.sqlite` shipped in the repo
> has **fewer columns** than the code-side DDL for `gis_lsus`, `gis_channels`,
> `gis_subbasins`, `gis_water`, and `gis_routing`. QSWATPlus at runtime executes
> `DROP TABLE IF EXISTS … ; CREATE TABLE …` using the code-side DDL. **We do
> the same.** See
> [`ADR-011`](DECISIONS.md#adr-011-code-side-ddl-is-the-contract-not-the-shipped-template).

---

## Required tables for a minimal run

| Table                   | Purpose                                                       | Populated by                 |
| ----------------------- | ------------------------------------------------------------- | ---------------------------- |
| `project_config`        | One row with project metadata, reference DB paths, flags      | `swatplus_builder.db.project`|
| `gis_points`            | Outlets, inlets, point sources, reservoir/pond points         | `gis.delineation`            |
| `gis_channels`          | One row per stream link (channel segment)                     | `gis.delineation`            |
| `gis_subbasins`         | One row per subbasin polygon                                  | `gis.delineation` + `gis.hru`|
| `gis_lsus`              | Landscape units (floodplain + upslope), 1–2 per channel       | `gis.hru`                    |
| `gis_hrus`              | HRUs, one per unique LU×Soil×Slope per LSU                    | `gis.hru`                    |
| `gis_water`             | Reservoirs / ponds / wetlands                                 | `gis.hru` (optional)         |
| `gis_routing`           | Directed graph of water routing between objects               | `gis.topology`               |
| `gis_elevationbands`    | Optional snow-band decomposition per subbasin                 | `gis.terrain` (Phase 2)      |
| `gis_aquifers`          | Shallow aquifer polygons                                      | `gis.topology` (Phase 2)     |
| `gis_deep_aquifers`     | Deep aquifer polygons                                         | `gis.topology` (Phase 2)     |

Internal scratch tables — `BASINSDATA`, `LSUSDATA`, `HRUSDATA`, `LAKESDATA`,
`LAKELINKS`, `LAKEBASINS` — are QSWATPlus caches and **are not required** by
the SWAT+ Editor when `project_config.imported_gis = 0` on first open.

---

## Column-level contracts

### `project_config` (one row, id = 1)

From `_CREATEPROJECTCONFIG` (DBUtils.py:3150) — **23 columns**.

| # | Column                      | Type      | Value we write                              |
|---|-----------------------------|-----------|---------------------------------------------|
| 1 | `id`                        | INT PK    | `1`                                         |
| 2 | `project_name`              | TEXT      | e.g. `"marsh_creek_v1"`                     |
| 3 | `project_directory`         | TEXT      | abs path to workdir                         |
| 4 | `editor_version`            | TEXT      | match vendored editor commit, e.g. `"2.3.3"`|
| 5 | `gis_type`                  | TEXT      | `"qgis"` (editor only checks format)        |
| 6 | `gis_version`               | TEXT      | e.g. `"3.28"`                               |
| 7 | `project_db`                | TEXT      | abs path to this sqlite                     |
| 8 | `reference_db`              | TEXT      | abs path to `swatplus_datasets.sqlite`      |
| 9 | `wgn_db`                    | TEXT      | abs path to `swatplus_wgn.sqlite`           |
|10 | `wgn_table_name`            | TEXT      | e.g. `"wgn_cfsr_world"`                     |
|11 | `weather_data_dir`          | TEXT      | `<workdir>/Scenarios/Default/TxtInOut`      |
|12 | `weather_data_format`       | TEXT      | `"plus"` / `"observed"` / `"netcdf"`        |
|13 | `input_files_dir`           | TEXT      | `<workdir>/Scenarios/Default/TxtInOut`      |
|14 | `input_files_last_written`  | DATETIME  | `NULL` initially                            |
|15 | `swat_last_run`             | DATETIME  | `NULL`                                      |
|16 | `delineation_done`          | BOOL NN   | `1` after we finish writing gis tables      |
|17 | `hrus_done`                 | BOOL NN   | `1` after we finish HRU tables              |
|18 | `soil_table`                | TEXT      | usually `"SSURGO"` or usersoil table name   |
|19 | `soil_layer_table`          | TEXT      | usually NULL (layers embedded)              |
|20 | `output_last_imported`      | DATETIME  | `NULL`                                      |
|21 | `imported_gis`              | BOOL NN   | `0` — editor flips to 1 after `import_gis`  |
|22 | `is_lte`                    | BOOL NN   | `0` (full SWAT+)                            |
|23 | `use_gwflow`                | BOOL NN   | `0`                                         |

### `gis_points` (8 columns)

From `_POINTSCREATESQL`. No PK constraint in the code-side DDL.

| Column    | Type | Notes                                                                 |
|-----------|------|-----------------------------------------------------------------------|
| `id`      | INT  | unique per-row; QSWATPlus assigns monotonically                        |
| `subbasin`| INT  | FK → `gis_subbasins.id` (0 if point is outside any subbasin)           |
| `ptype`   | TEXT | `'O'` outlet · `'I'` inlet · `'P'` point source · `'R'` reservoir pt · `'L'` lake outlet |
| `xpr`, `ypr` | REAL | projected CRS coordinates (metres)                                 |
| `lat`, `lon` | REAL | WGS84 degrees                                                      |
| `elev`    | REAL | m                                                                      |

### `gis_channels` (12 columns)

From `_CHANNELSCREATESQL`. INSERT order established at `QSWATTopology.py:3213`:

```
(SWATChannel, SWATBasin, drainAreaHa, strahlerOrder,
 lengthM, slopePercent, channelWidthM, channelDepthM,
 minElM, maxElM, midLatDeg, midLonDeg)
```

| Column     | Type | Notes                                                                 |
|------------|------|-----------------------------------------------------------------------|
| `id` PK    | INT  | SWAT channel id (1-based, dense)                                       |
| `subbasin` | INT  | FK → `gis_subbasins.id`; `0` if channel lives entirely inside a lake   |
| `areac`    | REAL | cumulative drainage area at channel **ha**                             |
| `strahler` | INT  | Strahler stream order (**not present in shipped template**)            |
| `len2`     | REAL | channel length **m** (× `mainLengthMultiplier`, default 1.0)           |
| `slo2`     | REAL | slope **%** (`raw_slope * 100 * reachSlopeMultiplier / mainLengthMultiplier`) |
| `wid2`     | REAL | width **m**: `channelWidthMultiplier * (drainAreaKm ** channelWidthExponent)` (QSWAT defaults `1.29 * A^0.6`) |
| `dep2`     | REAL | depth **m**: `channelDepthMultiplier * (drainAreaKm ** channelDepthExponent)` (defaults `0.13 * A^0.4`) |
| `elevmin`  | REAL | min elevation along channel **m**                                      |
| `elevmax`  | REAL | max elevation along channel **m**                                      |
| `midlat`   | REAL | midpoint latitude WGS84                                                |
| `midlon`   | REAL | midpoint longitude WGS84                                               |

### `gis_subbasins` (11 columns)

From `_SUBBASINSCREATESQL`. INSERT order from `hrus.py:4016`:

```
(SWATBasin, areaHa, meanSlopePercent, farDistance, slsubbsn,
 lat, lon, meanElevation, elevMin, elevMax, waterId)
```

| Column    | Type | Notes                                                                 |
|-----------|------|-----------------------------------------------------------------------|
| `id` PK   | INT  | SWAT basin id, 1-based                                                 |
| `area`    | REAL | **ha**                                                                 |
| `slo1`    | REAL | mean slope **%** (% — *not* m/m; units are consistent with `slo2`)     |
| `len1`    | REAL | longest flow path length **m** (`farDistance` in QSWAT)                |
| `sll`     | REAL | "slsubbsn" — slope of longest path **m/m**                             |
| `lat`, `lon` | REAL | centroid WGS84                                                      |
| `elev`    | REAL | mean elevation **m**                                                   |
| `elevmin` | REAL | subbasin min elevation **m**                                           |
| `elevmax` | REAL | subbasin max elevation **m**                                           |
| `waterid` | INT  | **new** — id of lake/reservoir fully inside this subbasin (0 = none)   |

### `gis_lsus` (13 columns)

From `_LSUSCREATESQL`. INSERT order from `hrus.py:4083`:

```
(lsuId, landscape, SWATChannel, SWATBasin, areaHa, meanSlopePercent,
 tribDistance, tribSlopePercent, tribWidth, tribDepth, lat, lon, meanElev)
```

| Column     | Type | Notes                                                                 |
|------------|------|-----------------------------------------------------------------------|
| `id` PK    | INT  | LSU id = `SWATChannel * 10 + landscape_code` (QSWATUtils convention)   |
| `category` | INT  | landscape code: `0` no-landscape · `1` floodplain · `2` upslope        |
| `channel`  | INT  | FK → `gis_channels.id`                                                 |
| `subbasin` | INT  | FK → `gis_subbasins.id` (**new vs template**)                          |
| `area`     | REAL | **ha**                                                                 |
| `slope`    | REAL | mean slope **%** (× `meanSlopeMultiplier`, default 1.0)                |
| `len1`     | REAL | tributary length **m** (**new vs template**)                           |
| `csl`      | REAL | tributary channel slope **%**                                          |
| `wid1`     | REAL | tributary width **m** (same regression as `wid2`)                      |
| `dep1`     | REAL | tributary depth **m** (same regression as `dep2`)                      |
| `lat`, `lon` | REAL | centroid WGS84                                                      |
| `elev`     | REAL | mean elevation **m**                                                   |

### `gis_hrus` (14 columns)

From `_HRUSCREATESQL`. INSERT order from `hrus.py:3434`:

```
(HRUNum, lsuId, subHa, arlsuHa, luse, arluse, snam, arso,
 slp, arslp, meanSlopePercent, lat, lon, meanElevation)
```

| Column    | Type | Notes                                                                 |
|-----------|------|-----------------------------------------------------------------------|
| `id` PK   | INT  | HRU number, 1-based dense                                              |
| `lsu`     | INT  | FK → `gis_lsus.id`                                                     |
| `arsub`   | REAL | HRU area as fraction of parent subbasin (**ha absolute**, not a ratio — QSWATPlus writes `subHa`) |
| `arlsu`   | REAL | HRU area within the LSU (**ha**)                                       |
| `landuse` | TEXT | SWAT+ plant/urban code, e.g. `"frst"`, `"agrl"`, `"urml"` (4-char lowercase match against `landuse_lum.name`) |
| `arland`  | REAL | area of this landuse within the LSU (**ha**)                           |
| `soil`    | TEXT | soil name matching `soils_sol.name` (or reference `statsgo_ssurgo_lkey` key) |
| `arso`    | REAL | area of this soil within the LSU (**ha**)                              |
| `slp`     | TEXT | slope band label, e.g. `"0-5"` / `"5-12"` / `"12-9999"`                |
| `arslp`   | REAL | area within this slope band (**ha**)                                   |
| `slope`   | REAL | mean slope **%**                                                       |
| `lat`, `lon` | REAL | centroid WGS84                                                      |
| `elev`    | REAL | mean elevation **m**                                                   |

> **Unit caveat.** Despite the column names suggesting "fractions",
> QSWATPlus writes **absolute hectare areas** for `arsub`, `arlsu`, `arland`,
> `arso`, `arslp`. The editor computes fractions downstream.

### `gis_water` (10 columns)

From `_WATERCREATESQL`. INSERT order from `hrus.py:4713`:

```
(lakeId, wCat, lsuId, SWATBasin, areaHa, centroidX, centroidY, lat, lon, elev)
```

| Column    | Type | Notes                                                                 |
|-----------|------|-----------------------------------------------------------------------|
| `id`      | INT  | water body id (no PK/unique in code-side DDL)                          |
| `wtype`   | TEXT | `'RES'` reservoir · `'PND'` pond · `'WETL'` wetland · `'PLAYA'`        |
| `lsu`     | INT  | FK                                                                     |
| `subbasin`| INT  | FK (**new vs template**)                                               |
| `area`    | REAL | **ha**                                                                 |
| `xpr`, `ypr` | REAL | projected CRS (**new vs template**)                                 |
| `lat`, `lon` | REAL | WGS84                                                               |
| `elev`    | REAL | **m**                                                                  |

### `gis_routing` (6 columns, the topology graph)

From `_ROUTINGCREATESQL`. INSERT order from `DBUtils.py:431`:

```
(sourceId, sourceCategory, hydTyp, sinkId, sinkCategory, percent)
```

| Column      | Type | Allowed values                                                            |
|-------------|------|---------------------------------------------------------------------------|
| `sourceid`  | INT  | id of source object                                                        |
| `sourcecat` | TEXT | `HRU` · `LSU` · `CH` · `SUB` · `SBR` · `AQU` · `DAQ` · `PT` · `RES` · `PND` · `WETL` · `PLAYA` |
| `hyd_typ`   | TEXT | `tot` total · `sur` surface · `lat` lateral · `rhg` recharge · `til` tile · `nil` (**new vs template**) |
| `sinkid`    | INT  | id of sink object, or `0` for the final outlet                             |
| `sinkcat`   | TEXT | same categories as `sourcecat`, plus `X` = "external/world outlet"         |
| `percent`   | REAL | **0–100** (percent, *not* fraction)                                        |

> **Unit caveat #2.** `gis_routing.percent` is stored as 0–100, not 0–1.
> Validation rule: for each `(sourceid, sourcecat, hyd_typ)` group, percents
> must sum to 100 ± 0.5.

**Non-unique** index on `(sourceid, sourcecat)` per `_ROUTINGINDEXSQL`. A
single source can appear multiple times because QSWATPlus splits flows
(e.g. an LSU writes `surface → 80% channel` + `surface → 20% downslope LSU`
as two rows). The shipped template DBs use `CREATE UNIQUE INDEX` — that's
template drift per ADR-011.

Validation constraints (enforced by `db.writer`, not SQL):

- For each `(sourceid, sourcecat)` there is at most **one row per
  `(sinkid, sinkcat, hyd_typ)`** triple.
- For each `(sourceid, sourcecat, hyd_typ)` group, `SUM(percent)` ∈ [100-0.5, 100+0.5].

### `gis_splithrus` and `gis_landexempt`

Optional user overrides. Empty for MVP.

### `gis_aquifers` / `gis_deep_aquifers`

**Optional for MVP but required by the editor if `use_gwflow = 0` with
default aquifer routing.** Note: the code-side DDL has a typo `REAK` instead
of `REAL` for the `area` column. SQLite stores the value correctly (dynamic
typing) — **we reproduce the typo verbatim** to match the hash the editor
expects if it checks. See `ADR-012`.

| Table              | Columns                                                               |
|--------------------|-----------------------------------------------------------------------|
| `gis_aquifers`     | `id`, `category`, `subbasin`, `deep_aquifer`, `area`, `lat`, `lon`, `elev` |
| `gis_deep_aquifers`| `id`, `subbasin`, `area`, `lat`, `lon`, `elev`                        |

---

## Population order (strict)

1. Create the project sqlite file, attach `_CREATEPROJECTCONFIG`, insert the
   single `project_config` row with `delineation_done = hrus_done = imported_gis = 0`.
2. `gis_points` — at minimum the main outlet (`ptype='O'`).
3. `gis_subbasins` — one row per basin.
4. `gis_channels` — one row per channel link.
5. `gis_lsus` — requires channels + subbasins.
6. `gis_hrus` — requires LSUs.
7. `gis_water` — optional; requires LSUs + subbasins.
8. `gis_aquifers` / `gis_deep_aquifers` — optional for MVP.
9. `gis_routing` — **last**; references every other id table.
10. `UPDATE project_config SET delineation_done=1, hrus_done=1`.
11. Hand off to the SWAT+ Editor: `python swatplus_api.py import_gis
    --project_db_file=<path> --delete_existing=y`.

After step 11 the editor populates all model tables (`rout_unit_*`,
`channel_cha`, `chandeg_cha`, `hru_data_hru`, `aquifer_aqu`, `hyd_con`,
`lu_mgt`, …) and flips `project_config.imported_gis` to 1.

---

## Validation rules enforced by `swatplus_builder.db.writer`

Before committing, the writer runs these pre-insert checks:

1. Every `gis_channels.subbasin` exists in `gis_subbasins.id` (or is `0`).
2. Every `gis_lsus.channel` exists in `gis_channels.id`.
3. Every `gis_lsus.subbasin` exists in `gis_subbasins.id`.
4. Every `gis_hrus.lsu` exists in `gis_lsus.id`.
5. Every `gis_water.lsu` and `gis_water.subbasin` exist.
6. For every subbasin there is at least one LSU and at least one HRU.
7. Sum of `gis_hrus.arlsu` (in ha) within each LSU equals that LSU's area ± 1e-3 ha.
8. Sum of `gis_hrus.arsub` (in ha) within each subbasin equals that subbasin's area ± 1e-3 ha.
9. `gis_routing` forms a **DAG with exactly one final sink** (`sinkcat='X'`).
   Enforced via `networkx.is_directed_acyclic_graph`.
10. Every non-outlet object id referenced in `gis_routing` exists in its
    corresponding `gis_*` table.
11. For each `(sourceid, sourcecat, hyd_typ)` group, `SUM(percent)` equals
    100 ± 0.5.
12. `project_config.reference_db` and `wgn_db` exist on disk.

Failed validation raises `SwatBuilderPipelineError` with the offending rows
attached to `.context`.
