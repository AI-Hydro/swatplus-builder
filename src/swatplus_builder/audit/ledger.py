"""Tamper-evident, append-only audit ledgers for workflow runs.

Every record appended through :class:`HashChainedLedger` carries

* ``seq`` — 0-based position in the ledger,
* ``prev_sha256`` — the ``sha256`` of the previous record (``GENESIS_SHA256``
  for the first one), and
* ``sha256`` — SHA-256 of the record's canonical JSON *without* the
  ``sha256`` field itself.

Editing, deleting, reordering or inserting a record therefore breaks the
chain, and :func:`verify_ledger` reports the first broken ``seq``. Truncating
the tail cannot be detected from the file alone, which is why the workflow
also seals the final ``sha256`` (the ledger *head*) into ``run_manifest.json``
and ``evidence_summary.json``; :func:`verify_ledger` checks it when given
``expected_head``.

The chain is tamper-*evident*, not tamper-*proof*: anyone who can rewrite the
file can recompute every hash. Anchoring the head somewhere the operator does
not control (a git commit, a dataset release, a signed timestamp) is what
turns it into an external commitment.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GENESIS_SHA256 = "0" * 64
LEDGER_SCHEMA_VERSION = 1
_CHAIN_FIELDS = ("seq", "prev_sha256", "sha256")


def canonical_json(obj: Any) -> str:
    """Serialize ``obj`` deterministically (sorted keys, compact, UTF-8)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def record_sha256(record: Mapping[str, Any]) -> str:
    """Hash a ledger record, excluding its own ``sha256`` field."""
    body = {k: v for k, v in record.items() if k != "sha256"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    """Round-trip through JSON so the stored record is exactly what was hashed."""
    return json.loads(canonical_json(value))


class HashChainedLedger:
    """Append-only JSONL file whose records form a SHA-256 hash chain.

    Opening an existing ledger resumes the chain from its last record, so
    several writers in sequence (e.g. a workflow and a later export step) can
    extend the same file. The ledger is not safe for concurrent writers.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._seq = 0
        self._head = GENESIS_SHA256
        if self.path.exists():
            last: dict[str, Any] | None = None
            for rec in iter_records(self.path):
                last = rec
            if last is not None:
                if "sha256" not in last or "seq" not in last:
                    raise ValueError(
                        f"{self.path} is not a hash-chained ledger (last record has no seq/sha256)."
                    )
                self._seq = int(last["seq"]) + 1
                self._head = str(last["sha256"])

    @property
    def head(self) -> str:
        """``sha256`` of the most recent record (``GENESIS_SHA256`` when empty)."""
        return self._head

    @property
    def count(self) -> int:
        return self._seq

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Append ``record`` and return it with its chain fields filled in."""
        clash = [k for k in _CHAIN_FIELDS if k in record]
        if clash:
            raise ValueError(f"ledger records must not set reserved fields: {clash}")
        entry: dict[str, Any] = _normalize(dict(record))
        entry["seq"] = self._seq
        entry["prev_sha256"] = self._head
        entry["sha256"] = record_sha256(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._seq += 1
        self._head = entry["sha256"]
        return entry


def iter_records(path: Path | str) -> Iterator[dict[str, Any]]:
    """Yield the JSON records of a JSONL ledger, skipping blank lines."""
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


@dataclass
class LedgerVerification:
    path: str
    ok: bool
    record_count: int = 0
    head_sha256: str = GENESIS_SHA256
    first_bad_seq: int | None = None
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "record_count": self.record_count,
            "head_sha256": self.head_sha256,
            "first_bad_seq": self.first_bad_seq,
            "problems": list(self.problems),
        }


def verify_ledger(path: Path | str, *, expected_head: str | None = None) -> LedgerVerification:
    """Check every link of a hash-chained ledger.

    Args:
        path: Ledger JSONL file.
        expected_head: Optional sealed head hash (from ``run_manifest.json``);
            when given, a ledger whose final record differs — including one
            truncated after sealing — fails verification.
    """
    p = Path(path)
    result = LedgerVerification(path=str(p), ok=True)
    if not p.exists():
        result.ok = False
        result.problems.append("ledger file does not exist")
        return result

    prev = GENESIS_SHA256
    try:
        records = list(iter_records(p))
    except json.JSONDecodeError as exc:
        result.ok = False
        result.problems.append(f"unparseable JSON line: {exc}")
        return result

    for idx, rec in enumerate(records):
        problem: str | None = None
        if rec.get("seq") != idx:
            problem = f"seq {rec.get('seq')!r} at position {idx} (records reordered, inserted or removed)"
        elif rec.get("prev_sha256") != prev:
            problem = "prev_sha256 does not match the previous record"
        elif rec.get("sha256") != record_sha256(rec):
            problem = "sha256 does not match record content (record edited)"
        if problem is not None:
            result.ok = False
            result.first_bad_seq = idx
            result.problems.append(f"seq {idx}: {problem}")
            break
        prev = str(rec["sha256"])

    result.record_count = len(records)
    result.head_sha256 = prev if result.ok else result.head_sha256
    if result.ok and expected_head is not None and expected_head != prev:
        result.ok = False
        result.problems.append(
            f"head {prev} does not match sealed head {expected_head} (ledger truncated or extended)"
        )
    return result
