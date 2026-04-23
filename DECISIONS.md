# Decisions Log

This is the canonical tracked decision log for roadmap execution.
Legacy ADR history exists in `docs/DECISIONS.md` (local working docs).

---

[2026-04-23] Canonical planning/progress docs are root-level
Context: Execution protocol for this roadmap requires authoritative `ROADMAP.md`, `PROGRESS.md`, and `DECISIONS.md` at repository root. Existing logs were primarily under `docs/`, and some were gitignored.
Decision: Treat root-level `ROADMAP.md`, `PROGRESS.md`, and `DECISIONS.md` as canonical for all future phase execution updates. Keep `docs/*` historical/local notes as reference until migration is complete.
Alternatives considered:
- Continue using `docs/PROGRESS.md` and `docs/DECISIONS.md` only — rejected because these are gitignored and not reliably reviewable.
- Fully rewrite and migrate all historical docs in one change — rejected as too disruptive for Phase 3A kickoff.
Consequences:
- New progress and non-obvious decisions are now tracked in committed root files.
- Historical context remains available in `docs/` during transition.
Status: Accepted

