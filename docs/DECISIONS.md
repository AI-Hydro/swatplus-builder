# Architecture Decision Records

Short records of "why we chose X over Y" so future contributors (and future you) don't redo the debate.

Format: one ADR per heading. Status is `Proposed` / `Accepted` / `Superseded by ADR‑NNN`.

---

## ADR‑001 — Path C (Hybrid): no QGIS at runtime

**Status:** Accepted — 2026‑04‑20.

**Context.** QSWATPlus is a QGIS plugin. Its "headless" drivers (`runHUC.py`, `test_qswatplus.py`, `swatplus-automatic-workflow/main_stages/run_qswat.py`) all require a full QGIS runtime plus Qt widgets, configured via dialog‑widget state. SWAT+ Editor, in contrast, is a pure‑Python + SQLite + Peewee backend exposed through `src/api/swatplus_api.py`. The two tools cooperate through a shared project SQLite file whose `gis_*` tables are the stable contract between them.

**Considered options.**

- **Path A — Pure Python rebuild.** Reimplement both GIS and DB→TxtInOut layers from scratch. Rejected: the DB→TxtInOut layer in `swatplus-editor/src/api/fileio/*.py` is ~6000 lines of carefully aligned column writers. Zero algorithmic benefit to rewriting, high risk of subtle format bugs that SWAT+ would silently accept but mis‑parse.
- **Path B — Dockerized QGIS + QSWATPlus.** Requires QGIS‑LTR, Xvfb, TauDEM, MPICH, the QSWATPlus plugin, plus careful version pinning. Image size 2–3 GB. Fragile across QGIS point releases (QSWATPlus dialog widget names change). Bad fit for server/agent runtime.
- **Path C — Hybrid.** Replace only QSWATPlus's GIS stage with pure Python (WhiteboxTools / pyflwdir / rasterio). Vendor the SWAT+ Editor Python backend verbatim. Contract between them is the `gis_*` schema.

**Decision.** Path C. Rationale:

1. The `gis_*` schema is stable, documented (`QSWATPlus/DBUtils.py`), and can be populated from any geoprocessing toolkit.
2. The SWAT+ Editor backend is open source, pure Python, MIT/Apache‑licensed, and already has a CLI (`swatplus_api.py`). Vendoring at a pinned commit gives reproducibility without a heavy runtime dep.
3. Python‑native delineation (WhiteboxTools, pyflwdir) is mature enough for SWAT‑scale basins. Subbasin area typically within 1–3% of TauDEM.
4. No QGIS ⇒ small image, trivial CI, trivial concurrency, trivial agent embedding.

**Consequences.**

- We commit to maintaining a small `gis_*` writer layer and to tracking SWAT+ Editor upstream.
- We lose byte‑for‑byte parity with QSWATPlus output and must justify numerical divergence per basin (see `BENCHMARK.md` in Phase 2).
- We gain the ability to run entirely inside a 500 MB container or a regular Python environment.

---

## ADR‑002 — Primary delineation backend is WhiteboxTools

**Status:** Accepted — 2026‑04‑20.

**Context.** We need a Python‑callable, headless, maintained, license‑friendly DEM hydro‑conditioning stack that covers: breach/fill, D8 flow direction, flow accumulation, stream extraction, watershed + subbasin delineation, and stream ordering.

**Considered options.** `whitebox-tools` (whitebox‑python), `pyflwdir` (Deltares), `pysheds`, TauDEM (subprocess).

**Decision.** WhiteboxTools primary; pyflwdir as a secondary backend for very large DEMs; TauDEM optional via subprocess for users who need parity with QSWATPlus numerics.

**Rationale.** WhiteboxTools is: single static Rust binary, MIT, actively maintained by John Lindsay, >500 tools including everything listed above, no runtime GIS dep. pyflwdir is excellent but not a complete replacement (no polygonize‑watershed step out of the box, no stream link IDs). pysheds is pure Python but slower and has been less actively maintained.

**Consequences.** Users need the WhiteboxTools binary available (`whitebox` pip package downloads it automatically on first use). We commit to testing both backends in CI once available.

---

## ADR‑003 — Vendor SWAT+ Editor backend at a pinned commit

**Status:** Accepted — 2026‑04‑20.

**Context.** We depend on `swat-model/swatplus-editor`'s `src/api/` for SQLite → TxtInOut. Two options: pip dependency, or vendored copy.

**Decision.** Vendored copy at a pinned commit SHA recorded in `REFERENCES.md`.

**Rationale.** The backend is not published to PyPI. It's installed via `pipenv` from source. Vendoring:

1. Locks the exact code path for `write_files` — critical for reproducibility.
2. Removes a Pipfile/PyInstaller dependency.
3. Lets us backport patches while upstream is slow.

Downside: we have to bump the vendored copy periodically. Mitigation: a `scripts/update_vendored_editor.sh` that re‑vendors and prints the diff.

---

## ADR‑004 — Package name `swatplus-builder`

**Status:** Accepted — 2026‑04‑20 (user confirmed).

**Context.** Need a distinctive, searchable, short name that doesn't collide with `QSWATPlus`, `pySWATPlus`, or `swatplus-automatic-workflow`.

**Alternatives considered.** `swatgenesis`, `pyswatplus-headless`, `swatgen`, `aihydro-swatplus`.

**Decision.** `swatplus-builder`. Reasons: descriptive ("builds SWAT+ inputs"), searchable, memorable, no PyPI collision. Importable Python name: `swatplus_builder`. PyPI: `swatplus-builder`.

---

## ADR‑005 — CLI command is `swat`, not `swatplus-builder` or `swatgen`

**Status:** Accepted — 2026‑04‑20 (user confirmed).

**Context.** A CLI entry point is only valuable if users remember it. The package name (`swatplus-builder`) is too long; an abbreviation is needed.

**Alternatives considered.** `swatgen`, `autoswat`, `swatplus-builder`, `spb`.

**Decision.** `swat` with subcommands: `swat build` (full pipeline), `swat run`, `swat watershed`, `swat hrus`, `swat project`, `swat mcp`. The MCP server has a separate entry point `swat-mcp` (matches MCP convention of hyphenated binary names).

**Rationale.** `swat build` / `swat run` are what users remember — the noun is the model name, the verb describes the action. One-word commands beat compound ones for daily use. `swat` has no known conflict on pypi as an entry-point name.

**Consequences.** If a user has another tool also registering `swat` on their PATH, there's a conflict. Mitigate: detect at install time (Phase 1 TODO in bootstrap script).

---

## ADR‑006 — Typer + pydantic, not click + dataclasses

**Status:** Accepted — 2026‑04‑20.

**Context.** Need a CLI and a config object that share types with the agent API.

**Decision.** Typer (CLI) + pydantic v2 (config, input validation). Both share Python type hints, so the CLI help, JSON schemas for MCP tools, and runtime validation all derive from the same source.

**Consequences.** pydantic is a non‑trivial dep but it's already part of the MCP SDK and AI‑Hydro's stack; amortised cost.

---

## ADR‑007 — Repo is a sibling of AI‑Hydro, published to GitHub as `ai-hydro/swatplus-builder`

**Status:** Accepted — 2026‑04‑20 (user confirmed).

**Context.** The package could live inside the AI‑Hydro monorepo or as a standalone sibling.

**Decision.** Sibling: `github.com/ai-hydro/swatplus-builder`. Reasons: independent versioning, independent PyPI publication, usable without cloning AI‑Hydro, cleaner CI.

**Consequences.** AI‑Hydro depends on `swatplus-builder` via `pyproject.toml` optional dep and/or MCP registry — not by path import.

---

## ADR‑008 — Reference databases mirrored to `ai-hydro/swatplus-reference-data` on GitHub

**Status:** Accepted — 2026‑04‑20 (user confirmed).

**Context.** SWAT+ reference SQLite files are hosted on Bitbucket by the SWAT+ team, without a stable versioned URL. Builds that depend on Bitbucket availability are fragile.

**Decision.** Mirror the reference DBs to a GitHub release at `ai-hydro/swatplus-reference-data`, tagged by SWAT+ version (e.g. `v60.5.7`). Bootstrap script downloads from the mirror URL and verifies a SHA-256 checksum.

**Consequences.** We own the mirror and are responsible for keeping it current with upstream releases. The alternative (pinning Bitbucket URLs) is simpler but collapses if upstream moves files.

---

## ADR‑009 — Windows support is best‑effort

**Status:** Accepted — 2026‑04‑20 (user confirmed).

**Decision.** Linux + macOS are first‑class (tested in CI). Windows has a dedicated CI job (`windows-latest`) in `ci.yml` but only runs the smoke tests, not the full integration suite. WhiteboxTools is cross‑platform so the path binary exists on Windows; filesystem path separators are handled by `pathlib.Path` throughout. Reports of Windows failures are triaged but not blocking for a release.

---

## ADR‑010 — Vendored pipeline and SWAT_data_prep stay read‑only references

**Status:** Accepted — 2026‑04‑20.

**Context.** The workspace already has `pipeline/` (9 numbered GIS scripts) and `SWAT_data_prep/` (7 notebooks) from prior work. These are useful but not the package's runtime.

**Decision.** Do not move or modify these. Port the algorithms into `swatplus_builder.gis.*` with typed signatures. Keep the originals as an evolving exploration area. Record the port map in `REFERENCES.md §Reuse Map`.

---

## ADR‑011 — Code-side DDL is the contract, not the shipped template

**Status:** Accepted — 2026‑04‑20.

**Context.** The QSWATPlus repository ships three "project template" SQLite
files (`QSWATPlusProj.sqlite`, `QSWATPlusProjHAWQS.sqlite`, `test.sqlite`).
Step 0 inspection confirmed:

