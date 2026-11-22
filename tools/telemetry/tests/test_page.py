"""Tests of the task page (tools/telemetry/page.py, tracker item #77).

Every file here is built by the tests: a git repository of its own in tmp_path (with a reflog, so `@{-1}` means
something), a host Claude home, a box home with a box run's record, the guard's logs and fresh-review receipts.
Nothing comes from a real transcript. SECRET is in every tool input, prompt, reply and tool output, in an Agent call's
description, a workflow's name and a box run's result; it must never reach the data or the page.
The git tests run against the git on the machine and fail when it is missing.
"""
import datetime as dt
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "page.py"
NOW = dt.datetime(2026, 11, 21, 12, 0, tzinfo=dt.timezone.utc)
SECRET = "SECRET-" + "MARKER-7f3a"  # in every tool input of the fixtures
PRICES = {"claude-opus-5-5": {"input": 5, "output": 25, "cache_read": 0.5, "cache_write": 5, "cache_write_1h": 10}}
REQUEST_USD = (1000 * 5 + 100 * 25) / 1_000_000  # one fixture request: 1,000 in, 100 out on Opus


@pytest.fixture(scope="module")
def page():
    spec = importlib.util.spec_from_file_location("page", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def git_bin():
    found = shutil.which("git")
    assert found, "these tests run against the git on the machine: install git, they do not pass without it"
    return found


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def ts(minute, second=0):
    return f"2026-11-20T10:{minute:02d}:{second:02d}.000Z"


def tool(tid, name):
    return {"type": "tool_use", "id": tid, "name": name, "input": {"command": f"echo {SECRET}", "path": SECRET}}


def asst(minute, branch, cwd, blocks, req):
    return {"type": "assistant", "timestamp": ts(minute), "gitBranch": branch, "cwd": cwd, "requestId": req,
            "message": {"model": "claude-opus-5-5", "stop_reason": "tool_use" if blocks else "end_turn",
                        "content": [{"type": "text", "text": f"reply {SECRET}"}, *blocks],  # a reply in every row
                        "usage": {"input_tokens": 1000, "output_tokens": 100}}}


def user(minute, branch, cwd, text=f"prompt {SECRET}"):
    return {"type": "user", "timestamp": ts(minute), "gitBranch": branch, "cwd": cwd,
            "message": {"role": "user", "content": text}}


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def session(folder, sid, branch, cwd, calls=(), title=None, pr=None, minute=0):
    rows = [user(minute, branch, cwd)]
    if title:
        rows.append({"type": "ai-title", "aiTitle": title, "sessionId": sid})
    rows.append(asst(minute + 1, branch, cwd, [tool(t, n) for t, n in calls], f"req-{sid}-1"))
    if calls:  # each call's output
        rows.append(user(minute + 1, branch, cwd, [{"type": "tool_result", "tool_use_id": t, "content": SECRET}
                                                    for t, _ in calls]))
    if pr:
        rows.append({"type": "pr-link", "sessionId": sid, "prNumber": pr, "prUrl": "u", "timestamp": ts(minute + 2)})
    write_jsonl(folder / f"{sid}.jsonl", rows)
    return folder / f"{sid}.jsonl"


def encoded(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def receipt(path, sha, when, findings, base_sha=None, verdict="COMMENT"):
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"sha": sha, "ts": when, "verdict": verdict, "base": "origin/main", "base_sha": base_sha, "cost_usd": 0.2,
           "findings": [{"file": f, "line": n, "severity": "MINOR", "summary": s} for f, n, s in findings]}
    path.write_text(json.dumps(rec), encoding="utf-8")


F_A, F_B, F_C = ("tools/x.py", 3, "finding A"), ("tools/x.py", 9, "finding B"), ("README.md", 1, "finding C")


@pytest.fixture
def world(tmp_path, git_bin):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("one\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "one")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "-c", "feat/page")
    (repo / "evidence" / "run-1").mkdir(parents=True)
    (repo / "evidence" / "run-1" / "out.txt").write_text("evidence\n")
    (repo / "tools").mkdir()
    (repo / "tools" / "x.py").write_text("x = 1\n")
    git(repo, "add", "evidence/run-1/out.txt", "tools/x.py")
    git(repo, "commit", "-q", "-m", "two")
    sha1 = git(repo, "rev-parse", "HEAD")
    (repo / "tools" / "x.py").write_text("x = 2\n")
    git(repo, "commit", "-q", "-am", "three")
    sha2 = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")
    git(repo, "switch", "-q", "-c", "feat/solo")  # a branch with a review and no session
    (repo / "solo.txt").write_text("solo\n")
    git(repo, "add", "solo.txt")
    git(repo, "commit", "-q", "-m", "solo")
    solo = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")  # the reflog now holds branch switches, so @{-1} names a branch
    git(repo, "branch", "feat/quiet")  # a branch with neither a session nor a review: no task
    project = os.path.realpath(repo)
    wt = os.path.join(project, ".claude", "worktrees", "wt")
    git(repo, "worktree", "add", "-q", wt, "feat/page")
    gdir = repo / ".git"
    receipt(gdir / "fresh-review" / f"{sha1}.json", sha1, "2026-11-20T10:30:00Z", [F_A, F_B])
    receipt(gdir / "worktrees" / "wt" / "fresh-review" / f"{sha2}.json", sha2, "2026-11-20T11:00:00Z", [F_B, F_C],
            base_sha=sha1)
    receipt(gdir / "fresh-review" / ("e" * 40 + ".json"), "e" * 40, "2026-11-20T11:30:00Z", [])  # on no branch
    receipt(gdir / "fresh-review" / f"{solo}.json", solo, "2026-11-20T09:00:00Z", [F_C])
    receipt(gdir / "fresh-review" / ("d" * 40 + ".json"), sha1, "2026-10-01T10:00:00Z", [F_A])  # before the window

    host, box = tmp_path / "host", tmp_path / "box"
    folder = host / "projects" / encoded(project)
    session(folder, "s1", "feat/page", project, [("toolu_ask", "Bash"), ("toolu_deny", "Bash"), ("toolu_free", "Read")],
            title="<img src=http://x>", pr=7)
    write_jsonl(folder / "s1" / "subagents" / "agent-a100.jsonl",
                [asst(5, "feat/page", project, [tool("toolu_agent", "Grep")], "req-a100")])
    (folder / "s1" / "subagents" / "agent-a100.meta.json").write_text(
        json.dumps({"agentType": "code-reviewer", "description": f"review the diff {SECRET}"}))  # Agent call input
    session(host / "projects" / encoded(wt), "s2", "feat/page", wt, [("toolu_wt", "Edit")], minute=20)
    for sid, branch in (("s3", "--output=x"), ("s4", "a b"), ("s5", "@{-1}"), ("s6", "main"), ("s7", "feat/gone")):
        session(folder, sid, branch, project, [(f"toolu_{sid}", "Read")], minute=30)
    write_jsonl(folder / "s7" / "subagents" / "workflows" / "wf1" / "agent-w100.jsonl",  # a workflow's agent
                [asst(31, "feat/gone", project, [], "req-w100")])
    (folder / "s7" / "workflows" / "scripts").mkdir(parents=True)
    (folder / "s7" / "workflows" / "scripts" / f"{SECRET}-wf1.js").write_text("")  # the name from the Workflow call
    session(host / "projects" / (encoded(project) + "-2"), "s8", "feat/page", project + "-2")  # same prefix, other
    old = session(folder, "s9", "feat/page", project)
    stale = (NOW - dt.timedelta(days=30)).timestamp()
    os.utime(old, (stale, stale))
    host_tel = tmp_path / "host-telemetry"
    write_jsonl(host_tel / "decisions.jsonl", [
        {"ts": "2026-11-20T10:01:00Z", "verdict": "ask", "rules": {"tracker-guard": "ask"}, "tool": "Bash",
         "session": "s1", "call": "toolu_ask"},
        {"ts": "2026-11-20T10:01:30Z", "verdict": "ran", "rules": {"tracker-guard": "ran"}, "tool": "Bash",
         "session": "s1", "call": "toolu_ask"},
        {"ts": "2026-11-20T10:01:40Z", "verdict": "deny", "rules": {"egress-guard": "deny"}, "tool": "Bash",
         "session": "s1", "call": "toolu_deny"},
        {"ts": "2026-11-20T10:05:00Z", "verdict": "ask", "rules": {"delete-guard": "ask"}, "tool": "Grep",
         "session": "s1", "call": "toolu_agent"},
    ])
    with open(host_tel / "decisions.jsonl", "a", encoding="utf-8") as fh:
        fh.write("{\n")  # a line cut off in the middle
    write_jsonl(host_tel / "sessions-2026-11.jsonl", [
        {"ts": "2026-11-20T10:10:00Z", "session": "s1", "cost_usd": 1.25, "cost_basis": "claude-code",
         "cost_check": "ok", "models": {}}])
    write_jsonl(host_tel / "spawns.jsonl", [  # the guard's spawn log: a workflow's name, an agent with no transcript
        {"ts": "2026-11-20T10:06:00Z", "event": "PreToolUse", "session": "s1", "tool": "Workflow", "workflow": SECRET},
        {"ts": "2026-11-20T10:06:10Z", "event": "SubagentStart", "session": "s1", "agent": "Explore",
         "agent_id": "a300"}])

    claude_home = box / "claude-home"
    session(claude_home / "projects" / "-work", "b1", "feat/page", "/work", [("toolu_box", "Bash")], minute=40)
    session(claude_home / "projects" / "-tmp-scratch", "b2", "feat/page", "/tmp/scratch")
    write_jsonl(claude_home / "telemetry" / "decisions.jsonl", [
        {"ts": "2026-11-20T10:41:00Z", "verdict": "logged", "rules": {"merge-guard": "logged"}, "tool": "Bash",
         "session": "b1", "call": "toolu_box", "profile": "box"}])
    result = box / "boxes" / "guard" / "results" / "20261120T104000Z" / "result.json"
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({"schema": "agent-box-result/1", "name": "guard", "seat": "guard", "exit": 0,
                                  "image": "agent-box:abc", "branch_after": "feat/page",
                                  "result": {"session_id": "b1", "result": SECRET}}))
    homes = [{"label": "host", "config": str(host), "telemetry": str(host_tel), "root": project, "results": None},
             {"label": "box", "config": str(claude_home), "telemetry": str(claude_home / "telemetry"),
              "root": "/work", "results": str(box / "boxes")}]
    return {"repo": repo, "project": project, "homes": homes, "sha1": sha1, "sha2": sha2, "solo": solo}


@pytest.fixture
def git_calls(page, monkeypatch):
    calls = []
    real = page.run_git

    def recording(args, cwd):
        calls.append((list(args), cwd))
        return real(args, cwd)

    monkeypatch.setattr(page, "run_git", recording)
    return calls


def collected(page, world):
    return page.collect(world["project"], 7, world["homes"], now=NOW, prices=PRICES)


def task(data, branch):
    found = [t for t in data["tasks"] if t["branch"] == branch]
    assert len(found) == 1, [t["branch"] for t in data["tasks"]]
    return found[0]


def sessions_of(data):
    return {s["id"]: s for t in data["tasks"] for s in t["sessions"]}


# ---- step 1: collect ----------------------------------------------------------------------------------------------

def test_sessions_of_both_homes_grouped_by_branch(page, world):
    data = collected(page, world)
    assert set(sessions_of(data)) == {"s1", "s2", "s3", "s4", "s5", "s6", "s7", "b1"}  # s8 another folder, s9 old,
    # b2 outside /work
    feat = task(data, "feat/page")
    assert [s["id"] for s in feat["sessions"]] == ["s1", "s2", "b1"]  # in order of start
    assert [s["home"] for s in feat["sessions"]] == ["host", "host", "box"]
    assert sorted(t["branch"] for t in data["tasks"]) == sorted(
        ["feat/page", "feat/solo", "--output=x", "a b", "@{-1}", "main", "feat/gone"])
    assert feat["prs"] == [7]
    b1 = sessions_of(data)["b1"]
    assert b1["box"]["name"] == "guard" and b1["box"]["exit"] == 0 and b1["box"]["branch_after"] == "feat/page"
    assert sessions_of(data)["s1"]["box"] is None
    assert [h["sessions"] for h in data["homes"]] == [7, 1]


def test_tool_calls_joined_with_the_guard_log_on_the_call_id(page, world):
    s = sessions_of(collected(page, world))
    got = [(c["agent"], c["tool"], c["verdict"], c["ran"]) for c in s["s1"]["calls"]]
    assert got == [("session", "Bash", "ask", True), ("session", "Bash", "deny", None), ("session", "Read", "-", None),
                   ("code-reviewer", "Grep", "ask", False)]
    assert s["s1"]["calls"][1]["rules"] == [("egress-guard", "deny")]
    assert [(c["tool"], c["verdict"]) for c in s["b1"]["calls"]] == [("Bash", "logged")]
    assert [a["kind"] for a in s["s1"]["agents"]] == ["session", "agent", "missing"]


def test_the_gate_holds_every_ask_and_deny_with_its_rule(page, world):
    data = collected(page, world)
    gate = sessions_of(data)["s1"]["gate"]
    assert [(g["verdict"], g["rules"], g["ran"]) for g in gate] == [
        ("ask", [("tracker-guard", "ask")], True), ("deny", [("egress-guard", "deny")], None),
        ("ask", [("delete-guard", "ask")], False)]
    feat = task(data, "feat/page")
    assert (feat["asks"], feat["denies"]) == (2, 1)
    assert data["lines_not_read"] >= 1  # the broken guard line is counted, not fatal


def test_cost_is_the_ledger_figure_else_the_own_count(page, world):
    s = sessions_of(collected(page, world))
    assert (s["s1"]["cost"], s["s1"]["cost_basis"]) == (1.25, "claude-code")
    assert s["s2"]["cost"] == pytest.approx(REQUEST_USD) and s["s2"]["cost_basis"] == "own count, no ledger line"
    assert task(collected(page, world), "feat/page")["cost"] == pytest.approx(1.25 + 2 * REQUEST_USD)


def test_reviews_are_tied_to_the_branch_by_its_reflog_and_retested(page, world):
    data = collected(page, world)
    feat = task(data, "feat/page")
    assert [r["sha"] for r in feat["reviews"]] == [world["sha1"], world["sha2"]]
    assert [r["where"] for r in feat["reviews"]] == ["main checkout", "worktree wt"]
    (rt,) = feat["retests"]
    assert rt["delta"] is True
    key = lambda f: (f["file"], f["line"], f["summary"])  # noqa: E731
    assert ([key(f) for f in rt["went"]], [key(f) for f in rt["stayed"]], [key(f) for f in rt["new"]]) == (
        [F_A], [F_B], [F_C])
    assert (data["reviews"], data["reviews_untied"]) == (4, 1)  # the old receipt is outside the window


def test_evidence_paths_are_those_the_branch_changed(page, world):
    feat = task(collected(page, world), "feat/page")
    assert (feat["lookup"], feat["commits"], feat["evidence"]) == ("ok", 2, ["evidence/run-1/out.txt"])


def test_branch_names_from_transcripts_that_never_reach_git_log(page, world, git_calls):
    data = collected(page, world)
    logs = [args for args, _ in git_calls if args[0] in ("log", "rev-list")]
    for name in ("--output=x", "a b", "@{-1}"):
        assert task(data, name)["lookup"] == "refused"
        assert ["check-ref-format", "--branch", name] in [args for args, _ in git_calls]
        assert not any(name in arg for args in logs for arg in args), name
    ahead = "refs/remotes/origin/main..refs/heads/main"  # the full ref, as has_base checked it
    main = [args for args in logs if ahead in args]
    assert [args[0] for args in main] == ["rev-list", "log"]
    for args in main:
        assert args.index("--end-of-options") < args.index(ahead) and args[-1] == "--"
    for args in logs:  # every name reaches git after --end-of-options, as refs/heads/NAME, with a closing --
        named = [a for a in args if "refs/heads/" in a]
        assert named and args.index("--end-of-options") < args.index(named[0]) and args[-1] == "--"
    assert {cwd for _, cwd in git_calls} == {world["project"]}  # git runs in the project only, never in /work


@pytest.mark.parametrize("name, answer", [("@{-1}", "@{-1}\n"), ("feat/alias", "main\n")])
def test_each_of_the_two_name_checks_holds_by_itself(page, monkeypatch, name, answer):
    # On git 2.55.0 every name check-ref-format changes also holds `@{`, so with the real git one check hides the
    # other. A stub that answers check-ref-format shows each holds alone: `@{` even when git keeps the name, a name
    # git changes even without `@{`.
    calls = []

    def stub(args, cwd):
        calls.append(list(args))
        return (0, answer) if args[0] == "check-ref-format" else (0, "")

    monkeypatch.setattr(page, "run_git", stub)
    assert page.branch_lookup(name, "/nowhere", True) == {"lookup": "refused"}
    assert calls == [["check-ref-format", "--branch", name]]


def test_a_reflog_read_that_fails_is_a_git_failure(page, monkeypatch):
    def stub(args, cwd):  # every other call answers as for a branch with no commits ahead
        if args[0] == "check-ref-format":
            return 0, "feat/x\n"
        return (None, "") if args[:2] == ["log", "-g"] else (0, "")

    monkeypatch.setattr(page, "run_git", stub)
    assert page.branch_lookup("feat/x", "/nowhere", True) == {"lookup": "error"}


def test_a_branch_with_no_reflog_is_looked_up(page, world):
    git(world["repo"], "-c", "core.logAllRefUpdates=false", "branch", "feat/nolog", world["sha1"])
    assert not (world["repo"] / ".git" / "logs" / "refs" / "heads" / "feat" / "nolog").exists()  # no reflog at all
    found = page.branch_lookup("feat/nolog", world["project"], True)
    assert (found["lookup"], found["commits"], found["shas"]) == ("ok", 1, {world["sha1"]})


def test_reviews_stay_tied_to_a_merged_branch(page, world):
    git(world["repo"], "update-ref", "refs/remotes/origin/main", world["sha2"])  # the branch is in main now
    feat = task(collected(page, world), "feat/page")
    assert (feat["lookup"], feat["commits"], feat["evidence"]) == ("ok", 0, [])
    assert [r["sha"] for r in feat["reviews"]] == [world["sha1"], world["sha2"]]  # through the branch's reflog


def test_a_block_written_on_two_lines_is_one_call(page, world):
    path = pathlib.Path(world["homes"][0]["config"]) / "projects" / encoded(world["project"]) / "s6.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines + [lines[-1]]) + "\n")  # the same assistant line, written again
    assert [c["tool"] for c in sessions_of(collected(page, world))["s6"]["calls"]] == ["Read"]


def test_a_branch_absent_from_the_clone_is_named_not_an_error(page, world):
    gone = task(collected(page, world), "feat/gone")
    assert gone["lookup"] == "absent" and gone["evidence"] == [] and gone["reviews"] == []
    assert page.LOOKUP_TEXT["absent"] == "no evidence lookup: branch not in this clone"


def test_without_origin_main_no_branch_gets_a_lookup(page, world, git_calls):
    git(world["repo"], "update-ref", "-d", "refs/remotes/origin/main")
    data = collected(page, world)
    assert task(data, "feat/page")["lookup"] == "no-base" and task(data, "main")["lookup"] == "no-base"
    assert not [args for args, _ in git_calls if args[0] in ("log", "rev-list")]


def test_a_local_branch_named_origin_main_is_no_base(page, world):
    git(world["repo"], "branch", "origin/main", world["sha2"])  # git takes refs/heads/ before refs/remotes/
    feat = task(collected(page, world), "feat/page")
    assert (feat["commits"], feat["evidence"]) == (2, ["evidence/run-1/out.txt"])


def test_an_evidence_path_git_would_quote_is_listed(page, world):
    wt = pathlib.Path(world["project"]) / ".claude" / "worktrees" / "wt"  # feat/page is checked out there
    name = 'evidence/résumé "x".txt'  # without -z, git writes it C-quoted
    (wt / name).write_text("e\n")
    git(wt, "add", name)
    git(wt, "commit", "-q", "-m", "four")
    feat = task(collected(page, world), "feat/page")
    assert feat["commits"] == 3 and feat["evidence"] == sorted(["evidence/run-1/out.txt", name])


def test_no_tool_input_reaches_the_data(page, world):
    assert SECRET not in repr(collected(page, world))


def test_an_agent_is_shown_by_its_type_and_a_workflow_without_its_name(page, world):
    s = sessions_of(collected(page, world))
    assert [(a["kind"], a["label"]) for a in s["s1"]["agents"] if a["kind"] != "session"] == [
        ("agent", "code-reviewer"), ("missing", "Explore  (no transcript)")]  # the ledger's label adds the description
    assert sorted((a["kind"], a["label"]) for a in s["s7"]["agents"] if a["kind"] != "session") == [
        ("agent", "agent"), ("workflow", "workflow")]  # the ledger's label adds the script's name


def test_an_agent_without_a_type_shows_no_description(page, world):
    folder = pathlib.Path(world["homes"][0]["config"]) / "projects" / encoded(world["project"]) / "s6" / "subagents"
    write_jsonl(folder / "agent-a200.jsonl", [asst(31, "main", world["project"], [], "req-a200")])
    (folder / "agent-a200.meta.json").write_text(json.dumps({"description": f"no type {SECRET}"}))
    agents = sessions_of(collected(page, world))["s6"]["agents"]
    assert [a["label"] for a in agents if a["kind"] == "agent"] == ["agent"] and SECRET not in repr(agents)


def test_a_session_sits_under_the_branch_most_of_its_lines_carry(page, tmp_path):
    rows = [user(0, "feat/a", "/r"), user(1, "feat/a", "/r"), user(2, "main", "/r")]
    write_jsonl(tmp_path / "most.jsonl", rows)
    assert page.read_transcript(str(tmp_path / "most.jsonl"))["branch"] == "feat/a"  # though main is seen last
    write_jsonl(tmp_path / "tie.jsonl", rows[1:])  # one line each: the tie goes to the branch seen last
    assert page.read_transcript(str(tmp_path / "tie.jsonl"))["branch"] == "main"


def test_one_call_with_two_guard_lines_keeps_the_stronger(page, tmp_path):
    line = {"ts": "2026-11-20T10:00:00Z", "tool": "Bash", "session": "s", "call": "c"}
    write_jsonl(tmp_path / "decisions.jsonl", [dict(line, verdict="deny", rules={"egress-guard": "deny"}),
                                               dict(line, verdict="ask", rules={"delete-guard": "ask"})])
    assert page.read_guard_log(str(tmp_path))["by_call"]["c"] == {"verdict": "deny",
                                                                  "rules": [("egress-guard", "deny")]}


def test_a_full_session_id_wins_over_the_ids_it_is_a_prefix_of(page, world):
    session(pathlib.Path(world["homes"][0]["config"]) / "projects" / encoded(world["project"]), "s10", "feat/page",
            world["project"])
    one = lambda sid: set(sessions_of(page.collect(world["project"], 7, world["homes"], now=NOW,  # noqa: E731
                                                   prices=PRICES, session=sid)))
    assert (one("s1"), one("s10")) == ({"s1"}, {"s10"})


def test_an_unreadable_transcript_line_is_counted_once(page, world):
    before = collected(page, world)["lines_not_read"]
    folder = pathlib.Path(world["homes"][0]["config"]) / "projects" / encoded(world["project"])
    for path in (folder / "s6.jsonl", folder / "s1" / "subagents" / "agent-a100.jsonl"):  # a session, an agent
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{\n")
    assert collected(page, world)["lines_not_read"] == before + 2


def test_a_box_record_tied_to_no_session_is_counted(page, world):
    before = collected(page, world)["files_not_read"]
    runs = pathlib.Path(world["homes"][1]["results"]) / "guard" / "results"
    for stamp, text in (("20261120T110000Z", '{"schema": '), ("20261120T111000Z", json.dumps({"result": None})),
                        ("20261120T112000Z", json.dumps({"result": {"session_id": "../b1"}}))):
        (runs / stamp).mkdir()
        (runs / stamp / "result.json").write_text(text)  # cut off; the CLI wrote no JSON; no session file's id
    data = collected(page, world)
    assert data["files_not_read"] == before + 3 and sessions_of(data)["b1"]["box"]["name"] == "guard"


def test_a_branch_list_that_fails_is_named_on_the_page(page, world, monkeypatch):
    assert collected(page, world)["branch_list"] == "ok"
    real = page.run_git
    monkeypatch.setattr(page, "run_git", lambda args, cwd: (1, "") if args[0] == "for-each-ref" else real(args, cwd))
    data = collected(page, world)
    assert data["branch_list"] == "error" and "feat/solo" not in [t["branch"] for t in data["tasks"]]
    html = page.render(data)
    assert "git for-each-ref failed" in html and page.check_page(html) == []


# ---- step 2: render and check_page --------------------------------------------------------------------------------

CSP_TAG = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"


def minimal(body="", head=CSP_TAG, style="p{color:red}"):
    """A hand-written page that passes the check, so a breach found below comes from what a test puts in."""
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">{head}<title>t</title>'
            f"<style>{style}</style></head><body>{body}</body></html>")


def test_the_rendered_fixtures_pass_the_check(page, world):
    html = page.render(collected(page, world))
    assert page.check_page(html) == []
    assert html.count(CSP_TAG.replace("'", "&#x27;")) == 1
    for section in ("Tasks", "Scope", "Agents", "Timeline", "Gate", "Findings", "Re-test", "Evidence", "Notes"):
        assert f"<h2>{section}</h2>" in html or f"<h3>{section}</h3>" in html, section


def test_an_empty_page_passes_the_check(page, tmp_path, git_bin):
    homes = [{"label": "host", "config": str(tmp_path / "none"), "telemetry": str(tmp_path / "t"),
              "root": str(tmp_path), "results": None}]
    html = page.render(page.collect(str(tmp_path), 7, homes, now=NOW, prices=PRICES))
    assert page.check_page(html) == [] and "no session of this project in the last 7 days" in html


def test_a_title_holding_markup_is_shown_as_text(page, world):
    html = page.render(collected(page, world))
    assert "&lt;img src=http://x&gt;" in html and "<img" not in html
    assert page.check_page(html) == []


def test_no_tool_input_reaches_the_page(page, world):
    assert SECRET not in page.render(collected(page, world))


def test_the_hand_written_page_passes_and_escaped_text_never_counts(page):
    assert page.check_page(minimal()) == []
    assert page.check_page(minimal("<p>&lt;script src=http://x&gt; url( url= @import \\</p>")) == []


@pytest.mark.parametrize("name, html", [
    ("no CSP tag", minimal(head="")),
    ("two CSP tags", minimal(head=CSP_TAG * 2)),
    ("default-src *", minimal(head=CSP_TAG.replace("default-src 'none'", "default-src *"))),
    ("CSP tag in the body", minimal(head="", body=CSP_TAG)),
    ("script", minimal("<script>x()</script>")),
    ("meta refresh", minimal(head=CSP_TAG + '<meta http-equiv="refresh" content="0;url=http://x">')),
    ("form action", minimal('<form action="http://x"><p>x</p></form>')),
    ("img srcset", minimal('<img srcset="http://x 1x">')),
    ("style attribute with url(", minimal('<p style="background:url(x)">x</p>')),
    ("@import in style", minimal(style="@import 'x.css';")),
    ("CSS escape for url(", minimal(style="p{background:\\75 rl(x)}")),
    ("link", minimal(head=CSP_TAG + '<link rel="stylesheet" href="x.css">')),
    ("href to a site", minimal('<a href="https://x">x</a>')),
    ("first of two hrefs", minimal('<a href="//x" href="#ok">x</a>')),
    ("url( spelled with an entity", minimal('<p class="u&#114;l(x)">x</p>')),
    ("svg", minimal("<svg></svg>")),
    ("comment", minimal("<!-- x -->")),
    # each of these breaks one rule only, so each rule is shown to hold by itself
    ("event handler attribute", minimal('<p onclick="x()">x</p>')),
    ("style attribute", minimal('<p style="color:red">x</p>')),
    ("url= in an attribute", minimal('<p class="0;url=x">x</p>')),
    ("a scheme in an attribute", minimal('<p id="http://x">x</p>')),
    ("a scheme in style", minimal(style="p{font-family:'http://x'}")),
    ("meta name", minimal(head=CSP_TAG + '<meta name="referrer" content="unsafe-url">')),
    ("meta refresh without a url", minimal(head=CSP_TAG + '<meta http-equiv="refresh" content="5">')),
    ("URL( in capitals in style", minimal(style="p{background:URL(x)}")),  # CSS reads it as url(
    ("CSP tag after body content, no </head>",  # body content ends the head: a browser ignores the tag there;
     # an empty <p>, so the start tag alone ends it (text would end it too, by its own rule)
     '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>t</title><p></p>' + CSP_TAG + "</html>"),
    ("CSP tag in a second <head> after body content",  # a browser drops a <head> tag in the body
     '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>t</title></head><body><p>x</p><head>'
     + CSP_TAG + "</head></body></html>"),
    ("text in the head before the CSP tag",
     '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">x' + CSP_TAG + "<title>t</title></head></html>"),
    ("a no-break space in the head before the CSP tag",  # text to a browser, whitespace to Python's isspace()
     '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">\u00a0' + CSP_TAG + "<title>t</title></head></html>"),
    ("text before <head>",  # a browser starts the body there and drops the later <head>
     '<!DOCTYPE html><html lang="en">x<head><meta charset="utf-8">' + CSP_TAG + "<title>t</title></head></html>"),
    ("</body> in the head before the CSP tag",
     '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"></body>' + CSP_TAG + "<title>t</title></head></html>"),
    ("whitespace before the CSP tag", minimal(head="\n" + CSP_TAG)),  # nothing between: the check stays this simple
    ("the CSP tag after the title", minimal(head="<title>t</title>" + CSP_TAG)),
])
def test_each_breach_is_found(page, name, html):
    assert page.check_page(html), name


# ---- step 3: the command ------------------------------------------------------------------------------------------

@pytest.fixture
def cli(page, world, tmp_path, monkeypatch):
    """main() with the world's homes: CLAUDE_CONFIG_DIR and KZ_TELEMETRY_DIR set, HOME holding the box's folder."""
    home = tmp_path / "home"
    home.mkdir()
    os.symlink(tmp_path / "box", home / ".agent-box")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", world["homes"][0]["config"])
    monkeypatch.setenv("KZ_TELEMETRY_DIR", world["homes"][0]["telemetry"])

    def run(*argv, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        code = page.main(list(argv), out, err, cwd=cwd or world["project"], now=NOW)
        return code, out.getvalue(), err.getvalue()

    return run


def mode(path):
    return os.stat(path).st_mode & 0o777


def test_the_default_place_and_its_modes(page, world, cli):
    pages = pathlib.Path(world["homes"][0]["telemetry"]) / "pages"
    pages.mkdir(parents=True, mode=0o755)
    os.chmod(pages, 0o755)
    code, out, err = cli()
    assert (code, err) == (0, "")
    assert out == str(pages / "20261121T120000Z.html") + "\n"  # the path alone, so a shell can open it
    assert (mode(pages), mode(out.strip())) == (0o700, 0o600)
    html = pathlib.Path(out.strip()).read_text(encoding="utf-8")
    assert page.check_page(html) == [] and SECRET not in html
    assert "box home not read: this repository has no bin/box" in html and "s-b1" not in html


def test_the_box_home_is_read_in_a_repository_with_bin_box(world, cli):
    (world["repo"] / "bin").mkdir()
    (world["repo"] / "bin" / "box").write_text("#!/bin/sh\n")
    code, out, _ = cli()
    html = pathlib.Path(out.strip()).read_text(encoding="utf-8")
    assert code == 0 and 'id="s-b1"' in html and "box guard, seat guard" in html


def test_a_run_from_a_worktree_is_the_page_of_the_repository(world, cli):
    code, out, _ = cli(cwd=os.path.join(world["project"], ".claude", "worktrees", "wt"))
    html = pathlib.Path(out.strip()).read_text(encoding="utf-8")
    assert code == 0 and 'id="s-s1"' in html and 'id="s-s2"' in html


@pytest.mark.parametrize("where", ["page.html", os.path.join(".claude", "worktrees", "wt", "page.html"),
                                   os.path.join(".git", "page.html")])
def test_out_inside_a_work_tree_is_refused(world, cli, where):
    target = os.path.join(world["project"], where)
    code, out, err = cli("--out", target)
    assert (code, out) == (1, "") and "lies in the git work tree" in err
    assert not os.path.exists(target)


def test_the_default_place_inside_a_work_tree_is_refused(world, cli, monkeypatch):
    monkeypatch.setenv("KZ_TELEMETRY_DIR", os.path.join(world["project"], "telemetry"))
    code, _, err = cli()
    assert code == 1 and "lies in the git work tree" in err
    assert not os.path.exists(os.path.join(world["project"], "telemetry"))


def test_out_outside_a_work_tree_is_written_0600(tmp_path, cli):
    (tmp_path / "elsewhere").mkdir()
    target = tmp_path / "elsewhere" / "p.html"
    code, out, _ = cli("--out", str(target))
    assert (code, out, mode(target)) == (0, f"{target}\n", 0o600)


def test_an_existing_file_is_never_overwritten(tmp_path, cli):
    target = tmp_path / "p.html"
    target.write_text("mine")
    code, _, err = cli("--out", str(target))
    assert code == 1 and "never overwritten" in err and target.read_text() == "mine"
    os.symlink(tmp_path / "nowhere", tmp_path / "link.html")
    assert cli("--out", str(tmp_path / "link.html"))[0] == 1 and not (tmp_path / "nowhere").exists()


def test_out_into_a_missing_folder_is_refused(tmp_path, cli):
    code, _, err = cli("--out", str(tmp_path / "no" / "p.html"))
    assert code == 1 and "no folder" in err


def test_one_session(tmp_path, cli):
    code, out, _ = cli("--session", "s1", "--out", str(tmp_path / "one.html"))
    html = (tmp_path / "one.html").read_text(encoding="utf-8")
    assert code == 0 and 'id="s-s1"' in html and 'id="s-s2"' not in html
    assert cli("--session", "s")[0:1] == (1,) and "fits 7 sessions" in cli("--session", "s")[2]
    assert "no session fits zz" in cli("--session", "zz")[2]
    assert cli("--session", "../x")[0] == 2


@pytest.mark.parametrize("argv", [["--days", "0"], ["--days", "x"], ["--nope"], ["--days", "3651"],
                                  ["--days", "1000000000"]])  # past datetime's range: no traceback
def test_usage_errors(cli, argv):
    assert cli(*argv)[0] == 2


def test_outside_a_repository(tmp_path, cli):
    (tmp_path / "plain").mkdir()
    code, _, err = cli(cwd=str(tmp_path / "plain"))
    assert code == 1 and "no git repository here" in err


def test_help(page):
    out = io.StringIO()
    assert page.main(["--help"], out) == 0 and "page.py [--days 7] [--session ID] [--out PATH]" in out.getvalue()


def test_git_variables_in_the_environment_do_not_move_the_repository(world, cli, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))  # as inside a git hook
    code, out, _ = cli()
    assert code == 0 and 'id="s-s1"' in pathlib.Path(out.strip()).read_text(encoding="utf-8")


def test_out_in_a_worktree_outside_the_repository_is_refused(world, cli, tmp_path):
    ext = tmp_path / "ext"  # its .git is a file, and no folder above it holds a .git
    git(world["repo"], "worktree", "add", "-q", "--detach", str(ext))
    code, out, err = cli("--out", str(ext / "page.html"))
    assert (code, out) == (1, "") and "lies in the git work tree" in err and not (ext / "page.html").exists()


def test_a_page_that_breaks_its_own_check_is_never_written(page, cli, tmp_path, monkeypatch):
    monkeypatch.setattr(page, "render", lambda data: "<script></script>")
    target = tmp_path / "bad.html"
    code, out, err = cli("--out", str(target))
    assert (code, out) == (1, "") and "breaks its own check" in err and not target.exists()


def test_pages_past_the_retention_are_named_and_kept(world, cli, tmp_path):
    pages = pathlib.Path(world["homes"][0]["telemetry"]) / "pages"
    pages.mkdir(parents=True)
    old, recent = pages / "20261001T000000Z.html", pages / "20261101T000000Z.html"  # 51 and 20 days before NOW
    for path in (old, recent, pages / "20261399T000000Z.html", pages / "20261001T000000Z.json",
                 pages / "notes.html"):  # no date, then two names this script never writes
        path.write_text("x")
    code, _, err = cli()
    assert (code, err) == (0, f"page: 1 of the pages in {pages} are older than 30 days, the retention of a page; "
                              "remove them\n")
    assert old.exists() and recent.exists()  # named, never removed
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "20261001T000000Z.html").write_text("x")
    assert cli("--out", str(mine / "p.html"))[2] == ""  # a folder given with --out is the owner's own


def test_a_branch_seen_only_through_its_reviews_is_a_task(page, world, git_calls):
    data = collected(page, world)
    solo = task(data, "feat/solo")
    assert (solo["sessions"], solo["cost"], solo["lookup"]) == ([], None, "ok")
    assert [r["sha"] for r in solo["reviews"]] == [world["solo"]] and solo["end"] is not None
    assert ["for-each-ref", "--format=%(refname)", "refs/heads/"] in [args for args, _ in git_calls]
    assert ["check-ref-format", "--branch", "feat/solo"] in [args for args, _ in git_calls]
    html = page.render(data)
    assert page.check_page(html) == [] and "no session on this branch in the window" in html


def test_a_page_of_one_session_holds_no_branch_seen_only_through_its_reviews(page, world):
    data = page.collect(world["project"], 7, world["homes"], now=NOW, prices=PRICES, session="s1")
    assert [t["branch"] for t in data["tasks"]] == ["feat/page"]
