# Changelog

All notable changes to swatplus-builder are documented here.

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
