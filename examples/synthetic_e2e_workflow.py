"""End-to-end Phase 2 demo: synthetic watershed → TxtInOut/ via SWAT+ Editor.

Runs the full pipeline without any network / external data:

1. Fabricate a tiny 2-subbasin watershed (DEM + subbasins GPKG +
   channels GPKG + routing graph + outlet).
2. Fabricate landuse and soil rasters with known class mixes.
3. ``gis.hru.create_hrus`` — dominant-mode HRU overlay.
4. ``gis.tables.build_tables`` — assemble typed :class:`GisTables`.
5. ``db.project.create_project_db`` + ``db.writer.write_all`` —
   write a real project.sqlite with the ``gis_*`` tables populated.
6. ``db.mock_datasets.create_mock_datasets_db`` — create a minimal
   swatplus_datasets.sqlite with enough data for LTE mode.
7. ``db.seed.seed_minimal_soils`` — seed soil tables in the project DB.
8. ``editor.api.setup_project(is_lte=True)`` — run SWAT+ Editor to
   import GIS tables and produce all model connection tables.
9. ``editor.api.write_files`` — generate the full TxtInOut/ directory.

Prints every generated file path and the count of rows written to
each table. Useful as:

* A smoke test that the end-to-end stack still connects.
* A reference for building real-data pipelines from live DEMs.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from swatplus_builder.db.mock_datasets import create_mock_datasets_db
from swatplus_builder.db.project import create_project_db
from swatplus_builder.db.seed import seed_minimal_soils
from swatplus_builder.db.writer import write_all
from swatplus_builder.editor.api import setup_project, write_files
from swatplus_builder.gis.hru import create_hrus
from swatplus_builder.gis.tables import build_tables
from swatplus_builder.types import WatershedResult

CRS_UTM = "EPSG:32617"
PIXEL = 30.0
ORIGIN = (500_000.0, 4_500_000.0)
N_ROWS, N_COLS = 8, 8


def _write_raster(
    path: Path,
    arr: np.ndarray,
    *,
    nodata: float | int | None = 0,
    dtype: str | None = None,
) -> Path:
    transform = from_origin(ORIGIN[0], ORIGIN[1], PIXEL, PIXEL)
    out_dtype = dtype or str(arr.dtype)
    profile = {
        "driver": "GTiff", "height": arr.shape[0], "width": arr.shape[1],
        "count": 1, "dtype": out_dtype, "crs": CRS_UTM, "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(out_dtype), 1)
    return path


def _subbasin_box(col_start: int, col_stop: int):
    minx = ORIGIN[0] + col_start * PIXEL
    maxx = ORIGIN[0] + col_stop * PIXEL
    maxy = ORIGIN[1]
    miny = ORIGIN[1] - N_ROWS * PIXEL
    return box(minx, miny, maxx, maxy)


def main(out_dir: Path) -> None:
    workdir = out_dir / "ws"
    (workdir / "rasters").mkdir(parents=True, exist_ok=True)
    (workdir / "shapes").mkdir(exist_ok=True)

    # --- DEM: gradient 100 m → 40 m ---
    rows, cols = np.meshgrid(
        np.arange(N_ROWS), np.arange(N_COLS), indexing="ij"
    )
    dem = (100.0 - 3.5 * rows - 3.5 * cols).astype("float32")
    dem_path = _write_raster(
        workdir / "rasters" / "dem.tif", dem, nodata=-9999.0, dtype="float32"
    )

    # --- Subbasins GPKG ---
    subs_gdf = gpd.GeoDataFrame(
        {"sub_id": [1, 2]},
        geometry=[_subbasin_box(0, 4), _subbasin_box(4, 8)],
        crs=CRS_UTM,
    )
    subs_path = workdir / "shapes" / "subbasins.gpkg"
    subs_gdf.to_file(subs_path, driver="GPKG")

    # --- Channels GPKG ---
    cha1 = LineString([(ORIGIN[0] + 2 * PIXEL, ORIGIN[1]),
                       (ORIGIN[0] + 2 * PIXEL, ORIGIN[1] - 8 * PIXEL)])
    cha2 = LineString([(ORIGIN[0] + 6 * PIXEL, ORIGIN[1]),
                       (ORIGIN[0] + 6 * PIXEL, ORIGIN[1] - 8 * PIXEL)])
    channels_gdf = gpd.GeoDataFrame(
        {
            "sub_id": [1, 2], "link_id": [101, 102],
            "length_m": [240.0, 240.0], "slope_m_m": [0.01, 0.02],
            "width_m": [2.5, 3.0], "depth_m": [0.3, 0.4],
            "elev_min_m": [72.5, 40.0], "elev_max_m": [100.0, 85.0],
        },
        geometry=[cha1, cha2], crs=CRS_UTM,
    )
    channels_path = workdir / "shapes" / "channels.gpkg"
    channels_gdf.to_file(channels_path, driver="GPKG")

    # --- Outlet GPKG ---
    outlets_path = workdir / "shapes" / "outlets.gpkg"
    gpd.GeoDataFrame(
        {"outlet_id": [1]},
        geometry=[Point(ORIGIN[0] + 6 * PIXEL, ORIGIN[1] - 8 * PIXEL)],
        crs=CRS_UTM,
    ).to_file(outlets_path, driver="GPKG")

    # --- Routing graph: 101 → 102 → outlet ---
    g = nx.DiGraph()
    g.add_node(101); g.add_node(102); g.add_edge(101, 102)
    routing_path = workdir / "routing.graphml"
    nx.write_graphml(g, routing_path)

    # --- Landuse raster ---
    lu = np.full((N_ROWS, N_COLS), 10, dtype="int32")
    lu[:, 0:3] = 10   # sub 1 (cols 0..2) = forest
    lu[:, 3] = 20     # sub 1 (col 3) = pasture
    lu[:, 4:] = 30    # sub 2 = agriculture
    landuse_path = _write_raster(
        workdir / "rasters" / "landuse.tif", lu, nodata=0, dtype="int32"
    )

    # --- Soil raster (mukey) ---
    soil = np.full((N_ROWS, N_COLS), 12345, dtype="int32")
    soil_path = _write_raster(
        workdir / "rasters" / "soil.tif", soil, nodata=0, dtype="int32"
    )

    # --- Wrap into a WatershedResult ---
    ws = WatershedResult(
        workdir=workdir, crs=CRS_UTM,
        dem_conditioned=dem_path, flow_dir=dem_path, flow_acc=dem_path,
        streams_raster=dem_path,
        subbasins_vector=subs_path, channels_vector=channels_path,
        outlets_vector=outlets_path, routing_graph=routing_path,
        stats={"n_subbasins": 2.0},
    )

    # =================================================================
    # 1. HRU overlay
    # =================================================================
    hru_result = create_hrus(
        ws, landuse_path, soil_path,
        landuse_lookup={10: "FRST", 20: "PAST", 30: "AGRR"},
    )

    # =================================================================
    # 2. Build GisTables
    # =================================================================
    tables = build_tables(ws, hru_result)

    # =================================================================
    # 3. Datasets DB (mock) + project.sqlite
    # =================================================================
    project_dir = out_dir / "project"
    project_dir.mkdir(exist_ok=True)

    # Collect unique landuse codes from the HRU overlay (lower-cased)
    landuses = sorted({h.landuse.lower() for h in tables.hrus})
    datasets_db = create_mock_datasets_db(
        out_dir / "swatplus_datasets.sqlite",
        landuses=landuses,
    )

    db_path = create_project_db("demo", project_dir, overwrite=True,
                                reference_db=datasets_db)
    counts = write_all(db_path, tables)
    seed_minimal_soils(db_path, {h.soil for h in tables.hrus})

    # =================================================================
    # 4. SWAT+ Editor: setup_project + write_files (LTE mode)
    # =================================================================
    setup_project(db_path, is_lte=True, timeout=120.0)
    wf = write_files(db_path, timeout=120.0)
    txtinout = wf.txtinout_dir

    # =================================================================
    # Report
    # =================================================================
    print("\n" + "=" * 72)
    print("Phase 2 end-to-end demo complete (LTE mode)")
    print("=" * 72)
    print(f"\nWorkdir:  {workdir}")
    print(f"Project:  {project_dir}")
    print(f"Datasets: {datasets_db}")
    print(f"TxtInOut: {txtinout}\n")

    print("─── GIS stage ─────────────────────────────────────────────────────────")
    for label, p in [
        ("DEM",              dem_path),
        ("Landuse raster",   landuse_path),
        ("Soil raster",      soil_path),
        ("Subbasins GPKG",   subs_path),
        ("Channels GPKG",    channels_path),
        ("Outlets GPKG",     outlets_path),
        ("Routing graph",    routing_path),
    ]:
        print(f"  {label:18}  {p}")

    print("\n─── HRU stage ─────────────────────────────────────────────────────────")
    for label, p in [
        ("LSUs GPKG",        hru_result.lsus_vector),
        ("HRUs GPKG",        hru_result.hrus_vector),
        ("HRU id raster",    hru_result.hru_raster),
        ("HRU catalog JSON", hru_result.catalog_path),
    ]:
        print(f"  {label:18}  {p}")
    print(f"  → stats: n_lsus={int(hru_result.stats['n_lsus'])}, "
          f"n_hrus={int(hru_result.stats['n_hrus'])}, "
          f"total_hru_area_ha={hru_result.stats['total_hru_area_ha']:.2f}")

    print("\n─── DB stage ──────────────────────────────────────────────────────────")
    print(f"  Project DB         {db_path}")
    print("  Rows written:")
    for tbl, n in counts.items():
        print(f"    gis_{tbl:<15} {n}")

    print("\n─── Editor + TxtInOut ─────────────────────────────────────────────────")
    print(f"  TxtInOut/          {txtinout}")
    txtfiles = sorted(txtinout.iterdir())
    print(f"  Files produced:    {len(txtfiles)}")
    key_files = ["file.cio", "time.sim", "object.cnt", "plants.plt",
                 "soils_lte.sol", "hru-lte.hru", "hru-lte.con", "chandeg.con"]
    for kf in key_files:
        status = "EXISTS" if (txtinout / kf).is_file() else "MISSING"
        print(f"    {kf:<20} {status}")

    # Query the DB to show a couple of real rows the way the editor will see them.
    print("\n─── Sample DB rows (post-write) ───────────────────────────────────────")
    with sqlite3.connect(db_path) as conn:
        hrus = conn.execute(
            "SELECT id, lsu, landuse, soil, slp, arslp, slope FROM gis_hrus "
            "ORDER BY id"
        ).fetchall()
        print("  gis_hrus:")
        print("    id | lsu | landuse | soil          | slp  | arslp | slope")
        for h in hrus:
            print(
                f"    {h[0]:<2} | {h[1]:<3} | {h[2]:<7} | {h[3]:<13} | "
                f"{h[4]:<4} | {h[5]:<5} | {h[6]:.2f}"
            )

        routing = conn.execute(
            "SELECT sourceid, sourcecat, hyd_typ, sinkid, sinkcat, percent "
            "FROM gis_routing ORDER BY sourcecat, sourceid"
        ).fetchall()
        print("\n  gis_routing:")
        print("    src_id | src_cat | hyd | sink_id | sink_cat | pct")
        for r in routing:
            print(
                f"    {r[0]:<6} | {r[1]:<7} | {r[2]:<3} | {r[3]:<7} | "
                f"{r[4]:<8} | {r[5]:.0f}"
            )

        (flag_delin,) = conn.execute(
            "SELECT delineation_done FROM project_config"
        ).fetchone()
    print(f"\n  project_config.delineation_done = {flag_delin}")
    print("=" * 72)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_output")
    out.mkdir(exist_ok=True)
    main(out.resolve())
