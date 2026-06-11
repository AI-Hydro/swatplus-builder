#!/usr/bin/env python
"""Phase 3G Sprint 1: Acquire real SSURGO soils for 03339000 via SDA API.

This script bypasses the Planetary Computer path (which fails for 03339000)
and fetches soils directly from USDA NRCS Soil Data Access.

Usage:
    python scripts/acquire_03339000_sda_soils.py \
        --basin-dir tests/_artifacts/e2e_runs/phase3f_multiyear_20260427_03339000_topology_fixed/usgs_03339000 \
        --output tests/_artifacts/phase3g_03339000_sda_soils_profiles.json

The output JSON can be used with load_external_soils.py to update project.sqlite.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Optional
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("acquire_sda_soils")


def extract_mukeys_from_artifacts(basin_dir: Path) -> set[int]:
    """Extract mukeys from HRU catalog in basin artifacts."""
    hru_catalog = basin_dir / "delin" / "hrus" / "hru_catalog.json"

    if not hru_catalog.exists():
        log.warning("HRU catalog not found at %s; attempting fallback", hru_catalog)
        return set()

    try:
        data = json.loads(hru_catalog.read_text())
        mukeys = set()

        # Navigate catalog structure: typically has "hrus" array with "soil" field
        if isinstance(data, dict):
            hrus = data.get("hrus", [])
            for hru in hrus:
                soil_id = hru.get("soil", "")
                # Soil ID format: "gnatsgo_<mukey>"
                if soil_id.startswith("gnatsgo_"):
                    try:
                        mukey = int(soil_id.removeprefix("gnatsgo_"))
                        mukeys.add(mukey)
                    except (ValueError, AttributeError):
                        pass

        log.info("Extracted %d unique mukeys from HRU catalog", len(mukeys))
        return mukeys

    except Exception as e:
        log.error("Failed to parse HRU catalog: %s", e)
        return set()


def fetch_sda_soils(mukeys: set[int], output_json: Path) -> bool:
    """Fetch real SSURGO soils from SDA API using horizon-resolved profiles."""
    if not mukeys:
        log.error("No mukeys provided")
        return False

    log.info("Fetching %d mukeys from USDA SDA API...", len(mukeys))

    try:
        # Lazy import to handle missing dependencies gracefully
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from swatplus_builder.soil.sda import fetch_sda_horizons
        from swatplus_builder.soil.models import SoilConfig, SoilProfile
        from swatplus_builder.config import Settings
    except ImportError as e:
        log.error("Failed to import soil modules: %s. Ensure PYTHONPATH includes src/", e)
        return False

    try:
        # Configure SDA to fetch real horizons, enable cache for offline reproducibility
        config = SoilConfig(
            use_sda=True,
            enable_cache=True,
            reproducible=False,  # Allow live fetches
            max_sda_mukeys=500,  # Batch size for USDA API
        )

        cache_dir = output_json.parent / "sda_cache"

        log.info("Calling fetch_sda_horizons with cache_dir=%s", cache_dir)
        profiles = fetch_sda_horizons(sorted(mukeys), config, cache_dir)

        if not profiles:
            log.error("SDA fetch returned no profiles")
            return False

        log.info("Successfully fetched %d SDA profiles", len(profiles))

        # Validate coverage
        coverage_pct = (len(profiles) / max(len(mukeys), 1)) * 100.0
        log.info("Coverage: %.1f%% (%d / %d mukeys)", coverage_pct, len(profiles), len(mukeys))

        if coverage_pct < 50.0:
            log.error("SDA coverage too low (%.1f%%); this may indicate API issues", coverage_pct)
            return False

        # Serialize profiles to JSON with metadata
        output_data = {
            "source": "sda_api_horizon_resolved",
            "acquisition_date": datetime.now(timezone.utc).isoformat(),
            "mukeys_requested": sorted(mukeys),
            "mukeys_acquired": sorted(list(profiles.keys())),
            "n_profiles": len(profiles),
            "coverage_pct": coverage_pct,
            "profiles": {},
        }

        for mk, prof in profiles.items():
            # Serialize each profile
            profile_dict = {
                "name": prof.name,
                "hyd_grp": prof.hyd_grp,
                "description": prof.description,
                "source": prof.source,
                "layers": [],
            }
            for layer in prof.layers:
                layer_data = layer.model_dump() if hasattr(layer, "model_dump") else {}
                soil_k = layer_data.get("soil_k", layer_data.get("k", 5.0))
                carbon = layer_data.get("carbon", layer_data.get("om", 1.0))
                layer_dict = {
                    "layer_num": layer_data.get("layer_num", 0),
                    "dp": layer_data.get("dp", 1000.0),
                    "rock": layer_data.get("rock", 0.0),
                    "bd": layer_data.get("bd", 1.4),
                    "awc": layer_data.get("awc", 0.15),
                    "k": soil_k,
                    "soil_k": soil_k,
                    "n": layer_data.get("n", 0.05),
                    "usle_k": layer_data.get("usle_k", 0.3),
                    "clay": layer_data.get("clay", 20.0),
                    "silt": layer_data.get("silt", 40.0),
                    "sand": layer_data.get("sand", 40.0),
                    "om": carbon,
                    "carbon": carbon,
                    "pst": layer_data.get("pst", 0.0),
                    "theta_sat": layer_data.get("theta_sat", 0.45),
                    "theta_fc": layer_data.get("theta_fc", 0.25),
                    "theta_wp": layer_data.get("theta_wp", 0.12),
                }
                profile_dict["layers"].append(layer_dict)

            output_data["profiles"][str(mk)] = profile_dict

        # Write output
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(output_data, indent=2))
        log.info("Soils written to %s", output_json)

        return True

    except Exception as e:
        log.error("SDA fetch failed: %s", e, exc_info=True)
        return False


def main(args):
    """Main entry point."""
    basin_dir = Path(args.basin_dir).resolve()
    output_json = Path(args.output).resolve()

    if not basin_dir.exists():
        log.error("Basin directory not found: %s", basin_dir)
        return False

    log.info("Phase 3G Sprint 1: Acquire 03339000 SSURGO soils via SDA")
    log.info("Basin dir: %s", basin_dir)
    log.info("Output: %s", output_json)

    # Extract mukeys from artifacts
    mukeys = extract_mukeys_from_artifacts(basin_dir)
    if not mukeys:
        log.error("Failed to extract mukeys")
        return False

    # Fetch via SDA
    success = fetch_sda_soils(mukeys, output_json)

    if success:
        log.info("✓ SDA soil acquisition complete")
    else:
        log.error("✗ SDA soil acquisition failed")

    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--basin-dir",
        required=True,
        help="Path to basin E2E artifacts directory (contains delin/hrus/hru_catalog.json)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for acquired SDA soils JSON",
    )

    args = parser.parse_args()
    success = main(args)
    sys.exit(0 if success else 1)
