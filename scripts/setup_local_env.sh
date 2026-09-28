#!/usr/bin/env bash
# setup_local_env.sh — one-shot local dev environment bootstrap for swatplus-builder.
#
# Sets up, on your own machine (macOS or Linux):
#   1. a Python venv with the package installed (core + gis + mcp + dev extras)
#   2. SWAT+ reference databases (soils/wgn datasets)
#   3. the SWAT+ engine binary, built from source with gfortran
#   4. a smoke check (`swat health`) to confirm everything is wired up
#
# Safe to re-run: every step checks whether its target already exists/works
# before doing anything, so this also works as a "is my env still healthy?"
# script.
#
# Usage:
#   ./scripts/setup_local_env.sh                 # full setup
#   ./scripts/setup_local_env.sh --skip-engine    # skip building the SWAT+ binary
#   ./scripts/setup_local_env.sh --skip-refdb     # skip reference-DB bootstrap
#   SWATPLUS_ENGINE_TAG=61.0.2.61 ./scripts/setup_local_env.sh   # pin engine tag
#
# Requires: git, python3 (>=3.10,<3.14), a C/Fortran toolchain (cmake, gfortran)
# only if building the engine from source.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
ENGINE_TAG="${SWATPLUS_ENGINE_TAG:-61.0.2.61}"
ENGINE_SRC_DIR="${ENGINE_SRC_DIR:-$REPO_ROOT/.build/swatplus-src}"
SKIP_ENGINE=0
SKIP_REFDB=0
SKIP_TESTS=0

for arg in "$@"; do
  case "$arg" in
    --skip-engine) SKIP_ENGINE=1 ;;
    --skip-refdb)  SKIP_REFDB=1 ;;
    --skip-tests)  SKIP_TESTS=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^#//'
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m! \033[0m %s\n' "$1"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# 0. Sanity: are we in the right repo, and is it up to date?
# ---------------------------------------------------------------------------
log "Checking repository state"
[ -f "pyproject.toml" ] && grep -q '^name = "swatplus-builder"' pyproject.toml \
  || die "Run this from inside a swatplus-builder checkout."

if git remote get-url origin >/dev/null 2>&1; then
  CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  git fetch origin "$CURRENT_BRANCH" --quiet || warn "Could not fetch origin/$CURRENT_BRANCH (offline?)"
  LOCAL_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  REMOTE_SHA="$(git rev-parse "origin/$CURRENT_BRANCH" 2>/dev/null || echo unknown)"
  if [ "$LOCAL_SHA" != "$REMOTE_SHA" ] && [ "$REMOTE_SHA" != "unknown" ]; then
    warn "Local $CURRENT_BRANCH ($LOCAL_SHA) is behind origin/$CURRENT_BRANCH ($REMOTE_SHA)."
    warn "Run: git pull --ff-only origin $CURRENT_BRANCH   (see docs/AGENT_HANDOFF.md, 'Syncing the local repo')"
  else
    ok "Branch $CURRENT_BRANCH is up to date with origin."
  fi
else
  warn "No 'origin' remote configured; skipping freshness check."
fi

# ---------------------------------------------------------------------------
# 1. Python venv + package install
# ---------------------------------------------------------------------------
log "Setting up Python virtual environment at $VENV_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "python3 not found on PATH."

PYVER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PYVER" in
  3.10|3.11|3.12|3.13) ;;
  *) warn "Python $PYVER is outside the tested 3.10–3.13 range (pyproject caps at <3.14)." ;;
esac

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  ok "Created venv."
else
  ok "Venv already exists, reusing it."
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip --quiet

log "Installing swatplus-builder (core + gis + mcp + dev extras) — editable install"
# gis is required for real (non-synthetic) builds; mcp for the agent tool
# server; dev for pytest/ruff/mypy. Add hyriver/gridmet/soils/swatplus as
# needed for the data sources you plan to use.
pip install -e ".[gis,mcp,dev]" --quiet
ok "Package installed in editable mode."

