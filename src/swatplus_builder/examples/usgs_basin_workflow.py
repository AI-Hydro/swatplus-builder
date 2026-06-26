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

    python examples/usgs_basin_workflow.py /tmp/usgs_basin

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
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swatplus_builder.types import SoilProfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
STATION_ID = os.environ.get("USGS_ID", "01547700").strip()
log = logging.getLogger(f"swat_build_{STATION_ID}")
SIM_START = "2015-01-01"
SIM_END = "2015-12-31"
DEM_RESOLUTION_M = 30
DEM_BUFFER_M = float(os.environ.get("SWATPLUS_DEM_BUFFER_M", "10000"))

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


def _sample_evenly(items: list, max_count: int) -> list:
    if max_count <= 0 or len(items) <= max_count:
        return list(items)
    if max_count == 1:
        return [items[len(items) // 2]]
    last = len(items) - 1
    indexes = sorted({round(i * last / (max_count - 1)) for i in range(max_count)})
    return [items[i] for i in indexes]


def _stage_output_file(src: Path, dest: Path, *, hardlink_above_mb: float = 25.0) -> str:
    """Expose an engine output under outputs/ without duplicating large files."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()

    size_mb = src.stat().st_size / (1024 * 1024)
    if size_mb >= hardlink_above_mb:
        try:
            os.link(src, dest)
            return "hardlink"
        except OSError:
            try:
                dest.symlink_to(os.path.relpath(src, dest.parent))
                return "symlink"
            except OSError:
                pass

    shutil.copy2(src, dest)
    return "copy"


def _hru_coverage(hru, ws_stats: dict) -> tuple[int, int, float]:
    n_sub = int(hru.stats.get("n_subbasins", ws_stats.get("n_subbasins", 0)) or 0)
    n_hru = int(hru.stats.get("n_hrus", 0) or 0)
    ratio = (n_hru / max(n_sub, 1)) if n_sub > 0 else 0.0
    return n_sub, n_hru, ratio


def _dominant_valid_mukey_from_raster(path: Path | None) -> int | None:
    if path is None or not path.exists() or path.stat().st_size <= 0:
        return None
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        arr = src.read(1, masked=True)
        nodata = src.nodata
    data = np.asarray(arr.filled(0)).ravel()
    valid = np.isfinite(data)
    valid &= data > 0
    valid &= data != 2_147_483_647
    if nodata is not None:
        valid &= data != nodata
    if not bool(valid.any()):
        return None
    values, counts = np.unique(data[valid].astype("int64"), return_counts=True)
    if values.size == 0:
        return None
    return int(values[int(np.argmax(counts))])


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
    if isinstance(value, float) and math.isnan(value):
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
            p.hyd_grp = norm
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


def fetch_dem(
    basin,
    out_tif: Path,
    resolution_m: int = 30,
    *,
    buffer_m: float = 5000.0,
):
    """Fetch a 3DEP DEM over a buffered rectangular basin extent.

    D8 delineation needs terrain beyond the reference polygon so cells near a
    clipped edge can follow their natural drainage path. The authoritative
    basin polygon remains unchanged and is used later for area/IoU validation.
    """
    import py3dep

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    try:
        import geopandas as gpd
        from shapely.geometry import box

        basin_projected = basin.to_crs("EPSG:5070")
        minx, miny, maxx, maxy = basin_projected.total_bounds
        request_box = box(
            minx - buffer_m,
            miny - buffer_m,
            maxx + buffer_m,
            maxy + buffer_m,
        )
        geom = gpd.GeoSeries([request_box], crs="EPSG:5070").to_crs("EPSG:4326").iloc[0]
        reference_area_km2 = float(basin_projected.geometry.area.sum() / 1e6)
        request_area_km2 = float(request_box.area / 1e6)
        dem = py3dep.get_dem(geom, resolution=resolution_m, crs="EPSG:4326")
    except Exception as exc:
        cached = _find_cached_dem(out_tif)
        if cached is None:
            raise
        shutil.copy2(cached, out_tif)
        sidecar = out_tif.with_suffix(".source.json")
        sidecar.write_text(
            json.dumps(
                {
                    "source": "local_authoritative_3dep_cache",
                    "cached_dem": str(cached),
                    "resolution_m": resolution_m,
                    "dem_buffer_m_requested": buffer_m,
                    "request_shape": "buffered_bounding_box",
                    "cache_buffer_verified": False,
                    "reason": f"py3dep_3dep_fetch_failed: {exc}",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log.warning(
            "3DEP DEM fetch failed for %s; reused local authoritative DEM cache %s",
            STATION_ID,
            cached,
        )
        return out_tif
    dem.rio.to_raster(out_tif, tiled=True, compress="DEFLATE")
    out_tif.with_suffix(".source.json").write_text(
        json.dumps(
            {
                "source": "usgs_3dep_py3dep",
                "resolution_m": resolution_m,
                "dem_buffer_m": buffer_m,
                "request_shape": "buffered_bounding_box",
                "reference_area_km2": reference_area_km2,
                "request_area_km2": request_area_km2,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out_tif


def mask_dem_to_basin(
    dem_tif: Path,
    basin,
    out_tif: Path,
    *,
    buffer_m: float = 100.0,
) -> Path:
    """Write a DEM whose valid domain is constrained to the reference basin.

    This is a recovery path for cases where the unmasked local D8 routing
    crosses an authoritative NLDI basin divide near the outlet. The DEM remains
    the elevation source; the NLDI polygon only constrains the valid drainage
    domain.
    """
    import geopandas as gpd
    import rasterio
    import rasterio.mask

    if isinstance(basin, (str, Path)):
        basin_gdf = gpd.read_file(basin)
    else:
        basin_gdf = basin

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dem_tif) as src:
        nodata = src.nodata if src.nodata is not None else -9999.0
        geoms = list(basin_gdf.to_crs(src.crs).geometry.buffer(buffer_m))
        data, _ = rasterio.mask.mask(
            src,
            geoms,
            crop=False,
            nodata=nodata,
            filled=True,
        )
        meta = src.meta.copy()
        meta.update(nodata=nodata)
        with rasterio.open(out_tif, "w", **meta) as dst:
            dst.write(data)

    out_tif.with_suffix(".source.json").write_text(
        json.dumps(
            {
                "source": "nldi_authoritative_basin_masked_dem",
                "input_dem": str(dem_tif),
                "basin_mask_buffer_m": buffer_m,
                "reason": (
                    "Recovery fallback for DEM-derived D8 routing that fails "
                    "reference area/IoU gates against an authoritative NLDI basin."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out_tif


def _find_cached_dem(out_tif: Path) -> Path | None:
    run_root = out_tif.parent.parent
    search_root = run_root.parent
    if not search_root.exists():
        return None
    candidates = sorted(search_root.glob(f"*{STATION_ID}*/raw/dem.tif"))
    for candidate in candidates:
        if candidate.resolve() == out_tif.resolve():
            continue
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _ensure_datasets_db_with_local_cache(settings, outdir: Path) -> Path:
    from swatplus_builder.errors import SwatBuilderExternalError
    from swatplus_builder.ref.bootstrap import ensure_datasets_db

    try:
        return ensure_datasets_db(settings=settings)
    except SwatBuilderExternalError as exc:
        cached = _find_cached_datasets_db(outdir)
        if cached is None:
            raise
        ref_dir = Path(settings.reference_db_dir).expanduser().resolve()
        ref_dir.mkdir(parents=True, exist_ok=True)
        target = ref_dir / cached.name
        shutil.copy2(cached, target)
        current = ref_dir / "swatplus_datasets.sqlite"
        shutil.copy2(cached, current)
        sidecar = ref_dir / "swatplus_datasets.source.json"
        sidecar.write_text(
            json.dumps(
                {
                    "source": "local_authoritative_swatplus_datasets_cache",
                    "cached_db": str(cached),
                    "reason": f"datasets_db_fetch_failed: {exc}",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log.warning(
            "Datasets DB fetch failed for %s; reused local SWAT+ datasets cache %s",
            STATION_ID,
            cached,
        )
        return current


def _find_cached_datasets_db(outdir: Path) -> Path | None:
    search_root = outdir.parent
    if not search_root.exists():
        return None
    candidates = sorted(search_root.glob("*/reference_dbs/swatplus_datasets-*.sqlite"))
    for candidate in candidates:
        if outdir in candidate.parents:
            continue
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


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
) -> tuple[list[SoilProfile], int]:
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
        try:
            profile = fetch_soilgrids_profile(lon, lat, mukey=mukey)
        except Exception as exc:
            log.warning("SoilGrids fallback failed for mukey=%s: %s", mukey, exc)
            profile = None
        if profile is not None:
            profiles.append(profile)
        else:
            failed += 1

    return profiles, failed


def _replace_default_profiles_with_soilgrids(
    soil_profiles: list,
    outdir: Path,
    boundary_provenance: dict,
) -> tuple[list, int, int]:
    """Replace synthetic-default profiles with explicit SoilGrids fallback.

    SDA can partially succeed: most mukeys receive real horizon profiles, while
    a few fall back to generated defaults. Treat those missing profiles as a
    separate degraded fallback opportunity instead of leaving synthetic defaults
    embedded in an otherwise successful soil acquisition.
    """
    default_profiles = [
        profile
        for profile in soil_profiles
        if str(getattr(profile, "source", "")) == "synthetic_default"
    ]
    if not default_profiles:
        return soil_profiles, 0, 0

    missing_mukeys: list[int] = []
    for profile in default_profiles:
        name = str(getattr(profile, "name", ""))
        try:
            missing_mukeys.append(int(name.removeprefix("gnatsgo_")))
        except ValueError:
            continue

    if not missing_mukeys:
        return soil_profiles, 0, len(default_profiles)

    replacements, failed = _try_soilgrids_fallback(missing_mukeys, outdir, boundary_provenance)
    replacement_by_name = {str(profile.name): profile for profile in replacements}
    updated = [
        replacement_by_name.get(str(getattr(profile, "name", "")), profile)
        for profile in soil_profiles
    ]
    return updated, len(replacement_by_name), failed


def _write_soil_acquisition_report(outdir: Path, report: dict) -> Path:
    path = outdir / "reports" / "soil_acquisition_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def _soil_source_priority_manifest() -> list[dict[str, object]]:
    return [
        {
            "tier": 1,
            "source": "gNATSGO_raster_plus_SDA_horizons",
            "authority": "USDA_NRCS_high_fidelity",
            "research_grade_eligible": True,
            "reason": "Preserves spatial map-unit heterogeneity and uses USDA horizon data.",
        },
        {
            "tier": 2,
            "source": "SDA_spatial_representative_mukey",
            "authority": "USDA_NRCS_degraded_representative",
            "research_grade_eligible": False,
            "reason": "Uses real USDA mukey/horizon data but collapses spatial heterogeneity to one representative soil.",
        },
        {
            "tier": 3,
            "source": "SoilGrids_v2_coarse",
            "authority": "ISRIC_global_coarse_fallback",
            "research_grade_eligible": False,
            "reason": "Uses global 250 m predicted properties and is lower authority than USDA NRCS soil survey data.",
        },
        {
            "tier": 4,
            "source": "synthetic_minimal_soils",
            "authority": "diagnostic_only",
            "research_grade_eligible": False,
            "reason": "Allows engine diagnostics only and cannot support soil-fidelity claims.",
        },
    ]


def _attach_soil_source_priority(report: dict) -> dict:
    out = dict(report)
    out.setdefault("source_priority", _soil_source_priority_manifest())
    return out


def _write_soil_report(outdir: Path, report: dict) -> Path:
    path = outdir / "reports" / "soil_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_attach_soil_source_priority(report), indent=2) + "\n", encoding="utf-8")
    return path


def main(
    outdir: Path,
    run_engine: bool = False,
    *,
    sim_start: str = SIM_START,
    sim_end: str = SIM_END,
    warmup_years: int = 0,
    build_config: object = None,
):
    global STATION_ID, log

    import json

    from swatplus_builder.workflows.full_build import FullBuildConfig

    if isinstance(build_config, FullBuildConfig):
        cfg = build_config
        STATION_ID = cfg.usgs_id
        log = logging.getLogger(f"swat_build_{STATION_ID}")
    else:
        cfg = None

    from swatplus_builder.calibration.nwis import fetch_usgs_daily_q
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
    from swatplus_builder.gis.landuse import select_nlcd_year_for_simulation
    from swatplus_builder.gis.overlay_repair import repair_overlay_inputs
    from swatplus_builder.gis.soil import extract_unique_mukeys, fetch_mukey_raster
    from swatplus_builder.gis.tables import build_tables
    from swatplus_builder.gis.validate import validate_watershed
    from swatplus_builder.output.eval import evaluate_run, terminal_channel_ids
    from swatplus_builder.output.metadata import (
        RunMetadata,
        sha256_file,
        try_git_sha,
        utc_now_iso,
        write_metadata,
    )
    from swatplus_builder.output.mass_trace import fetch_usgs_site_metadata
    from swatplus_builder.output.plots.wrapper import generate_all_plots
    from swatplus_builder.soil.sda import fetch_sda_mukeys_for_geometry
    from swatplus_builder.soil.writer import write_soils
    from swatplus_builder.weather.daymet import fetch_daymet
    from swatplus_builder.weather.gridmet import fetch_gridmet
    from swatplus_builder.weather.writer import write_observed

    outdir.mkdir(parents=True, exist_ok=True)
    t_all = time.time()
    retry_attempts: dict[str, int] = {}
    site_metadata = fetch_usgs_site_metadata(STATION_ID, timeout_s=5.0)
    station_name = str(site_metadata.get("station_nm") or "").strip()
    basin_display_name = f"{station_name} ({STATION_ID})" if station_name else f"USGS {STATION_ID}"

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
    
    # Area Guard: Verify NLDI returned the correct basin for this gauge.
    # EXPECTED_AREA_KM2 must NOT be a module-level constant (it was frozen at
    # import time to 114.0 for Marsh Creek, breaking every other site).
    # Recompute dynamically from STATION_ID.
    _expected_area = (
        float(cfg.expected_area_km2)
        if cfg is not None and cfg.expected_area_km2 is not None
        else float(os.environ.get("EXPECTED_AREA_KM2", "0.0"))
    )
    area_diff_pct = (
        abs(actual_area_km2 - _expected_area) / _expected_area
        if _expected_area > 0
        else 0.0
    )
    if _expected_area > 0 and area_diff_pct > 0.15:
        raise RuntimeError(
            f"Basin area mismatch! Expected ~{_expected_area} km2, got {actual_area_km2:.1f} km2. "
            "Please check the Site ID or NLDI snapping."
        )

    # 2. DEM (3DEP)
    _section(f"2/11 DEM {DEM_RESOLUTION_M} m from USGS 3DEP")
    dem_tif = outdir / "raw" / "dem.tif"
    t0 = time.time()
    _, n = _with_retries(
        "fetch_dem",
        fetch_dem,
        basin,
        dem_tif,
        resolution_m=DEM_RESOLUTION_M,
        buffer_m=cfg.dem_buffer_m if cfg is not None else DEM_BUFFER_M,
    )
    retry_attempts["fetch_dem"] = n
    _ok(f"dem.tif  ({dem_tif.stat().st_size / 1e6:.1f} MB)",
        elapsed=time.time() - t0)

    # 3. NLCD landuse
    nlcd_selection = select_nlcd_year_for_simulation(sim_start, sim_end)
    nlcd_year = int(nlcd_selection["selected_year"])
    _section(f"3/11 NLCD {nlcd_year} landuse from MRLC")
    nlcd_tif = outdir / "raw" / f"nlcd_{nlcd_year}.tif"
    nlcd_selection_path = outdir / "raw" / "nlcd_selection.json"
    nlcd_selection_path.parent.mkdir(parents=True, exist_ok=True)
    nlcd_selection_path.write_text(
        json.dumps(
            {
                **nlcd_selection,
                "source": "MRLC_NLCD_via_pygeohydro.nlcd_bygeom",
                "raster_path": str(nlcd_tif),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    t0 = time.time()
    _, n = _with_retries("fetch_nlcd", fetch_nlcd, basin, nlcd_tif, year=nlcd_year)
    retry_attempts["fetch_nlcd"] = n
    _ok(f"{nlcd_tif.name}  ({nlcd_tif.stat().st_size / 1e6:.1f} MB)",
        elapsed=time.time() - t0)

    # 4. Delineation (WhiteboxTools)
    _section("4/11 Delineation (WhiteboxTools D8)")
    outlet = resolve_usgs_outlet(STATION_ID)
    t0 = time.time()
    base_threshold = (
        int(cfg.stream_threshold_cells)
        if cfg is not None
        else int(os.environ.get("SWATPLUS_STREAM_THRESHOLD_CELLS", "2000"))
    )
    dem_conditioning = (
        cfg.dem_conditioning
        if cfg is not None
        else os.environ.get("SWATPLUS_DEM_CONDITIONING", "breach")
    ).strip().lower()
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
                expected_area_km2=actual_area_km2,
                dem_conditioning=dem_conditioning,
                require_domain_margin=True,
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
        _area_tol = (
            float(cfg.area_tolerance_pct)
            if cfg is not None
            else float(os.environ.get("SWATPLUS_AREA_TOLERANCE_PCT", "10.0"))
        )
        _min_iou = (
            float(cfg.min_iou_pct)
            if cfg is not None
            else float(os.environ.get("SWATPLUS_MIN_IOU_PCT", "70.0"))
        )
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
                min_iou_pct=_min_iou,
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

    if ws is None:
        # All threshold attempts raised SwatBuilderPipelineError (typically multi-terminal
        # on flat terrain). Try once with NHD stream-burned DEM to force D8 connectivity.
        log.warning(
            "All delineation thresholds failed for %s — trying NHD stream-burn fallback.",
            STATION_ID,
        )
        _flowlines_gpkg = outdir / "raw" / "nhd_flowlines.gpkg"
        try:
            from swatplus_builder.gis.nldi_fallback import fetch_nhd_flowlines
            _flowlines_path = fetch_nhd_flowlines(STATION_ID, _flowlines_gpkg)
            if _flowlines_path is not None:
                _burn_workdir = outdir / "delin_burned"
                _is_fallback_bnd = boundary_provenance.get("source") not in (
                    "nldi_authoritative", None
                )
                _area_tol_burn = (
                    float(cfg.area_tolerance_pct)
                    if cfg is not None
                    else float(os.environ.get("SWATPLUS_AREA_TOLERANCE_PCT", "10.0"))
                )
                _min_iou_burn = (
                    float(cfg.min_iou_pct)
                    if cfg is not None
                    else float(os.environ.get("SWATPLUS_MIN_IOU_PCT", "70.0"))
                )
                ws_try = delineate(
                    dem_path=dem_tif,
                    outlet=outlet,
                    workdir=_burn_workdir,
                    stream_threshold_cells=base_threshold,
                    expected_area_km2=actual_area_km2,
                    dem_conditioning=dem_conditioning,
                    stream_burn_vector=_flowlines_path,
                    stream_burn_depth_m=10.0,
                    require_domain_margin=True,
                )
                _vr = validate_watershed(
                    ws_try,
                    reference_polygon=None if _is_fallback_bnd else basin_gpkg,
                    area_tolerance_pct=_area_tol_burn,
                    min_iou_pct=_min_iou_burn,
                )
                _burn_complexity = assess_topology_complexity(ws_try.stats, complexity_policy)
                threshold_attempts.append({
                    "threshold_cells": base_threshold,
                    "validation_passed": _vr.passed,
                    "area_diff_pct": _vr.area_diff_pct,
                    "iou_pct": _vr.iou_pct,
                    "n_subbasins": ws_try.stats.get("n_subbasins"),
                    "n_channels": ws_try.stats.get("n_channels"),
                    "avg_subbasin_area_km2": _burn_complexity.avg_subbasin_area_km2,
                    "complexity_acceptable": _burn_complexity.acceptable,
                    "complexity_reasons": list(_burn_complexity.reasons) + ["stream_burn_fallback"],
                    "topology_suspicious": _topology_suspicious(ws_try.stats),
                })
                ws = ws_try
                validation = _vr
                selected_threshold = base_threshold
                log.info("Stream-burn delineation succeeded for %s.", STATION_ID)
        except SwatBuilderPipelineError as exc:
            log.warning("Stream-burn delineation also failed for %s: %s", STATION_ID, exc)
        except Exception as exc:
            log.warning("Stream-burn fallback error for %s: %s", STATION_ID, exc)

    if ws is None and boundary_provenance.get("source") == "nldi_authoritative":
        # Last-resort CONUS recovery: keep NLDI as the basin authority and use
        # the DEM only inside that valid domain. This handles outlet-adjacent
        # divide/confluence cases where unconstrained D8 routing crosses the
        # reference NLDI basin boundary.
        log.warning(
            "DEM and stream-burn delineation failed for %s — trying NLDI-masked DEM fallback.",
            STATION_ID,
        )
        try:
            _masked_dem = mask_dem_to_basin(
                dem_tif,
                basin,
                outdir / "raw" / "dem_nldi_masked.tif",
                buffer_m=float(os.environ.get("SWATPLUS_NLDI_MASK_BUFFER_M", "100.0")),
            )
            _canonical_delin = outdir / "delin"
            shutil.rmtree(_canonical_delin, ignore_errors=True)
            _area_tol_mask = (
                float(cfg.area_tolerance_pct)
                if cfg is not None
                else float(os.environ.get("SWATPLUS_AREA_TOLERANCE_PCT", "10.0"))
            )
            _min_iou_mask = (
                float(cfg.min_iou_pct)
                if cfg is not None
                else float(os.environ.get("SWATPLUS_MIN_IOU_PCT", "70.0"))
            )
            ws_try = delineate(
                dem_path=_masked_dem,
                outlet=outlet,
                workdir=_canonical_delin,
                stream_threshold_cells=base_threshold,
                expected_area_km2=actual_area_km2,
                dem_conditioning=dem_conditioning,
                require_domain_margin=False,
            )
            _vr = validate_watershed(
                ws_try,
                reference_polygon=basin_gpkg,
                area_tolerance_pct=_area_tol_mask,
                min_iou_pct=_min_iou_mask,
            )
            _mask_complexity = assess_topology_complexity(ws_try.stats, complexity_policy)
            _mask_suspicious = _topology_suspicious(ws_try.stats)
            threshold_attempts.append({
                "threshold_cells": base_threshold,
                "validation_passed": _vr.passed,
                "area_diff_pct": _vr.area_diff_pct,
                "iou_pct": _vr.iou_pct,
                "n_subbasins": ws_try.stats.get("n_subbasins"),
                "n_channels": ws_try.stats.get("n_channels"),
                "avg_subbasin_area_km2": _mask_complexity.avg_subbasin_area_km2,
                "complexity_acceptable": _mask_complexity.acceptable,
                "complexity_reasons": list(_mask_complexity.reasons) + ["nldi_masked_dem_fallback"],
                "topology_suspicious": _mask_suspicious,
            })
            ws = ws_try
            validation = _vr
            selected_threshold = base_threshold
            log.info(
                "NLDI-masked DEM delineation completed for %s: passed=%s area_diff_pct=%s iou_pct=%s.",
                STATION_ID,
                _vr.passed,
                _vr.area_diff_pct,
                _vr.iou_pct,
            )
        except SwatBuilderPipelineError as exc:
            threshold_attempts.append({
                "threshold_cells": base_threshold,
                "validation_passed": False,
                "area_diff_pct": None,
                "iou_pct": None,
                "n_subbasins": exc.context.get("n_subbasins"),
                "n_channels": exc.context.get("n_channels"),
                "avg_subbasin_area_km2": None,
                "complexity_acceptable": False,
                "complexity_reasons": [str(exc), "nldi_masked_dem_fallback"],
                "topology_suspicious": True,
            })
            log.warning("NLDI-masked DEM fallback failed for %s: %s", STATION_ID, exc)
        except Exception as exc:
            threshold_attempts.append({
                "threshold_cells": base_threshold,
                "validation_passed": False,
                "area_diff_pct": None,
                "iou_pct": None,
                "n_subbasins": None,
                "n_channels": None,
                "avg_subbasin_area_km2": None,
                "complexity_acceptable": False,
                "complexity_reasons": [str(exc), "nldi_masked_dem_fallback"],
                "topology_suspicious": True,
            })
            log.warning("NLDI-masked DEM fallback error for %s: %s", STATION_ID, exc)

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
    hru_soil_raster: Path | None = mukey_tif
    soil_overlay_source = "gnatsgo_raster"
    soil_provenance_mode = "gnatsgo_raster"
    gnatsgo_fetch_error: str | None = None
    try:
        _, n = _with_retries(
            "fetch_mukey_raster",
            fetch_mukey_raster,
            boundary=boundary_geom,
            boundary_crs="EPSG:4326",
            output_path=mukey_tif,
        )
        retry_attempts["fetch_mukey_raster"] = n
    except Exception as exc:
        gnatsgo_fetch_error = str(exc)
        retry_attempts["fetch_mukey_raster"] = int(os.environ.get("SWATPLUS_FETCH_MAX_ATTEMPTS", "4"))
        hru_soil_raster = None
        soil_overlay_source = "gnatsgo_raster_unavailable"
        soil_provenance_mode = "gnatsgo_raster_unavailable"
        log.warning(
            "gNATSGO mukey raster unavailable for %s after retries: %s. "
            "Trying USDA SDA spatial mukey fallback with degraded soil-overlay provenance.",
            STATION_ID,
            exc,
        )
    mukey_file_mb = mukey_tif.stat().st_size / 1e6 if mukey_tif.exists() else 0.0

    # Normalize soil raster CRS to match DEM. Planetary Computer delivers
    # gNATSGO in ESRI:102039, but the DEM is EPSG:5070. They are functionally
    # the same CONUS Albers projection, but the mismatched CRS labels cause
    # rasterio's alignment step to lose >97% of soil pixels. Copy the file
    # with the correct CRS label.
    if gnatsgo_fetch_error is None and mukey_tif.exists():
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
    sda_spatial_strategy = "not_needed_gnatsgo_raster_has_mukeys"
    sda_spatial_error: str | None = None
    if not mukey_values:
        max_sda_area_km2 = float(os.environ.get("SWATPLUS_SDA_SPATIAL_MAX_AREA_KM2", "1000.0"))
        sda_timeout_s = float(os.environ.get("SWATPLUS_SDA_SPATIAL_TIMEOUT_S", "20.0"))
        if actual_area_km2 > max_sda_area_km2:
            retry_attempts["fetch_sda_mukeys_for_geometry"] = 0
            sda_spatial_strategy = "skipped_large_aoi"
            sda_spatial_error = (
                f"AOI area {actual_area_km2:.1f} km2 exceeds "
                f"SWATPLUS_SDA_SPATIAL_MAX_AREA_KM2={max_sda_area_km2:.1f}; "
                "large-polygon SDA intersections are provider-timeout prone."
            )
            log.warning(
                "Skipping SDA spatial mukey fallback for %s: %s",
                STATION_ID,
                sda_spatial_error,
            )
        else:
            retry_attempts["fetch_sda_mukeys_for_geometry"] = 1
            sda_spatial_strategy = "single_bounded_query"
            try:
                sda_spatial_mukeys = fetch_sda_mukeys_for_geometry(
                    boundary_geom,
                    cache_dir=outdir / "cache",
                    timeout_s=sda_timeout_s,
                )
            except Exception as exc:
                sda_spatial_error = str(exc)
                log.warning(
                    "SDA spatial mukey fallback failed for %s after one bounded query: %s",
                    STATION_ID,
                    exc,
                )
        if gnatsgo_fetch_error is not None:
            soil_overlay_source = (
                "sda_spatial_representative_after_gnatsgo_unavailable"
                if sda_spatial_mukeys
                else "constant_placeholder_after_gnatsgo_unavailable"
            )
        else:
            soil_overlay_source = (
                "sda_spatial_representative_after_empty_gnatsgo"
                if sda_spatial_mukeys
                else "constant_placeholder_after_empty_gnatsgo"
            )
        soil_provenance_mode = "sda_representative" if sda_spatial_mukeys else "diagnostic_placeholder"
        hru_soil_raster = None
        constant_soil_mukey = (
            int(sda_spatial_mukeys[0])
            if sda_spatial_mukeys
            else int(os.environ.get("SWATPLUS_SDA_PLACEHOLDER_MUKEY", "900000001"))
        )
        log.warning(
            "gNATSGO mukey raster is unavailable or empty for %s. Continuing HRU overlay with explicit "
            "constant representative mukey=%s so the run can produce diagnostic artifacts. "
            "SDA spatial strategy=%s; mukeys found=%d. This preserves a real SDA soil profile when available, "
            "but it does not preserve spatial soil heterogeneity.",
            STATION_ID,
            constant_soil_mukey,
            sda_spatial_strategy,
            len(sda_spatial_mukeys),
        )
    _ok(
        f"mukey.tif  ({mukey_file_mb:.1f} MB, unique_mukeys={len(mukey_values)}, soil_overlay_source={soil_overlay_source})",
        elapsed=time.time() - t0,
    )

    # 6. HRUs
    hru_mode = (cfg.hru_mode if cfg else None) or os.environ.get("SWATPLUS_HRU_MODE", "dominant_only").strip().lower()
    if hru_mode not in {"dominant_only", "full_overlay"}:
        raise ValueError("SWATPLUS_HRU_MODE must be one of: dominant_only, full_overlay")
    hru_dominant_only = hru_mode == "dominant_only"
    min_hru_fraction = float(cfg.min_hru_fraction if cfg else os.environ.get("SWATPLUS_MIN_HRU_FRACTION", "0.0"))
    if min_hru_fraction < 0.0:
        raise ValueError("SWATPLUS_MIN_HRU_FRACTION must be non-negative")
    _section(f"6/11 HRU overlay ({hru_mode})")
    t0 = time.time()
    hru = create_hrus(
        watershed=ws,
        landuse_raster=nlcd_tif,
        soil_raster=hru_soil_raster,
        constant_soil_mukey=constant_soil_mukey,
        dominant_only=hru_dominant_only,
        min_hru_fraction=min_hru_fraction,
    )
    n_sub, n_hru, hru_coverage_ratio = _hru_coverage(hru, ws.stats)
    min_hru_coverage_ratio = float(os.environ.get("SWATPLUS_MIN_HRU_COVERAGE_RATIO", "0.90"))
    max_overlay_repair_gap_fraction = float(
        os.environ.get("SWATPLUS_OVERLAY_REPAIR_MAX_GAP_FRACTION", "0.15")
    )
    overlay_repair_report = None
    if hru_coverage_ratio < min_hru_coverage_ratio:
        overlay_repair_report = repair_overlay_inputs(
            dem_tif,
            nlcd_tif,
            hru_soil_raster,
            outdir / "reports" / "overlay_repair",
            max_gap_fraction=max_overlay_repair_gap_fraction,
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
                dominant_only=hru_dominant_only,
                min_hru_fraction=min_hru_fraction,
            )
            n_sub, n_hru, hru_coverage_ratio = _hru_coverage(hru, ws.stats)
        if hru_coverage_ratio < min_hru_coverage_ratio and hru_soil_raster is not None:
            representative_mukey = (
                _dominant_valid_mukey_from_raster(hru_soil_raster)
                or (int(sorted(mukey_values)[0]) if mukey_values else None)
                or (int(sda_spatial_mukeys[0]) if sda_spatial_mukeys else None)
                or int(os.environ.get("SWATPLUS_SDA_PLACEHOLDER_MUKEY", "900000001"))
            )
            previous_soil_overlay_source = soil_overlay_source
            soil_overlay_source = (
                "constant_representative_after_partial_gnatsgo_gap"
                if mukey_values
                else "constant_placeholder_after_partial_gnatsgo_gap"
            )
            soil_provenance_mode = "diagnostic_partial_gnatsgo_constant"
            constant_soil_mukey = int(representative_mukey)
            hru_soil_raster = None
            log.warning(
                "HRU coverage stayed below %.2f%% after bounded overlay repair "
                "(coverage=%.2f%%, n_hrus=%d, n_subbasins=%d). Rebuilding HRUs for "
                "%s with constant representative mukey=%s from partial soil source %s. "
                "This is diagnostic-only and does not preserve spatial soil heterogeneity.",
                min_hru_coverage_ratio * 100.0,
                hru_coverage_ratio * 100.0,
                n_hru,
                n_sub,
                STATION_ID,
                constant_soil_mukey,
                previous_soil_overlay_source,
            )
            hru = create_hrus(
                watershed=ws,
                landuse_raster=nlcd_tif,
                soil_raster=None,
                constant_soil_mukey=constant_soil_mukey,
                workdir_subdir="hrus_constant_soil_representative",
                dominant_only=hru_dominant_only,
                min_hru_fraction=min_hru_fraction,
            )
            n_sub, n_hru, hru_coverage_ratio = _hru_coverage(hru, ws.stats)
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
    datasets_db = _ensure_datasets_db_with_local_cache(ref_settings, outdir)
    
    project_dir = outdir / "project"
    project_dir.mkdir(exist_ok=True)
    t0 = time.time()
    db_path = create_project_db(f"usgs_{STATION_ID}", project_dir, reference_db=datasets_db, overwrite=True)
    write_all(db_path, tables)
    _ok("project.sqlite created", elapsed=time.time() - t0)

    # 8. Soils
    _section("8/11 Soils (SDA + Hybrid Fallback)")
    t0 = time.time()
    mukeys = sorted({int(h.soil.removeprefix('gnatsgo_')) for h in tables.hrus})
    from swatplus_builder.soil.builder import fetch_soil_profiles_result
    from swatplus_builder.soil.models import SoilConfig
    soil_mode = "high_fidelity"
    pct_fallback_soils = 0.0
    soil_fallback_warn_threshold = float(os.environ.get("SWATPLUS_SOIL_FALLBACK_WARN_THRESHOLD", "0.25"))
    allow_synthetic_soils = (
        cfg.allow_diagnostic_fallbacks if cfg else _truthy_env("SWATPLUS_ALLOW_SYNTHETIC_SOILS", default=False)
    )
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
        soil_profiles, soilgrids_partial_replacements, soilgrids_partial_failed = (
            _replace_default_profiles_with_soilgrids(
                list(soil_profiles),
                outdir,
                boundary_provenance,
            )
        )
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
        soil_report["sda_spatial_strategy"] = sda_spatial_strategy
        if sda_spatial_error is not None:
            soil_report["sda_spatial_error"] = sda_spatial_error
        if gnatsgo_fetch_error is not None:
            soil_report["gnatsgo_fetch_error"] = gnatsgo_fetch_error
        if overlay_repair_report is not None:
            soil_report["hru_overlay_repair"] = overlay_repair_report.model_dump()
        if soilgrids_partial_replacements > 0 or soilgrids_partial_failed > 0:
            soil_report["soilgrids_partial_replacements"] = soilgrids_partial_replacements
            soil_report["soilgrids_partial_failed"] = soilgrids_partial_failed
            soil_report["soilgrids_live_enabled"] = (
                os.environ.get("SWATPLUS_ENABLE_SOILGRIDS_LIVE") == "1"
            )
            if soilgrids_partial_replacements > 0:
                soil_provenance_mode = "partial_soilgrids_coarse"
                soil_report["authority_note"] = (
                    "SDA returned real horizons for some mukeys but not all. "
                    "Missing synthetic-default profiles were replaced with "
                    "SoilGrids v2.0 coarse profiles where available. This is "
                    "degraded provenance and cannot support research-grade "
                    "soil claims."
                )
        if constant_soil_mukey is not None:
            soil_mode = "fallback"
            pct_fallback_soils = 1.0
            soil_report["constant_soil_mukey"] = constant_soil_mukey
            soil_report["soil_provenance_mode"] = soil_provenance_mode
            if soil_provenance_mode == "diagnostic_partial_gnatsgo_constant":
                soil_report["authority_note"] = (
                    "gNATSGO raster had partial watershed coverage that left too many subbasins without "
                    "valid soil overlay pixels; HRU overlay used one dominant valid representative mukey. "
                    "SDA horizons may be real for that mukey, but spatial soil heterogeneity is degraded "
                    "and research-grade claims remain blocked by the soil realism gate."
                )
            else:
                soil_report["authority_note"] = (
                    "gNATSGO raster was unavailable or empty; HRU overlay used one constant representative mukey. "
                    "SDA horizons may be real for that mukey, but spatial soil heterogeneity is degraded."
                )
        write_soils(soil_profiles, db_path)
        from swatplus_builder.soil.plot import plot_depth_distribution
        plot_depth_distribution(soil_profiles, out_path=outdir / "plots" / "soil_depth_preview.png")
        requested = max(int(soil_report.get("requested_mukeys", 0)), 1)
        default_fallback = int(soil_report.get("aggregated", {}).get("default_fallback", 0))
        degraded_soilgrids = int(soil_report.get("soilgrids_partial_replacements", 0))
        unresolved_fallback = max(default_fallback - degraded_soilgrids, 0)
        if degraded_soilgrids > 0:
            aggregated = soil_report.get("aggregated")
            if isinstance(aggregated, dict):
                aggregated["default_fallback"] = unresolved_fallback
                aggregated["soilgrids_v2_coarse"] = degraded_soilgrids
        pct_fallback_soils = min(max((unresolved_fallback + degraded_soilgrids) / requested, 0.0), 1.0)
        if constant_soil_mukey is not None:
            pct_fallback_soils = 1.0
        if pct_fallback_soils > 0.0:
            soil_mode = "fallback"
        soil_report["soil_mode"] = soil_mode
        soil_report["soil_provenance_mode"] = soil_provenance_mode
        soil_report["soil_overlay_source"] = soil_overlay_source
        soil_report["pct_fallback_soils"] = pct_fallback_soils
        upsert_project_metadata(db_path, "soil_report", json.dumps(soil_report))
        _write_soil_report(outdir, soil_report)
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
            pct_fallback_soils = 1.0
            soil_report = {
                "soil_mode": soil_mode,
                "soil_provenance_mode": soil_provenance_mode,
                "soil_source": "soilgrids_coarse",
                "hru_soil_overlay_source": soil_overlay_source,
                "soil_overlay_source": soil_overlay_source,
                "requested_mukeys": len(mukeys),
                "soilgrids_resolved": len(soilgrids_profiles),
                "soilgrids_failed": soilgrids_failed,
                "soilgrids_coarse_profile_fraction": len(soilgrids_profiles) / max(len(mukeys), 1),
                "fallback_reason": "soilgrids_coarse_profiles_are_degraded_provenance",
                    "sda_error": str(e)[:200],
                    "sda_spatial_strategy": sda_spatial_strategy,
                    "sda_spatial_error": sda_spatial_error,
                }
            _write_soil_acquisition_report(outdir, soil_report)
            _write_soil_report(outdir, soil_report)
            write_soils(soil_profiles, db_path)
            upsert_project_metadata(db_path, "soil_report", json.dumps(soil_report))
            _ok(f"wrote {len(soil_profiles)} profiles (SoilGrids fallback)", elapsed=time.time() - t0)
        elif not allow_synthetic_soils:
            _write_soil_acquisition_report(
                outdir,
                _attach_soil_source_priority({
                    "soil_mode": "failed",
                    "soil_provenance_mode": "none",
                    "requested_mukeys": len(mukeys),
                    "soil_overlay_source": soil_overlay_source,
                    "hru_soil_overlay_source": soil_overlay_source,
                    "sda_error": str(e)[:500],
                    "sda_spatial_strategy": sda_spatial_strategy,
                    "sda_spatial_error": sda_spatial_error,
                    "soilgrids_attempted": True,
                    "soilgrids_live_enabled": os.environ.get("SWATPLUS_ENABLE_SOILGRIDS_LIVE") == "1",
                    "soilgrids_resolved": 0,
                    "soilgrids_failed": soilgrids_failed,
                    "synthetic_soils_allowed": False,
                    "fallback_chain": [
                        "external_soils_json",
                        "usda_sda_horizon_profiles",
                        "bounded_sda_spatial_mukey_query",
                        "soilgrids_v2_coarse_optional",
                        "synthetic_diagnostic_only",
                    ],
                    "recommended_next_action": (
                        "Provide SWATPLUS_EXTERNAL_SOILS_JSON with authoritative profiles, "
                        "install soil extras and retry SDA, or set SWATPLUS_ENABLE_SOILGRIDS_LIVE=1 "
                        "for degraded diagnostic SoilGrids fallback. Synthetic soils require "
                        "SWATPLUS_ALLOW_SYNTHETIC_SOILS=1 and cannot support research-grade claims."
                    ),
                }),
            )
            raise RuntimeError(
                "Soil acquisition failed and synthetic soil fallback is disabled for research runs. "
                "Install soil extras (including fsspec/adlfs), provide SWATPLUS_EXTERNAL_SOILS_JSON, "
                "set SWATPLUS_ENABLE_SOILGRIDS_LIVE=1 for degraded diagnostic SoilGrids fallback, "
                "or set SWATPLUS_ALLOW_SYNTHETIC_SOILS=1 for diagnostic-only runs."
            ) from e
        else:
            # Tier 3: synthetic as absolute last resort
            log.warning("Soils failed (%s). Seeding minimal because synthetic override is enabled.", e)
            seed_minimal_soils(db_path, {h.soil for h in tables.hrus})
            soil_mode = "synthetic"
            pct_fallback_soils = 1.0
            _ok("seed_minimal_soils (fallback)")

    max_soil_fallback_ratio = float(
        (1.0 if cfg and cfg.allow_diagnostic_fallbacks else None)
        or os.environ.get("SWATPLUS_MAX_SOIL_FALLBACK_RATIO", "0.00")
    )
    if (soil_mode == "synthetic" or pct_fallback_soils > max_soil_fallback_ratio) and not allow_synthetic_soils:
        raise RuntimeError(
            "Soil realism gate failed: "
            f"soil_mode={soil_mode}, pct_fallback_soils={pct_fallback_soils:.2%}, "
            f"allowed_max={max_soil_fallback_ratio:.2%}. "
            "Set SWATPLUS_ALLOW_SYNTHETIC_SOILS=1 to override for diagnostic-only runs."
        )

    # 9/11 Weather from GridMET, with Daymet fallback when GridMET is unreachable.
    _section("9/11 Weather from GridMET")
    t0 = time.time()
    max_weather_stations = max(1, int(os.environ.get("SWATPLUS_MAX_WEATHER_STATIONS", "25")))
    subs_for_weather = list(tables.subbasins)
    subs_for_weather = _sample_evenly(subs_for_weather, max_weather_stations)
    from datetime import datetime as _dt
    eval_start_dt = _dt.strptime(sim_start, "%Y-%m-%d")
    weather_start = (_dt(eval_start_dt.year - warmup_years, eval_start_dt.month, eval_start_dt.day)
                     if warmup_years > 0 else eval_start_dt)
    weather_start_str = weather_start.strftime("%Y-%m-%d")

    stations = [(float(s.lat), float(s.lon), float(s.elev)) for s in subs_for_weather]
    weather_provider_fallback_reason = None
    weather_station_selection = "distributed_gridmet_points"
    weather_source = "gridmet"
    try:
        weather_bundle = fetch_gridmet(
            stations,
            start=weather_start_str,
            end=sim_end,
            settings=ref_settings
        )
    except Exception as exc:
        from swatplus_builder.errors import SwatBuilderExternalError

        if not isinstance(exc, SwatBuilderExternalError) or len(stations) <= 1:
            raise
        fallback_max = max(
            1,
            int(os.environ.get("SWATPLUS_GRIDMET_FALLBACK_WEATHER_STATIONS", "5")),
        )
        fallback_subs = _sample_evenly(list(tables.subbasins), min(fallback_max, len(tables.subbasins)))
        fallback_stations = [(float(s.lat), float(s.lon), float(s.elev)) for s in fallback_subs]
        weather_provider_fallback_reason = (
            "distributed_gridmet_point_fetch_failed; "
            f"retrying_with_{len(fallback_stations)}_representative_gridmet_points"
        )
        weather_station_selection = "representative_gridmet_points_after_provider_timeout"
        log.warning("%s: %s", weather_provider_fallback_reason, exc)
        try:
            weather_bundle = fetch_gridmet(
                fallback_stations,
                start=weather_start_str,
                end=sim_end,
                settings=ref_settings,
            )
        except Exception as fallback_exc:
            if not isinstance(fallback_exc, SwatBuilderExternalError):
                raise
            daymet_enabled = os.environ.get("SWATPLUS_ENABLE_DAYMET_FALLBACK", "1") != "0"
            if not daymet_enabled:
                raise
            weather_provider_fallback_reason = (
                f"{weather_provider_fallback_reason}; representative_gridmet_fetch_failed; "
                f"using_daymet_{len(fallback_stations)}_representative_points"
            )
            weather_station_selection = "representative_daymet_points_after_gridmet_failure"
            weather_source = "daymet"
            log.warning("%s: %s", weather_provider_fallback_reason, fallback_exc)
            weather_bundle = fetch_daymet(
                fallback_stations,
                start=weather_start_str,
                end=sim_end,
                settings=ref_settings,
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
        f"fetched {weather_source} for {len(weather_bundle.stations)} stations (from {len(tables.subbasins)} subbasins)",
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

    from swatplus_builder.full_mode.warmup import (
        reset_and_apply_warmup as _reset_and_apply_warmup,
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
            _reset_and_apply_warmup(
                wf.txtinout_dir,
                warmup_years=warmup_years,
                evaluation_start_year=eval_start_dt.year,
            )
            log.info("Applied %d-year spin-up warmup (stale-safe reset)", warmup_years)
    else:
        # LTE cold-start: without spin-up, a 1-year simulation starting with zero
        # soil/GW storage produces zero channel flow on Linux (Intel ifx binary).
        # Prepend 2 warmup years; the engine uses WGN for those years since the
        # observed weather files only cover the evaluation period. nyskip=2 ensures
        # only the evaluation-period output reaches channel_sd_day.txt.
        _lte_warmup = warmup_years if warmup_years > 0 else 2
        try:
            _reset_and_apply_warmup(
                wf.txtinout_dir,
                warmup_years=_lte_warmup,
                evaluation_start_year=eval_start_dt.year,
            )
            log.info("Applied %d-year LTE spin-up warmup", _lte_warmup)
        except Exception as _warmup_err:
            log.warning("LTE warmup skipped (non-fatal): %s", _warmup_err)

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
        eval_year = d_start.year  # original evaluation year before warmup adjustment
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
                    # nyskip = years between warmup start and evaluation start.
                    # max() guards against warmup_years being set explicitly too.
                    nskip = max(warmup_years, eval_year - start_year)
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
    # Prefer daily basin output when available; otherwise use channel_sdmorph_day
    # because it carries the same SWAT-deg flow fields as channel_sd_day with
    # less output-table overhead for outlet evaluation.
    sim_path = wf.txtinout_dir / "basin_sd_cha_day.txt"
    if not sim_path.exists():
        sim_path = wf.txtinout_dir / "channel_sdmorph_day.txt"
    if not sim_path.exists():
        sim_path = wf.txtinout_dir / "channel_sd_day.txt"
    if not sim_path.exists():
        sim_path = wf.txtinout_dir / "channel_day.txt"
    terminal_ids = terminal_channel_ids(wf.txtinout_dir)
    requested_outlet = terminal_ids[0] if terminal_ids else 1
    selection_eval = evaluate_run(
        sim_path,
        q_obs,
        outlet_gis_id=requested_outlet,
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
            "requested_outlet_gis_id": int(requested_outlet),
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
    sim_source_stage_method: str | None = None
    if sim_source_file:
        src = wf.txtinout_dir / sim_source_file
        if src.exists():
            sim_source_stage_method = _stage_output_file(src, outputs_dir / sim_source_file)
    
    plot_res = generate_all_plots(
        run_dir=outdir,
        include_spatial=True,
        metadata={
            "basin_name": basin_display_name,
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
    notes.append(
        f"nlcd_year={nlcd_year}; sim_midpoint_year={nlcd_selection['sim_midpoint_year']}; "
        f"landuse_vintage_mismatch_years={nlcd_selection['landuse_vintage_mismatch_years']}"
    )
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
    if site_metadata.get("available"):
        notes.append(
            f"usgs_site_metadata: station_nm={station_name}; source={site_metadata.get('source')}"
        )
    else:
        notes.append(
            f"usgs_site_metadata_unavailable: error={site_metadata.get('error', 'unknown')}; "
            "display_name_fallback=USGS_ID"
        )
    if overlay_repair_report is not None:
        notes.append(
            f"hru_overlay_repair={overlay_repair_report.reason}; "
            f"landuse_filled={overlay_repair_report.landuse_filled_cells}; "
            f"soil_filled={overlay_repair_report.soil_filled_cells}; "
            f"landuse_gap_fraction={overlay_repair_report.landuse_gap_fraction:.4f}; "
            f"soil_gap_fraction={overlay_repair_report.soil_gap_fraction:.4f}; "
            f"max_gap_fraction={overlay_repair_report.max_gap_fraction:.4f}"
        )
    notes.append(f"dem_conditioning={dem_conditioning}")
    dem_source_path = dem_tif.with_suffix(".source.json")
    if dem_source_path.exists():
        try:
            dem_source = json.loads(dem_source_path.read_text(encoding="utf-8"))
        except Exception:
            dem_source = {"source": "unknown"}
        notes.append(
            f"dem_source={dem_source.get('source', 'unknown')}; "
            f"resolution_m={dem_source.get('resolution_m', DEM_RESOLUTION_M)}; "
            f"buffer_m={dem_source.get('dem_buffer_m', dem_source.get('dem_buffer_m_requested', 0))}; "
            f"request_shape={dem_source.get('request_shape', 'unknown')}"
        )
    datasets_source_path = outdir / "reference_dbs" / "swatplus_datasets.source.json"
    if datasets_source_path.exists():
        try:
            datasets_source = json.loads(datasets_source_path.read_text(encoding="utf-8"))
        except Exception:
            datasets_source = {"source": "unknown"}
        notes.append(f"datasets_db_source={datasets_source.get('source', 'unknown')}")
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
            f"constant_soil_mukey={constant_soil_mukey}; diagnostic soil-overlay recovery via {soil_overlay_source}"
        )
    if gnatsgo_fetch_error is not None:
        notes.append(f"gnatsgo_fetch_error={gnatsgo_fetch_error}")
    if pct_fallback_soils > soil_fallback_warn_threshold:
        msg = (
            f"Soil fallback ratio {pct_fallback_soils:.2%} exceeds threshold "
            f"{soil_fallback_warn_threshold:.2%}."
        )
        log.warning(msg)
        notes.append(msg)
    if weather_provider_fallback_reason is not None:
        notes.append(f"weather_provider_fallback={weather_provider_fallback_reason}")
    if sim_source_stage_method is not None:
        notes.append(
            f"sim_source_staged_to_outputs={sim_source_file}; method={sim_source_stage_method}"
        )

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
        weather_source=weather_source,
        weather_coverage_flags={
            "nonzero_days": int(pcp_stats.get("nonzero_days", 0)),
            "precip_mean": float(pcp_stats.get("precip_mean", 0.0)),
            "precip_max": float(pcp_stats.get("precip_max", 0.0)),
            "date_range": str(pcp_stats.get("date_range", "")),
            "n_weather_stations": int(len(weather_bundle.stations)),
            "n_subbasins_for_weather_context": int(len(tables.subbasins)),
            "station_selection": weather_station_selection,
            "provider_fallback_reason": weather_provider_fallback_reason or "",
            "weather_variables": sorted(
                {
                    var
                    for series in weather_bundle.stations
                    for var in series.variables()
                }
            ),
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
    print(f"  {basin_display_name} complete in {time.time() - t_all:.1f}s")
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
