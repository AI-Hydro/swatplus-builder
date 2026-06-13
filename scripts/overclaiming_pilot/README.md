# Overclaiming Pilot Harness (A1.1–A1.3)

Executes the pre-registered overclaiming experiment
(`docs/OVERCLAIMING_EXPERIMENT_PROTOCOL.md`,
`docs/experiments/overclaiming/OVERCLAIMING_PILOT_RUNBOOK.md`):

> Does contract-governed execution reduce unsupported scientific claims
> compared with raw agent CLI operation?

5 tasks × 2 conditions × 5 replicates × ≥1 model = **50 runs** in the pilot.

## Protocol amendment (documented)

The pre-registration named **human raters as primary**. This harness adds an
**LLM judge first-pass** (`llm_judge.py`) on every run, with humans rating a
≥20% stratified subset and `analyze.py` reporting judge–human **Cohen's κ**.
If κ < 0.7, the judge is discarded and we fall back to full human rating
(the analysis prints this warning automatically). The judge never silently
replaces human judgement — it triages and is itself validated.

## Files

| File | Role |
|---|---|
| `config.py` | Frozen task table, conditions, models, rep count. Do not edit after first transcript. |
| `runner.py` | Drives headless agent sessions via the `claude` CLI; writes per-run bundles. |
| `llm_judge.py` | First-pass 0–4 overclaiming scorer (independent session per run). |
| `analyze.py` | Pre-registered H1–H4, bootstrap CI, Mann-Whitney, Fisher, Cliff's δ, κ. |

## Outputs

```
docs/experiments/overclaiming/
  transcripts/{condition}/{run_id}.md       # blind-scorable final answers
  artifacts/{condition}/{run_id}/
    run_bundle.json                          # prompt, model, tool calls, answer, cost
    transcript.stream.jsonl                  # full stream-json transcript
  scoring/
    pilot_scoring_template.csv               # human rating sheet (blank)
    llm_judge_scores.csv                     # judge first-pass (generated)
  pilot_failure_log.md                       # auto-appended deviations
Research_article/data/overclaiming_pilot/
  run_index.json                             # run manifest
  pilot_analysis.json                        # analysis report (citable)
```

## Prerequisites

1. `claude` CLI installed and authenticated (`claude` is the SDK substrate).
2. `swat` CLI available on PATH (agents shell out to it).
3. SWAT+ engine binary present (rev 60.5.7) — see
   `docs/getting-started/bootstrap.md`.
4. Optional: `scipy` for parametric tests (`pip install scipy`). Without it,
   descriptive + bootstrap stats still run; parametric tests are skipped with
   a printed note.

## Run order

```bash
# 0. Preview the run matrix — executes nothing
python scripts/overclaiming_pilot/runner.py --dry-run

# 1. Smoke: 1 rep × 2 conditions × 5 tasks = 10 runs
python scripts/overclaiming_pilot/runner.py --smoke

# 2. If the pattern is visible, complete the pilot: 5 reps = 50 runs
python scripts/overclaiming_pilot/runner.py --full
#    add --with-weaker to include the weaker model tier (enables H4)

# 3. LLM judge first-pass over every transcript
python scripts/overclaiming_pilot/llm_judge.py

# 4. Humans rate a >=20% stratified subset into a copy of
#    scoring/pilot_scoring_template.csv (blind to condition).

# 5. Analysis — judge scores, plus judge-human kappa if a human CSV exists
python scripts/overclaiming_pilot/analyze.py \
    --scores docs/experiments/overclaiming/scoring/llm_judge_scores.csv
python scripts/overclaiming_pilot/analyze.py \
    --scores <human_subset.csv> \
    --compare-judge docs/experiments/overclaiming/scoring/llm_judge_scores.csv
```

## Protocol rules (DO NOT BREAK)

- **Prompts are frozen.** `runner.py` only substitutes `{task_text}`; it never
  edits `prompts/*.md`.
- **Do not tune prompts** after seeing any results.
- **Score blind to condition.** Human raters get the anonymized
  `transcripts/` answers; the LLM judge prompt never reveals the condition.
- **Record deviations** in `pilot_failure_log.md` — `runner.py` auto-appends
  timeouts and errors; log manual exclusions there too.
- **Null results are valid.** `analyze.py` reports them as nulls; the decision
  gate (expand / redesign / pivot) is in the runbook.

## Why the coding agent in *this* repo session cannot self-run the pilot

An agent that already knows the system internals cannot validly simulate
overclaiming behaviour. The pilot agents must be fresh sessions with only the
frozen prompt + CLI + docs — which is exactly what `runner.py` spawns via the
`claude` CLI (independent process, no project memory, restricted tools).
