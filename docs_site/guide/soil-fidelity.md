# Soil fidelity

Soils are a frequent silent source of overclaiming: a model built on
placeholder soils can produce a perfectly reasonable-looking hydrograph.
swatplus-builder makes soil realism an explicit, recorded property — and it
**lowers the claim ceiling** when soils are not real.

## Soil modes

Every run persists soil realism metadata in `metadata.json`:

| Field | Meaning |
|---|---|
| `soil_mode` | `high_fidelity` · `fallback` · `synthetic` |
| `pct_fallback_soils` | fraction of basin polygons using fallback profiles |

- **high_fidelity** — gNATSGO profiles resolved for the basin polygons.
- **fallback** — minimal/hybrid soil profiles used where detailed soils were
  unavailable; keeps the run structurally executable.
- **synthetic** — placeholder soils; the run executes but the soil basis is not
  real.

## Provenance-or-degrade

This is invariant 5 in action: a fallback does not crash the run, but it
**caps** what can be claimed. The soil-fidelity gate feeds claim governance, so
a high NSE on synthetic soils cannot be promoted to a skill claim.

## Warnings and thresholds

Fallback usage above **25%** emits a warning. The threshold is configurable:

```bash
export SWATPLUS_SOIL_FALLBACK_WARN_THRESHOLD=0.10   # warn above 10%
```

Generated figures for fallback/synthetic runs carry a visible quality
annotation, so a plot can never quietly imply more fidelity than the soils
support.

## Inspecting a run's soil mode

```bash
swat inspect <run_path>
```

This prints the persisted `metadata.json`, including `soil_mode` and
`pct_fallback_soils`, so you can see the soil basis before trusting any
soil-dependent result.

## Read next

- [Claim governance](../concepts/claim-governance.md) — how the soil gate
  interacts with the tier
- [Reading the evidence](reading-evidence.md) — finding soil provenance in the
  bundle
