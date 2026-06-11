# Package as authority, agent as operator

The defining design decision in swatplus-builder is *where scientific authority
lives*. In most agent-driven tooling, the agent runs scripts and then reports
whatever the scripts printed. That is exactly the failure mode this project
exists to prevent.

## The problem: fast execution is not scientific success

A SWAT+ study is a chain of scientific decisions — outlet selection, stream
thresholds, HRU definition, soil sourcing, weather forcing, calibration scope,
metric interpretation. An AI agent can execute that chain in minutes. It can
also **overclaim** in minutes:

- report an optimizer's best-ever objective as the model's skill;
- present a metric computed on stale outputs from a previous run;
- omit that soils were a low-fidelity fallback;
- declare success because a script exited `0`.

None of these are hallucinations in the usual sense. They are *unsupported
claims that look supported*. The model knows the hydrology; what it lacks is an
environment that will not let it say more than the evidence allows.

## The principle

!!! quote ""
    **The package is the scientific authority. The agent is the operator.**

Concretely, responsibilities are split so that the agent cannot grant itself a
claim:

| The agent **operates** | The package **governs** |
|---|---|
| negotiates a contract | validates the contract against policy |
| calls typed tools | builds, evaluates, verifies |
| reads diagnostics | runs gates and records pass/fail with artifacts |
| reruns and iterates | **decides the claim tier** and writes the evidence bundle |
| summarizes from the bundle | blocks / downgrades with a typed reason |

Every feature in the package is tested against one sentence: *does this
constrain what may be claimed, with evidence an operator cannot fake?*

## Why this matters for AI-operated science

The same property that makes the package safe for an AI agent makes it
**auditable for a human reviewer**. Because claim tiers are emitted by code
from gate results and provenance — not asserted in prose — a reviewer can:

1. open `evidence_summary.json`;
2. read the `allowed_claims` and `blocked_claims`;
3. follow each claim's artifact pointer to the evidence that justifies it;
4. recompute the tier from the gate table.

The contribution is not "an AI that calibrates SWAT+." It is a **claim-governed
workflow** in which the difference between *a model ran* and *a result may be
claimed* is enforced at runtime and recorded in machine-readable form.

## Read next

- [Claim governance & tiers](claim-governance.md) — how gates map to a tier
- [Locked calibration protocol](locked-calibration.md) — why metrics come from
  an independent rerun
- [Six invariants](invariants.md) — the part that generalizes beyond hydrology
