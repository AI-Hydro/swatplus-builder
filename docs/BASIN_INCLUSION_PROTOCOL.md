# Basin inclusion protocol (SWAT-S1 decision-data reference pool)

Status: **v1, first draft — read the "What this does NOT do" section before
treating its output as a trusted reference set.**

This addresses the readiness review's P0 findings
(`../Swatplus_decision/research/BUILDER_READINESS.md`, 2026-09-23):

> Recruit independent basins under a published inclusion protocol; retain
> all build failures and exclusion reasons. Qualify reference basins using
> discharge and independent process evidence.
>
> Introduce separate fitting, decision-development and untouched final
> assessment periods, plus basin-group isolation.

Before this document, basin choice for this project was ad hoc: `02177000`
and `03339000` were picked because they were convenient (03339000 is
already the CI routing-regression basin — see `basins/curated_v1.json` —
and both are now "familiar development material" in the readiness review's
own sense, having been run repeatedly while building and testing this
pipeline). Neither is an independent reference basin. This protocol exists
so the *next* basin list is chosen by a documented, reproducible rule
instead of by convenience, and so every excluded candidate's reason is
recorded rather than silently dropped.

## 1. Candidate universe and data source

Candidates come from the USGS NWIS site service (queried live, per state,
via `pygeohydro.NWIS.get_info` — already a pinned dependency under the
`hyriver` extra, not a new one added for this). This is the same USGS
service this project already depends on for observed discharge
(`output/mass_trace.py`), so it introduces no new trust boundary.

Restricted to the conterminous United States (CONUS) + DC: this pipeline's
forcing/soil/terrain providers (GridMET, gNATSGO via Planetary Computer,
3DEP) are CONUS-only, so AK/HI/PR/territories are out of scope regardless
of gauge quality.

## 2. Hard inclusion filters (checked against live NWIS metadata, not assumed)

A candidate site must satisfy **all** of:

1. `site_tp_cd == "ST"` — a stream site (excludes lakes, springs, estuaries,
   wells, etc.).
2. Has a daily-discharge series (`parm_cd == "00060"`, `data_type_cd ==
   "dv"`) whose advertised period of record fully covers the requested
   window: `begin_date <= window_start` and `end_date >= window_end`.
3. `drain_area_va` (USGS's own field, **in square miles** — the
   long-standing NWIS RDB convention, converted to km² in the output but
   kept in its original unit too) falls within `[--min-drainage-mi2,
   --max-drainage-mi2]`. Defaults (207–1290 mi², i.e. the drainage areas of
   the two basins already run successfully through this pipeline, `02177000`
   and `03339000`) bracket the pipeline's only two proven-working runs with
   margin (`--min-drainage-mi2 50 --max-drainage-mi2 3000` is the actual
   default). **This is not a formal capacity study** — it is a pragmatic,
   disclosed starting bound, adjustable per basin via CLI flags, and it
   should be revisited once more basins have actually been run.
4. Not already used anywhere in this repository's development or testing
   history (see §4).

## 3. Reference-quality tag (recorded, not filtered on)

NWIS's expanded site info carries an `hcdn_2009` flag: USGS's own
Hydro-Climatic Data Network 2009 designation for gauges with minimal
anthropogenic disturbance to streamflow — a citable, third-party
"independent process evidence" signal, not something this project invents.
It is recorded per candidate but is **not** a hard filter: HCDN-2009 basins
are a small minority of active USGS gauges, and a decision model that will
eventually see real, often-regulated basins in production needs some
non-reference basins in its training data too. A caller who wants a
strict, minimally-disturbed-only subset can filter the output on
`hcdn_2009 == true` themselves; the protocol just makes that distinction
visible instead of erasing it.

## 4. Contamination exclusion (computed, not hand-maintained)

Every USGS ID that appears anywhere in this repository's own development
or testing history is excluded from the candidate pool, because a basin
this project has already used to build, debug, or test itself cannot serve
as *independent* evidence. `scripts/basin_inclusion_protocol.py` computes
this set automatically by scanning:

- `basins/curated_v1.json` (the existing structural/CI-regression basin
  list — a different, deliberately reused set for a different purpose;
  never treat it as an independent reference pool).
- Every `--usgs-id` / `"usgs_id"` literal in `tests/**/*.py`,
  `scripts/**/*.py` and `scripts/**/*.json`.
- Every `usgs_<id>` run-directory name already materialized under `runs/`.

This is a best-effort textual scan, not a formal audit — it will not catch
a USGS ID mentioned only in prose (a paragraph in a doc, say) without the
`usgs_id`/`usgs_<id>` patterns it looks for. Treat its exclusion list as a
floor, not a ceiling: a human should still sanity-check the final pool
before treating it as clean, especially before publishing anything built
from it.

## 5. Basin-group split: development vs. held-out final assessment

The readiness review's other P0 item — a period/basin-group split so the
same basins aren't used to both develop and finally assess the decision
model — is handled at the **basin** level, decided once, before any of
these basins are ever run:

Each surviving candidate's USGS ID is deterministically hashed (SHA-256,
same mechanism as `decision_data/typed.py::assign_split`'s train/validation/
test split, but with its own distinct salt — `swat-s1-basin-inclusion-v1`
by default — so this split is independent of, and does not leak into, the
per-episode train/validation/test split) into one of:

- `development` (default 50%): may be run repeatedly while iterating on the
  pipeline, the fault catalogue, or the decision model itself.
