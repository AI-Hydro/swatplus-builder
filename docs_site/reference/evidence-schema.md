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
| `effective_claim_tier` | the granted tier (`exploratory` … `publication_grade`) |
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
| `research_grade` | provenance + physical + verified-skill + outlet-scope gates pass |
| `publication_grade` | research-grade + full-coverage sensitivity + strictest preconditions |

See [The evidence bundle](../concepts/evidence-bundle.md) and
[Reading the evidence](../guide/reading-evidence.md).
