from __future__ import annotations

import json
from pathlib import Path

import pytest

from swatplus_builder.errors import SwatBuilderInputError
from swatplus_builder.full_mode.crop_management import apply_source_backed_corn_soy_rotation


def _write_fixture(root: Path) -> None:
    (root / "plant.ini").write_text(
        "title\nheader\nagrl_comm 1 1\n    agrl n 0 0 0 0 0 10000\nfrsd_comm 1 1\n    frsd y 2 50000 0 0 1 10000\n"
    )
    (root / "management.sch").write_text(
        "title\nheader\nagrl_rot 0 1\n    pl_hv_summer1 agrl\n"
    )
    (root / "landuse.lum").write_text(
        "title\nheader\nagrl_lum null agrl_comm agrl_rot rc_strow_g cross_slope\n"
    )
    (root / "lum.dtl").write_text("name conds alts acts\npl_hv_summer2_corn_soyb 7 9 5\n")
    (root / "plants.plt").write_text("name type\ncorn warm_annual\nsoyb warm_annual\nagrl warm_annual\n")


def _evidence() -> dict[str, object]:
    return {
        "source": "USDA NASS 2011 Indiana Cropland Data Layer",
        "source_url": "https://example.test/cdl.tif",
        "source_sha256": "a" * 64,
        "year": 2011,
        "basin_id": "03349000",
        "corn_fraction_of_basin": 0.315,
        "soybean_fraction_of_basin": 0.339,
        "cultivated_fraction_of_basin": 0.708,
    }


def test_apply_corn_soy_rotation_requires_and_records_source_evidence(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    report_path = tmp_path / "report.json"

    report = apply_source_backed_corn_soy_rotation(
        tmp_path,
        evidence=_evidence(),
        report_path=report_path,
    )

    assert report["status"] == "applied"
    assert report["evidence"]["corn_soy_share_of_cultivated"] == pytest.approx(
        (0.315 + 0.339) / 0.708
    )
    plant_text = (tmp_path / "plant.ini").read_text()
    assert "agrl_comm                2         1" in plant_text
    assert "corn             n" in plant_text
    assert "soyb             n" in plant_text
    assert plant_text.count("5000.00000") == 2
    assert "10000.00000" not in plant_text.split("frsd_comm", 1)[0]
    assert "pl_hv_summer2_corn_soyb   corn   soyb" in (tmp_path / "management.sch").read_text()
    assert json.loads(report_path.read_text())["profile"] == "source_backed_corn_soy_rotation_v1"


def test_apply_corn_soy_rotation_rejects_weak_crop_composition(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    before = (tmp_path / "plant.ini").read_text()
    evidence = _evidence()
    evidence["corn_fraction_of_basin"] = 0.10
    evidence["soybean_fraction_of_basin"] = 0.10

    with pytest.raises(SwatBuilderInputError, match="does not support"):
        apply_source_backed_corn_soy_rotation(tmp_path, evidence=evidence)

    assert (tmp_path / "plant.ini").read_text() == before
