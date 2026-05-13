from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.calibration.sensitivity_screen import screen_from_sensitivity_json, write_screen_artifacts


def test_screen_from_json_classifies_activity(tmp_path: Path):
    p = tmp_path / "audit.json"
    p.write_text(
        json.dumps(
            {
                "basin_id": "01654000",
                "parameters": {
                    "CN2": {"effect_size": 0.12, "tested": True},
                    "ALPHA_BF": {"effect_size": 0.0, "tested": True},
                    "SURLAG": {"tested": False},
                },
            }
        ),
        encoding="utf-8",
    )
    r = screen_from_sensitivity_json(p)
    m = {x.parameter: x.activity_class for x in r.parameters}
    assert m["CN2"] == "active"
    assert m["ALPHA_BF"] == "dead"
    assert m["SURLAG"] == "not_tested"


def test_write_screen_artifacts(tmp_path: Path):
    p = tmp_path / "audit.json"
    p.write_text(json.dumps({"parameters": {"CN2": {"effect_size": 0.1}}}), encoding="utf-8")
    r = screen_from_sensitivity_json(p, basin_id="X")
    j, m = write_screen_artifacts(r, tmp_path / "out")
    assert j.exists()
    assert m.exists()
