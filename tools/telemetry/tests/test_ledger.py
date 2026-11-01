import datetime as dt
import io
import json
import os

PRICES = {"claude-opus-4-5": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_write": 6.25},
          "claude-fable-5-1": None}


def line(model, inp, out, cr=0, cw=0, req=None, typ="assistant"):
    return json.dumps({
        "type": typ, "requestId": req, "sessionId": "s1",
        "message": {"model": model, "usage": {"input_tokens": inp, "output_tokens": out,
                                              "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}},
    })


def write_transcript(tmp_path, session="s1", subagents=1):
    proj = tmp_path / "projects" / "-Users-t-x"
    proj.mkdir(parents=True)
    main = proj / f"{session}.jsonl"
    main.write_text("\n".join([
        line("claude-fable-5-1", 100, 50, cr=1000, cw=200, req="r1"),
        line("claude-fable-5-1", 100, 50, cr=1000, cw=200, req="r1"),  # streamed duplicate: counted once
        json.dumps({"type": "user", "message": {"role": "user"}}),
        "not json at all",
        line("claude-fable-5-1", 10, 5, req="r2"),
        line("<synthetic>", 0, 0, req="r3"),  # Claude Code writes these for aborted turns: no usage, no row
        line("claude-fable-5-1", 1, 1),  # two lines without any id: each counts, they must not collapse
        line("claude-fable-5-1", 1, 1),
        json.dumps(["not", "an", "object"]),
        json.dumps({"type": "assistant", "message": {"model": "claude-fable-5-1",
                                                     "usage": {"input_tokens": 5, "output_tokens": "lots"}}}),
    ]) + "\n", encoding="utf-8")
    sub = proj / session / "subagents"
    sub.mkdir(parents=True)
    for i in range(subagents):
        (sub / f"agent-{i}.jsonl").write_text(line("claude-opus-4-5", 1000, 2000, cr=3000, cw=400, req=f"a{i}") + "\n")
    return main


def test_parse_transcript_dedups_and_counts_errors(ledger, tmp_path):
    main = write_transcript(tmp_path)
    usage, errors = ledger.parse_transcript(str(main))
    assert errors == 2  # one unparsable line, one non-numeric usage
    assert usage["claude-fable-5-1"] == {"input": 112, "output": 57, "cache_read": 1000, "cache_write": 200,
                                         "turns": 4}  # the half-numeric turn added nothing, not even its 5 input
    assert usage["<synthetic>"]["turns"] == 1


def test_price_lookup_by_longest_prefix(ledger):
    prices = {"claude-opus": {"input": 1, "output": 1, "cache_read": 1, "cache_write": 1}, **PRICES}
    assert ledger.price_for("claude-opus-4-5-20251101", prices)["input"] == 5.0
    assert ledger.price_for("claude-opus-9", prices)["input"] == 1
    assert ledger.price_for("claude-fable-5-1", prices) is None
    assert ledger.price_for("gpt-x", prices) is None


def test_build_entry_joins_subagents_spawns_and_prices(ledger, tmp_path, tdir):
    main = write_transcript(tmp_path, subagents=2)
    tdir.mkdir()
    (tdir / "spawns.jsonl").write_text("\n".join([
        json.dumps({"session": "s1", "event": "PreToolUse", "agent": "python-engineer", "model": "opus"}),
        json.dumps({"session": "s1", "event": "SubagentStart", "agent": None, "model": None}),
        json.dumps({"session": "other", "event": "PreToolUse", "agent": "x", "model": None}),
    ]) + "\n")
    raw = {"session_id": "s1", "transcript_path": str(main), "cwd": "/Users/t/x", "reason": "exit"}
    e = ledger.build_entry(raw, str(tdir), PRICES, now=dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc))
    assert e["ts"] == "2026-10-29T12:00:00Z" and e["project"] == "/Users/t/x" and e["parse_errors"] == 2
    assert e["models"]["claude-fable-5-1"]["cost_usd"] is None
    assert "<synthetic>" not in e["models"]
    opus = e["models"]["claude-opus-4-5"]
    assert opus["input"] == 2000 and opus["turns"] == 2
    assert opus["cost_usd"] == round((2000 * 5 + 4000 * 25 + 6000 * 0.5 + 800 * 6.25) / 1e6, 6)
    assert e["cost_usd"] is None  # one model unpriced → the session total stays honest
    assert e["subagents"]["transcripts"] == 2 and e["subagents"]["flag"] is True
    assert e["spawns"] == [{"agent": "python-engineer", "model": "opus"}]


def test_hook_appends_monthly_file_and_never_fails(ledger, tmp_path, tdir):
    main = write_transcript(tmp_path)
    raw = json.dumps({"session_id": "s1", "transcript_path": str(main), "cwd": "/Users/t/x", "reason": "exit"})
    err = io.StringIO()
    assert ledger.main(["hook"], stdin=io.StringIO(raw), out=io.StringIO(), err=err) == 0
    files = sorted(f for f in os.listdir(tdir) if not f.startswith("."))  # the lock file is a dotfile
    assert len(files) == 1 and files[0].startswith("sessions-") and files[0].endswith(".jsonl")
    row = json.loads((tdir / files[0]).read_text().splitlines()[0])
    assert row["session"] == "s1"
    # garbage in: exit 0 and nothing to count, so no line; a transcript path that does not exist: a line with errors
    assert ledger.main(["hook"], stdin=io.StringIO("{{{"), out=io.StringIO(), err=err) == 0
    assert len((tdir / files[0]).read_text().splitlines()) == 1
    assert ledger.main(["hook"], stdin=io.StringIO(json.dumps({"transcript_path": "/nope.jsonl"})),
                       out=io.StringIO(), err=err) == 0
    rows = [json.loads(ln) for ln in (tdir / files[0]).read_text().splitlines()]
    assert len(rows) == 2 and rows[1]["parse_errors"] >= 1 and rows[1]["models"] == {}


def test_hook_writes_one_line_per_session_id(ledger, tmp_path, tdir):
    main = write_transcript(tmp_path)
    raw = json.dumps({"session_id": "s1", "transcript_path": str(main), "cwd": "/Users/t/x", "reason": "exit"})
    for _ in range(2):  # the project hook and the user hook fire on the same SessionEnd
        assert ledger.main(["hook"], stdin=io.StringIO(raw), out=io.StringIO(), err=io.StringIO()) == 0
    files = sorted(f for f in os.listdir(tdir) if not f.startswith("."))
    path = tdir / files[0]
    rows = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert len(files) == 1 and [r["session"] for r in rows] == ["s1"]
    assert rows[0]["models"]["claude-fable-5-1"]["turns"] == 4
    with open(main, "a", encoding="utf-8") as fh:  # the session is resumed and ends again: cumulative, one line
        fh.write(line("claude-fable-5-1", 7, 7, req="r9") + "\n")
    assert ledger.main(["hook"], stdin=io.StringIO(raw), out=io.StringIO(), err=io.StringIO()) == 0
    rows = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert [r["session"] for r in rows] == ["s1"] and rows[0]["models"]["claude-fable-5-1"]["turns"] == 5
    other = json.dumps({"session_id": "s2", "transcript_path": str(main), "cwd": "/Users/t/x", "reason": "exit"})
    assert ledger.main(["hook"], stdin=io.StringIO(other), out=io.StringIO(), err=io.StringIO()) == 0
    rows = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert [r["session"] for r in rows] == ["s1", "s2"], "another session is another line, order kept"
    assert ledger.main(["hook"], stdin=io.StringIO(raw), out=io.StringIO(), err=io.StringIO()) == 0
    rows = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert [r["session"] for r in rows] == ["s2", "s1"], "the replaced line moves to the end: last end wins"
    raw_bytes = b'{"session": "s0", "ts": "2026-10-29T00:00:00Z", "note": "caf\xe9"}\n'  # not UTF-8: kept as is
    with open(path, "ab") as fh:
        fh.write(raw_bytes)
    assert ledger.main(["hook"], stdin=io.StringIO(raw), out=io.StringIO(), err=io.StringIO()) == 0
    assert raw_bytes in path.read_bytes() and not os.path.exists(str(path) + ".tmp")


def test_load_sessions_keeps_the_last_row_per_session_across_files(ledger, tdir):
    tdir.mkdir()
    row = {"session": "dup", "project": "/p", "models": {}, "spawns": [], "subagents": {}}
    (tdir / "sessions-2026-09.jsonl").write_text(json.dumps({**row, "ts": "2026-09-30T23:59:00Z", "n": 1}) + "\n")
    (tdir / "sessions-2026-10.jsonl").write_text("\n".join([
        json.dumps({**row, "ts": "2026-10-01T00:10:00Z", "n": 2}),
        json.dumps({**row, "session": "", "ts": "2026-10-01T00:11:00Z", "n": 3}),
        json.dumps({**row, "session": "", "ts": "2026-10-01T00:12:00Z", "n": 4}),
    ]) + "\n")
    rows = ledger.load_sessions(str(tdir), dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc))
    assert sorted(r["n"] for r in rows) == [2, 3, 4], "one row for `dup` (the later one); id-less rows all stay"


