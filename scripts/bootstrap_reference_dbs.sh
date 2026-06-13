#!/usr/bin/env bash
# Check whether the SWAT+ reference databases are in place and print
# instructions for obtaining any that are missing.
#
# AUTO-DOWNLOAD IS NOT IMPLEMENTED.  The three required SQLite files are
# distributed by the SWAT+ team but are not yet mirrored in a public
# machine-readable location that this script can safely point at.  The
# ai-hydro/swatplus-reference-data mirror referenced in earlier versions of
# this file does not exist.
#
# This script therefore ONLY:
#   1. Checks whether each required DB is already present, and
#   2. Exits 0 if all three are found, or 1 with actionable instructions
#      if any are missing.
#
# Reproducibility note for papers / reproducibility packages:
#   swatplus_datasets.sqlite and swatplus_soils.sqlite ship with SWAT+ Editor
#   and are obtainable from the official SWAT+ distribution.
#   swatplus_wgn.sqlite (weather-generator stations, table wgn_cfsr_world) is
#   also part of that distribution but is NOT present in this repository.
#   Any result produced by swatplus-builder cannot be reproduced on a fresh
#   machine without these three files.  See docs/REPRODUCIBILITY.md.
set -euo pipefail

TARGET="${SWATGEN_REFERENCE_DB_DIR:-$HOME/.swatplus_builder/reference_dbs}"

REQUIRED=(
    "swatplus_datasets.sqlite"
    "swatplus_soils.sqlite"
    "swatplus_wgn.sqlite"
)

missing=()
found=()
for db in "${REQUIRED[@]}"; do
    if [[ -f "$TARGET/$db" ]]; then
        found+=("$db")
    else
        missing+=("$db")
    fi
done

if [[ ${#found[@]} -gt 0 ]]; then
    echo "Reference DBs already present in $TARGET:"
    for db in "${found[@]}"; do
        size=$(du -sh "$TARGET/$db" 2>/dev/null | cut -f1)
        echo "  ✓  $db  ($size)"
    done
fi

if [[ ${#missing[@]} -eq 0 ]]; then
    echo ""
    echo "All three reference DBs are present.  No action needed."
    exit 0
fi

echo ""
echo "MISSING reference DBs (required for any real build):"
for db in "${missing[@]}"; do
    echo "  ✗  $db"
done
echo ""
echo "────────────────────────────────────────────────────────────────────"
echo "AUTO-DOWNLOAD IS NOT AVAILABLE."
echo ""
echo "How to obtain the missing files:"
echo ""
echo "Option A — SWAT+ Editor desktop app (recommended):"
echo "  1. Download from https://swat.tamu.edu/software/plus/"
echo "     (look for 'SWAT+ Editor' or 'SWAT+ Toolbox')"
echo "  2. Install it on any machine (macOS, Windows, or Linux)."
echo "  3. After installation, the databases are at:"
echo "     macOS/Linux:  \$HOME/SWATPlus/Databases/*.sqlite"
echo "     Windows:      %USERPROFILE%\\SWATPlus\\Databases\\*.sqlite"
echo "  4. Copy them to: $TARGET/"
echo ""
echo "Option B — from a project backup / shared drive:"
echo "  Copy all three *.sqlite files to: $TARGET/"
echo ""
echo "Option C — from a colleague's working installation:"
echo "  rsync -av colleague:/path/to/reference_dbs/ $TARGET/"
echo ""
echo "After placing the files, re-run this script to verify."
echo "────────────────────────────────────────────────────────────────────"
exit 1
