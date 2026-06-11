# Python API

Two public surfaces are stable for direct Python use: the **build** functions
and the **locked-benchmark** functions.

## Build API — `swatplus_builder.tools`

Four typed functions form the public build surface:

```python
from swatplus_builder.tools import (
    build_watershed,
    create_hrus,
    generate_swat_project,
    run_swat,
)
```

| Function | Role |
|---|---|
| `build_watershed(dem_path, outlet, stream_threshold_cells, workdir)` | delineation → watershed object |
| `create_hrus(watershed, landuse_raster, soil_raster)` | HRUs from land use × soil |
| `generate_swat_project(ws, hrus, weather_dir, start, end, name)` | SQLite → `TxtInOut` |
| `run_swat(project, threads=4)` | execute the engine |

```python
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

These are building blocks. For a governed, end-to-end run with locking,
verification, and an evidence bundle, use
[`swat workflow run`](../guide/canonical-workflow.md).

## Locked-benchmark API — `swatplus_builder.calibration.locked_benchmark`

```python
from swatplus_builder.calibration.locked_benchmark import (
    lock_benchmark,
    calibrate_against_lock,
    verify_calibration,
    build_readiness_table,
)

lock = lock_benchmark(txtinout_dir, obs_series, out_dir,
                      basin_id="usgs_01547700", outlet_gis_id=1)
evidence = calibrate_against_lock(lock, base_txtinout, out_dir,
                                  parameters=["CN2", "ALPHA_BF"])
result = verify_calibration(lock, evidence.best_solution_json, base_txtinout, out_dir)
rows = build_readiness_table(locks_root)
```

| Function | Role |
|---|---|
| `lock_benchmark(...)` | seal baseline + observed series with hashes |
| `calibrate_against_lock(...)` | search candidates behind the volume gate |
| `verify_calibration(...)` | independent rerun of the promoted artifact (authoritative) |
| `build_readiness_table(locks_root)` | suite-level readiness rows |

See [Locked calibration](../concepts/locked-calibration.md) for the protocol
these functions implement and why the verification step is the authoritative
one.

## Metric authority

All reported hydrologic metrics route through `evaluate_run`. Do not read
metrics off optimizer history or bridge objective values — they are
non-authoritative by design.
