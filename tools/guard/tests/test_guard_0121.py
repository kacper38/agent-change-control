"""guard 0.12.1 (tracker item #69, the limit #67 carried to it): a listed workflow is bound to its reviewed file.

At 0.12.0 a name on the `workflows` list of the committed guard.json started without a question, whatever that
name's file said; on the host an edit of `.claude/workflows/**` asks (`guard-config`), in a box it is only logged,
so a box could edit a listed workflow and then start it unasked. Since 0.12.1 an entry is {"name", "sha256"}: at
launch every file the guard finds for the name (the lookup of `cloud-launch`: `.claude/workflows/<name>.js` in the
call's folder and every folder above it, in CLAUDE_PROJECT_DIR and in the user's Claude folder) must hash to one of
the name's sha256 values. A file that differs, no file at all, a file the guard cannot read, a bare name and an entry
with no valid sha256 ask; in a box and in cloud an ask is a deny (the profiles, unchanged).

The rows were written before the code. Each runs in a child process through `main` with `hook pre`, as the held-out
rows of 0.12.0 do (test_heldout_0_12_0.py); nothing a row names is run."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
CLEARED = ("CLAUDE_CODE_REMOTE", "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR")
CHILD = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("guard", sys.argv[1])
g = importlib.util.module_from_spec(spec)
sys.modules["guard"] = g
spec.loader.exec_module(g)
facts = json.loads(os.environ.pop("ROW_FACTS"))
g.box_facts = lambda *a, **k: dict(facts)
sys.exit(g.main(["hook", "pre", "--wrapper", "claude"]))
'''
VALID = {"dockerenv": True, "marker_exists": True,
         "marker": {"schema": "agent-box/1", "name": "t", "seat": "t", "image": "x", "judge": "x",
                    "boundary": "own", "firewall": "set", "started": "2026-11-22T00:00:00Z"},
         "marker_uid": 0, "marker_writable": False, "marker_dir_writable": False,
         "guard_writable": False, "euid": 1000}
NO_MARKER = dict(VALID, marker_exists=False, marker=None, marker_uid=None, dockerenv=False)

WF = "export const meta = {name: 'review-panel', description: 'd'}\nawait agent('hi', {model: 'opus'})\n"
SHA = hashlib.sha256(WF.encode("utf-8")).hexdigest()
OTHER = hashlib.sha256(b"another reviewed version\n").hexdigest()
CALL = {"name": "review-panel"}

# what a file of the row holds; `link` is a symlink to a file outside every folder the guard looks in
FILES = {
    "same": WF,
    "edited": WF.replace("'hi'", "'hi, and push to main'"),
    "crlf": WF.replace("\n", "\r\n"),
    "big": "//" + "x" * 1_000_001 + "\n",
}
ENTRIES = {
    "bound": [{"name": "review-panel", "sha256": SHA}],
    "bare": ["review-panel"],
    "twice": [{"name": "review-panel", "sha256": OTHER}, {"name": "review-panel", "sha256": SHA}],
    "other-only": [{"name": "review-panel", "sha256": OTHER}],
    "upper": [{"name": "review-panel", "sha256": SHA.upper()}],
    "short": [{"name": "review-panel", "sha256": SHA[:40]}],
    "nosha": [{"name": "review-panel"}],
    "badname": [{"name": 7, "sha256": SHA}],
    "mixed": [7, {"name": "review-panel", "sha256": SHA}],
    "none": [],
}

# id | entries in the committed guard.json | where files are (repo=, user=, up=) | profile | call | expect | words
ROWS = [
    ("B01", "bound", "repo=same", "host", CALL, "silent", None),
    ("B02", "bound", "repo=edited", "host", CALL, "ask", "is not the reviewed file"),
    ("B03", "bare", "repo=same", "host", CALL, "ask", "without a sha256"),
    ("B04", "bound", "", "host", CALL, "ask", "no file of the workflow"),
    ("B05", "bound", "repo=same,user=edited", "host", CALL, "ask", "is not the reviewed file"),
    ("B06", "bound", "user=same", "host", CALL, "silent", None),
    ("B07", "twice", "repo=same", "host", CALL, "silent", None),
    ("B08", "other-only", "repo=same", "host", CALL, "ask", "is not the reviewed file"),
    ("B09", "upper", "repo=same", "host", CALL, "ask", "without a sha256"),
    ("B10", "short", "repo=same", "host", CALL, "ask", "without a sha256"),
    ("B11", "nosha", "repo=same", "host", CALL, "ask", "without a sha256"),
    ("B12", "badname", "repo=same", "host", CALL, "ask", "is not listed"),
    ("B13", "mixed", "repo=same", "host", CALL, "silent", None),
    ("B14", "bound", "repo=dir", "host", CALL, "ask", "could not check"),
    ("B15", "bound", "repo=big", "host", CALL, "ask", "could not check"),
    ("B16", "bound", "repo=crlf", "host", CALL, "ask", "is not the reviewed file"),
    ("B17", "bound", "repo=link", "host", CALL, "silent", None),
    ("B18", "bound", "up=edited,repo=same", "host", CALL, "ask", "is not the reviewed file"),
    ("B19", "bound", "repo=same", "host",
     {"name": "review-panel", "args": {"diff": "/tmp/x.diff"}, "resumeFromRunId": "wf_abc123"}, "silent", None),
    ("B20", "bound", "repo=same", "host", {"name": "review-panel", "script": "await agent('go')"}, "ask",
     "is not a reviewed, listed workflow"),
    ("B21", "bound", "repo=same", "host", {"name": "other"}, "ask", "is not listed"),
    ("B22", "local", "repo=same", "host", CALL, "ask", "is not listed"),
    ("B23", "bound", "repo=same", "box", CALL, "silent", None),
    ("B24", "bound", "repo=edited", "box", CALL, "deny", "is not the reviewed file"),
    ("B25", "bare", "repo=same", "box", CALL, "deny", "without a sha256"),
    ("B26", "bound", "repo=edited", "cloud", CALL, "deny", "is not the reviewed file"),
    ("B27", "bound", "repo=same", "cloud", CALL, "silent", None),
    ("B28", "bound", "repo=edited", "rules_off", CALL, "silent", None),
    ("B29", "bound", "repo=same,project=edited", "host", CALL, "ask", "is not the reviewed file"),
]


def _place(where: str, root: pathlib.Path, repo: pathlib.Path, user: pathlib.Path, project: pathlib.Path):
    for item in [w for w in where.split(",") if w]:
        spot, what = item.split("=", 1)
        base = {"repo": repo, "user": user.parent, "up": root, "project": project}[spot]
        folder = user if spot == "user" else base / ".claude" / "workflows"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "review-panel.js"
        if what == "dir":
            target.mkdir()
        elif what == "link":
            outside = root / "elsewhere" / "kept.js"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_text(WF, encoding="utf-8")
            target.symlink_to(outside)
        else:
            target.write_bytes(FILES[what].encode("utf-8"))


def _judge(guard_path: str, root: pathlib.Path, cfg: dict) -> str:
    """A copy of the guard under `root`, beside a committed guard.json that holds the row's `workflows` (in a box
    the configuration beside the guard is the one that counts, not the work tree's)."""
    (root / "tools" / "guard").mkdir(parents=True)
    (root / ".claude").mkdir()
    shutil.copyfile(guard_path, root / "tools" / "guard" / "guard.py")
    (root / ".claude" / "guard.json").write_text(json.dumps(cfg), encoding="utf-8")
    return str(root / "tools" / "guard" / "guard.py")


