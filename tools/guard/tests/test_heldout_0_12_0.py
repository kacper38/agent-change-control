"""guard 0.12.0 (tracker item #67): the held-out rows. The host session wrote them before the build and committed
only their sha256 (`heldout-0.12.0.sha256`, the branch's first commit); the session that built 0.12.0 did not see
them. Each row runs in a child process that imports the guard from its file, replaces `box_facts` with the row's
facts (valid box facts for `box`, no marker otherwise, as in heldout-0.11.0) and calls `main` with `hook pre`, or
`hook fan-out` for a SubagentStart row; the event goes in on stdin as the harness sends it. Nothing the rows name
is run.

A `box` row reads the configuration beside the guard (the judge's), not the scratch repository's. So that those
rows keep testing that, and not this repository's own `workflows` list (step 1.4 adds `review-panel` to it), a box
row runs a copy of the guard whose root holds this repository's `guard.json` with `workflows` set to [], as it is
at 0.12.0."""
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROWS = HERE / "heldout-0.12.0.txt"
REPO_CFG = HERE.parents[2] / ".claude" / "guard.json"
CLEARED = ("CLAUDE_CODE_REMOTE", "CLAUDE_PROJECT_DIR")
CHILD = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("guard", sys.argv[1])
g = importlib.util.module_from_spec(spec)
sys.modules["guard"] = g
spec.loader.exec_module(g)
facts = json.loads(os.environ.pop("HELDOUT_FACTS"))
g.box_facts = lambda *a, **k: dict(facts)
sys.exit(g.main(["hook", sys.argv[2], "--wrapper", "claude"]))
'''
VALID = {"dockerenv": True, "marker_exists": True,
         "marker": {"schema": "agent-box/1", "name": "t", "seat": "t", "image": "x", "judge": "x",
                    "boundary": "own", "firewall": "set", "started": "2026-11-20T00:00:00Z"},
         "marker_uid": 0, "marker_writable": False, "marker_dir_writable": False,
         "guard_writable": False, "euid": 1000}
NO_MARKER = dict(VALID, marker_exists=False, marker=None, marker_uid=None, dockerenv=False)
WF = "export const meta = {name: '%s', description: 'd'}\nawait agent('hi')\n"
# Rows whose answer guard 0.12.1 (item #69, the limit #67 carried to it) changed after the rows were hashed: a bare
# name on `workflows` binds no file, so it no longer starts unasked (test_guard_0121.py). The file keeps the answer
# written before 0.12.0 was built; here each change is named with the words its new answer must hold. What these
# rows held out, a listed workflow that starts unasked, is B01, B19, B13, B27 and B23 of test_guard_0121.py.
CHANGED_BY_0_12_1 = {"W01": ("ask", "without a sha256"), "W12": ("ask", "without a sha256"),
                     "W15": ("ask", "without a sha256"), "W16": ("deny", "without a sha256"),
                     "F10": ("ask", "without a sha256")}
ITEM = re.compile(r",(?=box|cloud|cfg=|localcfg=|rules_off=|file=|wf=|spawns=)")  # a comma in a JSON value stays


def _rows():
    out = []
    for line in ROWS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            out.append(tuple(p.strip() for p in line.split(" | ", 4)))
    return out


def _spawn_row(event, i, repo):
    return {"ts": "2026-11-21T00:00:00Z", "event": event, "harness": "claude", "session": "heldout",
            "agent": "python-engineer", "model": None, "agent_id": None if event == "PreToolUse" else f"s{i}",
            "cwd": str(repo)}


def _judge(guard_path, root):
    """A copy of the guard under `root`, beside this repository's guard.json with `workflows` as at 0.12.0."""
    (root / "tools" / "guard").mkdir(parents=True)
    (root / ".claude").mkdir()
    shutil.copyfile(guard_path, root / "tools" / "guard" / "guard.py")
    cfg = json.loads(REPO_CFG.read_text(encoding="utf-8"))
    cfg["workflows"] = []
    (root / ".claude" / "guard.json").write_text(json.dumps(cfg), encoding="utf-8")
    return str(root / "tools" / "guard" / "guard.py")


def test_the_rows_are_the_ones_committed_before_the_code():
    want = (HERE / "heldout-0.12.0.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(ROWS.read_bytes()).hexdigest() == want


@pytest.mark.parametrize("rid, env, expect, tool, text", _rows(), ids=[r[0] for r in _rows()])
def test_heldout_row(rid, env, expect, tool, text, guard_path, tmp_path):
    repo, tel = tmp_path / "repo", tmp_path / "telemetry"
    (repo / ".claude").mkdir(parents=True)
    tel.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feat/x", str(repo)], check=True)
    cfg = {"boundary": "own", "protected_branches": ["main"]}
    local = {}
    e = {k: v for k, v in os.environ.items() if not k.startswith("KZ_") and k not in CLEARED}
    e["KZ_TELEMETRY_DIR"] = str(tel)
    facts, guard = NO_MARKER, guard_path
    for item in ([] if env == "-" else ITEM.split(env)):
        if item == "box":
            facts, guard = VALID, _judge(guard_path, tmp_path / "judge")
        elif item == "cloud":
            e["CLAUDE_CODE_REMOTE"] = "true"
        elif item.startswith("cfg="):
            k, v = item[4:].split(":", 1)
            cfg[k] = json.loads(v)
        elif item.startswith("localcfg="):
            k, v = item[9:].split(":", 1)
            local[k] = json.loads(v)
        elif item.startswith("rules_off="):
            e["KZ_RULES_OFF"] = item.split("=", 1)[1]
        elif item == "file=client":
            cfg["boundary"] = "client"
        elif item.startswith("wf="):
            name = item[3:]
            (repo / ".claude" / "workflows").mkdir(exist_ok=True)
            (repo / ".claude" / "workflows" / f"{name}.js").write_text(WF % name, encoding="utf-8")
        elif item.startswith("spawns="):
            pre, start = (int(x) for x in item[7:].split(":"))
            rows = [_spawn_row("PreToolUse", i, repo) for i in range(pre)]
            rows += [_spawn_row("SubagentStart", i, repo) for i in range(start)]
            (tel / "spawns.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        else:
            raise AssertionError(f"{rid}: unknown env item {item!r}")
    (repo / ".claude" / "guard.json").write_text(json.dumps(cfg), encoding="utf-8")
    if local:
        (repo / ".claude" / "guard.local.json").write_text(json.dumps(local), encoding="utf-8")
    e["HELDOUT_FACTS"] = json.dumps(facts)
    base = {"cwd": str(repo), "session_id": "heldout", "transcript_path": "/x", "permission_mode": "bypassPermissions"}
    if tool == "SubagentStart":
        event, verb = dict(base, hook_event_name="SubagentStart", **json.loads(text)), "fan-out"
    else:
        tool_input = {"command": text} if tool == "Bash" else json.loads(text)
        event = dict(base, hook_event_name="PreToolUse", tool_name=tool, tool_input=tool_input,
                     tool_use_id=f"toolu_{rid}")
        verb = "pre"
    r = subprocess.run([sys.executable, "-c", CHILD, guard, verb], input=json.dumps(event),
                       capture_output=True, text=True, env=e, cwd=str(repo))
    assert r.returncode in (0, 2), r.stderr
    if expect.startswith("total="):
        assert not r.stdout.strip(), f"{rid}: {r.stdout}"
        last = json.loads((tel / "spawns.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        got = f"total={last.get('total')}"
    elif r.stdout.strip():
        got = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]
    else:
        log = tel / "decisions.jsonl"
        logged = log.read_text(encoding="utf-8") if log.exists() else ""
        lines = [json.loads(x) for x in logged.splitlines() if x.strip()]
        got = "logged" if any(x.get("verdict") == "logged" for x in lines) else "silent"
    if rid in CHANGED_BY_0_12_1:
        expect, words = CHANGED_BY_0_12_1[rid]
        assert words in r.stdout, f"{rid}: {r.stdout or r.stderr}"
    assert got == expect, f"{rid}: {r.stdout or r.stderr}"
