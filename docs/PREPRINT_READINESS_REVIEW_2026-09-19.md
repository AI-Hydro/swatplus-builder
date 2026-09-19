# Preprint readiness review — 19 September 2026

## Decision

**Do not publish the present manuscript unchanged.** There is a credible software-methods contribution, but the current claim of withheld validation is stronger than the modelling procedure supports. The immediate work is to correct that scientific claim, close demonstrated evidence-validation defects, and make the evaluated software and evidence publicly reconstructable. Perfection, nationwide hydrologic performance, and a large agent experiment are not prerequisites for a narrowly scoped preprint.

This review covers the dirty working tree at base commit `00592c495f4e0cb46d6de5a7fd95915712adf1e7`, the July manuscript evidence, the September live positive run, `Research_article/paper.md`, and the 17-page `Research_article/latex/paper_ems.tex` / PDF compiled September 16. It supersedes earlier readiness implications, not the historical numerical results. Application code and retained runs were not changed during this review.

## Remediation status — later on 19 September 2026

The demonstrated implementation gaps below are now corrected in the 0.7.14
working tree with regression coverage. Observation-conditioned preparation uses
calibration-window observations and matching annual model diagnostics; GridMET
validates the exact calendar and raw values and serializes any repair; research
weather claims reject imputation; claim gates recompute metric improvement and
require typed, hashed timing-exception evidence; engine receipts bind inputs,
binary identity and execution settings. The source suite passes 1,117 tests with
3 skips and 12 slow/live deselections. This remediation does not retroactively
make the July evidence independent. Fresh same-revision basin evidence,
manuscript reconciliation, portable packaging and archival publication remain
the release steps. Findings below retain their original review wording as the
audit record.

## 1. New findings, in release priority order

### P1 — Validation observations influence model preparation

**Confirmed in code, reproduced, and present in retained evidence.**

The workflow calculates a chronological split in `src/swatplus_builder/workflows/usgs_e2e.py:957`, but calls `run_pipeline` with the full requested date interval at line 984. In `src/swatplus_builder/orchestrate.py:167`, observed discharge for the full interval reaches `apply_subsurface_prior_correction`. In `src/swatplus_builder/full_mode/subsurface_priors.py:181`, `_observed_runoff_context` sums all available observations without a training-window restriction. The resulting observed runoff/precipitation ratio determines whether six parameter fields are changed before calibration. This is an observation-conditioned model adjustment, even though it is called a prior correction.

The retained correction reports show:

| Run | Observed days consulted | Correction outcome | Observed annual Q/P |
| --- | ---: | --- | ---: |
| July 10 positive, 01547700 | 3,652 | `applied_improved` | 0.453807 |
| July 10 negative, 03349000 | 3,652 | `not_applied` (ET/P guardrail) | 0.417340 |
| September 16 positive, 01547700 | 3,652 | `applied_improved` | 0.453878 |

These cover 2010–2019, including the nominal 2016–2019 validation interval. The negative case consulted the data but did not apply the correction; do not imply that its parameters were changed by this step.

An isolated fixture kept 2010–2015 observations and all model inputs fixed. Changing only 2016–2019 discharge changed full-period Q/P from 0.2 to approximately 0.4: the correction switched from `not_applied` to `applied`, changing six parameter fields. The fixture used the existing `_write_fixture` from `tests/test_subsurface_priors.py`, 100 km², 1,000 mm annual precipitation, and daily flow `depth_mm * 100 / 31557.6`; annual depths were 200 mm in training and either 200 or 700 mm in validation.

**Consequence:** the DDS search and sensitivity window can exclude validation years while the complete modelling procedure still leaks their information. The recorded scores remain descriptive measurements of the retained models. The size and direction of any bias are not established. Fresh execution is a different property from statistical independence.

**Required response:** partition observations before any adaptive preparation. Use matching training-period model water-balance diagnostics and observations for observation-conditioned priors and decisions. Audit diagnostic selection, calibration admission, search, and candidate selection too. Add a test that changing only validation observations cannot change prepared inputs, selected parameters, search trajectory, or the chosen model; only post-fit evaluation may change. Then rerun the focused pair under one frozen version if independent-validation wording is retained.

Repeated development has already inspected these years. Even a corrected rerun should disclose that history; a genuinely untouched temporal block or basin, evaluated with a predeclared frozen procedure, would support the strongest generalization claim. Do not tune repeatedly against a new test block.

**Manuscript impact:** abstract; Methods; focused-case results; Figures 2, 4 and 5; conclusions; ledger C07, C08, C12, C18 and related interpretation. The prior correction itself is absent from the manuscript's methods. Historical `research_grade` remains a recorded package decision, not proof that the independence requirement was satisfied.

### P1 — Weather validation accepts wrong dates and silently masks missing values

