# Pipeline audit and decision-model readiness — September 2026

Scope: security, code correctness and scientific soundness of the headless
`swat workflow run` pipeline (v0.7.13 at commit `9397584`), what was fixed, and
what an auditable decision-data layer needs for the SWAT-S1 research program
(a learned decision model in the style of Jev/Laya that proposes the next
modelling action; the package keeps authority over claims).

## 1. What was actually run

| Check | Result |
|---|---|
| SWAT+ engine 61.0.2.61 built from `swat-model/swatplus` source (gfortran) | Built. Ran the upstream `Ames_sub1` reference watershed through the Builder's `run()` wrapper: success. |
| Full test suite, Python 3.11, all extras | 1,090 tests collected, 0 failures after fixes (before fixes: 5 collection errors and 1 failure) |
| Opt-in real-engine test (`SWATPLUS_EXE`) | Pass |
| Workflow, MCP, CLI and audit tests on Python 3.10 (the declared minimum) | Pass (one GIS test skipped for lack of geopandas in that environment) |
| Security lint (`ruff --select S`) + manual review of the MCP surface, subprocess runner, SQL building and file handling | Findings below |
| Metric formulas (NSE, KGE, log-KGE, PBIAS) vs independent NumPy formulas | Identical to about 1e-13 |
| Live gauge-to-evidence run | **Not run.** The session's network policy blocks USGS NWIS, 3DEP, GridMET and Planetary Computer, and the SWAT+ reference SQLite DBs are not redistributable. See §5. |

## 2. Findings fixed in this change

| ID | Severity | Area | Finding | Fix |
|---|---|---|---|---|
| F1 | High | Portability | The package, and so `swat workflow run`, failed to import on Python 3.10. `pyproject.toml` declares 3.10 support and CI lists it. Eight modules import `datetime.UTC`, which is 3.11+. CI never caught this because it only runs `test_smoke.py`. | 3.10-safe `UTC = timezone.utc` alias |
| F2 | High | Packaging | `pip install swatplus-builder[mcp]` now resolves `mcp` 2.x, which removed `FastMCP`, so the MCP server cannot start. | Pin `mcp>=1.2,<2` |
| F3 | Medium | Packaging | `requests` is imported by the SDA and SoilGrids soil clients on the real build path but was not declared. | Added to core deps |
| F4 | Medium | Governance | MCP `locked_calibrate` wrapped verification in `except Exception: pass`. A failed independent rerun returned the candidate's `best_nse` with null deltas, indistinguishable from "not requested". | `verification_status` (`verified`/`skipped`/`failed`) + error |
| F5 | Medium | Security | MCP `locked_calibrate` executed any caller-supplied `binary` path. An agent steered by prompt injection could run an arbitrary file. | Refused unless `SWATPLUS_BUILDER_MCP_ALLOW_BINARY_OVERRIDE=1` |
| F6 | Medium | Scientific hardening | Calibration candidates delete stale *channel* outputs before running, but not `basin_wb_aa.txt`, which the candidate water-balance gate reads. A candidate whose run did not rewrite it would be judged on the base run's water balance. | Deleted with the other outputs, plus a regression test |
| F7 | Low | Governance | An unrecognized `--claim-tier` value (e.g. `research`) passed the contract unvalidated and was echoed as the claim tier. | Falls back to `diagnostic` with a policy note |
| F8 | Low | UX | `swat health` checked only `$SWATPLUS_EXE`, so it reported an engine installed with `swat setup engine` as missing. The docs say no env var is needed. | Uses the runtime resolver |
| F9 | Low | Test integrity | The editor ORM schema-drift guard looked for `vendored/database/...`, which doesn't exist (the code is under `_swatplus_db`), so it was always skipped. | Path fixed; the guard passes |
| F10 | Low | Test integrity | `test_production_objective_audit_reports_current_complete_status` needs a git-ignored, locally generated report, so it fails on every clean checkout. | Skips with a reason when the artifact is absent |
| F11 | Auditability | Provenance | `events.jsonl` was deleted when a run directory was reused. It was not tamper-evident, and no workflow decision was recorded as a decision. | Hash-chained ledgers, decision records, sealed heads (§3) |

## 3. New audit layer (the data-prep foundation for SWAT-S1)

```
run_dir/
  events.jsonl        hash-chained stage trace (existing fields + seq/prev_sha256/sha256)
  decisions.jsonl     hash-chained decision + outcome records
  audit_history/      earlier attempts' ledgers (previously deleted)
  run_manifest.json   audit_ledgers: {events|decisions: head_sha256, records}
```

