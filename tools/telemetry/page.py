#!/usr/bin/env python3
"""page — the task page (tracker item #77, docs/PLAN-2026-11-dashboard.md): a local, read-only record of the tasks
of one repository over the last N days, read from files already on the machine.

  page.py [--days 7] [--session ID] [--out PATH]
                                 write one HTML page for the repository of the current folder and print its path:
                                 <telemetry>/pages/<UTC>.html by default (folder 0700, file 0600; telemetry =
                                 KZ_TELEMETRY_DIR or ~/.claude/telemetry). The page goes nowhere else: a folder
                                 inside a git work tree is refused (the page is never committed), an existing file
                                 is never overwritten, and nothing is published. Sessions come from
                                 <CLAUDE_CONFIG_DIR or ~/.claude>/projects and, in a repository that has bin/box,
                                 from the box's ~/.agent-box/claude-home. --session ID: one session, a full id or a
                                 prefix that fits one. No server, no port, no network call, no JavaScript.
                                 A page is kept 30 days: a run to the default place names on stderr how many pages
                                 there are older, and removes none (the owner does).
                                 Exit codes: 0 written, 1 refused or failed (one line on stderr says why), 2 usage.

  collect(project, days, homes)  the sessions of every home given (the owner's Claude home, the box's) whose
                                 folder lies in the project (or, for the box, in /work), grouped by the branch most
                                 of their lines carry; per session its scope, agents (ledger.read_agents), every
                                 tool call joined on its id with the guard's line in decisions.jsonl, and its cost;
                                 per branch the PR numbers, the fresh-review receipts tied to it, the re-test of
                                 consecutive receipts and the evidence/ paths of origin/main..refs/heads/NAME.

Nothing is printed or written here, and no tool input, tool output, prompt or reply is read into the data: of a
tool_use block only its name, id and time; of an agent its type, without the description its Agent call gave; of a
workflow neither its script nor the script's name. Every text comes from a file and is untrusted. A branch name reaches
git only as checked by `git check-ref-format --branch` (unchanged, no `@{`), after `--end-of-options`, as
`refs/heads/NAME`, with a closing `--`. Git runs only in the project folder (never in a box's clone: the box
session controls its .git/config). Standard library only, Python >= 3.9.
"""
import argparse
import datetime as _dt
import glob
import html
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
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
MAX_DAYS = 3650  # a window of ten years; far larger values overflow datetime
RETENTION_DAYS = 30  # a page's retention, the default cleanupPeriodDays of the transcripts it is read from
PAGE_NAME = re.compile(r"[0-9]{8}T[0-9]{6}Z\.html")  # the name of a page written to the default place
LOOKUP_TEXT = {
    "none": "no branch: the session's folder is no git work tree on a branch",
    "refused": "no evidence lookup: not a plain branch name",
    "absent": "no evidence lookup: branch not in this clone",
    "no-base": "no evidence lookup: origin/main not in this clone",
    "no-repo": "no evidence lookup: the project is no git repository",
    "error": "no evidence lookup: git failed",
}


# Variables that point git at a repository other than the one its folder lies in: dropped, so `cwd` decides.
GIT_LOCATORS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


