"""Reference-dataset bootstrap.

``swatplus-builder`` depends on a single external asset —
``swatplus_datasets.sqlite`` — that the SWAT+ Editor reads to populate the
project DB with default plants, soils, management schedules, etc.

This subpackage knows three things and nothing else:

1. **Where** the file lives (upstream, pinned by release tag). See
   :mod:`swatplus_builder.ref.catalog`.
2. **How** to fetch + verify + cache it. See
   :mod:`swatplus_builder.ref.bootstrap`.
3. **Whether** a local copy is already present for a given version. See
   :func:`swatplus_builder.ref.bootstrap.locate_datasets_db`.

This module does not import any heavy deps. It uses ``urllib`` + ``hashlib``
from the stdlib so ``swat init`` works from a vanilla pip install.
"""

from __future__ import annotations

from .bootstrap import (
    DatasetsRelease,
    ensure_datasets_db,
    fetch_datasets_db,
    locate_datasets_db,
)
from .catalog import DATASETS_RELEASES, DEFAULT_DATASETS_VERSION, get_release

__all__ = [
    "DATASETS_RELEASES",
    "DEFAULT_DATASETS_VERSION",
    "DatasetsRelease",
    "ensure_datasets_db",
    "fetch_datasets_db",
    "get_release",
    "locate_datasets_db",
]
