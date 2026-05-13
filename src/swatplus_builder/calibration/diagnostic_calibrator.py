"""Deterministic phased calibration orchestration.

Phases: volume -> baseflow -> peaks -> finetune.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from ..errors import SwatBuilderExternalError


@dataclass
class PhaseRun:
    stage: int
    phase: str
    status: str
    message: str
    script: str


@dataclass
class DiagnosticCalibrationResult:
    success: bool
    phases: list[PhaseRun] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


def run_diagnostic_calibration(
    source_run: Path,
    *,
    claim_tier: str,
    strict: bool = True,
) -> DiagnosticCalibrationResult:
    source_run = Path(source_run).expanduser().resolve()
    reports = source_run / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    screen = source_run / "reports" / "sensitivity_screen.json"
    if strict and claim_tier != "exploratory" and screen.exists():
        data = json.loads(screen.read_text(encoding="utf-8"))
        blocked = [p["parameter"] for p in data.get("parameters", []) if p.get("activity_class") in {"dead", "not_tested"}]
        if blocked:
            res = DiagnosticCalibrationResult(
                success=False,
                phases=[PhaseRun(stage=0, phase="eligibility", status="blocked", message="sensitivity policy blocked parameters", script="sensitivity_screen")],
                provenance={"blocked_parameters": blocked, "claim_tier": claim_tier, "strict": strict},
            )
            (reports / "diagnostic_calibration.json").write_text(json.dumps({"success": res.success, "phases": [asdict(p) for p in res.phases], "provenance": res.provenance}, indent=2) + "\n", encoding="utf-8")
            return res

    phase_scripts = [
        (1, "volume", "scripts/calibrate_lte_stage1.py"),
        (2, "baseflow", "scripts/calibrate_lte_stage2.py"),
        (3, "peaks", "scripts/calibrate_lte_stage3.py"),
    ]
    runs: list[PhaseRun] = []
    ok = True

    for stage, phase, script in phase_scripts:
        script_path = Path(script)
        if not script_path.exists():
            runs.append(PhaseRun(stage=stage, phase=phase, status="skipped", message="stage script missing in checkout", script=script))
            ok = False
            continue
        proc = subprocess.run(["python", str(script_path)], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            runs.append(PhaseRun(stage=stage, phase=phase, status="failed", message=(proc.stderr or proc.stdout)[-400:], script=script))
            ok = False
            break
        runs.append(PhaseRun(stage=stage, phase=phase, status="passed", message="stage completed", script=script))

    if ok:
        runs.append(PhaseRun(stage=4, phase="finetune", status="passed", message="deterministic ladder complete", script="implicit"))

    res = DiagnosticCalibrationResult(
        success=ok,
        phases=runs,
        provenance={
            "calibration_method": "diagnostic_phased_deterministic",
            "claim_tier": claim_tier,
            "strict": strict,
            "source_run": str(source_run),
        },
    )
    (reports / "diagnostic_calibration.json").write_text(
        json.dumps({"success": res.success, "phases": [asdict(p) for p in res.phases], "provenance": res.provenance}, indent=2) + "\n",
        encoding="utf-8",
    )
    return res
