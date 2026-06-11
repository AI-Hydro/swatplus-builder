# The evidence bundle

Every run writes a **machine-readable evidence bundle** — the durable record of
what happened, what was checked, and what may be claimed. It is the interface
between the package's authority and any consumer (a human reviewer, an audit
script, or another agent).

## Anatomy

| Artifact | What it carries |
|---|---|
| `evidence_summary.json` | the headline: gate results, claim tier vector, **allowed/blocked claims** |
| `run_manifest.json` | inputs, artifact paths, run summary, git SHA |
| `events.jsonl` | append-only, stage-by-stage execution trace |
| `benchmark/benchmark_lock.json` | sealed baseline metrics + observed-vs-modeled alignment |
| `calibration_provenance.json` | candidate → lock → verification authority chain |
| `physical_gates.json` | ET / mass-balance / volume-bias gate decisions |
| `routing_flow_gates.json` | routed-flow mass-closure gate decisions |

## Read `blocked_claims` first

The instinct is to open the file and look for the NSE. Resist it. The most
information-dense field is **`blocked_claims`** — it tells you what the system
refused to assert and why:

```json
{
  "blocked_claims": [
    {
      "claim": "terminal_scope_claim",
      "reason": "outlet_scope_volume_mismatch",
      "detail": "selected terminal carries 0.757 of generated terminal flow",
      "artifact": "routing_flow_gates.json"
    }
  ]
}
```

Each blocked claim is a **typed reason plus an artifact pointer**. That is what
makes refusal *machine-readable*: a downstream agent can branch on the reason
code, and a reviewer can open the named artifact and check it.

!!! quote "Refusal is a first-class output"
    A pipeline that only emits successes teaches you nothing about its limits.
    This one emits its refusals in the same structured form as its successes —
    so "the system said no" is auditable, not invisible.

## Provenance and reproducibility

`run_manifest.json` records the inputs and the git SHA; `evidence_summary.json`
records the gates, claims, and provenance hashes. Together they make a run
reproducible from its own record. When you report a result, cite the
repository and the run's provenance hash.

## Authority rule

Only metrics that appear in the verified section of the bundle (the
independent locked rerun — see
[Locked calibration](locked-calibration.md)) are authoritative. Candidate /
optimizer-loop metrics are present for transparency but are explicitly marked
non-authoritative and must not be reported as final.

## Read next

- [Reading the evidence (guide)](../guide/reading-evidence.md) — a worked walk
- [Evidence schema (reference)](../reference/evidence-schema.md) — field list
- [Six invariants](invariants.md) — the generalizable pattern behind the bundle
