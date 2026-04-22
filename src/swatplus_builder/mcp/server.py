"""MCP server (stdio transport) exposing build/create/generate/run.

Relies on the official ``mcp`` Python SDK (extra: ``pip install swatplus_builder[mcp]``).

Each tool's JSON schema is auto-derived from the pydantic return models in
:mod:`swatplus_builder.types` (ADR-005).

Phase 1 TODO:
    - Register the four tools with the SDK's FastMCP pattern.
    - Map SwatgenesisError subclasses to MCP error responses with .context.
    - Emit progress notifications during long-running delineation / engine runs.
"""

from __future__ import annotations


def main() -> None:
    """CLI entry point registered as ``swatgen-mcp``."""
    # TODO(phase1): integrate with the MCP SDK.
    raise SystemExit(
        "swatgen-mcp is a Phase 3 deliverable.\n"
        "For direct Python or CLI use, see `swatgen --help` or "
        "`from swatplus_builder.tools import build_watershed, create_hrus, "
        "generate_swat_project, run_swat`."
    )


if __name__ == "__main__":
    main()
