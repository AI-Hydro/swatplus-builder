# swatplus-builder

> **Calibrated SWAT+ models from a single gauge ID — with evidence you can audit.**

swatplus-builder builds and calibrates SWAT+ hydrologic models in Python,
starting from one USGS streamgage ID. It can be driven by a person or by an AI
agent — and either way, the **software, not the operator, decides what each
result is allowed to claim**.

!!! quote "The idea in one sentence"
    A capable modeler — human or AI — already knows hydrology. What they lack is
    an environment that will not let them claim more than the evidence supports.
    swatplus-builder is that environment: it builds, evaluates, verifies,
    blocks, and downgrades, and records every decision as machine-readable
    evidence.

## What you can do with it

<div class="grid cards" markdown>

-   :material-map-marker-radius: **Gauge → calibrated model**

    One USGS ID drives delineation, HRUs, gNATSGO soils, weather, and a valid
    SWAT+ model — start to finish in Python, with no desktop GIS (no QGIS).

-   :material-lock-check: **Calibration you can trust**

    A `lock → calibrate → verify` protocol where the reported numbers come from
    an **independent rerun** of the calibrated model, never from the optimizer.

-   :material-shield-check: **Claims you can audit**

    Runtime gates decide a result's tier —
    `exploratory → diagnostic → research_grade → publication_grade`. A strong
    metric never promotes itself past a failed gate.

-   :material-file-document-multiple: **A complete evidence bundle**

    Every run writes its results *and its refusals* — each allowed or blocked
    claim carries a plain reason and a pointer to the evidence behind it.

</div>

## One command, end to end

```bash
swat workflow run --usgs-id 02177000 --model-family full \
  --start 2000-01-01 --end 2019-12-31 --warmup-years 3 \
  --calibrate --claim-tier research_grade --json
```

This builds the model, runs the engine, locks a baseline, calibrates, verifies a
clean rerun, and writes the evidence bundle. Start with the
[Quickstart](getting-started/quickstart.md).

## Find your way

| If you want to… | Go to |
|---|---|
| Install and run your first basin | [Getting Started](getting-started/installation.md) |
| Understand *why* results are governed | [How claims are governed](concepts/overview.md) |
| Understand the calibration protocol | [Locked calibration](concepts/locked-calibration.md) |
| Drive the pipeline with an AI agent | [Working with agents](agents/mcp-server.md) |
| Look up a command, function, or field | [Reference](reference/cli.md) |
| Know what the system claims today | [Project status](project/status.md) |

!!! warning "This is research software — read the status page"
    Under its current strict gates, swatplus-builder grants **no basin a
    research-grade claim** across the 11-basin test suite, and it does not relax
    those gates to manufacture passes. That is the system working as intended:
    its value is an *auditable* workflow that makes both successes and
    limitations inspectable — not a claim that automated SWAT+ calibration is a
    solved problem. See [Project status](project/status.md).
