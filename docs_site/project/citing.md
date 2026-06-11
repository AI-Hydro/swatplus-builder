# Citing & references

## Citing swatplus-builder

When you report a result produced with swatplus-builder, cite the repository
**and** the run's provenance hash, so the claim is traceable to the exact run:

> Galib, M. *swatplus-builder: headless, agent-native SWAT+ modeling with
> runtime claim governance.* AI-Hydro.
> <https://github.com/AI-Hydro/swatplus-builder>

Each run records its inputs and git SHA in `run_manifest.json` and provenance
hashes in `evidence_summary.json`. Cite the provenance hash alongside any
metric you report — a metric without its run provenance is not reproducible.

!!! tip "Report the gate context, not just the number"
    Following the project's own discipline: when you cite a metric, cite
    whether it was a *verified* metric and which claim tier it earned. See
    [Reading the evidence](../guide/reading-evidence.md).

## Upstream projects

| Project | Role here |
|---|---|
| [QSWATPlus](https://github.com/swat-model/QSWATPlus) | **Reference only** — algorithms are the specification; not imported |
| [swatplus-editor](https://github.com/swat-model/swatplus-editor) | **Vendored** — drives SQLite → `TxtInOut` (Apache-2.0) |
| [swatplus-automatic-workflow](https://github.com/celray/swatplus-automatic-workflow) | **Reference only** — editor call sequence, not its QGIS calls |
| [pySWATPlus](https://github.com/swat-model/pySWATPlus) | **Optional dep** — non-authoritative bridge (GPL-3.0) |
| [WhiteboxTools](https://github.com/jblindsay/whitebox-tools) | primary delineation backend (`gis` extra) |
| [pyflwdir](https://github.com/Deltares/pyflwdir) | secondary delineation backend (`gis` extra) |
| SWAT+ engine | external binary (`rev60+`), not bundled |
| SWAT+ reference DBs | `datasets` / `soils` / `wgn` SQLite |

A fuller reverse-engineering and reuse map is maintained in the repository at
`docs/REFERENCES.md`.

## Data sources

- **USGS NWIS** — observed discharge.
- **gNATSGO** (via Microsoft Planetary Computer) — soils.
- **Daymet / gridMET** — meteorological forcing.
