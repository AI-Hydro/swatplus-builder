from __future__ import annotations

import copy
import logging
from collections.abc import Iterable

from swatplus_builder.config import DEFAULT_SETTINGS, Settings
from swatplus_builder.soil.models import SoilConfig, SoilProfile, SoilProfilesResult
from swatplus_builder.soil.pc import fetch_aggregated_profiles
from swatplus_builder.soil.sda import fetch_sda_horizons

log = logging.getLogger(__name__)

SDA_MIN_LAYERS = 2
SDA_MIN_DEPTH_MM = 500.0
MAX_PROFILE_DEPTH_MM = 2500.0

def normalize_profile(profile: SoilProfile, max_depth_mm: float = MAX_PROFILE_DEPTH_MM) -> SoilProfile:
    """Enforce sanity bounds on any profile before delivering to SWAT+.

    SSURGO/gNATSGO and the aggregate fallback can contain zero-thickness
    horizons or duplicate bottom depths, especially shallow profiles with
    bedrock at the first aggregate break. Those rows carry no additional
    SWAT+ layer volume, so drop them upstream while keeping the writer's
    strict monotonicity gate intact.
    """
    normalized_layers = []
    last_dp = 0.0
    layer_num = 1
    for layer in sorted(profile.layers, key=lambda lyr: lyr.dp):
        new_layer = layer.model_copy(deep=True) if hasattr(layer, 'model_copy') else copy.deepcopy(layer)

        if new_layer.dp > max_depth_mm:
            new_layer.dp = max_depth_mm
            if new_layer.dp > last_dp:
                new_layer.layer_num = layer_num
                normalized_layers.append(new_layer)
            break

        if new_layer.dp <= last_dp:
            continue

        new_layer.layer_num = layer_num
        normalized_layers.append(new_layer)
        last_dp = new_layer.dp
        layer_num += 1

    prof_copy = profile.model_copy(deep=True) if hasattr(profile, 'model_copy') else copy.deepcopy(profile)
    if normalized_layers:
        prof_copy.layers = normalized_layers
    return prof_copy

def fetch_soil_profiles_result(
    mukeys: Iterable[int], 
    config: SoilConfig | None = None,
    settings: Settings = DEFAULT_SETTINGS
) -> SoilProfilesResult:
    """End-to-End Orchestrator for 2-tier hybrid soil profiles."""
    mukey_list = sorted(list(set(mukeys)))
    config = config or SoilConfig()
    
    # Tier 1: Generate guaranteed fallback profiles
    baseline_profiles = fetch_aggregated_profiles(mukey_list, settings=settings)
    
    final_profiles = {}
    aggregated_pc_count = 0
    aggregated_default_count = 0
    horizon_used = 0
    horizon_rejected = 0

    for mk in mukey_list:
        p = baseline_profiles.get(mk)
        if p:
            final_profiles[mk] = p
            if p.source == "pc_muaggatt":
                aggregated_pc_count += 1
            else:
                aggregated_default_count += 1
        else:
            # Fallback if pc fails entirely
            from swatplus_builder.soil.params import horizon_from_chorizon
            layers = [
                horizon_from_chorizon(layer_num=1, hzdepb_cm=30.0, sandtotal_r=40.0, silttotal_r=40.0, claytotal_r=20.0, ksat_umps=5.0, dbthirdbar=1.4, wthirdbar_pct=30.0, wfifteenbar_pct=15.0, om_r=1.0),
                horizon_from_chorizon(layer_num=2, hzdepb_cm=100.0, sandtotal_r=40.0, silttotal_r=40.0, claytotal_r=20.0, ksat_umps=5.0, dbthirdbar=1.4, wthirdbar_pct=30.0, wfifteenbar_pct=15.0, om_r=1.0)
            ]
            final_profiles[mk] = SoilProfile(
                name=f"gnatsgo_{mk}", hyd_grp="D",
                description="emergency fallback tier 1",
                source="synthetic_default", layers=layers
            )
            aggregated_default_count += 1

    sda_attempted = 0
    sda_profiles = {}
    
    if config.use_sda and mukey_list:
        cache_dir = settings.reference_db_dir.parent / "gnatsgo_cache"
        sda_attempted = len(mukey_list)
        sda_profiles = fetch_sda_horizons(mukey_list, config, cache_dir)
        
    for mk in mukey_list:
        sda_p = sda_profiles.get(mk)
        if sda_p:
            sda_p = normalize_profile(sda_p)
            # Validate SDA
            layers_count = len(sda_p.layers)
            max_depth = max(lyr.dp for lyr in sda_p.layers)
            
            if layers_count >= SDA_MIN_LAYERS and max_depth >= SDA_MIN_DEPTH_MM:
                old_source = final_profiles[mk].source
                if old_source == "pc_muaggatt":
                    aggregated_pc_count -= 1
                else:
                    aggregated_default_count -= 1
                    
                final_profiles[mk] = sda_p
                horizon_used += 1
            else:
                horizon_rejected += 1

    sda_success = horizon_used
    sda_failed = sda_attempted - sda_success if sda_attempted > 0 else 0

    profiles_list = [normalize_profile(final_profiles[m]) for m in mukey_list]

    soil_report = {
        "requested_mukeys": len(mukey_list),
        "profiles_written": len(profiles_list),
        "coverage_pct": 1.0, 
        "horizon": {
            "used": horizon_used,
            "rejected": horizon_rejected
        },
        "aggregated": {
            "muaggatt_based": aggregated_pc_count,
            "default_fallback": aggregated_default_count
        },
        "sda_attempted": sda_attempted,
        "sda_success": sda_success,
        "sda_failed": sda_failed,
        "sources": {
            "pc": True,
            "sda": config.use_sda
        }
    }
    
    stats = {
        "soil_coverage_pct": 1.0,
        "soil_horizon_profiles": float(horizon_used),
        "soil_aggregated_profiles": float(aggregated_pc_count + aggregated_default_count),
        "soil_missing_mukeys": 0.0
    }

    return SoilProfilesResult(
        profiles=profiles_list, 
        soil_report=soil_report, 
        stats=stats
    )
