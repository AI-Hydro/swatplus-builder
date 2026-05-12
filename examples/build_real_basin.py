"""End-to-end real-basin demo for a USGS basin.

Defaults to Marsh Creek at Blanchard, PA (USGS 01547700), but the
workflow is basin-generic and can be driven by ``USGS_ID``.

Drives the full ``swatplus-builder`` pipeline against **real data**:

1. **Basin boundary** — USGS NLDI via ``pynhd``.
2. **DEM** — USGS 3DEP 30 m via ``py3dep``.
3. **Landuse** — NLCD 2021 via ``pygeohydro``.
4. **Delineation** — WhiteboxTools D8 → subbasins/channels/routing.
5. **Soils** — gNATSGO mukey raster via Planetary Computer, then
   horizon-resolved ``Soils_sol`` via
   :func:`swatplus_builder.soil.gnatsgo.fetch_gnatsgo_profiles`.
6. **HRUs** — dominant overlay on NLCD × mukey × slope.
7. **GisTables** — wrap into typed rows.
8. **Project DB** — ``create_project_db`` + ``write_all``.
9. **Weather** — GridMET (configurable window, default 1 year).
10. **Editor** — ``setup_project(is_lte=True)`` + ``import_weather_observed``
    + ``write_files`` → ``TxtInOut/``.
11. **Engine run** (optional) — only if ``SWATPLUS_EXE`` is set.

Run:

    python examples/build_real_basin.py /tmp/usgs_basin

Every stage prints the artifact paths it produced so you can inspect
them on disk.

Network + disk requirements:

* ~200 MB free under the output directory (DEM + NLCD + gNATSGO +
  weather + TxtInOut).
* Unrestricted access to ``usgs.gov``, ``mrlc.gov``,
  ``planetarycomputer.microsoft.com``, ``thredds.daac.ornl.gov``,
  and ``raw.githubusercontent.com``.
* Runtime: ~3–10 min on a residential connection.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
STATION_ID = os.environ.get("USGS_ID", "01547700").strip()
log = logging.getLogger(f"swat_build_{STATION_ID}")
EXPECTED_AREA_KM2 = float(
    os.environ.get(
        "EXPECTED_AREA_KM2",
        "114.0" if STATION_ID == "01547700" else "0.0",
    )
)
SIM_START = "2015-01-01"
SIM_END = "2015-12-31"
DEM_RESOLUTION_M = 30

# Resolve binary location
BIN_DIR = Path(__file__).parent.parent / "bin"
EXE_PATH = BIN_DIR / "swatplus_exe"
if EXE_PATH.exists():
    os.environ["SWATPLUS_EXE"] = str(EXE_PATH.resolve())


def _section(title: str) -> None:
    print("\n" + "─" * 72)
    print(f"  {title}")
    print("─" * 72)


def _ok(msg: str, *, elapsed: float | None = None) -> None:
    suffix = f"  ({elapsed:.1f}s)" if elapsed is not None else ""
    print(f"  ✓ {msg}{suffix}")


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _topology_suspicious(ws_stats: dict) -> bool:
    n_sub = int(ws_stats.get("n_subbasins", 0) or 0)
    n_cha = int(ws_stats.get("n_channels", 0) or 0)
    if n_sub <= 0 or n_cha <= 0:
        return True
    if n_cha > 20 * max(n_sub, 1):
        return True
    if float(ws_stats.get("total_area_km2", 0.0) or 0.0) > 5.0 and n_sub < 3:
        return True
    return False


def _with_retries(label: str, fn, *args, **kwargs):
    """Run fn with exponential backoff + jitter and return (result, attempts)."""
    max_attempts = int(os.environ.get("SWATPLUS_FETCH_MAX_ATTEMPTS", "4"))
    base_s = float(os.environ.get("SWATPLUS_FETCH_RETRY_BASE_S", "1.0"))
    cap_s = float(os.environ.get("SWATPLUS_FETCH_RETRY_CAP_S", "20.0"))
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(*args, **kwargs), attempt
        except Exception as exc:
            if attempt >= max_attempts:
                raise RuntimeError(f"{label} failed after {attempt} attempts: {exc}") from exc
            delay = min(cap_s, base_s * (2 ** (attempt - 1)))
            jitter = random.uniform(0.0, max(0.1, delay * 0.25))
            sleep_s = delay + jitter
            log.warning(
                "%s attempt %d/%d failed: %s; retrying in %.1fs",
                label,
                attempt,
                max_attempts,
                exc,
                sleep_s,
            )
            time.sleep(sleep_s)


def _scale_lte_soil_scon(txtinout_dir: Path, scale: float) -> int:
    """Scale LTE soil saturated-conductivity values in ``soils_lte.sol``."""
    p = txtinout_dir / "soils_lte.sol"
    if not p.exists() or abs(scale - 1.0) < 1e-9:
        return 0
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        return 0
    header = lines[1].split()
    if "scon" not in header:
        return 0
    idx = header.index("scon")
    out: list[str] = []
    updated = 0
    for i, ln in enumerate(lines):
        if i < 2 or not ln.strip():
            out.append(ln)
            continue
        parts = ln.split()
        if len(parts) <= idx:
            out.append(ln)
            continue
        scon = float(parts[idx])
        parts[idx] = f"{max(0.05, min(250.0, scon * scale)):.5f}"
        updated += 1
        out.append("  " + "       ".join(parts))
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return updated


def _set_lte_hru_column(txtinout_dir: Path, column: str, value: float) -> int:
    """Set one column across all rows in ``hru-lte.hru``."""
    p = txtinout_dir / "hru-lte.hru"
    if not p.exists():
        return 0
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        return 0
    header = lines[1].split()
    if column not in header:
        return 0
    idx = header.index(column)
    out: list[str] = []
    updated = 0
    for i, ln in enumerate(lines):
        if i < 2 or not ln.strip():
            out.append(ln)
            continue
        parts = ln.split()
        if len(parts) <= idx:
            out.append(ln)
            continue
        parts[idx] = f"{value:.5f}"
        updated += 1
        out.append("  " + "       ".join(parts))
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return updated


def _patch_lte_hru_channel_transfer_scale(
    txtinout_dir: Path,
    correction_factor: float = 0.01,
) -> int:
    """Patch hru-lte.con frac to cancel SWAT+ LTE engine ×100 transfer-scale bug.

    Evidence: SWAT+ v2023.60.5.7 computes HRU-lte-to-channel inflow as
    ``water_yield_mm * 1000 * area_ha`` instead of the correct
    ``water_yield_mm * 10 * area_ha``, producing exactly 100× too much
    volume per channel.  Setting the connection fraction to *correction_factor*
    (default 0.01) cancels the engine bug::

        engine_channel_inflow = (water_yield * buggy_100x) * frac
                              = water_yield * 100 * 0.01
                              = water_yield                 (correct)

    Returns the number of rows modified.
    """
    p = txtinout_dir / "hru-lte.con"
    if not p.exists():
        return 0
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        return 0

    header = lines[1].split()
    if "frac" not in header:
        return 0
    frac_idx = header.index("frac")

    out: list[str] = []
    updated = 0
    for i, ln in enumerate(lines):
        if i < 2 or not ln.strip():
            out.append(ln)
            continue
        parts = ln.split()
        if len(parts) <= frac_idx:
            out.append(ln)
            continue
        parts[frac_idx] = f"{correction_factor:.5f}"
        updated += 1
        out.append("  " + "       ".join(parts))
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return updated


def _load_external_soil_profiles(json_path: Path, mukeys: list[int]):
    """Load pre-acquired soil profiles and fill missing mukeys with defaults."""
    import json

    from swatplus_builder.soil.params import horizon_from_chorizon
    from swatplus_builder.types import SoilHorizon, SoilProfile

    data = json.loads(json_path.read_text(encoding="utf-8"))
    requested = set(mukeys)
    profiles_by_mukey: dict[int, SoilProfile] = {}

    for mukey_raw, profile_dict in data.get("profiles", {}).items():
        try:
            mukey = int(mukey_raw)
        except (TypeError, ValueError):
            continue
        if mukey not in requested:
            continue

        layers = [
            SoilHorizon(
                layer_num=int(layer.get("layer_num", idx + 1)),
                dp=float(layer.get("dp", 1000.0)),
                bd=float(layer.get("bd", 1.4)),
                awc=float(layer.get("awc", 0.15)),
                soil_k=float(layer.get("soil_k", layer.get("k", 5.0))),
                carbon=float(layer.get("carbon", layer.get("om", 1.0))),
                clay=float(layer.get("clay", 20.0)),
                silt=float(layer.get("silt", 40.0)),
                sand=float(layer.get("sand", 40.0)),
                rock=float(layer.get("rock", 0.0)),
                alb=float(layer.get("alb", 0.13)),
                usle_k=float(layer.get("usle_k", 0.3)),
                ec=float(layer.get("ec", 0.0)),
                caco3=layer.get("caco3"),
                ph=layer.get("ph"),
            )
            for idx, layer in enumerate(profile_dict.get("layers", []))
        ]
        if not layers:
            continue

        profiles_by_mukey[mukey] = SoilProfile(
            name=str(profile_dict.get("name") or f"gnatsgo_{mukey}"),
            hyd_grp=_valid_hyd_group(profile_dict.get("hyd_grp")),
            texture=profile_dict.get("texture"),
            description=profile_dict.get("description"),
            source=str(profile_dict.get("source") or data.get("source") or "external_soil_json"),
            layers=layers,
        )

    missing = sorted(requested - set(profiles_by_mukey))
    fallback_profiles = []
    if missing:
        fallback_profiles = [
            SoilProfile(
                name=f"gnatsgo_{mk}",
                hyd_grp="D",
                description="external soil JSON missing mukey; deterministic local fallback",
                source="external_soil_json_missing_fallback",
                layers=[
                    horizon_from_chorizon(
                        layer_num=1,
                        hzdepb_cm=30.0,
                        sandtotal_r=40.0,
                        silttotal_r=40.0,
                        claytotal_r=20.0,
                        ksat_umps=5.0,
                        dbthirdbar=1.4,
                        wthirdbar_pct=30.0,
                        wfifteenbar_pct=15.0,
                        om_r=1.0,
                    ),
                    horizon_from_chorizon(
                        layer_num=2,
                        hzdepb_cm=100.0,
                        sandtotal_r=40.0,
                        silttotal_r=40.0,
                        claytotal_r=20.0,
                        ksat_umps=5.0,
                        dbthirdbar=1.4,
                        wthirdbar_pct=30.0,
                        wfifteenbar_pct=15.0,
                        om_r=1.0,
                    ),
                ],
            )
            for mk in missing
        ]

    profiles = [profiles_by_mukey[mk] for mk in sorted(profiles_by_mukey)] + fallback_profiles
    soil_report = {
        "source": "external_soil_json",
        "external_json": str(json_path),
        "requested_mukeys": len(mukeys),
        "profiles_written": len(profiles),
        "external_profiles": len(profiles_by_mukey),
        "external_coverage_pct": len(profiles_by_mukey) / max(len(set(mukeys)), 1),
        "aggregated": {"default_fallback": len(missing)},
        "missing_mukeys": missing,
    }
    return profiles, soil_report


def _valid_hyd_group(value: object) -> str:
    if value is None:
        return "D"
    if isinstance(value, float) and np.isnan(value):
        return "D"
    code = str(value).strip().upper()
    if code in {"", "NAN", "NONE", "NULL"}:
        return "D"
    return code if code in {"A", "B", "C", "D"} else "D"


def _normalize_soil_profiles_hydgrp(profiles):
    """Normalize hydrologic group codes in-place to A/B/C/D."""
    fixed = 0
    for p in profiles:
        raw = getattr(p, "hyd_grp", None)
        norm = _valid_hyd_group(raw)
        if raw != norm:
            setattr(p, "hyd_grp", norm)
            fixed += 1
    return fixed


def _fiona_safe_gdf(gdf):
    """Return a copy with pandas extension dtypes Fiona can infer.

    GeoPandas 0.14 + Fiona 1.10 cannot infer pandas 3 nullable dtypes such as
    ``StringDtype(na_value=nan)`` when writing GeoPackages. Keep the geometry
    untouched and coerce non-geometry extension columns to plain Python object
    values before calling ``to_file``.
    """
    import pandas as pd

    if gdf.index.name is not None or not isinstance(gdf.index, pd.RangeIndex):
        out = gdf.reset_index()
    else:
        out = gdf.copy()
    geometry_name = out.geometry.name if out.geometry is not None else None
    for column in out.columns:
        if column == geometry_name:
            continue
        if pd.api.types.is_extension_array_dtype(out[column].dtype):
            out[column] = out[column].astype("object").where(out[column].notna(), None)
    return out


def _geometry_union(gdf):
    """Return a single geometry across GeoPandas versions."""
    if hasattr(gdf, "union_all"):
        return gdf.union_all()
    return gdf.unary_union


def fetch_basin_boundary(usgs_id: str, out_gpkg: Path, *, dem_path: Path | None = None):
    """Fetch the basin polygon for a USGS gauge with NLDI fallback cascade.

    Returns (basin_gdf, boundary_provenance_dict).
    """
    from swatplus_builder.gis.nldi_fallback import fetch_basin_boundary_cascade

    out_gpkg.parent.mkdir(parents=True, exist_ok=True)
    cascade_dem = Path(dem_path) if dem_path else None
    basin, provenance = fetch_basin_boundary_cascade(usgs_id, dem_path=cascade_dem)
    basin = basin.to_crs("EPSG:4326")
    _fiona_safe_gdf(basin).to_file(out_gpkg, driver="GPKG")
    provenance_dict = provenance.model_dump()
    (out_gpkg.parent / "basin_boundary_provenance.json").write_text(
        json.dumps(provenance_dict, indent=2), encoding="utf-8"
    )
    return basin, provenance_dict


def fetch_dem(basin, out_tif: Path, resolution_m: int = 30):
    """Fetch 3DEP DEM over ``basin`` polygon as a GeoTIFF."""
    import py3dep

    geom = basin.geometry.iloc[0]
    dem = py3dep.get_dem(geom, resolution=resolution_m, crs="EPSG:4326")
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    dem.rio.to_raster(out_tif, tiled=True, compress="DEFLATE")
    return out_tif


def fetch_nlcd(basin, out_tif: Path, year: int = 2021):
    """Fetch NLCD ``year`` land cover raster clipped to the basin."""
    import pygeohydro

    out_tif.parent.mkdir(parents=True, exist_ok=True)

    nlcd_dict = pygeohydro.nlcd_bygeom(
        basin, years={"cover": [year]}, resolution=30
    )
    first_key = next(iter(nlcd_dict))
    ds = nlcd_dict[first_key]
    lu = ds[f"cover_{year}"].astype("int32")
    lu.rio.to_raster(out_tif, tiled=True, compress="DEFLATE")
    return out_tif


def _try_soilgrids_fallback(
    mukeys: list[int],
    outdir: Path,
    boundary_provenance: dict,
) -> tuple[list["SoilProfile"], int]:
    """Try SoilGrids v2.0 as a coarse soil fallback.

    Returns (profiles_list, failed_count).
    """
    from swatplus_builder.soil.soilgrids import fetch_soilgrids_profile

    profiles: list = []
    failed = 0

    # Use basin subbasin centroid as the query point for SoilGrids.
    # SoilGrids is coarse (250 m), so a single point per basin is
    # sufficient as a degraded-provenance fallback.
    try:
        import geopandas as gpd
        subs_path = outdir / "delin" / "shapes" / "subbasins.gpkg"
        if subs_path.exists():
            gdf = gpd.read_file(subs_path)
            centroid = gdf.to_crs("EPSG:4326").geometry.union_all().centroid
            lon, lat = centroid.x, centroid.y
        else:
            # Fall back to rough coordinates
            lon, lat = -86.0, 40.0
    except Exception:
        lon, lat = -86.0, 40.0

    for mukey in mukeys:
        profile = fetch_soilgrids_profile(lon, lat, mukey=mukey)
        if profile is not None:
            profiles.append(profile)
        else:
            failed += 1

    return profiles, failed


def main(
    outdir: Path,
    run_engine: bool = False,
    *,
    sim_start: str = SIM_START,
    sim_end: str = SIM_END,
    warmup_years: int = 0,
):
    import json

    from swatplus_builder.db.project import create_project_db, upsert_project_metadata
    from swatplus_builder.db.seed import seed_minimal_soils
    from swatplus_builder.db.writer import write_all
    from swatplus_builder.editor.api import (
        import_weather_observed,
        setup_project,
        write_files,
    )
    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.gis.delineation import delineate, resolve_usgs_outlet
    from swatplus_builder.gis.hru import create_hrus
    from swatplus_builder.gis.overlay_repair import repair_overlay_inputs
    from swatplus_builder.gis.soil import extract_unique_mukeys, fetch_mukey_raster
    from swatplus_builder.gis.tables import build_tables
    from swatplus_builder.gis.validate import validate_watershed
    from swatplus_builder.ref.bootstrap import ensure_datasets_db
    from swatplus_builder.soil.writer import write_soils
    from swatplus_builder.weather.gridmet import fetch_gridmet
    from swatplus_builder.weather.writer import write_observed
    from swatplus_builder.calibration.nwis import fetch_usgs_daily_q
    from swatplus_builder.output.eval import evaluate_run
    from swatplus_builder.output.metadata import (
        RunMetadata,
        sha256_file,
        try_git_sha,
        utc_now_iso,
        write_metadata,
    )
    from swatplus_builder.output.plots.wrapper import generate_all_plots
    from swatplus_builder.soil.sda import fetch_sda_mukeys_for_geometry

    outdir.mkdir(parents=True, exist_ok=True)
    t_all = time.time()
    retry_attempts: dict[str, int] = {}

    # 1. Basin boundary (USGS NLDI with fallback cascade)
    _section("1/11 Basin boundary from USGS NLDI")
    basin_gpkg = outdir / "raw" / "basin_boundary.gpkg"
    t0 = time.time()
    (basin, boundary_provenance), n = _with_retries(
        "fetch_basin_boundary", fetch_basin_boundary, STATION_ID, basin_gpkg
    )
    retry_attempts["fetch_basin_boundary"] = n
    actual_area_km2 = float(basin.to_crs('EPSG:5070').area.sum() / 1e6)
    boundary_source = boundary_provenance.get("source", "unknown")
    _ok(f"basin_boundary.gpkg  area = {actual_area_km2:.1f} km²  source={boundary_source}", elapsed=time.time() - t0)
    
    # Area Guard: Ensure we haven't snapped to a major river trunk (like Bald Eagle Creek)
    area_diff_pct = (
        abs(actual_area_km2 - EXPECTED_AREA_KM2) / EXPECTED_AREA_KM2
        if EXPECTED_AREA_KM2 > 0
        else 0.0
    )
    if EXPECTED_AREA_KM2 > 0 and area_diff_pct > 0.15:
        raise RuntimeError(
            f"Basin area mismatch! Expected ~{EXPECTED_AREA_KM2} km2, got {actual_area_km2:.1f} km2. "
            "Please check the Site ID or NLDI snapping."
        )

    # 2. DEM (3DEP)
    _section(f"2/11 DEM {DEM_RESOLUTION_M} m from USGS 3DEP")
    dem_tif = outdir / "raw" / "dem.tif"
    t0 = time.time()
    _, n = _with_retries("fetch_dem", fetch_dem, basin, dem_tif, resolution_m=DEM_RESOLUTION_M)
    retry_attempts["fetch_dem"] = n
    _ok(f"dem.tif  ({dem_tif.stat().st_size / 1e6:.1f} MB)",
        elapsed=time.time() - t0)

    # 3. NLCD landuse
    _section("3/11 NLCD 2021 landuse from MRLC")
    nlcd_tif = outdir / "raw" / "nlcd_2021.tif"
    t0 = time.time()
    _, n = _with_retries("fetch_nlcd", fetch_nlcd, basin, nlcd_tif, year=2021)
    retry_attempts["fetch_nlcd"] = n
    _ok(f"nlcd_2021.tif  ({nlcd_tif.stat().st_size / 1e6:.1f} MB)",
        elapsed=time.time() - t0)

    # 4. Delineation (WhiteboxTools)
    _section("4/11 Delineation (WhiteboxTools D8)")
    outlet = resolve_usgs_outlet(STATION_ID)
    t0 = time.time()
    base_threshold = int(os.environ.get("SWATPLUS_STREAM_THRESHOLD_CELLS", "2000"))
    dem_conditioning = os.environ.get("SWATPLUS_DEM_CONDITIONING", "breach").strip().lower()
    if dem_conditioning not in {"breach", "fill"}:
        raise RuntimeError(
            "SWATPLUS_DEM_CONDITIONING must be 'breach' or 'fill' "
            f"(got {dem_conditioning!r})."
        )
    from swatplus_builder.gis.complexity import (
        DiscretizationPolicy,
        assess_topology_complexity,
        stream_threshold_candidates,
    )

    complexity_policy = DiscretizationPolicy(
        stream_threshold_area_pct=float(os.environ.get("SWATPLUS_STREAM_THRESHOLD_AREA_PCT", "2.0")),
        max_acceptable_subbasins=int(os.environ.get("SWATPLUS_MAX_SUBBASINS", "500")),
        min_acceptable_avg_subbasin_area_km2=float(
            os.environ.get("SWATPLUS_MIN_AVG_SUBBASIN_AREA_KM2", "1.0")
        ),
    )
    threshold_policy = os.environ.get("SWATPLUS_THRESHOLD_POLICY", "adaptive").strip().lower()
    if threshold_policy in {"fixed", "legacy"}:
        # Keep user-seeded threshold first, but allow coarse retries so the
        # run can recover from over-discretization in strict fixed mode.
        thresholds = [base_threshold, int(round(base_threshold * 1.5)), base_threshold * 2]
        thresholds = list(dict.fromkeys([max(100, t) for t in thresholds]))
    elif threshold_policy == "adaptive":
        thresholds = stream_threshold_candidates(
            actual_area_km2,
            DEM_RESOLUTION_M,
            seed_threshold=base_threshold,
            policy=complexity_policy,
        )
    else:
        raise RuntimeError(
            "SWATPLUS_THRESHOLD_POLICY must be 'adaptive', 'fixed', or 'legacy' "
            f"(got {threshold_policy!r})."
        )
    ws = None
    validation = None
    selected_threshold = None
    threshold_attempts = []
    for th in thresholds:
        try:
            ws_try = delineate(
                dem_path=dem_tif,
                outlet=outlet,
                workdir=outdir / "delin",
                stream_threshold_cells=th,
                expected_area_km2=EXPECTED_AREA_KM2 if EXPECTED_AREA_KM2 > 0 else None,
            )
        except SwatBuilderPipelineError as exc:
            threshold_attempts.append({
                "threshold_cells": th,
                "validation_passed": False,
                "area_diff_pct": None,
                "iou_pct": None,
                "n_subbasins": exc.context.get("n_subbasins"),
                "n_channels": exc.context.get("n_channels"),
                "avg_subbasin_area_km2": None,
                "complexity_acceptable": False,
                "complexity_reasons": [str(exc)],
                "topology_suspicious": True,
            })
            log.warning("Delineation attempt rejected (threshold=%s): %s", th, exc)
            continue
        # Default 30 %: DEM-boundary truncation can legitimately leave 25-30 % of
        # a large basin outside the delineated watershed. Override via env var.
        _area_tol = float(os.environ.get("SWATPLUS_AREA_TOLERANCE_PCT", "30.0"))
        # When the boundary is from a fallback source (WBD HUC12, NHDPlus,
        # or DEM-from-gauge), the reference polygon is not hydrologically
        # authoritative. Skip area/IoU validation and accept the DEM-derived
        # watershed as ground truth.
        is_fallback_boundary = boundary_provenance.get("source") not in (
            "nldi_authoritative", None
        )
        if is_fallback_boundary:
            log.warning(
                "Boundary source is %s (fallback); skipping area/IoU validation "
                "against reference polygon. Using DEM-derived watershed as "
                "authoritative boundary.",
                boundary_provenance.get("source"),
            )
            vr = validate_watershed(ws_try, reference_polygon=None)
        else:
            vr = validate_watershed(
                ws_try,
                reference_polygon=basin_gpkg,
                area_tolerance_pct=_area_tol,
            )
        suspicious = _topology_suspicious(ws_try.stats)
        complexity = assess_topology_complexity(ws_try.stats, complexity_policy)
        threshold_attempts.append({
            "threshold_cells": th,
            "validation_passed": vr.passed,
            "area_diff_pct": vr.area_diff_pct,
            "iou_pct": vr.iou_pct,
            "n_subbasins": complexity.n_subbasins,
            "n_channels": complexity.n_channels,
            "avg_subbasin_area_km2": complexity.avg_subbasin_area_km2,
            "complexity_acceptable": complexity.acceptable,
            "complexity_reasons": list(complexity.reasons),
            "topology_suspicious": suspicious,
        })
        ws = ws_try
        validation = vr
        selected_threshold = th
        if vr.passed and not suspicious and complexity.acceptable:
            break
        log.warning(
            "Delineation attempt rejected (threshold=%s): passed=%s, area_diff_pct=%s, iou_pct=%s, suspicious_topology=%s, complexity=%s",
            th,
            vr.passed,
            vr.area_diff_pct,
            vr.iou_pct,
            suspicious,
            ",".join(complexity.reasons) or "ok",
        )

    if ws is None or validation is None:
        raise RuntimeError(
            "Delineation failed to produce a watershed after threshold attempts: "
            f"{threshold_attempts}"
        )
    final_complexity = assess_topology_complexity(ws.stats, complexity_policy)
    if not validation.passed or _topology_suspicious(ws.stats) or not final_complexity.acceptable:
        raise RuntimeError(
            "Delineation failed realism gates (area/topology). "
            f"area_diff_pct={validation.area_diff_pct}, iou_pct={validation.iou_pct}, "
            f"n_subbasins={ws.stats.get('n_subbasins')}, n_channels={ws.stats.get('n_channels')}, "
            f"complexity_reasons={list(final_complexity.reasons)}."
        )
    (outdir / "delin" / "validation_result.json").write_text(
        json.dumps(validation.to_dict(), indent=2),
        encoding="utf-8",
    )
    (outdir / "delin" / "threshold_selection.json").write_text(
        json.dumps({
            "policy": {
                "threshold_policy": threshold_policy,
                "stream_threshold_area_pct": complexity_policy.stream_threshold_area_pct,
                "max_acceptable_subbasins": complexity_policy.max_acceptable_subbasins,
                "min_acceptable_avg_subbasin_area_km2": (
                    complexity_policy.min_acceptable_avg_subbasin_area_km2
                ),
            },
            "selected_threshold_cells": selected_threshold,
            "attempts": threshold_attempts,
        }, indent=2),
        encoding="utf-8",
    )
    _ok(
        f"subbasins = {ws.stats.get('n_subbasins', 0):.0f}  channels = {ws.stats.get('n_channels', 0):.0f}  "
        f"threshold = {selected_threshold}",
        elapsed=time.time() - t0,
    )

    # 5. gNATSGO mukey raster
    _section("5/11 gNATSGO mukey raster (Planetary Computer)")
    mukey_tif = outdir / "raw" / "mukey.tif"
    import geopandas as gpd
    subs = gpd.read_file(ws.subbasins_vector)
    boundary_geom = _geometry_union(subs.to_crs("EPSG:4326"))
    t0 = time.time()
    _, n = _with_retries(
        "fetch_mukey_raster",
        fetch_mukey_raster,
        boundary=boundary_geom,
        boundary_crs="EPSG:4326",
        output_path=mukey_tif,
    )
    retry_attempts["fetch_mukey_raster"] = n
    mukey_file_mb = mukey_tif.stat().st_size / 1e6 if mukey_tif.exists() else 0.0

    # Normalize soil raster CRS to match DEM. Planetary Computer delivers
    # gNATSGO in ESRI:102039, but the DEM is EPSG:5070. They are functionally
    # the same CONUS Albers projection, but the mismatched CRS labels cause
    # rasterio's alignment step to lose >97% of soil pixels. Copy the file
    # with the correct CRS label.
    if mukey_tif.exists():
        try:
            import rasterio as _rio
            with _rio.open(mukey_tif) as _src:
                _data = _src.read()
                _profile = _src.profile.copy()
            _profile["crs"] = "EPSG:5070"
            _reproj_tif = outdir / "raw" / "mukey_e5070.tif"
            _reproj_tif.parent.mkdir(parents=True, exist_ok=True)
            with _rio.open(_reproj_tif, "w", **_profile) as _dst:
                _dst.write(_data)
            hru_soil_raster = _reproj_tif
            soil_overlay_source = "gnatsgo_raster"
            log.info("Normalized soil raster CRS to EPSG:5070.")
        except Exception as _exc:
            log.warning("Soil CRS metadata update failed (%s); using original raster.", _exc)

    mukey_values = extract_unique_mukeys(hru_soil_raster) if hru_soil_raster is not None and hru_soil_raster.exists() and hru_soil_raster.stat().st_size > 0 else set()
    constant_soil_mukey: int | None = None
    sda_spatial_mukeys: list[int] = []
    if not mukey_values:
        sda_spatial_mukeys, n = _with_retries(
            "fetch_sda_mukeys_for_geometry",
            fetch_sda_mukeys_for_geometry,
            boundary_geom,
            cache_dir=outdir / "cache",
        )
        retry_attempts["fetch_sda_mukeys_for_geometry"] = n
        soil_overlay_source = (
            "sda_spatial_representative_after_empty_gnatsgo"
            if sda_spatial_mukeys
            else "constant_placeholder_after_empty_gnatsgo"
        )
        soil_provenance_mode = (
            "sda_representative"
            if sda_spatial_mukeys
            else "diagnostic_placeholder"
        )
        hru_soil_raster = None
        constant_soil_mukey = (
            int(sda_spatial_mukeys[0])
            if sda_spatial_mukeys
            else int(os.environ.get("SWATPLUS_SDA_PLACEHOLDER_MUKEY", "900000001"))
        )
        log.warning(
            "gNATSGO mukey raster is empty for %s. Continuing HRU overlay with explicit "
            "constant representative mukey=%s so the run can produce diagnostic artifacts. "
            "SDA spatial mukeys found=%d. This preserves a real SDA soil profile when available, "
            "but it does not preserve spatial soil heterogeneity.",
            STATION_ID,
            constant_soil_mukey,
            len(sda_spatial_mukeys),
        )
    _ok(
        f"mukey.tif  ({mukey_file_mb:.1f} MB, unique_mukeys={len(mukey_values)}, soil_overlay_source={soil_overlay_source})",
        elapsed=time.time() - t0,
    )

    # 6. HRUs
    _section("6/11 HRU overlay (dominant per LSU)")
    t0 = time.time()
    hru = create_hrus(
        watershed=ws,
        landuse_raster=nlcd_tif,
        soil_raster=hru_soil_raster,
        constant_soil_mukey=constant_soil_mukey,
    )
    n_sub = int(hru.stats.get("n_subbasins", ws.stats.get("n_subbasins", 0)))
    n_hru = int(hru.stats["n_hrus"])
    min_hru_coverage_ratio = float(os.environ.get("SWATPLUS_MIN_HRU_COVERAGE_RATIO", "0.90"))
    hru_coverage_ratio = (n_hru / max(n_sub, 1)) if n_sub > 0 else 0.0
    overlay_repair_report = None
    if hru_coverage_ratio < min_hru_coverage_ratio:
        overlay_repair_report = repair_overlay_inputs(
            dem_tif,
            nlcd_tif,
            hru_soil_raster,
            outdir / "reports" / "overlay_repair",
        )
        if overlay_repair_report.repaired:
            log.warning(
                "HRU overlay repair filled small nodata gaps (%s). Rebuilding HRUs from repaired rasters.",
                overlay_repair_report.reason,
            )
            repaired_landuse = Path(overlay_repair_report.landuse_output_path)
            repaired_soil = (
                Path(overlay_repair_report.soil_output_path)
                if overlay_repair_report.soil_output_path is not None
                else None
            )
            hru = create_hrus(
                watershed=ws,
                landuse_raster=repaired_landuse,
                soil_raster=repaired_soil,
                constant_soil_mukey=constant_soil_mukey,
            )
            n_sub = int(hru.stats.get("n_subbasins", ws.stats.get("n_subbasins", 0)))
            n_hru = int(hru.stats["n_hrus"])
            hru_coverage_ratio = (n_hru / max(n_sub, 1)) if n_sub > 0 else 0.0
        if hru_coverage_ratio < min_hru_coverage_ratio:
            repair_reason = (
                f"; overlay_repair_reason={overlay_repair_report.reason}"
                if overlay_repair_report is not None
                else ""
            )
            raise RuntimeError(
                "HRU realism gate failed: too many delineated subbasins have no valid landuse/soil overlay. "
                f"coverage_ratio={hru_coverage_ratio:.2%}, required>={min_hru_coverage_ratio:.2%} "
                f"(n_hrus={n_hru}, n_subbasins={n_sub}).{repair_reason}"
            )
    _ok(f"n_lsus = {int(hru.stats['n_lsus'])}  "
        f"n_hrus = {int(hru.stats['n_hrus'])}",
        elapsed=time.time() - t0)

    # 7. GisTables + project.sqlite
    _section("7/11 GisTables → project.sqlite")
    tables = build_tables(ws, hru)
    
    # Keep native subbasin coordinates/elevations for spatially realistic forcing.
    from swatplus_builder.config import Settings
    ref_settings = Settings(reference_db_dir=outdir / "reference_dbs")
    datasets_db = ensure_datasets_db(settings=ref_settings)
    
    project_dir = outdir / "project"
    project_dir.mkdir(exist_ok=True)
    t0 = time.time()
    db_path = create_project_db(f"usgs_{STATION_ID}", project_dir, reference_db=datasets_db, overwrite=True)
    write_all(db_path, tables)
    _ok(f"project.sqlite created", elapsed=time.time() - t0)

    # 8. Soils
    _section("8/11 Soils (SDA + Hybrid Fallback)")
    t0 = time.time()
    mukeys = sorted({int(h.soil.removeprefix('gnatsgo_')) for h in tables.hrus})
    from swatplus_builder.soil.builder import fetch_soil_profiles_result
    from swatplus_builder.soil.models import SoilConfig
    soil_mode = "high_fidelity"
    soil_provenance_mode = "gnatsgo_raster"
    pct_fallback_soils = 0.0
    soil_fallback_warn_threshold = float(os.environ.get("SWATPLUS_SOIL_FALLBACK_WARN_THRESHOLD", "0.25"))
    allow_synthetic_soils = _truthy_env("SWATPLUS_ALLOW_SYNTHETIC_SOILS", default=False)
    soil_acquired = False
    try:
        external_soils_json = os.environ.get("SWATPLUS_EXTERNAL_SOILS_JSON")
        if external_soils_json:
            soil_profiles, soil_report = _load_external_soil_profiles(
                Path(external_soils_json).expanduser().resolve(),
                mukeys,
            )
        else:
            soil_res, n = _with_retries(
                "fetch_soil_profiles_result",
                fetch_soil_profiles_result,
                mukeys,
                config=SoilConfig(use_sda=True),
                settings=ref_settings,
            )
            retry_attempts["fetch_soil_profiles_result"] = n
            soil_profiles = soil_res.profiles
            soil_report = soil_res.soil_report
        soil_acquired = True
        hydgrp_fixed = _normalize_soil_profiles_hydgrp(soil_profiles)
        if hydgrp_fixed > 0:
            log.warning(
                "Normalized %d soil hydrologic group values to valid A/B/C/D codes before write_soils().",
                hydgrp_fixed,
            )
            soil_report = dict(soil_report)
            soil_report["hydgrp_normalized_count"] = hydgrp_fixed
        soil_report = dict(soil_report)
        soil_report["hru_soil_overlay_source"] = soil_overlay_source
        soil_report["gnatsgo_mukey_file_mb"] = mukey_file_mb
        soil_report["gnatsgo_unique_mukeys"] = len(mukey_values)
        soil_report["sda_spatial_mukeys_found"] = len(sda_spatial_mukeys)
        if overlay_repair_report is not None:
            soil_report["hru_overlay_repair"] = overlay_repair_report.model_dump()
        if constant_soil_mukey is not None:
            soil_report["constant_soil_mukey"] = constant_soil_mukey
            soil_report["soil_provenance_mode"] = soil_provenance_mode
            soil_report["authority_note"] = (
                "gNATSGO raster was empty; HRU overlay used one constant representative mukey. "
                "SDA horizons may be real for that mukey, but spatial soil heterogeneity is degraded."
            )
        soil_report["soil_mode"] = soil_mode
        soil_report["soil_overlay_source"] = soil_overlay_source
        write_soils(soil_profiles, db_path)
        upsert_project_metadata(db_path, "soil_report", json.dumps(soil_report))
        from swatplus_builder.soil.plot import plot_depth_distribution
        plot_depth_distribution(soil_profiles, out_path=outdir / "plots" / "soil_depth_preview.png")
        requested = max(int(soil_report.get("requested_mukeys", 0)), 1)
        default_fallback = int(soil_report.get("aggregated", {}).get("default_fallback", 0))
        pct_fallback_soils = min(max(default_fallback / requested, 0.0), 1.0)
        if pct_fallback_soils > 0.0:
            soil_mode = "fallback"
        _ok(f"wrote {len(soil_profiles)} profiles", elapsed=time.time() - t0)
    except Exception as e:
        # Tier 2: SoilGrids coarse fallback for regions where SDA has no profiles.
        soilgrids_profiles, soilgrids_failed = _try_soilgrids_fallback(
            mukeys, outdir, boundary_provenance
        )
        if soilgrids_profiles:
            log.warning(
                "SDA soil acquisition failed (%s). Recovered %d profiles from SoilGrids v2.0 "
                "coarse fallback. %d mukeys could not be resolved.",
                e, len(soilgrids_profiles), soilgrids_failed,
            )
            soil_profiles = soilgrids_profiles
            soil_mode = "fallback"
            soil_provenance_mode = "soilgrids_coarse"
            pct_fallback_soils = soilgrids_failed / max(len(mukeys), 1)
            soil_report = {
                "soil_mode": soil_mode,
                "soil_provenance_mode": soil_provenance_mode,
                "soil_source": "soilgrids_coarse",
                "hru_soil_overlay_source": soil_overlay_source,
                "soil_overlay_source": soil_overlay_source,
                "requested_mukeys": len(mukeys),
                "soilgrids_resolved": len(soilgrids_profiles),
                "soilgrids_failed": soilgrids_failed,
                "sda_error": str(e)[:200],
            }
            soil_acquired = True
            write_soils(soil_profiles, db_path)
            upsert_project_metadata(db_path, "soil_report", json.dumps(soil_report))
            _ok(f"wrote {len(soil_profiles)} profiles (SoilGrids fallback)", elapsed=time.time() - t0)
        elif not allow_synthetic_soils:
            raise RuntimeError(
                "Soil acquisition failed and synthetic soil fallback is disabled for research runs. "
                "Install soil extras (including fsspec/adlfs), provide SWATPLUS_EXTERNAL_SOILS_JSON, "
                "or set SWATPLUS_ALLOW_SYNTHETIC_SOILS=1 for diagnostic-only runs."
            ) from e
        else:
            # Tier 3: synthetic as absolute last resort
            log.warning("Soils failed (%s). Seeding minimal because synthetic override is enabled.", e)
            seed_minimal_soils(db_path, {h.soil for h in tables.hrus})
            soil_mode = "synthetic"
            pct_fallback_soils = 1.0
            _ok("seed_minimal_soils (fallback)")

    max_soil_fallback_ratio = float(os.environ.get("SWATPLUS_MAX_SOIL_FALLBACK_RATIO", "0.00"))
    if (soil_mode == "synthetic" or pct_fallback_soils > max_soil_fallback_ratio) and not allow_synthetic_soils:
        raise RuntimeError(
            "Soil realism gate failed: "
            f"soil_mode={soil_mode}, pct_fallback_soils={pct_fallback_soils:.2%}, "
            f"allowed_max={max_soil_fallback_ratio:.2%}. "
            "Set SWATPLUS_ALLOW_SYNTHETIC_SOILS=1 to override for diagnostic-only runs."
        )

    # 9/11 Weather from GridMET
    _section("9/11 Weather from GridMET")
    t0 = time.time()
    max_weather_stations = max(1, int(os.environ.get("SWATPLUS_MAX_WEATHER_STATIONS", "25")))
    subs_for_weather = list(tables.subbasins)
    if len(subs_for_weather) > max_weather_stations:
        step = max(1, len(subs_for_weather) // max_weather_stations)
        subs_for_weather = subs_for_weather[::step][:max_weather_stations]
    from datetime import datetime as _dt, timedelta
    eval_start_dt = _dt.strptime(sim_start, "%Y-%m-%d")
    weather_start = (_dt(eval_start_dt.year - warmup_years, eval_start_dt.month, eval_start_dt.day)
                     if warmup_years > 0 else eval_start_dt)
    weather_start_str = weather_start.strftime("%Y-%m-%d")

    stations = [(float(s.lat), float(s.lon), float(s.elev)) for s in subs_for_weather]
    weather_bundle = fetch_gridmet(
        stations,
        start=weather_start_str,
        end=sim_end,
        settings=ref_settings
    )
    
    # Weather signature validation
    all_pcp = [v for s in weather_bundle.stations for v in (s.pcp or [])]
    import numpy as np
    pcp_stats = {
        "precip_mean": float(np.mean(all_pcp)),
        "precip_max": float(np.max(all_pcp)),
        "nonzero_days": int(np.sum(np.array(all_pcp) > 0)),
        "date_range": f"{weather_bundle.start} to n_days={weather_bundle.n_days}"
    }
    log.info("Weather Signature: %s", json.dumps(pcp_stats, indent=2))
    _ok(
        f"fetched GridMET for {len(weather_bundle.stations)} stations (from {len(tables.subbasins)} subbasins)",
        elapsed=time.time() - t0,
    )

    # 10. Editor
    _section("10/11 SWAT+ Editor Operations")
    t0 = time.time()
    is_lte = args.model_family == "lte"
    setup_project(db_path, is_lte=is_lte, timeout=300.0)
    txtinout_dir = project_dir / "Scenarios" / "Default" / "TxtInOut"
    write_observed(weather_bundle, txtinout_dir)
    import_weather_observed(db_path, txtinout_dir, timeout=300.0)
    wf = write_files(db_path, timeout=300.0)

    lte_hru_chan_correction = 0.0
    lte_hru_rows_patched = 0
    if is_lte:
        lte_scon_scale = float(os.environ.get("SWATPLUS_LTE_SCON_SCALE", "0.60"))
        scon_rows = _scale_lte_soil_scon(wf.txtinout_dir, lte_scon_scale)
        if scon_rows > 0:
            log.info(
                "Applied LTE soil conductivity scaling to %d rows (scale=%.3f)",
                scon_rows,
                lte_scon_scale,
            )
        lte_alpha_bf = float(os.environ.get("SWATPLUS_LTE_ALPHA_BF", "0.20"))
        alpha_rows = _set_lte_hru_column(wf.txtinout_dir, "alpha_bf", lte_alpha_bf)
        if alpha_rows > 0:
            log.info(
                "Applied LTE alpha_bf override to %d rows (alpha_bf=%.3f)",
                alpha_rows,
                lte_alpha_bf,
            )
        # LTE HRU-to-channel transfer scale correction.
        lte_hru_chan_correction = float(
            os.environ.get(
                "SWATPLUS_LTE_HRU_CHANNEL_SCALE_CORRECTION",
                "0.01",
            )
        )
        lte_hru_rows_patched = 0
        if lte_hru_chan_correction > 0.0:
            lte_hru_rows_patched = _patch_lte_hru_channel_transfer_scale(
                wf.txtinout_dir, correction_factor=lte_hru_chan_correction
            )
            if lte_hru_rows_patched > 0:
                log.info(
                    "Applied LTE HRU→channel scale correction %s to %d rows in hru-lte.con",
                    lte_hru_chan_correction,
                    lte_hru_rows_patched,
                )

    if not is_lte:
        # Full SWAT+ mode: apply post-editor routing fixes for engine rev 60.5.7.
        # Editor v3.2.0 generates sdc/chandeg routing natively but needs:
        # - codes.bsn: rte_cha=1 + companion flags
        # - rout_unit.def: 2-element (source+sink) per routing unit
        # - rout_unit.con: sur+lat hyd type entries
        from swatplus_builder.full_mode.routing_fixes import apply_full_routing_fixes
        apply_full_routing_fixes(wf.txtinout_dir)
        log.info("Applied full-mode routing fixes")

        # Warmup: prepend spin-up years before the evaluation period
        if warmup_years > 0:
            from swatplus_builder.full_mode.warmup import reset_and_apply_warmup as _reset_and_apply_warmup
            _reset_and_apply_warmup(
                wf.txtinout_dir,
                warmup_years=warmup_years,
                evaluation_start_year=eval_start_dt.year,
            )
            log.info("Applied %d-year spin-up warmup (stale-safe reset)", warmup_years)

    _ok(f"TxtInOut ready ({sum(1 for _ in wf.txtinout_dir.iterdir())} files)", elapsed=time.time() - t0)

    # 11/11 Engine Run
    _section("11/11 Engine Run")
    subprocess_successful = False
    engine_version = None
    if run_engine:
        # Patch print.prt: set nyskip=0, dates matching the simulation period,
        # and enable daily channel outputs.
        from datetime import datetime as _dt
        d_start = _dt.strptime(sim_start, "%Y-%m-%d")
        d_end = _dt.strptime(sim_end, "%Y-%m-%d")
        start_jday, start_year = d_start.timetuple().tm_yday, d_start.year
        end_jday,   end_year   = d_end.timetuple().tm_yday,   d_end.year

        # Read actual yrc_start from time.sim (may differ from sim_start due to warmup)
        time_sim = wf.txtinout_dir / "time.sim"
        if time_sim.is_file():
            ts_lines = [l for l in time_sim.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            if len(ts_lines) >= 3:
                ts_parts = ts_lines[2].split()
                ts_hdr = ts_lines[1].split()
                if "yrc_start" in ts_hdr:
                    warmup_start_year = int(ts_parts[ts_hdr.index("yrc_start")])
                    if warmup_start_year < start_year:
                        start_year = warmup_start_year

        prt = wf.txtinout_dir / "print.prt"
        if prt.is_file():
            lines = prt.read_text(encoding="utf-8", errors="replace").splitlines()
            out: list[str] = []
            for i, line in enumerate(lines):
                if i == 2:
                    # Rewrite control row; preserve warmup nyskip if set
                    nskip = warmup_years
                    line = (
                        f"{nskip:<12}{start_jday:<11}{start_year:<11}"
                        f"{end_jday:<11}{end_year:<11}{'1':<10}"
                    )
                elif line.strip().startswith("channel ") or line.strip().startswith("channel_sd"):
                    # Enable daily output
                    line = line.replace(" n ", " y ", 1)
                out.append(line)
            prt.write_text("\n".join(out) + "\n", encoding="utf-8")

        # Patch time.sim to match the simulation period.
        time_sim = wf.txtinout_dir / "time.sim"
        if time_sim.is_file():
            ts_lines = time_sim.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(ts_lines) >= 3:
                ts_lines[2] = (
                    f"{start_jday:>10}{start_year:>10}"
                    f"{end_jday:>10}{end_year:>10}{'0':>10}"
                )
                time_sim.write_text("\n".join(ts_lines) + "\n", encoding="utf-8")

        # Optional override for channel-routing switch (preserve existing value by default).
        codes_bsn = wf.txtinout_dir / "codes.bsn"
        force_rte_cha = os.environ.get("SWATPLUS_FORCE_RTE_CHA")
        if codes_bsn.is_file() and force_rte_cha in {"0", "1"}:
            lines = codes_bsn.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(lines) >= 3:
                header = lines[1].split()
                values = lines[2].split()
                if "rte_cha" in header:
                    idx = header.index("rte_cha")
                    if idx < len(values):
                        values[idx] = force_rte_cha
                        # Rebuild: first 2 cols are string (16-wide), rest are int (10-wide)
                        lines[2] = f"{values[0]:<16}{values[1]:<16}" + "".join(
                            f"{(force_rte_cha if j == idx else v):>10}" for j, v in enumerate(values[2:], start=2)
                        )
                        codes_bsn.write_text("\n".join(lines) + "\n", encoding="utf-8")
                        log.info("Applied codes.bsn rte_cha override: %s", force_rte_cha)

        # Rev61 (mac) can segfault in `climate_control.f90` if WGN inputs are
        # missing. The editor expects `weather-wgn.cli` to exist and
        # `weather-sta.cli` to reference a WGN name. We synthesize a single
        # WGN generator collocated with the unified station.
        weather_sta = wf.txtinout_dir / "weather-sta.cli"
        weather_wgn = wf.txtinout_dir / "weather-wgn.cli"
        if weather_sta.is_file():
            rows = weather_sta.read_text(encoding="utf-8", errors="replace").splitlines()
            # Header + one station row in our unified-forcing workflow.
            if len(rows) >= 3:
                sta_parts = rows[2].split()
                sta_name = sta_parts[0]

                # Extract station coordinates from the .pcp header (line 3).
                pcp_path = wf.txtinout_dir / f"{sta_name}.pcp"
                lat = lon = elev = 0.0
                if pcp_path.is_file():
                    pcp_lines = pcp_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if len(pcp_lines) >= 3:
                        meta = pcp_lines[2].split()
                        if len(meta) >= 5:
                            lat, lon, elev = float(meta[2]), float(meta[3]), float(meta[4])

                wgn_name = "wgn1"
                # Patch station row: set the "wgn" column to wgn1.
                # weather-sta.cli columns are:
                # name wgn pcp tmp slr hmd wnd pet atmo_dep
                if len(sta_parts) >= 2:
                    rows[2] = rows[2].replace("null", wgn_name, 1)
                    weather_sta.write_text("\n".join(rows) + "\n", encoding="utf-8")

                # Write a minimal weather-wgn.cli with 12 months of values.
                # Column order matches editor's `fileio/climate.py`.
                import datetime as _dt

                now = _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
                wgn_lines: list[str] = []
                wgn_lines.append(
                    f"weather-wgn.cli: written by swatplus-builder on {now}"
                )
                wgn_lines.append(
                    "name                           lat        lon       elev   rain_yrs"
                )
                wgn_lines.append(
                    f"{wgn_name:<25s}{lat:10.3f}{lon:10.3f}{elev:10.3f}{30:10d}"
                )
                wgn_lines.append(
                    "tmp_max_ave tmp_min_ave tmp_max_sd tmp_min_sd    pcp_ave     pcp_sd   pcp_skew    wet_dry    wet_wet   pcp_days   pcp_hhr    slr_ave    dew_ave    wnd_ave"
                )
                # These are generic mid-latitude CONUS-ish values; they only
                # need to be well-formed for the engine.
                monthly = [
                    (-1.0, -9.0, 6.0, 6.0, 70.0, 30.0, 1.0, 0.30, 0.50, 12.0, 0.10, 10.0, -6.0, 3.0),
                    ( 1.0, -8.0, 6.0, 6.0, 60.0, 28.0, 1.0, 0.30, 0.50, 11.0, 0.10, 12.0, -5.0, 3.0),
                    ( 7.0, -3.0, 6.0, 6.0, 80.0, 35.0, 1.0, 0.32, 0.52, 12.0, 0.10, 14.0, -1.0, 3.0),
                    (14.0,  3.0, 6.0, 6.0, 90.0, 40.0, 1.0, 0.35, 0.55, 12.0, 0.10, 16.0,  4.0, 3.0),
                    (20.0,  8.0, 6.0, 6.0, 95.0, 45.0, 1.0, 0.35, 0.55, 12.0, 0.10, 18.0,  9.0, 3.0),
                    (25.0, 13.0, 6.0, 6.0, 90.0, 45.0, 1.0, 0.33, 0.53, 11.0, 0.10, 20.0, 14.0, 3.0),
                    (28.0, 16.0, 6.0, 6.0, 95.0, 48.0, 1.0, 0.32, 0.52, 11.0, 0.10, 21.0, 16.0, 3.0),
                    (27.0, 15.0, 6.0, 6.0, 85.0, 45.0, 1.0, 0.32, 0.52, 10.0, 0.10, 19.0, 15.0, 3.0),
                    (22.0, 10.0, 6.0, 6.0, 80.0, 40.0, 1.0, 0.33, 0.53, 10.0, 0.10, 16.0, 10.0, 3.0),
                    (15.0,  4.0, 6.0, 6.0, 75.0, 35.0, 1.0, 0.34, 0.54, 11.0, 0.10, 13.0,  5.0, 3.0),
                    ( 8.0, -1.0, 6.0, 6.0, 80.0, 35.0, 1.0, 0.34, 0.54, 12.0, 0.10, 11.0, -1.0, 3.0),
                    ( 2.0, -7.0, 6.0, 6.0, 75.0, 33.0, 1.0, 0.32, 0.52, 12.0, 0.10, 10.0, -6.0, 3.0),
                ]
                for vals in monthly:
                    wgn_lines.append(" ".join(f"{v:10.3f}" for v in vals))

                weather_wgn.write_text("\n".join(wgn_lines) + "\n", encoding="utf-8")

        from swatplus_builder.run.swatplus import run as run_engine_fn
        # threads=1 requested for stability in benchmark
        r = run_engine_fn(wf.txtinout_dir, threads=1, timeout_s=1800.0)
        if r.success:
            subprocess_successful = True
            engine_version = str(r.binary)
            _ok("SWAT+ engine execution successful")
        else:
            raise RuntimeError(f"SWAT+ engine failed with code {r.exit_code}")
    else:
        log.warning("Skipping engine run (--run not provided). Pipeline will fail at evaluation.")

    if not subprocess_successful and run_engine:
        raise RuntimeError("SWAT+ engine failed to produce results.")

    # PUBLISHING
    _section("PUBLISHING: Diagnostics & Manuscript Suite")
    plots_dir, outputs_dir, reports_dir = outdir/"plots", outdir/"outputs", outdir/"reports"
    for d in [plots_dir, outputs_dir, reports_dir]: d.mkdir(parents=True, exist_ok=True)

    import json
    q_obs = fetch_usgs_daily_q(STATION_ID, sim_start, sim_end, outputs_dir / "obs_q.csv")
    # Prefer basin_sd_cha_day.txt for consistent, routing-amplification-free daily volumes
    sim_path = wf.txtinout_dir / "basin_sd_cha_day.txt"
    if not sim_path.exists():
        sim_path = wf.txtinout_dir / "channel_sd_day.txt"
    if not sim_path.exists():
        sim_path = wf.txtinout_dir / "channel_day.txt"
    selection_eval = evaluate_run(
        sim_path,
        q_obs,
        outlet_gis_id=1,
        outlet_policy="auto",
        return_diagnostics=True,
    )
    selection_df, selection_metrics, selection_diag = selection_eval
    pinned_outlet = int(selection_diag.get("selected_outlet_gis_id", 1) or 1)

    pinned_eval = evaluate_run(
        sim_path,
        q_obs,
        outlet_gis_id=pinned_outlet,
        out_alignment_csv=outputs_dir / "alignment.csv",
        outlet_policy="strict",
        return_diagnostics=True,
    )
    eval_df, eval_metrics, eval_diag = pinned_eval
    reports_dir.joinpath("metrics.json").write_text(json.dumps(eval_metrics, indent=2))

    outlet_provenance = {
        "version": 1,
        "selection_pass": {
            "policy": "auto",
            "requested_outlet_gis_id": 1,
            "metrics": selection_metrics,
            "diagnostics": selection_diag,
            "aligned_days": int(len(selection_df)),
        },
        "pinned_pass": {
            "policy": "strict",
            "pinned_outlet_gis_id": pinned_outlet,
            "metrics": eval_metrics,
            "diagnostics": eval_diag,
            "aligned_days": int(len(eval_df)),
        },
    }
    outlet_provenance_path = outputs_dir / "outlet_provenance.json"
    outlet_provenance_path.write_text(
        json.dumps(outlet_provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outlet_provenance_sha = sha256_file(outlet_provenance_path)
    sim_source_file = str(eval_diag.get("sim_source_file", "") or "")
    if sim_source_file:
        src = wf.txtinout_dir / sim_source_file
        if src.exists():
            shutil.copy2(src, outputs_dir / sim_source_file)
    
    plot_res = generate_all_plots(
        run_dir=outdir,
        include_spatial=True,
        metadata={
            "basin_name": f"Marsh Creek ({STATION_ID})",
            "usgs_id": STATION_ID,
            "soil_mode": soil_mode,
            "pct_fallback_soils": pct_fallback_soils,
            "model_family": args.model_family,
        }
    )
    _ok(f"generated {plot_res['n_plots']} figures in plots/")

    input_hashes: dict[str, str] = {}
    for name, p in {
        "dem_tif": dem_tif,
        "nlcd_tif": nlcd_tif,
        "mukey_tif": mukey_tif,
    }.items():
        if p.exists():
            input_hashes[name] = sha256_file(p)

    notes: list[str] = []
    if is_lte:
        if abs(float(lte_scon_scale) - 1.0) > 1e-9:
            notes.append(
                f"lte_scon_scale_applied={float(lte_scon_scale):.3f} (rows={int(scon_rows)})"
            )
        if lte_hru_rows_patched > 0 and lte_hru_chan_correction > 0.0:
            notes.append(
                f"lte_hru_channel_scale_correction_applied={lte_hru_chan_correction:.3f} "
            f"(rows={lte_hru_rows_patched})"
        )
    if validation is not None:
        notes.append(
            f"delineation_validation: passed={validation.passed}, area_diff_pct={validation.area_diff_pct}, iou_pct={validation.iou_pct}"
        )
        notes.extend(validation.notes)
    if overlay_repair_report is not None:
        notes.append(
            f"hru_overlay_repair={overlay_repair_report.reason}; "
            f"landuse_filled={overlay_repair_report.landuse_filled_cells}; "
            f"soil_filled={overlay_repair_report.soil_filled_cells}"
        )
    notes.append(f"dem_conditioning={dem_conditioning}")
    notes.append(f"basin_boundary_source={boundary_source}")
    if boundary_source != "nldi_authoritative" and boundary_provenance is not None:
        notes.append(
            f"basin_boundary_cascade_tier={boundary_provenance.get('tier', 'unknown')}; "
            + "; ".join(boundary_provenance.get("notes", [])[-3:])
        )
    notes.append(f"hru_soil_overlay_source={soil_overlay_source}")
    notes.append(f"soil_provenance_mode={soil_provenance_mode}")
    if constant_soil_mukey is not None:
        notes.append(
            f"constant_soil_mukey={constant_soil_mukey}; diagnostic soil-overlay recovery after empty gNATSGO raster"
        )
    if pct_fallback_soils > soil_fallback_warn_threshold:
        msg = (
            f"Soil fallback ratio {pct_fallback_soils:.2%} exceeds threshold "
            f"{soil_fallback_warn_threshold:.2%}."
        )
        log.warning(msg)
        notes.append(msg)

    md = RunMetadata(
        timestamp_utc=utc_now_iso(),
        usgs_id=STATION_ID,
        requested_outlet_gis_id=int(selection_diag.get("requested_outlet_gis_id", 1)),
        selected_outlet_gis_id=int(pinned_outlet),
        outlet_autodetected=bool(selection_diag.get("outlet_autodetected", False)),
        outlet_selection_reason=str(selection_diag.get("outlet_selection_reason", "")),
        outlet_policy="strict_pinned_from_auto",
        outlet_provenance_path=str(outlet_provenance_path),
        outlet_provenance_sha256=outlet_provenance_sha,
        sim_source_file=str(eval_diag.get("sim_source_file", "") or ""),
        sim_source_sha256=str(eval_diag.get("sim_source_sha256", "") or ""),
        chandeg_con_sha256=str(eval_diag.get("chandeg_con_sha256", "") or ""),
        routing_mode="standard",
        soil_mode=soil_mode,
        soil_provenance_mode=soil_provenance_mode if soil_overlay_source != "gnatsgo_raster" else None,
        boundary_provenance=boundary_provenance if boundary_provenance is not None else None,
        pct_fallback_soils=pct_fallback_soils,
        engine_version=engine_version,
        builder_git_sha=try_git_sha(Path(__file__).resolve().parents[1]),
        input_hashes=input_hashes,
        weather_source="gridmet",
        weather_coverage_flags={
            "nonzero_days": int(pcp_stats.get("nonzero_days", 0)),
            "precip_mean": float(pcp_stats.get("precip_mean", 0.0)),
            "precip_max": float(pcp_stats.get("precip_max", 0.0)),
            "date_range": str(pcp_stats.get("date_range", "")),
            "n_weather_stations": int(len(weather_bundle.stations)),
            "n_subbasins_for_weather_context": int(len(tables.subbasins)),
        },
        retry_attempts=retry_attempts,
        lte_hru_channel_scale_correction=(
            lte_hru_chan_correction if lte_hru_chan_correction > 0.0 else None
        ),
        lte_hru_channel_scale_correction_reason=(
            "SWAT+ v2023.60.5.7 LTE hru_lte→channel transfer scale audit: "
            "engine multiplies water_yield_mm * 1000 * area_ha (should be * 10); "
            "applied hru-lte.con frac correction to cancel ×100 bug."
            if lte_hru_chan_correction > 0.0 else None
        ),
        notes=notes,
    )
    write_metadata(outdir / "metadata.json", md)

    print("\n" + "=" * 72)
    print(f"  Marsh Creek (USGS {STATION_ID}) complete in {time.time() - t_all:.1f}s")
    print("=" * 72 + "\n")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("outdir", nargs="?", default="./usgs_basin_output", type=Path)
    p.add_argument("--run", action="store_true", help="Also run the SWAT+ engine.")
    p.add_argument("--start", default=SIM_START, help="Simulation start date (YYYY-MM-DD).")
    p.add_argument("--end", default=SIM_END, help="Simulation end date (YYYY-MM-DD).")
    p.add_argument("--model-family", default="lte", choices=["lte", "full"],
                   help="Model family: lte (default) or full.")
    p.add_argument("--warmup-years", type=int, default=0,
                   help="Spin-up years to prepend before evaluation (default 2 for full mode).")
    args = p.parse_args()
    warmup_years = args.warmup_years
    if warmup_years == 0 and args.model_family == "full":
        warmup_years = 2  # default for full mode
    try:
        main(
            args.outdir.resolve(),
            run_engine=args.run,
            sim_start=args.start,
            sim_end=args.end,
            warmup_years=warmup_years,
        )
    except Exception as e:
        log.exception("Pipeline failed: %s", e)
        sys.exit(1)
