from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10: stdlib tomllib is 3.11+; tomli is its backport (dev extra).
    import tomli as tomllib


def test_default_dependencies_cover_workflow_plot_imports() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = {dep.split(">=")[0].split("<")[0].strip() for dep in project["dependencies"]}

    assert "matplotlib" in dependencies
