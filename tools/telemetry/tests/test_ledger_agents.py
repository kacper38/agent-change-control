import json
import os
import pathlib

import pytest

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "agents"
PROJECT = FIX / "config" / "projects" / "-work-demo"
SESSIONS = {
    "plain": "11111111-1111-4111-8111-111111111111",
    "two-agents": "22222222-2222-4222-8222-222222222222",
    "workflow": "33333333-3333-4333-8333-333333333333",
    "nested": "44444444-4444-4444-8444-444444444444",
    "running": "55555555-5555-4555-8555-555555555555",
    "broken": "66666666-6666-4666-8666-666666666666",
    "noprice": "11111111-9999-4999-8999-999999999999",
}
# (kind, depth, state, tool calls, seconds) per row, in print order, as fixtures/agents/README.md derives them
FIXTURE_ROWS = {
    "plain": [("session", 0, "finished", 1, 245)],
    "two-agents": [("session", 0, "finished", 2, 930), ("agent", 1, "finished", 2, 570),
                   ("agent", 1, "finished", 3, 285)],
    "workflow": [("session", 0, "finished", 1, 1230), ("workflow", 1, "finished", 4, 1173),
                 ("agent", 2, "finished", 3, 600), ("agent", 2, "finished", 1, 570)],
    "nested": [("session", 0, "finished", 2, 2410), ("agent", 1, "finished", 1, 1192),
               ("agent", 2, "finished", 2, 838), ("agent", 1, "finished", 1, 1189)],
    "running": [("session", 0, "running", 5, 30), ("agent", 1, "running", 2, 184), ("agent", 1, "running", 1, 9),
                ("agent", 1, "running", 0, 0), ("agent", 1, "finished", 1, 36), ("workflow", 1, "running", 0, 18),
                ("agent", 2, "running", 0, 18)],
    "broken": [("session", 0, "finished", 4, 630), ("agent", 1, "finished", 1, 584), ("missing", 1, "-", None, None),
               ("agent", 1, "finished", 0, 30), ("agent", 1, "finished", 0, 40)],
    "noprice": [("session", 0, "finished", 0, 42)],
}
OWN_COST = {"plain": 6.0, "two-agents": 7.75, "workflow": 6.11, "nested": 4.82, "running": 3.254, "broken": 2.65}


@pytest.fixture(scope="module")
def prices(ledger):
    return ledger.load_prices(str(FIX / "prices.json"))


def fixture_transcript(name):
    sid = SESSIONS[name]
    project = "-work-other" if name == "noprice" else "-work-demo"
    return str(FIX / "config" / "projects" / project / f"{sid}.jsonl")


def ts(sec):
    return f"2026-01-05T10:{sec // 60:02d}:{sec % 60:02d}.000Z"


def asst(content=None, stop="end_turn", req=None, model="claude-opus-5-5", inp=100, out=10, sec=0, **extra):
    msg = {"model": model, "content": content if content is not None else [{"type": "text", "text": "r"}],
           "usage": {"input_tokens": inp, "output_tokens": out}}
    if stop is not ...:
        msg["stop_reason"] = stop
    d = {"type": "assistant", "timestamp": ts(sec), "message": msg}
    if req:
        d["requestId"] = req
    d.update(extra)
    return d


def user(content, sec=0):
    return {"type": "user", "timestamp": ts(sec), "message": {"role": "user", "content": content}}


def tool_use(tid, name="Read"):
    return {"type": "tool_use", "id": tid, "name": name, "input": {}}


def tool_result(tid):
    return [{"type": "tool_result", "tool_use_id": tid, "content": "x"}]


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines), encoding="utf-8")
    return path


def make_session(tmp_path, main_lines, agents=(), sid="s-1"):
    """A session under tmp_path/config/projects/-p; agents = [(relative dir, agent id, lines, meta or None)]."""
    proj = tmp_path / "config" / "projects" / "-p"
    main = write_lines(proj / f"{sid}.jsonl", main_lines)
    for rel, aid, lines, meta in agents:
        folder = proj / sid / "subagents" / rel
        write_lines(folder / f"agent-{aid}.jsonl", lines)
        if meta is not None:
            (folder / f"agent-{aid}.meta.json").write_text(meta if isinstance(meta, str) else json.dumps(meta))
    return str(main)


OPUS = {"claude-opus-5-5": {"input": 1.0, "output": 1.0, "cache_read": 1.0, "cache_write": 1.0}}


def tree(ledger, transcript, tdir, prices=None):
    return ledger.read_agents(transcript, str(tdir), OPUS if prices is None else prices)


def agent_state(ledger, tmp_path, lines):
    t = make_session(tmp_path, [asst(), {"type": "cost-state", "totalCostUSD": 0.1}], [("", "x1", lines, None)])
    return tree(ledger, t, tmp_path / "telemetry")["rows"][1]["state"]


