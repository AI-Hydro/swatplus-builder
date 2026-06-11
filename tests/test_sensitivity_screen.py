from __future__ import annotations

import json
from pathlib import Path

from swatplus_builder.calibration.sensitivity_screen import (
    screen_from_parameter_list,
    screen_from_sensitivity_json,
    write_screen_artifacts,
)
from swatplus_builder.params.governance import (
    FULL_MODE_CORE_PARAMETERS,
    FULL_MODE_EXTENDED_PARAMETERS,
    full_mode_extended_screen_rows,
    full_mode_screen_rows,
)


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


def test_screen_from_parameter_list_uses_full_mode_governance_defaults() -> None:
    result = screen_from_parameter_list(list(FULL_MODE_CORE_PARAMETERS), basin_id="governed")
    expected = {row["parameter"]: row["activity_class"] for row in full_mode_screen_rows()}
    actual = {row.parameter: row.activity_class for row in result.parameters}

    assert actual == expected
    assert actual["CN2"] == "active"
    assert actual["GW_DELAY"] == "dead"
    assert result.parameters[0].evidence["claim_tier_allowance"]
    assert "governance defaults" in result.warnings[0]


def test_extended_process_controls_have_governed_screen_rows() -> None:
    result = screen_from_parameter_list(list(FULL_MODE_EXTENDED_PARAMETERS), basin_id="process")
    expected = {row["parameter"]: row["activity_class"] for row in full_mode_extended_screen_rows()}
    actual = {row.parameter: row.activity_class for row in result.parameters}

    assert actual == expected
    assert actual == {
        "SFTMP": "weak",
        "SMTMP": "weak",
        "LAT_TTIME": "not_tested",
        "CN3_SWF": "not_tested",
        "CH_N2": "not_tested",
        "CH_K2": "not_tested",
    }
