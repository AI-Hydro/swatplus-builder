from __future__ import annotations

from pathlib import Path

import tomllib


def test_default_dependencies_cover_workflow_plot_imports() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = {dep.split(">=")[0].split("<")[0].strip() for dep in project["dependencies"]}

    assert "matplotlib" in dependencies
