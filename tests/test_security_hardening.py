"""Regressions for the September 2026 security/reliability review."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import swatplus_builder
from swatplus_builder.artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
)
from swatplus_builder.governance.gates import (
    benchmark_lock_gate,
    fresh_engine_gate,
    landuse_fidelity_gate,
    outlet_provenance_gate,
    research_metric_gate,
)
from swatplus_builder.mcp import server
from swatplus_builder.validation.runner import BasinSpec, ExecutorResult, run_validation
from tests.evidence_helpers import seal_benchmark, seal_engine, seal_outlet


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, "NaN"])
@pytest.mark.parametrize("name", ["nse", "kge", "pbias"])
def test_nonfinite_metrics_cannot_authorize_claims(name, bad):
    metrics = {"nse": 0.8, "kge": 0.8, "pbias": 0.0, name: bad}
    assert not research_metric_gate({"metrics": metrics})["passed"]


@pytest.mark.parametrize(
    "name", ["landuse_class_retention_fraction", "landuse_vintage_mismatch_years"]
)
def test_nonfinite_landuse_cannot_authorize_claims(name):
    block = {
        "status": "evaluated",
        "hru_mode": "full_overlay",
        "landuse_class_retention_fraction": 1.0,
        "landuse_vintage_mismatch_years": 0.0,
        name: float("nan"),
    }
    assert not landuse_fidelity_gate({"landuse_fidelity": block})["passed"]


def record():
    return ArtifactRecord(
        content_hash="a" * 64,
        config=RunConfig(
            basin_id="fixture", simulation_start="2010-01-01", simulation_end="2019-12-31"
        ),
        metadata=ArtifactMetadata(timestamp_utc="2026-09-16T00:00:00Z"),
        metrics=ArtifactMetrics(nse=0.91),
    )


def test_artifact_replacement_cannot_mix_generations(tmp_path):
    store = LocalArtifactStore(tmp_path)
    old = record()
    store.write(old)
    with pytest.raises(FileExistsError):
        store.write(old.model_copy(update={"metrics": None}))
    assert store.read(old.content_hash).metrics.nse == 0.91


def test_partial_write_never_publishes(tmp_path):
    store = LocalArtifactStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.write(record(), timeseries_parquet=tmp_path / "missing")
    assert not store.exists(record().content_hash)
    assert not list(store.runs_dir.glob(".staging-*"))


def test_tampered_artifact_is_not_reused(tmp_path):
    store = LocalArtifactStore(tmp_path)
    path = store.write(record())
    (path / "metrics.json").write_text('{"nse":1.0}')
    assert not store.exists(record().content_hash)
    with pytest.raises(ValueError, match="integrity"):
        store.read(record().content_hash)


@pytest.mark.parametrize("identifier", ["../../escaped", "/tmp/escaped", "a" * 63, "g" * 64])
def test_artifact_identifiers_are_confined(tmp_path, identifier):
    store = LocalArtifactStore(tmp_path / "store")
    with pytest.raises(ValueError):
        store.write(record().model_copy(update={"content_hash": identifier}))
    with pytest.raises(ValueError):
        store.read(identifier)
    with pytest.raises(ValueError):
        store.exists(identifier)


def test_artifact_symlink_cannot_escape_root(tmp_path):
    store = LocalArtifactStore(tmp_path / "store")
    (store.runs_dir / record().content_hash).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        store.write(record())


def test_failed_validation_retries_and_never_counts_as_success(tmp_path):
    calls = []

    def fail(spec, run_dir):
        calls.append(spec.usgs_id)
        return ExecutorResult(status="failed", metrics={"nse": 0.9})

    kw = dict(
        basins=[
            BasinSpec(
                usgs_id="01547700", simulation_start="2010-01-01", simulation_end="2019-12-31"
            )
        ],
        artifacts_root=tmp_path / "artifacts",
        runs_root=tmp_path / "runs",
        executor=fail,
    )
    first, _ = run_validation(**kw)
    second, report_dir = run_validation(**kw)
    assert len(calls) == 2
    assert first[0].status == second[0].status == "failed"
    assert not second[0].cache_hit and not second[0].passed
    assert json.loads((report_dir / "benchmark_summary.json").read_text())["success_count"] == 0


def test_duplicate_launch_preserves_existing_log(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        lambda *args, **kw: calls.append(args) or SimpleNamespace(pid=123),
    )
    monkeypatch.setattr(server.threading.Thread, "start", lambda self: None)
    tools = {tool.name: tool for tool in server.create_mcp_server()._tool_manager.list_tools()}
    req = server.RunWorkflowRequest(usgs_id="01547700", out_dir=str(tmp_path))
    tools["run_workflow"].fn(req=req)
    log = tmp_path / "workflow_mcp.log"
    log.write_text("original evidence")
    with pytest.raises(FileExistsError):
        tools["run_workflow"].fn(req=req)
    assert len(calls) == 1 and log.read_text() == "original evidence"


@pytest.mark.parametrize("returncode,expected", [(0, "completed"), (3, "failed")])
def test_supervisor_persists_exit_and_status_ignores_reused_pid(tmp_path, returncode, expected):
    state = {
        "launch_id": "test-launch",
        "pid": os.getpid(),
        "log_path": str(tmp_path / "workflow_mcp.log"),
        "argv": [
            sys.executable,
            "-c",
            f"import json; print(json.dumps({{'success': True}}, indent=2)); raise SystemExit({returncode})",
        ],
    }
    (tmp_path / "workflow_launch.json").write_text(json.dumps(state))
    env = dict(os.environ, PYTHONPATH=str(Path(swatplus_builder.__file__).parent.parent))
    with (tmp_path / "workflow_mcp.log").open("wb") as log:
        subprocess.run(
            [sys.executable, "-m", "swatplus_builder.mcp.worker", str(tmp_path)],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            check=True,
            timeout=15,
        )
    result = json.loads((tmp_path / "workflow_result.json").read_text())
    assert result == {"launch_id": "test-launch", "returncode": returncode}
    tool = next(
        t
        for t in server.create_mcp_server()._tool_manager.list_tools()
        if t.name == "workflow_status"
    )
    status = tool.fn(req=server.WorkflowStatusRequest(out_dir=str(tmp_path)))
    assert status.status == expected


def test_benchmark_and_outlet_require_real_consistent_artifacts(tmp_path):
    lock = tmp_path / "benchmark" / "benchmark_lock.json"
    seal_benchmark(lock, 7)
    values = {"benchmark_lock_path": str(lock), "selected_outlet_gis_id": 7}
    assert benchmark_lock_gate(values)["passed"]
    values["selected_outlet_gis_id"] = 9
    assert not benchmark_lock_gate(values)["passed"]
    values["selected_outlet_gis_id"] = 7
    (lock.parent / "metrics.json").write_text("{}")
    assert not benchmark_lock_gate(values)["passed"]
    outlet = tmp_path / "outlet.json"
    fields = seal_outlet(outlet, 7)
    values.update(fields, outlet_provenance_path=str(outlet))
    assert outlet_provenance_gate(values)["passed"]
    values["workflow_run_id"] = "different-run"
    assert not outlet_provenance_gate(values)["passed"]
    outlet.write_text("{}")
    assert not outlet_provenance_gate(values)["passed"]


def test_freshness_checks_execution_identity_and_output_bytes(tmp_path):
    source = tmp_path / "channel_sd_day.txt"
    source.write_text("fresh output")
    values = {"fresh_engine_run": True, "txtinout_dir": str(tmp_path), **seal_engine(tmp_path)}
    assert fresh_engine_gate(values)["passed"]
    values["engine_run_id"] = "previous-run"
    assert not fresh_engine_gate(values)["passed"]
    values["engine_run_id"] = "fixture-engine"
    source.write_text("replaced output")
    assert not fresh_engine_gate(values)["passed"]


def test_binary_installer_rejects_modified_archive_and_cache(tmp_path, monkeypatch):
    import io
    import zipfile

    source = Path(__file__).parents[1] / "scripts" / "ci" / "install_binary.py"
    spec = importlib.util.spec_from_file_location("review_binary_installer", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("engine", b"reviewed executable")
        z.writestr("../../escape", b"must never extract")
    pin = {
        "url": "https://fixture.invalid",
        "member": "engine",
        "archive_sha256": hashlib.sha256(archive.getvalue()).hexdigest(),
        "binary_sha256": hashlib.sha256(b"reviewed executable").hexdigest(),
    }
    (tmp_path / "binary_pins.json").write_text(json.dumps({"fixture": pin}))
    monkeypatch.setattr(module, "__file__", str(tmp_path / "installer.py"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"modified"))
    destination = tmp_path / "bin" / "engine"
    with pytest.raises(ValueError, match="digest mismatch"):
        module.install("fixture", destination)
    assert not destination.exists()
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(archive.getvalue())
    )
    module.install("fixture", destination)
    assert destination.read_bytes() == b"reviewed executable"
    cache = tmp_path / ".cache" / "swatplus-builder-binaries" / pin["binary_sha256"]
    cache.write_bytes(b"modified")
    with pytest.raises(ValueError, match="digest mismatch"):
        module.install("fixture", destination)
    assert not (tmp_path / "escape").exists()


def test_solver_receipt_is_removed_before_failed_retry(tmp_path, monkeypatch):
    from swatplus_builder.errors import SwatBuilderExternalError
    from swatplus_builder.run import swatplus

    executable = tmp_path / "fake-engine"
    executable.touch()

    def complete(**kwargs):
        (tmp_path / "simulation.out").write_text("Execution successfully completed")
        (tmp_path / "channel_sd_day.txt").write_text("new output")
        return 0, "", ""

    monkeypatch.setattr(swatplus, "run_solver_subprocess", complete)
    swatplus.clean_and_run_solver(tmp_path, exe=executable)
    receipt = json.loads((tmp_path / "engine_run_receipt.json").read_text())
    assert fresh_engine_gate(
        {
            "fresh_engine_run": True,
            "engine_returncode": 0,
            "engine_run_id": receipt["run_id"],
            "txtinout_dir": str(tmp_path),
        }
    )["passed"]
    monkeypatch.setattr(swatplus, "run_solver_subprocess", lambda **kw: (1, "", "failed"))
    with pytest.raises(SwatBuilderExternalError):
        swatplus.clean_and_run_solver(tmp_path, exe=executable)
    assert not (tmp_path / "engine_run_receipt.json").exists()


def test_post_execution_input_mutation_invalidates_receipt(tmp_path, monkeypatch):
    from swatplus_builder.run import swatplus

    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    (txt / "file.cio").write_text("original input")
    executable = tmp_path / "fake-engine"
    executable.write_bytes(b"engine")

    def complete(**kwargs):
        (txt / "simulation.out").write_text("Execution successfully completed")
        (txt / "channel_sd_day.txt").write_text("new output")
        return 0, "", ""

    monkeypatch.setattr(swatplus, "run_solver_subprocess", complete)
    swatplus.clean_and_run_solver(txt, exe=executable)
    receipt = json.loads((txt / "engine_run_receipt.json").read_text())
    values = {
        "fresh_engine_run": True,
        "engine_returncode": 0,
        "engine_run_id": receipt["run_id"],
        "txtinout_dir": str(txt),
    }
    assert fresh_engine_gate(values)["passed"]
    (txt / "file.cio").write_text("mutated after execution")
    result = fresh_engine_gate(values)
    assert result["passed"] is False
    assert "inputs differ" in result["reason"]


def test_execution_receipt_is_not_a_static_model_input(tmp_path):
    from swatplus_builder.calibration.locked_benchmark import _input_configuration_fingerprint
    from swatplus_builder.calibration.real_engine import _copy_fresh_txtinout

    source = tmp_path / "source"
    source.mkdir()
    (source / "file.cio").write_text("fixed inputs")
    original = _input_configuration_fingerprint(source)
    (source / "engine_run_receipt.json").write_text('{"run_id":"old"}')
    assert _input_configuration_fingerprint(source) == original
    target = tmp_path / "candidate"
    _copy_fresh_txtinout(source, target)
    assert not (target / "engine_run_receipt.json").exists()


def test_concurrent_artifact_publishers_never_mix_payloads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = LocalArtifactStore(tmp_path)

    def publish(nse):
        try:
            store.write(record().model_copy(update={"metrics": ArtifactMetrics(nse=nse)}))
            return nse
        except FileExistsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [0.1, 0.9]))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert store.read(record().content_hash).metrics.nse == winners[0]


def test_release_requires_offline_contract_workflow():
    root = Path(__file__).parents[1]
    release = (root / ".github/workflows/publish.yml").read_text()
    workflow = (root / ".github/workflows/offline-contracts.yml").read_text()
    assert "needs: [build, offline-contracts]" in release
    assert "uses: ./.github/workflows/offline-contracts.yml" in release
    for filename in (
        "test_security_hardening.py",
        "test_governance_gates.py",
        "test_mcp_server.py",
        "test_locked_benchmark.py",
    ):
        assert filename in workflow
    assert "working-directory: /tmp" in workflow


def test_direct_solver_used_by_calibration_seals_fresh_outputs(tmp_path, monkeypatch):
    from swatplus_builder.run import swatplus

    executable = tmp_path / "fake-engine"
    executable.touch()
    (tmp_path / "file.cio").write_text("fixture")
    source = tmp_path / "channel_sd_day.txt"
    source.write_text("stale")
    (tmp_path / "engine_run_receipt.json").write_text('{"run_id":"stale"}')

    def execute(*args, **kwargs):
        assert not source.exists()
        assert not (tmp_path / "engine_run_receipt.json").exists()
        source.write_text("fresh")
        (tmp_path / "simulation.out").write_text("Execution successfully completed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(swatplus.subprocess, "run", execute)
    assert swatplus.run(tmp_path, binary=executable).success
    receipt = json.loads((tmp_path / "engine_run_receipt.json").read_text())
    assert fresh_engine_gate(
        {
            "fresh_engine_run": True,
            "engine_returncode": 0,
            "engine_run_id": receipt["run_id"],
            "txtinout_dir": str(tmp_path),
        }
    )["passed"]


def test_changed_model_inputs_fail_benchmark_claim_gate(tmp_path):
    txt = tmp_path / "model"
    txt.mkdir()
    model_input = txt / "file.cio"
    model_input.write_text("original model configuration")
    lock = tmp_path / "benchmark" / "benchmark_lock.json"
    seal_benchmark(lock, txt=txt)
    values = {
        "benchmark_lock_path": str(lock),
        "txtinout_dir": str(txt),
        "selected_outlet_gis_id": 7,
    }
    assert benchmark_lock_gate(values)["passed"]
    model_input.write_text("different model configuration")
    assert not benchmark_lock_gate(values)["passed"]
