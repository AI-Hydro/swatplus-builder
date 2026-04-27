from __future__ import annotations

from datetime import date
from pathlib import Path

from swatplus_builder.artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)
from swatplus_builder.autoresearch import (
    LoopRequest,
    LoopStoppingCriteria,
    SurrogatePrediction,
    run_autoresearch_loop,
)


def _deterministic_evaluator(parameters: dict[str, float], iteration: int) -> dict[str, float]:
    score = (parameters["CN2"] / 200.0) - (parameters["ESCO"] / 5.0) + (parameters["SURLAG"] / 200.0)
    return {"nse": float(score), "kge": float(score - 0.1)}


def test_autoresearch_loop_is_deterministic_for_same_seed(tmp_path: Path) -> None:
    req1 = LoopRequest(
        basin_id="usgs_01547700",
        simulation_start="2015-01-01",
        simulation_end="2015-12-31",
        artifacts_root=str(tmp_path / "a1"),
        proposal_source="random",
        proposal_parameters=["CN2", "ESCO", "SURLAG"],
        seed=123,
        stopping=LoopStoppingCriteria(n_iterations=4),
    )
    req2 = req1.model_copy(update={"artifacts_root": str(tmp_path / "a2")})

    r1 = run_autoresearch_loop(req1, evaluator=_deterministic_evaluator, builder_git_sha="git-test")
    r2 = run_autoresearch_loop(req2, evaluator=_deterministic_evaluator, builder_git_sha="git-test")

    assert [it.parameters for it in r1.iterations] == [it.parameters for it in r2.iterations]
    assert [it.objective_value for it in r1.iterations] == [it.objective_value for it in r2.iterations]
    assert r1.best_objective == r2.best_objective


def test_autoresearch_loop_stops_on_objective_threshold(tmp_path: Path) -> None:
    def evaluator(parameters: dict[str, float], iteration: int) -> dict[str, float]:
        _ = parameters
        return {"nse": float(iteration) / 10.0}

    req = LoopRequest(
        basin_id="usgs_01547700",
        simulation_start="2015-01-01",
        simulation_end="2015-12-31",
        artifacts_root=str(tmp_path / "threshold"),
        stopping=LoopStoppingCriteria(n_iterations=20, objective_threshold=0.2),
    )
    result = run_autoresearch_loop(req, evaluator=evaluator, builder_git_sha="git-test")

    assert result.status == "objective_threshold"
    assert len(result.iterations) == 3
    assert result.best_objective >= 0.2


def test_autoresearch_loop_stops_on_convergence(tmp_path: Path) -> None:
    def evaluator(parameters: dict[str, float], iteration: int) -> dict[str, float]:
        _ = parameters
        _ = iteration
        return {"nse": 0.33}

    req = LoopRequest(
        basin_id="usgs_01013500",
        simulation_start="2015-01-01",
        simulation_end="2015-12-31",
        artifacts_root=str(tmp_path / "converged"),
        stopping=LoopStoppingCriteria(
            n_iterations=10,
            convergence_tolerance=1e-8,
            convergence_window=3,
        ),
    )
    result = run_autoresearch_loop(req, evaluator=evaluator, builder_git_sha="git-test")

    assert result.status == "converged"
    assert len(result.iterations) == 3


def test_autoresearch_loop_persists_parent_lineage(tmp_path: Path) -> None:
    req = LoopRequest(
        basin_id="usgs_01547700",
        simulation_start="2015-01-01",
        simulation_end="2015-12-31",
        artifacts_root=str(tmp_path / "lineage"),
        stopping=LoopStoppingCriteria(n_iterations=3),
    )
    result = run_autoresearch_loop(req, evaluator=_deterministic_evaluator, builder_git_sha="git-test")
    store = LocalArtifactStore(tmp_path / "lineage")

    first = store.read(result.iterations[0].content_hash)
    second = store.read(result.iterations[1].content_hash)
    third = store.read(result.iterations[2].content_hash)

    assert first.provenance is not None
    assert second.provenance is not None
    assert third.provenance is not None
    assert first.provenance.parent_run is None
    assert second.provenance.parent_run == result.iterations[0].content_hash
    assert third.provenance.parent_run == result.iterations[1].content_hash


def test_autoresearch_loop_routes_to_surrogate_when_uncertainty_low(tmp_path: Path) -> None:
    calls = {"real": 0}

    def evaluator(parameters: dict[str, float], iteration: int) -> dict[str, float]:
        _ = parameters
        _ = iteration
        calls["real"] += 1
        return {"nse": -1.0}

    def surrogate(parameters: dict[str, float], iteration: int) -> SurrogatePrediction:
        _ = parameters
        return SurrogatePrediction(objective=0.5 + iteration * 0.01, uncertainty=0.01)

    req = LoopRequest(
        basin_id="usgs_01547700",
        simulation_start="2015-01-01",
        simulation_end="2015-12-31",
        artifacts_root=str(tmp_path / "surrogate"),
        stopping=LoopStoppingCriteria(n_iterations=2),
        uncertainty_threshold=0.05,
    )
    result = run_autoresearch_loop(
        req,
        evaluator=evaluator,
        surrogate_predictor=surrogate,
        builder_git_sha="git-test",
    )

    assert calls["real"] == 0
    assert all(it.used_surrogate for it in result.iterations)


def test_autoresearch_loop_consults_playbook_for_flat_history(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "seeded")
    for idx in range(3):
        cfg = RunConfig.model_validate(
            {
                "basin_id": "usgs_01547700",
                "simulation_start": date(2015, 1, 1),
                "simulation_end": date(2015, 12, 31),
                "parameters": {"CN2": {"value": 70.0 + idx, "scope": "hru"}},
                "options": {"source": "seed"},
            }
        )
        content_hash = compute_content_hash(cfg, engine_version="test", builder_git_sha=f"git-seed-{idx}")
        store.write(
            ArtifactRecord(
                content_hash=content_hash,
                config=cfg,
                metadata=ArtifactMetadata(run_id=content_hash, timestamp_utc="2026-04-24T00:00:00Z"),
                metrics=ArtifactMetrics(nse=0.1, kge=0.05),
            )
        )

    req = LoopRequest(
        basin_id="usgs_01547700",
        simulation_start="2015-01-01",
        simulation_end="2015-12-31",
        artifacts_root=str(tmp_path / "seeded"),
        proposal_source="history",
        proposal_parameters=["CN2"],
        stopping=LoopStoppingCriteria(n_iterations=2),
    )

    def _cn2_only_eval(parameters: dict[str, float], _iteration: int) -> dict[str, float]:
        return {"nse": parameters["CN2"] / 100.0}

    result = run_autoresearch_loop(req, evaluator=_cn2_only_eval, builder_git_sha="git-test")

    assert all(it.proposal_source == "random" for it in result.iterations)


def test_autoresearch_loop_appends_playbook_evidence(tmp_path: Path) -> None:
    playbook = tmp_path / "playbook.md"
    req = LoopRequest(
        basin_id="usgs_01547700",
        simulation_start="2015-01-01",
        simulation_end="2015-12-31",
        artifacts_root=str(tmp_path / "runs"),
        proposal_parameters=["CN2", "ESCO", "SURLAG"],
        playbook_path=str(playbook),
        stopping=LoopStoppingCriteria(n_iterations=1),
    )
    _ = run_autoresearch_loop(req, evaluator=_deterministic_evaluator, builder_git_sha="git-test")

    text = playbook.read_text(encoding="utf-8")
    assert "Autoresearch iteration 0" in text
    assert "status: `tentative`" in text
