# Changelog

All notable changes to swatplus-builder are documented here.

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
