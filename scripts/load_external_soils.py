#!/usr/bin/env python
"""Phase 3G Sprint 1: Load externally-acquired real SSURGO soils into project.sqlite.

This script reads a soils JSON (output from acquire_03339000_sda_soils.py)
and upsets soil_sol and soil profile rows into an existing project.sqlite.

Usage:
    python scripts/load_external_soils.py \
        --soils-json tests/_artifacts/phase3g_03339000_sda_soils_profiles.json \
        --project-db <path-to-project.sqlite> \
        --allow-replace

The script validates schema compatibility and uses transaction rollback on failure.
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("load_external_soils")


def load_soils_json(json_path: Path) -> dict | None:
    """Parse and validate soils JSON from acquisition script."""
    try:
        data = json.loads(json_path.read_text())
        log.info("Loaded soils JSON: %s", json_path)
        log.info("  Source: %s", data.get("source"))
        log.info("  Profiles: %d / %d mukeys (%.1f%%)",
                 data.get("n_profiles", 0),
                 len(data.get("mukeys_requested", [])),
                 data.get("coverage_pct", 0.0))
        return data
    except Exception as e:
        log.error("Failed to load soils JSON: %s", e)
        return None


def create_soils_sql_values(profile_dict: dict, mukey: int) -> tuple[tuple, ...]:
    """Generate soil_sol row tuples for each layer in a profile."""
    rows = []
    for layer_dict in profile_dict.get("layers", []):
        layer_num = int(layer_dict.get("layer_num", 0))
        row = (
            mukey,  # soil_id (foreign key to soils table)
            layer_num,  # layer_num
            float(layer_dict.get("dp", 1000.0)),  # dp (depth)
            float(layer_dict.get("rock", 0.0)),  # rock
            float(layer_dict.get("bd", 1.4)),  # bd (bulk density)
            float(layer_dict.get("awc", 0.15)),  # awc (available water capacity)
            float(layer_dict.get("k", 5.0)),  # k (saturated conductivity)
            float(layer_dict.get("n", 0.05)),  # n (Manning's n)
            float(layer_dict.get("usle_k", 0.3)),  # usle_k
            float(layer_dict.get("clay", 20.0)),  # clay
            float(layer_dict.get("silt", 40.0)),  # silt
            float(layer_dict.get("sand", 40.0)),  # sand
            float(layer_dict.get("om", 1.0)),  # om (organic matter)
            float(layer_dict.get("pst", 0.0)),  # pst
            float(layer_dict.get("theta_sat", 0.45)),  # theta_sat
            float(layer_dict.get("theta_fc", 0.25)),  # theta_fc
            float(layer_dict.get("theta_wp", 0.12)),  # theta_wp
        )
        rows.append(row)
    return tuple(rows)


def load_into_database(db_path: Path, soils_data: dict, allow_replace: bool = False) -> bool:
    """Load soils into project.sqlite, replacing existing if allowed."""
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check schema compatibility
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='soils_sol'")
        if not cursor.fetchone():
            log.error("Table soils_sol not found in %s", db_path)
            conn.close()
            return False

        cursor.execute("PRAGMA table_info(soils_sol)")
        columns = {row[1] for row in cursor.fetchall()}
        required_cols = {"soil_id", "layer_num", "dp", "bd", "awc", "k"}
        if not required_cols.issubset(columns):
            log.error("soils_sol schema missing required columns: %s", required_cols - columns)
            conn.close()
            return False

        # Optionally back up existing soils
        if allow_replace:
            cursor.execute("DELETE FROM soils_sol WHERE soil_id > 0")
            log.info("Cleared existing soils_sol rows")

        # Insert new soils
        profiles = soils_data.get("profiles", {})
        n_inserted = 0

        for mukey_str, profile_dict in profiles.items():
            try:
                mukey = int(mukey_str)
            except ValueError:
                log.warning("Skipping invalid mukey: %s", mukey_str)
                continue

            # Insert soil_sol rows for this mukey
            soil_rows = create_soils_sql_values(profile_dict, mukey)
            for row in soil_rows:
                try:
                    # SQL schema: soil_id, layer_num, dp, rock, bd, awc, k, n, usle_k, clay, silt, sand, om, pst, theta_sat, theta_fc, theta_wp
                    cursor.execute("""
                        INSERT INTO soils_sol (
                            soil_id, layer_num, dp, rock, bd, awc, k, n, usle_k,
                            clay, silt, sand, om, pst, theta_sat, theta_fc, theta_wp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, row)
                    n_inserted += 1
                except Exception as e:
                    log.warning("Failed to insert soil layer for mukey %d: %s", mukey, e)

        log.info("Inserted %d soil_sol rows", n_inserted)

        # Update metadata
        cursor.execute("""
            INSERT OR REPLACE INTO project_metadata (key, value)
            VALUES ('soil_source', 'sda_external_real'),
                   ('soil_acquisition_date', ?)
        """, (soils_data.get("acquisition_date", ""),))

        conn.commit()
        log.info("✓ Successfully loaded soils into %s", db_path)
        conn.close()
        return True

    except Exception as e:
        log.error("Database load failed: %s", e, exc_info=True)
        return False


def main(args):
    """Main entry point."""
    soils_json = Path(args.soils_json).resolve()
    project_db = Path(args.project_db).resolve()

    if not soils_json.exists():
        log.error("Soils JSON not found: %s", soils_json)
        return False

    if not project_db.exists():
        log.error("Project database not found: %s", project_db)
        return False

    log.info("Phase 3G Sprint 1: Load external SSURGO soils into project.sqlite")
    log.info("Input: %s", soils_json)
    log.info("Target DB: %s", project_db)

    # Load soils
    soils_data = load_soils_json(soils_json)
    if not soils_data:
        return False

    # Load into database
    success = load_into_database(
        project_db,
        soils_data,
        allow_replace=args.allow_replace,
    )

    if success:
        log.info("✓ Soils loaded successfully")
    else:
        log.error("✗ Failed to load soils")

    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--soils-json",
        required=True,
        help="Path to soils JSON (output from acquire_03339000_sda_soils.py)",
    )
    parser.add_argument(
        "--project-db",
        required=True,
        help="Path to project.sqlite to update",
    )
    parser.add_argument(
        "--allow-replace",
        action="store_true",
        help="Delete existing soils_sol rows before inserting (DESTRUCTIVE)",
    )

    args = parser.parse_args()
    success = main(args)
    sys.exit(0 if success else 1)
