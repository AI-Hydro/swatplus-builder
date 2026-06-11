# Six invariants

SWAT+ hydrology is the case study, not the point. The exportable contribution
is a small set of **invariants for agent-governed scientific pipelines** — the
properties that make *any* AI-operated computational science workflow
trustworthy and auditable. swatplus-builder is one concrete implementation of
them.

## The invariants

1. **Typed contract before execution.**
   Work begins from an explicit, machine-checkable contract (task, scope,
   requested claim tier, preconditions) — not from free-form intent. Policy is
   validated *before* compute is spent.

2. **Claims, not results — tiered, gated, artifact-backed.**
   The unit of output is a *claim* with a tier, not a bare number. Every claim
   is backed by gate results and an artifact pointer. The headline metric is
   never the authority.

3. **Locked baseline → candidate → independent verification.**
   Improvement is measured against a sealed baseline, and the reported value
   comes from an independent rerun of the promoted artifact — never from the
   optimizer's own trajectory.

4. **Fresh-evidence enforcement.**
   Outputs must be provably produced by *this* run. Stale artifacts are
   unscoreable; a metric computed on yesterday's outputs cannot promote a
   claim today.

5. **Provenance-or-degrade.**
   Every fallback (synthetic weather, fallback soils, auto-selected outlet)
   lowers the achievable claim ceiling and is recorded. You can still run with
   degraded inputs — you just cannot claim as much.

6. **Machine-readable refusal.**
   When the evidence does not support a claim, the system refuses with a
   **typed reason and a next action**, in the same structured form as a
   success — so refusals are auditable and programmable.

## Why frame it this way

These six properties are domain-neutral. A flood-frequency tool, a
remote-sensing retrieval pipeline, or a parameter-estimation service could each
implement the same invariants with entirely different gates. That is the
generality claim: the *governance core* — contracts, claims, tiers, gate
protocol, evidence I/O, refusal types — is separable from the hydrology, and
the hydrology is just the first set of gate implementations registered against
it.

!!! note "Status of the generality claim"
    Demonstrating the invariants in a *second*, non-hydrology domain (a small
    toy reference) is planned work, not a completed result. See the
    [project roadmap on GitHub](https://github.com/AI-Hydro/swatplus-builder)
    and [Honest status](../project/status.md). This page states the framework;
    it does not claim the second-domain demonstration is already done.

## Read next

- [Package as authority](overview.md) — the principle the invariants encode
- [Claim governance](claim-governance.md) — invariants 1, 2, 5, 6 in practice
- [Locked calibration](locked-calibration.md) — invariants 3 and 4 in practice
