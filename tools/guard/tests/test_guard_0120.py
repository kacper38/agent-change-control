"""guard 0.12.0 (tracker item #67, plan steps 1.1, 1.2): the rule `workflow-launch`, workflow agents in the fan-out
total, `.claude/workflows/**` in guard-config, and never weaker. These rows were written before the code (D7 of the
host's design); the commands are data, nothing runs.

Never weaker (criterion 7, D6). baseline-0.11.0.jsonl holds, per input, what guard 0.11.0 (commit 1b35952)
answered: `pre`, the combined answer of `hook pre` on a machine with no marker; `rule`, the answer of the rule the
input names (for rule `shell` the strongest shell rule); `box`, the answer of `hook pre` behind a valid box marker
(`logged` when the box let the call run and wrote a line). It was written by this module run as a script:

    git show 1b35952:tools/guard/guard.py > /tmp/guard-0.11.0.py
    python3 tools/guard/tests/test_guard_0120.py --write /tmp/guard-0.11.0.py

Covered inputs: the corpus of test_box_profile.py (the corpus of test_never_weaker.py, every fixture on disk but
those of `workflow-launch`, and the text tables of 0.10.0; their docstrings say what that leaves out and why), plus
the text tables 0.11.0 added: the local and remote deletes of test_box_profile.py (LOCAL, REMOTE), as shell
inputs of delete-guard. Each input is judged as test_box_profile.py judges it. Not covered: the other row lists of
test_box_profile.py (ASK_ROWS, SCRIPT_ROWS, MERGE_ROWS, PATH_ROWS and the marker rows build a judge folder, a work
clone or a repository for their row: code, not text tables; each keeps its own expectation and runs on its own),
the held-out rows of 0.10.0 and 0.11.0 (they run through the real entry point in their own modules), the fixtures
of `workflow-launch` (no such rule at 0.11.0; test_fixtures.py runs them) and the cloud profile (it is the host's
answer with every ask turned into a deny by PROFILES, which 0.12.0 does not change; the host equality covers it).

Every input answers exactly as 0.11.0, apart from the inputs in CHANGED, each with the decision that changes it;
a listed change must be stricter, an unlisted change fails, and a listed change that did not happen fails too.

Row ids in the tables below: W the rule workflow-launch (D3, D11), F the fan-out total (D4), G guard-config (D5).
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASELINE = HERE / "baseline-0.11.0.jsonl"
ORDER = {"silent": 0, "logged": 0, "ask": 1, "deny": 2}  # logged: the box let it run, as silent let it run on a host


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BP = _load("_g0120_box_profile", HERE / "test_box_profile.py")

# ----------------------------------------------------------------------------
# D6: never weaker
# ----------------------------------------------------------------------------

# id | which (pre, rule or box) | 0.11.0 | 0.12.0 | decision. A1: the Workflow calls of the corpus that are no
# listed workflow (none is listed in the corpus' configuration) now ask, in a box they are denied.
CHANGED = r"""
fixture:cloud-launch/claude/allow/09-workflow-review-panel.json | pre | silent | ask | D3: a name not in `workflows`
fixture:cloud-launch/claude/allow/09-workflow-review-panel.json | box | silent | deny | D3: a name not in `workflows`
test_guard_0100.TOOL_ROWS:21 | pre | silent | ask | D3: an inline script is not a listed workflow
test_guard_0100.TOOL_ROWS:21 | box | silent | deny | D3: an inline script is not a listed workflow
test_guard_0100.TOOL_ROWS:22 | pre | silent | ask | D3: an inline script is not a listed workflow
test_guard_0100.TOOL_ROWS:22 | box | silent | deny | D3: an inline script is not a listed workflow
test_guard_0100.TOOL_ROWS:23 | pre | silent | ask | D3: a name not in `workflows`
test_guard_0100.TOOL_ROWS:23 | box | silent | deny | D3: a name not in `workflows`
"""


def _changed() -> dict:
    out = {}
    for line in CHANGED.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        rid, which, old, new, why = (p.strip() for p in line.split(" | ", 4))
        assert ORDER[new] > ORDER[old], f"a listed change must be stricter: {line}"
        assert (rid, which) not in out, f"listed twice: {line}"
        out[(rid, which)] = (old, new, why)
    return out


def inputs() -> list:
    out = list(BP.inputs())
    for n, (_tag, command) in enumerate(BP.DELETE_ROWS):
        out.append((f"test_box_profile.DELETE_ROWS:{n}",
                    {"branch": "feat/x", "boundary": "own", "rule": "delete-guard", "command": command}))
    return out


def answers(guard, inp: dict) -> dict:
    pre, rule = BP.answers(guard, inp, BP.NO_MARKER)
    box, _rule = BP.answers(guard, inp, BP.VALID)
    return {"pre": pre, "rule": rule, "box": box}


def _baseline() -> list:
    return [json.loads(ln) for ln in BASELINE.read_text().splitlines() if ln.strip()]


def test_the_baseline_covers_the_corpus_of_0110():
    ids = [row["id"] for row in _baseline()]
    assert len(ids) == len(set(ids)) and len(ids) > 4000, len(ids)
    assert {i.split(":")[0] for i in ids if not i.startswith("fixture:")} >= {
        "test_table_forms.ROWS_B", "test_guard_0100.TOOL_ROWS", "test_box_profile.DELETE_ROWS"}
    assert not [i for i in ids if i.startswith("fixture:workflow-launch/")]
    assert sorted(ids) == sorted(rid for rid, _inp in inputs()), "the corpus moved: write the baseline again"
    corpus = {rid: json.loads(json.dumps(inp)) for rid, inp in inputs()}  # as the writer stored it
    moved = [row["id"] for row in _baseline() if row["in"] != corpus[row["id"]]]
    assert moved == [], f"a baseline input is not its corpus input: {moved[:5]}"


def test_the_baseline_is_the_file_its_hash_names():
    # the first review: the oracle of the never-weaker check is left out of the review diff (1.26 million
    # characters), so its content is pinned by the sha256 the writer stores beside it
    want = (HERE / "baseline-0.11.0.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == want


def test_every_0110_answer_holds(guard):
    changed = _changed()
    weaker, unlisted, wrong, seen = [], [], [], set()
    for row in _baseline():
        now = answers(guard, row["in"])
        for which in ("pre", "rule", "box"):
            old, new = row[which], now[which]
            if new == old:
                continue
            key = (row["id"], which)
            seen.add(key)
            what = f"{row['id']} {which}: {old} -> {new} {json.dumps(row['in'])}"
            if ORDER[new] < ORDER[old] or (new, old) == ("silent", "logged"):
                weaker.append(what)
            elif key not in changed:
                unlisted.append(what)
            elif changed[key][:2] != (old, new):
                wrong.append(f"{what}; listed as {changed[key][0]} -> {changed[key][1]}")
    missing = [f"{rid} {which}: listed {old} -> {new} ({why}), did not happen"
               for (rid, which), (old, new, why) in changed.items() if (rid, which) not in seen]
    assert weaker == [], "a move toward silence:\n" + "\n".join(weaker)
    assert unlisted == [] and wrong == [] and missing == [], "\n".join(unlisted + wrong + missing)


def test_every_changed_input_is_a_workflow_call():
    rows = {row["id"]: row["in"] for row in _baseline()}
    for rid, _which in _changed():
        inp = rows[rid]
        tool = inp.get("call") or inp.get("fixture", {}).get("tool_name")
        assert tool == "Workflow", (rid, inp)


def test_the_version_is_0_12_0(guard):
    # the guard is 0.12.1 since item #69 (test_guard_0121.py)
    assert guard.VERSION == "0.12.1"


# ----------------------------------------------------------------------------
# Helpers: a judge folder, a work clone, one event through run_hook under a profile
# ----------------------------------------------------------------------------

WORK_POLICY = {"boundary": "own", "protected_branches": ["main"], "host_install": "ask"}


@pytest.fixture
def judge(tmp_path):
    root = tmp_path / "judge"
    BP._write_json(root / ".claude" / "guard.json", BP.JUDGE_POLICY)
    return root


@pytest.fixture
def work(tmp_path):
    root = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "feat/x", str(root)], check=True)
    BP._write_json(root / ".claude" / "guard.json", WORK_POLICY)
    (root / "w.js").write_text("await agent('go')\n")
    return root


def _setup(setup: str, judge, work) -> None:
    """`work.KEY=JSON; judge.KEY=JSON; local.KEY=JSON`: a key of the work clone's guard.json, the judge's, or the
    work clone's guard.local.json. `file.PATH=JSON` and `user.PATH=JSON` write the JSON string as a file at PATH in
    the work clone or in the user's Claude folder (CLAUDE_CONFIG_DIR, set by _profile)."""
    for item in (p.strip() for p in setup.split(";")):
        if not item or item == "-":
            continue
        key, _, value = item.partition("=")
        where, _, name = key.partition(".")
        if where in ("file", "user"):
            path = (work if where == "file" else judge.parent / "config") / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.loads(value))
            continue
        path = {"work": work / ".claude" / "guard.json", "judge": judge / ".claude" / "guard.json",
                "local": work / ".claude" / "guard.local.json"}[where]
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = json.loads(value)
        BP._write_json(path, data)


