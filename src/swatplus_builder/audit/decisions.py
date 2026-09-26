"""Decision records, environment fingerprints and DecisionEpisode export.

A workflow run takes many bounded decisions — which claim tier the contract
allows, whether calibration may start, which calibration phases run, which
claim tier the evidence finally supports. Today those are made by package
rules; later some may be proposed by an agent or a learned decision model.
Recording each one as ``state → options → chosen → outcome`` in a hash-chained
ledger (``decisions.jsonl``) makes every run

* auditable: who/what decided, under which policy, from which evidence, and
* reusable as training data: :func:`export_decision_episodes` joins each
  decision with its outcome into a model-agnostic ``DecisionEpisode`` row.

Records are data about the run, never instructions: nothing here changes a
decision, it only writes down the one that was taken.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .ledger import HashChainedLedger, iter_records, verify_ledger

UTC = timezone.utc  # datetime.UTC is Python 3.11+; the package supports 3.10.

DECISIONS_FILENAME = "decisions.jsonl"
EVENTS_FILENAME = "events.jsonl"
DECISION_EPISODE_SCHEMA = "swatplus_builder.decision_episode/v1"

DecidedBy = Literal["package_rule", "agent", "human", "learned_model"]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def file_sha256(path: Path | str) -> str | None:
    """SHA-256 of a file, or ``None`` when it cannot be read."""
    p = Path(path)
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def environment_fingerprint() -> dict[str, Any]:
    """Capture what a rerun needs to match: code, engine binary and runtime.

    Never raises; missing pieces are recorded as ``None`` so the absence is
    itself auditable.
    """
    from .. import __version__

    fp: dict[str, Any] = {
        "package_version": __version__,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": sys.executable,
    }
    try:
        from ..output.metadata import try_git_sha

        fp["git_sha"] = try_git_sha(Path(__file__).resolve().parents[3])
    except Exception:
        fp["git_sha"] = None

    try:
        from ..run.swatplus import locate_binary

        exe = locate_binary()
        fp["engine_path"] = str(exe)
        fp["engine_sha256"] = file_sha256(exe)
        fp["engine_revision"] = _engine_revision(exe)
    except Exception as exc:
        fp["engine_path"] = None
        fp["engine_sha256"] = None
        fp["engine_error"] = f"{type(exc).__name__}: {exc}"

    versions: dict[str, str | None] = {}
    try:
        from importlib import metadata

        for dist in ("numpy", "pandas", "pydantic", "whitebox", "rasterio", "geopandas", "pySWATPlus"):
            try:
                versions[dist] = metadata.version(dist)
            except metadata.PackageNotFoundError:
                versions[dist] = None
    except Exception:
        pass
    fp["dependency_versions"] = versions
    return fp


def _engine_revision(exe: Path) -> str | None:
    """Read the engine's ``Revision`` banner (it prints it before failing on file.cio)."""
    import subprocess
    import tempfile

    from ..run.swatplus import parse_engine_revision

    try:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5, cwd=tmp)
        return parse_engine_revision((proc.stdout or "") + (proc.stderr or ""))
    except Exception:
        return None


def archive_previous_trail(run_dir: Path | str) -> list[str]:
    """Move an earlier attempt's ledgers into ``audit_history/`` instead of deleting them.

    Re-running a workflow in the same directory used to delete the previous
    ``events.jsonl``; keeping it preserves the full history of attempts.
    """
    root = Path(run_dir)
    moved: list[str] = []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for name in (EVENTS_FILENAME, DECISIONS_FILENAME):
        src = root / name
        if src.exists():
            dest_dir = root / "audit_history"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{src.stem}.{stamp}{src.suffix}"
            src.replace(dest)
            moved.append(str(dest))
    return moved


