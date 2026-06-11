# Tool surface

The MCP server exposes **11 typed tools** in two tiers. The names below are the
exact tool names registered in `src/swatplus_builder/mcp/server.py`.

## Tier 1 — Basin workflow (8 tools)

| Tool | Purpose |
|---|---|
| `build_project` | build a SWAT+ `TxtInOut` from inputs |
| `run_basin` | run the SWAT+ engine on a project |
| `calibrate` | run calibration (locked-benchmark protocol) |
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
