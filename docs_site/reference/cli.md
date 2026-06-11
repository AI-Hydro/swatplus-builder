# CLI reference

The CLI is a [Typer](https://typer.tiangolo.com/) app exposed as `swat`. From a
source checkout without the entry point, every command is also reachable as
`PYTHONPATH=src python -m swatplus_builder.cli <command>`.

Run `swat --help` or `swat <command> --help` for the authoritative, in-tree
option list. The tables below reflect the commands registered in
`src/swatplus_builder/cli.py`.

## Workflow (canonical)

| Command | Purpose |
|---|---|
| `swat workflow negotiate --task "..."` | validate a request, emit `workflow_contract.json` |
| `swat workflow run --usgs-id <id> --model-family <full\|lte> ...` | the end-to-end governed pipeline |

Key `workflow run` options: `--usgs-id` (required), `--model-family` (required:
`full` or `lte`), `--start`, `--end`, `--warmup-years`, `--calibrate /
--no-calibrate`, `--claim-tier` (default `diagnostic`), `--contract`,
`--contract-status`, `--accepted-by`, `--out-dir`, `--json`. See
[The canonical workflow](../guide/canonical-workflow.md).

## Run, inspect, health

| Command | Purpose |
|---|---|
| `swat version [--json]` | version + git SHA |
| `swat health [--json]` | runtime health; exit `0` healthy / `1` degraded / `2` unhealthy |
| `swat init` | set up reference datasets (`--ref-dir`, `--datasets-version`) |
| `swat run --txtinout TxtInOut/ --threads 4` | run the engine on an existing project |
| `swat inspect <run_path>` | print persisted run metadata |
| `swat validate --basins <file>` | validate over a basin suite |

## Calibration & benchmark

| Command | Purpose |
|---|---|
| `swat calibrate ...` | calibration entry (real-engine or pyswatplus bridge) |
| `swat lock-benchmark ...` | seal a baseline with hashes |
| `swat locked-calibrate ...` | calibrate against a lock and verify |
| `swat readiness-table --locks-root <dir> [--json]` | suite readiness summary |
| `swat sensitivity ...` | parameter sensitivity screen |

## Diagnostics

| Command | Purpose |
|---|---|
| `swat diagnose ...` | diagnose a run |
| `swat bridge-diagnose ...` | inspect a pySWATPlus bridge failure |
| `swat realism-audit ...` | physical-realism audit of a run |

## MCP

| Command | Purpose |
|---|---|
| `swat mcp` | launch the stdio MCP server (see [Agents](../agents/mcp-server.md)) |

## Exit-code contract

See [Exit codes](exit-codes.md).
