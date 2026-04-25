# swatplus_playbook

Evidence-backed decision skill for SWAT+ modeling workflows.

## Public API

- `recommend_next_action(context) -> PlaybookRecommendation`
- `append_playbook_evidence(playbook_path, entries) -> Path`

## Failure Modes

- If `metric_source != evaluate_run`, recommendation forces metric-authority restoration.
- If calibration history is flat (`unique_nse <= 1` for >=3 rows), recommendation routes to calibration-bridge investigation before search expansion.
- If routing segfault evidence is present with `routing_mode=1`, recommendation routes to channel geometry/runtime audit.

## Intended Integration

1. Build a `PlaybookContext` before proposing experiments.
2. Call `recommend_next_action` and honor `rejected_paths`/`preferred_paths`.
3. After each experiment, append evidence with `append_playbook_evidence`.
4. Never rewrite old entries; mark changes with status transitions (`validated`, `tentative`, `rejected`, `superseded`).
