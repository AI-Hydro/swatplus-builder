# Evidence schema

The evidence bundle is a set of JSON / JSONL artifacts written to the run
directory. This page lists the artifacts and the fields you will most often
read. Treat the in-tree files as the source of truth — the schema is evolving
toward a versioned, pydantic-owned `schema_version: "1.0"`.

!!! note "Schema versioning is in progress"
    A formal versioned schema (with a `schema_version` field, a typed claim
    model, and typed diagnostics) is planned. Until it lands, consume the
    bundle defensively: read the fields documented here, and tolerate
    additional keys.

## Bundle artifacts

| Artifact | Format | Contents |
|---|---|---|
| `evidence_summary.json` | JSON | gate results, claim tier vector, allowed/blocked claims |
| `run_manifest.json` | JSON | inputs, artifact paths, run summary, git SHA |
| `events.jsonl` | JSONL | append-only stage-by-stage execution trace |
| `benchmark/benchmark_lock.json` | JSON | sealed baseline metrics + alignment + hashes |
| `calibration_provenance.json` | JSON | candidate → lock → verification authority chain |
| `physical_gates.json` | JSON | ET / mass-balance / volume-bias gate decisions |
| `routing_flow_gates.json` | JSON | routed-flow mass-closure gate decisions |

## `evidence_summary.json` — key fields

| Field | Meaning |
|---|---|
| `effective_claim_tier` | the granted legacy identifier, ordered `exploratory → diagnostic → publication_grade → research_grade` |
| `effective_claim_tier_label` | public workflow label alongside the legacy identifier in new workflow summaries |
| `claim_tier_label` | public label for the requested/allowed tier in new workflow summaries |
| `allowed_claims` | claims the gates support |
| `blocked_claims` | claims refused, each with a `reason` and `artifact` |
| gate entries | per-gate status with a pointer to the gate artifact |

A blocked-claim entry has the shape:

```json
{
  "claim": "terminal_scope_claim",
  "reason": "outlet_scope_volume_mismatch",
  "artifact": "routing_flow_gates.json"
}
```

## `calibration_provenance.json` — authority

| Field | Meaning |
|---|---|
| `baseline` | locked baseline metrics |
| `verified` | metrics from the independent rerun — **authoritative** |
| `authority` | which stage holds authority (`verified_rerun`) |
| `candidate_metrics_authoritative` | always `false` — candidate metrics are not reportable |

## Claim tiers

| Tier | Granted when |
|---|---|
| `exploratory` | the run executed; no quality claim supported |
| `diagnostic` | outputs usable for diagnosis; specific gated sub-claims may hold |
| **Calibration verified** (`publication_grade`) | legacy intermediate tier: calibration and skill checks pass, but complete highest-tier fidelity requirements are not established |
| **Gate-verified** (`research_grade`) | applicable provenance, physical, routing, verified-skill, outlet-scope, sensitivity, soil and land-use fidelity requirements pass for the recorded claim and scope |

These public labels describe workflow verification. Neither legacy identifier
asserts journal approval or a published performance rating. Moriasi criteria
must be assessed separately for the specified variable, time step and period;
missing required metrics do not establish a pass.

See [The evidence bundle](../concepts/evidence-bundle.md) and
[Reading the evidence](../guide/reading-evidence.md).

## Separate numeric performance assessment

The dashboard embeds `streamflow_performance` and
`streamflow_validation_performance` as derived assessments, separate from sealed
workflow claims. Their schema is `moriasi_2015_streamflow_numeric_v1`, with
`status` (`met`, `not_met`, `not_evaluated`), R²/NSE/PBIAS, reference DOI, variable,
timestep, period, evaluation role, and reasons. Calibration alignment assessment
uses every CSV row before plot downsampling and records its source SHA-256.
Reported validation metrics are evaluated only when the complete required
metrics and period are present; no R² is inferred from KGE.

Moriasi 2015 watershed streamflow numeric criteria are R² > 0.60, NSE > 0.50,
and |PBIAS| ≤ 15%. This numeric screen does not replace graphical and contextual
assessment, establish independent validation, or change a workflow tier.
Historical artifacts are not rewritten to contain these new fields.
