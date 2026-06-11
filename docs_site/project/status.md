# Honest status

This page states, plainly, what swatplus-builder does and does not currently
establish. Keeping it visible is deliberate: the whole point of the system is
that claims track evidence, and that discipline applies to the project's own
claims too.

## Headline

!!! warning "Alpha research software"
    Under the current strict gates, the canonical 11-basin objective report
    classifies **0 basins as research-grade**. The `≥7` target stated in
    earlier planning is **not** supported by the present evidence, and gate
    weakening to manufacture passes is not permitted.

This is not a failure of the pipeline; it is the pipeline working as designed.
Most basins **build and run** the engine, and several **calibrate with real,
independently verified improvement** — and still do not earn a research-grade
*claim*, because a provenance, physical, outlet-scope, or skill gate is not
met. A blocked claim is *classified evidence*, not a crash.

## What is solid today

- Headless gauge-to-`TxtInOut` build with no QGIS.
- The [locked calibration protocol](../concepts/locked-calibration.md): lock →
  calibrate → independently verified rerun.
- [Claim governance](../concepts/claim-governance.md): runtime gates emit a
  tier; metrics never self-promote.
- A machine-readable [evidence bundle](../concepts/evidence-bundle.md) on every
  run, including typed, artifact-backed refusals.
- An 11-tool [MCP surface](../agents/tool-surface.md) and a container baseline.

## Best performers, honestly labeled

Even the strongest runs are downgraded when a gate fails. Representative
examples (baseline → independently verified locked rerun):

| Basin | ΔNSE | ΔKGE | Gates passed | Why still blocked |
|---|---|---|---|---|
| `03349000` | −0.043 → 0.412 | −0.131 → 0.658 | physical | outlet / terminal scope |
| `03351500` | 0.009 → 0.278 | −0.101 → 0.534 | physical + routing | terminal scope + soil fidelity |
| `01547700` | −0.015 → 0.153 | −0.177 → 0.314 | locked verification | below research-grade skill |

A conventional pipeline would headline KGE 0.66 for `03349000`. This one blocks
that claim because the modeled outlet's drainage scope is not yet proven to
match the gauge. When the delineation work lands, the claim unlocks — *with
evidence, not assertion.*

## Known limitations and active work

- **Multi-terminal outlet scope** — for several basins the selected terminal
  carries only part of the generated terminal flow, which blocks
  `terminal_scope_claim`. Single-terminal delineation repair is the priority
  builder fix.
- **Absolute skill** — verified improvement is real, but absolute NSE/KGE is
  not yet benchmark-grade for most basins.
- **Schema versioning** — the evidence schema is moving to a versioned,
  pydantic-owned form (`schema_version: "1.0"`).
- **Generality demonstration** — the [six invariants](../concepts/invariants.md)
  are stated as a framework; a second, non-hydrology reference implementation
  is planned, not done.
- **Empirical governance study** — a pre-registered overclaiming experiment
  (does contract-governed execution reduce unsupported agent claims?) is
  designed and not yet run.

!!! note "Version"
    The packaged version is `0.4.0` (`pyproject.toml` / `swatplus_builder.__version__`).
    Treat `pyproject.toml` as authoritative for what you installed.

## The contribution, stated precisely

The contribution is an **evidence-producing, claim-governed workflow** that
makes both successes and limitations inspectable — not a claim that automated
SWAT+ calibration is solved. The refusals are part of the result.

For the full internal audit, see `docs/PIPELINE_RESEARCH_GRADE_AUDIT.md` in the
repository.
