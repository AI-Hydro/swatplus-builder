#!/usr/bin/env bash
# Bootstrap the SWAT+ engine binary.
#
# Tested version: SWAT+ v2023 rev 60.5.7
#   Official download page: https://swat.tamu.edu/software/plus/
#   SWAT+ GitBook docs:     https://swatplus.gitbook.io/docs
#   Source / releases:      https://github.com/swat-model
#
# The binary is NOT redistributable via this script — download it from the
# official SWAT+ website, then run this script with the path to install it.
#
# Usage:
#   SWATPLUS_BIN_PATH=/path/to/downloaded/swatplus_exe bash scripts/bootstrap_swatplus_binary.sh
#
# Or just print instructions (no env var set):
#   bash scripts/bootstrap_swatplus_binary.sh
set -euo pipefail

BIN_DIR="${SWATGEN_BIN_DIR:-/usr/local/bin}"
TARGET="$BIN_DIR/swatplus"

if [[ -z "${SWATPLUS_BIN_PATH:-}" ]]; then
  echo "=== SWAT+ engine binary bootstrap ==="
  echo ""
  echo "Tested version: SWAT+ v2023 rev 60.5.7"
  echo ""
  echo "Download the binary for your platform from:"
  echo "  https://swat.tamu.edu/software/plus/"
  echo ""
  echo "Then re-run this script with the path to the downloaded binary:"
  echo "  SWATPLUS_BIN_PATH=/path/to/swatplus_exe bash scripts/bootstrap_swatplus_binary.sh"
  echo ""
  echo "Or install manually:"
  echo "  chmod +x /path/to/swatplus_exe"
  echo "  sudo mv /path/to/swatplus_exe $TARGET"
  echo "  export SWATPLUS_EXE=$TARGET   # or add $BIN_DIR to PATH"
  echo ""
  echo "Verify with: swat health"
  exit 0
fi

SRC="$(realpath "$SWATPLUS_BIN_PATH")"

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: SWATPLUS_BIN_PATH does not exist: $SRC"
  exit 1
fi

chmod +x "$SRC"
mkdir -p "$BIN_DIR"
cp "$SRC" "$TARGET"
echo "Installed SWAT+ binary to: $TARGET"
echo "Verify: swat health"
