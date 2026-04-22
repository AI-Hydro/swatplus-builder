#!/usr/bin/env bash
# Download SWAT+ reference databases from the GitHub mirror (ai-hydro/swatplus-reference-data).
#
# The mirror tags match SWAT+ release versions (e.g. v60.5.7), ensuring reproducible
# builds without relying on upstream Bitbucket availability.
#
# Target directory: $SWATGEN_REFERENCE_DB_DIR (default: ~/.swatplus-builder/reference_dbs)
#
# Required DBs:
#   swatplus_datasets.sqlite   — landuse/plant/urban/fert/pest/op parameter tables
#   swatplus_soils.sqlite      — STATSGO / STATSGO2 soil definitions
#   swatplus_wgn.sqlite        — Weather Generator stations (CFSR, world coverage)
set -euo pipefail

TARGET="${SWATGEN_REFERENCE_DB_DIR:-$HOME/.swatplus-builder/reference_dbs}"
# Tag on ai-hydro/swatplus-reference-data mirroring SWAT+ v60.5.7 reference DBs
MIRROR_TAG="${SWATPLUS_DB_TAG:-v60.5.7}"
MIRROR_BASE="https://github.com/ai-hydro/swatplus-reference-data/releases/download/${MIRROR_TAG}"

mkdir -p "$TARGET"
echo "Downloading SWAT+ reference databases (${MIRROR_TAG}) into ${TARGET}..."
echo ""
echo "TODO(Phase 1): populate ai-hydro/swatplus-reference-data mirror and hardcode URLs here."
echo ""
echo "Interim: install SWAT+ Editor desktop app, then copy from its Databases folder:"
echo "  macOS/Linux: ~/SWATPlus/Databases/*.sqlite  →  $TARGET/"
echo "  Windows:     %USERPROFILE%\\SWATPlus\\Databases\\*.sqlite  →  $TARGET/"
