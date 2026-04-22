#!/usr/bin/env bash
# Vendor the SWAT+ Editor Python API at a pinned commit.
# Usage: scripts/vendor_swatplus_editor.sh <commit_sha>
#
# Records the SHA in src/swatplus_builder/editor/vendored/.VENDORED_COMMIT.
set -euo pipefail

COMMIT="${1:?usage: vendor_swatplus_editor.sh <commit_sha>}"
REPO_URL="https://github.com/swat-model/swatplus-editor.git"
WORK="$(mktemp -d)"
DEST="$(cd "$(dirname "$0")/.." && pwd)/src/swatplus_builder/editor/vendored"

echo "Cloning $REPO_URL @ $COMMIT..."
git clone --depth=1 "$REPO_URL" "$WORK/swatplus-editor"
( cd "$WORK/swatplus-editor" && git fetch --depth=1 origin "$COMMIT" && git checkout "$COMMIT" )

PREV_COMMIT="$(cat "$DEST/.VENDORED_COMMIT" 2>/dev/null || echo none)"

rsync -a --delete \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  "$WORK/swatplus-editor/src/api/" "$DEST/" \
  2>/dev/null || true

echo "$COMMIT" > "$DEST/.VENDORED_COMMIT"

echo "---"
echo "Previous commit: $PREV_COMMIT"
echo "New commit:      $COMMIT"
echo "Vendored into:   $DEST"

rm -rf "$WORK"