- **Environment fingerprint**, recorded as the first event after start: package version, git SHA, engine path, SHA-256 and revision, Python and key dependency versions.
- **Decision records** at three governed forks:
  - `claim_tier_contract`
  - `calibration_precheck`, with the calibration outcome, verification metrics and phase statuses attached as its outcome
  - `effective_claim_tier`

  Each record stores `state`, the full `options` set, `chosen`, `decided_by` (`package_rule` today; `agent`/`human`/`learned_model` are reserved) and the `policy` function. It can also store per-option `probabilities`, so a future Laya/Jev-style proposal can be logged next to the rule's decision.
- **Evidence sealing**: the final event hashes `evidence_summary.json`, `evidence_v1.json` and `EVIDENCE_SUMMARY.md` into the chain. Both ledger heads are then sealed into the manifest, so editing, reordering or truncating either ledger is detected.
- **CLI**:
  - `swat audit verify <run_dir> [--json]` exits 0 only when both chains verify against the sealed heads.
  - `swat audit episodes <run_dir>... [--out file.jsonl]` exports model-agnostic `DecisionEpisode` rows (schema `swatplus_builder.decision_episode/v1`). Each row carries `split_group = basin_id` for basin-disjoint splits and the ledger hashes it came from.

This is tamper-*evident*, not tamper-*proof*: someone who can rewrite a run directory can recompute every hash. To make the heads an external commitment, anchor them outside the operator's control, e.g. in a dataset release commit.

## 4. Recommended next fixes (not changed here)

| ID | Severity | Finding | Recommendation |
|---|---|---|---|
| R1 | Medium (scientific) | Benchmark lock pass 1 (`outlet_policy="auto"`) can switch outlets by **best NSE over the full observed record**, including the years later withheld for the transfer check. The model-structure choice therefore sees validation data. The volume diagnostics already flag an autodetected outlet when there are several terminals. | Select outlets from topology (the gauge-snapped channel), or score selection on the calibration window only. Record the selection window in `outlet_provenance.json`. |
| R2 | Medium (scientific) | `orchestrate.run_pipeline` passes `terminal_ids[0]` (the lowest GIS ID) as the requested outlet when there are several terminals, then relies on auto-selection. | Pass the delineation's snapped outlet ID explicitly. |
| R3 | Medium (process) | CI runs only `tests/test_smoke.py`. F1, F2, F3 and F9 would all have been caught by the offline suite, which takes minutes. The CI `ruff` step is also unpinned, and current ruff reports 7 pre-existing findings. | Run the full offline suite on 3.10–3.12 and pin `ruff`. |
| R4 | Low (security) | MCP tools accept arbitrary filesystem paths for reads and writes. For a local stdio server that is same-privilege, but an agent can be steered. | Optional workspace-root allowlist for MCP path arguments. |
| R5 | Low (auditability) | `build_readiness_table` silently skips unreadable or tampered lock and verification files. | Report them as `unreadable` rows. |
| R6 | Low (supply chain) | The vendored SWAT+ Editor has no committed `.VENDORED_COMMIT` pin. `get-pip.py` (2.6 MB) and platform build scripts ship inside the wheel. | Commit the pin and exclude non-runtime vendored files from the wheel. |
| R7 | Low | `scripts/audit_production_objective.py` has no argument parsing: `--help` runs the audit and writes to `docs/`. | Add `argparse`. |
| R8 | Info (engine) | Upstream SWAT+ CMake builds with `-ffpe-trap=...underflow` even in Release. That gfortran binary crashes with an FPE on the upstream reference watershed; it runs once the trap is removed. | Document supported binaries and flags. The engine SHA-256 and revision are now recorded per run. |
| R9 | Low | `evaluate_run` mutates the caller's `obs_series.index` in place and swallows metric exceptions, which leaves keys silently missing. | Copy the input and record the failure reason. |

Checks that **passed** review:
- Split-sample withholding in `calibrate_against_lock`: the validation window is excluded from the objective.
- Warm-up is prepended before `start`, so the 60/40 split applies to the evaluation window.
- Stale channel outputs are deleted before candidate runs.
- Engine success requires the `Execution successfully completed` banner.
- Unit conversions are correct: `channel_sd`/`basin_sd_cha` are m³/s, and `channel_day`/`basin_cha` are ha·m/day × 10⁴ / 86,400.
- SQL built for SDA queries escapes WKT. Map-unit keys (mukeys) come from rasters and are annotated `list[int]` but not coerced; `int()`-coercing them before building the `IN (...)` clause would make that guarantee explicit.

