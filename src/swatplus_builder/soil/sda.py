from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import requests

from swatplus_builder.soil.models import SoilProfile, SoilConfig
from swatplus_builder.soil.params import horizon_from_chorizon, collapse_dual_hyd_group

log = logging.getLogger(__name__)

CACHE_VERSION = "sda_v1"

def _num(val: str | None, default: float) -> float:
    try:
        return float(val) if val is not None and val != '' else default
    except (ValueError, TypeError):
        return default

def fetch_sda_horizons(mukeys: List[int], config: SoilConfig, cache_dir: Path | None = None) -> dict[int, SoilProfile]:
    """Fetch rigorous soil horizons via USDA Soil Data Access API."""
    if not mukeys:
        return {}

    url = "https://sdmdataaccess.nrcs.usda.gov/Tabular/post.rest"

    cache_path = (cache_dir / "sda_cache.json") if cache_dir and config.enable_cache else None
    cache = {}
    
    if cache_path and cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                raw_cache = json.load(f)
                # Cache version validation
                if isinstance(raw_cache, dict) and raw_cache.get("_version") == CACHE_VERSION:
                    cache = raw_cache.get("data", {})
                else:
                    log.info("SDA Cache version mismatch or corrupt, ignoring old cache.")
        except Exception as e:
            log.warning(f"Failed to read SDA cache: {e}")

    uncached_mukeys = [m for m in mukeys if str(m) not in cache]
    
    # Reproducible mode enforces cache ONLY
    if config.reproducible:
        uncached_mukeys = []
        log.info("SoilConfig.reproducible is True; bypassing all live SDA fetches.")

    if uncached_mukeys:
        max_b = config.max_sda_mukeys
        batches = [uncached_mukeys[i:i + max_b] for i in range(0, len(uncached_mukeys), max_b)]
        
        session = requests.Session()
        
        # Rate limit: 30 requests per minute -> 2 seconds per request baseline
        min_interval_seconds = 2.0 
        
        for batch in batches:
            in_clause = ",".join(f"'{m}'" for m in batch)
            
            # Removed majcompflag requirement, rely on max(comppct_r) via ORDER BY
            query = f"""
            SELECT c.mukey, c.cokey, c.compname, c.hydgrp, c.comppct_r, c.majcompflag,
                   h.hzname, h.hzdept_r, h.hzdepb_r,
                   h.sandtotal_r, h.silttotal_r, h.claytotal_r,
                   h.ksat_r, h.om_r, h.dbthirdbar_r, h.wthirdbar_r, h.wfifteenbar_r
            FROM component c
            INNER JOIN chorizon h ON c.cokey = h.cokey
            WHERE c.mukey IN ({in_clause})
            ORDER BY c.mukey, c.comppct_r DESC, h.hzdept_r ASC
            """
            
            payload = {'query': query, 'format': 'JSON'}
            
            max_retries = 3
            base_delay = 2.0
            sleep_time = base_delay
            
            time.sleep(min_interval_seconds)
            
            for attempt in range(max_retries):
                try:
                    resp = session.post(url, data=payload, timeout=30.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        if 'Table' in data:
                            current_batch_rows = {}
                            for row in data['Table']:
                                mk = str(row[0])
                                if mk not in current_batch_rows:
                                    current_batch_rows[mk] = []
                                current_batch_rows[mk].append(row)
                                
                            for m in batch:
                                mk = str(m)
                                if mk in current_batch_rows:
                                    cache[mk] = current_batch_rows[mk]
                                else:
                                    cache[mk] = [] # Cache empty array so we don't refetch missing mukeys
                        break
                    else:
                        log.warning(f"SDA returned {resp.status_code}. Attempt {attempt+1}/{max_retries}.")
                except Exception as e:
                    log.warning(f"SDA request error: {e}. Attempt {attempt+1}/{max_retries}.")
                
                # Exponential backoff
                time.sleep(sleep_time)
                sleep_time *= 2

        if cache_path:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                full_payload = {
                    "_version": CACHE_VERSION,
                    "_updated": datetime.now(timezone.utc).isoformat(),
                    "data": cache
                }
                with open(cache_path, "w") as f:
                    json.dump(full_payload, f)
            except Exception as e:
                log.warning(f"Failed to write SDA cache: {e}")

    profiles = {}
    for mukey in mukeys:
        mk_str = str(mukey)
        if mk_str not in cache or not cache[mk_str]:
            continue
            
        rows = cache[mk_str]
        
        # highest pct via ORDER BY
        target_cokey = rows[0][1]
        compname = rows[0][2]
        hydgrp = collapse_dual_hyd_group(rows[0][3] if rows[0][3] else "D")
        
        hz_rows = [r for r in rows if r[1] == target_cokey]
        
        layers = []
        layer_idx = 1
        for r in hz_rows:
            # unpacked 17 args from query above
            _, _, _, _, _, _, _, _, depb, sand, silt, clay, ksat, om, bd, w3, w15 = r
            
            if depb is None or depb == '':
                continue
                
            try:
                wb_val = _num(w3, 30.0)
                w15_val = _num(w15, 15.0)
                if abs(wb_val - w15_val) < 0.001:
                    w15_val = max(0.0, wb_val - 15.0)
                    
                layers.append(horizon_from_chorizon(
                    layer_num=layer_idx, hzdepb_cm=_num(depb, 100.0),
                    sandtotal_r=_num(sand, 33.3), silttotal_r=_num(silt, 33.3), claytotal_r=_num(clay, 33.4),
                    ksat_umps=_num(ksat, 10.0), dbthirdbar=_num(bd, 1.4),
                    wthirdbar_pct=wb_val, wfifteenbar_pct=w15_val, om_r=_num(om, 1.0)
                ))
                layer_idx += 1
            except Exception:
                pass
                
        if layers:
            profiles[mukey] = SoilProfile(
                name=f"gnatsgo_{mukey}", 
                hyd_grp=hydgrp,
                texture=None,
                description=f"SDA horizon mukey={mukey} cokey={target_cokey} compname={compname}",
                source="sda_horizon",
                layers=layers
            )

    return profiles
