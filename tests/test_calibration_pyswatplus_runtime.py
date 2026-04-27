from __future__ import annotations

import pytest

from swatplus_builder.calibration import pyswatplus_runtime as rt
from swatplus_builder.errors import SwatBuilderExternalError


def test_ensure_pyswatplus_runtime_passes_with_sufficient_versions(monkeypatch) -> None:
    monkeypatch.setattr(rt.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        rt,
        "version",
        lambda name: {"pySWATPlus": "1.3.0", "pymoo": "0.6.1", "SALib": "1.5.1"}[name],
    )
    s = rt.ensure_pyswatplus_runtime()
    assert s.pyswatplus_version == "1.3.0"
    assert s.pymoo_version == "0.6.1"
    assert s.salib_version == "1.5.1"


def test_ensure_pyswatplus_runtime_fails_when_missing_module(monkeypatch) -> None:
    def _find(name: str):
        return None if name == "pySWATPlus" else object()

    monkeypatch.setattr(rt.util, "find_spec", _find)
    with pytest.raises(SwatBuilderExternalError, match="Missing optional calibration dependency"):
        rt.ensure_pyswatplus_runtime()


def test_ensure_pyswatplus_runtime_fails_when_version_too_old(monkeypatch) -> None:
    monkeypatch.setattr(rt.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        rt,
        "version",
        lambda name: {"pySWATPlus": "1.2.9", "pymoo": "0.6.1", "SALib": "1.5.0"}[name],
    )
    with pytest.raises(SwatBuilderExternalError, match="version too old"):
        rt.ensure_pyswatplus_runtime()
