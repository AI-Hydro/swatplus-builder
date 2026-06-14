"""Typed pre-execution contract parser for agent-governed workflows.

Parses a natural-language task string via regex and returns a ``WorkflowContract``
dataclass (typed, serialisable).  This is a structured parser — not an LLM-side
negotiator; LLM interaction is the caller's responsibility.  ``negotiate_workflow``
is the parse entry-point; the CLI exposes it as ``swat workflow negotiate``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class WorkflowContract:
    status: str
    workflow_name: str
    usgs_id: str | None
    start: str | None
    end: str | None
    claim_tier: str
    contract_status: str
    accepted_by: str | None
    needs_input: list[str]
    policy_issues: list[str]


_RE_USGS = re.compile(r"\b(\d{8})\b")
_RE_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def negotiate_workflow(task: str) -> WorkflowContract:
    t = task.strip()
    dates = _RE_DATE.findall(t)
    usgs = _RE_USGS.search(t)
    tier = "diagnostic"
    lower = t.lower()
    if "publication" in lower:
        tier = "publication_grade"
    elif "research" in lower:
        tier = "research_grade"
    elif "exploratory" in lower:
        tier = "exploratory"

    needs: list[str] = []
    policy_issues: list[str] = []
    if usgs is None:
        needs.append("usgs_id")
    if len(dates) < 2:
        needs.append("start_end_dates")
    else:
        try:
            years = datetime.fromisoformat(dates[1]).year - datetime.fromisoformat(dates[0]).year + 1
            if tier in {"research_grade", "publication_grade"} and years < 10:
                policy_issues.append("research_claim_requires_>=10_year_window")
                needs.append("longer_time_window")
        except Exception:
            needs.append("start_end_dates")

    if needs:
        return WorkflowContract(
            status="needs_input",
            workflow_name="unresolved",
            usgs_id=usgs.group(1) if usgs else None,
            start=dates[0] if len(dates) > 0 else None,
            end=dates[1] if len(dates) > 1 else None,
            claim_tier=tier,
            contract_status="draft",
            accepted_by=None,
            needs_input=needs,
            policy_issues=policy_issues,
        )

    workflow_name = f"usgs_{usgs.group(1)}_{dates[0]}_{dates[1]}"
    return WorkflowContract(
        status="planned",
        workflow_name=workflow_name,
        usgs_id=usgs.group(1),
        start=dates[0],
        end=dates[1],
        claim_tier=tier,
        contract_status="draft",
        accepted_by=None,
        needs_input=[],
        policy_issues=[],
    )


def write_contract(contract: WorkflowContract, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "workflow_contract.json"
    m = out_dir / "WORKFLOW_CONTRACT.md"
    j.write_text(json.dumps(asdict(contract), indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Workflow Contract: {contract.workflow_name}",
        "",
        f"- status: `{contract.status}`",
        f"- usgs_id: `{contract.usgs_id}`",
        f"- start: `{contract.start}`",
        f"- end: `{contract.end}`",
        f"- claim_tier: `{contract.claim_tier}`",
        f"- contract_status: `{contract.contract_status}`",
        f"- accepted_by: `{contract.accepted_by}`",
    ]
    if contract.policy_issues:
        lines += ["", "## policy_issues"] + [f"- {x}" for x in contract.policy_issues]
    if contract.needs_input:
        lines += ["", "## needs_input"] + [f"- {x}" for x in contract.needs_input]
    m.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return j, m
