# Reading the evidence

A run is only as useful as your ability to read what it claims. This page is a
practical walk-through of the bundle, in the order you should actually read it.

## 1. Open `evidence_summary.json` and read `blocked_claims`

Start with what the system *refused* to assert. Each blocked claim has a typed
reason and an artifact pointer:

```json
{
  "blocked_claims": [
    {
      "claim": "terminal_scope_claim",
      "reason": "outlet_scope_volume_mismatch",
      "artifact": "routing_flow_gates.json"
    }
  ]
}
```

If the claim you care about (say, "research-grade skill at the gauge") is in
`blocked_claims`, the reason code tells you *which gate* stopped it — and the
artifact tells you *where to look*.

## 2. Read `allowed_claims` and the tier

```json
{
  "effective_claim_tier": "exploratory",
  "allowed_claims": ["model_executed", "calibration_improved_baseline"]
}
```

The tier is computed from the gate table, not asserted. "calibration improved
the baseline" and "the model has research-grade skill" are *separate* claims
that gate independently — a run can be allowed the first and blocked on the
second.

## 3. Confirm the metrics are verified, not candidate

Cross-check `calibration_provenance.json`. Only metrics tied to the
**verification** rerun are authoritative:

```json
{
  "baseline": {"nse": -0.015, "kge": -0.177},
  "verified": {"nse": 0.153, "kge": 0.314},
  "authority": "verified_rerun",
  "candidate_metrics_authoritative": false
}
```

If a number you want to cite is a *candidate* metric, it is not reportable as a
final result. See [Locked calibration](../concepts/locked-calibration.md).

## 4. Follow the gate artifacts

`physical_gates.json` and `routing_flow_gates.json` carry the pass/fail detail
behind the claim decisions — ET partition, mass balance, volume bias, routed
mass closure. When a claim is blocked, this is where the justification lives.

## 5. Check provenance for reproducibility

`run_manifest.json` carries inputs, artifact paths, and the git SHA;
`evidence_summary.json` carries provenance hashes. Cite the repository and the
run's provenance hash when reporting.

## 6. Audit the whole run in `dashboard.html`

Every workflow run writes `dashboard.html` into its run directory, including
runs that were blocked before the engine ran. It is the modeller's interface to
the headless pipeline: one self-contained file that opens in any browser,
offline, with no server. Plotly and Leaflet are embedded; only the map's
background tiles need a network.

| Tab | What it answers |
|---|---|
| Overview | Which gates passed; benchmark, verified and withheld metrics side by side; known limitations; model inventory |
| Hydrology | Hydrograph, flow-duration curve, observed vs simulated, baseflow index, seasonal flow, water balance |
| Calibration | Method, search history and convergence, calibrated parameter positions |
| Spatial | Basin, subbasins, channels, outlet, HRUs and DEM on a map; land-use and soil sources |
| Evidence | Allowed and blocked claims with their basis or reason; run and artifact details |
| Audit | Every recorded pipeline stage, every typed decision, and whether the evidence still matches what was sealed |

The **Audit** tab re-verifies both hash-chained ledgers against the heads
sealed in `run_manifest.json` and re-hashes the sealed evidence files, so a
file edited after the run shows as *changed*. It also lists the package and
engine versions, the benchmark input lock, and the locked verification run's
execution receipt. A blocked run's trail shows the stage that stopped it and
the typed reason every later stage records.

The workflow builds the dashboard once during the run and again after the
ledger heads are sealed, so the `dashboard.html` a finished run leaves behind
already carries the sealed-head check. If the second build fails, the
dashboard from the run is kept; its Audit tab then confirms only that each
chain is intact and says so. To re-check a run later, run
`swat audit verify <run_dir>` or rebuild the dashboard:

```python
from swatplus_builder.output.dashboard import build_dashboard
build_dashboard("runs/usgs_01547700")
```

Rebuilding writes only `dashboard.html`; it never touches the sealed evidence.

## A reading checklist

- [ ] read `blocked_claims` — is my target claim blocked, and why?
- [ ] read `allowed_claims` and `effective_claim_tier`
- [ ] confirm any cited metric is from the **verified** rerun, not a candidate
- [ ] open the named gate artifact for any claim I rely on
- [ ] record the git SHA + provenance hash with the result

!!! quote "The one-line rule"
    Reporting a metric without disclosing a failed gate is overclaiming —
    whether a human or an agent does it.
