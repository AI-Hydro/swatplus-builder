# Security, reliability, and enhancement review

Date: 2026-09-16. Reviewed checkout: `00592c4`, package version `0.7.13`,
including the pre-existing uncommitted documentation changes.

## Remediation — 2026-09-16

All nine findings below have implementation changes and regression coverage in
this working tree. The original findings remain a record of the reviewed
baseline, not a description of the fixed code.

- R1: finite-number/range validation at scientific gates.
- R2: explicit successful execution status and a new validation cache namespace.
- R3: detached CLI supervisor, durable launch-bound terminal result, and child reaping.
- R4: unique launch IDs, empty output directories, exclusive ownership, and non-truncating logs.
- R5: immutable artifact directories, staged atomic publication, and payload manifests.
- R6: strict SHA-256 IDs and resolved-root/symlink confinement.
- R7: shared benchmark/input verification, run-bound outlet hashes, and execution
  receipts checked against output bytes; both solver entry points produce receipts.
- R8: reusable offline installed-wheel tests required by CI and release upload.
- R9: reviewed upstream archive/binary digests, verified cache restoration, and
  extraction of only the specifically pinned archive member.

The clean install also exposed incompatible MCP 2 dependency resolution; the
package now constrains its existing FastMCP implementation to MCP major version 1.

Compatibility: artifact IDs cannot be overwritten; unsealed historical artifacts
remain on disk but are not trusted automatically. Use a fresh artifact root and
fresh runs to generate new manifests/receipts. MCP launches reject nonempty
output directories. Binary pins record bytes fetched from official upstream URLs
on this date; they are not upstream signatures. Broader enhancement scopes below
(uncertainty studies, architecture refactoring, offline dashboards) remain future
work. Final clean Python 3.13 wheel validation: **360 passed, 2 skipped, 1 deselected**;
the skips concern absent vendored-editor fixtures, and the deselection is a live
engine test. All 38 new hardening regressions passed. Source lint and diff checks
passed. Live SWAT+ basin validation and publication were not performed.

## Assessment and scope

The package has substantial scientific safeguards: sealed calibration inputs,
fresh objective execution, separate withheld-period evaluation, explicit claim
gates, parameter governance, and evidence artifacts. The largest confirmed gaps
are at the boundaries between these components: numeric validation, persistent
job state, artifact replacement, and validation-cache semantics.

This review inspected the CLI/MCP entry points, governance, calibration,
artifact storage, validation, evaluation, dependency declarations, CI/release
workflows, and project documentation. It ran 233 existing focused tests and
temporary, isolated reproduction probes. No application code was changed and
no production basin simulations were launched.

The MCP entry point uses local stdio. Findings about paths and executable
integrity are security issues under the stated trust conditions; the review did
not establish an unauthenticated remote attack surface. This is not a complete
vendored-code audit, dependency-CVE scan, or hydrologic recertification.

## Findings

### R1 — High: non-finite values pass scientific claim gates

Location: `src/swatplus_builder/governance/gates.py:14`, `:76`, and `:136`.

`_as_float` accepts NaN and infinity. Threshold comparisons against NaN are
false, so `research_metric_gate` returns `passed=True` for undefined NSE/KGE.
This is reachable from normal numerical behavior: constant observed and
simulated flow produces NaN NSE/KGE in the package's own metric functions.
The land-use gate similarly accepts NaN retention and vintage mismatch.

Reproduced: metrics computed from observations `[1, 1]` and simulation `[1, 1]`
produced `{"passed": true, "reason": "metrics pass research thresholds"}`.
NaN land-use retention/mismatch also passed. The claim builder consumes this
result at `workflows/usgs_e2e.py:522`.

Impact: a specific research-threshold claim can be emitted without valid
metrics. This does not by itself prove that every independent requirement for
the overall research-grade tier can be bypassed.

Fix: reject non-finite and boolean numeric inputs centrally; validate physical
ranges; serialize unavailable numbers as null plus an explicit reason. Add
constant-flow, NaN, infinity, and malformed-evidence regressions.

