"""Catalog of known ``swatplus_datasets.sqlite`` releases.

Each entry pins one upstream tag of ``swat-model/swatplus-editor`` to the
exact blob that shipped under ``release/build/swatplus_datasets.sqlite`` at
that tag, with a SHA-256 we've verified locally.

We use GitHub's ``raw.githubusercontent.com`` host because it is:

* stable per tag (immutable by git's content-addressed storage),
* public and free of auth headers (friendly to CI and ``urllib``),
* cachable by CDN for fast repeat downloads.

We do **not** use the Bitbucket downloads page that the official install
docs point at — as of 2026-04 it returns 404 for the bare-name URL.

To add a new release:

1. ``git ls-remote --tags https://github.com/swat-model/swatplus-editor``
2. ``curl -sL https://raw.githubusercontent.com/swat-model/swatplus-editor/<TAG>/release/build/swatplus_datasets.sqlite -o /tmp/ds.sqlite``
3. ``shasum -a 256 /tmp/ds.sqlite``  → copy hex into ``sha256`` below.
4. ``python3 -c 'import sqlite3; c=sqlite3.connect("/tmp/ds.sqlite"); print(c.execute("SELECT value FROM version").fetchone())'``
   → copy the ``value`` into ``datasets_version``.
5. Append a :class:`DatasetsRelease` entry and bump
   :data:`DEFAULT_DATASETS_VERSION`.

The catalog is intentionally tiny (one entry today) — we do not track
every editor tag; we track the ones that ship a datasets DB we have
regression tests against. See ADR-015 in ``docs/DECISIONS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class DatasetsRelease:
    """One pinned release of ``swatplus_datasets.sqlite``.

    Attributes:
        editor_tag: Upstream tag, e.g. ``"v3.2.2"``.
        datasets_version: ``version.value`` recorded *inside* the sqlite,
            e.g. ``"3.2.0"`` (these don't always match the editor tag —
            the datasets DB has its own lifecycle).
        url: HTTPS URL that serves the raw sqlite. Must support HEAD
            + ranged GET. No auth.
        sha256: Hex digest (64 lowercase chars).
        size: File size in bytes.
        release_date: ISO-8601 date stored in the sqlite's ``version``
            row. Kept here as a human-readable sanity check.
    """

    editor_tag: str
    datasets_version: str
    url: str
    sha256: str
    size: int
    release_date: str


DATASETS_RELEASES: Final[dict[str, DatasetsRelease]] = {
    "3.2.0": DatasetsRelease(
        editor_tag="v3.2.2",
        datasets_version="3.2.0",
        url=(
            "https://raw.githubusercontent.com/swat-model/swatplus-editor/"
            "v3.2.2/release/build/swatplus_datasets.sqlite"
        ),
        sha256="91843c2cbe773f919b373cfa49b9a293a6a2694bdd16484f98b2166aa58f72c1",
        size=1_105_920,
        release_date="2026-02-17",
    ),
}

DEFAULT_DATASETS_VERSION: Final[str] = "3.2.0"
"""Version key consumed by default. Bump in lockstep with ``DATASETS_RELEASES``
when vendoring a newer editor."""


def get_release(version: str | None = None) -> DatasetsRelease:
    """Look up a release by :attr:`DatasetsRelease.datasets_version`.

    Args:
        version: Optional; defaults to :data:`DEFAULT_DATASETS_VERSION`.

    Raises:
        KeyError: If ``version`` isn't pinned. The message lists known
            versions so the caller can pick one.
    """
    key = version or DEFAULT_DATASETS_VERSION
    try:
        return DATASETS_RELEASES[key]
    except KeyError as exc:
        known = ", ".join(sorted(DATASETS_RELEASES))
        raise KeyError(
            f"Unknown datasets version {key!r}. Known: {known}. "
            "To add a new one, see the top of ref/catalog.py."
        ) from exc
