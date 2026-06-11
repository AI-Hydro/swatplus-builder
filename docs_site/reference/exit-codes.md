# Exit codes

CLI commands use deterministic exit codes so they compose cleanly in scripts,
CI, and agent tool calls.

## General contract

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Runtime / engine failure (external tool failed, bridge error) |
| `2` | User / config error (bad arguments, missing required files, unknown parameters) |
| `3` | Quality gate failure (e.g. `--min-improvement-nse` not met) |

## `swat health`

`swat health` uses its own three-state contract reflecting runtime readiness:

| Code | Meaning |
|---|---|
| `0` | healthy — engine and reference data resolved |
| `1` | degraded — runnable but missing something (e.g. no engine mounted) |
| `2` | unhealthy — cannot run |

```bash
swat health --json && echo "ready" || echo "not ready (see exit code)"
```

## Why deterministic codes matter

An agent or CI job branches on the exit code without parsing prose. A `3`
specifically signals a *quality gate* failure rather than a crash — the run
executed, but the result did not clear a threshold. That distinction is the
same one the [claim governance](../concepts/claim-governance.md) layer makes in
the evidence bundle: *it ran* and *it may be claimed* are different facts.
