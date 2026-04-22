"""SWAT+ engine runner (subprocess).

Public API:

* :func:`run` — spawn the engine on a ``TxtInOut/`` directory.
* :func:`run_project` — same, but takes a :class:`~swatplus_builder.types.SwatPlusProject`.
* :func:`locate_binary` — resolve the engine path from settings / env / PATH.
"""

from .swatplus import BINARY_CANDIDATES, locate_binary, run, run_project

__all__ = [
    "BINARY_CANDIDATES",
    "locate_binary",
    "run",
    "run_project",
]
