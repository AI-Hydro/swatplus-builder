# Test fixtures

Small, curated fixtures live here. Do not commit large rasters.

Planned (Phase 1):

- `marsh_creek/` — USGS 01547700, ~60 km², with clipped DEM / NLCD / gNATSGO
  and a single-year GridMET subset. Target footprint: < 50 MB total.
- `golden_txtinout/` — a known-good `TxtInOut/` produced from the Marsh Creek
  fixture with a pinned vendored editor commit, used for regression diffing.

Fetch instructions will live in `Makefile` (`make fixtures`).
