"""Every recorded hook shape normalizes to the same Event, whichever harness sent it."""
import json
import pathlib

import pytest

EXPECT = {  # filename prefix -> (kind, has_command, has_path)
    "PreToolUse-Bash": ("shell", True, False),
    "PreToolUse-Read": ("read", False, True),
    "PreToolUse-Write": ("write", False, True),
    "PreToolUse-Edit": ("edit", False, True),
    "PreToolUse-Agent": ("spawn", False, False),
    "PreToolUse-bash": ("shell", True, False),
    "PreToolUse-powershell": ("shell", True, False),
    "PreToolUse-view": ("read", False, True),
    "PreToolUse-create": ("write", False, True),
    "PreToolUse-edit": ("edit", False, True),
    "PreToolUse-task": ("spawn", False, False),
    "preToolUse-bash": ("shell", True, False),
}


def _cases(fixtures):
    for harness in ("claude", "copilot"):
        for f in sorted((fixtures / "_shapes" / harness).glob("*.json")):
            yield harness, f


def test_shapes_exist(fixtures):
    assert len(list(_cases(fixtures))) >= 20


FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("harness,path", list(_cases(FIX)), ids=lambda p: getattr(p, "name", str(p)))
def test_harness_and_event(guard, harness, path):
    raw = json.loads(path.read_text())
    ev = guard.Event(raw)
    assert ev.harness == harness, f"{path.name}: harness {ev.harness}"
    assert ev.event in guard.EVENT_NAMES.values(), f"{path.name}: event {ev.event!r}"
    assert ev.cwd == "/work/repo"
    for prefix, (kind, has_cmd, has_path) in EXPECT.items():
        if path.name.startswith(prefix):
            assert ev.kind == kind, f"{path.name}: kind {ev.kind}"
            assert bool(ev.command) == has_cmd, f"{path.name}: command {ev.command!r}"
            assert bool(ev.path) == has_path, f"{path.name}: path {ev.path!r}"
            if has_path:
                assert ev.abspath().startswith("/work/repo/")
            break


def test_subagent_marker_present(guard, fixtures):
    raw = json.loads((fixtures / "_shapes/claude/PreToolUse-Bash-in-subagent.json").read_text())
    assert raw["agent_id"] and raw["agent_type"] == "general-purpose"
    assert "agent_id" not in json.loads((fixtures / "_shapes/claude/PreToolUse-Bash.json").read_text())


def test_write_content_extracted(guard, fixtures):
    for name in ("claude/PreToolUse-Write.json", "copilot/PreToolUse-create.json"):
        ev = guard.Event(json.loads((fixtures / "_shapes" / name).read_text()))
        assert ev.content == "hi", name


def test_unknown_tool_is_other(guard):
    ev = guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Frobnicate", "tool_input": {}})
    assert ev.kind == "other" and ev.harness == "unknown"


def test_cli_string_tool_args_are_parsed(guard, fixtures):
    """Plan step 3.8: a JSON-encoded toolArgs string must not read as "no arguments" (that let every call through)."""
    raw = json.loads((fixtures / "_shapes/copilot/preToolUse-bash-cli-string-args.json").read_text())
    assert isinstance(raw["toolArgs"], str)
    assert guard.Event(raw).command == "ls -la"
    raw["toolArgs"] = json.dumps({"command": "git push --force origin main"})
    got = guard.RULES["git-guard"](guard.Event(raw), dict(guard.DEFAULTS))
    assert got is not None and got[0] == "deny"
    raw["toolArgs"] = "not json"
    ev = guard.Event(raw)
    assert ev.args == {} and ev.unreadable, "an unparseable string: no arguments, and the event says so"


def test_unreadable_args_ask_before_the_tool_runs(guard, fixtures, tmp_path, monkeypatch):
    """Before the tool runs, a call whose arguments no rule can read must not pass silently."""
    monkeypatch.setenv("KZ_TELEMETRY_DIR", str(tmp_path / "t"))
    raw = json.loads((fixtures / "_shapes/copilot/preToolUse-bash-cli-string-args.json").read_text())
    raw["cwd"] = str(tmp_path)
    seen = []
    monkeypatch.setattr(guard, "_read_event", lambda: dict(raw))
    monkeypatch.setattr(guard, "respond", lambda final, event: seen.append(final) or 0)
    guard.run_hook("pre", None)
    assert seen[-1] is None, "a parseable string: the rules ran and nothing fired on `ls -la`"
    raw["toolArgs"] = "{not json"
    guard.run_hook("pre", None)
    assert seen[-1] is not None and seen[-1][0] == "ask" and "not JSON" in seen[-1][1]
    for text in ('["rm -rf /"]', '"git push --force"', "null", "[" * 100000):  # valid JSON, not an object
        raw["toolArgs"] = text
        guard.run_hook("pre", None)
        assert seen[-1] is not None and seen[-1][0] == "ask", text[:20]
    raw["toolArgs"] = "   "
    guard.run_hook("pre", None)
    assert seen[-1] is None, "an empty string is no arguments, not an unreadable call"
    raw["toolArgs"] = ["rm -rf /"]  # already decoded, still not an object
    guard.run_hook("pre", None)
    assert seen[-1] is not None and seen[-1][0] == "ask", "a native non-object hides the call too"
    raw["toolArgs"] = '{"command": "ls"}'
    monkeypatch.setattr(guard.json, "loads", lambda *_a, **_k: (_ for _ in ()).throw(RecursionError()))
    guard.run_hook("pre", None)
    assert seen[-1] is not None and seen[-1][0] == "ask", "RecursionError is caught, not a crash"
