from __future__ import annotations

from pathlib import Path

from swatplus_builder.sensitivity import (
    SensitivityAnalyzer,
    SensitivityBackend,
    SensitivityIndex,
    SensitivityRequest,
)


class FakeSensitivityBackend(SensitivityBackend):
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: SensitivityRequest) -> list[SensitivityIndex]:
        self.calls += 1
        _ = request
        return [
            SensitivityIndex(parameter="CN2", s1=0.4, st=0.6),
            SensitivityIndex(parameter="ESCO", s1=0.1, st=0.3),
            SensitivityIndex(parameter="ALPHA_BF", s1=0.2, st=0.2),
        ]


def _request(tmp_path: Path) -> SensitivityRequest:
    txt = tmp_path / "TxtInOut"
    txt.mkdir(parents=True, exist_ok=True)
    return SensitivityRequest(
        basin_id="usgs_01547700",
        txtinout_dir=txt,
        parameters=["CN2", "ESCO", "ALPHA_BF"],
        n_samples=256,
        observed_csv=None,
        artifacts_root=tmp_path / "artifacts",
    )


def test_sensitivity_bridge_writes_ranked_artifacts_and_cache(tmp_path: Path) -> None:
    backend = FakeSensitivityBackend()
    req = _request(tmp_path)
    analyzer = SensitivityAnalyzer(backend=backend)

    first = analyzer.run(req)
    second = analyzer.run(req)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert backend.calls == 1
    assert first.indices_csv.exists()
    assert first.summary_md.exists()
    assert first.ranked[0].parameter == "CN2"