# 4.4, the agent table: one case per row
@pytest.mark.parametrize("lines, state", [
    ([{"type": "system", "subtype": "x"}], "running"),  # no assistant or user line
    ([user("brief"), asst(stop=None)], "running"),
    ([user("brief"), asst(stop=...)], "running"),  # stop_reason missing
    ([user("brief"), asst([tool_use("t1")], stop="tool_use")], "running"),
    ([user("brief"), asst(stop="pause_turn")], "running"),
    ([user("brief"), asst(stop="end_turn"), {"type": "system"}, {"type": "attachment"}], "finished"),
    ([user("brief"), asst(stop="max_tokens")], "finished"),
    ([user("brief"), asst(stop=None), user("[Request interrupted by user]")], "finished"),
    ([user("brief"), asst(stop=None), user([{"type": "text", "text": "[Request interrupted by user for tool use]"}])],
     "finished"),
    ([user("brief"), asst([tool_use("t1", "StructuredOutput")], stop="tool_use"), user(tool_result("t1"))],
     "finished"),
    ([user("brief"), asst([tool_use("t1", "SubagentHandback")], stop="tool_use"), user(tool_result("t1")),
      {"type": "last-prompt"}], "finished"),
    ([user("brief"), asst([tool_use("t1", "Glob")], stop="tool_use"), user(tool_result("t1"))], "running"),
    ([user("brief")], "running"),
    ([user("brief"), asst(stop="end_turn"), user("one more thing")], "running"),
])
def test_agent_state_table(ledger, tmp_path, lines, state):
    assert agent_state(ledger, tmp_path, lines) == state


def test_agent_end_tools_are_one_constant(ledger):
    assert set(ledger.AGENT_END_TOOLS) == {"StructuredOutput", "SubagentHandback"}


# 4.4, the session rule
@pytest.mark.parametrize("lines, state", [
    ([user("p"), asst(), {"type": "cost-state", "totalCostUSD": 1.0}, {"type": "last-prompt"}], "finished"),
    ([user("p"), asst()], "running"),
    ([user("p"), asst(), {"type": "cost-state", "totalCostUSD": 1.0}, user("resumed"), asst()], "running"),
    ([{"type": "cost-state", "totalCostUSD": 1.0}], "finished"),  # no assistant or user line at all
    ([{"type": "system"}], "running"),
])
def test_session_state(ledger, tmp_path, lines, state):
    t = make_session(tmp_path, lines)
    assert tree(ledger, t, tmp_path / "telemetry")["rows"][0]["state"] == state


@pytest.fixture
def fixture_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(FIX / "config"))
    monkeypatch.setenv("KZ_TELEMETRY_DIR", str(FIX / "telemetry"))


@pytest.mark.parametrize("name", sorted(SESSIONS))
def test_fixture_rows(ledger, prices, fixture_env, name):
    data = ledger.read_agents(fixture_transcript(name), str(FIX / "telemetry"), prices)
    got = [(r["kind"], r["depth"], r["state"], r["tools"], r["seconds"]) for r in data["rows"]]
    assert got == FIXTURE_ROWS[name]


@pytest.mark.parametrize("name", sorted(OWN_COST))
def test_fixture_costs_add_up_to_own_count(ledger, prices, fixture_env, name):
    data = ledger.read_agents(fixture_transcript(name), str(FIX / "telemetry"), prices)
    lines = [r["cost"] for r in data["rows"] if r["kind"] in ("session", "agent") and r["cost"] is not None]
    entry = ledger.build_entry({"session_id": SESSIONS[name], "transcript_path": fixture_transcript(name)},
                               str(FIX / "telemetry"), prices)
    assert sum(lines) == pytest.approx(entry["cost_usd_own"], abs=0.00005)
    assert sum(lines) == pytest.approx(OWN_COST[name], abs=1e-9)
    assert data["total"]["cost"] == pytest.approx(sum(lines), abs=1e-12)


def test_noprice_fixture_has_no_cost(ledger, prices, fixture_env):
    data = ledger.read_agents(fixture_transcript("noprice"), str(FIX / "telemetry"), prices)
    assert data["rows"][0]["cost"] is None and data["total"]["cost"] is None
    assert data["unpriced_models"] == ["claude-next-9"]


def test_workflow_fixture_sums_and_skips_the_journal(ledger, prices, fixture_env):
    rows = ledger.read_agents(fixture_transcript("workflow"), str(FIX / "telemetry"), prices)["rows"]
    wf = rows[1]
    assert wf["label"] == "workflow  demo-build"
    assert wf["cost"] == pytest.approx(4.41) and wf["model"] == "opus-5-5 +1"
    # the journal's one usage line holds 9,000,000 tokens at the Opus rates: counted, it would cost hundreds
    assert sum(r["cost"] for r in rows if r["kind"] != "workflow") == pytest.approx(6.11)
    assert sum(r["tools"] for r in rows if r["kind"] != "workflow") == 5