- `held_out_final_assessment` (default 50%): **must not be run, inspected,
  or have its results looked at until the pipeline and decision model are
  frozen.** This is a process discipline, not something this script can
  enforce by itself — nothing stops an agent or person from running a
  held-out basin anyway. Treat a held-out basin that has already been run
  as contaminated and move it back into the excluded set with that reason
  recorded, the same way §4 already does for prior-development basins.

## 6. Output

`scripts/basin_inclusion_protocol.py --out <path>` (default
`basins/reference_pool_v1.json`) writes one JSON document:

```json
{
  "schema": "swatplus_builder.basin_inclusion_pool/v1",
  "generated_utc": "...",
  "generator": {"script": "scripts/basin_inclusion_protocol.py", "states_queried": [...], "window": ["2000-01-01", "2019-12-31"], "filters": {...}},
  "included": [
    {"usgs_id": "...", "station_nm": "...", "state_cd": "...",
     "drain_area_mi2": ..., "drain_area_km2": ..., "hcdn_2009": true/false,
     "begin_date": "...", "end_date": "...", "group": "development"|"held_out_final_assessment"}
  ],
  "excluded": [
    {"usgs_id": "...", "reason": "not_stream_type"|"insufficient_period_of_record"|"drainage_area_out_of_bounds"|"contaminated_prior_use:<source>", "detail": "..."}
  ]
}
```

Every excluded candidate is retained with a reason (readiness review P0),
not just dropped silently.

## 7. What this protocol does NOT do (v1 gaps, disclosed)

- **No spatial-independence check.** A downstream gauge's drainage area can
  fully contain an upstream gauge already in the pool (nested basins). Not
  detected in v1.
- **No stratified climate/ecoregion coverage.** Filtering is criteria-based,
  not sampled for diversity across climate zones or physiographic regions.
- **No enforcement of the held-out group's "untouched" rule.** §5 is a
  documented process convention; nothing in this repository currently
  checks it automatically.
- **Reference quality beyond HCDN-2009 is not verified.** Most included
  basins will not be HCDN-2009 (regulation, diversion, or land-use change
  may affect them); this is disclosed, not hidden, by keeping the flag
  visible per basin instead of filtering on it.
- **Period-of-record coverage is a metadata check, not a gap-free
  guarantee.** `begin_date`/`end_date` covering the window does not mean
  every day in between has data — actual daily-value gaps are the existing
  pipeline's problem to handle at run time (GridMET/obs alignment), not
  this protocol's.

This is deliberately a v1: it replaces "picked by convenience" with a
documented, reproducible, inspectable rule, not a finished research design.

## 8. Empirical follow-up (2026-09-29): period-of-record coverage is not sufficient

A first live 4-basin sample from the `development` group (02363000,
07169800, 04077400, 01197000) found 2/4 hit a real build blocker despite
passing every filter in §2:

- `01197000`: `weather_provider_data_gap` — GridMET returned a station
  reading with minimum temperature not below maximum temperature
  (`s42422n73121w`), correctly rejected by the existing weather-fidelity
  gate rather than silently used.
- `04077400`: `full_model_build_failed` — "Discharge is not available for
  the requested query," despite this basin's NWIS site metadata advertising
  period-of-record coverage for the full requested window.

Both are the existing pipeline's governance working as intended (rejecting
bad or missing data rather than silently proceeding) — this is not a
failure of that governance. It is a limitation of §2's inclusion filters:
NWIS site-level period-of-record metadata (`begin_date`/`end_date` on the
site) does not guarantee the actual discharge query returns usable data for
every day in that window, and provider-side data-quality problems (GridMET
station artifacts) aren't visible at the metadata-screening stage at all.
`scripts/decision_data_batch.py` handles this correctly — such a basin is
still `status="ok"` (ledger verified, decisions exported) but
`workflow_success=False`, and contributes 0 calibration-phase
counterfactuals, only a couple of contract/claim-tier decisions. Anyone
consuming a batch's output must check `workflow_success` per basin, not
just admission status. See `scripts/decision_data_batch.py`'s
`BasinResult.workflow_success` docstring.

## 9. Contamination audit and pool v1.1 (2026-09-29)

The §4 scan was a floor, and it proved too low. A wider audit
(`scripts/audit_reference_pool.py`) searched docs, markdown notes, the
manuscript repository, the decision-model workspace, and run trees outside
the repository (`~/swatplus_runs`). It found six pool gauges that had been
used before the pool was generated. Each was dated from git history or file
metadata:

| Gauge | v1 group | Prior use |
|---|---|---|
| 03349000 | held-out | manuscript focused negative control (git since 2026-05-05) |
| 01435000 | held-out | screened as a positive-control candidate (local doc, 2026-06-12) |
| 03443000 | held-out | screened as a positive-control candidate (local doc, 2026-06-12) |
| 01031500 | development | development use (git since 2026-06-14) |
| 12031000 | development | development use (git since 2026-05-12) |
| 13185000 | development | soil-fallback development runs (git since 2026-05-05) |

`basins/reference_pool_v1_1.json` removes exactly these six and records the
evidence for each (4,061 gauges: 2,012 development, 2,049 held-out). Group
assignment is a per-gauge hash, so no other gauge changes group.
`basin_inclusion_protocol.py` now also scans docs, top-level markdown, and
manuscript materials.

Effect on PE1: none. None of the six was among the 13 candidates PE1
checked, and every PE1 basin appears only in PE1's own artifacts
(`basins/reference_pool_v1_audit.json`). Future selections should use v1.1.
The v1 held-out group contained three used gauges, so v1 should not be used
as a clean final-assessment set.