- All shipped templates have **empty** `gis_*` tables (row count = 0).
- The shipped `gis_*` schemas have **fewer columns** than the live Python
  code in `QSWATPlus/DBUtils.py` (e.g. template `gis_lsus` has 11 cols vs.
  code's 13; template `gis_channels` has 9 cols vs. code's 12; template
  `gis_routing` has 5 cols vs. code's 6 — missing `hyd_typ`).
- At runtime, QSWATPlus executes `DROP TABLE IF EXISTS <t>; CREATE TABLE <t>
  …` using the code-side DDL strings. So the template is vestigial.

**Considered options.**

1. Treat the shipped template as ground truth → would write broken schemas
   that no modern QSWATPlus consumer (including the SWAT+ Editor) expects.
2. Treat the DDL constants in `DBUtils.py` as ground truth, and copy them
   verbatim into `swatplus_builder.db.schema`.
3. Dynamically introspect `DBUtils.py` at runtime.

**Decision.** Option 2. We copy the exact DDL strings into
`src/swatplus_builder/db/schema.py`, with inline comments citing the source
line numbers. The schema module becomes the single source of truth for the
rest of the package.

**Rationale.** (a) Matches what the editor actually reads. (b) Keeps us
independent of the QSWATPlus Python tree at runtime. (c) Survives edits to
QSWATPlus we didn't review.

**Consequences.** When we upgrade vendored QSWATPlus reference data, we also
diff `DBUtils.py` DDL changes and propagate them here as a focused PR.

---

## ADR‑012 — Reproduce the `REAK` typo in aquifer tables verbatim

**Status:** Accepted — 2026‑04‑20.

**Context.** QSWATPlus's DDL for `gis_aquifers` and `gis_deep_aquifers`
declares the `area` column with type `REAK` (a typo for `REAL`).
SQLite's dynamic typing means values round-trip correctly regardless; but
any downstream tool that checksums the schema or runs `PRAGMA
table_info()` will see `REAK`.

**Decision.** Reproduce the typo verbatim in `db.schema.GIS_AQUIFERS_DDL`
and `GIS_DEEP_AQUIFERS_DDL`. Add a unit test that asserts the DDL string
contains `REAK` so nobody "fixes" it absent-mindedly.

**Rationale.** We want byte-identical schemas so the SWAT+ Editor and any
QA tooling (e.g. hashing the `sqlite_schema` blob for cache keys) treat
our output as indistinguishable from QSWATPlus's.

**Consequences.** Linters will flag this as a typo. Silenced via a
focused `# noqa`/comment.

---

## ADR‑013 — `gis_routing` index is NOT unique

**Status:** Accepted — 2026‑04‑20.

**Context.** The QSWATPlus template SQLite ships
`CREATE UNIQUE INDEX source ON gis_routing (sourceid, sourcecat)`.
However, QSWATPlus's runtime DDL in `DBUtils.py:3120` is
`CREATE INDEX source ON gis_routing(sourceid, sourcecat)` — **not unique**.

The non-unique form is required. A single source routinely appears with the
same `sourcecat` multiple times because QSWATPlus splits flows: e.g.
`addToRouting(lsu, 'LSU', channel, 'CH', 'sur', 80)` followed by
`addToRouting(lsu, 'LSU', down_lsu, 'LSU', 'sur', 20)` writes two rows with
identical `(sourceid='lsu', sourcecat='LSU')` differing only by sink.
A UNIQUE constraint would reject the second insert.

**Decision.** `db.schema.GIS_ROUTING_INDEX_DDL` uses plain `CREATE INDEX`.
Add a test that asserts this + proves duplicate inserts succeed.

**Consequences.** Validation of routing rules (sum-of-percents, at-most-one
row per `(source, sink, hyd_typ)` triple) is enforced in `db.writer`, not
in SQL. See `SCHEMA.md` §gis_routing.

---

## ADR‑014 — The vendored SWAT+ Editor ORM is the consumer contract

**Status:** Accepted — 2026‑04‑20.

**Context.** Step 1 vendored swatplus-editor @
`ed60db068e83602727267e2bffb1b7b6e346726a` and inspected
`src/api/database/project/gis.py`. The peewee models there declare
**every column the editor reads** from our `gis_*` tables.

Comparison (editor fields vs. our DDL, ignoring implicit `id`):

| Table             | Editor fields | Our cols | Diff                             |
| ----------------- | ------------- | -------- | -------------------------------- |
| Gis_subbasins     | 9             | 11       | we add `waterid`, `waterrole`    |
| Gis_channels      | 11            | 12       | exact (editor has implicit id)   |
| Gis_lsus          | 11            | 13       | we add `subbasin`, one extra col |
| Gis_hrus          | 13            | 14       | exact                            |
| Gis_water         | 9             | 10       | exact                            |
| Gis_points        | 7             | 8        | exact                            |
| Gis_routing       | 6             | 6        | exact                            |
| Gis_aquifers      | 7             | 8        | exact                            |
| Gis_deep_aquifers | 5             | 6        | exact                            |

The editor is a **proper subset** of our producer — every editor field
exists in our DDL. Extra columns (e.g. `waterid` on subbasins) are ignored
by peewee `.select()` which only hydrates declared fields.

`database/project/setup.py:101` does call
`create_tables([Gis_channels, Gis_subbasins, …])`. Peewee's default is
`safe=True` ⇒ `CREATE TABLE IF NOT EXISTS`, which is a no-op when our
`db.schema.ensure_schema` has already run. No schema conflict.

**Decision.** Keep our DDL as the superset (QSWATPlus parity). Add a test
(`test_editor_gis_orm_columns_are_producer_subset`) that parses the
vendored `gis.py` and asserts every peewee field name appears in our DDL,
so any upstream editor change that adds a required column breaks our CI
instead of breaking runtime.

**Consequences.** Editor upgrades are gated on the test. Schema drift is
impossible without a code change.

---

## ADR-015 — `project_config` superset is the editor's schema; INSERT by name

**Status:** Accepted — 2026-04-20.

**Context.** Step 4 hit two latent schema bugs on the very first end-to-end
invocation:

1. **Missing column.** The editor's Peewee `Project_config` model
   declares `netcdf_data_file` and `swat_exe_filename`. QSWATPlus's DDL
   (our previous source of truth) does not. Peewee's auto-generated
   `SELECT * FROM project_config` on a DB we produced failed with
   `no such column: t1.netcdf_data_file`.
2. **Missing `--project_name`.** The editor's `setup_project` script
   skips the code path that reads `project_name` from `project_config`
   when the caller supplies `--datasets_db_file`. That led to
   `Object_cnt.create(name=None)` → `NOT NULL constraint failed:
   object_cnt.name`. Root cause is upstream, but we work around it at
   our wrapper boundary.

**Decision.**

- Our `project_config` DDL is the **union** of the editor's Peewee
  model (24 non-id cols, new columns included) and the QSWATPlus-only
  workflow flags (`delineation_done`, `hrus_done`, `soil_table`,
  `soil_layer_table`, `use_gwflow`).
- `PROJECT_CONFIG_INSERT_SQL` is assembled from
  `PROJECT_CONFIG_COLUMNS` as a **named-column INSERT**, so adding a
  column doesn't require re-numbering positional placeholders across
  the stack. `db/project.py` constructs the row as a dict keyed by
  column name and tuples it via the constant — adding a column is a
  one-line edit.
- `editor.api.setup_project` always passes `--project_name`, reading
  from `project_config.project_name` when the caller didn't supply
  one. This papers over the upstream bug without modifying the
  vendored editor.

**Consequences.** Forward-compatible. Additive schema changes in
upstream do not force a cascading positional renumbering in our writer.

---

## ADR-016 — Bootstrap reference datasets from pinned GitHub raw URL

**Status:** Accepted — 2026-04-20.

**Context.** `swatplus_datasets.sqlite` is not distributed as a release
asset on GitHub and the install-doc Bitbucket URL returns 404. The
Windows installer bundles it; Linux/macOS installations are on their
own. For CI, agents, and pip installs we need a reproducible,
authentication-free fetch.

**Decision.** Pin each dataset version to the tagged blob in
`swat-model/swatplus-editor@<tag>:release/build/swatplus_datasets.sqlite`
(served by `raw.githubusercontent.com`) with a SHA-256 and size in
`ref/catalog.py`. v3.2.2 pins to datasets v3.2.0
(`91843c2c…` — 1 080 KiB). `ensure_datasets_db()` is cache-first,
content-addressed; `fetch_datasets_db()` is always network, fails
closed on size or digest mismatch and deletes the partial file.
`swat init` is the CLI driver.

**Why not the AI-Hydro mirror (ADR-008)?** We will still mirror there
for long-term air-gapped access. The mirror is a disaster-recovery
option; the primary source is the upstream tag because it's the one
with known provenance. If upstream disappears we flip one URL in the
catalog.

**Consequences.**

- Zero-auth, fully reproducible bootstraps.
- Any dataset DB update requires a catalog entry + SHA-256 refresh —
  we can't silently drift.
- Large future datasets (SSURGO, WGN) will need the same treatment; we
  can reuse the `fetch_datasets_db` plumbing by adding more
  `DatasetsRelease` entries.

---

## ADR-017 — `db.seed.seed_minimal_soils` is a test-only stand-in for SSURGO

**Status:** Accepted — 2026-04-20. Expected to be superseded when the
soils adapter lands (Phase 2).

**Context.** The editor's `import_gis` cross-checks every
`gis_hrus.soil` against `soils_sol`. Production pipelines populate
`soils_sol` from SSURGO/gNATSGO via QSWATPlus; our synthetic
`tiny_watershed` fixture can't.

**Decision.** Ship `db.seed.seed_minimal_soils(project_db, names)`
that pre-creates `soils_sol` + `soils_sol_layer` and upserts one
placeholder row per distinct soil name, with conservative defaults
(1000 mm single loam layer, hyd_grp=B). This runs before
`setup_project`; the editor's `create_tables(safe=True)` leaves the
pre-existing tables alone.

**Consequences.** The end-to-end test has no external soils
dependency. Production callers must not use `seed_minimal_soils` —
the docstring and ADR say so. A follow-up `gis.soils.from_ssurgo` or
similar adapter will replace it for real work.

---

## ADR-018 — SWAT+ engine runner: BYO binary, shim-tested wrapper

**Status:** Accepted — 2026-04-20.

**Context.** The SWAT+ engine (`swatplus_exe`) is a multi-MB native
Fortran binary with per-platform releases on
[`swat-model/swatplus`](https://github.com/swat-model/swatplus/releases)
and bundled copies inside the SWAT+ Editor installer. The executable:

* takes **no CLI arguments** (reads `file.cio` from CWD),
* writes all outputs **into CWD** alongside its inputs,
* respects `OMP_NUM_THREADS` for light parallelism,
* emits `diagnostics.out` for human/agent triage.

The editor's `actions/run_all.py` just `os.chdir(txtinout); os.system(swat_exe)`.
We need to match that contract while giving agents a structured result and
never blocking the build on a binary download that users typically
install once per host.

**Considered options.**

1. **Vendor the binary**, as we do the reference DB (ADR-016).
   Rejected: too large, per-platform, changes with every engine
   release. Users who want a specific revision would have to work
   around our pinning.
2. **Hard-depend on the editor's `run_all`**. Rejected: that action
   also imports WGN + weather, which we don't have yet. We'd be
   coupling the runner to Phase 2 work.
3. **BYO binary + subprocess wrapper with a Python shim test.**
   Chosen.

**Decision.**

* `swatplus_builder.run.swatplus.locate_binary()` resolves the engine
  in this order: `settings.swatplus_exe` > `$SWATPLUS_EXE` env >
  `shutil.which()` over `("swatplus_exe", "swatplus", "swatplus_exe.exe",
  "swatplus.exe")`. Missing binary → `SwatBuilderExternalError` with
  an actionable message.
* `run(txtinout_dir, *, threads, timeout_s, project, binary, settings)`
  invokes the engine with `cwd=txtinout_dir` and `OMP_NUM_THREADS=threads`.
  Non-zero exit raises `SwatBuilderExternalError` whose `.context`
  includes the tail of stdout, stderr, **and** `diagnostics.out`
  (that last one is the killer feature — it's where SWAT+ prints
  missing-file / invalid-input messages). Success returns a populated
  `SwatPlusRun` with `output_files` enumeration and a `paths` map
  keyed by well-known output filenames.
* `SwatPlusRun.project` is `Optional` — the primitive accepts a bare
  `TxtInOut/` so notebooks and ad-hoc debugging don't need a full
  `SwatPlusProject`. `run_project(project)` is the convenience wrapper
  for agent use.
* `swat run` CLI accepts either `--txtinout <dir>` or `--workdir <dir>`
  (latter resolves `<workdir>/Scenarios/Default/TxtInOut`) and prints
  a compact one-line summary plus the diagnostics tail on failure.

**Rationale.** BYO binary is the only honest answer until the SWAT+
project publishes per-platform wheels or an OCI image. The subprocess
wrapper is ~200 lines and maps cleanly to what the editor does.
Raising on non-zero (with rich `.context`) keeps the failure mode
aligned with `editor/api.py` so agent error-handling is uniform
across stages.

**Test strategy.** The real engine is replaced in CI by a Python
shim that pretends to be `swatplus_exe`: it validates `file.cio` is
in CWD, echoes `OMP_NUM_THREADS`, writes a `diagnostics.out` + a
couple of `*.txt` outputs, and exits 0 (or a configured non-zero).
That covers 100% of the wrapper's logic — cwd, env, timeout, tail
capture, output enumeration, error translation — without requiring
a 10-MB binary on CI. A separate opt-in test activates when a user
sets `$SWATPLUS_EXE=<path>` and asserts the wrapper's exception
contract against the real binary.

**Consequences.**

* First-run friction is a pip install **plus** pointing `$SWATPLUS_EXE`
  at an engine. Documented in `README.md` and `swat run --help`.
* If the SWAT+ team ships a standardized release artifact
  (e.g. a GitHub release asset with platform tags), we can add a
  `swat install-engine` command analogous to `swat init`. Deferred
  pending upstream stability.
* We do **not** parse output files yet — `SwatPlusRun.summary`
  returns `{}`. Phase 2 adds a reader that extracts outlet flow and
  a couple of QA metrics from `channel_sd_aa.txt` / `basin_wb_aa.txt`.

---

## ADR-019 — Weather writer targets the editor's observed-file format verbatim

**Status:** Accepted — 2026-04-20.

**Context.** SWAT+ can ingest weather three ways: (1) per-station text
files indexed by `<var>.cli` ("observed, plus"), (2) legacy SWAT2012 CSVs,
(3) NetCDF with a stations-CSV sidecar. Only (1) is the native format the
engine reads at runtime; (2) and (3) are pre-processors that end up
producing (1) files anyway. Any weather pipeline that ultimately produces
runnable SWAT+ inputs has to emit (1).

The editor's parser for (1) lives in
`actions/import_weather.py::add_weather_files_type` and validates byte-level
details:

- Line 2 must be the literal column labels right-justified to widths
  `4, 10, 10, 10, 10`.
- Line 3 splits to ≥4 fields, with indices 2 / 3 as lat / lon (floats).
- Line 4+ splits to ≥3 fields, indices 0 / 1 as year / julian-day (ints).
- The final non-empty line is treated as the end date.

The per-value `.cli` index is even simpler: two header lines (free text
+ literal `filename`) followed by one sorted filename per line.

**Considered options.**

- **A. Reuse the editor's `Swat2012WeatherImport.write_station` writer
  by shipping a CSV and running the editor twice** (once to convert,
  once to import). Rejected: two subprocess calls, noisy on-disk
  intermediates, and the CSV schema is itself poorly documented.
- **B. Write a pandas-based writer that uses DataFrames internally.**
  Rejected: pandas isn't yet a dependency and the writer is tiny (one
  loop over N days × ≤2 values). Adding pandas just for string
  formatting is disproportionate.
- **C. Write a pure-stdlib typed writer that exactly mirrors the
  editor's byte-level output.** Chosen.

**Decision.** Option C.
`swatplus_builder.weather.writer.write_observed(bundle, output_dir)`
consumes a Pydantic `WeatherBundle` and produces the five
`<station>.<pcp|tmp|hmd|wnd|slr>` files plus five `<var>.cli` indexes.
Format constants (`_NBYR_W`, `_VAL_WIDTH`, `_VAL_DECIMALS`) mirror
`helpers/utils.py:DEFAULT_NUM_PAD / DEFAULT_DECIMALS` in the vendored
editor; station names use the editor's `weather_sta_name()` convention
so `weather_sta_cli` rows collide deterministically.

**Rationale.**

1. Zero subprocess hops during write, which keeps weather emission
   well under a second for multi-year datasets.
2. The file format is actually pretty stable (the editor's parser has
   been unchanged since ~2020) — the risk of chasing drift is low.
3. By owning the writer we can evolve `WeatherBundle` (e.g. sub-daily
   data) without fighting the editor's intermediate representation.
4. Unit tests can assert byte-level structure and prove the editor
   parser accepts our output via the end-to-end integration test,
   catching any drift instantly.

**Consequences.**

- We now have a hard contract test: `test_editor_api.py::test_setup_
  project_and_write_files_end_to_end` feeds our writer's output through
  the editor's `import_weather`, and asserts `weather_file`,
  `weather_sta_cli`, and per-HRU `wst_id` all get populated.
- If the editor's parser ever tightens (e.g. adds a required column
  that the current version ignores), this single test breaks, and
  we adjust the writer constants.
