# Claim governance & tiers

A *claim* is a statement about a model result — "the discharge-skill thresholds
are met at the gauge," "the water balance closes," "the calibrated improvement is
real." swatplus-builder never lets a metric promote a claim on its own. A claim
is granted a **tier** only when the supporting **gates** pass, and every grant
or refusal is recorded with a typed reason and an artifact pointer.

## The four tiers

Claim tiers form an ordered ladder. The tier you *request* is an input; the
tier you are *granted* is computed from evidence.

| Tier | Meaning |
|---|---|
| `exploratory` | the run executed and produced outputs; no skill/quality claim is supported |
| `diagnostic` | outputs are usable for diagnosis; specific gated sub-claims may hold |
| **Calibration verified** (`publication_grade`) | legacy intermediate tier: calibration and skill checks pass, but the complete sensitivity/soil/land-use fidelity requirements for the highest tier are not established; this name does not signify publication approval |
| **Gate-verified** (`research_grade`) | applicable workflow gates, including sensitivity, soil and land-use fidelity, pass for the recorded claim and scope |

!!! note "The default request is conservative"
    `swat workflow run` requests `diagnostic` by default. Asking for
    `research_grade` is a *policy-gated* request with preconditions (e.g. a
    ≥10-year window) — and even when accepted, the tier is only *granted* if
    the evidence gates pass.

!!! note "`research_grade` is a package tier, not a performance class"
    The identifier is kept for compatibility with recorded evidence. It means
    that the applicable requirements for the recorded claim and scope passed; the thresholds (for
    example KGE ≥ 0.40, NSE ≥ 0, |PBIAS| ≤ 30 %) are more lenient than published
    streamflow ratings. The dashboard therefore labels it **Gate-verified**.

    Moriasi performance ratings concern a specified simulated variable, time
    step and evaluation period. They do not define a **research-grade** class.
    Any assessment against those criteria must be reported separately from the
    workflow tier, with the reference year and complete metric requirements.

## Separate streamflow performance assessment

New dashboards display Moriasi 2015 numeric streamflow criteria independently
of workflow status: **Met**, **Not met**, or **Not evaluated**. They require
R² > 0.60, NSE > 0.50 and |PBIAS| ≤ 15%, with a named time step, evaluation
period and role. Missing metrics or scope cannot establish a pass. Calibration
alignment is labelled separately from reported validation, and all matched
pairs are assessed before display downsampling. Graphical and contextual
assessment remain necessary. See the [assessment schema](../reference/evidence-schema.md#separate-numeric-performance-assessment).

## Gates

A gate is a runtime check that produces a pass/fail with an artifact. The
governance layer consults gates such as:

| Gate | Question it answers |
|---|---|
| **Fresh engine** | were the scored outputs produced by *this* run, not a stale directory? |
| **Benchmark lock** | is there a hashed baseline to measure improvement against? |
| **Outlet / terminal scope** | does the modeled outlet's drainage actually match the gauge? |
| **Physical sensibility** | are ET partition, mass balance, and volume bias within bounds? |
| **Routing-flow closure** | does routed flow conserve mass through the network? |
| **Soil fidelity** | were real soils used, or a fallback that lowers the ceiling? |
| **Sensitivity screen** | were the calibrated parameters actually shown to matter? |
| **Locked verification** | do the reported metrics survive an independent rerun? |

A claim is only as strong as the gates beneath it. **A beautiful NSE cannot
promote a claim if mass closure failed or the soils were a fallback.**

## The decisive rule

!!! quote "Metrics alone never promote a claim"
    Two runs can show the same KGE and receive *different* claim tiers, because
    one passed outlet-scope and soil-fidelity gates and the other did not.
    Promotion is a function of evidence, not of the headline number.

## Allowed, conditional, blocked

For each run the package emits, per claim:

- **allowed** — gates support the claim at the requested tier;
- **conditional / downgraded** — some gates degraded, so the claim is granted
  at a lower tier or with caveats;
- **blocked** — a gate failed; the claim is refused with a **typed reason**
  (for example `outlet_scope_volume_mismatch`) and a pointer to the artifact
  that justifies the refusal.

This is why a *blocked claim is itself evidence*: the system documents what you
may not say, in a form a reviewer or another agent can read mechanically.

## Read next

- [Locked calibration protocol](locked-calibration.md) — the verification gate
  in depth
- [The evidence bundle](evidence-bundle.md) — where allowed/blocked claims are
  written
- [Honest status](../project/status.md) — what tiers the basin suite actually
  earns today
