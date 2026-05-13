# SWAT+ Production Playbook

## Purpose
Operational recipes for running `swatplus-builder` in a scientifically defensible, agent-governed mode.

## Standard Run Contract
1. Use multi-year windows by default:
   - `start=2000-01-01`
   - `end=2019-12-31`
   - `warmup_years=2`
2. Use chronological split policy:
   - calibration: first 60% years
   - validation: last 40% years
3. Never claim research/publication grade without:
   - accepted/executed contract
   - accepted_by `user` or `policy`
   - >=10-year window

## Basin Regime Recipes
1. `exploratory`:
   - short windows or weak setup confidence
   - run build/diagnostics/sensitivity only
   - calibration optional
2. `diagnostic`:
   - full build, solver run, sensitivity screen, phased calibration attempt
   - classify blocker if calibration fails or is structurally blocked
3. `research_grade`:
   - only when contract policy allows
   - must pass physical/provenance gates
   - report both metrics and blocker-free evidence chain

## Failure Signatures
1. `contract_policy_blocked`:
   - tier/date/acceptance policy mismatch
2. `pipeline_failed`:
   - build/run stage failed
3. `low_skill_nonresearch`:
   - run completed but KGE/NSE below research-grade thresholds
4. `urban_or_structural_limited`:
   - basin-specific structure limitation (e.g., 01654000)

## Calibration Execution Policy
1. Always emit sensitivity and calibration provenance artifacts.
2. Treat `attempted_failed_or_blocked` as valid calibration usage evidence, not success evidence.
3. Do not upgrade claim tier from calibration attempt alone.

