#!/usr/bin/env python3
"""Install the WhiteboxTools binary for CI, with cache + version guard.

whitebox-python lazily downloads its pre-compiled binary from whiteboxgeo.com on
first use. In headless CI that download is unreliable, so this script does it
explicitly and deterministically:

1. If a cached binary exists (``~/.cache/whitebox_wbt/whitebox_tools``), restore it.
2. Otherwise call ``whitebox.download_wbt()`` — which fetches the version-compatible
   binary. We deliberately do NOT use the ``giswqs/whitebox-bin`` GitHub mirror:
   it is stuck at WBT v2.0.0 (2021), incompatible with whitebox-python 2.3.x.
3. As a last-resort fallback, curl the whiteboxgeo.com zip directly with retries.
4. Verify the binary runs and refuse the incompatible v2.0.0.

The binary is placed both at ``<pkg>/whitebox_tools`` and ``<pkg>/WBT/whitebox_tools``
(the two locations whitebox-python looks in) and persisted to the cache dir.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

WHITEBOXGEO_URL = "https://www.whiteboxgeo.com/WBT_Linux/WhiteboxTools_linux_amd64.zip"
CACHE_DIR = pathlib.Path.home() / ".cache" / "whitebox_wbt"


def _pkg_dir() -> pathlib.Path:
    import whitebox

    return pathlib.Path(whitebox.__file__).resolve().parent


def _install_binary(src: pathlib.Path, pkg_dir: pathlib.Path) -> pathlib.Path:
    """Copy ``src`` to both WBT lookup locations; return the primary exe path."""
    src.chmod(src.stat().st_mode | 0o111)
    primary = pkg_dir / "whitebox_tools"
    wbt_sub = pkg_dir / "WBT"
    wbt_sub.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, primary)
    shutil.copy2(src, wbt_sub / "whitebox_tools")
    primary.chmod(primary.stat().st_mode | 0o111)
    (wbt_sub / "whitebox_tools").chmod((wbt_sub / "whitebox_tools").stat().st_mode | 0o111)
    return primary


def _curl_fallback(pkg_dir: pathlib.Path) -> pathlib.Path | None:
    out = pathlib.Path(tempfile.mkdtemp()) / "wbt.zip"
    subprocess.run(
        ["curl", "--retry", "3", "--retry-delay", "5", "-fSL", "-o", str(out), WHITEBOXGEO_URL],
        check=True,
    )
    extract = pathlib.Path(tempfile.mkdtemp())
    with zipfile.ZipFile(out) as zf:
        zf.extractall(extract)
    for p in extract.rglob("whitebox_tools"):
        if p.is_file() and "WBT" in p.parts:
            return _install_binary(p, pkg_dir)
    return None


def main() -> int:
    pkg_dir = _pkg_dir()
    exe = pkg_dir / "whitebox_tools"
    cached = CACHE_DIR / "whitebox_tools"

    if cached.is_file():
        print("Restoring cached WBT binary.")
        _install_binary(cached, pkg_dir)
    else:
        print("Downloading WhiteboxTools via whitebox-python download_wbt() ...")
        import whitebox

        try:
            whitebox.download_wbt(verbose=True)
            if not exe.is_file():
                raise RuntimeError("download_wbt() did not produce a binary")
        except Exception as exc:  # noqa: BLE001 — fall back to direct curl
            print(f"download_wbt() failed ({exc}); trying direct curl ...", file=sys.stderr)
            if _curl_fallback(pkg_dir) is None:
                print("ERROR: could not obtain a WBT binary.", file=sys.stderr)
                return 1
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exe, cached)

    # Verify + version guard
    proc = subprocess.run([str(exe), "--version"], capture_output=True, text=True)
    version_line = (proc.stdout or proc.stderr).splitlines()[0] if (proc.stdout or proc.stderr) else ""
    print(f"WBT binary: {version_line}")
    if "v2.0.0" in version_line:
        print(
            "ERROR: WBT v2.0.0 is incompatible with whitebox-python 2.3.x "
            "(the giswqs backup mirror was used). Download from whiteboxgeo.com failed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