- `tmax` and `tmin` must be provided together (raises
  `SwatBuilderInputError` otherwise), because the `.tmp` file is a
  2-column format.

---

## ADR-020 — Synthetic weather is a test fixture, not a fallback

**Status:** Accepted — 2026-04-20.

**Context.** End-to-end tests need weather data, but at test time we want
to avoid (a) network calls to GridMET/THREDDS and (b) committing a
multi-MB real dataset to the repo. The writer in ADR-019 is generic —
anything that produces a `WeatherBundle` can feed it. The question is
what minimum source we ship for tests and "first-run smoke".

**Considered options.**

- **A. Ship a real tiny CAMELS excerpt (e.g. 1-year, 1-basin)** as a
  data file in the repo. Rejected: adds ~1 MB to the repo, and updating
  it requires a CAMELS round-trip.
- **B. Generate noise arrays from `numpy.random`.** Rejected: numpy
  isn't a weather dependency yet; cross-platform reproducibility of
  `random_state` is fragile.
- **C. Deterministic sinusoidal annual cycle + stdlib `random.Random`
  seeded from SHA-256 of the station name.** Chosen.

**Decision.** `weather/synthetic.py` produces climatologically
plausible but not physically meaningful daily timeseries. Each station
gets a per-station RNG keyed by SHA-256 to survive Python's hash-seed
randomization.

**Rationale.**

1. Zero-dep (stdlib `math`, `hashlib`, `random`) — no numpy required
   just to run the test suite.
2. Reproducible across machines: SHA-256 keyed RNG is byte-stable;
   Python 3's `hash()` is not.
3. Output is realistic enough to pass every SWAT+ input validation
   (tmax > tmin, rh ∈ [0,1], pcp ≥ 0), so the engine will actually run.
4. We tell users explicitly it's **not** real climate via docstrings
   and the module's name (`synthetic`).

**Consequences.**

- Nobody should be tempted to ship `synthesize()` output as "the
  weather for my basin" — if they do, it'll be physically wrong but
  the engine will still produce a result. Module docstring and
  `README` make this clear.
- Real-data sources (GridMET in Phase 2 Step 2, CAMELS, user CSVs) are
  also adapters that produce `WeatherBundle`; they reuse the same
  writer and the same editor-contract test we already have.

---

## ADR-021 — GridMET adapter uses pygridmet, not raw OPeNDAP

**Status:** Accepted — 2026-04-20.

**Context.** With the writer (ADR-019) settled, any weather source that
emits a :class:`WeatherBundle` works. The first production source we want
is GridMET (Abatzoglou 2013) — daily 4 km CONUS, 1979–present. It is
served over THREDDS/OPeNDAP at Northwest Knowledge Network.

**Considered options.**

- **A. Raw HTTP NCSS point queries.** The `/thredds/ncss/...` endpoint
  supports CSV output for a single lat/lon. Zero Python deps beyond
  stdlib. Rejected: per-request caps (~6 MB), no built-in retry, no
  connection pooling; implementing robust fetching (rate limits,
  server-side time chunking, retries on 5xx) becomes a non-trivial
  HTTP client. Also no way to unify the netCDF-native and CSV paths
  later.
