# Running with AI-Hydro

[AI-Hydro](https://github.com/AI-Hydro/AI-Hydro) is a VS Code–integrated
agentic hydrology platform. swatplus-builder integrates with AI-Hydro as both
an **MCP server** (13 tools available to the agent) and a **registered skill**
(the agent loads `SKILL.md` to understand the system before touching tools).

---

## Quick setup

### 1. Install the package

```bash
pip install "swatplus-builder[gis,mcp]"
```

### 2. Install the engine binary

The SWAT+ engine binary is not a pip dependency. Download from
[swat.tamu.edu/software/plus](https://swat.tamu.edu/software/plus/) then:

```bash
swat setup engine --path /path/to/downloaded/swatplus_exe
```

This installs to `~/.swatplus_builder/bin/` and is picked up automatically.
Run `swat setup engine` (no args) to check status or get download instructions.

### 3. Add the MCP server to AI-Hydro

Open your AI-Hydro MCP settings (`aihydro_mcp_settings.json`) and add:

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

No `SWATPLUS_EXE` env var needed if you used `swat setup engine --path`. If you
installed the engine manually, add it:

```json
{
  "env": { "SWATPLUS_EXE": "/path/to/swatplus_exe" }
}
```

### 4. Install from the Marketplace

swatplus-builder is listed in the
[AI-Hydro Marketplace](https://github.com/AI-Hydro/Marketplace). From
the AI-Hydro extension, open the Marketplace tab and search for
**"SWAT+ Builder"** — one-click install sets up the MCP server config.

---

## Load the skill before running

Before issuing any tool calls, instruct the agent to load the skill file:

```
Read the SKILL.md at https://raw.githubusercontent.com/AI-Hydro/swatplus-builder/main/SKILL.md
then help me build a model for USGS gauge 01547700
```

`SKILL.md` gives the agent the full tool catalog with signatures, parameter
registry, diagnostic heuristics, the locked-benchmark rules, and worked
example workflows. Without it, the agent can call the tools but lacks context
for correct sequencing.

---

## Running the full pipeline

### Via MCP tools (hosted/chat agents)

Once the MCP server is connected and the skill is loaded, ask the agent:

```
Build and calibrate a SWAT+ model for USGS gauge 01547700.
Report the evidence tier and calibrated NSE vs baseline.
```

The agent will:

1. Call `run_workflow(usgs_id="01547700")` — launches the canonical pipeline
   (build → run → lock benchmark → calibration → locked verification →
   evidence bundle) as a **background process** and returns immediately.
2. Poll `workflow_status(out_dir=...)` roughly every 60 s until `completed`.
3. On completion, read `evidence_summary_path` and report **only** from the
   evidence bundle — allowed claims, blocked claims, effective tier.

### Via CLI (shell-native agents, scripts)

Shell-native agents (Claude Code, Cursor) and reproducible scripts should use
the CLI directly — it is equivalent and often faster to iterate with:

```bash
swat workflow run --usgs-id 01547700 \
  --start 2000-01-01 --end 2019-12-31 \
  --model-family full --warmup-years 3 \
  --calibrate --claim-tier diagnostic \
  --out-dir runs/usgs_01547700 --json
```

The MCP `run_workflow` tool returns an `equivalent_cli` field with this exact
command for every run — record it for reproducibility.

---

## Claim governance from AI-Hydro

The package enforces claim governance regardless of which agent or platform
drives it. Even from AI-Hydro, the agent cannot:

- Upgrade a result to `research_grade` without passing all gates.
- Report calibrated metrics without an independent locked-verification rerun.
- Expand calibration parameters beyond the approved registry.

The allowed claims come from `evidence_summary.json` in the artifacts directory
— always machine-readable and auditable.

---

## Registered skill (Skills repo)

swatplus-builder is registered in the
[AI-Hydro/Skills](https://github.com/AI-Hydro/Skills/tree/main/skills/swatplus-builder)
repository. The AI-Hydro skill loader can pull it automatically when the agent
determines the task involves SWAT+ modeling.

---

## See also

- [MCP server](mcp-server.md) — full 13-tool surface and config options
- [Tool surface](tool-surface.md) — per-tool signatures and parameter registry
- [The agent contract](agent-contract.md) — what the agent may and may not do
- [`SKILL.md`](https://github.com/AI-Hydro/swatplus-builder/blob/main/SKILL.md) — canonical agent skill file
