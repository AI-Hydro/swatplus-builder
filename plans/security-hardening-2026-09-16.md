# Security and reliability hardening — 2026-09-16

Authorized by the user's request to fix the nine review findings.

1. Reject invalid scientific numbers and verify evidence contents and hashes.
2. Make artifact records complete and immutable, constrain IDs/paths, and reuse only successful validations.
3. Give MCP launches exclusive directories and supervised, durable exit status.
4. Run offline contract tests before release and verify CI executables before execution.
5. Add focused regression tests, run affected suites and release checks, document compatibility limits and evidence.

Acceptance: the review's isolated failure cases become passing regressions; no
new scientific claims or metric-policy weakening; existing tests updated only
where their synthetic artifacts no longer meet the strengthened contract.
No release, publication, or live basin rerun is part of this change.

## Completion

Implemented all nine findings. Added 38 focused hardening regressions and
updated synthetic evidence fixtures to use valid seals and receipts. The clean
Python 3.13 installed-wheel contract suite passed 360 tests, with two documented
vendored-fixture skips and one excluded live-engine test. Source lint and diff
checks pass. Live basin validation and release remain separate follow-up work.
