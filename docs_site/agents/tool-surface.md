# Tool surface

The MCP server exposes **13 typed tools** in three tiers. The names below are
the exact tool names registered in `src/swatplus_builder/mcp/server.py`.

## Tier 0 — Canonical governed workflow (2 tools)

This is the entry point for "model gauge X". It is the only MCP path that
produces a claim-governed evidence bundle.

| Tool | Purpose |
|---|---|
| `run_workflow` | launch the canonical workflow (build → run → lock → calibrate → verify → evidence bundle) for a USGS gauge ID as a detached background process; returns immediately with `out_dir`, `pid`, and the `equivalent_cli` string for reproducibility |
| `workflow_status` | poll a launch: `running` / `completed` / `failed`, with `evidence_summary_path` and blocker class once finished |

A full run takes tens of minutes — the background launch keeps the MCP call
fast, and the agent polls `workflow_status` between other work. On completion,
summarize **only** from the evidence bundle.

## Tier 1 — Basin workflow (8 tools)

| Tool | Purpose |
|---|---|
| `build_project` | validate a basin spec and write a build manifest (does **not** build a runnable project — use `run_workflow`) |
| `run_basin` | run the lower-level pipeline orchestrator (no evidence bundle — prefer `run_workflow`) |
| `calibrate` | standalone pySWATPlus-bridge calibration (non-authoritative path) |
| `propose_parameters` | suggest calibration parameters for a basin |
| `compare_runs` | compare metrics across runs |
| `query_artifacts` | look up artifacts from a run directory |
| `diagnose_failure` | structured diagnosis of a failed run |
| `validate` | validate a project / run against expectations |

## Tier 2 — Benchmark / readiness (3 tools)

| Tool | Purpose |
|---|---|
| `lock_benchmark` | seal a baseline with hashes (start of the locked protocol) |
| `locked_calibrate` | calibrate against a lock and verify |
| `readiness_table` | summarize lock/calibration/verification across basins |

## How tools enforce governance

The tools are deliberately *typed and narrow*. An agent cannot reach past them
to, say, hand-edit a metric into the evidence bundle or promote a claim tier.
Claim tiers are emitted by the package from gate results; the tools expose the
operations (build, run, calibrate, verify, query) but not the authority to
override an evidence-backed decision.

This is the mechanism behind [the agent contract](agent-contract.md): the
surface is the boundary. What is not a tool is not an action the agent can
take.

## Read next

- [The agent contract](agent-contract.md) — the rules the surface enforces
- [CLI reference](../reference/cli.md) — the equivalent command-line surface
