# Changelog

All notable changes to swatplus-builder are documented here.

## [Unreleased]

### Fixed
- `output/metrics.py`: added `log_kge_v2`, a scale-aware replacement for the
  calibration phase objective's low-flow term. `log_kge` (kept unchanged)
  adds a *fixed* 0.01 m^3/s epsilon before the log transform; a headwater
  stream and a large river share that one constant, and a synthetic 7-value
  probe showed the score swinging from -0.2551 to +0.91 under a pure
  m^3/s -> L/s relabeling of the same data while raw KGE stayed at 0.9182
  (`docs/AGENT_HANDOFF.md` §7; Santos, Thirel & Perrin 2018). `log_kge_v2`
  sizes epsilon to 1% of each basin's own mean observed flow instead
  (Pushpalatha et al. 2012's convention). `calibration/locked_benchmark.py`'s
  phase score now prefers `log_kge_v2` when present, falling back to legacy
  `log_kge` only for metrics recorded before this change, so old runs'
  objective values stay reproducible. `evaluate_run` now records both keys.
  This does not eliminate the inherent numerical instability of log-
  transformed metrics on very small, low-flow-dominated samples — see
  `log_kge_v2`'s docstring — and it blocks generating decision-model
  training labels from `phase_decisions.json` until this landed.

### Added
- Decision-model data pipeline (`docs/DECISION_DATA_PIPELINE.md`):
  - Calibration phases write `phase_decisions.json` with each phase's full
    candidate set (metrics, gate results, phase score) and the candidate it
    promoted; the workflow records one `calibration_phase:<phase>` ledger
    decision per phase with every candidate's outcome attached.
  - Fault injection (`swat fault list|inject|effect`,
    `swatplus_builder.decision_data.faults`): documented forcing and parameter
    faults applied to a copied TxtInOut with a hash-pinned
    `fault_manifest.json` and a hidden `latent_fault_family` label; injections
    that change no file or fail midway leave nothing behind, and
    `fault_effect` flags faults that changed no simulated hydrology.
  - `serialize_state` (version `state-v1`): deterministic, priority-ordered,
    character-budgeted state text that refuses hidden-label keys.
  - `swat audit typed`: compiles DecisionEpisodes into typed-decision (Choice)
    items with bounded option sets, hard or softmax targets, fault-diagnosis
    items for injected runs, and basin-disjoint splits.
  - Episodes from fault-injected runs carry `source: injected_fault` and a
    separate `latent_fault` field; the manifest is bound into `events.jsonl`
    by hash.
- Tamper-evident audit trail for the canonical workflow. `events.jsonl` is now a
  SHA-256 hash-chained ledger (additive `seq`/`prev_sha256`/`sha256` fields),
  and a new `decisions.jsonl` records each governed decision point
  (`claim_tier_contract`, `calibration_precheck`, `effective_claim_tier`) as
  state → options → chosen → outcome, with the deciding policy. Both ledger
  heads are sealed into `run_manifest.json` (`audit_ledgers`), and the final
  evidence files are hashed into the chain (`evidence_sealed` event).
- Each run records an environment fingerprint (package version, git SHA,
  engine path/SHA-256/revision, key dependency versions).
- `swat audit verify <run_dir>` checks both ledgers against the sealed heads;
  `swat audit episodes <run_dir>...` exports decisions joined with outcomes as
  model-agnostic `DecisionEpisode` JSONL for decision-model data preparation.
- Re-running a workflow in the same directory archives the previous attempt's
  ledgers under `audit_history/` instead of deleting them.

### Fixed
- The package (including `swat workflow run`) failed to import on Python 3.10,
  its declared minimum, because eight modules imported `datetime.UTC` (3.11+).
- Fresh `[mcp]` installs resolved `mcp` 2.x, which removed `FastMCP`; the extra
  is now pinned to `mcp>=1.2,<2`.
- `requests` (used by the SDA and SoilGrids soil clients on the real build
  path) is now a declared dependency.
- MCP `locked_calibrate` no longer swallows independent-verification failures;
  it reports `verification_status` (`verified` | `skipped` | `failed`) and the
  error, and refuses a caller-supplied `binary` path unless the server opts in
  with `SWATPLUS_BUILDER_MCP_ALLOW_BINARY_OVERRIDE=1`.
- Calibration candidates delete a copied `basin_wb_aa.txt` before the engine
  run, so the candidate water-balance gate can never judge the base run's file.
- An unrecognized requested claim tier (e.g. a typo) now falls back to
  `diagnostic` with an explicit policy note instead of passing through.
- `swat health` now resolves the engine the same way runs do, so an engine
  installed with `swat setup engine` is reported as available.
- The editor ORM schema-drift smoke test pointed at a non-existent path and was
  always skipped; it now runs.
- Outlet choice: when several terminal channels exist, the requested outlet is
  now the terminal draining the largest upstream network
  (`primary_terminal_channel_id`, topology only) instead of the lowest GIS ID.
  Benchmark-lock pass 1 accepts `outlet_selection_period`; the canonical
  workflow passes its calibration window so withheld validation years never
  influence outlet auto-selection. The window is recorded in
  `outlet_provenance.json`.
- `evaluate_run` no longer mutates the caller's observed series, and a metric
  failure is recorded as `metric_computation_error` instead of silently
  dropping metric keys.
- `build_readiness_table` reports unreadable or tampered lock/verification
  files as `unreadable_artifact` rows instead of skipping them.
- The vendored SWAT+ Editor is pinned (`.VENDORED_COMMIT`, upstream `v3.2.0`,
  content-verified; `VENDORED_EDITOR_VERSION` corrected from 3.2.2) with its one
  local patch documented in `VENDORED_PATCHES.md`; unused upstream files
  (REST server, `get-pip.py`, build scripts) are no longer shipped in the wheel.
- SDA mukeys are integer-coerced before being written into SQL.
- `scripts/audit_production_objective.py` parses arguments (`--out-dir`);
  `--help` no longer runs the audit.

### Security
- Optional MCP workspace sandbox: with `SWATPLUS_BUILDER_MCP_WORKSPACE=<dir>`
  every path argument must resolve inside `<dir>` (symlinks resolved), and
  SWAT+ output-file-name arguments must be bare file names.

### CI
- New `offline-test-suite` job runs the full offline test suite on Python
  3.10–3.12 with all runtime extras; `ruff` is pinned (0.16.9) and the
  pre-existing lint findings are fixed.

### Docs
- `QUICKSTART.md`: building the engine from source with gfortran (upstream
  Release flags trap FP underflow and crash on real inputs), and the MCP
  hardening environment variables.
- `docs/AGENT_HANDOFF.md`: project state, what's done vs. not, and how to
  sync a local checkout that's behind `origin/main`, for a new agent or
  contributor picking up the project.
- `scripts/setup_local_env.sh`: idempotent local dev environment bootstrap
  (venv + editable install, reference DBs, engine build from source, health
  check).

## [0.7.14] — 2026-09-20

### Scientific validity and evidence integrity

- Observation-conditioned subsurface preparation now uses only the declared
  calibration interval, including year-matched model water-balance diagnostics;
  nominal validation observations and validation-year diagnostics cannot alter
  the prepared parameters.
- GridMET forcing now requires the exact requested daily calendar, finite raw
  values, physical ranges, valid minimum/maximum ordering, and a provider client
  with bounded connection-timeout support. Known GridMET no-leap 31 December
  omissions are separately recorded as calendar normalization; other repaired
  gaps remain imputation and block the research-grade weather-fidelity claim.
- Calibration improvement is recomputed from designated baseline and locked
  verification metrics. Timing exceptions require a typed, checksummed
  supporting diagnostic artifact.
- Engine execution receipts bind output hashes to the exact input configuration,
  executable digest, thread count and timeout policy. Post-run input mutation
  invalidates freshness evidence, while derived alignment tables are excluded
  from the static model-input fingerprint.

### Security and reliability
- Claim gates reject NaN/infinity and verify benchmark hashes, model input
  identity, outlet provenance, and fresh-output execution receipts. Both solver
  entry points clear stale receipt-covered outputs; failed clean runs leave no
  valid receipt.
- MCP workflows use unique, exclusively owned empty directories and a detached
  supervisor that persists exit status and reaps children. Reusing an output
  directory now fails before logs can be truncated.
- Artifact IDs must be lowercase SHA-256 digests. Records are staged, checksummed,
  and published atomically; published IDs are immutable and cannot be overwritten.
  Historical records without manifests are not reused by the store. Preserve
  them as historical evidence and use a fresh artifact root for new work.
- Validation caches only explicit successful executions under a new cache
  namespace; failed executions are retried rather than counted as cached success.
- Release uploads depend on the same offline installed-wheel contract tests used
  by CI. Linux SWAT+/WhiteboxTools executables and binary caches are checked
  against repository-pinned SHA-256 digests before execution.
- The optional MCP dependency is constrained to `<2` because this package uses
  the v1 FastMCP API.
- Bundled legacy SWAT+ Editor entry points no longer invoke a user-supplied
  executable through a shell or expose the Flask debugger/tracebacks. A
  high-severity Bandit scan is clean after these changes.

### Improved
- Emit per-station GridMET progress events through canonical workflow runs and
  bound provider retry behavior with validated timeout/attempt settings.
- Reuse GridMET forcing for stations that resolve to the same native provider
  cell, reducing network/cache work while preserving SWAT+ station metadata.
- Record weather station coordinates and provider-client versions in run
  metadata, and expose bound-level calibration sensitivity progress.
- Independent locked sensitivity-bound evaluations now run through a bounded
  worker pool (`--sensitivity-workers`, default `4`) while each SWAT+ worker
  remains single-threaded. Candidate search, locked verification, and withheld
  transfer evaluation remain serial and fresh.
- Sensitivity-derived, fixed phase anchors now run through a separate bounded
  worker pool (`--anchor-workers`, default `4`). The workflow writes a hashed
  `diagnostic_warm_start.json` artifact, explicitly marked exploratory; it
  cannot authorize final metrics or claims.
- Interrupted sensitivity and adaptive-search runs can reuse exact compact
  objective traces only when a tamper-evident signature matches the sealed
  benchmark/input identity, scoring window, engine binary, and calibration
  implementation. Final verification and withheld validation never use this
  cache.

## [0.7.13] — 2026-07-10

### Fixed
- Benchmark locks now seal the static TxtInOut configuration in addition to
  alignment, metrics, and outlet-provenance hashes. New artifact-backed
  calibration, sensitivity, and verification paths fail closed when a sealed
  input or benchmark artifact has drifted; historical unsealed locks require a
  fresh relock before reuse for calibration.
- The canonical workflow now passes its recorded chronological 60/40 split into
  calibration. Candidate search excludes the held-out period and evaluates the
  selected solution against that period using the physical gate. Fresh locked
  reruns remain reproducibility checks, not a substitute for temporal transfer.
- Schema-versioned `evidence_v1.json` is now a required final artifact. A
  schema write failure fails the workflow rather than silently leaving a
  legacy-only evidence bundle.
- The generic hydrologic figure suite now accepts sealed final alignment and
  verification-metric overrides. A successful locked calibration renders
  calibrated hydrograph/FDC/scatter/residual/seasonal figures and labels them
  accordingly; an absent explicit final alignment fails figure regeneration
  rather than falling back to stale baseline plots.
- Verified-but-blocked calibrations now use the same final verified figure
  source, visibly labeled `claim blocked`, so diagnostic improvement is shown
  without implying a promoted claim.

## [0.7.12] — 2026-07-03

### Fixed
- Dashboard metric authority now prefers verified locked-calibration metrics
  when calibration verification exists, while retaining benchmark BFI labels
  when BFI comes from the baseline lock.
- Workflow plot regeneration now refreshes the full plot suite after benchmark
  lock/calibration evidence is available, reducing stale hydrograph/dashboard
  artifacts.
- Routing-flow diagnostics now attach terminal-inventory and terminal-area
  context for any non-passing routing-flow case, including single-terminal
  basins whose outlet scope is valid but whose SWAT+ channel-rate versus
  basin-yield semantics still need investigation.
- Full-overlay land-use fidelity gates now account for mapped area retention,
  so tiny missing classes are disclosed without falsely blocking otherwise
  area-complete HRU overlays.

### Evidence
- Fresh calibrated full-overlay validation on `01547700` completed with
  `effective_claim_tier=diagnostic`; locked calibrated verification improved
  KGE and volume behavior while disclosing the NSE decrease.
- Fresh calibrated full-overlay validation on `03349000` completed with
  calibration attempted and independently verified, but final claims were
  downgraded to `exploratory` because physical and routing-flow gates still
  failed. This release preserves that downgrade rather than promoting the
  improved metrics.

## [0.7.11] — 2026-07-02

### Fixed
- Workflow evidence now records the full generated plot suite instead of
  overwriting plot metadata with only the spatial/context subset.
- Plot metadata now names the log hydrograph consistently as
  `fig_01_hydrograph_log`.
- Basin spatial-overview rendering downsamples large rasters for diagnostic
  display, avoiding multi-GB memory spikes while leaving model artifacts
  unchanged.
- Objective-suite reporting no longer treats status strings such as `pass` as
  blockers. `fail_mass_closure` is classified as a diagnostics blocker and
  `landuse_fidelity` as a provenance/input-fidelity blocker.

### Evidence
- Completed seven current-code no-calibration reruns for the stale objective
  rows under `/Users/mgalib/swatplus_runs/objective_refresh_v0710/`.
- Regenerated the objective summary from current evidence. The canonical status
  remains `0/11` research-grade outcomes, with blocker domains
  `science=9`, `diagnostics=1`, `provenance=1`, and no unclassified blockers.

## [0.7.10] — 2026-07-01

### Fixed
- Locked calibration history now classifies candidates with non-finite required
  objective metrics as `invalid_objective_metrics` and records a
  `failure_reason`, instead of leaving ambiguous `NaN` rows that look like
  ordinary evaluated candidates.

### Evidence
- Fresh current-code diagnostic runs for `01013500` and `03351500` completed
  build, engine execution, benchmark lock, routing-flow checks, dashboards, and
  plot generation. Both replaced stale objective-suite full-build-failed rows
  with current exploratory evidence.
- A small locked-calibration smoke on `01013500` showed no verified
  improvement over baseline and exposed the ambiguous non-finite candidate
  history rows fixed in this release.

## [0.7.9] — 2026-07-01

### Fixed
- Add `matplotlib` to the default package dependencies. The released `0.7.8`
  wheel imported successfully, but `swat workflow negotiate` failed in a clean
  environment because workflow imports load plotting/dashboard modules that
  require Matplotlib.

### Evidence
- Clean PyPI install smoke for `0.7.8` reproduced the missing dependency:
  `ModuleNotFoundError: No module named 'matplotlib'`.

## [0.7.8] — 2026-06-26

### Fixed
- Diagnostic calibration now evaluates sensitivity-guided anchor combinations
  before DDS, avoiding false volume-gate blocks when complementary parameter
  moves pass together but fail one-at-a-time.
- Standalone `run_diagnostic_calibration()` now syncs root
  `calibration_provenance.json`, so debug reruns do not leave stale failed
  provenance beside successful report artifacts.

### Added
- Calibration heartbeat/progress evidence for screening, searching,
  verification, failed, blocked, and complete states.
- Dashboard evidence for calibration method, progress, best solution, history,
  calibrated alignment, and spatial basin overview context.

### Evidence
- `03349000_2010_2018_diag` now completes diagnostic calibration with locked
  verification (`NSE=-0.149`, `KGE=0.475`, `PBIAS=15.51%`), while retaining
  weak absolute skill honestly.
- `01031500_2010_2018_nocal` was recalibrated diagnostically after the earlier
  no-calibration run; it is now classified as attempted-but-blocked by
  calibration process gates, dominated by mass-imbalance evidence.

## [0.7.1] — 2026-06-17

### Added
- Land-use fidelity evidence and claim gating: workflow evidence now records
  source NLCD classes, retained HRU classes, class-retention fraction, NLCD
  vintage selection, and research-grade blockers when dominant-only HRUs
  collapse source land-use diversity.
- Terrain and climate-default disclosure evidence: workflow summaries now
  expose topographic length defaults, lapse settings, DEM relief, weather
  station context, diagnostic flags, and claim impact.
- Diagnostic plot suite additions for spatial overview, forcing context,
  water balance, and HRU/land-use composition.
- Subsurface-prior water-balance correction with guardrails and fresh-engine
  rerun enforcement for humid runoff-deficit cases.

### Fixed
- Declared raster nodata values, including NLCD-style `127`, are masked before
  full-overlay HRU combinations are emitted.
- Timestamped observed-flow CSV rows are preserved when normalized to dates,
  avoiding all-NaN observed series after index normalization.
- Objective compliance audit now accepts current build diagnostic artifacts
  when legacy overlay-repair reports are absent, while still requiring every
  referenced artifact path to exist.
- Package version metadata is synchronized between `pyproject.toml`,
  `swatplus_builder.__version__`, README, and citation metadata.

### Evidence
- A clean 20-year `01547700` run (`2000-01-01` to `2019-12-31`) completed build,
  engine execution, benchmark lock, gated calibration, locked verification,
  and plot generation. The package allowed diagnostic/reproducibility claims
  but kept the effective claim tier exploratory because research skill,
  land-use fidelity, and terrain/lapse audit gates still block promotion.

## [0.6.1] — 2026-06-14

### Fixed
- **`build_real_basin.py` missing from installed package** (regression since 0.5.0):
  `full_build._load_example_builder()` resolved the script relative to the repo
  root, which worked in editable installs but failed after `pip install` because
  `examples/` was excluded from the wheel by the sdist allowlist added in 0.5.0.
  The script is now bundled inside the package at
  `swatplus_builder/examples/build_real_basin.py` and the loader tries the
  package-relative path first, falling back to the repo path for editable installs.

## [0.6.0] — 2026-06-14

### Added
- **Governance package** (`swatplus_builder.governance`): 7 pure gate functions
  (`fresh_engine_gate`, `benchmark_lock_gate`, `outlet_provenance_gate`,
  `research_metric_gate`, `soil_fidelity_gate`, `calibration_improvement_gate`,
  `sensitivity_gate`) with zero hydrology imports. `usgs_e2e.py` delegates to
  these via thin wrappers — governance logic is now separable from the SWAT+ domain.
- **Flood-frequency toy domain** (`swatplus_builder.domains.flood_frequency`):
  second-domain reference implementation on the governance core; 4 gates
  (data adequacy, stationarity, distribution fit, return-period CI), own tier
  mapping, and 32 tests. Demonstrates that `swatplus_builder.governance` is
  domain-agnostic.
- **Per-claim tier matrix** (`claim_tier_matrix`): `run_objective_10basin.py`
  now reports a basins × assertion-type matrix (readiness / provenance /
  comparison / metric → highest unblocked tier), replacing the scalar
  `effective_claim_tier` headline.
- **Evidence schema v1** (`schema_version: "1.0"`): Pydantic-owned schema with
  required core fields; `migrate_legacy_bundle()` shim for round-trip
  compatibility.
- **`publication_grade` tier reachable** (C3): `_effective_claim_tier()` now
  returns `publication_grade` when calibration + metric gates pass but
  sensitivity / soil gates fail, instead of collapsing to `diagnostic`.
  Decision documented in `docs/DECISIONS.md` as DG-C3.
- **Audit collapse** (B2): `scripts/audit_production_objective.py` rewritten
  from 5 259 → 449 lines; 97 named per-row checks replaced by 4 generic
  structural invariants (I1–I4).
- **Single-terminal delineation repair** (C1): `_build_topology` now enforces
  a single-gauge → single-terminal invariant; multi-terminal emission raises
  at build time.
- **DDS calibration + split-sample validation** (C4): true Duan Shuffled
  Complex Evolution optimizer replaces the greedy staged grid search; Klemeš
  split-sample validation (calibrate / hold-out) gates claims that fail transfer.

### Fixed
- **GridMET trailing-day gaps**: `_repair_bounded_day_gaps` now correctly
  forward-fills consecutive trailing days (server real-time coverage clip).
  Repair cap raised 3 → 7 days. Fixes `weather_provider_data_gap` errors
  when the requested end date is within GridMET's ~3–5 day real-time lag.
- **GridMET pre-flight lag warning**: `fetch_gridmet` now emits a `WARNING`
  before the network call when `end` is within 7 days of today, naming the
  estimated coverage boundary. When forward-fill fires, a second `WARNING`
  names the station, the last real observation date, and the synthetic day
  count — operators know exactly what happened.
- **`_augment_topology_from_gpkg` NameError**: the disk-fallback path in
  `_build_topology` called this function but it was never defined. The inline
  endpoint-snapping logic is now extracted into the named helper shared by
  both paths.

### Changed
- `tiers.py` now exports `CLAIM_TIERS`, `tier_rank`, `higher_tier`; tier
  ordering: `blocked < exploratory < diagnostic < publication_grade < research_grade`.
- Hygiene (D2+D4): conversational agent-artifact comments removed; "negotiation"
  framing in `workflows/contracts.py` replaced with typed pre-execution contract
  language.

## [0.5.0] — 2026-06-12

### Added
- **`run_workflow` + `workflow_status` MCP tools** (13-tool server): launch the
  governed end-to-end pipeline as a detached background process — immune to MCP
  client timeouts and conda/venv drift — and poll it for evidence-bundle
  pointers. The `build_project` placeholder no longer fake-succeeds silently.
- **Engine version provenance**: every run now reads the SWAT+ revision directly
  from the engine — both the startup banner and the persisted output-file header
  (`MODULAR Rev …`) — and records the verified value in the evidence bundle. If
  an asserted version disagrees with the binary, the workflow records the
  engine's value and flags the mismatch. Version is verified, never operator-asserted.
- **A2 positive-control fixture test**: the claim-governance gate stack
  (`_claim_lists` / `_effective_claim_tier`) is now tested in the *passing*
  direction (synthetic research-grade single-channel basin), not only failing.
- **Overclaiming pilot harness** (`scripts/overclaiming_pilot/`): runner, LLM
  judge, and H1–H4 analysis scaffold for the pre-registered overclaiming experiment.
- **`docs/REPRODUCIBILITY.md`**: documents the external reference-DB dependency
  (esp. `swatplus_wgn.sqlite`) that is required but not bundled — a reproducibility
  caveat for downstream results.

### Fixed
- **Daymet date-range defect**: pydaymet ≥ 0.19 could ignore `dates=()` and
  return the full 1980-present archive. The adapter now clips every response to
  the requested window and fills the Dec-31 rows Daymet omits in leap years;
  validation reports "range ignored" vs "server clamped" as distinct failures.
- **Reference-DB bootstrap honesty**: `scripts/bootstrap_reference_dbs.sh` no
  longer claims to download from a non-existent mirror. It now checks which DBs
  are present and exits non-zero with manual-install instructions if any are missing.
- **MCP health check** improvements; added `mcp-check` command.

### Changed
- Engine version documentation corrected to the **validated range
  60.5.7 – 61.0.2.61** (shipped builds use rev 61.0.2.61), replacing the
  inaccurate single-version claim.

## [0.4.0] — 2026-06-11

### Added
- **Locked calibration protocol**: `lock-benchmark` → `locked-calibrate` → independent verification chain. Reported metrics always come from a clean rerun, never from the optimizer loop.
- **Claim governance**: runtime gates assign each result a tier (`exploratory → diagnostic → research_grade → publication_grade`). A strong metric never self-promotes past a failed gate.
- **Machine-readable evidence bundle**: every run writes `evidence_summary.json`, `run_manifest.json`, `events.jsonl`, `calibration_provenance.json`, `physical_gates.json` — including typed, evidence-backed refusals.
- **11-tool MCP server** (`swat mcp`): full agent interface for building, running, calibrating, and querying results via the Model Context Protocol.
- **Full-mode engine compatibility** (Phase 3L): parameter bridge, routing fixes, topology converter, water-balance gate.
- **New modules**: `nldi_fallback`, ET/mass/volume diagnostics, weather forcing, SoilGrids adapter, Daymet weather, full-build workflow, params governance.
- **`swat workflow run`**: canonical one-command end-to-end path from USGS gauge ID to evidence bundle.
- **Container baseline**: Dockerfile + docker-compose with MCP stdio service.
- **Publication-ready figures**: 7+ figure types including hydro comparison, soil depth, gate matrix.
- **`swat readiness-table`**: multi-basin calibration readiness summary.

### Changed
- `swat watershed`, `swat hrus`, `swat project`, `swat build`: now print a clear redirect to `swat workflow run` instead of crashing with an opaque error.
- `pyproject.toml` description and keywords updated to reflect the package's actual identity.
- Version aligned to `0.4.0` across `pyproject.toml` and `__init__.py`.

### Infrastructure
- MkDocs Material documentation site at <https://ai-hydro.github.io/swatplus-builder/>.
- GitHub Actions: CI (lint + smoke + routing regression), docs deploy, and this publish workflow.

## [0.3.x] — internal development

Phase 3 calibration and engine compatibility work. Not released to PyPI.

## [0.1.0 – 0.2.x] — internal development

Initial pipeline scaffold. Not released to PyPI.
