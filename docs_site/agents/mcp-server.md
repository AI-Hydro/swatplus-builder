# MCP server

swatplus-builder exposes a **Model Context Protocol (MCP)** tool server so an
AI agent operates the pipeline through typed tools rather than free-form code.
This is the design's intended mode: the agent operates, the package governs.

## Start the server

```bash
pip install -e ".[mcp]"
swat mcp                 # stdio transport
```

From a source tree without the entry point:

```bash
PYTHONPATH=src python -m swatplus_builder.cli mcp
```

The server is built on `FastMCP` (`name="swatplus-builder"`) and communicates
over stdio.

## Register it with an agent client

Claude Desktop / Claude Code (`claude_desktop_config.json`):

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

If you run from a source checkout, use the module form instead:

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

## Then ask in natural language

> "Negotiate a research-grade contract for USGS 02177000 over 2000–2019, run
> the canonical workflow, then summarize only from the evidence bundle —
> report allowed and blocked claims."

The agent calls typed tools to do this; it does not get to decide the claim
tier. See [The agent contract](agent-contract.md) for what the agent may and
may not do, and [Tool surface](tool-surface.md) for the 11 tools.

## Containers

```bash
SWATPLUS_BIN_DIR=/path/to/swatplus_dir docker compose run --rm mcp
```

## Read next

- [Tool surface](tool-surface.md) — the 11 MCP tools
- [The agent contract](agent-contract.md) — operate vs. govern
