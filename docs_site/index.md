# swatplus-builder

> **Headless, agent-native SWAT+ modeling — with runtime claim governance.**
> The package, not the agent, holds scientific authority.

`swatplus-builder` turns a single USGS streamgage ID into a complete,
calibrated SWAT+ model and a **machine-readable evidence bundle** that records
exactly what may — and may *not* — be claimed about the result. It runs
entirely in Python with **no QGIS**, and it is designed to be operated by an AI
agent through a typed tool surface (MCP) as readily as from the command line.

The central idea is simple and unusual:

!!! quote "Core principle"
    A capable AI agent already knows hydrology. What it lacks is an
    **environment whose actions are constrained by a verifiable scientific
    contract**. In swatplus-builder the *package* builds, evaluates, verifies,
    blocks, and downgrades; the *agent* only operates. Claim tiers come from
    runtime gates and provenance — never from a metric, and never from the
    agent's say-so.

## What it does

<div class="grid cards" markdown>

-   :material-map-marker-radius: **Gauge → model, headless**

    One USGS ID drives delineation, HRUs, gNATSGO soils, weather, and a valid
    SWAT+ `TxtInOut` — WhiteboxTools + rasterio + geopandas, no QGIS.

-   :material-lock-check: **Locked calibration**

    A `lock → calibrate → verify` protocol where final metrics come from an
    **independent rerun** of the locked artifact, never from the optimizer.

-   :material-shield-check: **Claim governance**

    Runtime gates (fresh engine, benchmark lock, outlet provenance, physical
    sensibility, routing closure, soil fidelity, sensitivity) decide a claim
    tier: `exploratory → diagnostic → research_grade → publication_grade`.

-   :material-file-document-multiple: **Evidence bundle**

    Every run writes `evidence_summary.json` with explicit **allowed and
    blocked claims**, each carrying a typed reason and an artifact pointer.

</div>

## The one-command path

```bash
swat workflow run --usgs-id 02177000 --model-family full \
  --start 2000-01-01 --end 2019-12-31 --warmup-years 3 \
  --calibrate --claim-tier research_grade --json
```

This builds the model, runs the engine, locks a benchmark, runs gated
diagnostic calibration, independently verifies a locked rerun, and writes the
evidence bundle. See [Quickstart](getting-started/quickstart.md).

## Where to go next

| If you want to… | Read |
|---|---|
| Install and run your first basin | [Getting Started](getting-started/installation.md) |
| Understand *why* claims are governed | [Package as authority](concepts/overview.md) |
| Understand the calibration protocol | [Locked calibration](concepts/locked-calibration.md) |
| Operate the pipeline with an AI agent | [Agents (MCP)](agents/mcp-server.md) |
| Look up a command or field | [Reference](reference/cli.md) |
| Know what the system honestly claims today | [Honest status](project/status.md) |

!!! warning "Research software — read the honest status"
    This is alpha research software. Under the current strict gates, the
    canonical 11-basin objective report classifies **0 basins as
    research-grade**, and gate weakening is not permitted. The contribution is
    an *evidence-producing, claim-governed* workflow that makes both successes
    and limitations inspectable — not a claim that automated SWAT+ calibration
    is solved. See [Honest status](project/status.md).
