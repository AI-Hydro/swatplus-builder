from __future__ import annotations

from pathlib import Path


def test_skill_md_exists_and_has_required_appendix_c_sections() -> None:
    skill = Path("SKILL.md")
    assert skill.exists(), "SKILL.md must exist at repository root"
    text = skill.read_text(encoding="utf-8")

    required_headers = [
        "## When to use this skill",
        "## Tool catalog",
        "## Parameter registry",
        "## Diagnostic heuristics",
        "## Basin taxonomy",
        "## Evaluation protocol",
        "## Example workflows",
        "## Common pitfalls",
    ]
    for header in required_headers:
        assert header in text


def test_skill_md_references_exact_mcp_tool_surface() -> None:
    text = Path("SKILL.md").read_text(encoding="utf-8")
    expected_tools = [
        "`build_project`",
        "`run_basin`",
        "`calibrate`",
        "`propose_parameters`",
        "`compare_runs`",
        "`query_artifacts`",
        "`diagnose_failure`",
        "`validate`",
        "`lock_benchmark`",
        "`locked_calibrate`",
        "`readiness_table`",
    ]
    for tool in expected_tools:
        assert tool in text


def test_skill_md_locked_benchmark_protocol_documented() -> None:
    """SKILL.md must document the locked-benchmark protocol rules."""
    text = Path("SKILL.md").read_text(encoding="utf-8")
    required_sections = [
        "## Locked-benchmark protocol rules",
        "## CLI commands",
        "lock_benchmark",
        "locked_calibrate",
        "readiness_table",
        "CN2 and ALPHA_BF only",
        "verify_calibration is mandatory",
    ]
    for item in required_sections:
        assert item in text, f"SKILL.md missing required content: {item!r}"


def test_skill_md_solver_wrapper_rule_documented() -> None:
    """SKILL.md must reference the solver wrapper guardrail."""
    text = Path("SKILL.md").read_text(encoding="utf-8")
    assert "run_solver_subprocess" in text or "solver" in text.lower()
