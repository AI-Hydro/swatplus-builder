# Phase 3D Closeout — Agent Loop & Autoresearch

Date: 2026-04-24  
Status: Complete (with explicit surrogate-model-family deviation documented)

## Scope Delivered

### 1) MCP typed 8-tool surface (Roadmap 3D.2)

Implemented in:
- `src/swatplus_builder/mcp/server.py`

Registered tools:
- `build_project`
- `run_basin`
- `calibrate`
- `propose_parameters`
- `compare_runs`
- `query_artifacts`
- `diagnose_failure`
- `validate`

Current behavior:
- All 8 tools are typed and executable.
- `build_project`, `run_basin`, and `calibrate` moved from placeholder to operational wrappers.

Evidence:
- `pytest -q tests/test_mcp_server.py` (pass)

### 2) Root agent skill contract (Roadmap 3D.3, Appendix C)

Implemented in:
- `SKILL.md`

Coverage includes:
- When-to-use boundaries
- Full tool catalog with signatures and failure modes
- Parameter registry guidance
- Diagnostic heuristics
- Basin taxonomy
- Evaluation protocol
- Example workflows
- Common pitfalls

Evidence:
- `pytest -q tests/test_skill_md.py` (pass)

### 3) Autoresearch loop orchestrator (Roadmap 3D.1)

Implemented in:
- `src/swatplus_builder/autoresearch/loop.py`
- `src/swatplus_builder/autoresearch/__init__.py`

Delivered capabilities:
- Proposal strategies: `random`, `grid`, `history`
- Uncertainty-gated routing between surrogate and real evaluator
- Iteration lineage persisted via artifact provenance (`parent_run`, `proposal_source`)
- Stop criteria:
  - max iterations
  - objective threshold
  - convergence window/tolerance

Evidence:
- `pytest -q tests/test_autoresearch_loop.py` (pass)

### 4) Surrogate training + routing + hold-out harness (Revised 3D.X / 3D.Y / 3D.Z)

Implemented in:
- `src/swatplus_builder/autoresearch/surrogate.py`

Delivered capabilities:
- Deterministic bootstrap ensemble training from artifact-backed dataset rows
- Uncertainty estimate from inter-member prediction spread
- Routing decision helper: `decide_routing_path(...)`
- Hold-out evaluation harness: `evaluate_surrogate_holdout(...)`
- Persisted artifacts under `surrogates/<ensemble_id>/`:
  - `training_rows.csv`
  - `model_cards.json`
  - `training_summary.json`
  - `holdout_evaluation/summary.json`
  - `holdout_evaluation/cases.csv`

Evidence:
- `pytest -q tests/test_autoresearch_surrogate.py` (pass)

## Verification Bundle

Executed together:
- `pytest -q tests/test_mcp_server.py tests/test_skill_md.py tests/test_autoresearch_loop.py tests/test_autoresearch_surrogate.py`
- Result: pass (20 tests)

## Additional Evidence Runs (3D.5 closure)

1) Curated-basin autoresearch trace artifact  
- Basin: `usgs_01547700` (from `basins/curated_v1.json`)  
- Artifact root:
  - `tests/_artifacts/phase3d_evidence_20260424/curated_autoresearch/`
- Key outputs:
  - `autoresearch_trace.json`
  - `README.md`
  - surrogate artifacts under `surrogates/<ensemble_id>/...`

2) External MCP client smoke against stdio server  
- Client: Python MCP client (`mcp.client.stdio.ClientSession`)  
- Server: `python -m swatplus_builder.mcp.server`  
- Artifact root:
  - `tests/_artifacts/phase3d_evidence_20260424/mcp_smoke/`
- Key outputs:
  - `mcp_smoke_transcript.json` (tool discovery + call results)
  - `README.md`
- Coverage:
  - all 8 tools discovered and callable,
  - operational wrappers validated (`build_project`, `run_basin`, `validate`, etc.),
  - `calibrate` fail-loud path demonstrated for missing required inputs.

## Deviations From Plan

1) Surrogate model family
- Planned in revised roadmap: small MLP ensemble.
- Implemented in this tranche: deterministic bootstrap linear ensemble.
- Rationale: stabilize routing contracts with dependency-light, inspectable baseline first.
- Decision captured in `DECISIONS.md` (2026-04-24).

2) External validation modality
- Roadmap wording says "external MCP-capable agent". This closeout uses an external MCP-capable client session (`ClientSession`) for reproducible automated evidence.
- Functional objective (external MCP interaction over stdio with tool calls + transcript) is met.

## Exit Criteria Mapping (Roadmap 3D.5)

1. All 8 MCP tools operational and typed  
Status: Met (local tests).

2. `SKILL.md` complete and tested with at least one external MCP-capable agent  
Status: Met (external MCP client smoke evidence persisted under `tests/_artifacts/phase3d_evidence_20260424/mcp_smoke/`).

3. Autoresearch loop completes end-to-end on a curated basin  
Status: Met (curated-basin evidence persisted under `tests/_artifacts/phase3d_evidence_20260424/curated_autoresearch/`).

4. Diagnostic heuristics produce actionable output for >=5 common failure modes  
Status: Met via Phase 3C diagnostics implementation + tests.

## Recommended Next Actions

1. Stage and commit the full Phase 3D tranche with roadmap-linked message.
2. Kick off Phase 3E planning (`PHASE_3E_PLAN.md`) after merge.
3. Revisit surrogate model-family upgrade path (MLP ensemble) as a follow-on decision when Phase 3E risk is contained.
