# Reproducibility of Published Results

This document records the external dependencies required to reproduce any result
produced by swatplus-builder, including the 11-basin objective suite reported in
`docs/objective_basin_validation_report.json`.

## External dependencies not in this repository

### SWAT+ engine binary

The SWAT+ executable is **not distributed with this package**. Obtain it from
[swat.tamu.edu/software/plus](https://swat.tamu.edu/software/plus/). The
published 11-basin suite ran on **rev 61.0.2.61** (x86_64 binary, confirmed via
persisted output-header stamps; see `memory/engine-version-provenance.md`).

On Darwin 25.5 (arm64): use the x86_64 binary under Rosetta — the native arm64
binary SIGILLs (exit 132) on this OS version.

### Reference databases

Three SQLite files are required at `~/.swatplus_builder/reference_dbs/`:

| File | Source | Status |
|---|---|---|
| `swatplus_datasets.sqlite` (v3.2.0) | SWAT+ Editor `~/SWATPlus/Databases/` | Obtainable from SWAT+ Editor install |
| `swatplus_soils.sqlite` | SWAT+ Editor `~/SWATPlus/Databases/` | Obtainable from SWAT+ Editor install |
| `swatplus_wgn.sqlite` | SWAT+ Editor `~/SWATPlus/Databases/` | Obtainable from SWAT+ Editor install |

**None of these files is bundled with the package** and **none has a public
machine-readable download URL** as of June 2026.
`scripts/bootstrap_reference_dbs.sh` checks whether they are present and gives
manual-installation instructions, but **cannot auto-download them**.

The planned `ai-hydro/swatplus-reference-data` GitHub mirror (referenced in
earlier bootstrap script versions) **does not exist**.

### Remote data sources (fetched at run time)

Each basin run downloads the following over the network:

| Data | Source | Notes |
|---|---|---|
| Daily streamflow | USGS NWIS API | Public, no credentials |
| Basin boundary / NHDPlus | NLDI (HyRiver) | Public |
| DEM terrain tiles | py3dep (TNM/3DEP) | Public |
| Soil mukey rasters | gNATSGO via Planetary Computer | Requires STAC API access; no auth needed |
| Meteorological forcing | GridMET | Public |

These are fetched fresh on every run. Exact source snapshots are not archived in
this repository, so output files may differ if upstream APIs change their data.

## Implication for the paper's reproducibility claims

Any reproduced run requires:

1. The SWAT+ engine binary at the correct revision (61.0.2.61 to match published
   suite; earlier rev 60.5.7 also validated but not identical output).
2. All three reference SQLite files.
3. Network access to USGS NWIS, NLDI, TNM, Planetary Computer, GridMET.

A third party cannot reproduce the 11-basin objective suite from this repository
alone — the reference databases must be obtained separately. The reproducibility
package for the associated paper (see
`docs/AGENT_GOVERNANCE_PUBLISHABLE_ROADMAP.md`) must either bundle these files
(check licensing with the SWAT+ team) or document the exact install path with a
verified checksum.

## Checksums of reference DBs used in the published suite

These will be recorded here once the wgn DB is located and the A2 positive-
control run is completed. The datasets and soils DBs currently symlinked at
`~/.swatplus_builder/reference_dbs/` match version 3.2.0 of the SWAT+ datasets
catalog (`swatplus_datasets` catalog key `"3.2.0"`).