### R2 — High: failed validations become cached successes

Location: `src/swatplus_builder/validation/runner.py:136` and `:163`.

An executor result is persisted even when its status is `failed`. The artifact
schema does not preserve that execution status. The next request treats any
existing artifact directory as a cache hit and reports status `cached`; report
aggregation counts cached rows as successful executions.

Reproduced with an executor returning `ExecutorResult(status="failed")`:
first call `failed`, second call `cached`, executor invoked only once, and
`benchmark_summary.json` reported `success_count=1`. The metric pass flag was
not thereby made true; the execution-success classification was wrong.

Fix: persist execution outcome and a completion manifest; reuse only validated,
complete successful results. Retry failed/interrupted entries and provide an
explicit refresh option. Keep failure archives separate from reusable results.

### R3 — High: completed MCP workflows can remain running indefinitely

Location: `src/swatplus_builder/mcp/server.py:265`, `:350`, and `:414`.

The launcher discards the process handle. Status checks `os.kill(pid, 0)` before
reading the final result. On POSIX an unreaped exited child still has a PID and
passes that check, so a completed workflow can remain `running` while the MCP
server stays alive. PID reuse can also associate a launch with another process.

Reproduced with a harmless child that exited with code zero: a valid final JSON
payload was present, `workflow_status` returned `running`, and `waitpid` confirmed
the child had exited. Existing MCP tests replace Popen with a fake dead PID and
do not exercise child lifecycle behavior.

Fix: retain and reap child handles while the server lives; persist an atomic
terminal result and exit code for restart recovery; verify process identity.
Use a real short-lived child in lifecycle tests. Python documents the relevant
[`Popen.poll()` and `wait()` APIs](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.poll).

### R4 — High: repeated launches share a directory and truncate evidence logs

Location: `src/swatplus_builder/mcp/server.py:313` and `:348`.

An explicitly supplied directory is accepted even if another workflow owns it.
The log is reopened with `wb` and launch metadata overwritten. Default directory
names have only second-level timestamp precision, allowing same-gauge collisions.

Reproduced with mocked process creation: two calls using the same directory
both launched, and the second call erased the first call's log. Concurrent
model/evidence corruption is a resulting risk, not something exercised against
a live model during this review.

Fix: atomically acquire exclusive run ownership before opening logs; use unique
run identifiers; distinguish new run, resume, and explicit replacement. Test
simultaneous requests and resume-after-crash behavior.

### R5 — Medium: artifact replacement retains stale optional payloads

Location: `src/swatplus_builder/artifacts/store.py:81`.

`write()` overwrites config/metadata but skips metrics/provenance when absent;
it does not remove previous optional files. Files are written individually and
`exists()` accepts a directory before a full write is complete.

Reproduced: wrote NSE `0.91`, rewrote the same record ID with `metrics=None`,
then read NSE `0.91` from the supposedly replacement record. Interrupted or
concurrent writes can additionally leave mixed generations.

Fix: make records immutable, or stage a complete replacement and atomically
publish a manifest/pointer. Readers should require and verify a completion
manifest rather than directory existence. Test omitted optional files and
interrupted writes.

### R6 — Medium, security: artifact identifiers can escape the storage root

Location: `src/swatplus_builder/artifacts/store.py:166` and
`src/swatplus_builder/artifacts/models.py:104`.

The content hash has a minimum-length check but no digest-format restriction.
`_run_dir` joins the supplied value directly; absolute paths and `..` components
escape the intended root. A caller-controlled record can overwrite the store's
standard JSON filenames in another writable directory.

Reproduced entirely inside a temporary directory: `content_hash="../../escaped"`
wrote outside `<store>/runs`.

Trust condition: the caller must influence a record/hash passed to this API.
This is not privilege escalation, and no direct remote MCP exploit was shown.

Fix: enforce 64 hexadecimal characters for SHA-256 IDs at the store boundary,
reject absolute/traversal paths, and enforce resolved-root containment including
symlinks. Apply the same contract to read, exists, and lineage identifiers.

