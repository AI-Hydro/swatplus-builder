"""Shared, standard-library artifact verification for execution and claim gates."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return payload


def verify_digest(path: Path, expected: object) -> None:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"Missing/invalid digest: {path.name}")
    if not path.is_file() or sha256_file(path) != expected:
        raise ValueError(f"Artifact integrity check failed: {path.name}")


def verify_benchmark_artifacts(path: Path) -> dict:
    lock = read_object(path)
    required = ("basin_id", "locked_at_utc", "sim_source_file", "input_configuration_sha256")
    if any(not isinstance(lock.get(key), str) or not lock[key] for key in required):
        raise ValueError("Incomplete benchmark lock")
    if not re.fullmatch(r"[0-9a-f]{64}", lock["input_configuration_sha256"]):
        raise ValueError("Invalid benchmark input seal")
    outlet = lock.get("outlet_gis_id")
    if type(outlet) is not int or outlet <= 0:
        raise ValueError("Invalid benchmark outlet")
    for name, key in (
        ("alignment.csv", "alignment_sha256"),
        ("metrics.json", "metrics_sha256"),
        ("outlet_provenance.json", "provenance_sha256"),
    ):
        verify_digest(path.parent / name, lock.get(key))
    provenance = read_object(path.parent / "outlet_provenance.json")
    if provenance.get("selected_outlet_gis_id") != outlet:
        raise ValueError("Benchmark outlet provenance mismatch")
    return lock


_DYNAMIC_OUTPUT_PREFIXES = (
    "basin_",
    "channel_",
    "chandeg_",
    "hru_",
    "hyd_",
    "lsunit_",
    "mgt_",
    "ru_",
    "soil_nut_",
    "aqu_",
    "outflow_",
    "flow_duration",
)


def input_configuration_fingerprint(txtinout_dir: Path | str) -> tuple[str, int]:
    """Hash static TxtInOut configuration while excluding engine output tables."""

    txt = Path(txtinout_dir).expanduser().resolve()
    if not txt.is_dir():
        raise ValueError("TxtInOut input directory missing")
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in txt.rglob("*"):
        if not path.is_file() or path.name == "engine_run_receipt.json":
            continue
        name = path.name.lower()
        if name.startswith("alignment_") and name.endswith(".csv"):
            continue
        if name.startswith(_DYNAMIC_OUTPUT_PREFIXES) and name.endswith((".txt", ".csv")):
            continue
        files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(txt).as_posix()):
        digest.update(path.relative_to(txt).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest(), len(files)
