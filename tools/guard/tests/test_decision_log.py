"""The decision log names the guard and the call, and the `post` hook records that an asked call ran (0.7.0, A3).

No hook event fires when the owner declines a prompt, so a `ran` line after an `ask` line of the same call is
the available evidence that the asked call went ahead."""

import io
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _pre(tmp_path, command, call="toolu_1", session="s1"):
    raw = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path), "session_id": session,
           "transcript_path": "/t", "tool_input": {"command": command}}
    if call is not None:
        raw["tool_use_id"] = call
    return raw


def _post(tmp_path, call="toolu_1", session="s1", event="PostToolUse"):
    raw = {"hook_event_name": event, "tool_name": "Bash", "cwd": str(tmp_path), "session_id": session,
           "transcript_path": "/t", "tool_input": {"command": "x"}, "tool_response": {"stdout": ""}}
    if call is not None:
        raw["tool_use_id"] = call
    return raw


def _hook(guard, monkeypatch, capsys, target, raw):
    data = raw if isinstance(raw, str) else json.dumps(raw)
    monkeypatch.setattr(sys, "stdin", io.StringIO(data))
    code = guard.main(["hook", target, "--wrapper", "claude"])
    return code, capsys.readouterr().out


def _log(tmp_path):
    return tmp_path / "telemetry" / "decisions.jsonl"


def _rows(tmp_path):
    path = _log(tmp_path)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_ask_and_deny_lines_carry_guard_and_call(guard, monkeypatch, capsys, tmp_path):
    assert _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "rm -rf build", call="toolu_a"))[0] == 0
    assert _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "git push --force origin main",
                                                         call="toolu_d"))[0] == 2
    rows = _rows(tmp_path)
    assert [r["verdict"] for r in rows] == ["ask", "deny"]
    assert [r["call"] for r in rows] == ["toolu_a", "toolu_d"]
    assert all(r["guard"] == guard.VERSION for r in rows)
    assert {"ts", "verdict", "rules", "tool", "event", "harness", "session"} <= set(rows[0])  # the old keys stay


def test_skipped_lines_carry_guard_and_call(guard, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("KZ_HOST_INSTALL", "off")  # silences host-install under every boundary: a skipped line
    assert _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "pip install requests", call="toolu_s")) == (0, "")
    (row,) = _rows(tmp_path)
    assert row["verdict"] == "skipped" and row["rules"] == {"host-install": "skipped"}
    assert row["call"] == "toolu_s" and row["guard"] == guard.VERSION


def test_a_line_without_a_call_id_has_no_call_key(guard, monkeypatch, capsys, tmp_path):
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "rm -rf build", call=None))
    (row,) = _rows(tmp_path)
    assert "call" not in row and row["guard"] == guard.VERSION


def test_post_records_one_ran_line_for_an_asked_call(guard, monkeypatch, capsys, tmp_path):
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "rm -rf build"))
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path)) == (0, "")
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path)) == (0, "")  # a repeated event
    rows = _rows(tmp_path)
    assert [r["verdict"] for r in rows] == ["ask", "ran"]
    ran = rows[1]
    assert ran["rules"] == {"delete-guard": "ran"} and ran["call"] == "toolu_1" and ran["session"] == "s1"
    assert ran["event"] == "PostToolUse" and ran["tool"] == "Bash" and ran["guard"] == guard.VERSION


def test_post_failure_is_recorded_with_its_event_name(guard, monkeypatch, capsys, tmp_path):
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "rm -rf build"))
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path, event="PostToolUseFailure")) == (0, "")
    assert _rows(tmp_path)[-1]["verdict"] == "ran" and _rows(tmp_path)[-1]["event"] == "PostToolUseFailure"


@pytest.mark.parametrize("call,session", [("toolu_other", "s1"), ("toolu_1", "s2")],
                         ids=["other-call", "other-session"])
def test_post_ignores_a_call_that_was_not_asked_here(guard, monkeypatch, capsys, tmp_path, call, session):
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "rm -rf build"))
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path, call=call, session=session)) == (0, "")
    assert [r["verdict"] for r in _rows(tmp_path)] == ["ask"]


def test_post_writes_nothing_after_a_deny_or_a_skip(guard, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("KZ_HOST_INSTALL", "off")
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "git push --force origin main", call="toolu_d"))
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "pip install requests", call="toolu_s"))
    for call in ("toolu_d", "toolu_s"):
        assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path, call=call)) == (0, "")
    assert [r["verdict"] for r in _rows(tmp_path)] == ["deny", "skipped"]


def test_post_without_a_log_is_a_no_op(guard, monkeypatch, capsys, tmp_path):
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path)) == (0, "")
    assert not _log(tmp_path).exists()


def test_post_with_an_unreadable_log_is_a_no_op(guard, monkeypatch, capsys, tmp_path):
    _log(tmp_path).mkdir(parents=True)  # a directory where the log should be: open() raises an OSError
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path)) == (0, "")