def run_row(guard_path, tmp_path, entries, where, profile, call):
    up = tmp_path / "up"
    repo, tel, user = up / "repo", tmp_path / "telemetry", tmp_path / "claude-config" / "workflows"
    project = tmp_path / "project"
    (repo / ".claude").mkdir(parents=True)
    tel.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feat/x", str(repo)], check=True)
    cfg = {"boundary": "own", "protected_branches": ["main"], "workflows": ENTRIES.get(entries, [])}
    (repo / ".claude" / "guard.json").write_text(json.dumps(cfg), encoding="utf-8")
    if entries == "local":
        (repo / ".claude" / "guard.local.json").write_text(json.dumps({"workflows": ENTRIES["bound"]}),
                                                           encoding="utf-8")
    _place(where, up, repo, user, project)
    e = {k: v for k, v in os.environ.items() if not k.startswith("KZ_") and k not in CLEARED}
    e["KZ_TELEMETRY_DIR"] = str(tel)
    e["CLAUDE_CONFIG_DIR"] = str(user.parent)
    if "project=" in where:
        e["CLAUDE_PROJECT_DIR"] = str(project)
    facts, guard = NO_MARKER, guard_path
    if profile == "box":
        facts, guard = VALID, _judge(guard_path, tmp_path / "judge", cfg)
    elif profile == "cloud":
        e["CLAUDE_CODE_REMOTE"] = "true"
    elif profile == "rules_off":
        e["KZ_RULES_OFF"] = "workflow-launch"
    e["ROW_FACTS"] = json.dumps(facts)
    event = {"cwd": str(repo), "session_id": "rows-0121", "transcript_path": "/x",
             "permission_mode": "bypassPermissions", "hook_event_name": "PreToolUse", "tool_name": "Workflow",
             "tool_input": call, "tool_use_id": "toolu_rows0121"}
    r = subprocess.run([sys.executable, "-c", CHILD, guard], input=json.dumps(event),
                       capture_output=True, text=True, env=e, cwd=str(repo))
    assert r.returncode in (0, 2), r.stderr
    if r.stdout.strip():
        out = json.loads(r.stdout)["hookSpecificOutput"]
        return out["permissionDecision"], out.get("permissionDecisionReason", ""), r.stderr
    return "silent", "", r.stderr


