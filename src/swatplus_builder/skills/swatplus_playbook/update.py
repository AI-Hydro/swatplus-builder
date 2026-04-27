"""Safe append-only updates for the SWAT+ modeling playbook."""

from __future__ import annotations

from pathlib import Path

from .schemas import PlaybookEvidenceEntry


def append_playbook_evidence(playbook_path: Path, entries: list[PlaybookEvidenceEntry]) -> Path:
    """Append evidence to the playbook without overwriting prior records.

    Each entry is appended as a dated markdown subsection. Existing content is preserved.

    Failure modes:
    - Raises ``ValueError`` if entries list is empty.
    - Raises ``OSError`` for filesystem write issues.
    """

    if not entries:
        raise ValueError("entries must contain at least one evidence item")

    path = playbook_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# SWAT+ Modeling Playbook\n\n", encoding="utf-8")

    with path.open("a", encoding="utf-8") as f:
        for item in entries:
            supersedes_note = (
                f"; supersedes: `{item.supersedes}`" if item.supersedes is not None else ""
            )
            f.write(f"### [{item.entry_date.isoformat()}] {item.title}\n")
            f.write(
                f"- status: `{item.status}`\n"
                f"- category: `{item.category}`\n"
                f"- source: `{item.source}`{supersedes_note}\n"
                f"- evidence: {item.evidence}\n"
                f"- consequence: {item.consequence}\n\n"
            )
    return path