**Reproduced at the adapter boundary.** `weather/gridmet.py:541` returns early whenever row count matches the requested number of days; `_validate_response_shape` at line 629 also checks only length. A response indexed January 2–3 passes a January 1–2 request and is relabelled with the requested start by `_build_series`.

At line 685, `min`/`max` conversions turn NaN relative humidity inputs into `1.0`, and NaN wind and radiation into `0.0`. The resulting `StationSeries` accepts them. Thus missing provider data can become plausible forcing without an error. This probe does not establish that the retained basin runs contain such data.

**Required response:** require a unique, ordered daily calendar equal to the requested interval; reject non-finite raw variables before conversion; validate physical ranges and temperature ordering. Record every permitted imputation by station, date, variable, method, and policy, and propagate its claim implications. Add shifted-date, duplicate-date, NaN/Inf, and missing-day negative controls.

### P1 — Some claim gates still trust unsupported declarations

**Reproduced for individual gates, not demonstrated as a complete workflow promotion exploit.**

- `governance/gates.py:220`: `calibration_improvement_gate` passes any nonempty `verification_improvement_basis` except `none`, when a success flag is true. A probe with basis `unsupported` and both NSE and KGE deltas `-1` passed.
- `governance/gates.py:122`: `timing_limitation_documented="false"` is truthy. With NSE `-0.5`, KGE `0.6`, PBIAS `0`, this passes the research-metric gate. Unvalidated exception text can also activate the exception.

**Required response:** typed evidence, enumerated improvement reasons, recomputed improvement from the designated verified metrics, and an explicitly authorized, scoped timing-exception record. Missing or contradictory evidence must fail. Keep valid positive controls alongside negative controls so rejection alone cannot masquerade as correctness.

### P2 — Execution receipts do not bind outputs to executed inputs or engine identity

**Reproduced at the freshness gate.** `run/swatplus.py:579` records a run ID, return code, and selected output hashes. After issuing a receipt, changing `hydrology.hyd` leaves `fresh_engine_gate` passing. The gate checks output integrity, not whether those outputs belong to the inputs now presented.

The separate benchmark lock protects baseline inputs in applicable paths. It does not by itself prove the identity of the final calibrated execution inputs, which the workflow identifies separately as `fresh_txtinout_dir`. This is a provenance-chain weakness, not proof that historical results were tampered with.

**Required response:** bind each execution to an input manifest, engine binary digest, execution configuration and timestamps; verify final metrics against that execution and its alignment/window. Define the trust boundary: hashes detect drift relative to a trusted manifest; they do not authenticate an operator who can rewrite both files and manifests. The current package is not a security sandbox against an agent with unrestricted filesystem access.

### P2 — Network timeout guarantee is conditional

**Code-confirmed compatibility path.** `weather/gridmet.py:472` retries older clients without `conn_timeout` when the keyword is rejected. The adapter therefore cannot guarantee its advertised timeout bound on that path. A connection timeout also need not bound a complete multi-request station fetch.

Pin a supported client or implement a tested deadline/cancellation mechanism. Record when fallback semantics apply. Treat September's native-cell deduplication as an optimization requiring independent provider equivalence checks near grid boundaries; comparing a reused series with its source is not an independent validation of cell assignment.

### P1 for publication — No single release snapshot represents all advertised evidence

The manuscript retains two July Builder revisions (`1e6110bff429`, `bab115f68847`); the public version cited is 0.7.13; `CITATION.cff` still identifies 0.7.10 and DOI `10.5281/zenodo.20650908`; September hardening and weather changes remain in a dirty working tree. The September complete run preceded some subsequent weather changes. None of those states is interchangeable.

Good news: all **16 manifest entries with a path and SHA-256** still match their local files. That establishes local retained-file integrity for those entries, not complete portability or reproduction. The manifest describes itself as a draft inventory, uses local absolute paths, records a dirty checkout and an installed-package version of 0.7.6, and has no public code-and-evidence archival identifier. Historical engine checksums are explicitly unavailable. `Research_article/` is ignored by Git; a software tag alone will omit the paper assets.

Freeze one evaluated code snapshot and build artifact; export the evidence, manuscript sources and figures with relative paths and redistribution terms; include environment and executable digests, policy version, recorded seed, forcing/observation identity, and exact commands. Do not manufacture missing historical provenance. Demonstrate replay from the exported package in a fresh environment before describing it as reproducible.

## 2. What the paper can contribute sharply

Suggested title: **SWATPlus-Builder: Executable Claim Governance for Auditable, Agent-Operable SWAT+ Workflows**.

Suggested central statement:

> SWATPlus-Builder makes the scope of a modelling claim an explicit software output. It connects domain checks and designated run evidence to machine-readable allowed and blocked claims, allowing human or agent operators to inspect why a completed workflow supports a particular assertion or falls short of it.