def _profile(guard, monkeypatch, judge, name: str) -> None:
    facts = BP.VALID if name == "box" else BP.NO_MARKER
    monkeypatch.setattr(guard, "box_facts", lambda: copy.deepcopy(facts))
    monkeypatch.setattr(guard, "guard_root", lambda: str(judge))
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "feat/x")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(judge.parent / "config"))  # the user's folder: empty but for a row
    if name == "cloud":
        monkeypatch.setenv("CLAUDE_CODE_REMOTE", "1")


def _word(final, rows) -> str:
    """deny | ask | logged | skipped (silent, a rules_off line) | silent (silent, no line)."""
    if final is not None:
        return final[0]
    verdicts = [r["verdict"] for r in rows]
    return {(): "silent", ("logged",): "logged", ("skipped",): "skipped"}.get(tuple(verdicts), f"silent+{rows}")


def _rows(text: str) -> list:
    out = []
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            out.append(tuple(p.strip() for p in line.split(" | ")))
    return out


# ----------------------------------------------------------------------------
# D3, D11: workflow-launch, through `hook pre`, under each profile
# ----------------------------------------------------------------------------

LISTED = 'work.workflows=["review-panel"]; judge.workflows=["review-panel"]'
# id | profile | setup (the lists) | expected | rule that must be on the decision line (- none) | tool | input
WORKFLOW_ROWS = r"""
# --- a listed name: no answer (the guard never says allow), in every profile; args and a run id change nothing
W1 | host | work.workflows=["review-panel"] | silent | - | Workflow | {"name": "review-panel"}
W1 | cloud | work.workflows=["review-panel"] | silent | - | Workflow | {"name": "review-panel"}
W1 | box | judge.workflows=["review-panel"] | silent | - | Workflow | {"name": "review-panel"}
W1 | host | work.workflows=["review-panel"] | silent | - | Workflow | {"name": "review-panel", "args": {"pr": 3}}
W1 | host | work.workflows=["review-panel"] | silent | - | Workflow | {"name": "review-panel", "resumeFromRunId": "wf_abc123"}
W1 | host | work.workflows=[5, "review-panel"] | silent | - | Workflow | {"name": "review-panel"}
# --- an unknown name: ask on the host, a deny in cloud and in a box
W2 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "other"}
W2 | cloud | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"name": "other"}
W2 | box | judge.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"name": "other"}
W2 | host | - | ask | workflow-launch | Workflow | {"name": "review-panel"}
W2 | box | - | deny | workflow-launch | Workflow | {"name": "review-panel"}
W2 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "other", "resumeFromRunId": "wf_abc123"}
W2 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "other", "args": "review-panel"}
W2 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "Review-Panel"}
W2 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "review-panel "}
W2 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": ".claude/workflows/review-panel"}
W2 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "review-panel.js"}
W2 | host | work.workflows="review-panel" | ask | workflow-launch | Workflow | {"name": "review-panel"}
W2 | host | work.workflows={"review-panel": true} | ask | workflow-launch | Workflow | {"name": "review-panel"}
# the list is the committed one: guard.local.json carries only rules_off; in a box only the judge's counts
W2 | host | local.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "review-panel"}
W2 | box | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"name": "review-panel"}
# --- an inline script or a script file: not the reviewed, listed workflow, also beside a listed name
W3 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"script": "await agent('go')"}
W3 | cloud | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"script": "await agent('go')"}
W3 | box | judge.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"script": "await agent('go')"}
W3 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "review-panel", "script": "await agent('go')"}
W3 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"script": ""}
W3 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"script": null}
W4 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"scriptPath": "w.js"}
W4 | cloud | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"scriptPath": "w.js"}
W4 | box | judge.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"scriptPath": "w.js"}
W4 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": "review-panel", "scriptPath": "w.js"}
# --- a crash of the reading (no name, not a string, empty): an ask built from READER_MSG, a deny in a box
W5 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": 5}
W5 | cloud | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"name": 5}
W5 | box | judge.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"name": 5}
W5 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {}
W5 | cloud | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {}
W5 | box | judge.workflows=["review-panel"] | deny | workflow-launch | Workflow | {}
W5 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": ""}
W5 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": null}
W5 | host | work.workflows=["review-panel"] | ask | workflow-launch | Workflow | {"name": ["review-panel"]}
# --- the deny (A3): a script whose agent asks for isolation remote; workflow-launch asks, cloud-launch denies
W6 | host | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"script": "await agent('go', { isolation: 'remote' })"}
W6 | host | work.workflows=["review-panel"] | deny | cloud-launch | Workflow | {"script": "await agent('go', { isolation: 'remote' })"}
W6 | cloud | work.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"script": "await agent('go', { isolation: 'remote' })"}
W6 | box | judge.workflows=["review-panel"] | deny | workflow-launch | Workflow | {"script": "await agent('go', { isolation: 'remote' })"}
# --- rules_off: on the host in an own repository it silences the ask (a skipped line); in a client repository,
# in cloud and in a box it changes nothing
W7 | host | work.rules_off=["workflow-launch"] | skipped | - | Workflow | {"name": "other"}
W7 | host | work.rules_off=["workflow-launch"] | skipped | - | Workflow | {"script": "await agent('go')"}
W7 | host | local.rules_off=["workflow-launch"] | skipped | - | Workflow | {"name": "other"}
W7 | host | work.rules_off=["workflow-launch"]; work.boundary="client" | ask | workflow-launch | Workflow | {"name": "other"}
W7 | cloud | work.rules_off=["workflow-launch"] | deny | workflow-launch | Workflow | {"name": "other"}
W7 | box | work.rules_off=["workflow-launch"]; judge.rules_off=["workflow-launch"] | deny | workflow-launch | Workflow | {"name": "other"}
# --- a name is resolved (0.10.0's named limit, closed in the first review): cloud-launch reads every
# .claude/workflows/<name>.js above the call's folder and in the user's Claude folder, as it reads a scriptPath;
# none found answers as 0.11.0 did
W9 | host | work.workflows=["review-panel"]; file..claude/workflows/review-panel.js="await agent('go')\n" | silent | - | Workflow | {"name": "review-panel"}
W9 | host | work.workflows=["review-panel"]; file..claude/workflows/review-panel.js="await agent('go', { isolation: 'remote' })\n" | deny | cloud-launch | Workflow | {"name": "review-panel"}
W9 | cloud | work.workflows=["review-panel"]; file..claude/workflows/review-panel.js="await agent('go', { isolation: 'remote' })\n" | deny | cloud-launch | Workflow | {"name": "review-panel"}
W9 | box | judge.workflows=["review-panel"]; file..claude/workflows/review-panel.js="await agent('go', { isolation: 'remote' })\n" | deny | cloud-launch | Workflow | {"name": "review-panel"}
W9 | host | work.workflows=["review-panel"]; user.workflows/review-panel.js="await agent('go', { isolation: 'remote' })\n" | deny | cloud-launch | Workflow | {"name": "review-panel"}
W9 | box | judge.workflows=["review-panel"]; user.workflows/review-panel.js="await agent('go', { isolation: 'remote' })\n" | deny | cloud-launch | Workflow | {"name": "review-panel"}
W9 | host | work.workflows=["review-panel"]; file..claude/workflows/review-panel.js/x="a folder" | ask | cloud-launch | Workflow | {"name": "review-panel"}
W9 | box | judge.workflows=["review-panel"]; file..claude/workflows/review-panel.js/x="a folder" | deny | cloud-launch | Workflow | {"name": "review-panel"}
W9 | host | work.workflows=["../review-panel"] | ask | cloud-launch | Workflow | {"name": "../review-panel"}
W9 | host | work.workflows=[".review-panel"] | ask | cloud-launch | Workflow | {"name": ".review-panel"}
W9 | host | work.workflows=["review-panel"]; file..claude/workflows/other.js="await agent('go', { isolation: 'remote' })\n" | silent | - | Workflow | {"name": "review-panel"}
# --- D11: a saved workflow started through Skill ends in a Workflow call; the Skill call answers as at 0.11.0
W8 | host | - | silent | - | Skill | {"skill": "review-panel"}
W8 | host | work.workflows=["review-panel"] | silent | - | Skill | {"skill": "review-panel", "args": "3"}
W8 | box | - | silent | - | Skill | {"skill": "review-panel"}
"""  # noqa: E501 (a row holds its input as written)
WORKFLOW_TABLE = _rows(WORKFLOW_ROWS)
# guard 0.12.1 (item #69): a bare name on `workflows` binds no file and no longer starts unasked. The table keeps the
# answers of 0.12.0; these rows answer as named, with the words the new answer holds. A bound name that starts
# unasked in every profile is B01, B19, B27 and B23 of test_guard_0121.py.
CHANGED_BY_0_12_1 = {
    "W1-host-0": "ask", "W1-cloud-1": "deny", "W1-box-2": "deny", "W1-host-3": "ask", "W1-host-4": "ask",
    "W1-host-5": "ask", "W9-host-50": "ask", "W9-host-60": "ask",
}


