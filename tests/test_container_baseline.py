"""Phase 3E PR-3E-01: Container baseline smoke tests.

These tests validate the Dockerfile and docker-compose.yml structure without
requiring a Docker daemon. They check:
1. Dockerfile exists and contains mandatory instruction patterns.
2. docker-compose.yml is valid YAML with the expected service definitions.
3. Key runtime env-var contracts are declared in the Dockerfile.
4. The non-root user is created.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"


# ---------------------------------------------------------------------------
# Dockerfile structure
# ---------------------------------------------------------------------------

def test_dockerfile_exists():
    assert DOCKERFILE.exists(), "Dockerfile must exist at repository root"


def test_dockerfile_uses_python311_base():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "python:3.11" in text, "Dockerfile must be based on python:3.11"


def test_dockerfile_has_multistage_build():
    text = DOCKERFILE.read_text(encoding="utf-8")
    from_count = len(re.findall(r"^FROM\s", text, re.MULTILINE))
    assert from_count >= 2, f"Expected multi-stage build (>=2 FROM), found {from_count}"


def test_dockerfile_declares_swatplus_exe_env():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "SWATPLUS_EXE" in text, "Dockerfile must declare SWATPLUS_EXE env var"


def test_dockerfile_declares_artifacts_env():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "SWATPLUS_BUILDER_ARTIFACTS" in text


def test_dockerfile_declares_volume():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "VOLUME" in text, "Dockerfile must declare a VOLUME for artifacts and binary"


def test_dockerfile_creates_nonroot_user():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "useradd" in text or "adduser" in text, \
        "Dockerfile must create a non-root runtime user"


def test_dockerfile_sets_swat_entrypoint():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "ENTRYPOINT" in text
    assert '"swat"' in text or "'swat'" in text


# ---------------------------------------------------------------------------
# docker-compose structure
# ---------------------------------------------------------------------------

def test_docker_compose_exists():
    assert COMPOSE.exists(), "docker-compose.yml must exist at repository root"


def test_docker_compose_is_valid_yaml():
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed; skipping compose YAML validation")
    with COMPOSE.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), "docker-compose.yml must parse to a mapping"


def test_docker_compose_has_swat_service():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "swat:" in text, "docker-compose.yml must define a 'swat' service"


def test_docker_compose_has_mcp_service():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "mcp:" in text, "docker-compose.yml must define an 'mcp' service"


def test_docker_compose_mounts_artifacts_volume():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "/data/artifacts" in text, \
        "docker-compose.yml must mount /data/artifacts for artifact persistence"


def test_docker_compose_mounts_swatplus_binary():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "/opt/swatplus" in text, \
        "docker-compose.yml must mount /opt/swatplus for the engine binary"


# ---------------------------------------------------------------------------
# .dockerignore (optional but recommended)
# ---------------------------------------------------------------------------

def test_dockerignore_excludes_artifacts_if_present():
    di = REPO_ROOT / ".dockerignore"
    if not di.exists():
        pytest.skip(".dockerignore not present (optional)")
    text = di.read_text(encoding="utf-8")
    assert "tests/_artifacts" in text or "_artifacts" in text, \
        ".dockerignore should exclude test artifact directories"
