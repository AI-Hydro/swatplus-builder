#!/usr/bin/env python
"""Diagnose why 03339000 gNATSGO fetch is failing and attempt manual acquisition.

Usage:
    python scripts/diagnose_03339000_soils.py <output_dir>
"""

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("diagnose_soils")

STATION_ID = "03339000"
EXPECTED_AREA_KM2 = 3340.9


def main(outdir: Path):
    """Diagnose 03339000 soil fetch issues."""
    outdir.mkdir(parents=True, exist_ok=True)

    # Import after logging is configured
    from swatplus_builder.gis.delineation import resolve_usgs_outlet
    from swatplus_builder.gis.soil import fetch_mukey_raster, extract_unique_mukeys
    from swatplus_builder.soil.builder import fetch_soil_profiles_result
    from swatplus_builder.soil.models import SoilConfig
    from swatplus_builder.config import Settings
    import geopandas as gpd
    import pynhd

    # 1. Fetch basin boundary
    log.info("Fetching basin boundary for %s...", STATION_ID)
    basin = pynhd.get_basin(f"USGS-{STATION_ID}")
    basin_gpkg = outdir / "basin_boundary.gpkg"
    basin.to_file(basin_gpkg, driver="GPKG")
    basin_area_km2 = float(basin.to_crs('EPSG:5070').area.sum() / 1e6)
    log.info("Basin area: %.1f km²", basin_area_km2)

    # 2. Fetch mukey raster
    log.info("Fetching mukey raster from Planetary Computer...")
    mukey_tif = outdir / "mukey.tif"
    boundary_geom = basin.to_crs("EPSG:4326").union_all()

    try:
        fetch_mukey_raster(
            boundary=boundary_geom,
            boundary_crs="EPSG:4326",
            output_path=mukey_tif,
        )
        log.info("Mukey raster saved to %s", mukey_tif)
    except Exception as e:
        log.error("Mukey raster fetch failed: %s", e, exc_info=True)
        return

    # 3. Extract mukeys
    log.info("Extracting unique mukeys from raster...")
    try:
        mukeys = extract_unique_mukeys(mukey_tif)
        log.info("Found %d unique mukeys: %s", len(mukeys), sorted(list(mukeys))[:20])
    except Exception as e:
        log.error("Mukey extraction failed: %s", e, exc_info=True)
        return

    # 4. Try to fetch gNATSGO profiles
    log.info("Attempting gNATSGO profile fetch for %d mukeys...", len(mukeys))
    settings = Settings(reference_db_dir=outdir / "reference_dbs")

    try:
        soil_config = SoilConfig(use_sda=True)
        soil_res = fetch_soil_profiles_result(mukeys, config=soil_config, settings=settings)
        log.info("Successfully fetched %d soil profiles", len(soil_res.profiles))
        log.info("Soil report: %s", json.dumps(soil_res.soil_report, indent=2))

        # Save results
        report_path = outdir / "soil_fetch_report.json"
        report_path.write_text(json.dumps({
            "mukeys_requested": len(mukeys),
            "profiles_fetched": len(soil_res.profiles),
            "soil_report": soil_res.soil_report,
            "success": True,
        }, indent=2))
        log.info("Report saved to %s", report_path)

    except Exception as e:
        log.error("gNATSGO fetch failed: %s", e, exc_info=True)

        # Try alternative approach: fetch using gNATSGO directly with pystac-client
        log.info("\nAttempting fallback: direct Planetary Computer access...")
        try:
            import pystac_client
            import planetary_computer

            # Query the gNATSGO STAC collection directly
            catalog = pystac_client.Client.open(
                "https://planetarycomputer.microsoft.com/api/stac/v1"
            )
            collection = catalog.get_collection("gnatsgo-rasters")

            log.info("gNATSGO rasters collection found")

            # Check what's available
            search = catalog.search(
                collections=["gnatsgo-rasters"],
                bbox=[
                    boundary_geom.bounds[0],
                    boundary_geom.bounds[1],
                    boundary_geom.bounds[2],
                    boundary_geom.bounds[3],
                ],
            )
            items = list(search.get_items())
            log.info("Found %d gNATSGO items in bbox", len(items))
            for item in items[:5]:
                log.info("  - %s", item.id)

        except Exception as e2:
            log.error("Fallback approach also failed: %s", e2, exc_info=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outdir", type=Path, help="Output directory")
    args = parser.parse_args()
    main(args.outdir)