- **B. Raw OPeNDAP via ``requests`` + DAP parser.** More efficient than
  NCSS but requires parsing DODS binary encoding. Reinvents what
  ``xarray``/``pydap`` already solve.
- **C. ``xarray.open_dataset`` against the OPeNDAP URL.** Requires a
  netCDF4/pydap engine and still rolls our own time chunking, but at
  least leverages xarray indexing. Medium effort.
- **D. ``pygridmet`` (HyRiver).** Purpose-built wrapper for this exact
  server. Handles time chunking, caches NetCDFs locally, and exposes a
  ``get_bycoords`` function returning a pandas DataFrame for a single
  (lon, lat). Same author (Chegini) as the other HyRiver packages we
  already optionally depend on. Chosen.

**Decision.** Option D.
``swatplus_builder.weather.gridmet.fetch_gridmet(stations, start, end)``
makes **one ``pygridmet.get_bycoords`` call per station**, not a single
batched multi-coord call.

**Rationale.**

1. Per-station calls give per-station error isolation — one bad
   coordinate (or one 503) does not poison an entire multi-basin run.
   pygridmet's multi-coord return uses a MultiIndex that adds zero
   value for single-pixel sampling.
2. pygridmet is optional (`extras_require["gridmet"]`) so the core
   writer + synthetic path stays zero-dep.
3. The lazy-import pattern (imported inside `fetch_gridmet`, not at
   module top) means `from swatplus_builder.weather import ...` works
   without pygridmet installed. Users see a clear, actionable error
   only if they actually try to fetch.
4. We own the unit conversions (K→°C, W/m²→MJ/m²/day, %→fraction) and
   the `tmax > tmin` invariant clamp, not pygridmet, so bugs in our
   output can't be blamed on upstream.

**Consequences.**

- One extra: `pip install 'swatplus-builder[gridmet]'`. Documented in
  the module docstring and README.
- If pygridmet's CSV column naming ever changes from ``"<var>
  (<unit>)"``, we fail loudly in `_normalize_columns` rather than
  silently producing garbage. Covered by a regression test that
  feeds the adapter a handcrafted DataFrame in that exact format.
- Tests use a monkey-patched `_FakeClient` that matches pygridmet's
  signature; the real HTTP path is exercised only when the user sets
  `SWATPLUS_BUILDER_RUN_GRIDMET=1`. CI stays hermetic.
- Any **future** real weather source (Daymet, NLDAS-2, CAMELS, user
  CSV) follows the same pattern — adapter → `WeatherBundle` → writer.
  The editor-contract test in `test_editor_api.py` already proves the
  bundle→editor round trip works; new adapters inherit that coverage
  for free.

---

## ADR-022 — gNATSGO via Planetary Computer; Williams (1995) for USLE K

**Status:** Accepted — 2026-04-20.

**Context.** `seed_minimal_soils` (ADR-017) writes one hardcoded
loam-like row per distinct soil name — enough to pass `import_gis` but
useless for real simulations. Phase 2 Step 2 is the real-data
replacement: every HRU's soil must come from a USDA-authoritative
source, with layered properties sufficient for SWAT+'s water-balance
calculators.

**Considered data sources.**

- **A. Raw SSURGO via Soil Data Access (SDA) SOAP.** Canonical, free,
  but: ~5 s latency per query, complex XML payloads, per-query caps,
  flaky under load. We'd need a rate-limited client with retries and a
  local cache — substantial code before we write the first horizon.
- **B. SSURGO tabular bulk downloads** (per-county ZIPs). Robust but
  reproducing the 3,000+ county joins in code is a ~1-month effort.
- **C. gNATSGO on Planetary Computer.** Microsoft ships the whole
  CONUS gNATSGO (2022) as Parquet-on-Azure via a public STAC catalog.
  One query returns item hrefs; each Parquet read with a mukey filter
  is a few hundred ms. Already used successfully in the parent
  `pipeline/04_get_soil.py`.
- **D. SoilGrids (ISRIC, 250 m global).** Global, but coarser than
  SSURGO and not USDA-authoritative — unsuitable for US-focused SWAT+
  work.

**Decision.** Option C.
`swatplus_builder.soil.gnatsgo.fetch_gnatsgo_profiles(mukeys, ...)`
queries the `gnatsgo-tables` collection, filters `component`,
`chorizon`, and `muaggatt` by the caller-supplied mukey set, and
returns typed `SoilProfile`s.

**USLE K formula.** Williams 1995 (EPIC) — the same formulation SSURGO
uses internally to populate `kwfact_r` when it's present. We prefer
recomputing from sand/silt/clay/OC because:

1. `kwfact_r` is absent for a nontrivial fraction of horizons (rock
   outcrops, organic soils, newly-mapped areas).
2. Recomputing gives us a value that's consistent with our other
   parameter derivations (albedo from Post 2000, OC from Van Bemmelen).
3. When calibration matters, we want K tied to measurable texture +
   OC, not an opaque lookup.

**Per-mukey profile assembly.**

- Pick the **majority component** (`comppct_r` DESC, `cokey` ASC for
  tie-break). Rationale: SWAT+ HRUs model a homogeneous parcel; the
  majority is the statistically most-likely driver of its hydrology.
- Sort horizons by `hzdept_r` ascending — deepest horizon yields
  `soils_sol.dp_tot`.
- Skip placeholder/NULL horizons (``NOTCOM`` map units, bedrock rows).
- Single-letter `hydgrpdcd` pass-through; dual codes (`A/D`) collapse
  to the **worst-drainage** member (ADR default: `D`). Rationale:
  undrained condition is the SWAT+ default for most watersheds.

**Consequences.**

- Optional extra: `pip install 'swatplus-builder[soils]'` pulls
  `pystac-client`, `planetary-computer`, `pyarrow`. Core stays lean.
- `seed_minimal_soils` is kept verbatim (ADR-017) — still the go-to for
  the `tiny_watershed` test fixture. `write_soils` cleanly replaces
  any seeded rows it overlaps with, so the "seed first, upgrade
  later" pattern is a supported workflow.
- Hermetic test strategy: mock `pystac_client` + `planetary_computer`
  + `pd.read_parquet`, feed synthetic tables. Real PC is opt-in via
  `SWATPLUS_BUILDER_RUN_GNATSGO=1`.
- **Responsibility boundary:** the adapter does NOT do raster I/O.
  Extracting the unique mukey set from a mukey raster clipped to the
  basin is the GIS stage's job (belongs in `gis.soil` when that lands).
  Keeping `fetch_gnatsgo_profiles` pure-tabular means the same function
  serves user BYO mukey lists and eliminates rioxarray/rasterio from
  the `[soils]` extra.
- **Known gaps.** `caco3` and `ph` are exposed in `SoilHorizon` but
  not populated by the current `chorizon` column set — we didn't
  request `caco3_r`/`ph1to1h2o_r`. They remain null, which matches
  the editor's default. Trivial to widen the fetch later.

---

## ADR-023 — Output reader is a whitespace parser; summary is best-effort

**Status:** Accepted — 2026-04-20.

**Context.** After the engine succeeds we want `SwatPlusRun.summary` to
carry a handful of headline numbers (precipitation, ET, outlet
discharge, …) so agents can cite results without opening any file
themselves. The engine writes these in plain text (`*_aa.txt`) in a
fixed format: one title line, one header line, optionally one units
line, then N data rows. There are ~20 such files per print time step;
we don't want to hand-maintain a schema for all of them up front.

**Considered options.**

- **A. pandas-only reader.** `pd.read_fwf` or `pd.read_csv(sep=r"\s+")`
  with per-file schemas. Fast path, but drags pandas into the runtime
  path (currently only a test/analysis dep) and still needs per-file
  hand-coding for the quirky title/units lines.
- **B. Parse via SWAT+ Editor's output DB.** The editor has a
  "SWAT+ Check" path (`get_swatplus_check`) that imports `*_aa.txt`
  into SQLite. Reusing it would give us a typed schema for free — but
  re-invokes the editor subprocess, duplicates files on disk, and
  couples us to the editor for every run summary.
- **C. Pure-stdlib whitespace parser, schema-free.** Read the header
  line as column names (whitespace-separated), auto-detect the units
  line, and emit `list[dict[str, Any]]`. Coerce the seven identifier
  columns (`jday`, `mon`, `day`, `yr`, `unit`, `gis_id`, `name`) via
  fixed rules and everything else as float.

**Decision.** Option C.
`swatplus_builder.output.reader` ships one generic `read_output_file`
and thin per-file wrappers (`read_basin_wb_aa`, `read_channel_sd_aa`).
`swatplus_builder.output.summary.build_run_summary` consumes those and
produces the canonical `dict[str, float]` that populates
`SwatPlusRun.summary`.

**Rationale.**

- SWAT+ never writes nested columns or multi-line records — one row
  per `write` statement means `str.split()` is lossless.
- Schema-free makes the reader robust to SWAT+ engine revisions: when
  the Fortran adds a new column to `basin_wb_aa`, we pick it up with
  zero code changes.
- Pure-stdlib keeps the post-run path dependency-free: an agent can
  introspect `SwatPlusRun.summary` on a bare `pip install
  swatplus-builder` with no extras.
- The summary is deliberately **best-effort** — a missing or malformed
  AA file logs a DEBUG message and yields a partial `summary` dict,
  never an exception. An ill-formed output should not mask a
  successful engine exit; agents treat "empty summary" as "look at
  the output files yourself".

**Outlet discharge heuristic.** `channel_sd_aa.txt` has no
`is_outlet` column. We pick the row with the largest `flo_out` — in a
well-formed SWAT+ project the outlet channel receives all upstream
flow and therefore has the maximum annual volume. This sidesteps
having to cross-reference `gis_channels` from inside the run wrapper.
Convert the annual volume (m³) to a mean rate (m³/s) by dividing by
`365.25 × 86400`.