@pytest.mark.parametrize("rid, prof, setup, expected, rule, tool, text", WORKFLOW_TABLE,
                         ids=[f"{r[0]}-{r[1]}-{n}" for n, r in enumerate(WORKFLOW_TABLE)])
def test_the_workflow_row(guard, monkeypatch, judge, work, request, rid, prof, setup, expected, rule, tool, text):
    _setup(setup, judge, work)
    _profile(guard, monkeypatch, judge, prof)
    final, rows = BP._hook(guard, monkeypatch, BP._tool(work, tool, json.loads(text)))
    row_id = request.node.callspec.id
    if row_id in CHANGED_BY_0_12_1:
        expected, rule = CHANGED_BY_0_12_1[row_id], "workflow-launch"
        assert "without a sha256" in final[1], final
    assert _word(final, rows) == expected, (final, rows)
    if rule != "-":
        (line,) = [r for r in rows if r["verdict"] == expected]
        assert rule in line["rules"], line
        assert line["profile"] == prof, line
    if prof == "box" and expected == "deny":  # the box's deny of an ask, but where cloud-launch itself denies first
        head, tail = guard.CLOUD_LAUNCH_MSG.split("{what}")
        if "isolation: 'remote'" in setup + text:
            assert final[1].startswith(head) and tail.split(";")[0] in final[1], final
        else:
            assert final[1].startswith(BP.BOX_PREFIX), final


