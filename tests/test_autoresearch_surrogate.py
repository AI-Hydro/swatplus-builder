from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swatplus_builder.artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)
from swatplus_builder.autoresearch import (
    HoldoutEvaluationRequest,
    decide_routing_path,
    evaluate_surrogate_holdout,
    SurrogateTrainingRequest,
    predict_with_surrogate,
    train_surrogate_ensemble,
)
from swatplus_builder.errors import SwatBuilderInputError


def _seed_forward_like_artifacts(
    root: Path,
    *,
    n_rows: int,
    seed: int = 7,
    basins: list[str] | None = None,
) -> Path:
    rng = np.random.default_rng(seed)
    store = LocalArtifactStore(root)
    basin_ids = basins or ["usgs_01547700"]

    for i in range(n_rows):
        basin_id = basin_ids[i % len(basin_ids)]
        cn2 = float(rng.uniform(40.0, 95.0))
        esco = float(rng.uniform(0.1, 1.0))
        surlag = float(rng.uniform(0.2, 15.0))
        noise = float(rng.normal(0.0, 0.015))
        nse = 0.02 * cn2 - 0.6 * esco + 0.01 * surlag + noise

        cfg = RunConfig.model_validate(
            {
                "basin_id": basin_id,
                "simulation_start": date(2015, 1, 1),
                "simulation_end": date(2015, 12, 31),
                "parameters": {
                    "CN2": {"value": cn2, "scope": "hru"},
                    "ESCO": {"value": esco, "scope": "hru"},
                    "SURLAG": {"value": surlag, "scope": "global"},
                },
                "options": {"objective_mode": "real_engine_forward"},
            }
        )
        content_hash = compute_content_hash(
            cfg,
            engine_version="swatplus-61.0.6",
            builder_git_sha=f"git-test-{i}",
        )
        store.write(
            ArtifactRecord(
                content_hash=content_hash,
                config=cfg,
                metadata=ArtifactMetadata(
                    run_id=content_hash,
                    timestamp_utc="2026-04-24T00:00:00Z",
                    soil_mode="high_fidelity",
                ),
                metrics=ArtifactMetrics(nse=nse, kge=nse - 0.1),
            )
        )

        ts = pd.DataFrame(
            {
                "obs": [0.3, 0.25, 0.2, 0.15],
                "sim": [0.28, 0.24, 0.19, 0.14],
            },
            index=pd.to_datetime(["2015-01-01", "2015-01-02", "2015-01-03", "2015-01-04"]),
        )
        ts.to_csv(store.runs_dir / content_hash / "timeseries.csv")

    return root


def test_train_surrogate_ensemble_persists_artifacts(tmp_path: Path) -> None:
    artifacts_root = _seed_forward_like_artifacts(tmp_path / "forward", n_rows=30)
    req = SurrogateTrainingRequest(
        artifacts_root=artifacts_root,
        output_root=tmp_path / "out",
        target_metric="nse",
        ensemble_size=5,
        holdout_fraction=0.2,
        seed=17,
        min_rows=10,
    )

    ensemble = train_surrogate_ensemble(req)

    assert len(ensemble.members) == 5
    assert ensemble.train_rows > 0
    assert ensemble.holdout_rows > 0
    assert (ensemble.artifact_dir / "training_rows.csv").exists()
    assert (ensemble.artifact_dir / "model_cards.json").exists()
    assert (ensemble.artifact_dir / "training_summary.json").exists()


def test_train_surrogate_ensemble_is_reproducible_with_fixed_seed(tmp_path: Path) -> None:
    artifacts_root = _seed_forward_like_artifacts(tmp_path / "forward", n_rows=24, seed=99)
    req1 = SurrogateTrainingRequest(
        artifacts_root=artifacts_root,
        output_root=tmp_path / "o1",
        ensemble_size=4,
        seed=31,
        min_rows=8,
    )
    req2 = req1.model_copy(update={"output_root": tmp_path / "o2"})

    e1 = train_surrogate_ensemble(req1)
    e2 = train_surrogate_ensemble(req2)

    assert e1.ensemble_id == e2.ensemble_id
    c1 = [m.coefficients for m in e1.members]
    c2 = [m.coefficients for m in e2.members]
    assert c1 == c2
    assert [m.intercept for m in e1.members] == [m.intercept for m in e2.members]


def test_predict_with_surrogate_returns_nonzero_uncertainty(tmp_path: Path) -> None:
    artifacts_root = _seed_forward_like_artifacts(tmp_path / "forward", n_rows=40, seed=123)
    req = SurrogateTrainingRequest(
        artifacts_root=artifacts_root,
        output_root=tmp_path / "out",
        ensemble_size=5,
        holdout_fraction=0.25,
        seed=77,
        min_rows=12,
    )
    ensemble = train_surrogate_ensemble(req)

    pred = predict_with_surrogate(
        ensemble,
        {"CN2": 72.0, "ESCO": 0.45, "SURLAG": 4.0},
    )

    assert len(pred.member_predictions) == 5
    assert pred.objective_std > 0.0


def test_train_surrogate_ensemble_fails_when_rows_insufficient(tmp_path: Path) -> None:
    artifacts_root = _seed_forward_like_artifacts(tmp_path / "forward", n_rows=5)
    req = SurrogateTrainingRequest(
        artifacts_root=artifacts_root,
        output_root=tmp_path / "out",
        min_rows=10,
    )

    with pytest.raises(SwatBuilderInputError):
        train_surrogate_ensemble(req)


def test_decide_routing_path_threshold_behavior() -> None:
    low = decide_routing_path(uncertainty=0.01, threshold=0.05)
    high = decide_routing_path(uncertainty=0.2, threshold=0.05)

    assert low.path == "surrogate"
    assert high.path == "real_engine"


def test_evaluate_surrogate_holdout_writes_report(tmp_path: Path) -> None:
    artifacts_root = _seed_forward_like_artifacts(
        tmp_path / "forward",
        n_rows=60,
        seed=19,
        basins=["usgs_01547700", "usgs_01013500", "usgs_03339000"],
    )

    req = HoldoutEvaluationRequest(
        artifacts_root=artifacts_root,
        output_root=tmp_path / "out",
        holdout_basin_ids=["usgs_03339000"],
        target_metric="nse",
        ensemble_size=5,
        min_rows=10,
        seed=13,
        agreement_nse_threshold=0.0,
    )
    report = evaluate_surrogate_holdout(req)

    assert report.n_holdout_rows > 0
    assert report.n_train_rows > 0
    assert np.isfinite(report.agreement_nse)
    assert (report.report_dir / "summary.json").exists()
    assert (report.report_dir / "cases.csv").exists()
