from __future__ import annotations

from pathlib import Path

from swatplus_builder.artifacts import (
    ArtifactMetadata,
    ArtifactMetrics,
    ArtifactProvenance,
    ArtifactQuery,
    ArtifactRecord,
    LocalArtifactStore,
    RunConfig,
    compute_content_hash,
)


def _record(basin_id: str, *, parent: str | None = None, nse: float | None = None) -> ArtifactRecord:
    cfg = RunConfig.model_validate(
        {
            "basin_id": basin_id,
            "bbox": [-77.0, 39.0, -76.5, 39.5],
            "simulation_start": "2010-01-01",
            "simulation_end": "2010-12-31",
            "parameters": {"CN2": {"value": 75.0, "scope": "hru"}},
            "options": {"routing_mode": "lte_stable"},
        }
    )
    h = compute_content_hash(cfg, engine_version="swatplus-61.0.6", builder_git_sha=f"git-{basin_id}")
    return ArtifactRecord(
        content_hash=h,
        config=cfg,
        metadata=ArtifactMetadata(
            run_id=h,
            timestamp_utc="2026-04-23T14:32:10Z",
            soil_mode="high_fidelity",
        ),
        metrics=ArtifactMetrics(nse=nse) if nse is not None else None,
        provenance=ArtifactProvenance(parent_run=parent) if parent is not None else None,
    )


def test_store_write_read_exists(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    rec = _record("usgs_01547700", nse=0.2)
    assert not store.exists(rec.content_hash)
    run_dir = store.write(rec)
    assert run_dir.exists()
    assert store.exists(rec.content_hash)
    got = store.read(rec.content_hash)
    assert got.config.basin_id == "usgs_01547700"
    assert got.metrics is not None
    assert got.metrics.nse == 0.2


def test_store_query_filters(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    r1 = _record("usgs_01547700", nse=0.2)
    r2 = _record("usgs_01013500", nse=-0.1)
    store.write(r1)
    store.write(r2)

    q1 = store.query(ArtifactQuery(basin_id="usgs_01547700"))
    assert len(q1) == 1
    assert q1[0].basin_id == "usgs_01547700"

    q2 = store.query(ArtifactQuery(nse_min=0.0))
    assert len(q2) == 1
    assert q2[0].content_hash == r1.content_hash


def test_store_lineage_walks_parent_chain(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    root = _record("root")
    child = _record("child", parent=root.content_hash)
    grandchild = _record("grandchild", parent=child.content_hash)
    store.write(root)
    store.write(child)
    store.write(grandchild)

    chain = store.lineage(grandchild.content_hash)
    assert chain == [grandchild.content_hash, child.content_hash, root.content_hash]