def test_a_named_workflow_is_read_above_the_call_and_in_the_home_folder(guard, monkeypatch, tmp_path):
    """W9's cases a row cannot hold: a call from a subfolder reads the project's file, so does a call from outside
    the project once the harness names it (CLAUDE_PROJECT_DIR), and with no CLAUDE_CONFIG_DIR the user's folder is
    ~/.claude."""
    remote = "await agent('go', { isolation: 'remote' })\n"
    proj, home = tmp_path / "proj", tmp_path / "home"
    (proj / "sub" / "dir").mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))

    def launch(cwd):
        return guard.rule_cloud_launch(guard.Event({
            "hook_event_name": "PreToolUse", "tool_name": "Workflow", "tool_input": {"name": "rp"},
            "cwd": str(cwd), "session_id": "s1", "transcript_path": "/t"}), {})

    assert launch(proj / "sub" / "dir") is None  # no file anywhere: as at 0.11.0
    script = proj / ".claude" / "workflows" / "rp.js"
    script.parent.mkdir(parents=True)
    script.write_text(remote)
    assert launch(proj / "sub" / "dir")[0] == "deny"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert launch(elsewhere) is None  # outside the project, and no project folder named
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    assert launch(elsewhere)[0] == "deny"
    script.write_text("await agent('go')\n")
    assert launch(proj / "sub" / "dir") is None
    (home / ".claude" / "workflows").mkdir(parents=True)
    (home / ".claude" / "workflows" / "rp.js").write_text(remote)
    assert launch(proj)[0] == "deny"


