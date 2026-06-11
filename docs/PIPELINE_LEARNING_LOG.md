# Pipeline Learning Log

Status: living log
Date: 2026-05-12

| Basin | Symptom | Root cause | Pipeline improvement | Evidence path | Generalized? |
|---|---|---|---|---|---|
| checkout-wide | `swat workflow` documented but unavailable | CLI did not register workflow sub-app | Restored `swat workflow negotiate/run` and added `--model-family` | `tests/test_cli_workflow.py` | yes |
| checkout-wide | CN2 bridge test failed | CN2 writer modified all `cntable.lum` rows, including non-wood land uses | CN2 bridge now edits only `wood_*` rows; registry target file corrected to `cntable.lum` | `tests/test_parameter_bridge.py` | yes |
| checkout-wide | Full-mode bridge and registry disagreed | `PERCO`, `LATQ_CO`, `PET_CO`, `RCHG_DP` existed in bridge but not registry | Added missing registry entries and documented claim-tier rules | `docs/CALIBRATION_PARAMETER_REGISTRY.md` | yes |
| checkout-wide | Agents had to infer workflow state from missing files or nested reports | Canonical workflow did not expose a stable top-level evidence contract | Every workflow run now writes `calibration_provenance.json`, `parameter_screen.json`, `run_manifest.json`, `events.jsonl`, plus explicit allowed/blocked claims | `tests/test_workflow_usgs_e2e.py` | yes |
| 03351500 | Repeated Planetary Computer STAC timeout while fetching gNATSGO mukey raster | Provider `/search` path was unavailable/too slow for the basin bbox; blind reruns wasted time | Researched alternatives: bounded PySTAC search, smaller page limit, explicit client timeout, GeoParquet item index, direct state item lookup, USDA SDA spatial query. Implemented bounded STAC search plus USDA SDA spatial mukey fallback with degraded provenance. | `tests/test_gis_soil.py`, `tests/test_soil_sda.py`, `demo_runs/post_hardening_03351500_network/evidence_summary.json` | yes |