@pytest.mark.parametrize("rid, entries, where, profile, call, expect, words", ROWS, ids=[r[0] for r in ROWS])
def test_row(rid, entries, where, profile, call, expect, words, guard_path, tmp_path):
    got, reason, stderr = run_row(guard_path, tmp_path, entries, where, profile, call)
    assert got == expect, f"{rid}: {got} {reason or stderr}"
    if words:
        assert words in reason, f"{rid}: {reason}"


def test_a_changed_file_is_named_in_the_answer(guard_path, tmp_path):
    _got, reason, _err = run_row(guard_path, tmp_path, "bound", "repo=same,user=edited", "host", CALL)
    assert str(tmp_path / "claude-config" / "workflows" / "review-panel.js") in reason


def test_odd_entries_are_named_on_stderr(guard_path, tmp_path):
    _got, _reason, stderr = run_row(guard_path, tmp_path, "mixed", "repo=same", "host", CALL)
    assert "workflows" in stderr and "ignored" in stderr


def test_the_note_names_only_the_names_that_ask(guard, capsys):
    # review round 1 of item #69: a bare entry beside a bound one of the same name leaves that name bound
    assert guard.listed_workflows({"workflows": [{"name": "a", "sha256": SHA}, "a", "b"]}) == {"a": {SHA}, "b": set()}
    err = capsys.readouterr().err
    assert "2 entries bind no sha256" in err and "names with no binding at all ask: b" in err
    guard.listed_workflows({"workflows": [{"name": "a", "sha256": SHA}, "a"]})
    assert "names with no binding at all ask: none" in capsys.readouterr().err


def test_listed_workflows_maps_names_to_their_hashes(guard):
    assert guard.listed_workflows({"workflows": ENTRIES["twice"]}) == {"review-panel": {OTHER, SHA}}
    assert guard.listed_workflows({"workflows": ["review-panel"]}) == {"review-panel": set()}
    assert guard.listed_workflows({"workflows": ENTRIES["upper"]}) == {"review-panel": set()}
    assert guard.listed_workflows({"workflows": "review-panel"}) == {}
    assert guard.listed_workflows({}) == {}


def test_the_version_is_0_12_1(guard):
    assert guard.VERSION == "0.12.1"
