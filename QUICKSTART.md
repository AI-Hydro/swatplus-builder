# SWATPlus-Builder — Quickstart (Run the Pipeline, Including via Agents)

Headless, agent-operable SWAT+ modeling from a single USGS gauge ID. The
package — not the agent — holds scientific authority: runtime gates,
provenance, locked reruns, and evidence-backed claim tiers decide what may be
claimed.

Repo: <https://github.com/AI-Hydro/swatplus-builder>

---

## 1. Requirements

- **Python ≥ 3.10**
- **SWAT+ engine binary** — SWAT+ v2023 rev 60.5.7–61.0.2.61. Download from
  [swat.tamu.edu/software/plus](https://swat.tamu.edu/software/plus/), then
  install with `swat setup engine --path <binary>` (recommended) or set
  `SWATPLUS_EXE` to its path.
- **SWAT+ reference databases** (datasets / soils / wgn).
- OS: macOS or Linux (Windows: place `swatplus.exe` on `PATH`).
- Network access for USGS NWIS discharge, soils (gNATSGO), and weather.

## 2. Install

```bash
git clone https://github.com/AI-Hydro/swatplus-builder.git
cd swatplus-builder

python -m venv .venv && source .venv/bin/activate

# core + the extras you need (gis is required for real builds)
pip install -e ".[gis,hyriver,gridmet,soils,mcp]"
```

Extras: `gis` (WhiteboxTools + rasterio/geopandas, required), `hyriver`
(NLDI/Daymet retrieval), `gridmet` (gridMET forcing), `soils` (gNATSGO via
Planetary Computer), `mcp` (agent tool server).

## 3. Bootstrap engine + reference data

```bash
# Reference DBs → ~/.swatplus_builder/reference_dbs
bash scripts/bootstrap_reference_dbs.sh

# SWAT+ engine binary — download from https://swat.tamu.edu/software/plus/
# then install with one command (no PATH or env-var needed after this):
swat setup engine --path /path/to/downloaded/swatplus_exe

# Run with no args to see download instructions + current status:
swat setup engine
```

Verify:

```bash
swat health --json   # engine + reference-DB readiness; exit 0 = healthy
```

## 4. Run the canonical workflow (one command)

One USGS gauge ID → build → fresh engine run → benchmark lock → gated
diagnostic calibration → independently verified locked rerun → evidence bundle.

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

Outputs land in the run directory as a machine-readable **evidence bundle**:

| Artifact | What it carries |
|---|---|
| `evidence_summary.json` | final evidence, gate results, **allowed/blocked claims** |
| `run_manifest.json` | file paths + run summary + git SHA |
| `events.jsonl` | stage-by-stage execution trace |
| `benchmark/benchmark_lock.json` | baseline metrics + alignment |
| `calibration_provenance.json` | candidate → lock → verification authority |
| `physical_gates.json`, `routing_flow_gates.json` | gate decisions |

**Read `evidence_summary.json` → `blocked_claims` first.** The system records
what you may *not* say, with a typed reason and an artifact pointer. Metrics
alone never promote a claim tier.

## 5. Drive it with an AI agent

swatplus-builder exposes two surfaces — choose based on your agent type:

| Surface | When to use |
|---|---|
| **`swat` CLI** | Shell-native agents (Claude Code, Cursor), reproducible scripts, CI — use `swat workflow run` directly |
| **MCP tools** | Hosted/chat agents that can't shell out; structured background launch + poll |

### CLI path (shell-native agents — recommended)

```bash
swat workflow run \
  --usgs-id 02177000 \
  --start 2000-01-01 --end 2019-12-31 \
  --model-family full --warmup-years 3 \
  --calibrate --claim-tier diagnostic \
  --out-dir runs/usgs_02177000 --json
```

### MCP path (hosted/chat agents)

```bash
pip install "swatplus-builder[mcp]"
swat mcp   # start the stdio MCP server
```

Register with your agent client (`claude_desktop_config.json` example):

```json
{
  "mcpServers": {
    "swatplus-builder": {
      "command": "swat",
      "args": ["mcp"]
    }
  }
}
```

Then ask the agent:

> "Build and calibrate a SWAT+ model for USGS gauge 02177000. Summarize only
> from the evidence bundle — report allowed and blocked claims."

The agent calls `run_workflow` (background launch), polls `workflow_status`,
then reads `evidence_summary_path`. The `run_workflow` response includes
`equivalent_cli` — the exact `swat workflow run` command for reproducibility.

### The agent contract (what the agent may and may not do)

- The agent **operates**: it calls tools, reads diagnostics, reruns workflows.
- The package **governs**: it builds, evaluates, verifies, blocks, downgrades,
  and writes evidence. Claim tiers come from gates, not from the agent.
- Summaries must come from the **evidence bundle**, not from terminal text.
  Reporting a metric without disclosing a failed gate is overclaiming.

See [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md) for the implemented
`negotiate → run → evidence` flow and the gate-to-claim mapping.

## 6. Honest status

This is research software. The current canonical objective report (11 basins)
classifies **0 as research-grade under strict gates**; gate weakening is not
permitted. The contribution is an *evidence-producing, claim-governed* workflow
that makes both successes and limitations inspectable — not a claim that
automated SWAT+ calibration is solved. See
[`docs/PIPELINE_RESEARCH_GRADE_AUDIT.md`](docs/PIPELINE_RESEARCH_GRADE_AUDIT.md).

## 7. Reproducibility

Every run is reproducible from its `run_manifest.json` (inputs, git SHA,
artifact paths) and `evidence_summary.json` (gates, claims, provenance hashes).
Cite the repository and the run's provenance hash when reporting results.