def _wf(guard, tool_input, event="PreToolUse", tool="Workflow"):
    return guard.Event({"hook_event_name": event, "tool_name": tool, "tool_input": tool_input, "cwd": "/nonexistent",
                        "session_id": "s1", "transcript_path": "/t"})


def test_the_rule_is_registered_after_cloud_launch(guard):
    names = list(guard.RULES)
    assert names.index("workflow-launch") == names.index("cloud-launch") + 1
    assert guard.PRE_RULES == names
    assert guard.BOX_TABLE["workflow-launch"] == "deny"
    assert guard.DEFAULTS["workflows"] == []
    # step 1.4 (item #69) lists review-panel, bound to its file since 0.12.1 (test_workflow_pins.py checks the hash)
    assert [e["name"] for e in json.loads((ROOT / ".claude" / "guard.json").read_text())["workflows"]] == [
        "review-panel"]
    assert guard.KNOWN_CLAUDE_TOOLS["Workflow"] == "judged"


def test_the_messages_name_what_the_list_is(guard):
    cfg = dict(guard.DEFAULTS, workflows=["review-panel"])
    verdict, reason = guard.RULES["workflow-launch"](_wf(guard, {"name": "other"}), cfg)
    assert (verdict, reason) == ("ask", guard.WORKFLOW_UNKNOWN_MSG.format(name="other"))
    assert "`other`" in reason and "`workflows`" in reason and ".claude/guard.json" in reason
    assert guard.RULES["workflow-launch"](_wf(guard, {"script": "x"}), cfg) == ("ask", guard.WORKFLOW_SCRIPT_MSG)
    assert guard.RULES["workflow-launch"](_wf(guard, {"scriptPath": "x.js"}), cfg) == ("ask", guard.WORKFLOW_SCRIPT_MSG)
    verdict, reason = guard.RULES["workflow-launch"](_wf(guard, {"name": 5}), cfg)
    assert verdict == "ask" and guard._is_reader_reason(reason) and reason.startswith("workflow-launch: ")


@pytest.mark.parametrize("event, tool, tool_input", [
    ("PostToolUse", "Workflow", {"name": "other"}),
    ("PostToolUseFailure", "Workflow", {"script": "x"}),
    ("SubagentStart", "", None),
    ("PreToolUse", "Bash", {"command": "echo workflow"}),
    ("PreToolUse", "Skill", {"skill": "other"}),
    ("PreToolUse", "Agent", {"description": "d", "prompt": "p", "name": "other"}),
])
def test_every_other_event_and_kind_is_none(guard, event, tool, tool_input):
    cfg = dict(guard.DEFAULTS)
    assert guard.RULES["workflow-launch"](_wf(guard, tool_input, event, tool), cfg) is None


def test_a_list_that_is_not_one_of_names_is_read_with_a_note(guard, capsys):
    rule = guard.RULES["workflow-launch"]
    # 0.12.1 (item #69): the bare name "a" binds no file, so it asks as well (it was None at 0.12.0)
    assert rule(_wf(guard, {"name": "a"}), dict(guard.DEFAULTS, workflows=[5, "a"])) == (
        "ask", guard.WORKFLOW_UNBOUND_MSG.format(name="a"))
    assert "workflows" in capsys.readouterr().err
    assert rule(_wf(guard, {"name": "a"}), dict(guard.DEFAULTS, workflows="a"))[0] == "ask"
    assert "workflows" in capsys.readouterr().err
    assert rule(_wf(guard, {"name": "a"}), {k: v for k, v in guard.DEFAULTS.items() if k != "workflows"})[0] == "ask"
    assert capsys.readouterr().err == "", "a missing list is the empty list, no note"


