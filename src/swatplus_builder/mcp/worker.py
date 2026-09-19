"""Detached workflow supervisor: reap the CLI and persist its exit status."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def write_result(out_dir: Path, payload: dict) -> None:
    temporary = out_dir / f".workflow_result-{os.getpid()}.tmp"
    temporary.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    temporary.replace(out_dir / "workflow_result.json")


def main() -> None:
    out_dir = Path(sys.argv[1]).resolve()
    state = json.loads((out_dir / "workflow_launch.json").read_text(encoding="utf-8"))
    try:
        result = subprocess.run(state["argv"], cwd=out_dir, stdin=subprocess.DEVNULL, check=False)
        payload = {"launch_id": state["launch_id"], "returncode": result.returncode}
    except Exception as exc:
        payload = {"launch_id": state["launch_id"], "returncode": -1, "error": str(exc)}
    write_result(out_dir, payload)


if __name__ == "__main__":
    main()
