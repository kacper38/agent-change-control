#!/usr/bin/env python3
"""page — the task page (tracker item #77, docs/PLAN-2026-11-dashboard.md): a local, read-only record of the tasks
of one repository over the last N days, read from files already on the machine.

  collect(project, days, homes)  the sessions of every home given (the owner's Claude home, the box's) whose
                                 folder lies in the project (or, for the box, in /work), grouped by the branch most
                                 of their lines carry; per session its scope, agents (ledger.read_agents), every
                                 tool call joined on its id with the guard's line in decisions.jsonl, and its cost;
                                 per branch the PR numbers, the fresh-review receipts tied to it, the re-test of
                                 consecutive receipts and the evidence/ paths of origin/main..refs/heads/NAME.

Nothing is printed or written here, and no tool input, tool output, prompt or reply is read into the data: of a
tool_use block only its name, id and time. Every text comes from a file and is untrusted. A branch name reaches
git only as checked by `git check-ref-format --branch` (unchanged, no `@{`), after `--end-of-options`, as
`refs/heads/NAME`, with a closing `--`. Git runs only in the project folder (never in a box's clone: the box
session controls its .git/config). Standard library only, Python >= 3.9.
"""
import datetime as _dt
import glob
import importlib.util
import json
import math
import os
import re
import subprocess
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_ledger():
    """The ledger beside this file, by path: page.py and ledger.py ship together (kit.manifest)."""
    spec = importlib.util.spec_from_file_location("kz_page_ledger", os.path.join(HERE, "ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ledger = _load_ledger()

BOX_ROOT = "/work"  # where a box mounts its clone, so the cwd of every box session
SESSION_FILE = re.compile(r"[A-Za-z0-9_-]+\.jsonl")
SHA = re.compile(r"[0-9a-f]{40}")
STRENGTH = {"deny": 4, "ask": 3, "logged": 2, "skipped": 1}  # one call with two guard lines keeps the stronger
GIT_TIMEOUT = 30
LOOKUP_TEXT = {
    "none": "no branch: the session's folder is no git work tree on a branch",
    "refused": "no evidence lookup: not a plain branch name",
    "absent": "no evidence lookup: branch not in this clone",
    "no-base": "no evidence lookup: origin/main not in this clone",
    "no-repo": "no evidence lookup: the project is no git repository",
    "error": "no evidence lookup: git failed",
}


def run_git(args: list, cwd: str) -> tuple:
    """(exit code or None, stdout) of `git ARGS` in `cwd`; None when git cannot be started or times out. The one way
    this module calls git, so a test can record every call."""
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=GIT_TIMEOUT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError):  # no git, no folder, or a hang: the caller says "git failed"
        return None, ""
    return r.returncode, r.stdout


def _text(value, limit: int = 300) -> Optional[str]:
    """A string from a file, printable, cut to `limit`; None for anything that is no non-empty string."""
    if not isinstance(value, str) or not value:
        return None
    text = ledger._clean(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _encoded(folder: str) -> str:
    """The name Claude Code gives the project folder of `folder` (ledger.find_session uses the same)."""
    return re.sub(r"[^A-Za-z0-9]", "-", folder)


def _inside(path: str, root: str) -> bool:
    """True when `path` is the folder `root` or lies under it (by name: transcripts hold absolute folders)."""
    root = root.rstrip("/")
    return path == root or path.startswith(root + "/")


def read_transcript(path: str) -> Optional[dict]:
    """Scope and tool calls of one transcript: the last title, line counts per branch, the folders in order, the PR
    numbers, and per tool_use block (first of each id) its time, name and id. None when the file does not open."""
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    title, branches, last_seen, cwds, prs, calls, ids, bad = None, {}, {}, [], set(), [], set(), 0
    with fh:
        for n, line in enumerate(fh):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except (ValueError, RecursionError):  # no JSON or nested too deep: counted, the rest still counts
                bad += 1
                continue
            if not isinstance(d, dict):
                continue
            title = _text(d.get("aiTitle")) or title
            branch = d.get("gitBranch")
            if isinstance(branch, str) and branch:
                branches[branch] = branches.get(branch, 0) + 1
                last_seen[branch] = n
            cwd = d.get("cwd")
            if isinstance(cwd, str) and cwd and cwd not in cwds:
                cwds.append(cwd)
            pr = d.get("prNumber")
            if isinstance(pr, int) and not isinstance(pr, bool) and 0 < pr < 10 ** 9:
                prs.add(pr)
            if d.get("type") != "assistant":
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            content = msg.get("content")
            when = ledger._when(d.get("timestamp"))
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call = block.get("id") if isinstance(block.get("id"), str) and block.get("id") else None
                if call is not None:
                    if call in ids:  # one block written on two lines is one call
                        continue
                    ids.add(call)
                calls.append({"when": when, "tool": _text(block.get("name"), 120) or "?", "call": call})
    branch = max(branches, key=lambda b: (branches[b], last_seen[b])) if branches else None
    return {"title": title, "branch": branch, "branches": branches, "cwds": cwds, "prs": prs, "calls": calls,
            "lines_not_read": bad}


_EPOCH = _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)


def read_guard_log(tdir: str) -> dict:
    """decisions.jsonl of one home: per call id the strongest verdict and its rules, the call ids with a `ran` line,
    and per session every ask and deny (one row per line, with each rule's own verdict)."""
    out = {"by_call": {}, "ran": set(), "gate": {}, "files_not_read": 0, "lines_not_read": 0}
    try:
        fh = open(os.path.join(tdir, "decisions.jsonl"), encoding="utf-8", errors="replace")
    except FileNotFoundError:  # no guard in this home, or nothing asked yet: normal
        return out
    except OSError:
        out["files_not_read"] = 1
        return out
    with fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except (ValueError, RecursionError):
                out["lines_not_read"] += 1
                continue
            verdict, session = (d.get("verdict"), d.get("session")) if isinstance(d, dict) else (None, None)
            if not isinstance(verdict, str) or not isinstance(session, str):
                out["lines_not_read"] += 1
                continue
            call = d.get("call") if isinstance(d.get("call"), str) and d.get("call") else None
            rules = d.get("rules")
            if isinstance(rules, dict):  # guard >= 0.4.1: each rule's own verdict
                pairs = sorted((_text(k, 80) or "?", _text(v, 20) or "?") for k, v in rules.items())
            elif isinstance(rules, list):
                pairs = sorted((_text(r, 80) or "?", _text(verdict, 20) or "?") for r in rules)
            else:
                pairs = []
            if verdict == "ran":
                if call:
                    out["ran"].add(call)
                continue
            if call:
                was = out["by_call"].get(call)
                if was is None or STRENGTH.get(verdict, 0) > STRENGTH.get(was["verdict"], 0):
                    out["by_call"][call] = {"verdict": _text(verdict, 20), "rules": pairs}
            if verdict in ("ask", "deny"):
                out["gate"].setdefault(session, []).append({
                    "when": ledger._when(d.get("ts")), "tool": _text(d.get("tool"), 120) or "?", "verdict": verdict,
                    "rules": pairs, "call": call})
    return out


def read_box_results(results: Optional[str]) -> dict:
    """{session id: the host's record of that box run} from boxes/NAME/results/<UTC>/result.json; the session id is
    the CLI's own (the `result` key), the other fields are written by the wrapper on the host."""
    found: dict = {}
    if not results:
        return found
    for path in sorted(glob.glob(os.path.join(glob.escape(results), "*", "results", "*", "result.json"))):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                rec = json.load(fh)
        except (OSError, ValueError, RecursionError):  # a run cut off before its record: no scope line for it
            continue
        inner = rec.get("result") if isinstance(rec, dict) else None
        sid = inner.get("session_id") if isinstance(inner, dict) else None
        if not isinstance(sid, str) or not SESSION_FILE.fullmatch(sid + ".jsonl"):
            continue
        keys = ("name", "seat", "image", "judge", "started", "ended", "head_before", "head_after", "branch_after")
        box = {k: _text(rec.get(k), 120) for k in keys}
        box["exit"] = rec.get("exit") if isinstance(rec.get("exit"), int) and not isinstance(rec.get("exit"), bool) \
            else None
        found[sid] = box
    return found


def _ledger_rows(tdir: str, since: _dt.datetime) -> tuple:
    """({session id: ledger row}, files not read) from sessions-*.jsonl of one home."""
    try:
        rows = ledger.load_sessions(tdir, since)
    except OSError:  # a month file that does not open: costs fall back to the own count, counted
        return {}, 1
    return {r["session"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("session"), str)}, 0


def _session_cost(row: Optional[dict], own: Optional[float]) -> tuple:
    """(cost or None, basis): the ledger's figure for a session that ended with a cost basis, else the own count."""
    cost = row.get("cost_usd") if row else None
    if row and row.get("cost_basis") and isinstance(cost, (int, float)) and not isinstance(cost, bool) \
            and math.isfinite(cost):
        return float(cost), _text(row["cost_basis"], 20) or "?"
    return own, "own count, no ledger line"


def read_home(home: dict, since: _dt.datetime, prices: dict) -> tuple:
    """(sessions, counters) of one home: every transcript of a project folder of home["root"] written since `since`
    whose folder lies in the root. A session id in two project folders counts once, the transcript written last."""
    counts = {"files_not_read": 0, "lines_not_read": 0, "read": False}
    projects = os.path.join(home["config"], "projects")
    root = home["root"]
    prefix = _encoded(root)
    try:
        folders = sorted(os.listdir(projects))
        counts["read"] = True
    except OSError:  # no such home on this machine (no box yet): the page says so
        return [], counts
    newest: dict = {}
    for folder in folders:
        if folder != prefix and not folder.startswith(prefix + "-"):
            continue
        try:
            names = sorted(os.listdir(os.path.join(projects, folder)))
        except OSError:
            counts["files_not_read"] += 1
            continue
        for name in names:
            path = os.path.join(projects, folder, name)
            if not SESSION_FILE.fullmatch(name) or not os.path.isfile(path):
                continue
            mtime = ledger._mtime(path)
            if mtime < since.timestamp() * 1e9:
                continue
            sid = name[:-len(".jsonl")]
            if sid not in newest or (mtime, path) > newest[sid]:
                newest[sid] = (mtime, path)
    guard = read_guard_log(home["telemetry"])
    counts["files_not_read"] += guard["files_not_read"]
    counts["lines_not_read"] += guard["lines_not_read"]
    rows, bad = _ledger_rows(home["telemetry"], since)
    counts["files_not_read"] += bad
    boxes = read_box_results(home.get("results"))
    sessions = []
    for sid, (_, path) in sorted(newest.items()):
        info = read_transcript(path)
        if info is None:
            counts["files_not_read"] += 1
            continue
        if not any(_inside(c, root) for c in info["cwds"]):  # a folder of the same name prefix, or another project
            continue
        tree = ledger.read_agents(path, home["telemetry"], prices)
        counts["files_not_read"] += tree["files_not_read"]
        counts["lines_not_read"] += tree["lines_not_read"] + info["lines_not_read"]
        calls = [dict(c, agent="session") for c in info["calls"]]
        for row in tree["rows"]:
            if row["kind"] != "agent" or not row["read"]:
                continue
            agent = read_transcript(row["path"])
            if agent is None:
                counts["files_not_read"] += 1
                continue
            counts["lines_not_read"] += agent["lines_not_read"]
            calls += [dict(c, agent=row["label"]) for c in agent["calls"]]
        for c in calls:
            seen = guard["by_call"].get(c["call"]) if c["call"] else None
            c["verdict"] = seen["verdict"] if seen else "-"
            c["rules"] = seen["rules"] if seen else []
            c["ran"] = (c["call"] in guard["ran"]) if seen and seen["verdict"] == "ask" else None
        calls.sort(key=lambda c: (c["when"] is None, c["when"] or _EPOCH))
        gate = []
        for g in guard["gate"].get(sid, []):
            gate.append(dict(g, ran=(g["call"] in guard["ran"]) if g["verdict"] == "ask" and g["call"] else None))
        gate.sort(key=lambda g: (g["when"] is None, g["when"] or _EPOCH))
        top = tree["rows"][0]
        cost, basis = _session_cost(rows.get(sid), tree["total"]["cost"])
        sessions.append({
            "id": sid, "home": home["label"], "title": info["title"], "branch": info["branch"],
            "branches": info["branches"], "folders": [_text(c, 300) for c in info["cwds"]], "prs": info["prs"],
            "model": top["model"], "state": top["state"], "start": top["start"], "end": top["end"],
            "seconds": top["seconds"], "cost": cost, "cost_basis": basis, "box": boxes.get(sid),
            "agents": [{k: r.get(k) for k in ("depth", "kind", "label", "state", "seconds", "cost", "tools", "model",
                                              "read")} for r in tree["rows"]],
            "calls": calls, "gate": gate})
    return sessions, counts


def read_receipts(common: Optional[str], since: _dt.datetime) -> tuple:
    """(receipts since `since`, files not read) from <git common dir>/fresh-review/ and every worktree's
    <git common dir>/worktrees/NAME/fresh-review/; each receipt with its findings as they were written."""
    if not common:
        return [], 0
    paths = sorted(glob.glob(os.path.join(glob.escape(common), "fresh-review", "*.json"))
                   + glob.glob(os.path.join(glob.escape(common), "worktrees", "*", "fresh-review", "*.json")))
    receipts, bad = [], 0
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                rec = json.load(fh)
        except (OSError, ValueError, RecursionError):
            bad += 1
            continue
        sha = rec.get("sha") if isinstance(rec, dict) else None
        when = ledger._when(rec.get("ts")) if isinstance(rec, dict) else None
        if not isinstance(sha, str) or not SHA.fullmatch(sha) or when is None:
            bad += 1
            continue
        if when < since:
            continue
        findings = []
        for f in rec.get("findings") if isinstance(rec.get("findings"), list) else []:
            if not isinstance(f, dict):
                continue
            line = f.get("line")
            findings.append({"file": _text(f.get("file"), 200) or "?",
                             "line": line if isinstance(line, int) and not isinstance(line, bool) else _text(line, 20),
                             "severity": _text(f.get("severity"), 20) or "?", "summary": _text(f.get("summary"), 600)
                             or ""})
        cost = rec.get("cost_usd")
        rel = os.path.relpath(path, common).split(os.sep)
        receipts.append({
            "sha": sha, "when": when, "verdict": _text(rec.get("verdict"), 20) or "?",
            "base": _text(rec.get("base"), 120), "base_sha": rec.get("base_sha") if isinstance(rec.get("base_sha"), str)
            and SHA.fullmatch(rec.get("base_sha")) else None,
            "cost": float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost)
            else None, "findings": findings,
            "where": f"worktree {_text(rel[1], 120)}" if rel[0] == "worktrees" else "main checkout"})
    receipts.sort(key=lambda r: (r["when"], r["sha"]))
    return receipts, bad


