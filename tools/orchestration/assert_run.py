#!/usr/bin/env python3
"""assert_run — deterministic checks on what an agent run left behind (plan steps 2.3, D1 and D4).

  python3 tools/orchestration/assert_run.py run FILE
  python3 tools/orchestration/assert_run.py worker FILE [--repo DIR]
  python3 tools/orchestration/assert_run.py merge-ready N [--repo DIR]

run: FILE is the stdout of `claude -p --output-format json|stream-json`; the last result message must be a
success with structured output, no permission denial (on any result message), no null stage and no outstanding
background work. worker: FILE is a `worker-result/1` object; its head must be the branch tip and every check must
have exited 0. merge-ready: pull request N must be open, its head the branch tip, its checks green, a fresh-review
receipt approve that head and the pull request add a DECISIONS.md line; on a pass the merge command is printed,
never run. One line per problem (FAIL, or GAP for what could not be read: a gap never passes), then a summary.
Exit codes: 0 pass, 1 a failure or a gap, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HEX40 = re.compile(r"[0-9a-f]{40}")
WORKER_SCHEMA = "worker-result/1"
RECEIPT_MAX = 1 << 20
RECEIPT_VERDICTS = ("APPROVE", "COMMENT")
CHECK_RUN_OK = ("SUCCESS", "NEUTRAL", "SKIPPED")
GIT_TIMEOUT_S = 10
GH_TIMEOUT_S = 60
PR_FIELDS = "number,state,headRefName,headRefOid,statusCheckRollup,files"


def _int(v) -> int | None:
    """v when it is an integer (a bool is not), else None."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _is_sha(v) -> bool:
    return isinstance(v, str) and HEX40.fullmatch(v) is not None


# --- gather: the only code that touches files, git or gh ----------------------------------------------------------

def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def load_messages(path: str) -> list | None:
    """The messages of a run file: one JSON object, a JSON array, or JSON lines; None when unreadable or no JSON."""
    text = read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except ValueError:
        pass
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except ValueError:
        return None


def load_json(path: str):
    text = read_text(path)
    try:
        return None if text is None else json.loads(text)
    except ValueError:
        return None


def _run(cmd: list, repo: str, timeout: int) -> str | None:
    """stdout of cmd in repo, None when it cannot run or exits non-zero."""
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return r.stdout if r.returncode == 0 else None


def branch_ref(repo: str, ref: str) -> str | None:
    out = _run(["git", "rev-parse", "--verify", "-q", ref + "^{commit}"], repo, GIT_TIMEOUT_S)
    return out.strip() if out and out.strip() else None


def branch_tip(repo: str, branch: str) -> str | None:
    """The local branch's commit, else origin's remote-tracking branch's, else None."""
    return branch_ref(repo, f"refs/heads/{branch}") or branch_ref(repo, f"refs/remotes/origin/{branch}")


# --- checks: parsed data in, problems out ---------------------------------------------------------------------------

