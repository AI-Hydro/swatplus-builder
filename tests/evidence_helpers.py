"""Small sealed artifacts for tests that exercise claim policy, not SWAT+."""

import hashlib
import json
from pathlib import Path


def seal_engine(txt: Path) -> dict:
    from swatplus_builder.evidence.integrity import input_configuration_fingerprint

    (txt / "simulation.out").write_text("Execution successfully completed\n")
    executable = txt.parent / f"{txt.name}-fixture-engine"
    executable.write_bytes(b"fixture engine")
    input_sha256, input_file_count = input_configuration_fingerprint(txt)
    receipt = {
        "schema_version": "2.0",
        "run_id": "fixture-engine",
        "returncode": 0,
        "input_configuration_sha256": input_sha256,
        "input_configuration_file_count": input_file_count,
        "engine": {
            "path": str(executable.resolve()),
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        },
        "execution": {"threads": 1, "timeout_s": 3600.0, "timeout_enforced": True},
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in txt.iterdir()
            if p.name
            in {
                "simulation.out",
                "channel_sd_day.txt",
                "basin_sd_cha_day.txt",
                "channel_day.txt",
            }
        },
    }
    (txt / "engine_run_receipt.json").write_text(json.dumps(receipt))
    return {"engine_run_id": receipt["run_id"], "engine_returncode": 0}


def seal_benchmark(path: Path, outlet: int = 7, txt: Path | None = None) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "alignment.csv": "date,obs,sim\n2010-01-01,1,1\n2010-01-02,2,2\n",
        "metrics.json": json.dumps({"nse": 1.0, "kge": 1.0, "pbias": 0.0}),
        "outlet_provenance.json": json.dumps({"selected_outlet_gis_id": outlet}),
    }
    for name, content in files.items():
        (path.parent / name).write_text(content)
    payload = {
        "basin_id": "fixture",
        "locked_at_utc": "2026-09-16T00:00:00Z",
        "sim_source_file": "channel_sd_day.txt",
        "outlet_gis_id": outlet,
        "input_configuration_sha256": "a" * 64,
    }
    for name, key in (
        ("alignment.csv", "alignment_sha256"),
        ("metrics.json", "metrics_sha256"),
        ("outlet_provenance.json", "provenance_sha256"),
    ):
        payload[key] = hashlib.sha256((path.parent / name).read_bytes()).hexdigest()
    candidate = txt or path.parent.parent / "project" / "Scenarios" / "Default" / "TxtInOut"
    if candidate.is_dir():
        from swatplus_builder.evidence.integrity import input_configuration_fingerprint

        payload["input_configuration_sha256"], payload["input_configuration_file_count"] = (
            input_configuration_fingerprint(candidate)
        )
    path.write_text(json.dumps(payload))
    return str(path)


def seal_outlet(path: Path, outlet: int) -> dict:
    path.write_text(json.dumps({"selected_outlet_gis_id": outlet, "run_id": "fixture-workflow"}))
    return {
        "workflow_run_id": "fixture-workflow",
        "outlet_provenance_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