def test_hook_writes_nothing_for_copilot_or_without_transcript(ledger, tdir):
    for raw in ({"timestamp": "2026-10-29T10:00:00Z", "session_id": "c1", "transcript_path": "/x.jsonl"},
                {"session_id": "s2", "cwd": "/Users/t/x", "reason": "exit"}):
        assert ledger.main(["hook"], stdin=io.StringIO(json.dumps(raw)), out=io.StringIO(), err=io.StringIO()) == 0
    assert not tdir.exists()


def test_hook_writes_an_error_line_when_the_builder_raises(ledger, tdir, monkeypatch):
    monkeypatch.setattr(ledger, "build_entry", lambda *a, **k: (_ for _ in ()).throw(KeyError("boom")))
    raw = json.dumps({"session_id": "s9", "transcript_path": "/x.jsonl", "cwd": "/Users/t/x"})
    assert ledger.main(["hook"], stdin=io.StringIO(raw), out=io.StringIO(), err=io.StringIO()) == 0
    month = next(f for f in os.listdir(tdir) if f.startswith("sessions-"))
    row = json.loads((tdir / month).read_text().splitlines()[0])
    assert row["session"] == "s9" and row["parse_errors"] == 1 and row["error"].startswith("KeyError")


def test_cost_report(ledger, tdir):
    tdir.mkdir()
    now = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)
    rows = [
        {"ts": "2026-10-28T10:00:00Z", "session": "abcdefgh1", "project": "/Users/t/alpha", "spawns": [{}, {}],
         "subagents": {"flag": True},
         "models": {"claude-opus-4-5": {"input": 10, "output": 20, "cache_read": 0, "cache_write": 0, "turns": 1,
                                        "cost_usd": 0.5},
                    "claude-fable-5-1": {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0, "turns": 1,
                                         "cost_usd": None}}},
        {"ts": "2026-09-01T10:00:00Z", "session": "old", "project": "/Users/t/alpha", "spawns": [],
         "subagents": {"flag": False},
         "models": {"claude-opus-4-5": {"input": 999, "output": 0, "cache_read": 0, "cache_write": 0, "turns": 1,
                                        "cost_usd": 9.0}}},
    ]
    (tdir / "sessions-2026-10.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tdir / "decisions.jsonl").write_text("\n".join([
        json.dumps({"ts": "2026-10-28T11:00:00Z", "verdict": "ask", "rules": ["delete-guard"]}),  # pre-0.4.1 shape
        json.dumps({"ts": "2026-10-28T11:00:00Z", "verdict": "deny",
                    "rules": {"delete-guard": "ask", "git-guard": "deny"}}),
        json.dumps({"ts": "2026-10-28T12:00:00Z", "verdict": "skipped",  # guard >= 0.5.1: a rule in rules_off
                    "rules": {"scratch-md": "skipped"}}),
    ]) + "\n")
    out = io.StringIO()
    assert ledger.cost_report(str(tdir), 7, out, now=now) == 0
    text = out.getvalue()
    assert "1 sessions in the last 7 days" in text
    assert "alpha" in text and "$0.50" in text and "n/a" in text and "$9.00" not in text
    assert "spawns: 2; sessions with subagent share > 70 %: abcdefgh" in text
    assert "hook prompts per rule (ask/deny): delete-guard 2/0, git-guard 0/1, scratch-md 0/0 skipped 1" in text
    out = io.StringIO()
    ledger.cost_report(str(tdir / "empty"), 7, out, now=now)
    assert "no sessions" in out.getvalue()


def test_prices_file_is_well_formed(ledger):
    prices = ledger.load_prices()
    assert "claude-opus-4-5" in prices
    for name, table in prices.items():
        assert table is None or set(table) == {"input", "output", "cache_read", "cache_write"}, name
