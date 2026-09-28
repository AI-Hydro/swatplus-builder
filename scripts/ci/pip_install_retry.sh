#!/usr/bin/env bash
# pip_install_retry.sh — retry `pip install` a few times with backoff.
#
# CI dependency installs occasionally fail against a transient PyPI/CDN
# hiccup rather than a real incompatibility (observed: the same `pip install`
# with the same lockfile-free version pins succeeds locally immediately
# after a CI run fails with "Could not find a version that satisfies ...
# (from versions: none)" for a package whose index metadata is otherwise
# fine). Retrying with backoff absorbs that class of failure without masking
# a real, reproducible dependency conflict — if all attempts fail, the exit
# code and pip's own error output are preserved so a genuine conflict still
# fails the build loudly.
#
# Usage: scripts/ci/pip_install_retry.sh <args to pass to 'pip install'>
#   scripts/ci/pip_install_retry.sh -e ".[dev]"

set -euo pipefail

max_attempts=3
delay_seconds=15

for attempt in $(seq 1 "$max_attempts"); do
  if pip install "$@"; then
    exit 0
  fi
  if [ "$attempt" -lt "$max_attempts" ]; then
    echo "pip install failed (attempt $attempt/$max_attempts); retrying in ${delay_seconds}s..." >&2
    sleep "$delay_seconds"
  fi
done

echo "pip install failed after $max_attempts attempts." >&2
exit 1