def branch_lookup(branch: Optional[str], project: str, has_base: bool) -> dict:
    """The evidence of one branch: its commits ahead of origin/main with the evidence/ paths they changed, and every
    value refs/heads/NAME had (its reflog), so a review of an earlier tip is still tied to it after a merge or a
    rebase. `lookup` says why there is none."""
    if not branch:
        return {"lookup": "none"}
    code, out = run_git(["check-ref-format", "--branch", branch], project)  # the name as its single argument
    shown = out[:-1] if out.endswith("\n") else out
    if code != 0 or "@{" in branch or shown != branch:
        return {"lookup": "refused"}
    if not has_base:
        return {"lookup": "no-base"}
    code, out = run_git(["log", "--name-only", "--format=%x00%H", "--end-of-options",
                         f"origin/main..refs/heads/{branch}", "--"], project)
    if code == 128:  # git's answer for a revision it does not know; origin/main was checked to exist
        return {"lookup": "absent"}
    if code != 0:
        return {"lookup": "error"}
    commits, paths = [], set()
    for line in out.splitlines():
        if line.startswith("\x00"):
            commits.append(line[1:])
        elif line:
            paths.add(line)
    code, out = run_git(["log", "-g", "--format=%H", "--end-of-options", f"refs/heads/{branch}", "--"], project)
    tips = set(out.split()) if code == 0 else set()
    return {"lookup": "ok", "commits": len(commits), "shas": set(commits) | tips,
            "evidence": sorted(_text(p, 300) for p in paths if p.startswith("evidence/"))}


