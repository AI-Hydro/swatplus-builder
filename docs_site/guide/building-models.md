# Building a model

In normal use you do not call the build stages individually — `swat workflow
run` orchestrates the entire build for you. This page explains what the build
produces and how to drive the build primitives directly from Python when you
need finer control.

## What the build produces

From a USGS gauge ID (or an explicit outlet + DEM), the build stages produce a
valid SWAT+ `TxtInOut/` directory:

1. **Delineation** — watershed boundary and stream network from the DEM
   (WhiteboxTools primary, pyflwdir secondary).
2. **HRUs** — hydrologic response units from land use × soil × slope bands.
3. **Soils** — gNATSGO profiles where available, with explicit fallback
   provenance when they are not (see [Soil fidelity](soil-fidelity.md)).
4. **Weather** — Daymet / gridMET forcing, or synthetic as a recorded fallback.
5. **Project** — SQLite database translated to `TxtInOut` via the vendored
   `swat-model/swatplus-editor` API.

## The Python build API

The public Python surface is four typed functions in
`swatplus_builder.tools`:

```python
from swatplus_builder.tools import (
    build_watershed,
    create_hrus,
    generate_swat_project,
    run_swat,
)

ws = build_watershed(
    dem_path="data/dem.tif",
    outlet=(-77.123, 41.456),
    stream_threshold_cells=500,
    workdir="runs/marsh_creek/",
)

hrus = create_hrus(ws, "data/nlcd_2019.tif", "data/gnatsgo_mukey.tif")
project = generate_swat_project(
    ws, hrus, "data/weather/", "2000-01-01", "2010-12-31", "marsh_creek_v1"
)
result = run_swat(project, threads=4)
```

These are the building blocks; the governed, end-to-end path is
[`swat workflow run`](canonical-workflow.md), which wires them together and
adds locking, calibration, verification, and the evidence bundle.

## CLI build status

!!! warning "Some standalone build subcommands are placeholders"
    The granular CLI subcommands `swat watershed`, `swat hrus`, `swat project`,
    and `swat build` are **not yet implemented** — they currently exit with a
    "Not implemented yet (Phase 1)" message and a pointer to the roadmap. Use
    `swat workflow run` for builds, or the Python API above. The implemented
    CLI commands are listed in the [CLI reference](../reference/cli.md).

## Soil realism is always recorded

Every run persists soil realism metadata (`soil_mode`,
`pct_fallback_soils`) in `metadata.json`. This is not cosmetic: fallback soils
**lower the achievable claim ceiling** under the provenance-or-degrade
invariant. See [Soil fidelity](soil-fidelity.md).