def test_broken_fixture_counts_what_it_could_not_read(ledger, prices, fixture_env):
    data = ledger.read_agents(fixture_transcript("broken"), str(FIX / "telemetry"), prices)
    assert (data["files_not_read"], data["lines_not_read"]) == (1, 2)
    labels = [r["label"] for r in data["rows"][1:]]
    assert labels == ["python-engineer  Repair the importer", "code-reviewer  (no transcript)", "python-engineer",
                      "agent"]
    assert data["total"]["agents"] == 4 and data["total"]["running"] == 0


def ids_of(data):
    return sorted(r["agent_id"] for r in data["rows"] if r["kind"] == "agent")


def test_one_agent_id_in_two_files_gives_two_rows(ledger, tmp_path):
    lines = [user("b", 1), asst(sec=2)]
    t = make_session(tmp_path, [asst()], [("", "dup", lines, {"agentType": "a"}),
                                          ("workflows/wf_1", "dup", lines, {"agentType": "b"})])
    data = tree(ledger, t, tmp_path / "telemetry")
    assert ids_of(data) == ["dup", "dup"]
    assert [r["kind"] for r in data["rows"]] == ["session", "agent", "workflow", "agent"]


@pytest.mark.parametrize("parents", [
    {"a1": "a1"},  # names itself
    {"a1": "a2", "a2": "a1"},  # a pair that name each other
    {"a1": "a3", "a2": "a3", "a3": "a1"},  # a ring of three
    {"a1": "nobody"},  # an id no transcript of the session carries
    {"a1": 7, "a2": ["a1"]},  # no string
])
def test_parent_links_never_lose_or_repeat_a_transcript(ledger, tmp_path, parents):
    agents = [("", aid, [user("b", i), asst(sec=i + 1)], {"agentType": aid, "parentAgentId": parents.get(aid)})
              for i, aid in enumerate(["a1", "a2", "a3"])]
    data = tree(ledger, make_session(tmp_path, [asst()], agents), tmp_path / "telemetry")
    assert ids_of(data) == ["a1", "a2", "a3"]
    by_id = {r["agent_id"]: r for r in data["rows"] if r["kind"] == "agent"}
    for r in data["rows"][1:]:  # every parent is printed before its child
        assert data["rows"].index(r) > r["parent"]
    assert any(by_id[a]["depth"] == 1 for a in by_id)


def test_parent_link_hangs_an_agent_under_its_parent(ledger, tmp_path):
    agents = [("", "a1", [user("b", 1), asst(sec=9)], {"agentType": "outer"}),
              ("", "a2", [user("b", 3), asst(sec=5)], {"agentType": "inner", "parentAgentId": "a1"})]
    rows = tree(ledger, make_session(tmp_path, [asst()], agents), tmp_path / "telemetry")["rows"]
    assert [(r["label"], r["depth"]) for r in rows[1:]] == [("outer", 1), ("inner", 2)]


def test_rows_sort_by_time_not_text_and_rows_without_time_come_last(ledger, tmp_path):
    agents = [("", "a1", [{"type": "user", "timestamp": "2026-01-05T11:00:00+01:00", "message": {}}], None),
              ("", "a2", [{"type": "user", "timestamp": "2026-01-05T10:30:00Z", "message": {}}], None),
              ("", "a0", [{"type": "user", "message": {}}], None)]
    rows = tree(ledger, make_session(tmp_path, [asst()], agents), tmp_path / "telemetry")["rows"]
    assert [r["agent_id"] for r in rows[1:]] == ["a1", "a2", "a0"]  # 10:00 UTC, 10:30 UTC, none


