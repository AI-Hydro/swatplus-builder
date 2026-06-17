# The canonical workflow

`swat workflow run` is the one command that takes a USGS gauge ID all the way
to an evidence bundle. This page covers the full `negotiate → run → evidence`
flow, which is the recommended path for anything beyond a quick exploratory
run.

## negotiate first

For `research_grade` / `publication_grade` work, start by negotiating a
contract. This validates policy preconditions *before* you spend compute.

```bash
swat workflow negotiate --task "research-grade model for USGS 02177000, 2000-2019"
```

Behavior:

1. parses the USGS ID and date range from the task;
2. parses the requested claim tier;
3. validates policy preconditions for research/publication requests (e.g. a
   ≥10-year window);
4. emits `workflow_contract.json` and `WORKFLOW_CONTRACT.md`.

If policy fails, it returns `status=needs_input` with `policy_issues` rather
than proceeding — you fix the request and re-negotiate.

## run

```bash
swat workflow run \
  --usgs-id 02177000 \
  --model-family full \
  --start 2000-01-01 --end 2019-12-31 \
  --warmup-years 3 \
  --calibrate \
  --hru-mode full_overlay \
  --min-hru-fraction 0.001 \
  --claim-tier research_grade \
  --contract workflow_contract.json \
  --out-dir demo_runs/workflow/02177000 \
  --json
```

Passing the accepted `--contract` (optionally with `--contract-status` and
`--accepted-by`) lets a research-grade run carry its accepted contract metadata
directly. Without it, a high-tier *request* still only yields a high-tier
*grant* if the gates pass.

`--hru-mode full_overlay` is the claim-conservative land-use fidelity path for
research-grade probes. The default `dominant_only` mode remains useful for
first-pass builds, but the land-use fidelity gate will not promote a
research-grade land-use claim from dominant-only HRUs.

### The stages a run executes

| Stage | What happens |
|---|---|
| acquire | USGS discharge, terrain, land use, soils, weather |
| delineate | watershed + stream network from the DEM |
| HRU / soil / weather | hydrologic response units, soil profiles, forcing |
| project | SQLite → `TxtInOut` via the vendored SWAT+ editor |
| run | SWAT+ engine executes (subprocess) |
| **lock** | baseline sealed with hashes (see [Locked calibration](../concepts/locked-calibration.md)) |
| calibrate | gated real-engine DDS on effective parameters |
| **verify** | independent rerun of the promoted artifact |
| evidence | gates evaluated, claim tiers emitted, bundle written |

## model families

| `--model-family` | Description |
|---|---|
| `full` | subbasin / HRU representation with channel routing |
| `lte` | lumped, lightweight configuration |

## evidence

Every run writes the [evidence bundle](../concepts/evidence-bundle.md). Read
`evidence_summary.json → blocked_claims` first, then `allowed_claims`, then the
verified metrics. See [Reading the evidence](reading-evidence.md).

!!! tip "Lower-level primitives still exist"
    `swat lock-benchmark`, `swat locked-calibrate`, and `swat readiness-table`
    remain available as composable primitives — `workflow run` orchestrates
    them for you. See the [CLI reference](../reference/cli.md).
