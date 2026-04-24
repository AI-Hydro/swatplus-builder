"""Runtime availability/version checks for pySWATPlus calibration stack."""

from __future__ import annotations

from importlib import util
from importlib.metadata import PackageNotFoundError, version

from pydantic import BaseModel, Field

from ..errors import SwatBuilderExternalError


class PySwatPlusRuntimeStatus(BaseModel):
    """Resolved dependency versions for calibration runtime."""

    pyswatplus_version: str = Field(...)
    pymoo_version: str = Field(...)
    salib_version: str = Field(...)


def ensure_pyswatplus_runtime(
    *,
    min_pyswatplus: str = "1.3.0",
    min_pymoo: str = "0.6.1",
    min_salib: str = "1.5.0",
) -> PySwatPlusRuntimeStatus:
    """Validate pySWATPlus calibration runtime dependencies.

    Failure modes:
    - Raises ``SwatBuilderExternalError`` if a package is missing.
    - Raises ``SwatBuilderExternalError`` if a package version is below minimum.
    """

    _require_module("pySWATPlus", pip_name="pySWATPlus")
    _require_module("pymoo", pip_name="pymoo")
    _require_module("SALib", pip_name="SALib")

    pysw = _require_version("pySWATPlus", min_pyswatplus)
    pymoo = _require_version("pymoo", min_pymoo)
    salib = _require_version("SALib", min_salib)
    return PySwatPlusRuntimeStatus(
        pyswatplus_version=pysw,
        pymoo_version=pymoo,
        salib_version=salib,
    )


def _require_module(module_name: str, *, pip_name: str) -> None:
    if util.find_spec(module_name) is None:
        raise SwatBuilderExternalError(
            f"Missing optional calibration dependency: {module_name}",
            module=module_name,
            pip_name=pip_name,
            hint="Install with: pip install pySWATPlus pymoo SALib",
        )


def _require_version(dist_name: str, minimum: str) -> str:
    try:
        current = version(dist_name)
    except PackageNotFoundError as exc:
        raise SwatBuilderExternalError(
            f"Missing distribution metadata: {dist_name}",
            distribution=dist_name,
            hint="Install with: pip install pySWATPlus pymoo SALib",
        ) from exc
    if not _version_at_least(current, minimum):
        raise SwatBuilderExternalError(
            f"{dist_name} version too old: {current} < {minimum}",
            distribution=dist_name,
            current=current,
            minimum=minimum,
        )
    return current


def _version_at_least(current: str, minimum: str) -> bool:
    return _norm(current) >= _norm(minimum)


def _norm(v: str) -> tuple[int, int, int]:
    parts = []
    for token in v.split("."):
        num = ""
        for ch in token:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])
