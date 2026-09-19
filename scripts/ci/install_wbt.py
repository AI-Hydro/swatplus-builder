#!/usr/bin/env python3
"""Install pinned WhiteboxTools bytes before any execution in Linux CI."""

from __future__ import annotations

import subprocess
from pathlib import Path

from install_binary import install


def main() -> int:
    import whitebox

    package = Path(whitebox.__file__).resolve().parent
    executable = install("whitebox", package / "whitebox_tools")
    install("whitebox", package / "WBT" / "whitebox_tools")
    proc = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, check=True
    )
    print(proc.stdout or proc.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