def test_the_rule_is_a_pure_verdict(guard, tmp_path):
    cfg = dict(guard.DEFAULTS, telemetry_dir=str(tmp_path / "t"), workflows=["a"])
    guard.RULES["workflow-launch"](_wf(guard, {"name": "a"}), cfg)
    guard.RULES["workflow-launch"](_wf(guard, {"name": "b"}), cfg)
    assert not (tmp_path / "t").exists(), "workflow-launch writes nothing; fan-out logs the launch"


# ----------------------------------------------------------------------------
# D4: workflow agents count in the fan-out total
# ----------------------------------------------------------------------------

def _seed_row(token: str, session: str = "s1") -> dict:
    """One spawn log row. L: a PreToolUse row of 0.11.0 (no tool, no total); P=n, T=n, C=n: a PreToolUse row of
    Agent, Task, Copilot's task with total n; S: a SubagentStart row; W: a Workflow PreToolUse row; O: an Agent
    row of another session."""
    kind, _, total = token.partition("=")
    row = {"ts": "2026-11-21T10:00:00Z", "harness": "claude", "session": session, "agent": "x", "model": None,
           "agent_id": None, "cwd": "/work"}
    if kind == "L":
        return dict(row, event="PreToolUse")
    if kind in ("P", "T", "C"):
        tool = {"P": "Agent", "T": "Task", "C": "task"}[kind]
        return dict(row, event="PreToolUse", tool=tool, total=int(total) if total.isdigit() else total)
    if kind == "S":
        return dict(row, event="SubagentStart", tool=None, agent_id="a", total=None)
    if kind == "W":
        return dict(row, event="PreToolUse", tool="Workflow", workflow="review-panel", script=False, total=0)
    if kind == "O":
        return dict(row, event="PreToolUse", tool="Agent", session="s2", total=1)
    raise ValueError(token)


def _seed(text: str) -> list:
    out = []
    for token in text.split():
        token, _, times = token.partition("*")
        out += [_seed_row(token) for _ in range(int(times or 1))]
    return out


def _fan_event(guard, which: str):
    base = {"cwd": "/work/repo", "session_id": "s1", "transcript_path": "/t"}
    if which == "Start":
        return guard.Event(dict(base, hook_event_name="SubagentStart", agent_id="a9", agent_type="workflow-subagent"))
    if which == "task":
        return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "task", "cwd": "/work/repo",
                            "sessionId": "s1", "timestamp": "t", "tool_input": {"description": "d", "prompt": "p"}})
    if which == "Workflow":
        return guard.Event(dict(base, hook_event_name="PreToolUse", tool_name="Workflow",
                                tool_input={"name": "review-panel"}))
    if which == "WorkflowScript":
        return guard.Event(dict(base, hook_event_name="PreToolUse", tool_name="Workflow",
                                tool_input={"scriptPath": "x.js"}))
    return guard.Event(dict(base, hook_event_name="PreToolUse", tool_name=which,
                            tool_input={"description": "d", "prompt": "p", "subagent_type": "Explore"}))


# id | seeded rows of the session | event | expected | the total on the new row
FANOUT_ROWS = r"""
# --- the threshold crossing: workflow agents count, so the ask can come before the sixth Agent call
F1 | S*5 | Agent | ask | 6
F1 | S*5 P=6 S*10 | Agent | ask | 16
F1 | S*20 | Agent | ask | 21
F1 | P=1 S*25 | Agent | ask | 26
F1 | S*5 P=6 S | Agent | silent | 7
F1 | S*5 P=6 S*9 | Agent | silent | 15
F1 | P=1 P=2 P=3 P=4 P=5 | Agent | ask | 6
F1 | T=1 T=2 T=3 T=4 T=5 | Task | ask | 6
# --- Copilot sends no SubagentStart: the count of its task calls, exactly 0.11.0
F2 | C=1 C=2 C=3 C=4 C=5 | task | ask | 6
F2 | C=1 C=2 C=3 C=4 | task | silent | 5
# --- the rows of 0.11.0 and older carry no tool and no total: each is a spawn, and they count up to the last
F3 | L*5 | Agent | ask | 6
F3 | L*15 | Agent | ask | 16
F3 | L*3 S*5 | Agent | ask | 6
F3 | L*6 S*6 | Agent | silent | 7
F3 | L*5 P=x | Agent | silent | 7
# --- a Workflow row is no spawn; another session's rows do not count
F4 | W*5 | Agent | silent | 1
F4 | S*3 W*9 | Agent | silent | 4
F4 | O*10 | Agent | silent | 1
# --- the Workflow call: one row with the current total; it asks nothing
F5 | S*3 | Workflow | silent | 3
F5 | P=1 S*5 | Workflow | silent | 5
F5 | P=1 S*5 | WorkflowScript | silent | 5
# --- the SubagentStart total; the hook cannot block, so it never answers
F6 | P=1 P=2 | Start | silent | 2
F6 | P=1 S | Start | silent | 2
F6 | S*9 | Start | silent | 10
# --- criterion 5: a sixth spawn through a workflow shows in spawns.jsonl with the session total
F7 | P=1 S P=2 S P=3 S P=4 S P=5 S W | Start | silent | 6
"""
FANOUT_TABLE = _rows(FANOUT_ROWS)