**Canonical summary keys.** Frozen in
`swatplus_builder.output.summary.SUMMARY_KEYS`:
`precip_mm`, `et_mm`, `pet_mm`, `surq_gen_mm`, `latq_mm`, `perc_mm`,
`wateryld_mm`, `mean_q_at_outlet_m3_per_s`, `channel_count`.

**Consequences.**

- **No pandas in the hot path.** Agents that want DataFrames can
  trivially `pd.DataFrame(table.rows)` from an `OutputTable`.
- **Missing keys are normal.** Consumers must use
  `summary.get(key)`, not subscript. The key set is a *subset* of
  `SUMMARY_KEYS`, never a superset.
- **Non-object files are out of scope.** Files without the
  `jday mon day yr unit gis_id name` prefix (e.g. `output.std`,
  `hydrology.cha`) are not handled by the generic parser. If/when we
  need those, they get their own reader; the whitespace parser stays
  focused on the object-level AA/day/mon/yr files.
- **Token-count mismatches raise.** The parser is strict about
  rectangularity — a row with the wrong number of tokens indicates
  an engine / locale / whitespace bug that we should surface, not
  silently skip. The wrapper in `build_run_summary` still downgrades
  these to WARN so the run result remains usable.

---

## ADR-024 — `gis.soil` is raster-only; tabular lives in `soil.*`

**Status:** Accepted — 2026-04-20.

**Context.** Before this change, `swatplus_builder.gis.soil` held a
single stub that conflated three unrelated concerns: raster I/O
(mukey clipping), tabular SSURGO joins, and `soils_sol` emission.
Phase 2 Step 2 (ADR-022) gave us a clean typed pipeline
(`SoilProfile`) implemented in `swatplus_builder.soil.*`. The GIS
side of the pipeline still needed "which mukeys does this watershed
touch?" — a pure-raster question.

**Considered options.**

- **A. Keep the monolithic stub** and graft the `SoilProfile` writers
  into it. Rejected: re-introduces the three-concern blob we already
  unwound in `soil.*`.
- **B. Put mukey extraction inside `soil.gnatsgo`.** Rejected:
  `soil.gnatsgo` is a tabular Parquet adapter; adding rasterio as a
  hard dependency would bloat the `[soils]` extra and force every
  BYO-mukey user to install geospatial wheels they don't need.
- **C. Slim `gis.soil` to raster-only responsibilities**, with
  `fetch_mukey_raster` + `extract_unique_mukeys` + a thin
  `extract_mukeys_for_watershed` wrapper. `soil.gnatsgo` stays
  tabular. The two modules compose via a plain `set[int]`.

**Decision.** Option C.
`swatplus_builder.gis.soil` is now three public functions (plus two
module-level constants for the PC endpoint). The legacy
`SoilRow` / `SoilLayerRow` / `build_soil_rows` / `ingest_mukey_raster`
stubs are removed — nothing in the tree consumed them (checked via
`rg` across `swatplus-builder/`).

**Rationale.**

- **Clean cross-module contract.** `set[int]` is the universal
  handoff between GIS and tabular stages. No coupling beyond that.
- **Dependency hygiene.** `gis.soil` uses only deps already in the
  `[gis]` extra (`rasterio`, `shapely`, `geopandas`). The lone
  cloud path (`fetch_mukey_raster`) lazy-imports `pystac-client` /
  `planetary-computer` from `[soils]` so users with a pre-downloaded
  raster never need Azure client wheels.
- **Nodata handling is opinionated by default.** gNATSGO's mukey
  raster uses ``0`` for "no map unit / water / urban" and
  ``2_147_483_647`` post-promotion from `uint32` by rioxarray. Both
  get dropped automatically; `nodata_sentinels=()` opts out for
  non-gNATSGO rasters.
- **Reprojection errors are typed.** GDAL raises
  `CPLE_AppDefinedError` (a bare `Exception`) when a reprojection is
  mathematically invalid (e.g. boundary far outside the destination
  UTM zone's validity). We catch this and surface as
  `SwatBuilderPipelineError` with both CRSs in `.context` so agents
  can triage without parsing GDAL strings.

**Consequences.**

- **End-to-end pipeline closes.** `build_watershed(...)` →
  `gis.soil.extract_mukeys_for_watershed(...)` →
  `soil.gnatsgo.fetch_gnatsgo_profiles(...)` →
  `soil.writer.write_soils(...)` now composes without the user
  needing to hand-roll a mukey extraction step.
- **Caching is caller-controlled.** The default cache directory is
  `watershed.workdir / 'rasters' / 'mukey.tif'` so that the clipped
  raster lands next to the other delineation artifacts. Explicit
  `cache_dir=` override is supported.
- **Single-tile scope.** We take the FIRST matching STAC item and
  clip to the boundary. This is correct for single-state CONUS
  watersheds (the common case). Multi-state basins and watersheds
  straddling Hawaii / Alaska would need a mosaic step — flagged as
  follow-up in the module docstring.
- **Hermetic testability.** Tests use a 4×4 synthetic GeoTIFF +
  fake `pystac_client` / `planetary_computer` modules. No network
  hits on the default test path. The opt-in real-PC round-trip
  is already covered by `test_soil_gnatsgo.py::test_real_pc_endpoint`.

---

## ADR-025 — Dominant-HRU MVP; DEM is the canonical grid

**Status:** Accepted — 2026-04-20.

**Context.** `gis.hru` was the last remaining Phase-0 stub. SWAT+
expects one or more HRUs per LSU, where an HRU is a ``(landuse,
soil, slope-band)`` triple with area attributes (``arsub`` /
``arlsu`` / ``arland`` / ``arso`` / ``arslp``). QSWATPlus offers two
HRU modes:

* **Dominant.** Exactly one HRU per LSU; the triple is the
  most-frequent one in the LSU's pixels; the HRU covers the entire
  LSU's area (pixels that didn't match are re-attributed to the
  dominant class).
* **Multiple / full-overlay.** One HRU per distinct triple that
  survives a percent-area filter; each HRU covers its own pixels.

**Considered options.**

1. **Full-overlay only.** Rejected for MVP: pulls in HAND-based LSU
   splitting and waterbody subtraction (both Phase 2) before we can
   validate anything end-to-end.
2. **Both modes, behind a flag.** Accepted. `dominant_only=True`
   (default) is the "first SWAT+ run" path; `dominant_only=False`
   is the full-overlay mode with `min_hru_fraction` filter.
3. **Pure raster → rasterize everything → loop pixels.** Also
   accepted — using the DEM grid as the canonical alignment target
   and `rasterio.warp.reproject` with nearest-neighbor to harmonize
   landuse / soil / slope rasters.

**Decision.** Option 2 + 3.

- Two modes, same function signature, one flag. Default is
  dominant-only because it's the minimal viable SWAT+ input.
- DEM is the canonical grid. Landuse and soil rasters reproject
  to it; slope is either user-supplied (reprojected) or computed
  directly from the DEM via `np.gradient` (Horn-style percent-slope
  approximation). No user setup of alignment required.

**Rationale.**

- **Dominant mode as the default.** One HRU per LSU produces the
  smallest possible `gis_hrus` table that the editor accepts. For
  a basin with ~10 subbasins this is 10 HRUs — trivial to inspect,
  trivial to debug, and enough for agents to produce a first
  engine run.
- **DEM = canonical grid.** Using the DEM's transform/CRS means
  slope derivation is free (same grid), and there's exactly one
  canonical alignment target for every raster in the pipeline. If
  a user's landuse raster is in EPSG:5070 and the DEM is in UTM
  17N, we silently reproject LU and move on.
- **Dominance semantics match QSWATPlus.** When `dominant_only=True`
  the HRU inherits the LSU's full area (all `ar*` fields = LSU area)
  and geometry. Slope, centroid, and elevation use LSU-level stats
  rather than the per-combo pixel stats, because the dominant HRU
  IS the LSU geometrically. Full-overlay mode uses per-combo pixel
  stats exclusively.
- **`soil = f"gnatsgo_{mukey}"`** is the producer/consumer contract
  between `gis.hru` and `soil.gnatsgo.fetch_gnatsgo_profiles`.
  Both sides use this exact naming so the editor's `import_gis`
  FK check between `gis_hrus.soil` and `soils_sol.name` passes
  without a lookup table.
- **Catalog JSON embeds the typed rows.** `HRUResult` stays
  pure-path (existing schema) but `hru_catalog.json` carries the
  full `LsuRow` / `HruRow` serialized so downstream writers never
  need to re-parse the GPKG. The `load_lsus_hrus(hru_result)` helper
  returns pydantic-validated lists ready to drop into `GisTables`.

**Consequences.**

- **MVP scope is explicit.** One LSU per subbasin (category 1,
  floodplain). No HAND split, no waterbody subtraction, no
  percent-area HRU filter. Each of these is a Phase-2 follow-up
  tracked in the module docstring.
- **Channel attrs.** LSU fields `channel`, `len1`, `csl`, `wid1`,
  `dep1` come from `watershed.channels_vector` via `sub_id` join.
  A subbasin with no channel (shouldn't happen with WBT but
  possible after lake burning) falls back to safe defaults —
  flagged in the log, not a fatal error.
- **Deterministic output.** No network, no subprocesses, pure
  numpy + rasterio. Same inputs → byte-identical outputs. Makes
  HRU generation trivially re-runnable when iterating on LU
  reclassification.
- **Tests stay hermetic.** The synthetic 8×8 watershed fixture
  runs the entire pipeline (alignment, overlay, vectorization,
  catalog JSON, round-trip) end-to-end in <100 ms.

---

## ADR-026 — Mock datasets DB uses vendored Peewee models, not hand-rolled DDL

**Status:** Accepted — 2026-04-20.

**Context.**

The SWAT+ Editor's `setup_project` and `write_files` actions read from a
`swatplus_datasets.sqlite` reference database (~1 MB, downloaded on
first use). Integration tests that depend on this DB cannot run in
network-isolated CI and create a hard external dependency. We need a
lightweight, version-pinned, self-contained substitute for testing the
LTE pipeline end-to-end.

**Considered options.**

1. **Download the real DB in CI** — breaks offline/fast-feedback
   loops; a SHA-mismatch or upstream URL change silently skips the
   entire integration tier.
