# SWATPlus-Builder — Quickstart (Run the Pipeline, Including via Agents)

Headless, agent-operable SWAT+ modeling from a single USGS gauge ID. The
package — not the agent — holds scientific authority: runtime gates,
provenance, locked reruns, and evidence-backed claim tiers decide what may be
claimed.

Repo: <https://github.com/AI-Hydro/swatplus-builder>

---

## 1. Requirements

- **Python ≥ 3.10**
- **SWAT+ engine binary** (`rev60+`) on `PATH` as `swatplus`, or set
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
# Reference DBs → ~/.swatplus-builder/reference_dbs (tag v60.5.7)
bash scripts/bootstrap_reference_dbs.sh

# SWAT+ engine binary (see script for the per-platform download)
bash scripts/bootstrap_swatplus_binary.sh
```

Verify:

```bash
PYTHONPATH=src python -m swatplus_builder.cli version
PYTHONPATH=src python -m swatplus_builder.cli workflow run --help
```

## 4. Run the canonical workflow (one command)

One USGS gauge ID → build → fresh engine run → benchmark lock → gated
diagnostic calibration → independently verified locked rerun → evidence bundle.

```bash
PYTHONPATH=src python -m swatplus_builder.cli workflow run \
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

## 5. Drive it with an AI agent (MCP)

The package exposes an MCP tool server so an agent (Claude Code, Claude
Desktop, or any MCP client) operates the workflow through typed tools rather
than free-form code.

```bash
# start the stdio MCP server
PYTHONPATH=src python -m swatplus_builder.cli mcp
```

Register it with your agent client (Claude Desktop / Claude Code
`claude_desktop_config.json` example):

```json
{
  "mcpServers": {
    "swatplus-builder": {
      "command": "python",
      "args": ["-m", "swatplus_builder.cli", "mcp"],
      "env": { "PYTHONPATH": "src" }
    }
  }
}
```

Then ask the agent in natural language, e.g.:

> "Negotiate a research-grade contract for USGS 02177000 over 2000–2019, run
> the canonical workflow, then summarize only from the evidence bundle —
> report allowed and blocked claims."

### The agent contract (what the agent may and may not do)

- The agent **operates**: it negotiates contracts, calls tools, reads
  diagnostics, and reruns workflows.
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
