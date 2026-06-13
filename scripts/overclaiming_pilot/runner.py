"""Overclaiming pilot run harness (A1.1).

Drives headless agent sessions via the `claude` CLI (the same substrate the
Claude Agent SDK wraps), one per (condition × task × model × rep) cell, and
writes a self-contained per-run bundle: the exact prompt, model id, full
stream-json transcript, the extracted final answer, the tool-call sequence,
and any artifacts the agent produced.

Design constraints (from OVERCLAIMING_PILOT_RUNBOOK.md):
- Prompts are FROZEN. This harness only *substitutes* {task_text}; it never
  edits prompt files.
- Each run is isolated in its own working directory so agents cannot see each
  other's artifacts.
- Nothing here scores or interprets — that is llm_judge.py + human raters.

Stdlib only — no third-party deps, so it runs anywhere the `claude` CLI is
installed and authenticated.

Usage:
    python scripts/overclaiming_pilot/runner.py --smoke          # 10 runs, 1 rep
    python scripts/overclaiming_pilot/runner.py --full           # 50 runs, 5 reps
    python scripts/overclaiming_pilot/runner.py --task T1-missing-date --reps 1
    python scripts/overclaiming_pilot/runner.py --dry-run        # print matrix only
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402, N812


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_prompt(condition: str) -> str:
    fname = {
        "raw_cli": "raw_agent_prompt.md",
        "contract_governed": "contract_agent_prompt.md",
    }[condition]
    return (C.PROMPTS_DIR / fname).read_text(encoding="utf-8")


def _run_id(condition: str, task_id: str, model_label: str, rep: int) -> str:
    safe_task = task_id.replace("-", "_")
    safe_model = model_label.replace("-", "_").replace(".", "_")
    return f"{condition}_{safe_task}_{safe_model}_rep{rep}"


def _claude_available() -> bool:
    return shutil.which("claude") is not None


def _build_matrix(args) -> list[dict]:
    tasks = C.TASKS
    if args.task:
        tasks = [t for t in C.TASKS if t["id"] == args.task]
        if not tasks:
            sys.exit(f"Unknown task id: {args.task}")
    conditions = [args.condition] if args.condition else C.CONDITIONS
    reps = args.reps if args.reps else (C.SMOKE_REPS if args.smoke else C.N_REPS)

    models = {"frontier": C.MODELS["frontier"]}
    if args.with_weaker:
        models["weaker"] = C.MODELS["weaker"]

    matrix = []
    for condition in conditions:
        for task in tasks:
            for model_label, model_id in models.items():
                for rep in range(1, reps + 1):
                    matrix.append(
                        {
                            "run_id": _run_id(condition, task["id"], model_id, rep),
                            "condition": condition,
                            "task": task,
                            "model_label": model_label,
                            "model_id": model_id,
                            "rep": rep,
                        }
                    )
    return matrix


def _parse_stream_json(raw: str) -> dict:
    """Extract final answer + tool-call sequence from a stream-json transcript."""
    events = []
    final_text_parts: list[str] = []
    tool_calls: list[dict] = []
    result_meta: dict = {}

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(ev)

        etype = ev.get("type")
        if etype == "assistant":
            msg = ev.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    final_text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "name": block.get("name"),
                            "input": block.get("input"),
                        }
                    )
        elif etype == "result":
            result_meta = {
                "is_error": ev.get("is_error"),
                "duration_ms": ev.get("duration_ms"),
                "num_turns": ev.get("num_turns"),
                "total_cost_usd": ev.get("total_cost_usd"),
                "usage": ev.get("usage"),
                "result": ev.get("result"),
            }

    # Prefer the result event's final text if present (it is the canonical answer).
    final_answer = result_meta.get("result") or "\n".join(final_text_parts).strip()
    return {
        "final_answer": final_answer,
        "tool_calls": tool_calls,
        "n_events": len(events),
        "result_meta": result_meta,
    }


def _execute_run(run: dict, dry_run: bool) -> dict:
    condition = run["condition"]
    task = run["task"]
    run_id = run["run_id"]

    work_dir = C.ARTIFACTS_DIR / condition / run_id
    transcript_dir = C.TRANSCRIPTS_DIR / condition
    work_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    system_prompt = _load_prompt(condition).replace("<task text>", task["text"])
    user_message = task["text"]

    cmd = [
        "claude",
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        run["model_id"],
        "--append-system-prompt",
        system_prompt,
        "--allowedTools",
        "Bash,Read,Glob,Grep",
        "--permission-mode",
        "bypassPermissions",
        "--no-session-persistence",
        "--max-budget-usd",
        "2.00",
        user_message,
    ]

    bundle = {
        "run_id": run_id,
        "condition": condition,
        "task_id": task["id"],
        "task_category": task["category"],
        "task_text": task["text"],
        "model_label": run["model_label"],
        "model_id": run["model_id"],
        "rep": run["rep"],
        "started_at": _utc_now(),
        "work_dir": str(work_dir.relative_to(C.REPO_ROOT)),
        "protocol_version": "1.0",
    }

    if dry_run:
        bundle["status"] = "dry_run"
        bundle["command_preview"] = " ".join(
            c if len(c) < 60 else c[:57] + "..." for c in cmd
        )
        return bundle

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=C.AGENT_TIMEOUT_S,
        )
        raw_stdout = proc.stdout
        parsed = _parse_stream_json(raw_stdout)

        # Persist the raw transcript next to the bundle and in the transcripts tree.
        (work_dir / "transcript.stream.jsonl").write_text(raw_stdout, encoding="utf-8")
        if proc.stderr.strip():
            (work_dir / "stderr.log").write_text(proc.stderr, encoding="utf-8")

        bundle.update(
            {
                "status": "ok" if proc.returncode == 0 else "nonzero_exit",
                "return_code": proc.returncode,
                "final_answer": parsed["final_answer"],
                "tool_calls": parsed["tool_calls"],
                "n_tool_calls": len(parsed["tool_calls"]),
                "n_events": parsed["n_events"],
                "result_meta": parsed["result_meta"],
                "finished_at": _utc_now(),
            }
        )

        # Human-readable transcript for blind scoring (final answer only).
        transcript_md = (
            f"# Run {run_id}\n\n"
            f"**Task:** {task['text']}\n\n"
            f"**Model:** {run['model_id']}\n\n"
            f"---\n\n## Agent final answer\n\n{parsed['final_answer']}\n"
        )
        (transcript_dir / f"{run_id}.md").write_text(transcript_md, encoding="utf-8")

    except subprocess.TimeoutExpired:
        bundle.update(
            {
                "status": "timeout",
                "timeout_s": C.AGENT_TIMEOUT_S,
                "finished_at": _utc_now(),
            }
        )
        _log_failure(run_id, condition, run["model_id"], run["rep"], "timeout",
                     f"Exceeded {C.AGENT_TIMEOUT_S}s")
    except Exception as exc:  # noqa: BLE001
        bundle.update(
            {"status": "error", "error": str(exc), "finished_at": _utc_now()}
        )
        _log_failure(run_id, condition, run["model_id"], run["rep"], "error", str(exc))

    (work_dir / "run_bundle.json").write_text(
        json.dumps(bundle, indent=2), encoding="utf-8"
    )
    return bundle


def _log_failure(run_id, condition, model, rep, kind, detail) -> None:
    C.FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n### Failure: {_utc_now()} — {run_id}\n"
        f"- **Kind:** {kind}\n"
        f"- **Condition:** {condition} · **Model:** {model} · **Rep:** {rep}\n"
        f"- **Detail:** {detail}\n"
        f"- **Impact on analysis:** run excluded from primary metric (per exclusion rules)\n"
    )
    with C.FAILURE_LOG.open("a", encoding="utf-8") as fh:
        if C.FAILURE_LOG.stat().st_size == 0:
            fh.write("# Pilot Failure Log\n")
        fh.write(entry)


def main() -> None:
    ap = argparse.ArgumentParser(description="Overclaiming pilot run harness (A1.1)")
    ap.add_argument("--smoke", action="store_true", help="1 rep per cell (10 runs)")
    ap.add_argument("--full", action="store_true", help="N_REPS per cell (50 runs)")
    ap.add_argument("--task", help="run a single task id only")
    ap.add_argument("--condition", choices=C.CONDITIONS, help="run a single condition")
    ap.add_argument("--reps", type=int, help="override replicate count")
    ap.add_argument("--with-weaker", action="store_true", help="add weaker model tier (H4)")
    ap.add_argument("--dry-run", action="store_true", help="print matrix, execute nothing")
    args = ap.parse_args()

    if not args.smoke and not args.full and not args.reps and not args.dry_run:
        ap.error("choose one of --smoke / --full / --reps / --dry-run")

    if not args.dry_run and not _claude_available():
        sys.exit(
            "The `claude` CLI is not on PATH. Install Claude Code and authenticate, "
            "or run with --dry-run to preview the matrix."
        )

    matrix = _build_matrix(args)
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Run matrix: {len(matrix)} runs "
          f"({len(C.CONDITIONS) if not args.condition else 1} conditions × "
          f"tasks × models × reps)")
    if args.dry_run:
        for run in matrix:
            print(f"  - {run['run_id']}  [{run['model_id']}]")
        print("\nDry run — nothing executed.")
        return

    index = []
    for i, run in enumerate(matrix, 1):
        print(f"[{i}/{len(matrix)}] {run['run_id']} ...", flush=True)
        bundle = _execute_run(run, dry_run=False)
        index.append(
            {
                "run_id": bundle["run_id"],
                "condition": bundle["condition"],
                "task_id": bundle["task_id"],
                "model_id": bundle["model_id"],
                "rep": bundle["rep"],
                "status": bundle.get("status"),
                "n_tool_calls": bundle.get("n_tool_calls"),
            }
        )
        print(f"      -> {bundle.get('status')} "
              f"({bundle.get('n_tool_calls', '?')} tool calls)")

    index_path = C.DATA_DIR / "run_index.json"
    index_path.write_text(
        json.dumps(
            {"generated_at": _utc_now(), "protocol_version": "1.0", "runs": index},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote run index: {index_path.relative_to(C.REPO_ROOT)}")
    ok = sum(1 for r in index if r["status"] == "ok")
    print(f"Completed: {ok}/{len(index)} runs ok")


if __name__ == "__main__":
    main()