2. **Hard-code DDL in a fixture script** — must be kept in sync with
   the vendored editor's Peewee models manually; schema drift is
   silent.
3. **Subprocess that imports the vendored Peewee models** — the mock
   DB is created by the *same ORM that reads it*. Schema compatibility
   is a tautology.

**Decision.**

`db/mock_datasets.py:create_mock_datasets_db()` spawns a Python
subprocess that imports `swatplus_builder.editor.vendored.*` Peewee
models and uses `Model.create(...)` to populate a minimal
`swatplus_datasets.sqlite`. The subprocess approach keeps peewee's
database-connection state isolated from the test runner.

**Rationale.**

- Schema drift between the mock and the real consumer is impossible
  by construction. When the vendored editor is bumped (ADR-014), the
  mock DB automatically picks up any column additions.
- The script is ~150 lines of pure Python; no SQL, no DDL constants,
  no CSV assets to maintain.
- The subprocess overhead (~200 ms) is amortized over a `module`-scoped
  fixture; all five integration tests share one mock DB.
- The mock DB is test-only. Production use still calls
  `ref/bootstrap.py:ensure_datasets_db()` to download the real file
  (ADR-016). The two code paths never interleave.

**Consequences.**

- A new `@pytest.mark.slow` test class (`tests/test_phase2_step7.py`)
  exercises the full LTE pipeline without any network calls.
- Adding a new SWAT+ parameter table to the mock requires adding one
  `Model.create(...)` call. Contrast with a DDL approach (one `CREATE
  TABLE` + one `INSERT`).
- The mock DB intentionally contains *only* what the LTE path needs.
  Non-LTE tables (e.g. `soils_sol`, `urban_urb`) are not populated;
  tests that need them must use the real datasets DB or extend the
  mock separately.

---

<!-- template for future ADRs:
## ADR-NNN — <title>

**Status:** Proposed / Accepted / Superseded by ADR-MMM — YYYY-MM-DD.

**Context.** …

**Considered options.** …

**Decision.** …

**Rationale.** …

**Consequences.** …
-->

---

## ADR-027 — 2-Tier hybrid soil architecture: PC muaggatt (Tier 1) + USDA SDA (Tier 2)

**Status:** Accepted — 2026-04-21.

**Context.** The original `soil/gnatsgo.py` adapter depended entirely on Planetary Computer's `chorizon` Parquet table, which was found to be sparse (many mukeys had no horizon records). A fallback was added using `muaggatt` aggregate properties, but the code was monolithic and the fallback was fragile. For production pipelines we need: (a) guaranteed coverage for every mukey, (b) high-fidelity horizon data when available, and (c) strict validation to prevent bad data from corrupting the model.

**Considered options.**

1. **Augment `gnatsgo.py` in-place** — pile the fallback logic into the existing file. Rejected: the file was already 750 lines; merging a second tier would make it unmaintainable.
2. **Planetary Computer only, better fallback** — improve synthetic generation from `muaggatt`. Rejected: PC `chorizon` will always be the bottleneck; no amount of synthetic improvement compensates for absent real data.
3. **USDA SDA only** — query USDA Soil Data Access as the sole source. Rejected: SDA is rate-limited, external, and not suitable as a sole dependency in headless pipelines.
4. **2-Tier hybrid** — Tier 1 (PC `muaggatt`) guarantees 100% coverage; Tier 2 (SDA horizon) enriches when valid. Chosen.

**Decision.** Option 4.

- `soil/pc.py` (Tier 1): queries `muaggatt` from PC; generates synthetic layers using SWAT+ empirical regressions; falls back to `synthetic_default` if PC is unreachable.
- `soil/sda.py` (Tier 2): batched USDA SDA API fetcher; versioned JSON cache (`sda_v1`); exponential backoff + rate-limit throttle; `reproducible` mode for offline/deterministic runs.
- `soil/builder.py`: orchestrator; replaces Tier 1 with Tier 2 **only if** `n_layers ≥ 2 AND max_depth ≥ 500 mm`; applies `normalize_profile()` (2500 mm depth cap) to all outputs.
- `soil/gnatsgo.py`: backward-compatible wrapper — callers using `fetch_gnatsgo_profiles_result` are silently routed to `builder.py`.

**Consequences.**

- 100% mukey coverage is guaranteed regardless of PC or SDA availability.
- SDA cache (`sda_v1` versioning) prevents stale data from polluting future runs.
- Profile source is tracked in `SoilProfile.source` (`pc_muaggatt` / `synthetic_default` / `sda_horizon`) for full provenance.
- `SoilConfig` presets (`fast()`, `high_fidelity()`, `reproducible_mode()`) provide one-liner control over the trade-off.
- Adding a Tier 3 (e.g. user-supplied CSV) requires only a new module + a merge hook in `builder.py`.

---

## ADR-028 — `project_metadata` table + `output/metrics.py` for pipeline observability

**Status:** Accepted — 2026-04-21.

**Context.** Post-Phase-2 the pipeline produced `TxtInOut/` but offered no structured record of what soil data was used, nor any hydrological evaluation of the model output. Two gaps: (1) `soil_report` was transient — lost between runs; (2) no NSE/KGE/BFI calculation was available without a heavy external library.

**Considered options (DB persistence).**

1. **Write `soil_report` to a sidecar JSON file.** Rejected: not co-located with the project; easy to lose or overwrite.
2. **Add a column to `project_config`.** Rejected: `project_config` is a single-row table with a fixed schema consumed by the editor. Adding freeform JSON columns risks ORM conflicts on editor upgrades.
3. **New `project_metadata (key TEXT PRIMARY KEY, value TEXT)` table.** Chosen: schema-stable, infinitely extensible, never read by the editor.

**Considered options (metrics).**

1. **Wrap `hydroeval` or `spotpy`.** Rejected: heavy dependencies; pulls in NumPy/SciPy even when not needed.
2. **Pure-stdlib implementation.** Chosen: NSE and KGE are simple closed-form expressions; BFI uses a 2-pass recursive filter; FDC is a sorted interpolation. Zero-dependency for the evaluation pipeline.

**Decision.** Both options 3 + 2 above.

`db/schema.py` adds `PROJECT_METADATA_DDL` and `PROJECT_METADATA_UPSERT_SQL`. `db/project.upsert_project_metadata(project_db, key, value_json)` is the single write path. `output/metrics.py` ships `nse`, `kge`, `baseflow_index` — all operating on plain Python sequences.

**Consequences.**
- `soil_report` now travel inside the project SQLite, queryable with `SELECT value FROM project_metadata WHERE key = 'soil_report'`.
- NSE/KGE require caller-supplied observed arrays.

---

## ADR-028: Environment Compatibility (Python 3.9+)

**Status:** Accepted — 2026-04-21.

**Context**: The platform must run in restrictive academic/enterprise environments where only Python 3.9 is available.
**Decision**: Standardize on Python 3.9 compatibility. Remove all Python 3.10+ specific syntax (e.g., `zip(strict=True)`).
**Consequences**: Broader reach; guaranteed stability on legacy systems.

---

## ADR-029: Automated Hydrological Orchestration

**Status:** Accepted — 2026-04-21.

**Context**: Building a SWAT+ project requires multiple discrete steps (GIS, Soil, Weather, Editor, Run). Managing these manually in scripts is error-prone.
**Decision**: Implement a unified orchestration pattern with a standardized output hierarchy (`raw/`, `delin/`, `hrus/`, `project/`, `reports/`, `plots/`).
**Consequences**: Standardizes the "SWAT+ Platform" look and feel.

---

## ADR-030: Standardized Evaluation and Plotting Suite

**Status:** Accepted — 2026-04-21.

**Context**: Users need immediate feedback on model performance vs observed data (NWIS) to validate simulations.
**Decision**:
1. **Calibration/NWIS**: Automatically fetch observed discharge from USGS.
2. **Evaluation**: Standardize on NSE, KGE, and BFI.
3. **Manuscript Suite**: Generate a 7-figure (12+ file) diagnostic suite (Hydrograph, FDC, Scatter, Residuals, Seasonal, Soil).
**Consequences**: Enables publication-ready workflows directly from the CLI.

---

## ADR-024: Unified Weather Forcing for Regional Models

**Status:** Accepted — 2026-04-22.

**Context**: In complex multi-subbasin projects, mapping unique weather stations to every subbasin can trigger segmentation faults in the SWAT+ engine's `climate_control.f90` if internal indexing doesn't align with the binary's expectations or metadata structure.
**Decision**: For stabilize-phase basins, collapse all subbasin weather metadata into a single "virtual station" located at the basin centroid (basin-mean lat, lon, elev). Use a single GridMET feed for this virtual station.
**Consequences**: Eliminates indexing-related crashes (Exit 174) and simplifies the input `weather-sta.cli` structure. Quantitative impact on small basins (< 500 km²) is negligible.

---

## ADR-025: Transition to Standard Mode for Climate Robustness

**Status:** Accepted — 2026-04-22.

**Context**: LTE (Lumped Tributary Area) mode in SWAT+ is a newer, streamlined routing logic but has exhibited stability issues (Exit 174/134) in the current binary revision on macOS when processing external climate forcing.
**Decision**: Set `is_lte=False` by default for the Marsh Creek baseline. Standard Mode provides the most robust and legacy-tested path for reading climate inputs and calculating catchment hydrology.
**Consequences**: Slightly more complex routing structure in the database but significantly higher engine stability.

---

## ADR-026: Mandatory Environment Paths for macOS Engine Stability

**Status:** Accepted — 2026-04-22.

**Context**: The current macOS SWAT+ binary is compiled with Intel Fortran/OpenMP and requires `libiomp5.dylib`. This library is often missing from user paths, causing silent or crashy failures on engine start.
**Decision**: Explicitly manage `DYLD_LIBRARY_PATH` and `DYLD_FALLBACK_LIBRARY_PATH` in the engine runner (`src/swatplus_builder/run/swatplus.py`). Prepend the project `bin/` directory to these paths.
**Consequences**: Guarantees binary execution regardless of global system configuration. Requires developers to ensure `libiomp5.dylib` is present in the `bin/` directory.

---



---

