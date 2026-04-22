#!/usr/bin/env bash
# Download the SWAT+ engine binary for the current platform.
# Writes $SWATGEN_BIN_DIR/swatplus (default: /usr/local/bin/swatplus).
set -euo pipefail

BIN_DIR="${SWATGEN_BIN_DIR:-/usr/local/bin}"

echo "TODO(Phase 1): pin the SWAT+ engine download URL per platform and write a"
echo "               checksum-verified installer here."
echo ""
echo "Interim instructions:"
echo "  macOS/Linux: download the latest rev60+ engine from swatplus.gitbook.io,"
echo "               chmod +x and place it at $BIN_DIR/swatplus."
echo "  Windows:     place swatplus.exe on PATH or set SWATPLUS_EXE to its path."
