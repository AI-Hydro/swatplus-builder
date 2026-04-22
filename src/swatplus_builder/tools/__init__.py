"""Agent-facing tool functions.

These four functions define the public contract of the package. They are
imported by :mod:`swatplus_builder.mcp.server`, the CLI in :mod:`swatplus_builder.cli`,
and any direct Python caller.

Keep this surface tiny. Do not add tools here unless they are genuinely
agent-level primitives; specialized helpers belong in the lower-level modules.
"""

from .agent import build_watershed, create_hrus, generate_swat_project, run_swat

__all__ = [
    "build_watershed",
    "create_hrus",
    "generate_swat_project",
    "run_swat",
]
