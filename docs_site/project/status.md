# Project status

> **What swatplus-builder establishes today — and what it does not — stated plainly.**

Keeping this page prominent is deliberate. The whole point of the system is that
claims track evidence; that discipline applies to the project's own claims too.

## Where it stands

!!! warning "Alpha research software"
    Under its current strict gates, the 11-basin test suite grants **no basin a
    research-grade claim**. The gates are not relaxed to manufacture passes.

This is not a failure of the pipeline — it is the pipeline working as designed.
Most basins **build and run** the engine cleanly, and several **calibrate with
real, independently verified improvement** — and still do not earn a
research-grade *claim*, because a provenance, physical-realism, outlet-scope, or
skill gate is not met. A blocked claim is *classified evidence*, not a crash.

## What is solid today

- A complete gauge-to-model build in Python, with no desktop GIS.
- The [locked calibration protocol](../concepts/locked-calibration.md): lock →
  calibrate → independently verified rerun.
- [Claim governance](../concepts/claim-governance.md): runtime gates emit a
  tier, and metrics never promote themselves.
- A machine-readable [evidence bundle](../concepts/evidence-bundle.md) on every
  run, including typed, evidence-backed refusals.
- An [11-tool agent interface](../agents/tool-surface.md) and a container
  baseline.

## Best results, honestly labeled

Even the strongest runs are downgraded when a gate fails. Representative
examples (baseline → independently verified rerun):

| Basin | ΔNSE | ΔKGE | Gates passed | Why still blocked |
|---|---|---|---|---|
| `03349000` | −0.043 → 0.412 | −0.131 → 0.658 | physical realism | outlet / drainage scope |
| `03351500` | 0.009 → 0.278 | −0.101 → 0.534 | physical + routing | drainage scope + soil fidelity |
| `01547700` | −0.015 → 0.153 | −0.177 → 0.314 | verified calibration | below research-grade skill |

A conventional pipeline would headline KGE 0.66 for `03349000`. This one blocks
that claim because the modeled outlet's drainage area is not yet proven to match
the gauge. When the delineation work lands, the claim unlocks — *with evidence,
not assertion.*

## Known limitations

- **Drainage / outlet scope.** For several basins the selected outlet carries
  only part of the network's flow, which blocks a basin-scale skill claim.
  Single-outlet delineation is the priority fix.
- **Absolute skill.** Verified *improvement* is real, but absolute NSE/KGE is
  not yet benchmark-grade for most basins.
- **Evidence schema.** The on-disk evidence format is stabilizing toward a
  formally versioned schema; consume it defensively for now.

!!! note "Version"
    The current packaged version is `0.7.8`
    (`pyproject.toml` / `swatplus_builder.__version__`).

## The contribution, stated precisely

swatplus-builder is an **evidence-producing, claim-governed modeling workflow**
that makes both successes and limitations inspectable. The refusals are part of
the result — not something hidden behind the headline number.
