# Vendored SWAT+ Editor Python API

**Source:** <https://github.com/swat-model/swatplus-editor>
**Commit:** `ed60db068e83602727267e2bffb1b7b6e346726a`
**Path:** mirrors `swatplus-editor/src/api/`

## Why this is vendored

The SWAT+ Editor's Python API does the critical `gis_* → SWAT+ model tables →
TxtInOut` translation. It is pure Python (peewee ORM + text-file writers)
with no QGIS dependency, so we use it directly from a headless environment.

By vendoring at a pinned commit we:

1. **Lock the DB contract** — the ORM models in
   `database/project/gis.py` define exactly which columns the editor reads
   from our `gis_*` tables. See `../../../../docs/SCHEMA.md` for the
   producer/consumer comparison.
2. **Avoid runtime Git dependencies** — no network needed at install time.
3. **Get reproducible builds** — the commit is pinned in
   `.VENDORED_COMMIT`.

## Upgrading

```bash
scripts/vendor_swatplus_editor.sh <new_commit_sha>
```

After upgrading:

1. Diff `database/project/gis.py` against the previous vendored version.
2. If column sets changed, update `../../db/schema.py` to match (see
   ADR-011 in `../../../../docs/DECISIONS.md`).
3. Re-run `pytest tests/test_smoke.py -q`.

## Not directly importable

This directory is vendored source, not a Python package under
`swatplus_builder.editor.vendored`. We invoke it as a subprocess through
`swatplus_builder.editor.api`, which adds the `vendored/` path to `sys.path`
on-demand inside a worker process to avoid polluting our own namespace.
