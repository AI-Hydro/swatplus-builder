# Project status

> **What swatplus-builder establishes today — and what it does not — stated plainly.**

Keeping this page prominent is deliberate. The whole point of the system is that
claims track evidence; that discipline applies to the project's own claims too.

## Where it stands

!!! warning "Alpha research software"
    In the dated 2026-07-02 objective-suite snapshot, **0 of 11 complete
    workflows** were promoted to the package-defined `research_grade` tier.
    The gates were not relaxed to manufacture passes. A later focused positive
    case is reported separately below and does not revise that snapshot.

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
- A [13-tool agent interface](../agents/tool-surface.md) and a container
  baseline.

## Later focused cases, honestly labeled

Two deliberately retained 2026-07-10 cases exercise contrasting package
decisions. They are mechanism demonstrations, not a representative basin
sample and not additions to the dated objective-suite snapshot.

| Basin | Benchmark NSE / KGE | Locked verification NSE / KGE | Withheld 2016--2019 NSE / KGE | Package decision |
|---|---:|---:|---:|---|
| `01547700` | 0.2875 / 0.3522 | 0.3536 / 0.5856 | 0.3742 / 0.6260 | `research_grade` workflow tier; terrain/lapse-derived subclaims remain blocked |
| `03349000` | -0.4202 / 0.0841 | -0.0199 / 0.3548 | 0.0087 / 0.3010 | `exploratory`; final skill and transfer requirements did not pass |

The negative control preserves real metric improvement without promoting the
calibrated skill claim. The positive case shows that a complete governed path
can reach the package-defined tier while still retaining blocked subclaims.

## Known limitations

- **Drainage / outlet scope.** For several basins the selected outlet carries
  only part of the network's flow, which blocks a basin-scale skill claim.
  Single-outlet delineation is the priority fix.
- **Evaluation breadth.** The two focused cases were selected to expose
  contrasting decisions and do not establish broad basin performance.
- **Peak flows.** The positive case still underrepresents some sharp observed
  peaks despite passing the package policy.
- **Evidence schema.** The on-disk evidence format is stabilizing toward a
  formally versioned schema; consume it defensively for now.
- **Archival reproduction.** Version 0.7.14 is the current hardened source
  state. A public checksummed evidence archive and archival DOI remain pending;
  the historical July run-engine checksum cannot be reconstructed.

!!! note "Version"
    The current source version is `0.7.14`
    (`pyproject.toml` / `swatplus_builder.__version__`).

## The contribution, stated precisely

swatplus-builder is an **evidence-producing, claim-governed modeling workflow**
that makes both successes and limitations inspectable. The refusals are part of
the result — not something hidden behind the headline number.