def run_git(args: list, cwd: str) -> tuple:
    """(exit code or None, stdout) of `git ARGS` in `cwd`; None when git cannot be started or times out. The one way
    this module calls git, so a test can record every call."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_LOCATORS}
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=GIT_TIMEOUT, env=dict(env, GIT_TERMINAL_PROMPT="0"))
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


def read_box_results(results: Optional[str], since: _dt.datetime) -> tuple:
    """({session id: the host's record of that box run}, files not read since `since`) from
    boxes/NAME/results/<UTC>/result.json; the session id is the CLI's own (the `result` key), the other fields are
    written by the wrapper on the host. A record tied to a session is kept at any age, so a session in the window
    keeps the box cell of a run that started before it. A record that does not parse counts at any age, since it may
    be any session's; one that parses and names no session counts only when its run ended in the window (the
    wrapper's `ended`), so a run stopped inside the window counts even when it started before."""
    found: dict = {}
    bad = 0
    if not results:
        return found, bad
    for path in sorted(glob.glob(os.path.join(glob.escape(results), "*", "results", "*", "result.json"))):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                rec = json.load(fh)
        except (OSError, ValueError, RecursionError):  # unreadable or cut off: it may be the record of a session in
            bad += 1  # the window, whose box cell is then missing, so it counts at any age
            continue
        inner = rec.get("result") if isinstance(rec, dict) else None
        sid = inner.get("session_id") if isinstance(inner, dict) else None
        if not isinstance(sid, str) or not SESSION_FILE.fullmatch(sid + ".jsonl"):
            # the CLI wrote no session id (a run that never got going, or one stopped) or one no session file can
            # have: tied to no session, so counted when its run ended in the window, by the wrapper's `ended`, and
            # always when no end time says it is old
            ended = ledger._when(rec.get("ended")) if isinstance(rec, dict) else None
            bad += ended is None or ended >= since
            continue
        keys = ("name", "seat", "image", "judge", "started", "ended", "head_before", "head_after", "branch_after")
        box = {k: _text(rec.get(k), 120) for k in keys}
        box["exit"] = rec.get("exit") if isinstance(rec.get("exit"), int) and not isinstance(rec.get("exit"), bool) \
            else None
        found[sid] = box
    return found, bad


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


def agent_label(row: dict) -> str:
    """The label of a tree row without what a tool call wrote into it: an agent's type (the ledger's `type`, never
    its label, which adds the description the Agent call gave), a workflow without its script's name (the plan's
    answer 1: no tool-call content in this version); the session's own row and an agent with no transcript (kind
    `missing`, its type from the spawn log) keep the ledger's label, which holds an id or a type only."""
    if row.get("kind") == "agent":
        return row.get("type") or "agent"
    if row.get("kind") == "workflow":
        return "workflow"
    return row.get("label") or ""


def read_home(home: dict, since: _dt.datetime, prices: dict, session: Optional[str] = None) -> tuple:
    """(sessions, counters) of one home: every transcript of a project folder of home["root"] written since `since`
    whose folder lies in the root (with `session`, only ids that start with it). A session id in two project
    folders counts once, the transcript written last."""
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
            if session and not sid.startswith(session):
                continue
            if sid not in newest or (mtime, path) > newest[sid]:
                newest[sid] = (mtime, path)
    guard = read_guard_log(home["telemetry"])
    counts["files_not_read"] += guard["files_not_read"]
    counts["lines_not_read"] += guard["lines_not_read"]
    rows, bad = _ledger_rows(home["telemetry"], since)
    counts["files_not_read"] += bad
    boxes, bad = read_box_results(home.get("results"), since)
    counts["files_not_read"] += bad
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
        counts["lines_not_read"] += tree["lines_not_read"]  # the ledger read the same transcripts: counted once
        calls = [dict(c, agent="session") for c in info["calls"]]
        for row in tree["rows"]:
            if row["kind"] != "agent" or not row["read"]:
                continue
            agent = read_transcript(row["path"])
            if agent is None:
                counts["files_not_read"] += 1
                continue
            calls += [dict(c, agent=agent_label(row)) for c in agent["calls"]]
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
            "agents": [dict({k: r.get(k) for k in ("depth", "kind", "state", "seconds", "cost", "tools", "model",
                                                   "read")}, label=agent_label(r)) for r in tree["rows"]],
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
    ahead = f"refs/remotes/origin/main..refs/heads/{branch}"  # the ref has_base checked: a short origin/main would
    # take a local branch or tag of that name first
    code, out = run_git(["rev-list", "--end-of-options", ahead, "--"], project)
    if code == 128:  # git's answer for a revision it does not know; origin/main was checked to exist
        return {"lookup": "absent"}
    if code != 0:
        return {"lookup": "error"}
    commits = out.split()
    code, out = run_git(["log", "-z", "--name-only", "--format=", "--end-of-options", ahead, "--"], project)
    if code != 0:  # -z: each path as it is, NUL-terminated, never C-quoted
        return {"lookup": "error"}
    paths = set(out.split("\x00"))  # the empty rest after the last NUL is no evidence/ path
    code, out = run_git(["log", "-g", "--format=%H", "--end-of-options", f"refs/heads/{branch}", "--"], project)
    if code != 0:  # a branch with no reflog exits 0 with nothing; a failure here would untie its reviews unseen
        return {"lookup": "error"}
    return {"lookup": "ok", "commits": len(commits), "shas": set(commits) | set(out.split()),
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


def _task(branch: Optional[str], group: list, found: dict, receipts: list) -> dict:
    """One task: a branch, its sessions (none for a branch seen only through its reviews), the receipts its commits
    or its reflog hold, and the figures of the task list. `end` is its last activity: a session's last line or a
    review."""
    reviews = [r for r in receipts if r["sha"] in found.get("shas", ())]
    costs = [s["cost"] for s in group]
    ends = [s["end"] for s in group if s["end"] is not None] + [r["when"] for r in reviews]
    return {"branch": branch, "sessions": group, "prs": sorted(set().union(*(s["prs"] for s in group))),
            "cost": None if not group or None in costs else sum(costs, 0.0), "end": max(ends) if ends else None,
            "asks": sum(g["verdict"] == "ask" for s in group for g in s["gate"]),
            "denies": sum(g["verdict"] == "deny" for s in group for g in s["gate"]),
            "lookup": found["lookup"], "commits": found.get("commits"), "evidence": found.get("evidence", []),
            "reviews": reviews, "retests": retests(reviews)}


def collect(project: str, days: int, homes: list, now: Optional[_dt.datetime] = None,
            prices: Optional[dict] = None, session: Optional[str] = None) -> dict:
    """Everything the page shows, read from local files and the project's git; writes nothing. `homes` is a list of
    {"label", "config", "telemetry", "root", "results"}: a Claude home, its guard and ledger folder, the folder its
    sessions' cwd must lie in, and (for the box) the folder of the box runs. `session`: only the sessions whose id
    is it, or, when none is, those whose id starts with it."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = now - _dt.timedelta(days=days)
    prices = ledger.load_prices() if prices is None else prices
    project = os.path.realpath(project)
    sessions, counts = [], {"files_not_read": 0, "lines_not_read": 0}
    read_homes = []
    for home in homes:
        found, c = read_home(home, since, prices, session)
        sessions += found
        counts["files_not_read"] += c["files_not_read"]
        counts["lines_not_read"] += c["lines_not_read"]
        read_homes.append({"label": home["label"], "config": home["config"], "read": c["read"],
                           "sessions": len(found)})
    if session and any(s["id"] == session for s in sessions):  # the full id wins over the ids it is a prefix of
        sessions = [s for s in sessions if s["id"] == session]
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
        tasks.append(_task(branch or None, group, found, receipts))
        tied.update(id(r) for r in tasks[-1]["reviews"])
    untied = {id(r) for r in receipts} - tied
    branch_list = None  # not read: no review untied, no origin/main, or a page of one session
    if untied and has_base and not session:  # a page of one session shows that session's task only
        # A review whose branch has no session here (its sessions ran from a folder on another branch): the
        # repository's other branches whose reflog holds it become tasks of their own, with no session.
        code, out = run_git(["for-each-ref", "--format=%(refname)", "refs/heads/"], project)
        branch_list = "ok" if code == 0 else "error"
        names = {line[len("refs/heads/"):] for line in out.splitlines() if line.startswith("refs/heads/")} \
            if code == 0 else set()
        for name in sorted(names - set(by_branch)):
            found = branch_lookup(name, project, has_base)  # the same checks as a name from a transcript
            if any(id(r) in untied for r in receipts if r["sha"] in found.get("shas", ())):
                tasks.append(_task(name, [], found, receipts))
                tied.update(id(r) for r in tasks[-1]["reviews"])
    tasks.sort(key=lambda t: (t["end"] is None, -(t["end"] or _EPOCH).timestamp(), t["branch"] or ""))
    return {"project": project, "days": days, "since": since, "now": now, "homes": read_homes, "tasks": tasks,
            "reviews_untied": sum(id(r) not in tied for r in receipts), "reviews": len(receipts),
            "branch_list": branch_list, **counts}


# ---- the page ---------------------------------------------------------------------------------------------------

CSP = "default-src 'none'; style-src 'unsafe-inline'"
# The page's only style: no url(, no @import, no ://, no backslash (check_page refuses each, and a CSS escape could
# spell url( past a text search).
STYLE = """
:root{color-scheme:light dark;--fg:#1d1d1f;--muted:#5f6368;--bg:#ffffff;--line:#d9d9de;--ask:#8a5a00;
--deny:#b3261e;--ok:#1a7f37}
@media (prefers-color-scheme:dark){:root{--fg:#e6e6e9;--muted:#a0a3a8;--bg:#16171a;--line:#34363b;--ask:#e3b341;
--deny:#ff7b72;--ok:#56d364}}
body{margin:0;padding:1.5rem 1rem;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,
sans-serif}
main{max-width:84rem;margin:0 auto}
h1{font-size:1.4rem;margin:0 0 .4rem}
h2{font-size:1.15rem;margin:2.2rem 0 .4rem;border-top:1px solid var(--line);padding-top:1rem}
h3{font-size:1rem;margin:1.4rem 0 .3rem}
.wide{overflow-x:auto}
table{border-collapse:collapse;margin:.3rem 0 1rem;min-width:100%}
th,td{text-align:left;padding:.25rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.muted{color:var(--muted)}
.ask{color:var(--ask)}
.deny{color:var(--deny)}
.ok{color:var(--ok)}
code{font:12px ui-monospace,Menlo,monospace}
details{margin:.5rem 0;padding:.3rem .7rem;border:1px solid var(--line);border-radius:6px}
summary{cursor:pointer}
"""
LEGEND = ("verdict `-`: the guard wrote no line for the call (no rule spoke, or no guard ran); `ask` then `ran`: "
          "the owner let an asked call go ahead; `ask` with `no ran line`: it never ran; `skipped`: a rule switched "
          "off by configuration would have spoken; `logged`: a box let the call run and logged it",
          "cost: the ledger's figure for a session that ended (Claude Code's own or the ledger's own count, as its "
          "basis says), else the ledger's own count from the transcripts; a task's cost is n/a when one of its "
          "sessions has none",
          "re-test: each review against the one before it, by file, line and summary; a delta review saw only the "
          "change since the review before it, so a finding that went may only lie outside that change",
          "not read: a file that did not open or parse, a line that is no JSON, and the record of a box run ended "
          "in the window that names no session (the run wrote no output, or its session id can be no session "
          "file's), so no session shows it; a box run's record that does not parse counts at any age",
          "state: inferred from the end of each transcript, so a session cut off reads as running",
          "task: a session sits under the branch most of its lines carry, which is the branch of the folder it ran "
          "from; a review is tied to the branch whose reflog or commits hold the reviewed commit, so a branch worked "
          "on from another folder can appear with its reviews and no session",
          "this page is a local, read-only record: it holds titles, folders, branch names and finding summaries "
          "and is never attached to a ticket, a pull request, a chat or an evidence pack, nor copied off this "
          "machine")


def _e(value) -> str:
    """Any value as escaped HTML text: every text on the page goes through here."""
    return html.escape("" if value is None else str(value), quote=True)


def _time(when: Optional[_dt.datetime], long: bool = False) -> str:
    if when is None:
        return "-"
    return when.astimezone(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC" if long else "%m-%d %H:%M:%S")


def _cell(value, cls: str = "") -> str:
    return f'<td class="{cls}">{_e(value)}</td>' if cls else f"<td>{_e(value)}</td>"


def _table(head: list, rows: list, nums: tuple = ()) -> str:
    """A table of escaped cells; `rows` holds lists of (text, class) or text; `nums` the columns set right."""
    out = ['<div class="wide"><table><thead><tr>']
    out += [f'<th class="num">{_e(h)}</th>' if i in nums else f"<th>{_e(h)}</th>" for i, h in enumerate(head)]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            text, cls = cell if isinstance(cell, tuple) else (cell, "")
            out.append(_cell(text, " ".join(c for c in (cls, "num" if i in nums else "") if c)))
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _verdict(verdict: str) -> tuple:
    return verdict, {"ask": "ask", "deny": "deny"}.get(verdict, "muted" if verdict == "-" else "")


def _ran(ran: Optional[bool], has_call: bool = True) -> tuple:
    if ran is None:
        return ("no call id", "muted") if not has_call else ("", "")
    return ("ran", "ok") if ran else ("no ran line", "deny")


def _rules(pairs: list) -> str:
    return ", ".join(f"{name}: {verdict}" for name, verdict in pairs)


def _finding(f: dict) -> str:
    where = f["file"] + (f":{f['line']}" if f["line"] is not None else "")
    return f"{f['severity']} {where} {f['summary']}"


def _session_section(s: dict) -> str:
    asks = sum(g["verdict"] == "ask" for g in s["gate"])
    denies = sum(g["verdict"] == "deny" for g in s["gate"])
    out = [f'<details id="s-{_e(s["id"])}"><summary>{_e(s["home"])} session <code>{_e(s["id"])}</code> &middot; '
           f'{_e(s["title"] or "(no title)")} &middot; {len(s["calls"])} tool calls, asks {asks}, denies {denies}'
           "</summary>"]
    out.append("<h3>Agents</h3>")
    out.append(_table(["state", "duration", "cost", "tool calls", "model", "agent"], [
        [a["state"], ledger.fmt_duration(a["seconds"]), ledger.fmt_cost(a["cost"], a["read"]),
         "-" if a["tools"] is None else a["tools"], a["model"] or "-",
         "  " * a["depth"] + ("└ " if a["depth"] else "") + (a["label"] or "")]
        for a in s["agents"]], nums=(1, 2, 3)))
    out.append("<h3>Timeline</h3>")
    if s["calls"]:
        out.append(_table(["time", "agent", "tool", "verdict", "rules", "ran"], [
            [_time(c["when"]), c["agent"], c["tool"], _verdict(c["verdict"]), _rules(c["rules"]),
             _ran(c["ran"])] for c in s["calls"]]))
    else:
        out.append('<p class="muted">no tool calls</p>')
    out.append("<h3>Gate</h3>")
    if s["gate"]:
        out.append(_table(["time", "tool", "verdict", "rules", "ran"], [
            [_time(g["when"]), g["tool"], _verdict(g["verdict"]), _rules(g["rules"]),
             _ran(g["ran"], g["call"] is not None) if g["verdict"] == "ask" else ""] for g in s["gate"]]))
    else:
        out.append('<p class="muted">no ask and no deny</p>')
    out.append("</details>")
    return "".join(out)


def _task_section(n: int, t: dict) -> str:
    name = t["branch"] or "(no branch)"
    out = [f'<section id="task-{n}"><h2>{_e(name)}</h2>']
    facts = [f"PR {', '.join('#' + str(p) for p in t['prs'])}" if t["prs"] else "no PR seen",
             f"cost {ledger.fmt_cost(t['cost'])}", f"asks {t['asks']}, denies {t['denies']}"]
    out.append(f'<p class="muted">{_e(" · ".join(facts))}</p>')
    out.append("<h3>Scope</h3>")
    rows = []
    for s in t["sessions"]:
        others = sorted(b for b in s["branches"] if b != s["branch"])
        box = s["box"]
        box_text = (f"box {box['name']}, seat {box['seat']}, exit {box['exit']}, image {box['image']}, "
                    f"head {(box['head_before'] or '-')[:12]} to {(box['head_after'] or '-')[:12]}" if box else "")
        rows.append([s["id"][:8], s["home"], s["title"] or "-", ", ".join([s["branch"] or "-"] + others),
                     ", ".join(f for f in s["folders"] if f), s["model"] or "-", s["state"], _time(s["start"]),
                     ledger.fmt_duration(s["seconds"]), f"{ledger.fmt_cost(s['cost'])} ({s['cost_basis']})",
                     ", ".join("#" + str(p) for p in sorted(s["prs"])) or "-", box_text])
    if rows:
        out.append(_table(["session", "home", "title", "branch", "folder", "model", "state", "start", "duration",
                           "cost", "PR", "box run"], rows, nums=(8,)))
    else:
        out.append('<p class="muted">no session on this branch in the window: it is here for its reviews, and its '
                   "sessions sit under the branch of the folder they ran from</p>")
    out += [_session_section(s) for s in t["sessions"]]
    out.append("<h3>Findings</h3>")
    if not t["reviews"]:
        out.append('<p class="muted">no fresh-review receipt tied to this branch in the window</p>')
    for r in t["reviews"]:
        cost = ledger.fmt_cost(r["cost"])
        out.append(f"<p><code>{_e(r['sha'][:12])}</code> {_e(_time(r['when']))} &middot; {_e(r['verdict'])} &middot; "
                   f"base {_e(r['base'] or '-')} &middot; {_e(cost)} &middot; {_e(r['where'])}</p>")
        if r["findings"]:
            out.append(_table(["severity", "file", "line", "summary"], [
                [f["severity"], f["file"], "-" if f["line"] is None else f["line"], f["summary"]]
                for f in r["findings"]], nums=(2,)))
        else:
            out.append('<p class="muted">no findings</p>')
    out.append("<h3>Re-test</h3>")
    if not t["retests"]:
        out.append('<p class="muted">fewer than two reviews: nothing to compare</p>')
    for rt in t["retests"]:
        kind = "delta review" if rt["delta"] else "review"
        out.append(f"<p><code>{_e(rt['from'][:12])}</code> to <code>{_e(rt['to'][:12])}</code> ({_e(kind)}): "
                   f"went {len(rt['went'])}, stayed {len(rt['stayed'])}, new {len(rt['new'])}</p>")
        items = ([("went", f) for f in rt["went"]] + [("stayed", f) for f in rt["stayed"]]
                 + [("new", f) for f in rt["new"]])
        if items:
            out.append("<ul>" + "".join(f"<li>{_e(k)}: {_e(_finding(f))}</li>" for k, f in items) + "</ul>")
    out.append("<h3>Evidence</h3>")
    if t["lookup"] != "ok":
        out.append(f'<p class="muted">{_e(LOOKUP_TEXT.get(t["lookup"], t["lookup"]))}</p>')
    else:
        out.append(f"<p>{_e(t['commits'])} commits in origin/main..refs/heads/{_e(t['branch'])}</p>")
        out.append("<ul>" + "".join(f"<li><code>{_e(p)}</code></li>" for p in t["evidence"]) + "</ul>"
                   if t["evidence"] else '<p class="muted">no evidence/ path changed</p>')
    out.append("</section>")
    return "".join(out)


def render(data: dict) -> str:
    """The page as one HTML string: no script, no link, no image, nothing loaded from outside the file."""
    homes = "; ".join(f"{h['label']} {h['config']}: " + (f"{h['sessions']} sessions" if h["read"] else "not read")
                      for h in data["homes"])
    head = (f"window {_time(data['since'], True)} to {_time(data['now'], True)} ({data['days']} days) · {homes} · "
            f"reviews in the window {data['reviews']}, tied to no branch here {data['reviews_untied']}")
    out = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
           f'<meta http-equiv="Content-Security-Policy" content="{_e(CSP)}">',
           f"<title>Task page {_e(os.path.basename(data['project']))}</title><style>{STYLE}</style></head>",
           "<body><main><header>", f"<h1>Task page &middot; {_e(data['project'])}</h1>",
           f'<p class="muted">{_e(head)}</p>']
    out += [f'<p class="muted">{_e(note)}</p>' for note in data.get("notes", [])]
    if data.get("branch_list") == "error":
        out.append('<p class="deny">git for-each-ref failed: the reviews tied to no branch here were not looked for '
                   "among branches with no session</p>")
    if data["files_not_read"] or data["lines_not_read"]:
        out.append(f'<p class="deny">not read: files {_e(data["files_not_read"])}, lines '
                   f'{_e(data["lines_not_read"])} (what they held is missing below)</p>')
    out.append("</header><h2>Tasks</h2>")
    if data["tasks"]:
        out.append('<div class="wide"><table><thead><tr><th>task</th><th>PR</th><th class="num">sessions</th>'
                   '<th class="num">cost</th><th class="num">asks</th><th class="num">denies</th>'
                   '<th class="num">reviews</th><th>last activity</th></tr></thead><tbody>')
        for n, t in enumerate(data["tasks"], 1):
            homes_of = [s["home"] for s in t["sessions"]]
            count = ", ".join(f"{homes_of.count(h)} {h}" for h in ("host", "box") if h in homes_of) or "none"
            out.append(f'<tr><td><a href="#task-{n}">{_e(t["branch"] or "(no branch)")}</a></td>'
                       f'<td>{_e(", ".join("#" + str(p) for p in t["prs"]) or "-")}</td>'
                       f'<td class="num">{_e(count)}</td><td class="num">{_e(ledger.fmt_cost(t["cost"]))}</td>'
                       f'<td class="num">{_e(t["asks"])}</td><td class="num">{_e(t["denies"])}</td>'
                       f'<td class="num">{_e(len(t["reviews"]))}</td><td>{_e(_time(t["end"]))}</td></tr>')
        out.append("</tbody></table></div>")
        out += [_task_section(n, t) for n, t in enumerate(data["tasks"], 1)]
    else:
        out.append(f'<p class="muted">no session of this project in the last {_e(data["days"])} days</p>')
    out.append("<h2>Notes</h2><ul>" + "".join(f"<li>{_e(line)}</li>" for line in LEGEND) + "</ul>")
    out.append("</main></body></html>\n")
    return "".join(out)


# ---- the page's own check ---------------------------------------------------------------------------------------

def check_page(page: str) -> list:
    """Every breach of the page's allowlist, as text; [] for a page that loads nothing from outside the file. The
    lists are written here and never taken from the renderer. html.parser reads the page, so escaped text is data
    and never counts; attribute values arrive unescaped and are checked as the browser would read them."""
    tags ={"html", "head", "meta", "title", "style", "body", "main", "header", "section", "div", "h1", "h2", "h3",
            "p", "table", "thead", "tbody", "tr", "th", "td", "details", "summary", "ul", "li", "code", "a"}
    attrs = {"html": {"lang"}, "meta": {"charset", "http-equiv", "content"}, "a": {"href"}}
    anywhere = {"class", "id"}
    banned = ("://", "url(", "url=", "@import", "\\")
    csp = "default-src 'none'; style-src 'unsafe-inline'"
    # The page opens with these, in this order, nothing between (not even whitespace): there every browser applies
    # the CSP tag, so the check needs no model of where a browser ends the head.
    opening = ["doctype", "html", "head", "meta charset", "meta csp"]
    breaches: list = []
    state = {"csp": 0, "in_style": False, "first": []}

    def loads(text: str) -> Optional[str]:
        low = text.lower()
        return next((b for b in banned if b in low), None)

    def seen(event: str) -> None:
        if len(state["first"]) < len(opening):
            state["first"].append(event)

    class Check(HTMLParser):
        def handle_starttag(self, tag, attributes):
            if tag not in tags:
                breaches.append(f"tag <{tag}> is not on the allowlist")
            for name, value in attributes:
                if name not in anywhere and name not in attrs.get(tag, ()):
                    breaches.append(f"attribute {name} on <{tag}> is not on the allowlist")
                hit = loads(value or "")
                if hit:
                    breaches.append(f"attribute {name} on <{tag}> holds {hit}")
                if name == "href" and not re.fullmatch(r"#[A-Za-z0-9_-]+", value or ""):  # each one: a browser
                    breaches.append("an href that is no # anchor")  # takes the first of two, dict() the last
            names, given = sorted(n for n, _ in attributes), dict(attributes)
            event = tag
            if tag == "meta":
                if names == ["charset"]:
                    event = "meta charset"
                elif names == ["content", "http-equiv"] and \
                        (given["http-equiv"] or "").lower() == "content-security-policy":
                    event = "meta csp"
                    state["csp"] += 1
                    if given["content"] != csp:
                        breaches.append(f"CSP tag with the content {given['content']!r}")
                else:
                    breaches.append(f"<meta> that is neither charset nor the CSP tag: {names}")
            seen(event)
            if tag == "style":
                state["in_style"] = True

        def handle_endtag(self, tag):
            seen("/" + tag)
            if tag == "style":
                state["in_style"] = False

        def handle_data(self, data):
            seen("text")
            if state["in_style"]:
                hit = loads(data)
                if hit:
                    breaches.append(f"<style> holds {hit}")

        def handle_comment(self, data):
            seen("comment")
            breaches.append("a comment (the renderer writes none)")

        def handle_decl(self, decl):
            seen("doctype" if decl.lower() == "doctype html" else "declaration")
            if decl.lower() != "doctype html":
                breaches.append(f"declaration <!{decl}>")

        def handle_pi(self, data):
            seen("processing instruction")
            breaches.append("a processing instruction")

        def unknown_decl(self, data):
            breaches.append("an unknown declaration")

    parser = Check()  # attribute values are unescaped either way; <style> text never is
    parser.feed(page)
    parser.close()
    if state["csp"] > 1:  # none at all breaks the opening
        breaches.append(f"the CSP tag appears {state['csp']} times, not once")
    if state["first"] != opening:
        breaches.append(f"the page opens with {state['first']}, not with {opening}")
    return breaches


# ---- the command ------------------------------------------------------------------------------------------------

def project_of(cwd: str) -> Optional[str]:
    """The main work tree of the repository `cwd` lies in, so a page run from a worktree is the page of the whole
    repository; None outside a repository (or in a bare one)."""
    code, out = run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    common = out.strip() if code == 0 else ""
    if not common:
        return None
    if os.path.basename(common) == ".git":
        return os.path.dirname(common)
    code, out = run_git(["rev-parse", "--show-toplevel"], cwd)  # a common dir elsewhere (--separate-git-dir)
    return out.strip() if code == 0 and out.strip() else None


def default_homes(project: str) -> tuple:
    """(homes, notes): the owner's Claude home, and the box's when the project has bin/box, since a box only clones
    the repository that starts it and tools/box is not in kit.manifest (box sessions hold no repository name)."""
    host = {"label": "host", "config": os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"),
            "telemetry": ledger.telemetry_dir(), "root": project, "results": None}
    if not os.path.isfile(os.path.join(project, "bin", "box")):
        return [host], ["box home not read: this repository has no bin/box, and a box only runs on the repository "
                        "that starts it"]
    base = os.path.expanduser("~/.agent-box")  # the folder tools/box/box.py keeps everything in
    claude_home = os.path.join(base, "claude-home")
    return [host, {"label": "box", "config": claude_home, "telemetry": os.path.join(claude_home, "telemetry"),
                   "root": BOX_ROOT, "results": os.path.join(base, "boxes")}], []


def inside_work_tree(folder: str) -> Optional[str]:
    """The nearest folder at or above `folder` that holds a .git entry, else None. Stricter than git's discovery on
    purpose: the refusal needs no git and no config, and an ownership or ceiling setting cannot turn it off."""
    here = os.path.realpath(folder)
    while True:
        if os.path.lexists(os.path.join(here, ".git")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up


def write_page(text: str, path: str) -> None:
    """A new file of mode 0600; an existing file (or a link in its place) raises FileExistsError and stays as it is."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    if hasattr(os, "fchmod"):  # the mode, whatever the umask
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def old_pages(folder: str, now: _dt.datetime) -> int:
    """How many pages of the default place are past RETENTION_DAYS, by the UTC time in their name; reads names only."""
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    old = 0
    for name in names:
        if not PAGE_NAME.fullmatch(name):
            continue
        try:
            when = _dt.datetime.strptime(name[:-len(".html")], "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
        except ValueError:  # digits that are no date: not a name this script wrote
            continue
        old += when < now - _dt.timedelta(days=RETENTION_DAYS)
    return old


def main(argv: list, out=None, err=None, cwd: Optional[str] = None, now: Optional[_dt.datetime] = None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    if argv and argv[0] in ("help", "-h", "--help"):
        out.write(__doc__.strip() + "\n")
        return 0
    ap = argparse.ArgumentParser(prog="page", add_help=False)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--session")
    ap.add_argument("--out")
    try:
        ns = ap.parse_args(argv)
    except SystemExit:  # argparse printed the usage line
        return 2
    if not 1 <= ns.days <= MAX_DAYS:
        err.write(f"page: --days is a whole number of days from 1 to {MAX_DAYS}\n")
        return 2
    if ns.session is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", ns.session):
        err.write("page: a session id holds only letters, digits, - and _\n")
        return 2
    try:
        cwd = cwd or os.getcwd()
    except FileNotFoundError:  # the folder was removed under the shell (a worktree gone)
        err.write("page: the current folder is gone; run it inside the repository whose tasks it shows\n")
        return 1
    project = project_of(cwd)
    if project is None:
        err.write("page: no git repository here; run it inside the repository whose tasks it shows\n")
        return 1
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if ns.out:
        path = os.path.abspath(os.path.expanduser(ns.out))
        folder = os.path.dirname(path)
    else:
        folder = os.path.join(ledger.telemetry_dir(), "pages")
        path = os.path.join(folder, now.strftime("%Y%m%dT%H%M%SZ") + ".html")
    tree = inside_work_tree(folder)
    if tree:
        err.write(f"page: refused: {folder} lies in the git work tree {tree}; the page is never committed, so it is "
                  "written outside any work tree\n")
        return 1
    if ns.out and not os.path.isdir(folder):
        err.write(f"page: no folder {folder}\n")
        return 1
    homes, notes = default_homes(project)
    data = collect(project, ns.days, homes, now=now, session=ns.session)
    data["notes"] = notes
    if ns.session:
        ids = {s["id"] for t in data["tasks"] for s in t["sessions"]}
        if len(ids) != 1:
            err.write(f"page: no session fits {ns.session} in the last {ns.days} days\n" if not ids else
                      f"page: {ns.session} fits {len(ids)} sessions; give more of the id\n")
            return 1
    text = render(data)
    breaches = check_page(text)
    if breaches:  # the renderer's own output must pass; a page that does not is never written
        err.write("page: refused, the page breaks its own check: " + "; ".join(breaches[:5]) + "\n")
        return 1
    try:
        if not ns.out:
            os.makedirs(folder, mode=0o700, exist_ok=True)
            os.chmod(folder, 0o700)  # also a folder made earlier with a wider mode
        write_page(text, path)
    except FileExistsError:
        err.write(f"page: {path} exists and is never overwritten; give another --out\n")
        return 1
    except OSError as exc:
        err.write(f"page: cannot write {path}: {exc}\n")
        return 1
    out.write(path + "\n")
    old = 0 if ns.out else old_pages(folder, now)
    if old:  # the owner deletes them: this script never removes a file
        err.write(f"page: {old} of the pages in {folder} are older than {RETENTION_DAYS} days, the retention of "
                  "a page; remove them\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
