"""Install only a reviewed, digest-pinned Linux CI executable."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def verify(blob: bytes, expected: str) -> None:
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError(
            "Executable download/cache digest mismatch; review upstream before updating pins"
        )


def install(name: str, destination: Path) -> Path:
    pins = json.loads(Path(__file__).with_name("binary_pins.json").read_text())
    pin = pins[name]
    cache = Path.home() / ".cache" / "swatplus-builder-binaries" / pin["binary_sha256"]
    if cache.is_file():
        binary = cache.read_bytes()
    else:
        with urllib.request.urlopen(pin["url"], timeout=120) as response:  # noqa: S310 -- reviewed HTTPS pins
            archive = response.read()
        verify(archive, pin["archive_sha256"])
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            # Read exactly one pinned member; never extract arbitrary archive paths.
            binary = bundle.read(pin["member"])
    verify(binary, pin["binary_sha256"])
    for target in (cache, destination):
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            pending = Path(handle.name)
            handle.write(binary)
        try:
            pending.chmod(0o755)
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    install(sys.argv[1], Path(sys.argv[2]))
