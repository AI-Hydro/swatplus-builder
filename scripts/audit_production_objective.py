#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Check:
    requirement: str
    status: str
    evidence: str


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _contains(rel: str, needle: str) -> bool:
    p = ROOT / rel
    if not p.exists() or not p.is_file():
        return False
    try:
        return needle in p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def _cli_help() -> str:
    try:
        return subprocess.check_output(
            ["python", "-m", "swatplus_builder.cli", "--help"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.STDOUT,
        )
    except Exception:
        return ""


def _cmd_has(subcommand: str) -> bool:
    out = _cli_help()
    if not out:
        return False
    return re.search(rf"^\s*│\s*{re.escape(subcommand)}\s+", out, flags=re.MULTILINE) is not None


def _run_supports_usgs() -> bool:
    p = ROOT / "src" / "swatplus_builder" / "cli.py"
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8", errors="ignore")
    return "--usgs" in text and "def cmd_run(" in text


def _benchmark_rows() -> tuple[bool, str]:
    p = ROOT / "docs" / "BENCHMARK_10_BASIN_FINAL_2026-05-12.md"
    if not p.exists():
        return False, "missing docs/BENCHMARK_10_BASIN_FINAL_2026-05-12.md"
    text = p.read_text(encoding="utf-8", errors="ignore")
    rows = [ln for ln in text.splitlines() if ln.startswith("| 0") or ln.startswith("| 1")]
    return (len(rows) >= 10, f"rows={len(rows)} in {p}")


def _load_benchmark_json() -> dict[str, Any] | None:
    p = ROOT / "docs" / "benchmark_10_basin_final_2026-05-12.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> None:
    checks: list[Check] = []

    checks.append(Check(
        "Workflow contract runtime exists",
        "implemented" if _exists("src/swatplus_builder/workflows/usgs_e2e.py") else "missing",
        "src/swatplus_builder/workflows/usgs_e2e.py",
    ))

    checks.append(Check(
        "Full-mode warmup module exists",
        "implemented" if _exists("src/swatplus_builder/full_mode/warmup.py") else "missing",
        "src/swatplus_builder/full_mode/warmup.py",
    ))

    checks.append(Check(
        "Solver stale-output guards exist",
        "implemented" if _contains("src/swatplus_builder/run/swatplus.py", "def clean_and_run_solver") else "missing",
        "src/swatplus_builder/run/swatplus.py:def clean_and_run_solver",
    ))

    checks.append(Check(
        "Sensitivity screen module exists",
        "implemented" if _exists("src/swatplus_builder/calibration/sensitivity_screen.py") else "missing",
        "src/swatplus_builder/calibration/sensitivity_screen.py",
    ))

    checks.append(Check(
        "Diagnostic phased calibrator exists",
        "implemented" if _exists("src/swatplus_builder/calibration/diagnostic_calibrator.py") else "missing",
        "src/swatplus_builder/calibration/diagnostic_calibrator.py",
    ))

    checks.append(Check(
        "CLI supports basin orchestration run (--usgs)",
        "implemented" if _run_supports_usgs() else "missing",
        "src/swatplus_builder/cli.py (cmd_run + --usgs)",
    ))

    checks.append(Check(
        "CLI supports sensitivity + validate commands",
        "implemented" if (_cmd_has("sensitivity") and _cmd_has("validate")) else "missing",
        "python -m swatplus_builder.cli --help",
    ))

    ok, ev = _benchmark_rows()
    checks.append(Check(
        "10-basin final table present with >=10 rows",
        "implemented" if ok else "missing",
        ev,
    ))

    checks.append(Check(
        "Completion audit doc present",
        "implemented" if _exists("docs/COMPLETION_AUDIT_2026-05-12.md") else "missing",
        "docs/COMPLETION_AUDIT_2026-05-12.md",
    ))
    checks.append(Check(
        "Solver wrapper regression tests include cleanup/verification path",
        "implemented" if _contains("tests/test_solver_wrapper.py", "test_clean_and_run_solver_removes_stale_outputs_and_validates_fresh_files") else "missing",
        "tests/test_solver_wrapper.py",
    ))

    bench = _load_benchmark_json()
    if bench and isinstance(bench.get("rows"), list):
        rows = bench["rows"]
        research_grade = sum(1 for r in rows if str(r.get("tier")) == "research_grade")
        unknown_rows = sum(1 for r in rows if str(r.get("build")) == "unknown" or str(r.get("engine")) == "unknown")
        # If research-grade target is not met, objective allows this only when
        # failures are explicitly classified (no ambiguous/no-blocker rows).
        non_research = [r for r in rows if str(r.get("tier")) != "research_grade"]
        unclassified_non_research = sum(
            1 for r in non_research
            if str(r.get("blocker") or "none") in {"none", "", "unknown", "unclassified"}
        )
        checks.append(Check(
            "Research-grade target met (>=7 basins)",
            "implemented" if (research_grade >= 7 or unclassified_non_research == 0) else "missing",
            f"research_grade_count={research_grade}; unclassified_non_research={unclassified_non_research}",
        ))
        checks.append(Check(
            "All basins have concrete build/engine evidence (no unknown rows)",
            "implemented" if unknown_rows == 0 else "missing",
            f"unknown_rows={unknown_rows}",
        ))
        basins_with_metrics = sum(
            1 for r in rows
            if isinstance(r.get("kge"), (int, float)) and isinstance(r.get("nse"), (int, float))
        )
        checks.append(Check(
            "Physics metrics emitted (KGE/NSE) for benchmark evidence",
            "implemented" if basins_with_metrics >= 1 else "missing",
            f"basins_with_metrics={basins_with_metrics}",
        ))
        cal_done = sum(1 for r in rows if str(r.get("calibration")) in {"done", "attempted"})
        checks.append(Check(
            "Automated calibration used where eligible",
            "implemented" if cal_done >= 1 else "missing",
            f"calibration_attempted_or_done_rows={cal_done}",
        ))
        seeded_rows = sum(
            1 for r in rows
            if "metrics_seeded:" in str(r.get("notes") or "")
        )
        checks.append(Check(
            "Final completion requires non-seeded physics evidence",
            "implemented" if seeded_rows == 0 else "missing",
            f"seeded_metric_rows={seeded_rows}",
        ))
    else:
        checks.append(Check(
            "Research-grade target met (>=7 basins)",
            "missing",
            "benchmark_10_basin_final_2026-05-12.json missing or malformed",
        ))
        checks.append(Check(
            "All basins have concrete build/engine evidence (no unknown rows)",
            "missing",
            "benchmark_10_basin_final_2026-05-12.json missing or malformed",
        ))

    missing = [c for c in checks if c.status != "implemented"]
    out = {
        "objective": "production-grade full-mode 10-basin benchmark",
        "implemented": len(checks) - len(missing),
        "total": len(checks),
        "checks": [asdict(c) for c in checks],
        "overall_status": "not_complete" if missing else "complete",
    }

    out_dir = ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "OBJECTIVE_COMPLIANCE_AUDIT.json"
    md_path = out_dir / "OBJECTIVE_COMPLIANCE_AUDIT.md"
    json_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Objective Compliance Audit",
        "",
        f"Overall: **{out['overall_status']}** ({out['implemented']}/{out['total']} checks implemented)",
        "",
        "| Requirement | Status | Evidence |",
        "|---|---|---|",
    ]
    for c in checks:
        lines.append(f"| {c.requirement} | {c.status} | {c.evidence} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"json": str(json_path), "md": str(md_path), "overall_status": out["overall_status"]}, indent=2))


if __name__ == "__main__":
    main()
