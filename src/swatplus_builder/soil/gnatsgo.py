"""gNATSGO → :class:`SoilProfile` adapter.

Pulls USDA-NRCS gNATSGO (gridded, stacked National Soil Geographic
Database) tables from Microsoft's Planetary Computer STAC catalog and
produces one :class:`SoilProfile` per requested ``mukey`` (map unit
key).

Why Planetary Computer / not raw SSURGO?
    The legacy SSURGO SOAP "Soil Data Access" endpoint is slow, has
    per-query caps, and requires XML wrangling. gNATSGO-on-PC is a
    single Parquet-on-Azure store per table, queryable with pandas in
    a few hundred milliseconds once the mukey filter is applied.

Pipeline:

    ``mukeys``  →  query ``gnatsgo-tables`` STAC collection
               →  read ``component`` parquet (filter by mukey, pick
                   majority component per mukey by ``comppct_r``)
               →  read ``chorizon`` parquet (filter by chosen ``cokey``,
                   sort by ``hzdept_r``)
               →  read ``muaggatt`` parquet (filter by mukey, grab
                   ``hydgrpdcd``)
               →  per-horizon unit conversions / derivations
                   (see :mod:`.params`)
               →  :class:`SoilProfile` with
                   ``name = f"gnatsgo_{mukey}"``

Optional dependencies: ``pystac-client``, ``planetary-computer``,
``pyarrow`` (for Parquet). Install via
``pip install 'swatplus-builder[soils]'``.

Lazy-imported so ``from swatplus_builder.soil import ...`` works in a
minimal env; the failure mode is a clear
:class:`SwatBuilderExternalError` only if the caller actually invokes
:func:`fetch_gnatsgo_profiles`.

Soil data strategy (authoritative)
----------------------------------

- **Aggregated soil profiles** (muaggatt-based synthetic layers) are the
  default and guaranteed path.
- **Horizon-based profiles** are opportunistic and only used when they
  meet explicit usability criteria (depth + layer count).
- The system does **not** assume Planetary Computer provides complete
  national SSURGO/gNATSGO horizons.

Invariant:
    For any mukey that appears in HRUs, the pipeline should be able to
    produce a deterministic :class:`SoilProfile` without requiring full
    horizon coverage.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)
from ..types import SoilProfile
from .params import collapse_dual_hyd_group, horizon_from_chorizon

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "DEFAULT_PC_STAC_URL",
    "GnatsgoFetchOptions",
    "fetch_gnatsgo_profiles",
    "SoilProfilesResult",
    "fetch_gnatsgo_profiles_result",
]


DEFAULT_PC_STAC_URL: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
"""Stable Planetary Computer STAC root. Override per-call via
:class:`GnatsgoFetchOptions` when testing against a local mirror."""

# Minimum columns we must find in each table. If Microsoft ever drops
# any of these, we fail in :func:`_require_columns` with a pointer to
# the offending table.
_COMPONENT_COLS: tuple[str, ...] = (
    "mukey", "cokey", "comppct_r", "compname", "hydgrp",
)
_CHORIZON_COLS: tuple[str, ...] = (
    "cokey", "chkey", "hzdept_r", "hzdepb_r",
    "sandtotal_r", "silttotal_r", "claytotal_r",
    "ksat_r", "wthirdbar_r", "wfifteenbar_r", "om_r", "dbthirdbar_r",
)
_MUAGGATT_COLS: tuple[str, ...] = ("mukey", "hydgrpdcd")
_MUAGGATT_OPTIONAL_COLS: tuple[str, ...] = (
    # Enough to build a stable synthetic profile when horizons are missing.
    "aws025wta", "aws050wta", "aws0100wta", "aws0150wta",
    "brockdepmin", "wtdepannmin",
)

# Aggregated profile defaults / invariants (baseline mental model).
_AGG_LAYER_BREAKS_MM: tuple[float, ...] = (300.0, 1000.0, 1500.0)
_AGG_MIN_LAYERS: int = 2

# Horizon usability thresholds (enhancement path, not baseline).
_HZ_MIN_LAYERS: int = 2
_HZ_MIN_DEPTH_MM: float = 500.0


@dataclass(frozen=True)
class GnatsgoFetchOptions:
    """Tunable knobs for :func:`fetch_gnatsgo_profiles`."""

    stac_url: str = DEFAULT_PC_STAC_URL
    tables_collection: str = "gnatsgo-tables"
    cache_dir: Path | None = None
    """Where to drop downloaded Parquet files. Defaults to
    ``Settings.reference_db_dir.parent / 'gnatsgo_cache'``."""


@dataclass(frozen=True)
class SoilProfilesResult:
    """Return type for :func:`fetch_gnatsgo_profiles_result`."""

    profiles: list[SoilProfile]
    soil_report: dict[str, Any]


def fetch_gnatsgo_profiles(
    mukeys: Iterable[int],
    *,
    options: GnatsgoFetchOptions | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> list[SoilProfile]:
    """Download gNATSGO tables and return one :class:`SoilProfile` per mukey.

    Profile name is ``f"gnatsgo_{mukey}"`` so the GIS writer can set
    ``gis_hrus.soil = "gnatsgo_{mukey}"`` up front without waiting on
    the fetch to finish.

    Args:
        mukeys: Map unit keys (non-negative ints). Duplicates collapse.
        options: Per-call overrides. Default: :class:`GnatsgoFetchOptions`.
        settings: Runtime overrides (used for cache-dir defaulting).

    Returns:
        List of :class:`SoilProfile`, one per **successfully-resolved**
        mukey. Map units where every component lacks chorizon data are
        **omitted** (logged but not raised) — SSURGO's ``NOTCOM`` / rock-
        outcrop-only map units are the usual culprits and SWAT+ HRUs on
        those pixels need a seed soil anyway (typically urban or bare).

    Raises:
        SwatBuilderInputError:    empty mukey set, or any non-int member.
        SwatBuilderExternalError: STAC query failed, Parquet read failed,
            ``[soils]`` extras not installed.
        SwatBuilderPipelineError: one of the STAC tables is missing a
            column we depend on (indicates upstream schema change).
    """
    return fetch_gnatsgo_profiles_result(
        mukeys, options=options, settings=settings
    ).profiles


def fetch_gnatsgo_profiles_result(
    mukeys: Iterable[int],
    *,
    options: GnatsgoFetchOptions | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> SoilProfilesResult:
    """Like :func:`fetch_gnatsgo_profiles`, but also returns a structured report."""
    opts = options or GnatsgoFetchOptions()
    mukey_set = _validate_mukeys(mukeys)

    tables = _load_tables(
        mukey_set=mukey_set,
        opts=opts,
        cache_dir=_resolve_cache_dir(opts.cache_dir, settings),
    )

    # Baseline = aggregated profiles (muaggatt-driven).
    profiles_by_mukey: dict[int, SoilProfile] = {}
    aggregated_ok: set[int] = set()
    for mukey in sorted(mukey_set):
        agg = _build_profile_from_muaggatt(mukey=mukey, tables=tables)
        if agg is not None:
            profiles_by_mukey[mukey] = agg
            aggregated_ok.add(mukey)

    # Enhancement = horizon profiles (only when "usable").
    horizon_ok: set[int] = set()
    horizon_rejected: dict[int, str] = {}
    for mukey in sorted(mukey_set):
        hz = _build_profile_from_chorizon(mukey=mukey, tables=tables)
        if hz is None:
            continue
        ok, reason = _is_usable_horizon_profile(hz)
        if ok:
            profiles_by_mukey[mukey] = hz
            horizon_ok.add(mukey)
        else:
            horizon_rejected[mukey] = reason

    profiles = [profiles_by_mukey[m] for m in sorted(profiles_by_mukey)]
    missing = mukey_set - set(profiles_by_mukey)
    if missing:
        # Invariant: every requested mukey yields a SoilProfile.
        # Aggregated profiles are built even when muaggatt is missing by
        # falling back to conservative defaults, so missing indicates a bug.
        raise SwatBuilderPipelineError(
            "Invariant violated: every mukey must yield a SoilProfile",
            missing_mukeys=sorted(missing),
        )

    soil_report: dict[str, Any] = {
        "requested_mukeys": len(mukey_set),
        "profiles_written": len(profiles),
        "coverage_pct": (len(profiles) / len(mukey_set)) if mukey_set else 0.0,
        "horizon": {
            "used": len(horizon_ok),
            "rejected": len(horizon_rejected),
            "criteria": {
                "min_layers": _HZ_MIN_LAYERS,
                "min_depth_mm": _HZ_MIN_DEPTH_MM,
            },
        },
        "aggregated": {
            "used": len(aggregated_ok - horizon_ok),
            "layer_strategy_mm": list(_AGG_LAYER_BREAKS_MM),
            "awc_source": "muaggatt aws* columns (scaled) or default",
        },
        "missing": {"mukeys": 0},
        "sources": {"muaggatt": True, "horizons": bool(horizon_ok)},
    }
    log.info("soil_report=%s", soil_report)

    if missing:
        sample = sorted(missing)[:15]
        log.warning(
            "Soils skipped %d mukeys (no muaggatt row and no usable horizons); "
            "sample: %s%s",
            len(missing),
            sample,
            " …" if len(missing) > 15 else "",
        )
    if horizon_rejected:
        sample_items = list(sorted(horizon_rejected.items()))[:10]
        log.warning(
            "Horizon profiles rejected for %d mukeys (using aggregated instead); "
            "sample: %s%s",
            len(horizon_rejected),
            sample_items,
            " …" if len(horizon_rejected) > 10 else "",
        )

    return SoilProfilesResult(profiles=profiles, soil_report=soil_report)


# ---------------------------------------------------------------------------
# Table loading
# ---------------------------------------------------------------------------


def _load_tables(
    *,
    mukey_set: set[int],
    opts: GnatsgoFetchOptions,
    cache_dir: Path,
) -> dict[str, "pd.DataFrame"]:
    """Query STAC + download + filter the three Parquet tables.

    Kept as a single function so the happy path is easy to follow;
    error translation is centralized here.
    """
    try:
        import pystac_client  # type: ignore[import-untyped]
        import planetary_computer  # type: ignore[import-untyped]
        import pandas as pd
    except ImportError as exc:
        raise SwatBuilderExternalError(
            "gNATSGO fetch requires optional extras. "
            "Install with: pip install 'swatplus-builder[soils]'",
            missing=str(exc),
            extra_install="swatplus-builder[soils]",
        ) from exc

    try:
        catalog = pystac_client.Client.open(
            opts.stac_url, modifier=planetary_computer.sign_inplace
        )
        search = catalog.search(collections=[opts.tables_collection])
        items = {item.id: item for item in search.items()}
    except Exception as exc:
        raise SwatBuilderExternalError(
            f"Planetary Computer STAC query failed: {exc}",
            stac_url=opts.stac_url,
            collection=opts.tables_collection,
        ) from exc

    if not items:
        raise SwatBuilderExternalError(
            f"collection {opts.tables_collection!r} returned zero items",
            stac_url=opts.stac_url,
        )

    tables: dict[str, pd.DataFrame] = {}

    tables["component"] = _read_parquet(
        item_id="component",
        items=items,
        columns=list(_COMPONENT_COLS),
        filter_col="mukey",
        filter_values=mukey_set,
        cache_dir=cache_dir,
    )
    _require_columns("component", tables["component"], _COMPONENT_COLS)

    if tables["component"].empty:
        # Aggregated soils do not require the component/chorizon join.
        # Keep going so callers still get deterministic synthetic profiles.
        log.warning(
            "No gNATSGO components found for requested mukeys; "
            "horizon-based enhancement will be unavailable (n_mukeys=%d, sample=%s)",
            len(mukey_set),
            sorted(mukey_set)[:5],
        )

    cokey_set = set(tables["component"]["cokey"].astype("int64").tolist())
    if cokey_set:
        tables["chorizon"] = _read_parquet(
            item_id="chorizon",
            items=items,
            columns=list(_CHORIZON_COLS),
            filter_col="cokey",
            filter_values=cokey_set,
            cache_dir=cache_dir,
        )
        _require_columns("chorizon", tables["chorizon"], _CHORIZON_COLS)
    else:
        # No components → no cokeys to request.
        tables["chorizon"] = pd.DataFrame(columns=list(_CHORIZON_COLS))

    tables["muaggatt"] = _read_parquet(
        item_id="muaggatt",
        items=items,
        columns=list(_MUAGGATT_COLS + _MUAGGATT_OPTIONAL_COLS),
        filter_col="mukey",
        filter_values=mukey_set,
        cache_dir=cache_dir,
    )
    _require_columns("muaggatt", tables["muaggatt"], _MUAGGATT_COLS)

    return tables


def _filter_parquet_rows(
    df: "pd.DataFrame",
    *,
    filter_col: str,
    filter_values: set[int],
) -> "pd.DataFrame":
    """Keep rows whose ``filter_col`` is in ``filter_values``.

    Coerces with ``to_numeric`` when ``isin`` matches nothing but the
    column is float/string-like — Parquet occasionally widens keys.
    """
    import pandas as pd

    keys = list(filter_values)
    col = df[filter_col]
    mask = col.isin(keys)
    if not bool(mask.any()) and len(df) > 0:
        coerced = pd.to_numeric(col, errors="coerce")
        mask = coerced.isin(keys)
    return df.loc[mask]


def _read_parquet(
    *,
    item_id: str,
    items: Mapping[str, Any],
    columns: list[str],
    filter_col: str,
    filter_values: set[int],
    cache_dir: Path,
):  # type: ignore[no-untyped-def]
    """Read one STAC item's Parquet asset, filtered by a single column.

    Filtering happens **server-side** via ``pyarrow``'s predicate push-
    down if available, falling back to pandas for portability.
    """
    import pandas as pd
    import planetary_computer  # type: ignore[import-untyped]

    if item_id not in items:
        raise SwatBuilderPipelineError(
            f"STAC collection is missing item {item_id!r}",
            available=sorted(items),
        )

    signed_item = planetary_computer.sign(items[item_id])
    if "data" not in signed_item.assets:
        raise SwatBuilderPipelineError(
            f"item {item_id!r} is missing its 'data' asset",
            assets=sorted(signed_item.assets),
        )
    asset = signed_item.assets["data"]
    storage_options = asset.extra_fields.get("table:storage_options", {})
    href = asset.href

    # Planetary Computer STAC points gNATSGO tables at ``abfs://…`` blobs with
    # credentials in ``table:storage_options`` (same pattern as
    # ``pipeline/04_get_soil.py``). PyArrow ``Dataset`` with ``filesystem=None``
    # cannot apply those options to Azure; it may error or return zero rows.
    # Pandas + fsspec/adlfs is the supported read path for PC Parquet.
    if href.startswith("abfs://") or storage_options:
        df = pd.read_parquet(href, columns=columns, storage_options=storage_options)
        df = _filter_parquet_rows(df, filter_col=filter_col, filter_values=filter_values)
    else:
        try:
            import pyarrow.parquet as pq
            import pyarrow.dataset as ds

            dataset = ds.dataset(href, filesystem=None, format="parquet")
            filter_expr = ds.field(filter_col).isin(sorted(filter_values))
            df = dataset.to_table(columns=columns, filter=filter_expr).to_pandas()
            _ = pq  # silence flake if pyarrow.parquet is unused below
        except Exception as exc:
            log.debug("pyarrow dataset read failed (%s); using pandas", exc)
            df = pd.read_parquet(href, columns=columns, storage_options=storage_options)
            df = _filter_parquet_rows(df, filter_col=filter_col, filter_values=filter_values)

    # Cache to disk for debugging / reproducibility.
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_dir / f"{item_id}_filtered.parquet")
    except Exception:
        # Cache write is best-effort. Sandboxes / read-only FS must not
        # break the fetch.
        pass

    return df


def _require_columns(
    table: str, df: "pd.DataFrame", required: tuple[str, ...]
) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SwatBuilderPipelineError(
            f"gNATSGO table {table!r} is missing columns {missing}; "
            "Microsoft may have changed the schema",
            table=table,
            missing=missing,
            available=list(df.columns),
        )


# ---------------------------------------------------------------------------
# Profile assembly
# ---------------------------------------------------------------------------


def _build_profile(
    *, mukey: int, tables: Mapping[str, "pd.DataFrame"]
) -> SoilProfile | None:
    """Return the :class:`SoilProfile` for one mukey, or ``None`` if
    the map unit has no usable horizon data."""
    import pandas as pd

    components = tables["component"]
    mu_components = components[components["mukey"].astype("int64") == mukey]
    if mu_components.empty:
        return None

    # Pick the majority component by ``comppct_r``; ties break on
    # lowest ``cokey`` for determinism.
    dominant = (
        mu_components.sort_values(
            ["comppct_r", "cokey"], ascending=[False, True]
        ).iloc[0]
    )
    cokey = int(dominant["cokey"])
    compname = str(dominant.get("compname", f"mukey_{mukey}") or f"mukey_{mukey}")

    chorizons = tables["chorizon"]
    horizons = chorizons[chorizons["cokey"].astype("int64") == cokey]
    if horizons.empty:
        return None
    horizons = horizons.sort_values("hzdept_r")

    layers = []
    for layer_num, row in enumerate(horizons.itertuples(index=False), start=1):
        # Skip horizons with no physical data — SSURGO sometimes ships a
        # "bedrock" placeholder row with all NULLs.
        if _is_placeholder_horizon(row):
            continue
        try:
            layer = horizon_from_chorizon(
                layer_num=layer_num,
                hzdepb_cm=_f(row.hzdepb_r, default=100.0),
                sandtotal_r=_f(row.sandtotal_r, default=33.3),
                silttotal_r=_f(row.silttotal_r, default=33.3),
                claytotal_r=_f(row.claytotal_r, default=33.4),
                ksat_umps=_f(row.ksat_r, default=10.0),
                dbthirdbar=_f(row.dbthirdbar_r, default=1.4),
                wthirdbar_pct=_f(row.wthirdbar_r, default=30.0),
                wfifteenbar_pct=_f(row.wfifteenbar_r, default=15.0),
                om_r=_f(row.om_r, default=1.0),
            )
        except Exception as exc:
            # Single bad horizon should not kill the whole profile;
            # log (in future — we don't have a logger wired yet) and
            # skip. Failing harder would mean one bad SSURGO row kills
            # HRUs elsewhere in the watershed.
            _ = exc
            continue
        layers.append(layer)

    if not layers:
        return None

    # Re-number after placeholder skips so layer_num stays 1..N contiguous.
    for i, layer in enumerate(layers, start=1):
        if layer.layer_num != i:
            layers[i - 1] = layer.model_copy(update={"layer_num": i})

    hydgrp = _resolve_hyd_group(mukey=mukey, tables=tables)

    return SoilProfile(
        name=f"gnatsgo_{mukey}",
        hyd_grp=hydgrp,
        texture=None,
        description=f"gNATSGO mukey={mukey} compname={compname} cokey={cokey}",
        layers=layers,
    )

def _build_profile_from_chorizon(
    *, mukey: int, tables: Mapping[str, "pd.DataFrame"]
) -> SoilProfile | None:
    # Back-compat alias for readability at the call site.
    return _build_profile(mukey=mukey, tables=tables)


def _build_profile_from_muaggatt(
    *, mukey: int, tables: Mapping[str, "pd.DataFrame"]
) -> SoilProfile | None:
    """Baseline soil builder: stable, aggregated, reproducible.

    Synthesizes 2–3 layers using muaggatt cumulative AWS and bedrock depth.
    Does NOT depend on full horizon (chorizon) coverage.
    """
    muaggatt = tables["muaggatt"]
    match = muaggatt[muaggatt["mukey"].astype("int64") == mukey]
    row = match.iloc[0] if not match.empty else None

    hydgrp = (
        collapse_dual_hyd_group(
            str(row.get("hydgrpdcd")) if row is not None and row.get("hydgrpdcd") is not None else None
        )
        if row is not None
        else "D"
    )

    # Total depth (mm): bedrock depth is cm in muaggatt.
    dp_tot_cm = _num(row.get("brockdepmin"), default=150.0) if row is not None else 150.0
    dp_tot_cm = max(30.0, min(250.0, dp_tot_cm))
    dp_tot_mm = dp_tot_cm * 10.0

    # Fixed layer strategy (consistency > "precision").
    breaks_mm: list[float] = []
    for b in _AGG_LAYER_BREAKS_MM:
        if b < dp_tot_mm:
            breaks_mm.append(float(b))
    breaks_mm.append(float(dp_tot_mm))
    # Ensure at least 2 layers.
    if len(breaks_mm) < _AGG_MIN_LAYERS:
        first = min(_AGG_LAYER_BREAKS_MM[0], dp_tot_mm)
        breaks_mm = [float(first), float(dp_tot_mm)]

    # Cumulative AWS (cm water) to standard depths (cm soil).
    aws_25 = _num(row.get("aws025wta"), default=None) if row is not None else None
    aws_50 = _num(row.get("aws050wta"), default=None) if row is not None else None
    aws_100 = _num(row.get("aws0100wta"), default=None) if row is not None else None
    aws_150 = _num(row.get("aws0150wta"), default=None) if row is not None else None

    def cum_aws(depth_cm: float) -> float | None:
        if depth_cm <= 25 and aws_25 is not None:
            return aws_25
        if depth_cm <= 50 and aws_50 is not None:
            return aws_50
        if depth_cm <= 100 and aws_100 is not None:
            return aws_100
        if depth_cm <= 150 and aws_150 is not None:
            return aws_150
        return None

    def awc_for_segment(top_cm: float, bot_cm: float) -> float:
        thickness_cm = max(1e-6, bot_cm - top_cm)
        c_top = cum_aws(top_cm) or 0.0
        c_bot = cum_aws(bot_cm)
        if c_bot is None:
            # Scale the nearest known cumulative AWS to our target depth.
            for depth, val in ((150.0, aws_150), (100.0, aws_100), (50.0, aws_50), (25.0, aws_25)):
                if val is not None:
                    c_bot = float(val) * (bot_cm / depth)
                    break
        if c_bot is None:
            return 0.15  # conservative default AWC fraction
        seg_cm_water = max(0.0, float(c_bot) - float(c_top))
        awc = seg_cm_water / thickness_cm
        return max(0.01, min(0.35, awc))

    # Conservative mineral-soil defaults for texture/OC/BD.
    bd = 1.4
    # Use OM (not OC) as horizon_from_chorizon expects om_r.
    om_r = 1.0
    sand, silt, clay = 40.0, 40.0, 20.0

    # Representative conductivity by HSG (mm/hour), converted to SSURGO units (µm/s).
    ksat_mmph = _ksat_mmph_for_hydgrp(hydgrp)
    ksat_umps = ksat_mmph / 3.6

    layers = []
    top_cm = 0.0
    for layer_num, bot_mm in enumerate(breaks_mm, start=1):
        bot_cm = bot_mm / 10.0
        awc = awc_for_segment(top_cm, bot_cm)
        # Encode AWC via (FC - WP); keep FC anchored, adjust WP.
        wthird = 30.0
        wfifteen = max(0.0, wthird - awc * 100.0)
        layers.append(
            horizon_from_chorizon(
                layer_num=layer_num,
                hzdepb_cm=bot_cm,
                sandtotal_r=sand,
                silttotal_r=silt,
                claytotal_r=clay,
                ksat_umps=ksat_umps,
                dbthirdbar=bd,
                wthirdbar_pct=wthird,
                wfifteenbar_pct=wfifteen,
                om_r=om_r,
            )
        )
        top_cm = bot_cm

    return SoilProfile(
        name=f"gnatsgo_{mukey}",
        hyd_grp=hydgrp,
        texture=None,
        description=(
            f"synthetic {'muaggatt' if row is not None else 'defaults'} "
            f"mukey={mukey} dp_tot_cm={dp_tot_cm:.0f}"
        ),
        layers=layers,
    )


def _is_usable_horizon_profile(profile: SoilProfile) -> tuple[bool, str]:
    """Gate "horizon enhancement" profiles so half-broken horizons don't leak in."""
    if len(profile.layers) < _HZ_MIN_LAYERS:
        return (False, f"layers<{_HZ_MIN_LAYERS}")
    depth_mm = max((lyr.dp for lyr in profile.layers), default=0.0)
    if depth_mm < _HZ_MIN_DEPTH_MM:
        return (False, f"depth_mm<{_HZ_MIN_DEPTH_MM:g}")
    return (True, "ok")