## 5. What the research says, and what to take from it for SWAT-S1

- **Laya** (open, Apache-2.0, ModernBERT-large, 421M parameters, typed Choice/Score/Noul outputs):
  - Zero-shot accuracy on its own benchmark is about 0.36, so domain fine-tuning is mandatory.
  - Raw expected calibration error (ECE) is high. Refitting one temperature per (question type, option count) on held-out data brings ECE down to about 0.08–0.11.
  - Out of distribution it *collapses while staying confident*: 0.000 accuracy at 0.952 confidence on an unseen language.
  - Context is 512–1,024 tokens, and it becomes unreliable above about 20 options.
  - Fine-tuning: about 30k questions takes 4–5 h on 2×T4 (free Kaggle tier).

  Take-aways:
  1. Keep v0 action sets ≤ 10 and hierarchical, as the vision doc already proposes.
  2. Serialize the evidence state within a token budget; the `DecisionEpisode.state_before` fields need a compact canonical form.
  3. Detect OOD cases **outside** the model's own confidence, e.g. basin-attribute distance to the training basins.
  4. Calibrate temperatures on held-out *basins*, never held-out rows.

  Sources: [Laya HF card](https://huggingface.co/convaiinnovations/laya-typed-decisions), [Laya repo](https://github.com/NandhaKishorM/laya), [benchmarks](https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md), [independent review](https://www.eesel.ai/blog/laya-ai-review).
- **Jev** (TypeSafe, closed): used in practice as a "smart if-statement", a router and an **evaluation judge over frozen agent traces**. The pattern is a deterministic check for facts (did the tool call succeed?) plus a typed judge for semantics (does the answer *claim* success?). This maps directly onto a `PROCESS_CREDIBILITY` judge over evidence bundles for zombie-calibration detection. Sources: [MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/), [Jev judge](https://blog.dailydoseofds.com/p/build-a-jev-judge), [LangSmith evals](https://www.langchain.com/blog/jev-is-now-available-in-langsmith-evals), [X: agent control layer](https://x.com/0xRicker/status/2101292455391809670).
- **CUA-S1-FORMS** (706K parameters, byte-level): 99.7% versus about 83.6% for a general LLM API on a sharply bounded task. That is evidence that a small specialist can win when the synthetic data generator and candidate set are designed well. Sources: [X announcement](https://x.com/trycua/status/2101014004927729737), [MindStudio](https://www.mindstudio.ai/blog/cua-s1-forms-gui-form-filling-model).
- **HydroAgent** (May 2026, CREST model):
  - Nine frontier LLM agents reach at best NSE 0.65–0.75, and none reaches the human expert except on one gauge.
  - The authors attribute the gap to *domain grounding*, not scale.
  - Their method is SFT of Qwen3-4B on 2,576 expert calibration trajectories plus GRPO with NSE as the verifiable simulator reward.

  For SWAT-S1 this is both the nearest baseline and the clearest warning. An NSE-only reward is exactly what produces zombie calibration, so the Builder's gated multi-objective outcome vector (validity + transfer + process) is the differentiator. Source: [arXiv 2605.17792](https://arxiv.org/abs/2605.17792).
- **Trace provenance**:
  - AgentLTL scores *procedural* compliance over agent traces as temporal-logic rules. Example: "no calibrated claim before a verified rerun". This can run directly on the new `events.jsonl`/`decisions.jsonl`, and the same score can serve as a dense reward.
  - NovaFabric and provmcp show the hash-chain → W3C PROV export path.

  Sources: [AgentLTL](https://arxiv.org/abs/2607.02599), [NovaFabric](https://arxiv.org/html/2609.12582), [provmcp](https://pypi.org/project/provmcp/), [survey](https://arxiv.org/html/2606.04990).

## 6. Suggested next steps

1. Land R1–R3 so the data the decision model learns from is itself scientifically clean.
2. Instrument the next layer of decisions inside `diagnostic_calibrator`: phase selection, parameter-family opening, and stop/continue. Record the real candidate set at each fork, so episodes carry the counterfactual structure the vision doc (§8.5) requires.
3. Add a compact, versioned state serializer (token-budgeted) and a `DecisionEpisode` → Laya JSON compiler that keeps the model-agnostic record canonical.
4. Build a fault-injection harness (vision doc §8.3) that reuses the locked-benchmark machinery, so injected-cause episodes carry the same audit trail.
5. Once network egress is allowed for USGS, 3DEP, GridMET and Planetary Computer (plus the reference DBs), run the 11-basin objective suite and archive `swat audit verify` output with each run.