| Contribution | Why it matters | Appropriate evidence and limit |
| --- | --- | --- |
| Executable, scoped claim decisions linked to evidence and a versioned policy | A successful engine exit or better score alone cannot explain which scientific assertions are supported | Trace representative claims through required gates, artifact identities, and decisions; repair the declaration and identity gaps above |
| A common evidence contract across build, calibration, fresh verification and reporting | Prevents candidate scores, baseline results and final reported results from being conflated | One replayable positive and one contrasting failed case, with exact provenance and revised validation interpretation |
| Failure-preserving evaluation | A system can retain a numerical improvement while explicitly withholding a stronger claim | Keep the 0/11 dated suite and negative case, without treating them as a current performance estimate |
| An operator-independent interface suitable for agents | Lets tools expose the same evidence state to humans, scripts and agents | Demonstrate an actual tool-call-to-evidence trace; no causal claim about improved agent behaviour without a controlled study |

The contribution is an implemented domain-specific integration and its evaluated decision mechanism. It is not a new hydrologic model, optimizer, universal adequacy standard, or proof that agents cannot overclaim.

**Potential precedent:** scientific software could return a result together with explicit, testable limits on its interpretation. A rejected or downgraded claim becomes a preserved research output. The portable design pattern is `request → execution → identified evidence → policy decision → scoped assertion`. Adoption beyond this package and effectiveness in other domains remain hypotheses, not demonstrated outcomes or a defensible claim to being the first such system.

## 3. Closest prior work and the missing comparison