@pytest.mark.parametrize("rid, seed, which, expected, total", FANOUT_TABLE,
                         ids=[f"{r[0]}-{n}" for n, r in enumerate(FANOUT_TABLE)])
def test_the_fan_out_row(guard, monkeypatch, tmp_path, rid, seed, which, expected, total):
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: False)
    log = tmp_path / "telemetry" / "spawns.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(r) + "\n" for r in _seed(seed)))
    ev = _fan_event(guard, which)
    got = guard.rule_fan_out(ev, dict(guard.DEFAULTS, telemetry_dir=str(tmp_path / "telemetry")))
    assert (got or ("silent",))[0] == expected, got
    rows = [json.loads(ln) for ln in log.read_text().splitlines()]
    new = rows[-1]
    assert len(rows) == len(_seed(seed)) + 1, "one row per call"
    assert new["total"] == int(total), new
    assert new["tool"] == (ev.tool or None), new
    if got:
        assert f"#{total} " in got[1], got
    if which.startswith("Workflow"):
        assert new["workflow"] == ev.args.get("name") and new["script"] == ("scriptPath" in ev.args), new


def test_a_threshold_asks_once(guard, monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: False)
    cfg = dict(guard.DEFAULTS, telemetry_dir=str(tmp_path / "t"))
    start = _fan_event(guard, "Start")
    for _ in range(8):
        assert guard.rule_fan_out(start, cfg) is None
    asked = [guard.rule_fan_out(_fan_event(guard, "Agent"), cfg) for _ in range(3)]
    assert [a and a[0] for a in asked] == ["ask", None, None], asked
    assert "#9 " in asked[0][1]


def test_a_spawn_log_line_that_is_no_utf8_does_not_crash(guard, monkeypatch, tmp_path):
    # the first review: a crash of the hook now blocks the call (onFailure block), so one bad byte in the shared
    # log must not stop every spawn of every session. The byte is replaced: a line that is then no JSON is skipped,
    # one that still parses is read as any row (here one with no event, which counts nothing)
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: False)
    cfg = dict(guard.DEFAULTS, telemetry_dir=str(tmp_path / "t"))
    path = pathlib.Path(guard.spawn_log_path(cfg))
    path.parent.mkdir(parents=True)
    rows = "".join(json.dumps(r) + "\n" for r in _seed("P=1 P=2 P=3 P=4 P=5"))
    path.write_bytes(rows.encode("utf-8") + b'{"session": "s1", "x": "\xff\xfe"}\n\xff{"session": "s1"}\n')
    got = guard.rule_fan_out(_fan_event(guard, "Agent"), cfg)
    assert got and got[0] == "ask" and "#6 " in got[1], got


def test_every_tool_of_kind_spawn_is_counted(guard):
    # the first review: the count filters on SPAWN_TOOLS while the row is written for kind spawn; a spawn tool
    # missing from the tuple would be logged and never counted
    kinds = {name for table in (guard.CLAUDE_TOOLS, guard.COPILOT_TOOLS) for name, kind in table.items()
             if kind == "spawn"}
    assert kinds == set(guard.SPAWN_TOOLS), kinds


def test_a_plain_int_from_log_spawn_is_the_total(guard, monkeypatch):
    # A2: the stubs of the older modules return an int: read as total n, previous n - 1
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: False)
    for n, want in ((5, None), (6, "ask"), (7, None), (16, "ask")):
        monkeypatch.setattr(guard, "log_spawn", lambda ev, cfg, n=n: n)
        got = guard.rule_fan_out(_fan_event(guard, "Agent"), dict(guard.DEFAULTS))
        assert (got and got[0]) == want, (n, got)


# ----------------------------------------------------------------------------
# D5: .claude/workflows/** joins guard-config
# ----------------------------------------------------------------------------