def test_lines_of_the_wrong_shape_never_raise(ledger, tmp_path):
    bad = ["[]", '"x"', "3", "null", "{not json",
           {"type": "assistant", "message": "text"},
           {"type": "assistant", "message": {"content": "text", "usage": [], "stop_reason": 3}},
           {"type": "assistant", "message": {"content": [3, None, {"type": "tool_use", "id": 5}], "stop_reason": []}},
           {"type": "assistant", "message": {"content": [{"type": "tool_use"}], "usage": {"input_tokens": "lots"},
                                             "model": "claude-opus-5-5"}, "requestId": "r9"},
           {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": ["x"]}, 4]}},
           {"type": "user", "message": {"content": {"text": "[Request interrupted"}}},
           {"type": "user", "timestamp": 1767618120000, "message": None},
           {"type": "user", "timestamp": "not a time"},
           {"type": "user", "timestamp": ["2026-01-05T10:00:00Z"]}]
    t = make_session(tmp_path, [asst(sec=1)] + bad, [("", "x1", bad, None)])
    data = tree(ledger, t, tmp_path / "telemetry")
    agent = data["rows"][1]
    assert agent["tools"] == 2 and agent["seconds"] is None and agent["state"] == "running"
    assert data["rows"][0]["seconds"] == 0  # one readable timestamp
    assert data["lines_not_read"] == 4  # per transcript: the cut line and the usage that is no number
    assert data["files_not_read"] == 0


@pytest.mark.parametrize("meta", ["[]", '{"agentType": 3, "description": ["x"], "parentAgentId": {}}', "{cut",
                                  "null", '"text"'])
def test_meta_files_of_the_wrong_shape(ledger, tmp_path, meta):
    t = make_session(tmp_path, [asst()], [("", "x1", [user("b"), asst()], meta)])
    data = tree(ledger, t, tmp_path / "telemetry")
    assert data["rows"][1]["label"] == "agent"
    assert data["files_not_read"] == (0 if meta.startswith("{\"") else 1)


def test_a_transcript_that_cannot_be_opened(ledger, tmp_path):
    t = make_session(tmp_path, [asst()])
    sub = pathlib.Path(t).with_suffix("") / "subagents"
    sub.mkdir(parents=True)
    os.symlink(str(tmp_path / "gone.jsonl"), str(sub / "agent-x.jsonl"))
    data = tree(ledger, t, tmp_path / "telemetry")
    row = data["rows"][1]
    assert (row["kind"], row["state"], row["seconds"], row["cost"], row["tools"], row["model"]) == \
        ("agent", "-", None, None, None, None)
    assert (data["files_not_read"], data["lines_not_read"]) == (1, 0)
    assert data["total"]["agents"] == 1 and data["total"]["cost"] == data["rows"][0]["cost"]  # `-` adds nothing


def test_spawn_log_rows_of_the_wrong_shape(ledger, tmp_path):
    t = make_session(tmp_path, [asst()], [("", "a1", [user("b", 5)], None)], sid="s-9")
    log = tmp_path / "telemetry" / "spawns.jsonl"
    write_lines(log, [
        "[]", "3", "{cut", "",
        {"event": "SubagentStart", "session": "s-9", "agent_id": 12, "agent": "num"},
        {"event": "SubagentStart", "session": "s-9", "agent_id": None, "agent": "none"},
        {"event": "PreToolUse", "session": "s-9", "agent_id": "a7", "agent": "pre"},
        {"event": "SubagentStart", "session": "other", "agent_id": "a8", "agent": "other"},
        {"event": "SubagentStart", "session": "s-9", "agent_id": "a1", "agent": "from-log"},
        {"event": "SubagentStart", "session": "s-9", "agent_id": "a5", "agent": ["x"], "ts": 4},
        {"event": "SubagentStart", "session": "s-9", "agent_id": "a6", "agent": "late", "ts": "2026-01-05T10:00:09Z"},
        {"event": "SubagentStart", "session": "s-9", "agent_id": "a6", "agent": "late", "ts": "2026-01-05T10:00:01Z"},
    ])
    data = tree(ledger, t, tmp_path / "telemetry")
    got = [(r["kind"], r["label"]) for r in data["rows"][1:]]
    assert got == [("missing", "late  (no transcript)"), ("agent", "from-log"), ("missing", "agent  (no transcript)")]
    assert data["lines_not_read"] == 1 and data["files_not_read"] == 0


def test_no_spawn_log_and_no_subagents_folder(ledger, tmp_path):
    data = tree(ledger, make_session(tmp_path, [asst()]), tmp_path / "nothing-here")
    assert [r["kind"] for r in data["rows"]] == ["session"]
    assert (data["files_not_read"], data["lines_not_read"]) == (0, 0)


def test_model_label(ledger, tmp_path):
    lines = [asst(model="claude-opus-5-5", req="r1"), asst(model="claude-haiku-5-5", req="r2"),
             asst(model="claude-haiku-5-5", req="r3"), asst(model="claude-fable-5-2", req="r4"),
             asst(model="<synthetic>", req="r5", inp=0, out=0)]
    rows = tree(ledger, make_session(tmp_path, lines), tmp_path / "telemetry")["rows"]
    assert rows[0]["model"] == "haiku-5-5 +2"
    long = [asst(model="a-model-name-that-is-long", req="r1")]
    rows = tree(ledger, make_session(tmp_path / "b", long), tmp_path / "telemetry")["rows"]
    assert rows[0]["model"] == "a-model-nam..."