class RunAuditTrail:
    """Hash-chained ``events.jsonl`` + ``decisions.jsonl`` for one run directory."""

    def __init__(
        self,
        run_dir: Path | str,
        *,
        run_id: str,
        basin_id: str,
        attempt_id: str | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.basin_id = basin_id
        # run_id is deterministic per (gauge, window); attempt_id keeps decision
        # ids unique when the same run directory is re-executed.
        self.attempt_id = attempt_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self.events = HashChainedLedger(self.run_dir / EVENTS_FILENAME)
        self.decisions = HashChainedLedger(self.run_dir / DECISIONS_FILENAME)
        self._decision_counter = 0

    # -- events ---------------------------------------------------------
    def event(self, stage: str, status: str, **extra: Any) -> dict[str, Any]:
        rec = {
            "time": _utc_now(),
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "usgs_id": self.basin_id,
            "stage": stage,
            "status": status,
            **extra,
        }
        return self.events.append(rec)

    # -- decisions ------------------------------------------------------
    def decision(
        self,
        decision_point: str,
        *,
        state: Mapping[str, Any],
        options: Sequence[str],
        chosen: str,
        decided_by: DecidedBy = "package_rule",
        policy: str,
        rationale: str | None = None,
        evidence: Mapping[str, Any] | None = None,
        probabilities: Mapping[str, float] | None = None,
    ) -> str:
        """Record one decision and return its ``decision_id``.

        Args:
            decision_point: Stable name of the fork in the workflow.
            state: Compact evidence the decision was based on.
            options: The full bounded option set that was available.
            chosen: The option taken; must be one of ``options``.
            decided_by: Which authority took it.
            policy: The rule/model identity (e.g. function name + version).
            rationale: Short machine-readable reason.
            evidence: Artifact pointers (paths or hashes) backing ``state``.
            probabilities: Optional per-option probabilities, when a
                probabilistic decider (agent/model) proposed the choice.
        """
        opts = [str(o) for o in options]
        if str(chosen) not in opts:
            raise ValueError(f"chosen {chosen!r} is not one of the recorded options {opts}")
        self._decision_counter += 1
        decision_id = f"{self.run_id}@{self.attempt_id}:{decision_point}:{self._decision_counter}"
        self.decisions.append(
            {
                "kind": "decision",
                "time": _utc_now(),
                "run_id": self.run_id,
                "attempt_id": self.attempt_id,
                "basin_id": self.basin_id,
                "decision_id": decision_id,
                "decision_point": decision_point,
                "state": dict(state),
                "options": opts,
                "chosen": str(chosen),
                "decided_by": decided_by,
                "policy": policy,
                "rationale": rationale,
                "evidence": dict(evidence or {}),
                "probabilities": dict(probabilities) if probabilities else None,
            }
        )
        return decision_id

    def outcome(self, decision_id: str, outcome: Mapping[str, Any]) -> None:
        """Attach the observed consequence of an earlier decision."""
        self.decisions.append(
            {
                "kind": "outcome",
                "time": _utc_now(),
                "run_id": self.run_id,
                "decision_id": decision_id,
                "outcome": dict(outcome),
            }
        )

    def heads(self) -> dict[str, Any]:
        """Sealable summary of both ledgers (head hash + record count)."""
        return {
            "events": {"path": str(self.events.path), "head_sha256": self.events.head, "records": self.events.count},
            "decisions": {
                "path": str(self.decisions.path),
                "head_sha256": self.decisions.head,
                "records": self.decisions.count,
            },
        }


def verify_run_audit(run_dir: Path | str) -> dict[str, Any]:
    """Verify a run's ledgers against the heads sealed in ``run_manifest.json``."""
    import json

    root = Path(run_dir)
    sealed: dict[str, Any] = {}
    manifest = root / "run_manifest.json"
    if manifest.is_file():
        try:
            sealed = json.loads(manifest.read_text(encoding="utf-8")).get("audit_ledgers") or {}
        except (OSError, ValueError):
            sealed = {}
    results: dict[str, Any] = {"run_dir": str(root), "sealed_heads_found": bool(sealed), "ledgers": {}}
    ok = True
    for name, filename in (("events", EVENTS_FILENAME), ("decisions", DECISIONS_FILENAME)):
        expected = (sealed.get(name) or {}).get("head_sha256")
        res = verify_ledger(root / filename, expected_head=expected).to_dict()
        results["ledgers"][name] = res
        ok = ok and bool(res["ok"])
    results["ok"] = ok and bool(sealed)
    if not sealed:
        results["problems"] = ["run_manifest.json has no sealed audit_ledgers heads"]
    return results


def export_decision_episodes(run_dir: Path | str) -> list[dict[str, Any]]:
    """Join a run's decisions with their outcomes into DecisionEpisode rows.

    The rows are model-agnostic (no Laya/Jev-specific format) so they can be
    compiled into any training format later. Each row carries the ledger
    record hashes it was built from, so a dataset row can always be traced
    back to — and re-verified against — the original run.
    """
    root = Path(run_dir)
    path = root / DECISIONS_FILENAME
    if not path.is_file():
        return []
    decisions: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, list[dict[str, Any]]] = {}
    for rec in iter_records(path):
        if rec.get("kind") == "decision":
            decisions[str(rec["decision_id"])] = rec
        elif rec.get("kind") == "outcome":
            outcomes.setdefault(str(rec["decision_id"]), []).append(rec)

    env: dict[str, Any] = {}
    events_path = root / EVENTS_FILENAME
    if events_path.is_file():
        for rec in iter_records(events_path):
            if rec.get("stage") == "environment":
                env = {k: v for k, v in rec.items() if k not in {"seq", "prev_sha256", "sha256"}}
                break

    episodes: list[dict[str, Any]] = []
    for decision_id, rec in decisions.items():
        outs = outcomes.get(decision_id, [])
        merged_outcome: dict[str, Any] = {}
        for o in outs:
            merged_outcome.update(o.get("outcome") or {})
        episodes.append(
            {
                "schema": DECISION_EPISODE_SCHEMA,
                "episode_id": decision_id,
                "run_id": rec.get("run_id"),
                "basin_id": rec.get("basin_id"),
                "decision_point": rec.get("decision_point"),
                "state_before": rec.get("state"),
                "candidate_actions": rec.get("options"),
                "chosen_action": rec.get("chosen"),
                "decided_by": rec.get("decided_by"),
                "policy": rec.get("policy"),
                "rationale": rec.get("rationale"),
                "probabilities": rec.get("probabilities"),
                "outcome_vector": merged_outcome or None,
                "outcome_observed": bool(outs),
                "evidence": rec.get("evidence"),
                "source": "natural",
                "split_group": rec.get("basin_id"),
                "builder_git_sha": env.get("git_sha"),
                "package_version": env.get("package_version"),
                "engine_sha256": env.get("engine_sha256"),
                "ledger_record_sha256": [rec.get("sha256"), *[o.get("sha256") for o in outs]],
            }
        )
    return episodes
