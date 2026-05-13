"""Sensitivity screening helpers for calibration eligibility."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from ..params.registry import get_parameter


@dataclass
class ParameterScreen:
    parameter: str
    activity_class: str
    evidence: dict[str, Any]


@dataclass
class SensitivityScreenResult:
    basin_id: str | None
    parameters: list[ParameterScreen]
    warnings: list[str]


def _classify(effect_size: float | None, tested: bool) -> str:
    if not tested:
        return "not_tested"
    if effect_size is None:
        return "not_tested"
    v = abs(float(effect_size))
    if v < 1e-9:
        return "dead"
    if v < 0.01:
        return "weak"
    return "active"


def screen_from_sensitivity_json(sensitivity_json: Path, basin_id: str | None = None) -> SensitivityScreenResult:
    data = json.loads(Path(sensitivity_json).read_text(encoding="utf-8"))
    params_blob = data.get("parameters") or data.get("results") or {}
    out: list[ParameterScreen] = []
    warnings: list[str] = []
    if not isinstance(params_blob, dict):
        warnings.append("sensitivity JSON has no parameter map")
        return SensitivityScreenResult(basin_id=basin_id, parameters=[], warnings=warnings)

    for name, blob in params_blob.items():
        try:
            get_parameter(name)
        except Exception:
            continue
        if not isinstance(blob, dict):
            out.append(ParameterScreen(parameter=name, activity_class="not_tested", evidence={"raw": blob}))
            continue
        tested = bool(blob.get("tested", True))
        effect = blob.get("effect_size")
        if effect is None:
            # allow alternate keys
            for k in ("delta_nse", "delta", "sensitivity"):
                if k in blob:
                    effect = blob[k]
                    break
        out.append(
            ParameterScreen(
                parameter=name,
                activity_class=_classify(effect, tested=tested),
                evidence={"effect_size": effect, "tested": tested},
            )
        )

    return SensitivityScreenResult(
        basin_id=basin_id or data.get("basin_id"),
        parameters=sorted(out, key=lambda p: p.parameter),
        warnings=warnings,
    )


def screen_from_parameter_list(parameters: list[str], basin_id: str | None = None) -> SensitivityScreenResult:
    rows: list[ParameterScreen] = []
    for p in parameters:
        get_parameter(p)
        rows.append(ParameterScreen(parameter=p, activity_class="not_tested", evidence={}))
    return SensitivityScreenResult(basin_id=basin_id, parameters=rows, warnings=["No sensitivity JSON provided — all parameters marked not_tested"])


def write_screen_artifacts(screen: SensitivityScreenResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "sensitivity_screen.json"
    m = out_dir / "sensitivity_screen.md"
    payload = {
        "basin_id": screen.basin_id,
        "warnings": screen.warnings,
        "parameters": [asdict(p) for p in screen.parameters],
    }
    j.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = ["# Calibration Sensitivity Screen", "", f"- Basin: `{screen.basin_id or 'n/a'}`", "", "| Parameter | Activity |", "|---|---|"]
    for p in screen.parameters:
        lines.append(f"| `{p.parameter}` | `{p.activity_class}` |")
    if screen.warnings:
        lines += ["", "## Warnings"] + [f"- {w}" for w in screen.warnings]
    m.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return j, m
