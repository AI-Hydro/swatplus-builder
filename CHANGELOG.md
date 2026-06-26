# Changelog

All notable changes to swatplus-builder are documented here.

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
