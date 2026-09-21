# Second preprint critical review — 21 September 2026

## Verdict and scope

The earlier claim of a technically complete portable package was premature.
Checksums established file integrity but did not establish that a recipient could
rebuild the manuscript or figures. This review corrected the defects below and
executed both rebuilds from a separate extraction of the revised package.

This is a focused evidence/publication review, not a new exhaustive penetration
test or an independent hydrologic replication. No solver code, frozen run, or
scientific gate was changed; the evidence commit remains `90eeec95df7e`.

## Confirmed defects and fixes

1. **High: stale construction inventory.** Table 5 retained July values after
   the main results moved to September evidence. Corrected both manuscript
   sources directly from watershed, land-use and soil reports: positive basin
   111.398 km², 25 channels, 1,506 HRUs and 65 soil profiles; negative basin
   2,192.863 km², 37 channels, 3,320 HRUs and 247 soil profiles. Routing and
   land-cover retention values were also corrected. Added claim C21 and a
   repeatable evidence checker.
2. **High: packaged LaTeX did not resolve its figures.** The source requested
   `latex/figures`, but the builder copied images to `publication/figures`.
   The builder now preserves the source-relative layout.
3. **High: packaged figure script resolved the wrong root.** The script was
   copied one directory above its expected location. It now lives under
   `publication/Research_article/scripts`, preserving its root calculations.
4. **High: objective map depended on excluded historical sidecars.** Redacting
   their paths did not make the map reproducible. Retained the eleven exact
   outlet coordinates and source-file SHA-256 digests as publication data;
   map generation uses that frozen data and needs no original run directories.
5. **Medium: incorrect rounded negative benchmark KGE.** The final value
   0.08318601686058169 rounds to 0.0832, not 0.0833. Corrected the manuscript,
   claim ledger and evidence freeze.
6. **Medium: premature author declarations.** The draft asserted absence of
   competing interests and completion of author review without confirmation.
   These statements and proposed CRediT roles now explicitly await author
   confirmation.
7. **Medium: destructive ordering in figure generation.** Output cleanup ran
   before input validation. Moved cleanup after loading required inputs, so a
   missing or invalid input does not erase existing figures before failing.
8. **Low: evidence-freeze date preceded completion.** The negative run ended
   on 21 September. The evidence freeze now states that date and distinguishes
   the local initiation date.

## Verification performed

- New evidence checker passes against both final runs: all Table 5 inventory
  fields, eighteen rounded metrics, recorded revisions, and weather counts.
- The same checker rejects the previous package for the stale KGE value.
- Extracted both complete run archives to a separate temporary directory and
  copied only packaged publication files there.
- Ran the packaged figure generator with the extracted run paths: all thirteen
  manuscript/graphical-abstract/thesis review rasters match the reviewed local
  rasters byte for byte. Cartopy used this host's installed basemap cache;
  first-use Natural Earth downloads remain documented, not tested offline.
- Built the packaged LaTeX source from scratch: seventeen pages, no overfull
  boxes and no undefined references. Inspected the rendered page contact sheet
  and changed table/declaration pages.
- Revised archive uses checksum-verified copies of the already validated run
  archives, preserving the scientific evidence bytes.

## Remaining limits

Human correspondence, funding, competing interests, CRediT, author review and
consent, repository/licence selection and public identifiers remain unresolved.
The package does not supply independent cross-machine reproduction, a controlled
agent-behaviour study, broad basin validation, uncertainty quantification, or a
security completeness guarantee. The historical objective snapshot's full
sidecars remain excluded and this is disclosed. Rebuilding its map is supported;
reconstructing every historical workflow from this focused package is not.

The revised package is `/Users/mgalib/swatplus_preprint_release/swatplus-builder-0.7.14-90eeec9-review2`.
The previous `...-20260920` package is retained as a superseded audit artifact.