## ADR-031: Calibration Bridge Authoritative Rerun Fallback on Flat-Output Signature

**Status:** Accepted — 2026-04-24.

**Context**: In parity-hardened calibration runs, pySWATPlus produced varying parameter proposals and varying `calibration.cal` entries, but raw simulation outputs remained byte-identical, causing flat objective histories.

**Decision**: When the bridge detects a flat-output signature (multiple parameter vectors with one output hash/metric), rerun each proposal through direct-parameter objective execution and score using `evaluate_run`. Persist metric source as `evaluate_run_real_objective_rerun`.

**Consequences**:
- Calibration metrics remain trustworthy even when raw pySWATPlus objective behavior is unreliable in this environment.
- Runtime cost increases, accepted as a reliability-first tradeoff.
- `evaluate_run` is reinforced as the sole authoritative metric source.

---

## ADR-032: Integrate SWAT+ Playbook Skill Into Autoresearch Decision Loop

**Status:** Accepted — 2026-04-24.

**Context**: Rejected investigative paths were being revisited by automation, reducing efficiency and risking regressions.

**Decision**: Add `swatplus_playbook` machine-usable rule layer and consult it before autoresearch proposal generation. Append experiment evidence to playbook in append-only mode.

**Consequences**:
- Known rejected paths can be avoided automatically.
- Validated practices are favored in future automated investigations.
- Evidence accumulation remains traceable and non-destructive.

---

## ADR-033: Locked Calibration Objective Uses Strict Outlet Policy by Default

**Status:** Accepted — 2026-04-27.

**Context**: A fresh Phase 3F real-engine locked quick run for `usgs_01547700` surfaced a warning that the calibration objective had allowed the evaluator default outlet policy (`auto`) even though the benchmark lock itself was strict-pinned. That creates a hidden risk: calibration could optimize a different terminal channel than the one recorded in the benchmark lock.

**Decision**: `make_real_objective` now calls `evaluate_run(..., outlet_policy="strict")` unless `allow_outlet_autodetect=True` is explicitly requested. The auto policy remains available for exploratory workflows, but locked-benchmark calibration and verification use strict scoring by default.

**Consequences**:
- Locked-benchmark metrics now enforce the recorded outlet context rather than relying on evaluator defaults.
- Objective traces preserve requested/selected outlet IDs and `outlet_autodetected` status for every evaluation.
- Regression tests pin both behaviors: strict by default and auto only when explicitly allowed.

---

## ADR-034: Roadmap v1.2 Separates Operational Tooling From Hydrologic Realism Gates

**Status:** Accepted — 2026-04-28.

**Context:** Phase 3A-3E delivered the core operational framework: typed CLI/MCP surfaces, artifact storage, locked-benchmark calibration, bridge diagnostics, container baseline, and health/version commands. Phase 3F then resolved major structural portability blockers, including routing zero-flow, outlet snapping, topology gates, cycle removal, and contrast-basin execution. However, Phase 3G evidence shows that verified calibration improvement does not yet equal benchmark-grade hydrologic realism: `03339000` still has volume bias, baseflow excess, low-flow overestimation, and autumn seasonal weakness.

**Decision:** Recast the roadmap around two separate maturity tracks. Operational/tooling maturity is largely complete for the current alpha framework; research-grade and production-grade hydrologic claims remain gated by new long-term phases:

- Phase 3G: Hydrologic Realism & Structural Diagnosis.
- Phase 3H: Multi-Basin Research Benchmark.
- Phase 3I: Production Readiness & Release Engineering.
- Phase 3J: Publication-Grade Case Study Package.
- Phase 3K: Agentic Research Operations.
- Phase 4: Broader Hydrologic Generalization.

**Consequences:**

- Future agents should not keep expanding interfaces before resolving realism evidence.
- Metric improvements require realism audits and caveat ledgers before being presented as hydrologic skill.
- `SURLAG` and `SOL_K` dead-end evidence for the current LTE benchmark should prevent repeated unproductive calibration expansions.
- PyPI/GHCR/docs release work can proceed separately from strong hydrologic performance claims, but public scientific claims require Phase 3G/3H evidence.

---

## ADR-035: Coverage Diagnosis as an Artifact-Only Structural Gate

**Status:** Accepted — 2026-04-29.

**Context:** Phase 3G evidence showed that `03339000` can pass the fail-loud topology gate while still covering only ~75% of the expected basin. The basin is runnable, but not clean enough to treat calibration metrics as fully representative without caveats. The existing `basin-report` and `basin-compare` commands summarized this issue but did not classify the likely mechanism or prescribe the next structural experiment.

**Decision:** Add `swat coverage-diagnosis` as an artifact-only diagnostic layer. It consumes existing basin artifacts and classifies coverage state into explicit categories such as `complete_coverage`, `partial_coverage_after_successful_snap`, `outlet_snap_still_suspect`, and `blocked_topology`. It writes `coverage_diagnosis.json` and `coverage_diagnosis.md` with evidence, recommendations, and next experiments.

**Consequences:**

- A topology gate pass no longer silently implies full coverage validity.
- The current `03339000` state is classified as `partial_coverage_after_successful_snap`: snapping reached the high-accumulation drainage area, but coverage remains incomplete.
- The next recommended work is DEM conditioning / routing-fragmentation diagnosis before broad calibration expansion.
- The diagnostic stays lightweight and reproducible because it does not rerun GIS or the SWAT+ engine.

---

## ADR-036: Prefer FillDepressions for `03339000` Coverage-Rerun Candidate

**Status:** Accepted — 2026-04-29.

**Context:** `03339000` remained scientifically caveated after max-accumulation snapping because `BreachDepressionsLeastCost` produced only 75.2% expected basin coverage, 9.22 km centroid offset, and `partial_coverage_after_successful_snap` diagnosis. The next Phase 3G experiment was a controlled DEM-conditioning matrix holding outlet, threshold, and snap settings fixed.

**Decision:** For the next full `03339000` E2E rerun, use `SWATPLUS_DEM_CONDITIONING=fill`. The matrix showed `FillDepressions` improved generated area ratio from `0.752` to `0.984`, centroid offset from `9.22 km` to `0.07 km`, and IoU from `75.22%` to `98.41%`, while changing the diagnosis to `complete_coverage`.

**Consequences:**

- `FillDepressions` is not made the global default yet; the evidence is basin-specific and should be expanded in Phase 3H.
- For low-gradient large basins with the same signature, agents should run `swat dem-matrix` before choosing a conditioning mode.
- The next `03339000` calibration evidence should be regenerated from a fill-conditioned E2E run, not compared directly against the old breach-conditioned topology without caveats.

---

## ADR-037: Stream Large Channel Outputs During Outlet Evaluation

**Status:** Accepted — 2026-04-29.

**Context:** The fill-conditioned `03339000` E2E rerun resolved basin coverage but produced a very large `channel_sd_day.txt`. The generic SWAT+ output parser materializes full tables and was too slow/heavy for this evaluation path, even though outlet scoring only needs the requested outlet and terminal candidates.

**Decision:** Add a streaming read path in `output.eval` for large `channel_sd_day.txt` files. When the file exceeds the large-output threshold, evaluation scans rows once and retains only requested/terminal `gis_id` series needed for strict scoring, dry-outlet fallback, or terminal best-NSE selection.

**Consequences:**

- Large-basin evaluation can complete without loading multi-GB channel outputs into memory.
- Outlet provenance and selected GIS IDs remain unchanged relative to the normal parser path.
- The large-output threshold is intentionally conservative and covered by a forced-streaming regression test.
- This is an evaluator scalability fix, not a hydrologic skill claim.

---

## ADR-038: Treat Fill-Conditioned `03339000` as a New Structural Benchmark Candidate

**Status:** Accepted — 2026-04-29.

**Context:** The DEM-conditioning matrix showed `FillDepressions` resolved the 03339000 coverage caveat, and the full fill-conditioned E2E rerun confirmed `complete_coverage` with area ratio `0.984`. However, the fill topology changed the selected evaluation outlet to GIS `1285`, while previous calibration evidence used breach-conditioned outlet `290`. The rerun also logged soil-fetch fallback in the active runtime.

**Decision:** Do not compare fill-conditioned metrics directly against old breach-conditioned calibration metrics as if they were the same benchmark. Treat the fill run as a new structural benchmark candidate requiring outlet identity audit, soil provenance restoration, lock, calibration, and independent verification.

**Consequences:**

- Coverage success is preserved as a validated structural improvement.
- Hydrologic skill remains unclaimed until outlet and soil provenance are pinned.
- Future agents should prefer fill conditioning for this basin only after recording the topology/outlet shift explicitly.

---

## ADR-039: Hydrofabric-First for CONUS, DEM-First as Global Fallback

**Status:** Accepted — 2026-04-29.

**Context:** The framework proved that DEM conditioning and outlet snapping can repair large-basin coverage failures, but the fill-conditioned `03339000` rerun also exposed a scientific caveat: the outlet selected for NSE scoring can differ materially from the physically nearest terminal channel. In parallel, the project’s long-term goal is to run anywhere in the world, where CONUS-only hydrofabric services such as NLDI are unavailable.

**Decision:** Treat hydrofabric data as the primary authority whenever available, especially for CONUS USGS basins. Use NLDI/NHDPlus/WBD/NWIS priors for basin boundary, outlet provenance, and candidate subbasin fabric. Use DEM-first delineation only when hydrofabric priors are unavailable or insufficient. Persist the authority tier in artifacts and keep DEM conditioning as validation/refinement rather than sole source of truth.

**Alternatives considered:**

- DEM-first everywhere — rejected because it already produced outlet drift and overly fragmented large-basin topology for CONUS cases.
- Hydrofabric-first only — rejected because the framework must still run globally where NLDI/NHDPlus are unavailable.
- Manual outlet selection by best NSE — rejected because it is diagnostic only and can select a physically implausible outlet.

**Consequences:**

- CONUS runs become more defensible for publication and calibration.
- Global runs remain supported via the existing DEM pipeline.
- Outlet audit and soil provenance become mandatory gates before locked calibration.
- Future basin runs must record whether `basin_authority` is hydrofabric-first or DEM-first.