def _resolve_hyd_group(*, mukey: int, tables: Mapping[str, "pd.DataFrame"]) -> str:
    muaggatt = tables["muaggatt"]
    match = muaggatt[muaggatt["mukey"].astype("int64") == mukey]
    if not match.empty:
        code = match.iloc[0].get("hydgrpdcd")
        return collapse_dual_hyd_group(str(code) if code is not None else None)
    return "D"


def _is_placeholder_horizon(row: Any) -> bool:
    """Flag horizons we cannot convert — all NULLs for key properties."""
    for name in ("sandtotal_r", "claytotal_r", "ksat_r", "dbthirdbar_r"):
        v = getattr(row, name, None)
        if v is not None and not _is_nan(v):
            return False
    return True


def _is_nan(x: Any) -> bool:
    try:
        return x != x  # only NaN != NaN in IEEE-754
    except Exception:
        return False


def _f(value: Any, *, default: float) -> float:
    if value is None or _is_nan(value):
        return default
    return float(value)

def _num(value: Any, *, default: float | None) -> float | None:
    if value is None or _is_nan(value):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _ksat_mmph_for_hydgrp(hydgrp: str) -> float:
    # Very rough representative conductivity by HSG (A fast → D slow).
    return {"A": 50.0, "B": 20.0, "C": 8.0, "D": 2.0}.get(hydgrp.upper(), 2.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_mukeys(mukeys: Iterable[int]) -> set[int]:
    out: set[int] = set()
    for m in mukeys:
        if not isinstance(m, int) or isinstance(m, bool):
            raise SwatBuilderInputError(
                f"mukey must be int, got {type(m).__name__}: {m!r}",
                mukey=repr(m),
            )
        if m < 0:
            raise SwatBuilderInputError(
                f"mukey cannot be negative: {m}", mukey=m
            )
        out.add(int(m))
    if not out:
        raise SwatBuilderInputError(
            "fetch_gnatsgo_profiles() needs at least one mukey",
            mukeys=[],
        )
    return out


def _resolve_cache_dir(cache_dir: Path | None, settings: Settings) -> Path:
    if cache_dir is not None:
        return Path(cache_dir).expanduser().resolve()
    root = Path(settings.reference_db_dir).expanduser().resolve().parent
    return root / "gnatsgo_cache"
