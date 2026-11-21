"""guard 0.11.0 (tracker item #66): the held-out rows. The host session wrote them before the build and committed
only their sha256 (`heldout-0.11.0.sha256`, the branch's first commit); the sessions that built 0.11.0 did not see
them. The box profile needs a root-owned marker, which no test can make, so each row runs in a child process that
imports the guard from its file, replaces `box_facts` with the row's facts (the seam of D1) and calls `main` with
`hook pre --wrapper claude`; the event goes in on stdin as the harness sends it. Nothing the rows name is run."""
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROWS = HERE / "heldout-0.11.0.txt"
CLEARED = ("CLAUDE_CODE_REMOTE", "CLAUDE_PROJECT_DIR")
CHILD = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("guard", sys.argv[1])
g = importlib.util.module_from_spec(spec)
sys.modules["guard"] = g
spec.loader.exec_module(g)
facts = json.loads(os.environ.pop("HELDOUT_FACTS"))
if facts is not None:
    g.box_facts = lambda *a, **k: dict(facts)
sys.exit(g.main(["hook", "pre", "--wrapper", "claude"]))
'''
# Rows whose answer the review of 0.11.0 changed after the rows were hashed: a box merges no head the clone does
# not have, and the rows' SHA is no commit in their scratch repository (fix `_merge_paths_failed`). The file keeps
# the answer written before the build; here each change is named with the words its new answer must hold.
CHANGED_BY_REVIEW = {"X19": ("deny", "cannot find"), "X20": ("deny", "cannot find")}
VALID = {"dockerenv": True, "marker_exists": True,
         "marker": {"schema": "agent-box/1", "name": "t", "seat": "t", "image": "x", "judge": "x",
                    "boundary": "own", "firewall": "set", "started": "2026-11-20T00:00:00Z"},
         "marker_uid": 0, "marker_writable": False, "marker_dir_writable": False,
         "guard_writable": False, "euid": 1000}
VARIANTS = {"user-owned": {"marker_uid": 1000}, "writable": {"marker_writable": True},
            "dir-writable": {"marker_dir_writable": True}, "root": {"euid": 0},
            "no-dockerenv": {"dockerenv": False}, "guard-writable": {"guard_writable": True}}


def _rows():
    out = []
    for line in ROWS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            out.append(tuple(p.strip() for p in line.split(" | ", 4)))
    return out


def _facts(item):
    f = json.loads(json.dumps(VALID))
    if item == "no-marker":
        f.update(marker_exists=False, marker=None, marker_uid=None)
        return f
    v = item.split(":", 1)[1] if ":" in item else None
    if v in VARIANTS:
        f.update(VARIANTS[v])
    elif v == "marker-client":
        f["marker"]["boundary"] = "client"
    elif v == "bad-schema":
        f["marker"]["schema"] = "agent-box/0"
    elif v is not None:
        raise AssertionError(f"unknown box variant {v!r}")
    return f


def test_the_rows_are_the_ones_committed_before_the_code():
    want = (HERE / "heldout-0.11.0.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(ROWS.read_bytes()).hexdigest() == want


@pytest.mark.parametrize("rid, env, expect, tool, text", _rows(), ids=[r[0] for r in _rows()])
def test_heldout_row(rid, env, expect, tool, text, guard_path, tmp_path):
    repo, tel = tmp_path / "repo", tmp_path / "telemetry"
    (repo / ".claude").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "feat/x", str(repo)], check=True)
    cfg = {"boundary": "own", "protected_branches": ["main"]}
    e = {k: v for k, v in os.environ.items() if not k.startswith("KZ_") and k not in CLEARED}
    e["KZ_TELEMETRY_DIR"] = str(tel)
    facts = None
    for item in ([] if env == "-" else env.split(",")):
        if item == "box" or item.startswith("box:") or item == "no-marker":
            facts = _facts(item)
        elif item.startswith(("receipt=", "receipt2=")):
            key, val = item.split("=", 1)
            verdict, sha = val.split(":", 1)
            rdir = repo / ".git" / "fresh-review"
            rdir.mkdir(exist_ok=True)
            name = f"{sha}.json" if key == "receipt" else f"{sha}.2.json"
            (rdir / name).write_text(json.dumps({"sha": sha, "base": "main", "verdict": verdict, "findings": []}))
        elif item.startswith("rules_off="):
            e["KZ_RULES_OFF"] = item.split("=", 1)[1]
        elif item.startswith("local="):
            (repo / ".claude" / "guard.local.json").write_text(json.dumps({"rules_off": [item.split("=", 1)[1]]}))
        elif item.startswith("cfg="):
            k, v = item[4:].split(":", 1)
            cfg[k] = json.loads(v)
        elif item == "file=client":
            cfg["boundary"] = "client"
        elif item.split("=", 1)[0] in ("KZ_BOUNDARY", "KZ_SCRATCH_MD", "KZ_PROTECTED_BRANCHES"):
            k, v = item.split("=", 1)
            e[k] = v
        else:
            raise AssertionError(f"{rid}: unknown env item {item!r}")
    (repo / ".claude" / "guard.json").write_text(json.dumps(cfg))
    e["HELDOUT_FACTS"] = json.dumps(facts)
    tool_input = {"command": text} if tool == "Bash" else json.loads(text)
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(repo),
             "session_id": "heldout", "transcript_path": "/x", "permission_mode": "bypassPermissions",
             "tool_use_id": f"toolu_{rid}"}
    r = subprocess.run([sys.executable, "-c", CHILD, guard_path], input=json.dumps(event),
                       capture_output=True, text=True, env=e, cwd=str(repo))
    assert r.returncode in (0, 2), r.stderr
    if r.stdout.strip():
        got = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]
    else:
        log = tel / "decisions.jsonl"
        lines = [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
        got = "logged" if any(x.get("verdict") == "logged" for x in lines) else "silent"
    if rid in CHANGED_BY_REVIEW:
        expect, words = CHANGED_BY_REVIEW[rid]
        assert words in r.stdout, f"{rid}: {r.stdout or r.stderr}"
    assert got == expect, f"{rid}: {r.stdout or r.stderr}"
