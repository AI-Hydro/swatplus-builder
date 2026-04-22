"""Download + verify + cache ``swatplus_datasets.sqlite``.

This is the backend for the ``swat init`` CLI command and for any Python
caller that wants to guarantee a datasets DB is on disk before running
:func:`swatplus_builder.editor.api.setup_project`.

Contract:

* :func:`locate_datasets_db` is **read-only** and never raises; it just
  returns ``None`` if nothing is present.
* :func:`fetch_datasets_db` always downloads (no cache hit), and always
  verifies the SHA-256. It fails closed — if the download is corrupted,
  the partial file is deleted.
* :func:`ensure_datasets_db` is the one agents should call. It resolves
  to the same path :func:`locate_datasets_db` would, downloading only
  when necessary.

Cache layout (under :attr:`Settings.reference_db_dir`,
default ``~/.swatplus_builder/reference_dbs``)::

    swatplus_datasets-3.2.0.sqlite      # actual DB, versioned filename
    swatplus_datasets.sqlite            # symlink → current default
    .swatplus_datasets-3.2.0.sqlite.sha256   # digest sentinel (optional)

The symlink lets the editor find the DB by a stable name, while the
versioned filename lets us keep multiple versions side by side (for
regression testing against older projects).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

from ..config import DEFAULT_SETTINGS, Settings
from ..errors import SwatBuilderExternalError, SwatBuilderInputError
from .catalog import DATASETS_RELEASES, DEFAULT_DATASETS_VERSION, DatasetsRelease, get_release

__all__ = [
    "DatasetsRelease",
    "cached_filename",
    "current_symlink",
    "ensure_datasets_db",
    "fetch_datasets_db",
    "locate_datasets_db",
    "verify_sha256",
]

_CHUNK_BYTES: Final[int] = 1 << 16
"""64 KB per read — big enough to be efficient, small enough to stream."""


def cached_filename(release: DatasetsRelease) -> str:
    """Return the versioned on-disk filename for a release.

    Example: ``swatplus_datasets-3.2.0.sqlite``.
    """
    return f"swatplus_datasets-{release.datasets_version}.sqlite"


def current_symlink(ref_dir: Path | str) -> Path:
    """Path of the stable-name symlink the editor is pointed at."""
    return Path(ref_dir).expanduser() / "swatplus_datasets.sqlite"


def locate_datasets_db(
    version: str | None = None,
    *,
    settings: Settings = DEFAULT_SETTINGS,
) -> Path | None:
    """Return the cached datasets DB for ``version``, or ``None``.

    Only returns a path if:

    1. The versioned file exists on disk under
       ``settings.reference_db_dir``, and
    2. Its SHA-256 matches the catalog pin (so a corrupt or truncated
       previous download doesn't masquerade as "already installed").

    A mismatched file is **not** deleted here (we don't overwrite user
    state silently). :func:`fetch_datasets_db` will overwrite on a
    subsequent fetch.

    Args:
        version: Datasets version key. Defaults to
            :data:`~swatplus_builder.ref.catalog.DEFAULT_DATASETS_VERSION`.
        settings: Used only for ``reference_db_dir``.

    Returns:
        Absolute path to the cached DB, or ``None`` if absent/corrupt.
    """
    try:
        release = get_release(version)
    except KeyError:
        return None

    ref_dir = Path(settings.reference_db_dir).expanduser()
    cached = ref_dir / cached_filename(release)
    if not cached.is_file():
        return None
    if cached.stat().st_size != release.size:
        return None
    try:
        if verify_sha256(cached) != release.sha256:
            return None
    except OSError:
        return None
    return cached.resolve()


def verify_sha256(path: Path | str) -> str:
    """Return the lowercase-hex SHA-256 of ``path``.

    Streams the file; never loads more than :data:`_CHUNK_BYTES` at a time.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:  # noqa: PTH123 (stdlib is fine here)
        while True:
            chunk = fh.read(_CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def fetch_datasets_db(
    version: str | None = None,
    *,
    settings: Settings = DEFAULT_SETTINGS,
    update_symlink: bool = True,
    timeout: float = 120.0,
) -> Path:
    """Download ``swatplus_datasets.sqlite`` for ``version``, verify,
    and place it into the reference cache.

    Always performs a network fetch — use :func:`ensure_datasets_db`
    when you want cache-first semantics.

    Args:
        version: Datasets version key. Defaults to
            :data:`~swatplus_builder.ref.catalog.DEFAULT_DATASETS_VERSION`.
        settings: Used only for ``reference_db_dir``.
        update_symlink: If ``True``, also point
            ``<ref_dir>/swatplus_datasets.sqlite`` at the new file so
            callers using the stable name pick it up. On Windows (where
            symlinks need admin), we fall back to a plain file copy.
        timeout: Seconds to wait on the HTTPS connection before giving up.

    Returns:
        Absolute path to the on-disk cached DB (the versioned filename,
        not the symlink).

    Raises:
        SwatBuilderInputError: ``version`` is not in the catalog.
        SwatBuilderExternalError: network failure or checksum mismatch.
    """
    try:
        release = get_release(version)
    except KeyError as exc:
        raise SwatBuilderInputError(str(exc), version=version) from exc

    ref_dir = Path(settings.reference_db_dir).expanduser()
    ref_dir.mkdir(parents=True, exist_ok=True)

    target = ref_dir / cached_filename(release)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".dl-", suffix=".sqlite.part", dir=str(ref_dir),
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        _stream_download(release.url, tmp_path, timeout=timeout)

        actual_size = tmp_path.stat().st_size
        if actual_size != release.size:
            raise SwatBuilderExternalError(
                "Downloaded datasets DB size mismatch.",
                url=release.url,
                expected_size=release.size,
                actual_size=actual_size,
            )
        actual_sha = verify_sha256(tmp_path)
        if actual_sha != release.sha256:
            raise SwatBuilderExternalError(
                "Downloaded datasets DB sha256 mismatch.",
                url=release.url,
                expected_sha256=release.sha256,
                actual_sha256=actual_sha,
            )
        tmp_path.replace(target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    if update_symlink:
        _update_current_symlink(ref_dir, target)

    return target.resolve()


def ensure_datasets_db(
    version: str | None = None,
    *,
    settings: Settings = DEFAULT_SETTINGS,
    update_symlink: bool = True,
    timeout: float = 120.0,
) -> Path:
    """Return a cached datasets DB path, downloading on cache miss.

    The 95% agent entry point. Example::

        from swatplus_builder.ref import ensure_datasets_db
        ds_db = ensure_datasets_db()
        setup_project(project_db, datasets_db=ds_db)

    Args:
        version: Datasets version key. Defaults to
            :data:`~swatplus_builder.ref.catalog.DEFAULT_DATASETS_VERSION`.
        settings: Override ``reference_db_dir``, etc.
        update_symlink: See :func:`fetch_datasets_db`.
        timeout: See :func:`fetch_datasets_db`.

    Returns:
        Absolute path to the cached DB on disk.

    Raises:
        SwatBuilderInputError: Unknown ``version``.
        SwatBuilderExternalError: Download or checksum failed and no
            valid cached copy was available.
    """
    cached = locate_datasets_db(version, settings=settings)
    if cached is not None:
        if update_symlink:
            _update_current_symlink(Path(settings.reference_db_dir).expanduser(), cached)
        return cached
    return fetch_datasets_db(
        version,
        settings=settings,
        update_symlink=update_symlink,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _stream_download(url: str, dest: Path, *, timeout: float) -> None:
    """Stream ``url`` → ``dest`` via urllib, chunked. Raises on HTTP errors."""
    req = urllib.request.Request(  # noqa: S310 (pinned https URL)
        url,
        headers={"User-Agent": "swatplus-builder/0.0.1 (+https://github.com/ai-hydro)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            if status != 200:
                raise SwatBuilderExternalError(
                    f"HTTP {status} fetching datasets DB.",
                    url=url,
                    status=status,
                )
            with open(dest, "wb") as out:  # noqa: PTH123
                while True:
                    chunk = resp.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    out.write(chunk)
    except urllib.error.URLError as exc:
        raise SwatBuilderExternalError(
            f"Network error fetching datasets DB: {exc}",
            url=url,
            reason=str(exc.reason) if hasattr(exc, "reason") else repr(exc),
        ) from exc


def _update_current_symlink(ref_dir: Path, target: Path) -> None:
    """Point ``<ref_dir>/swatplus_datasets.sqlite`` at ``target``.

    Tries a symlink first (the correct UNIX idiom); falls back to a
    file copy on Windows or any filesystem where symlinks aren't
    permitted. This runs post-download, on a path the caller controls,
    so failure is logged silently — the versioned file is still usable.
    """
    link = ref_dir / "swatplus_datasets.sqlite"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target.name)
        return
    except (OSError, NotImplementedError):
        pass
    try:
        shutil.copy2(target, link)
    except OSError:
        pass


# Re-export for static tools that walk __all__.
_ = (DATASETS_RELEASES, DEFAULT_DATASETS_VERSION)
