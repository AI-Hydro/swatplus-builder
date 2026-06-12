# The agent contract

When an AI agent operates swatplus-builder, it works under an explicit
division of authority. This contract is what makes agent-operated runs
trustworthy: the agent's capabilities are real, but bounded.

## What the agent may do

The agent **operates**:

- negotiate a contract (task, scope, requested claim tier);
- call typed tools to build, run, calibrate, and verify;
- read diagnostics and decide what to try next;
- rerun and iterate;
- **summarize from the evidence bundle**.

## What the agent may not do

The package **governs**:

- it builds, evaluates, and verifies;
- it runs gates and records pass/fail with artifacts;
- it **decides the claim tier** from evidence;
- it blocks or downgrades a claim with a typed reason;
- it writes the evidence bundle.

The agent cannot grant itself a tier, edit a gate result, or report a candidate
metric as a verified one. Those are not exposed as actions.

## The reporting rule

!!! quote ""
    Summaries must come from the **evidence bundle**, not from terminal text.
    Reporting a metric without disclosing a failed gate is overclaiming.

A correct agent summary reads `evidence_summary.json`, reports `allowed_claims`
*and* `blocked_claims`, and cites verified metrics only. An agent that scrapes
the highest NSE it saw scroll past in the logs is doing exactly what the
governance layer exists to prevent.

## Why a contract, not just a prompt

A prompt is advisory; a contract is checkable. The negotiated
`workflow_contract.json` records the requested tier and the policy
preconditions, validated *before* compute is spent. That gives both the agent
and a human reviewer a machine-readable statement of what this run was supposed
to establish — which the final evidence bundle can then be checked against.

## Read next

- [MCP server](mcp-server.md) — start and register the server
- [Tool surface](tool-surface.md) — the 13 tools that form the boundary
- [Claim governance](../concepts/claim-governance.md) — how tiers are decided