The current draft already bounds several comparisons well. One especially relevant omission is **SWATdoctR**, absent from the searched paper, bibliography and literature matrix. Its five-step workflow already checks weather, water balance, management, plant growth and other setup processes before calibration. This directly narrows claims that adding physical checks itself is novel. [SWATdoctR, Environmental Modelling & Software, 2024](https://doi.org/10.1016/j.envsoft.2023.105878).

Other established foundations are configuration-driven SWAT+ automation and reproducibility in [SWAT+ AW (2020)](https://doi.org/10.1016/j.envsoft.2020.104812), scripted calibration and validation in [SWATtunR (2026)](https://doi.org/10.1016/j.envsoft.2026.107014), and workflow execution provenance and packaging in [Workflow Run RO-Crate (2024)](https://doi.org/10.1371/journal.pone.0309210).

Add a source-backed comparison by capability: model construction; setup diagnostics; calibration/validation; provenance; explicit claim decisions; machine-readable reasons; agent-callable interface. Use “not documented in the reviewed source” where appropriate, rather than asserting a competing tool lacks a feature. The additional value to demonstrate is the executable connection between these layers. No runtime or skill ranking is currently supported.

## 4. Evidence that is missing, thin, or optional

| Evidence | Present state | Minimum credible next step |
| --- | --- | --- |
| Strict holdout isolation | Contradicted by observation-conditioned preparation | Correct/re-evaluate, or explicitly reclassify historical temporal scores as retrospective evaluation after full-period-informed preparation |
| Governance correctness | Eight selected challenges pass; new acceptance gaps reproduced | Add the new fault cases, valid controls, gate-boundary/contradiction cases, and a trace to final claim output; report coverage, not a universal safety rate |
| Reproducibility | Locally retained, matching hashes; archive incomplete | One portable, checksummed code/data/evidence release and a clean-environment replay |
| Current-version behaviour | Old suite, two July revisions, one September positive | Same frozen version for new positive/negative demonstrations; preserve older results separately |
| Agent operability | Interfaces and prospective study exist | Retain a real agent/tool transcript, model/tool versions, request, decisions, final answer and human interventions; useful demonstration, not a causal experiment |
| Reduction in agent overclaiming | No executed comparison | Only necessary if claiming reduction: matched tasks, governed/ungoverned conditions, blinded scoring, repeated runs and uncertainty; the full 400-run study need not block a bounded software preprint |
| Basin generality | Two deliberately selected cases; historical 0/11 | Disclose selection and limitations. More prospectively chosen climates/sizes and failures strengthen the next study; do not cherry-pick a pass count |
| Threshold validity | Package policy, modest skills, exception paths | Cite rationale, show a small threshold sensitivity analysis and describe user-relevant claim scope; `research_grade` must not imply certification |
| Hydrologic adequacy | Daily metrics, hydrographs, peak and flow-duration plots | Retain visible peak/low-flow limitations. Uncertainty, event/seasonal diagnostics and multiple splits are valuable if broader application claims are added |
| Security | Focused local integrity review | State trusted local operator assumptions. No dependency-CVE audit or hostile remote-service penetration test was completed here |

For the strongest governance-specific experiment, use a paired fault-injection evaluation: fixed clean evidence, one changed condition at a time, independently specified expected claim states, valid controls, and final emitted decisions. Include the leakage case: a policy can confidently approve a run while missing a scientific requirement. Report that limitation and the correction rather than presenting 8/8 selected tests as comprehensive validation.

## 5. Specific manuscript revisions

1. **Title and abstract:** the compiled title foregrounds generative AI, although the comparative agent study is unexecuted. Prefer the implementation-focused title above. Replace “scientific authority” with “evaluates explicit claim policy from recorded evidence” where the broader phrase suggests scientific certification. Change “all eight controlled violations were rejected” to “eight selected challenges produced their expected decisions,” since some decisions retain evidence while downgrading claims.
2. **Methods:** document the observation-conditioned subsurface correction, its thresholds, changed fields, evidence window and scientific justification. Separate fresh rerun verification, temporal evaluation and genuinely independent validation. Specify policy/version and any authorized exceptions.
3. **Results and figures:** keep existing scores attached to their original runs. Revise “withheld validation PASS” labels and interpretations unless corrected evidence is added. Do not silently regenerate July figures from September results. A caption should distinguish historical package approval from a claim supported after this audit.
4. **Related work:** add SWATdoctR and sharpen the comparison with AW, SWATtunR and RO-Crate. Avoid first-ever, superior, or agent-safety claims unsupported by controlled comparisons.
5. **Limitations:** add preprocessing leakage, development reuse of validation years, the trusted-local-writer boundary and untested governance cases. The present limitations section is careful, but does not contain these material findings.
6. **Reproducibility and declarations:** reconcile code/archive/citation versions; remove the two placeholder email addresses; obtain author confirmation of contact, contributions, funding and declarations. Do not infer a funding statement or invent an email. Verify bibliography metadata against primary records. Journal-specific upload formatting can be completed later; it is not the main preprint blocker.
7. **Document consistency:** synchronize Markdown, LaTeX, claim ledger and figures only after selecting the evidence scope. Preserve the historical freeze and append a dated correction. The existing `GAPS.md` list is incomplete without the scientific issues above.

The reviewed title/abstract and positive-case figure are legible; visual polish is not the main obstacle. Figure 4 prominently presents withheld validation and a green package approval, making the interpretation correction necessary in the visual as well as the prose. This was a targeted visual review, not a new full-page layout certification.

## 6. Shortest responsible path to public release

**Recommended:** correct the observation isolation, weather validation and evidence gates; freeze code; rerun the positive/negative demonstrations; independently replay claims/metrics from the exported evidence; update the paper and archive. A negative scientific outcome must remain publishable evidence of the mechanism, not trigger weaker thresholds. Further basin breadth and a large agent experiment can follow.

**If the deadline cannot accommodate reruns:** publish only a clearly bounded software/mechanism preprint after disclosure and claim revision. Describe the July temporal scores as retrospective and the `research_grade` result as a historical package decision with the newly identified limitation. Include this failure mode and the remaining implementation limitations. Supply the actual evaluated snapshot and evidence. This route does not justify presenting the unchanged paper as independently validated or the current code as fully hardened.

Release acceptance checks:

- Every headline claim has a matching artifact and an explicit scope; no hidden dependence on validation observations is labelled independent.
- Every cited experiment identifies its actual code and policy, without merging July, September and later edits.
- Representative clean and corrupted evidence produces the independently expected final claim state.
- A reader can obtain and replay the exported evidence without the author's absolute filesystem paths.
- Manuscript text, figures, ledger, archive and citation identify the same release story; author placeholders are gone.

## Verification performed in this review

- Existing focused suites: **119 passed, 1 live-GridMET test skipped** across subsurface priors, weather, governance and security-hardening tests. Source loaded with `PYTHONPATH=src` in `/tmp/swatplus-hardening-20260916/venv/`.
- The exact eight manuscript challenge identifiers were rerun: **8 passed**. This overlaps the focused suites and is not an additional unique test total.
- Temporary isolated probes reproduced the holdout-only parameter change, shifted weather-date acceptance, NaN coercion, unsupported improvement basis, string-boolean exception and post-receipt input mutation acceptance. No retained run was modified.
- All 16 hash-bearing file entries in the July reproducibility manifest matched locally.
- Read Markdown/LaTeX and evidence/gap records; extracted compiled PDF text and visually inspected physical pages 1, 2 and 11.
- Checked primary prior-art records for AW, SWATtunR, SWATdoctR and Workflow Run RO-Crate. The live EMS author-guide page returned HTTP 403; this review does not assert a fresh verification of journal submission requirements or all bibliography records.
- No new full-basin simulation, independent reproduction by another researcher, package publication, dependency vulnerability scan or comprehensive security certification was performed.