# ---------------------------------------------------------------------------
# 2. Reference databases
# ---------------------------------------------------------------------------
if [ "$SKIP_REFDB" -eq 0 ]; then
  log "Bootstrapping SWAT+ reference databases"
  if [ -x "scripts/bootstrap_reference_dbs.sh" ]; then
    bash scripts/bootstrap_reference_dbs.sh || warn "Reference DB bootstrap reported an error (check network access)."
  else
    warn "scripts/bootstrap_reference_dbs.sh not found or not executable; skipping."
  fi
else
  warn "Skipping reference-DB bootstrap (--skip-refdb)."
fi

# ---------------------------------------------------------------------------
# 3. SWAT+ engine binary (build from source; strips the debug FPE traps that
#    upstream's CMakeLists.txt bakes into Release builds — see QUICKSTART.md
#    §"Building the engine from source" for why this is necessary).
# ---------------------------------------------------------------------------
if [ "$SKIP_ENGINE" -eq 0 ]; then
  log "Building SWAT+ engine $ENGINE_TAG from source"

  if swat setup engine 2>/dev/null | grep -qi "healthy\|installed"; then
    ok "SWAT+ engine already installed; skipping build. (Use --skip-engine to always skip.)"
  else
    for tool in cmake gfortran git; do
      command -v "$tool" >/dev/null 2>&1 || die "Missing build tool: $tool (install via your package manager, e.g. 'apt install cmake gfortran' or 'brew install cmake gcc')."
    done

    mkdir -p "$(dirname "$ENGINE_SRC_DIR")"
    if [ ! -d "$ENGINE_SRC_DIR" ]; then
      git clone --depth 1 --branch "$ENGINE_TAG" \
        https://github.com/swat-model/swatplus.git "$ENGINE_SRC_DIR"
    else
      ok "Engine source already cloned at $ENGINE_SRC_DIR."
    fi

    pushd "$ENGINE_SRC_DIR" >/dev/null
    # Strip the debug FPE traps upstream adds even to Release builds; an
    # unmodified build aborts with "Floating point exception" on ordinary
    # inputs, including upstream's own refdata/Ames_sub1 fixture.
    sed -i.bak \
      -e 's/ -fcheck=all -ffpe-trap=invalid,zero,overflow,underflow//' \
      -e 's/ -fsignaling-nans//' \
      CMakeLists.txt
    cmake -B build -DCMAKE_BUILD_TYPE=Release
    cmake --build build -j "$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
    BINARY="$(find build -maxdepth 1 -type f -name 'swatplus-*' -print -quit)"
    [ -n "$BINARY" ] || die "Build finished but no swatplus-* binary found in $ENGINE_SRC_DIR/build."
    popd >/dev/null

    swat setup engine --path "$ENGINE_SRC_DIR/build/$(basename "$BINARY")"
    ok "Engine built and registered with 'swat setup engine'."
  fi
else
  warn "Skipping engine build (--skip-engine). Set SWATPLUS_EXE or run 'swat setup engine --path <binary>' manually."
fi

# ---------------------------------------------------------------------------
# 4. Verify
# ---------------------------------------------------------------------------
log "Running health check"
swat health --json || warn "swat health reported issues — see output above."

if [ "$SKIP_TESTS" -eq 0 ]; then
  log "Running offline test suite (fast sanity check, no network/engine needed)"
  python -m pytest -q -x -k "not integration and not e2e" || warn "Some tests failed — review before relying on this environment."
else
  warn "Skipping test run (--skip-tests)."
fi

log "Done."
cat <<EOF

Next steps:
  source $VENV_DIR/bin/activate
  swat health --json
  swat workflow run --usgs-id 02177000 --model-family full \\
      --start 2000-01-01 --end 2019-12-31 --warmup-years 3 \\
      --calibrate --claim-tier diagnostic --out-dir runs/usgs_02177000 --json

Read docs/AGENT_HANDOFF.md for full project context and where to pick up work.
EOF