### R7 — Medium: evidence gates check existence rather than integrity

Location: `src/swatplus_builder/governance/gates.py:25`, `:56`, and `:66`.

The benchmark gate accepts any existing file; the outlet gate accepts any file
plus a separately supplied outlet ID. The fresh-output gate relies on an input
flag and a nonempty file, without checking run identity or output freshness.

Reproduced: a file containing only `{}` passed both benchmark and outlet
provenance gates when the outlet ID was supplied separately.

The calibration path already performs stronger integrity checking in
`calibration/locked_benchmark.py:2539`. The gap is that the final claim layer
does not independently reuse those guarantees. File existence supports an
availability claim, but cannot establish verified provenance.

Fix: share a typed artifact verifier between calibration and claim evaluation;
check schemas, hashes, run identity, and outlet consistency. Keep availability
and verification as separate claims. Local users able to rewrite all files are
outside what an unsigned local checksum system can authenticate.

### R8 — High: release workflow does not enforce the critical regression suites

Location: `.github/workflows/ci.yml:37` and `.github/workflows/publish.yml:39`.

Push/PR CI runs `test_smoke.py`; mypy is advisory. The nightly workflow runs a
live routing regression, not the offline governance, MCP, cache, and calibration
suites. Publishing depends only on a distribution build and `twine check`,
with no test dependency in the publishing workflow. Tag pushes are not triggers
for `ci.yml`.

Impact: a successful configured build/release does not demonstrate that the
scientific and operational contracts passed their existing regressions. This
review did not inspect external GitHub branch/environment protection settings.

Fix: add a mandatory offline suite for governance, locks, artifact/cache state,
MCP lifecycle, and output evaluation; reuse that job before publishing; test the
built wheel on supported Python versions, including 3.13. Retain live-service
tests as a separate integration signal.

### R9 — Medium, security: downloaded executables lack pinned integrity checks

Location: `.github/workflows/nightly-integration.yml:53` and
`scripts/ci/install_wbt.py:28`, `:51`.

SWAT+ is downloaded from a release URL and made executable without validating
a pinned digest. The WhiteboxTools fallback uses a mutable URL and likewise
installs the extracted binary without a digest check. HTTPS and a versioned
filename do not bind execution to one reviewed artifact.

Threat condition: replacement/compromise of upstream artifacts or download
infrastructure; no such compromise was observed. This also weakens run
reconstruction when an upstream artifact changes.

Fix: maintain per-platform executable digests, verify before extraction or
execution, and bind binary caches to those digests. Reuse the existing
datasets-bootstrap pattern, which already validates size and SHA-256.

## Enhancement scope and order

| Priority | Scope | Concrete acceptance criterion |
|---|---|---|
| First | Scientific gate hardening (R1, R7) | Undefined numbers, empty provenance, mismatched outlets, and stale artifacts cannot authorize the corresponding claim. |
| First | Durable job and cache state (R2–R5) | Failed jobs retry; completed children reach terminal state; concurrent requests cannot share mutable output; artifacts are published completely. |
| First | Automated regression/release gates (R8) | Offline contract suites and wheel smoke tests must pass before an upload job can run. |
| Next | Security boundaries and supply chain (R6, R9) | Root-escape probes fail; every installed executable matches a recorded approved digest. |
| Next | Reproducible environments and cache identity | Save dependency lock, source-tree identity, executable digest, input-data versions, and run manifest; relevant implementation/data changes invalidate cached evaluations. |
| Next | Scientific coverage diagnostics | Report valid paired days, seasonal coverage, missing periods, USGS qualifiers, and forcing coverage separately for training and withheld windows; define domain-backed acceptance thresholds. |
| Next | Calibration uncertainty and generalization | Evaluate parameter uncertainty, multiple seeds, contrasting basin regimes, and independent temporal periods; keep these claims separate from one successful deterministic run. |
| Later | Smaller orchestration modules | Extract job state, evidence assembly, calibration policy, and presentation behind existing tested contracts; preserve scientific outputs during refactoring. |
| Later | Operational usability | Add cancel/resume, bounded job budgets, incremental log tails, typed request bounds, and a clear distinction between a validated spec and an actually built model. |
| Later | Portable reporting and documentation | Offer dashboard assets that work offline; compress PROJECT current state and reconcile ROADMAP/architecture claims with implementation. |

