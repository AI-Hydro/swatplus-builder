# Quickstart

One USGS gauge ID → build → fresh engine run → benchmark lock → gated
diagnostic calibration → independently verified locked rerun → evidence bundle.

## Run the canonical workflow

```bash
swat workflow run \
  --usgs-id 02177000 \
  --model-family full \
  --start 2000-01-01 --end 2019-12-31 \
  --warmup-years 3 \
  --calibrate \
  --claim-tier research_grade \
  --json
```

!!! tip "Running from a source checkout"
    If you installed with `pip install -e .`, the `swat` entry point is on your
    `PATH`. If you are running directly from the tree without the entry point,
    the equivalent is:
    ```bash
    PYTHONPATH=src python -m swatplus_builder.cli workflow run --usgs-id 02177000 ...
    ```

### What each flag means

| Flag | Default | Meaning |
|---|---|---|
| `--usgs-id` | *(required)* | USGS streamgage ID — anchors data retrieval and the outlet |
| `--model-family` | *(required)* | `full` (subbasin/HRU routing) or `lte` (lumped, lightweight) |
| `--start` / `--end` | `2000-01-01` / `2019-12-31` | simulation period |
| `--warmup-years` | `3` | warmup discarded before scoring |
| `--calibrate / --no-calibrate` | `--calibrate` | run gated diagnostic calibration |
| `--claim-tier` | `diagnostic` | the tier you *request*; gates decide what is *granted* |
| `--contract` | — | path to an accepted `workflow_contract.json` (see below) |
| `--json` | off | emit a machine-readable summary to stdout |

!!! warning "Requesting research-grade requires a contract"
    Requesting `research_grade` / `publication_grade` is a *policy-gated*
    request. The toolchain checks preconditions (e.g. a ≥10-year window) and
    expects accepted contract metadata. The clean way to do this is to
    [negotiate a contract first](../guide/canonical-workflow.md#negotiate-first).
    Requesting a high tier does **not** make the result that tier — only the
    gates do.

## Read the evidence bundle

Outputs land in the run directory. **Read `evidence_summary.json` →
`blocked_claims` first** — the system records what you may *not* say, with a
typed reason and an artifact pointer.

| Artifact | What it carries |
|---|---|
| `evidence_summary.json` | final evidence, gate results, **allowed/blocked claims** |
| `run_manifest.json` | file paths + run summary + git SHA |
| `events.jsonl` | stage-by-stage execution trace |
| `benchmark/benchmark_lock.json` | baseline metrics + alignment |
| `calibration_provenance.json` | candidate → lock → verification authority |
| `physical_gates.json`, `routing_flow_gates.json` | gate decisions |

See [The evidence bundle](../concepts/evidence-bundle.md) for the full anatomy
and [Reading the evidence](../guide/reading-evidence.md) for a worked walk-through.

## What to expect honestly

Most basins **build and run** cleanly and many **calibrate with real, verified
improvement** — and still do not earn a `research_grade` claim under the strict
gates. That is the system working as designed: a blocked claim is *classified
evidence*, not a crash. See [Honest status](../project/status.md).

Next: [Why claims are governed →](../concepts/overview.md)
