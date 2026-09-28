# Vendored SWAT+ Editor provenance

- Upstream: https://github.com/swat-model/swatplus-editor, path `src/api/`
- Pinned commit: `7fd0284c5d140c1c475ba8f780e492351f42f178` (tag `v3.2.0`),
  recorded in `.VENDORED_COMMIT`.
- Verified 2026-09 by content comparison: 145 of 147 files are byte-identical
  to upstream `v3.2.0` after the mechanical `database` → `_swatplus_db` rename
  performed by `scripts/vendor_swatplus_editor.sh`.

## Local patches (re-apply after every re-vendor)

1. `actions/import_gis.py` and `actions/import_gis_legacy.py` — the
   `hyd_sed_lte_cha` row writes `'len': 0.0005` (km) instead of
   `row.len2 / 1000`. In the `sdc`/`chandeg` LTE channel path the engine
   treats this field as a transfer length; physical lengths remain in
   `gis_channels.len2`. Rationale and evidence: `DECISIONS.md`
   (hyd-sed-lte transfer length ADR).

## Not shipped in the wheel

`rest/`, `swatplus_rest_api.py` (upstream's Flask REST server),
`get-pip.py`, `Pipfile` and the `python-build-*` scripts stay in the source
tree so it can be diffed against upstream, but are excluded from the wheel
(`pyproject.toml`) because nothing at runtime imports them.