Specific opportunities supporting these scopes:

- `output/plots/utils.py:27` drops missing paired observations; the split in
  `calibration/locked_benchmark.py:424` requires only 30 observed days per side.
  Those checks do not establish representative coverage of a multi-year period.
- `calibration/real_engine.py:337` already hashes the executable and three source
  modules for cache identity. Extend this to metric/parser/policy dependencies
  or a complete implementation fingerprint. The general validation cache still
  defaults to engine version `unknown`.
- The reviewed `cli.py`, `workflows/usgs_e2e.py`, `locked_benchmark.py`,
  `output/dashboard.py`, and `output/mass_trace.py` total 11,976 lines. Split
  responsibilities after protecting behavior with regression tests.
- The dashboard embeds data but loads Plotly and Leaflet remotely at
  `output/dashboard.py:414`; the current artifact therefore needs external
  assets for its interactive views.
- Use a hash-locked application/test environment while keeping appropriate
  library dependency ranges. See [pip's secure installation guidance](https://pip.pypa.io/en/stable/topics/secure-installs/).
  Replace the long-lived PyPI upload secret with
  [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/).

## Validation evidence

Supported test interpreter: `/opt/miniconda3/bin/python3`, Python 3.13.2.
The local `.venv` uses unsupported Python 3.14.4 and lacks pytest;
`.venv-repro` uses Python 3.11.14 and also lacks pytest. Neither was modified.

Existing focused suites: **233 passed** (184 + 49).

```bash
PYTHONPATH=src python3 -m pytest -q \
  tests/test_mcp_server.py tests/test_workflow_usgs_e2e.py \
  tests/test_evidence_schema.py tests/test_artifact_store.py \
  tests/test_artifact_hashing.py tests/test_locked_benchmark.py \
  tests/test_governance_gates.py \
  -m 'not slow and not network and not swat_binary'

PYTHONPATH=src python3 -m pytest -o addopts='' -q \
  tests/test_validation_runner.py tests/test_output_eval.py \
  tests/test_solver_wrapper.py tests/test_calibration_real_engine.py \
  -m 'not slow and not network and not swat_binary'
```

Additional isolated probes reproduced R1–R7 as described above. R4 used mocked
process launch; R3 used a real harmless short-lived child, reaped afterward.
R8–R9 are source/configuration findings. Passing existing tests does not
invalidate the probes: those boundary cases are missing from current coverage.

## Live follow-up

On 2026-09-16, the positive-control basin `01547700` was run through the full
research-grade workflow with the local SWAT+ engine. The run completed in about
39 minutes and passed all evidence gates; manifest pointers were all present and
the evidence JSON contained no non-finite numbers. The run produced 2,275
GridMET cache files before the pipeline completion event, and calibration
progress remained at `0/16` until sensitivity workers finished. These observations
confirm an observability/performance gap under real network and engine load.

The remediation adds bound-level sensitivity progress; records weather station
coordinates and provider client/version in future metadata; emits GridMET
start/station/retry/completion events into the canonical event stream; and
replaces the fixed 1,800-second connection timeout and three-attempt budget with
validated, configurable defaults of 300 seconds and two attempts. Provider
requests are deduplicated by native 1/24-degree GridMET cell while all SWAT+
station records are retained; the audited basin maps 25 stations to 10 cells,
avoiding 15 repeated downloads. Live one- and two-station probes confirmed the
progress stream and same-cell reuse against the real client. The full live artifact is
`/Users/mgalib/swatplus_runs/live_audit_20260916/01547700_2010_2019_full`.
No remote penetration test or installed-package CVE audit was performed.
