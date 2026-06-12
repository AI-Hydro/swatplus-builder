# Running with AI-Hydro

[AI-Hydro](https://github.com/AI-Hydro/AI-Hydro) is a VS Code–integrated
agentic hydrology platform. swatplus-builder integrates with AI-Hydro as both
an **MCP server** (11 tools available to the agent) and a **registered skill**
(the agent loads `SKILL.md` to understand the system before touching tools).

---

## Quick setup

### 1. Install the package

```bash
pip install "swatplus-builder[gis,mcp]"
```

### 2. Add the MCP server to AI-Hydro

Open your AI-Hydro MCP settings (`aihydro_mcp_settings.json`) and add:

```json
{
  "mcpServers": {
    "swatplus-builder": {
      "command": "swat",
      "args": ["mcp"],
      "env": {
        "SWATPLUS_EXE": "/path/to/swatplus_exe",
        "SWATPLUS_BUILDER_ARTIFACTS": "/data/artifacts"
      }
    }
  }
}
```

`SWATPLUS_EXE` points to the SWAT+ engine binary you supply (not a pip
dependency). `SWATPLUS_BUILDER_ARTIFACTS` is where run artifacts are persisted.

### 3. Install from the Marketplace

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

Once the MCP server is connected and the skill is loaded, ask the agent:

```
Build and calibrate a SWAT+ model for USGS gauge 01547700.
Use the canonical workflow: build → run → lock benchmark → locked calibrate → verify.
Report the evidence tier and calibrated NSE vs baseline.
```

The agent will:

1. Call `build_project` to delineate the watershed and generate the SWAT+ project.
2. Call `run_basin` to execute the base simulation.
3. Call `lock_benchmark` to snapshot baseline metrics (required before calibration).
4. Call `locked_calibrate` with `CN2` + `ALPHA_BF` parameters.
5. Call `validate` to verify the calibrated solution independently.
6. Return the evidence bundle path and the allowed claim tier.

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

- [MCP server](mcp-server.md) — full 11-tool surface and config options
- [Tool surface](tool-surface.md) — per-tool signatures and parameter registry
- [The agent contract](agent-contract.md) — what the agent may and may not do
- [`SKILL.md`](https://github.com/AI-Hydro/swatplus-builder/blob/main/SKILL.md) — canonical agent skill file
