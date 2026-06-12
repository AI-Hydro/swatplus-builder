# MCP server

swatplus-builder exposes a **Model Context Protocol (MCP)** tool server so an
AI agent operates the pipeline through typed tools rather than free-form code.
This is the design's intended mode: the agent operates, the package governs.

## Start the server

```bash
pip install "swatplus-builder[mcp]"
swat mcp                 # stdio transport
```

Before starting, run a pre-flight check to confirm the server and all tools
load correctly in your active Python environment:

```bash
swat mcp-check           # exits 0 if ready, 1 if not
swat mcp-check --json    # machine-readable output
```

This is especially useful when you have multiple Python environments (conda,
venv, pyenv) — `mcp-check` tells you exactly which import is missing and in
which environment, rather than failing silently when the server spawns.

## Register it with an agent client

Claude Desktop / Claude Code (`claude_desktop_config.json`) — **recommended** form:

```json
{
  "mcpServers": {
    "swatplus-builder": {
      "command": "swat",
      "args": ["mcp"],
      "env": {
        "SWATPLUS_EXE": "/usr/local/bin/swatplus_exe",
        "SWATPLUS_BUILDER_ARTIFACTS": "/data/artifacts"
      }
    }
  }
}
```

!!! tip "Mixed conda/venv environments"
    If you get `ModuleNotFoundError: No module named 'mcp'` when the server
    starts, the `swat` binary is resolving from a different Python than where
    `mcp` is installed. Pin the exact Python interpreter instead:

    ```json
    {
      "mcpServers": {
        "swatplus-builder": {
          "command": "/opt/miniconda3/bin/python",
          "args": ["-m", "swatplus_builder.mcp.server"],
          "env": {
            "SWATPLUS_EXE": "/usr/local/bin/swatplus_exe",
            "SWATPLUS_BUILDER_ARTIFACTS": "/data/artifacts"
          }
        }
      }
    }
    ```

    Find the right interpreter: `which python` inside the environment where
    `pip install swatplus-builder[mcp]` succeeded. Confirm with:
    `python -c "from mcp.server.fastmcp import FastMCP; print('ok')"`.

If you run from a source checkout:

```json
{
  "mcpServers": {
    "swatplus-builder": {
      "command": "python",
      "args": ["-m", "swatplus_builder.mcp.server"],
      "env": { "PYTHONPATH": "/path/to/swatplus-builder/src" }
    }
  }
}
```

## Tool input shape (`req` wrapper)

Every swatplus-builder tool takes a single `req` object — not flat keyword
arguments. This differs from tools that accept top-level parameters directly.
Pass arguments nested under `"req"`:

```json
{
  "req": {
    "strategy": "random",
    "parameters": ["CN2", "ALPHA_BF"],
    "n_suggestions": 5
  }
}
```

The schema for each tool is defined by a named `*Request` Pydantic model
(e.g. `ProposeParametersRequest`). See [Tool surface](tool-surface.md) for
the full list of fields per tool.

## Teach the agent the system: `SKILL.md`

The repository ships a [`SKILL.md`](https://github.com/AI-Hydro/swatplus-builder/blob/main/SKILL.md)
at its root — a single, self-contained skill file that teaches an agent the
whole system: when to use it, the 13-tool catalog with signatures, the
parameter registry, diagnostic heuristics, basin taxonomy, the evaluation
protocol, the locked-benchmark rules, and worked example workflows.

For **Claude Code** (and Claude.ai with skills), point the agent at this file —
it is written in the skill format (YAML front-matter + structured sections) so
the agent loads it as operating knowledge before it touches a tool. It is the
fastest way to bring a cold agent up to competence on the pipeline.

## Then ask in natural language

> "Negotiate a research-grade contract for USGS 02177000 over 2000–2019, run
> the canonical workflow, then summarize only from the evidence bundle —
> report allowed and blocked claims."

The agent calls typed tools to do this; it does not get to decide the claim
tier. See [The agent contract](agent-contract.md) for what the agent may and
may not do, and [Tool surface](tool-surface.md) for the 13 tools.

## SWAT+ engine binary (required for real runs)

The MCP server starts without the engine binary (health returns `degraded`),
but **no simulation, calibration, or locked-benchmark tool will succeed** until
the engine is present.

**Tested version:** `SWAT+ v2023 rev 60.5.7`

| Resource | Link |
|---|---|
| Official download page | [swat.tamu.edu/software/plus](https://swat.tamu.edu/software/plus/) |
| SWAT+ GitBook docs | [swatplus.gitbook.io/docs](https://swatplus.gitbook.io/docs) |
| Source / releases | [github.com/swat-model](https://github.com/swat-model) |

Once downloaded:

```bash
chmod +x swatplus_exe
export SWATPLUS_EXE=/path/to/swatplus_exe   # or place as 'swatplus' on PATH
swat health                                  # should show "swatplus_exe: ✓"
```

When the agent calls `swat health --json` and sees `"swatplus_exe": false`, it
should tell the user to download rev 60.5.7 from the link above and set
`SWATPLUS_EXE`.

## Containers

```bash
SWATPLUS_BIN_DIR=/path/to/swatplus_dir docker compose run --rm mcp
```

## Read next

- [`SKILL.md`](https://github.com/AI-Hydro/swatplus-builder/blob/main/SKILL.md) — the agent skill file (tool catalog, heuristics, workflows)
- [Tool surface](tool-surface.md) — the 13 MCP tools
- [The agent contract](agent-contract.md) — operate vs. govern
