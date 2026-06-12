# Citing & references

## How to cite swatplus-builder

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20650908.svg)](https://doi.org/10.5281/zenodo.20650908)

When you report a result produced with swatplus-builder, cite the software
**and** the run's provenance hash, so the claim is traceable to the exact run.

### BibTeX

```bibtex
@software{galib_swatplus_builder_2026,
  author       = {Galib, Mohammad and Merwade, Venkatesh},
  title        = {{swatplus-builder: Claim-governed SWAT+ hydrologic
                   modeling from a USGS gauge ID}},
  year         = {2026},
  publisher    = {Zenodo},
  version      = {0.4.0},
  doi          = {10.5281/zenodo.20650908},
  url          = {https://doi.org/10.5281/zenodo.20650908}
}
```

### Plain text

> Galib, M. & Merwade, V. (2026). *swatplus-builder: Claim-governed SWAT+
> hydrologic modeling from a USGS gauge ID* (v0.4.0). Zenodo.
> https://doi.org/10.5281/zenodo.20650908

!!! tip "Report the gate context, not just the number"
    Following the project's own discipline: when you cite a metric, also cite
    whether it was a *verified* metric and which claim tier it earned. Each run
    records its inputs, git SHA, and provenance hashes in `run_manifest.json`
    and `evidence_summary.json`. See [Reading the evidence](../guide/reading-evidence.md).

---

## Upstream projects

| Project | Role here |
|---|---|
| [QSWATPlus](https://github.com/swat-model/QSWATPlus) | **Reference only** — algorithms are the specification; not imported |
| [swatplus-editor](https://github.com/swat-model/swatplus-editor) | **Vendored** — drives SQLite → `TxtInOut` (Apache-2.0) |
| [swatplus-automatic-workflow](https://github.com/celray/swatplus-automatic-workflow) | **Reference only** — editor call sequence, not its QGIS calls |
| [pySWATPlus](https://github.com/swat-model/pySWATPlus) | **Optional dep** — non-authoritative bridge (GPL-3.0) |
| [WhiteboxTools](https://github.com/jblindsay/whitebox-tools) | Primary delineation backend (`gis` extra) |
| [pyflwdir](https://github.com/Deltares/pyflwdir) | Secondary delineation backend (`gis` extra) |
| SWAT+ engine | External binary (`rev60+`), not bundled |
| SWAT+ reference DBs | `datasets` / `soils` / `wgn` SQLite |

## Data sources

- **USGS NWIS** — observed discharge.
- **gNATSGO** (via Microsoft Planetary Computer) — soils.
- **Daymet / gridMET** — meteorological forcing.