def test_post_skips_broken_lines(guard, monkeypatch, capsys, tmp_path):
    _log(tmp_path).parent.mkdir(parents=True)
    ask = {"ts": "2026-11-16T10:00:00Z", "verdict": "ask", "rules": {"delete-guard": "ask"}, "session": "s1",
           "call": "toolu_1"}
    broken = ["{not json", "[1, 2]", "\xff\xfe", json.dumps({"verdict": "ask", "session": "s1", "call": "toolu_9",
                                                             "rules": "delete-guard"})]
    _log(tmp_path).write_text("\n".join(broken + [json.dumps(ask)]) + "\n", encoding="utf-8")
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path)) == (0, "")
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path, call="toolu_9")) == (0, "")
    last = [json.loads(line) for line in _log(tmp_path).read_text(encoding="utf-8").splitlines()[-2:]]
    assert [(r["verdict"], r["call"]) for r in last] == [("ask", "toolu_1"), ("ran", "toolu_1")]


def test_post_reads_only_the_tail_of_a_long_log(guard, monkeypatch, capsys, tmp_path):
    _log(tmp_path).parent.mkdir(parents=True)
    old = {"verdict": "ask", "rules": {"delete-guard": "ask"}, "session": "s1", "call": "toolu_old"}
    new = dict(old, call="toolu_new")
    filler = json.dumps({"verdict": "deny", "rules": {"git-guard": "deny"}, "session": "s1", "pad": "x" * 200})
    lines = [json.dumps(old)] + [filler] * (guard.POST_TAIL_BYTES // len(filler) + 2) + [json.dumps(new)]
    _log(tmp_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for call in ("toolu_old", "toolu_new"):
        assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path, call=call)) == (0, "")
    assert [r["call"] for r in _rows(tmp_path)[-2:]] == ["toolu_new", "toolu_new"]


@pytest.mark.parametrize("raw", [
    "", "not json", "[]",
    {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s1", "transcript_path": "/t"},
    {"hookEventName": "postToolUse", "toolName": "bash", "sessionId": "s1", "timestamp": "2026-11-16T10:00:00Z",
     "toolArgs": "{\"command\": \"rm -rf build\"}", "tool_use_id": "toolu_1"},
], ids=["empty", "not-json", "list", "no-call-id", "copilot"])
def test_post_failure_cases_are_silent_no_ops(guard, monkeypatch, capsys, tmp_path, raw):
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "rm -rf build"))
    assert _hook(guard, monkeypatch, capsys, "post", raw) == (0, "")
    assert [r["verdict"] for r in _rows(tmp_path)] == ["ask"]


def test_post_runs_without_the_budget(guard, monkeypatch, capsys, tmp_path):
    _hook(guard, monkeypatch, capsys, "pre", _pre(tmp_path, "rm -rf build"))

    def no_fork():
        raise AssertionError("post forked a rules process")

    monkeypatch.setattr(guard.os, "fork", no_fork)
    assert _hook(guard, monkeypatch, capsys, "post", _post(tmp_path)) == (0, "")
    assert [r["verdict"] for r in _rows(tmp_path)] == ["ask", "ran"]


def test_pre_then_post_through_the_real_hook(guard_path, tmp_path):
    def hook(target, raw):
        return subprocess.run([sys.executable, guard_path, "hook", target, "--wrapper", "claude"],
                              input=json.dumps(raw), capture_output=True, text=True, timeout=30, cwd=str(tmp_path))

    assert hook("pre", _pre(tmp_path, "rm -rf build")).returncode == 0
    r = hook("post", _post(tmp_path))
    assert (r.returncode, r.stdout) == (0, "")
    assert [(row["verdict"], row["call"]) for row in _rows(tmp_path)] == [("ask", "toolu_1"), ("ran", "toolu_1")]


def test_settings_wire_post_for_both_post_events():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = 'python3 "${CLAUDE_PROJECT_DIR:-.}"/tools/guard/guard.py hook post --wrapper claude'
    for event in ("PostToolUse", "PostToolUseFailure"):
        groups = [g for g in settings["hooks"].get(event, []) if any(h["command"] == command for h in g["hooks"])]
        assert len(groups) == 1, event
        assert groups[0]["matcher"] == ("Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Agent|Task|Monitor|ExitWorktree"
                                        "|Skill|Workflow|RemoteTrigger|DesignSync|mcp__github__.*")  # 0.10.0
        (hook,) = groups[0]["hooks"]
        assert hook == {"type": "command", "command": command, "timeout": 5, "statusMessage": "guard"}


def test_copilot_wiring_has_no_post_hook():
    data = json.loads((ROOT / ".github" / "hooks" / "guard.json").read_text(encoding="utf-8"))
    assert "hook post" not in json.dumps(data)


def test_usage_names_the_post_target(guard):
    assert "hook post" in guard.__doc__