# id | profile | expected | tool | input ({w} is the work clone)
GUARD_CONFIG_ROWS = r"""
G1 | host | ask | Write | {"file_path": "{w}/.claude/workflows/review-panel.js", "content": "x"}
G1 | host | ask | Edit | {"file_path": "{w}/.claude/workflows/review-panel.js", "old_string": "a", "new_string": "b"}
G1 | host | ask | Write | {"file_path": "{w}/.claude/workflows/sub/x.js", "content": "x"}
G1 | host | ask | Write | {"file_path": "{w}/.CLAUDE/Workflows/X.js", "content": "x"}
G1 | host | ask | Bash | {"command": "sed -i s/a/b/ .claude/workflows/review-panel.js"}
G1 | host | ask | Bash | {"command": "echo x > .claude/workflows/x.js"}
G1 | host | ask | Bash | {"command": "cp /tmp/x.js .claude/workflows/"}
# a shell write that names the folder itself writes inside it (the first review): copy, move, link, sync
G1 | host | ask | Bash | {"command": "cp evil.js .claude/workflows"}
G1 | host | ask | Bash | {"command": "mv d .claude/workflows"}
G1 | host | ask | Bash | {"command": "ln -s /tmp/d .claude/workflows"}
G1 | host | ask | Bash | {"command": "rsync -a d/ .claude/workflows"}
G1 | box | logged | Bash | {"command": "ln -s /tmp/d .claude/workflows"}
G1 | host | ask | mcp__github__create_or_update_file | {"owner": "o", "repo": "r", "path": ".claude/workflows/x.js", "content": "x", "message": "m", "branch": "feat/x"}
G1 | box | logged | Write | {"file_path": "{w}/.claude/workflows/review-panel.js", "content": "x"}
G1 | box | logged | Bash | {"command": "sed -i s/a/b/ .claude/workflows/review-panel.js"}
G1 | cloud | deny | Write | {"file_path": "{w}/.claude/workflows/review-panel.js", "content": "x"}
G1 | cloud | deny | Bash | {"command": "sed -i s/a/b/ .claude/workflows/review-panel.js"}
# neighbours that stay silent: a read, the folder itself, a folder of the same name elsewhere, a sibling file
G2 | host | silent | Read | {"file_path": "{w}/.claude/workflows/review-panel.js"}
G2 | host | silent | Bash | {"command": "cat .claude/workflows/review-panel.js"}
G2 | host | silent | Write | {"file_path": "{w}/docs/workflows/x.js", "content": "x"}
G2 | host | silent | Write | {"file_path": "{w}/.claude/workflows-notes.txt", "content": "x"}
G2 | host | silent | Write | {"file_path": "{w}/.claude/workflows", "content": "x"}
G2 | host | silent | Write | {"file_path": "{w}/.claude/agents/workflows.md", "content": "x"}
G2 | box | silent | Read | {"file_path": "{w}/.claude/workflows/review-panel.js"}
"""  # noqa: E501
GUARD_CONFIG_TABLE = _rows(GUARD_CONFIG_ROWS)


@pytest.mark.parametrize("rid, prof, expected, tool, text", GUARD_CONFIG_TABLE,
                         ids=[f"{r[0]}-{r[1]}-{n}" for n, r in enumerate(GUARD_CONFIG_TABLE)])
def test_the_guard_config_row(guard, monkeypatch, judge, work, rid, prof, expected, tool, text):
    _profile(guard, monkeypatch, judge, prof)
    tool_input = json.loads(text.replace("{w}", str(work)))
    final, rows = BP._hook(guard, monkeypatch, BP._tool(work, tool, tool_input))
    assert _word(final, rows) == expected, (final, rows)
    if expected in ("ask", "deny"):
        rules = rows[-1]["rules"]
        assert "guard-config" in rules or (tool.startswith("mcp__") and "github-tools" in rules), rows
        if tool.startswith("mcp__"):
            assert "a workflow script" in final[1], final
    if expected == "logged":
        assert rows[-1]["rules"] == {"guard-config": "logged"}, rows


def test_the_class_names_a_workflow_script(guard):
    assert guard.guard_config_class("/r/.claude/workflows/review-panel.js") == "a workflow script"
    assert guard.guard_config_class("/r/.claude/workflows") is None


# ----------------------------------------------------------------------------
# Writing the baseline (run once with guard 0.11.0)
# ----------------------------------------------------------------------------

def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", metavar="GUARD_PY", required=True, help="the guard.py of 0.11.0")
    ns = ap.parse_args(argv)
    guard = _load("guard", pathlib.Path(ns.write))
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KZ_TELEMETRY_DIR": tmp}):
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            lines = []
            with contextlib.redirect_stderr(open(os.devnull, "w")):
                for rid, inp in inputs():
                    lines.append(json.dumps({"id": rid, "in": inp, **answers(guard, inp)}, sort_keys=True))
        finally:
            os.chdir(cwd)
    BASELINE.write_text("\n".join(lines) + "\n")
    digest = hashlib.sha256(BASELINE.read_bytes()).hexdigest()
    (HERE / "baseline-0.11.0.sha256").write_text(f"{digest}  {BASELINE.name}\n", encoding="utf-8")
    print(f"guard {guard.VERSION}: {len(lines)} inputs written to {BASELINE}, sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
