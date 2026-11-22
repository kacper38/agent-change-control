"""fan-out keeps state in the spawn log, so it is tested against a temporary telemetry dir."""
import json


def _spawn(guard, session="s1", agent="python-engineer", model=None, harness="claude"):
    if harness == "claude":
        ti = {"description": "d", "prompt": "p", "subagent_type": agent}
        if model:
            ti["model"] = model
        raw = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "cwd": "/work/repo", "session_id": session,
               "transcript_path": "~/x.jsonl", "tool_input": ti}
    else:
        raw = {"hook_event_name": "PreToolUse", "tool_name": "task", "cwd": "/work/repo", "session_id": session,
               "timestamp": "t", "tool_input": {"description": "d", "prompt": "p"}}
    return guard.Event(raw)


def _cfg(guard, tmp_path):
    return {**guard.DEFAULTS, "telemetry_dir": str(tmp_path / "telemetry")}


def test_asks_at_sixth_and_every_tenth(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: False)
    cfg = _cfg(guard, tmp_path)
    verdicts = [guard.rule_fan_out(_spawn(guard), cfg) for _ in range(27)]
    asked = [i + 1 for i, v in enumerate(verdicts) if v is not None]
    assert asked == [6, 16, 26]
    assert all(v[0] == "ask" for v in verdicts if v), "fan-out never denies"
    assert "#6" in verdicts[5][1] and "llama" not in verdicts[5][1]


def test_sessions_counted_separately(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: False)
    cfg = _cfg(guard, tmp_path)
    for _ in range(5):
        assert guard.rule_fan_out(_spawn(guard, session="a"), cfg) is None
    assert guard.rule_fan_out(_spawn(guard, session="b"), cfg) is None, "first spawn of another session"
    assert guard.rule_fan_out(_spawn(guard, session="a"), cfg)[0] == "ask"


def test_log_lines_carry_agent_and_model(guard, tmp_path):
    cfg = _cfg(guard, tmp_path)
    guard.rule_fan_out(_spawn(guard, agent="code-reviewer", model="opus"), cfg)
    guard.rule_fan_out(_spawn(guard, harness="copilot"), cfg)
    start = guard.Event({"hook_event_name": "SubagentStart", "cwd": "/work/repo", "session_id": "s1",
                         "agent_id": "a1", "agent_type": "code-reviewer", "transcript_path": "~/x.jsonl"})
    assert guard.rule_fan_out(start, cfg) is None
    rows = [json.loads(line) for line in (tmp_path / "telemetry" / "spawns.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows] == ["PreToolUse", "PreToolUse", "SubagentStart"]
    assert rows[0]["agent"] == "code-reviewer" and rows[0]["model"] == "opus" and rows[0]["harness"] == "claude"
    assert rows[1]["harness"] == "copilot"
    assert rows[2]["agent"] == "code-reviewer" and rows[2]["agent_id"] == "a1"
    assert all(set(r) >= {"ts", "harness", "agent", "model", "session"} for r in rows)


def test_subagent_start_does_not_count(guard, tmp_path, monkeypatch):
    # 0.12.0 (D4, A5 of item #67): SubagentStart rows count toward the total, a workflow's agents too; the hook
    # itself never answers (it cannot block), so the next Agent call asks
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: False)
    cfg = _cfg(guard, tmp_path)
    start = guard.Event({"hook_event_name": "SubagentStart", "cwd": "/work/repo", "session_id": "s1",
                         "agent_id": "a1", "agent_type": "x", "transcript_path": "~/x.jsonl"})
    for _ in range(10):
        assert guard.rule_fan_out(start, cfg) is None
    got = guard.rule_fan_out(_spawn(guard), cfg)
    assert got is not None and got[0] == "ask" and "#11 " in got[1], got


def test_llama_note_when_port_answers(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "llama_server_up", lambda port=0: True)
    cfg = _cfg(guard, tmp_path)
    for _ in range(5):
        guard.rule_fan_out(_spawn(guard), cfg)
    got = guard.rule_fan_out(_spawn(guard), cfg)
    assert got[0] == "ask" and "llama-server is up" in got[1] and "8012" in got[1]


def test_unwritable_log_never_blocks(guard, tmp_path, capsys):
    blocker = tmp_path / "telemetry"
    blocker.write_text("not a directory")
    cfg = {**guard.DEFAULTS, "telemetry_dir": str(blocker)}
    assert guard.rule_fan_out(_spawn(guard), cfg) is None
    assert "spawn log failed" in capsys.readouterr().err
