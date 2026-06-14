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

# Rename upstream's 'database/' package to '_swatplus_db/' to prevent
# namespace collision with the PyPI 'database' package.
if [ -d "$DEST/database" ]; then
  mv "$DEST/database" "$DEST/_swatplus_db"
  echo "Renamed database/ → _swatplus_db/"
fi

# Rewrite all Python-level references to the renamed package.
find "$DEST" -name "*.py" ! -path '*/__pycache__/*' -print0 \
  | xargs -0 python3 - <<'PYEOF'
import re, sys
from pathlib import Path

for p in [Path(f) for f in sys.argv[1:]]:
    text = p.read_text(encoding="utf-8")
    new  = re.sub(r'\bimport database\b', 'import _swatplus_db', text)
    new  = re.sub(r'\bfrom database\b',   'from _swatplus_db',   new)
    new  = re.sub(r'\bdatabase\.',        '_swatplus_db.',        new)
    if new != text:
        p.write_text(new, encoding="utf-8")
        print(f"  rewritten: {p.name}")
PYEOF

echo "---"
echo "Previous commit: $PREV_COMMIT"
echo "New commit:      $COMMIT"
echo "Vendored into:   $DEST"

rm -rf "$WORK"