def _key(f: dict) -> tuple:
    return (f["file"], f["line"], f["summary"])


def retests(reviews: list) -> list:
    """Each review after the first against the one before it, by file, line and summary: which findings went, which
    stayed, which are new; `delta` when its base is the earlier review's commit (it saw only the change since)."""
    out = []
    for before, after in zip(reviews, reviews[1:]):
        was, now = {_key(f) for f in before["findings"]}, {_key(f) for f in after["findings"]}
        out.append({"from": before["sha"], "to": after["sha"], "delta": after["base_sha"] == before["sha"],
                    "went": [f for f in before["findings"] if _key(f) not in now],
                    "stayed": [f for f in after["findings"] if _key(f) in was],
                    "new": [f for f in after["findings"] if _key(f) not in was]})
    return out


def collect(project: str, days: int, homes: list, now: Optional[_dt.datetime] = None,
            prices: Optional[dict] = None) -> dict:
    """Everything the page shows, read from local files and the project's git; writes nothing. `homes` is a list of
    {"label", "config", "telemetry", "root", "results"}: a Claude home, its guard and ledger folder, the folder its
    sessions' cwd must lie in, and (for the box) the folder of the box runs."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = now - _dt.timedelta(days=days)
    prices = ledger.load_prices() if prices is None else prices
    project = os.path.realpath(project)
    sessions, counts = [], {"files_not_read": 0, "lines_not_read": 0}
    read_homes = []
    for home in homes:
        found, c = read_home(home, since, prices)
        sessions += found
        counts["files_not_read"] += c["files_not_read"]
        counts["lines_not_read"] += c["lines_not_read"]
        read_homes.append({"label": home["label"], "config": home["config"], "read": c["read"],
                           "sessions": len(found)})
    code, out = run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], project)
    common = out.strip() if code == 0 and out.strip() else None
    has_base = common is not None and run_git(["rev-parse", "--verify", "--quiet", "--end-of-options",
                                               "refs/remotes/origin/main^{commit}"], project)[0] == 0
    receipts, bad = read_receipts(common, since)
    counts["files_not_read"] += bad
    by_branch: dict = {}
    for s in sessions:
        by_branch.setdefault(s["branch"] or "", []).append(s)
    tasks, tied = [], set()
    for branch, group in by_branch.items():
        group.sort(key=lambda s: (s["start"] is None, s["start"] or _EPOCH, s["id"]))
        found = branch_lookup(branch or None, project, has_base) if common else {"lookup": "no-repo"}
        reviews = [r for r in receipts if r["sha"] in found.get("shas", ())]
        tied.update(id(r) for r in reviews)
        costs = [s["cost"] for s in group]
        ends = [s["end"] for s in group if s["end"] is not None]
        tasks.append({
            "branch": branch or None, "sessions": group, "prs": sorted(set().union(*(s["prs"] for s in group))),
            "cost": None if None in costs else sum(costs, 0.0), "end": max(ends) if ends else None,
            "asks": sum(g["verdict"] == "ask" for s in group for g in s["gate"]),
            "denies": sum(g["verdict"] == "deny" for s in group for g in s["gate"]),
            "lookup": found["lookup"], "commits": found.get("commits"), "evidence": found.get("evidence", []),
            "reviews": reviews, "retests": retests(reviews)})
    tasks.sort(key=lambda t: (t["end"] is None, -(t["end"] or _EPOCH).timestamp(), t["branch"] or ""))
    return {"project": project, "days": days, "since": since, "now": now, "homes": read_homes, "tasks": tasks,
            "reviews_untied": sum(id(r) not in tied for r in receipts), "reviews": len(receipts), **counts}