def check_run(messages: list | None, name: str) -> list:
    """The D4 post-step on the messages of a headless run, judged on its last result message."""
    results = [m for m in messages or [] if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        return [f"GAP: no result message in {name}"]
    last, problems = results[-1], []
    if last.get("is_error") is not False or last.get("subtype") != "success":
        problems.append(f"FAIL: the run ended with subtype {last.get('subtype')!r}, is_error {last.get('is_error')!r}")
    seen = set()
    for m in results:
        denials = m.get("permission_denials")
        for d in denials if isinstance(denials, list) else []:
            d = d if isinstance(d, dict) else {}
            key = d.get("tool_use_id") or json.dumps(d, sort_keys=True)
            if key not in seen:
                seen.add(key)
                problems.append(f"FAIL: permission denied: {d.get('tool_name')}")
    if not isinstance(last.get("permission_denials"), list):
        problems.append("GAP: no permission_denials field on the last result message")
    out = last.get("structured_output")
    if out is None:
        problems.append("GAP: no structured output")
    elif isinstance(out, dict):
        problems += [f'FAIL: stage "{k}" is null' for k, v in out.items() if v is None]
        stages = out.get("stages")
        if isinstance(stages, list):
            problems += [f"FAIL: stages[{i}] is null" for i, v in enumerate(stages) if v is None]
        elif isinstance(stages, dict):
            problems += [f'FAIL: stages["{k}"] is null' for k, v in stages.items() if v is None]
    stats = last.get("subagent_stats")
    if not isinstance(stats, dict):
        problems.append("GAP: no subagent_stats on the last result message")
    else:
        killed = stats.get("killed")
        counts = [_int(stats.get(k)) for k in ("spawned", "completed", "failed")]
        counts += [_int(v) for v in killed.values()] if isinstance(killed, dict) else [None]
        if None in counts:
            problems.append("GAP: subagent_stats has no readable spawned, completed, failed and killed counts")
        elif counts[0] > sum(counts[1:]):
            problems.append(f"FAIL: {counts[0] - sum(counts[1:])} subagent(s) spawned and not finished")
    queued = _int(last.get("queued_turn_count"))
    if queued:
        problems.append(f"FAIL: {queued} queued turn(s) outstanding")
    return problems


def check_worker(data, tip: str | None) -> list:
    """A `worker-result/1` against the tip of its branch (None: the branch was not found)."""
    if not isinstance(data, dict) or data.get("schema") != WORKER_SCHEMA:
        return ["GAP: no worker result"]
    problems = []
    branch, head, checks = data.get("branch"), data.get("head"), data.get("checks")
    if not isinstance(branch, str) or not branch:
        problems.append("GAP: field branch is not a non-empty string")
    if not _is_sha(head):
        problems.append("GAP: field head is not 40 lower-case hex digits")
    if not isinstance(checks, list) or not checks:
        problems.append("GAP: field checks is not a non-empty list")
    if not isinstance(data.get("not_verified"), list):
        problems.append("GAP: field not_verified is not a list")
    if isinstance(branch, str) and branch:
        if tip is None:
            problems.append(f"GAP: branch {branch} not found locally or at origin")
        elif _is_sha(head) and head != tip:
            problems.append(f"FAIL: head {head} is not the tip {tip} of {branch}")
    for i, c in enumerate(checks if isinstance(checks, list) else []):
        if not isinstance(c, dict) or not isinstance(c.get("command"), str):
            problems.append(f"GAP: field checks[{i}] has no command")
        elif _int(c.get("exit_code")) != 0:
            problems.append(f"FAIL: check {c['command']!r} exited {c.get('exit_code')!r}")
    return problems


def not_verified(data) -> list:
    entries = data.get("not_verified") if isinstance(data, dict) else None
    return [f"NOT VERIFIED: {e}" for e in entries] if isinstance(entries, list) else []


# --- command line ---------------------------------------------------------------------------------------------------

def report(mode: str, problems: list, info: list, out) -> int:
    for line in problems + info:
        out.write(line + "\n")
    out.write(f"assert_run {mode}: FAIL ({len(problems)} problems)\n" if problems else f"assert_run {mode}: PASS\n")
    return 1 if problems else 0


def main(argv: list | None = None, out=None) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="assert_run.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("run").add_argument("file")
    w = sub.add_parser("worker")
    w.add_argument("file")
    w.add_argument("--repo", default=os.getcwd())
    ns = ap.parse_args(argv)
    if ns.mode == "run":
        return report("run", check_run(load_messages(ns.file), ns.file), [], out)
    data = load_json(ns.file)
    branch = data.get("branch") if isinstance(data, dict) else None
    tip = branch_tip(ns.repo, branch) if isinstance(branch, str) and branch else None
    return report("worker", check_worker(data, tip), not_verified(data), out)


if __name__ == "__main__":
    sys.exit(main())