**Status:** Accepted

---

## ADR-040: Prefer NLDI Gauge Coordinates for USGS Outlet Audit

**Status:** Accepted — 2026-04-29.

**Context:** The new outlet-audit workflow needs a physical gauge location before it can rank terminal outlet candidates. For USGS basins, the gauge location can often be resolved directly from NLDI/NWIS site geometry, which is better provenance than using the already-snapped model outlet or a downstream diagnostic coordinate.

**Decision:** For USGS basins, attempt NLDI/NWIS site coordinates first when outlet auditing. Fall back to `snap_diagnostic.outlet_raw` only when NLDI lookup is unavailable or the basin is not a USGS site. Persist the gauge source in the audit artifact.

**Alternatives considered:**

- Always require explicit `--gauge-lon/--gauge-lat` — rejected because it creates avoidable manual work for common USGS use cases.
- Use only `snap_diagnostic.outlet_raw` — rejected because it reflects the model's current snapped outlet, not the physical gauge.
- Use model-selected outlet coordinates as the gauge proxy — rejected because that reproduces the outlet-drift problem we are trying to avoid.

**Consequences:**

- USGS outlet audits become easier to run and more reproducible.
- The audit artifact now distinguishes physical gauge geometry from model-selected evaluation outlets.
- Non-USGS or offline runs still work, but with explicit fallback provenance.

---

## ADR-041: Persist Basin Authority in Locked-Benchmark Artifacts

**Status:** Accepted — 2026-04-29.

**Context:** The hydrofabric-first pivot is only scientifically useful if the benchmark lock itself records which basin authority was used. Otherwise the calibration artifacts can drift back into the older habit of treating the model-selected outlet as if it were the physical ground truth.

**Decision:** Extend `BenchmarkLock` and its persisted `benchmark_lock.json` artifact with explicit basin-authority provenance fields: `basin_authority`, `gauge_source`, optional gauge coordinates, and resolver notes. Resolve that provenance during benchmark lock creation and persist it alongside the baseline metrics.

**Alternatives considered:**

- Keep authority only in outlet-audit artifacts — rejected because locked calibration and verification need the same provenance context.
- Infer authority later from the audit — rejected because the lock should be self-contained and reproducible on its own.
- Store only a free-text note — rejected because downstream tooling needs structured fields.

**Consequences:**

- Benchmark locks now pin the same provenance tier used by outlet auditing.
- Readiness tables and calibration verification can display the authority context without reparsing audit logs.
- Existing lock fixtures must be updated to include the new provenance fields.

---

## ADR-042: Persist Basin Construction Plan in Watershed Artifacts

**Status:** Accepted — 2026-04-29.

**Context:** The hydrofabric strategy needs to be basin-construction-aware, not just outlet-audit-aware. If the watershed artifacts do not record which authority tier was chosen, later topology and calibration reports cannot distinguish hydrofabric-first construction from DEM-first fallback.

**Decision:** Resolve a typed basin construction plan during delineation and persist it into the watershed artifacts (`watershed_result.json` and `snap_diagnostic.json`). Surface the same plan in the basin topology report so downstream audit and calibration steps can see the chosen basin authority, source, outlet authority, subbasin authority, and DEM role.

**Alternatives considered:**

- Leave basin authority implicit in the Whitebox configuration — rejected because later reports would have to infer the decision from side effects.
- Store the plan only in documentation — rejected because the plan needs to travel with the run artifacts.
- Make hydrofabric-first mandatory for every basin — rejected because global runs must still support DEM-first fallback.

**Consequences:**

- Watershed runs become self-describing with respect to basin construction authority.
- Basin reports can explain why a run is hydrofabric-first or DEM-first without guessing.
- The strategy is now operational at the basin-construction layer, not only at outlet provenance.

---

## ADR-043: Make Legacy Stream-Threshold Default Authority-Aware

**Status:** Accepted — 2026-04-29.

**Context:** The legacy delineation default (`stream_threshold_cells=500`) is too fine for many large USGS basins and can silently produce impractical over-discretization. We needed a way to improve defaults for hydrofabric-first basins without breaking users who explicitly set thresholds.

**Decision:** Keep explicit thresholds authoritative, but reinterpret only the legacy default value (`500`) as an authority-aware adaptive default when:
- basin authority is `hydrofabric_first`, and
- expected basin area is available.

In that case, derive threshold cells from the existing percent-area policy (`2%` of basin area at DEM resolution). For DEM-first basins or missing expected area, keep the legacy behavior.

**Alternatives considered:**

- Change the global default threshold for all basins — rejected because it would silently alter DEM-first workflows.
- Always override user thresholds — rejected because explicit caller intent must win.
- Keep fixed default and rely only on documentation — rejected because the problematic behavior was already observable in real basin runs.



## ADR-044 — LTE hru_lte → channel transfer scale correction (0.01 frac in hru-lte.con)

**Status:** Accepted — 2026-05-06.

**Context.** SWAT+ v2023.60.5.7 was found to produce exactly 100× too much
channel inflow volume from HRU-LTE water yield in the 01654000 (Accotink
Creek, VA) basin. The engine computes:

```
channel_inflow_m3 = water_yield_mm * 1000 * area_ha  (buggy)
```

instead of the correct:

```
channel_inflow_m3 = water_yield_mm * 10 * area_ha    (correct)
```

The ×100 factor (1000 ÷ 10) is consistent across all 40 channels (ratio
min=99.99995, max=100.00005, mean=100.00000). The bug causes simulated
mean discharge ~214 m³/s vs observed ~0.89 m³/s.

**Considered options.**

1. **Post-hoc divide channel_sd_day by 100 in evaluation.** Rejected:
   the engine would still route 100× too much water through channels,
   corrupting sediment, routing attenuation, and channel hydraulics.
2. **Modify hru-lte.hru area by 0.01.** Rejected: HRU water balance
   output would be wrong, and weather assignment might be affected.
3. **Modify hru-lte.con frac from 1.00 to 0.01.** Chosen: cancels the
   engine bug without affecting HRU water balance computation.

**Decision.** Apply `frac=0.01` to all rows in `hru-lte.con` before
engine execution via `SWATPLUS_LTE_HRU_CHANNEL_SCALE_CORRECTION=0.01`
environment variable (default: 0.01). The correction is logged in
`metadata.json` with `lte_hru_channel_scale_correction` and
`lte_hru_channel_scale_correction_reason` fields.

**Evidence.** After correction on 01654000:
- HRU water yield → channel inflow ratio: 1.000 (was 100.0)
- Basin water yield → outlet outflow ratio: 1.000 (was 93.6)
- Simulated mean discharge: 2.14 m³/s (was 213.95; obs 0.89)
- NSE: -4.7 (was -81,729)

The remaining 2.4× overestimation is consistent with an uncalibrated
model (CN2=98, no calibration parameters tuned).

**Auto-detection.** `mass_trace.py` now detects the bug: if
`channel_inflow_m3 / hru_wateryld_m3 ≈ 100` (±5%), the report flags
`fail_lte_transfer_scale` with a diagnostic note recommending the
correction.

**Consequences.**

- Every LTE run now applies the correction by default. Non-LTE runs
  are unaffected.
- The correction is reversible: set `SWATPLUS_LTE_HRU_CHANNEL_SCALE_CORRECTION=1.0`
  to disable.
- This is a workaround for an engine bug, not a model calibration.
  Evidence has been packaged for upstream SWAT+ bug reporting.
- If upstream fixes the engine, remove the correction and bump the
  minimum required engine version.

**Consequences:**

- Hydrofabric-first runs get safer out-of-the-box discretization when users do not explicitly tune thresholds.
- Existing scripts that pass non-default thresholds keep identical behavior.
- The chosen threshold source is now traceable in artifacts (`stream_threshold_source`).

---

## DG-C3 — publication_grade tier: sensitivity_screen + soil_fidelity gates graduate to research_grade preconditions (2026-06-13)

**Context.** Prior to C3, `_effective_claim_tier` returned `"diagnostic"` whenever
calibration and metric gates passed but the basin-specific sensitivity screen
(`sensitivity_screen_basis=basin_specific`) or soil fidelity gate failed. The
`publication_grade` tier existed in the constants but was unused in practice.

**Decision.** A run that clears all *process* gates (fresh engine, benchmark lock,
outlet provenance, physical, routing, terminal scope) AND the *calibration evidence*
gates (calibration_success, research metrics, calibration improvement) earns
`publication_grade` by default.  Advancing from `publication_grade` to
`research_grade` additionally requires:

1. **Basin-specific sensitivity screen** (`sensitivity_screen_basis=basin_specific`)
   covering all current governed core parameters.
2. **Soil fidelity** (`soil_mode=high_fidelity`, `pct_fallback_soils=0.0`,
   authoritative provenance `gnatsgo_raster`).

Both requirements are enforced in `_effective_claim_tier()` in
`src/swatplus_builder/workflows/usgs_e2e.py`.

**Rationale.** Sensitivity screen and soil provenance are reproducibility and
physical-realism preconditions, not model-skill metrics.  Separating them from the
`publication_grade` level makes the tier hierarchy interpretable:
- `exploratory`: pipeline executed; process gates not fully cleared.
- `diagnostic`: process gates cleared; calibration not yet verified.
- `publication_grade`: calibration verified + skill metrics met; reproducibility
  preconditions pending.
- `research_grade`: full stack — calibration, skill, sensitivity, soil fidelity.

**Untouchable thresholds (locked until after A2 positive control).**
KGE ≥ 0.40, |PBIAS| ≤ 30 %, NSE ≥ 0.0 (or documented timing limitation with
KGE ≥ 0.40).  No threshold may be weakened without a positive-control run
demonstrating that the current thresholds are miscalibrated rather than correctly
blocking a weak model.

**Consequences.**
- Basins that pass calibration/metric gates but lack soil/sensitivity data will
  now report `publication_grade` instead of `diagnostic`.
- The current 11-basin suite is unaffected (all basins fail earlier process gates
  and never reach the calibration check).
- `CLAIM_TIERS` in `swatplus_builder.governance.tiers` already includes
  `publication_grade`; no schema change required.
