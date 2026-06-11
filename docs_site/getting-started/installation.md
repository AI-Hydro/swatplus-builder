# Installation

## Requirements

- **Python ≥ 3.10**
- **SWAT+ engine binary** (`rev60+`) on `PATH` as `swatplus`, or pointed to by
  the `SWATPLUS_EXE` environment variable. The engine is **not** a pip
  dependency — you bring your own and mount it at runtime.
- **SWAT+ reference databases** (`swatplus_datasets.sqlite`,
  `swatplus_soils.sqlite`, `swatplus_wgn.sqlite`).
- **OS:** macOS or Linux. On Windows, place `swatplus.exe` on `PATH`.
- **Network access** for USGS NWIS discharge, gNATSGO soils, and weather
  forcing retrieval.

## Install from source

```bash
git clone https://github.com/AI-Hydro/swatplus-builder.git
cd swatplus-builder

python -m venv .venv && source .venv/bin/activate

# core + the extras you need (gis is required for real builds)
pip install -e ".[gis,hyriver,gridmet,soils,mcp]"
```

## Extras

| Extra | Pulls in | Needed for |
|---|---|---|
| `gis` | WhiteboxTools, rasterio, geopandas, shapely, pyproj | **Required** for any real build (delineation, HRUs) |
| `hyriver` | HyRiver stack (NLDI, py3dep, pynhd) | USGS gauge / NHDPlus / terrain retrieval |
| `gridmet` | gridMET client | Meteorological forcing |
| `soils` | gNATSGO via Planetary Computer | High-fidelity soils |
| `mcp` | `mcp` / FastMCP | The agent tool server |

```bash
# Minimal install (no GIS — limited to inspecting existing artifacts)
pip install -e .

# Everything, for development
pip install -e ".[all]"
```

!!! note "Engine binary is separate"
    `pip install` never downloads the SWAT+ engine. Provide it via `PATH`
    (`swatplus`), the `SWATPLUS_EXE` variable, or the bootstrap script in the
    next section.

## Verify the install

```bash
# from a source checkout, src/ is on the path via -e install; otherwise:
swat version
swat version --json     # machine-readable

swat health             # runtime health (engine + reference DBs)
swat health --json
```

`swat health` returns deterministic exit codes: `0` healthy, `1` degraded
(e.g. no engine mounted), `2` unhealthy. A degraded result is expected before
you bootstrap the engine and reference data — see
[Bootstrap](bootstrap.md).

Next: [Bootstrap the engine & reference data →](bootstrap.md)
