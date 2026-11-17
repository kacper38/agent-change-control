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
                                         "cache_write_1h": 0,  # no 5m/1h breakdown in these lines
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
    assert e["subagents"]["workflow_transcripts"] == 0
    assert e["spawns"] == [{"agent": "python-engineer", "model": "opus"}]


def test_build_entry_reads_workflow_agents_and_skips_the_journal(ledger, tmp_path, tdir):
    main = write_transcript(tmp_path, subagents=1)
    wf = main.parent / "s1" / "subagents" / "workflows" / "wf_abc"
    wf.mkdir(parents=True)
    (wf / "agent-def.jsonl").write_text(line("claude-opus-4-5", 7, 3, req="w1") + "\n")
    (wf / "journal.jsonl").write_text(line("claude-opus-4-5", 500000, 500000, req="j1") + "\n")  # never counted
    (wf / "agent-def.meta.json").write_text(json.dumps({"agentType": "workflow-subagent"}) + "\n")
    (wf / "agent-def.json").write_text("{}\n")
    raw = {"session_id": "s1", "transcript_path": str(main), "cwd": "/Users/t/x", "reason": "exit"}
    e = ledger.build_entry(raw, str(tdir), PRICES)
    opus = e["models"]["claude-opus-4-5"]
    assert opus["input"] == 1000 + 7 and opus["output"] == 2000 + 3 and opus["turns"] == 2
    assert e["subagents"]["transcripts"] == 2 and e["subagents"]["workflow_transcripts"] == 1
    assert e["subagents"]["tokens"] == 1000 + 2000 + 3000 + 400 + 7 + 3
    assert e["parse_errors"] == 2  # the main transcript's two, nothing from the journal or the meta files


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
    assert row["cost_check"] == "error" and row["cost_basis"] == "own"
    assert row["cost_usd_own"] is None and row["cost_usd_cc"] is None
    out = io.StringIO()
    ledger.cost_report(str(tdir), 7, out)
    basis_line = next(ln for ln in out.getvalue().splitlines() if ln.startswith("sessions by cost basis"))
    assert basis_line == "sessions by cost basis: own 1; marked 1 (error 1)", "a failed run is marked, not legacy"


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
    rates = {"input", "output", "cache_read", "cache_write", "cache_write_1h"}
    for name, table in prices.items():
        assert table is None or set(table) - {"long_prompt"} == rates, name
        if table and "long_prompt" in table:
            assert set(table["long_prompt"]) == rates | {"over_tokens"}, name
    assert set(prices["claude-haiku-5-5"]) == rates | {"long_prompt"}
    for model in ("claude-opus-5-5", "claude-sonnet-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1",
                  "claude-fable-5-2", "claude-haiku-4-5-20251001"):  # every model id seen in the last 30 days
        assert ledger.price_for(model, prices) is not None, model


def usage_line(model, inp, out, cr=0, cw=0, split=None, req=None):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
             "cache_creation_input_tokens": cw}
    if split is not None:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": split[0], "ephemeral_1h_input_tokens": split[1]}
    return json.dumps({"type": "assistant", "requestId": req, "message": {"model": model, "usage": usage}})


def priced_models(ledger, tmp_path, lines):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines) + "\n")
    prices = ledger.load_prices()
    usage, errors = ledger.parse_transcript(str(path), prices)
    return {m: (u, ledger.usage_cost(u, ledger.price_for(m, prices))) for m, u in usage.items()}, errors


def test_a_5m_1h_split_prices_each_part_at_its_rate(ledger, tmp_path):
    got, errors = priced_models(ledger, tmp_path, [usage_line("claude-opus-5-5", 10, 20, cr=1000, cw=3000,
                                                              split=(1000, 2000), req="r1")])
    u, cost = got["claude-opus-5-5"]
    assert errors == 0 and u["cache_write"] == 3000 and u["cache_write_1h"] == 2000
    assert cost == round((10 * 4 + 20 * 20 + 1000 * 0.2 + 1000 * 5 + 2000 * 8) / 1e6, 6)


def test_a_write_without_a_split_is_priced_at_the_5m_rate(ledger, tmp_path):
    got, _ = priced_models(ledger, tmp_path, [usage_line("claude-opus-5-5", 0, 0, cw=3000, req="r1")])
    u, cost = got["claude-opus-5-5"]
    assert u["cache_write_1h"] == 0 and cost == round(3000 * 5 / 1e6, 6)


def test_a_non_integer_split_makes_the_request_a_parse_error(ledger, tmp_path):
    got, errors = priced_models(ledger, tmp_path, [usage_line("claude-opus-5-5", 5, 5, cw=10, split=(0, "x"),
                                                              req="r1")])
    assert errors == 1 and got == {}


def test_haiku_5_5_pays_the_higher_row_per_request_over_100k(ledger, tmp_path):
    under = usage_line("claude-haiku-5-5", 1000, 100, cr=99000, cw=0, req="r1")  # prompt 100,000: not over
    over = usage_line("claude-haiku-5-5", 1000, 100, cr=99000, cw=1, split=(0, 1), req="r2")  # prompt 100,001
    got, _ = priced_models(ledger, tmp_path, [under])
    u, cost = got["claude-haiku-5-5"]
    assert "long" not in u and cost == round((1000 * 0.1 + 100 * 0.5 + 99000 * 0.01) / 1e6, 6)
    got, _ = priced_models(ledger, tmp_path, [under, over])
    u, cost = got["claude-haiku-5-5"]
    assert u["turns"] == 2 and u["long"]["turns"] == 1 and u["long"]["cache_write_1h"] == 1
    assert cost == round((1000 * 0.1 + 100 * 0.5 + 99000 * 0.01
                          + 1000 * 0.5 + 100 * 2.5 + 99000 * 0.05 + 1 * 1.0) / 1e6, 6)


def test_sonnet_5_5_has_its_own_row(ledger):
    prices = ledger.load_prices()
    assert ledger.price_for("claude-sonnet-5-5-20261101", prices) is prices["claude-sonnet-5-5"]
    assert ledger.price_for("claude-sonnet-5-20260801", prices) is prices["claude-sonnet-5"]
    assert prices["claude-sonnet-5-5"]["cache_read"] != prices["claude-sonnet-5"]["cache_read"]


def test_build_entry_prices_1h_writes_of_every_transcript(ledger, tmp_path, tdir):
    proj = tmp_path / "projects" / "-p"
    wf = proj / "s1" / "subagents" / "workflows" / "wf_1"
    wf.mkdir(parents=True)
    (proj / "s1.jsonl").write_text(usage_line("claude-opus-5-5", 0, 0, cw=1000, split=(0, 1000), req="m1") + "\n")
    (wf / "agent-a.jsonl").write_text(usage_line("claude-opus-5-5", 0, 0, cw=1000, split=(0, 1000), req="w1") + "\n")
    e = ledger.build_entry({"session_id": "s1", "transcript_path": str(proj / "s1.jsonl")}, str(tdir),
                           ledger.load_prices())
    assert e["models"]["claude-opus-5-5"]["cache_write_1h"] == 2000
    assert e["cost_usd"] == round(2000 * 8 / 1e6, 4)


def test_an_old_format_row_in_a_month_file_still_reports(ledger, tdir):
    tdir.mkdir()
    old = {"ts": "2026-10-28T10:00:00Z", "session": "old1", "project": "/Users/t/beta", "spawns": [],
           "subagents": {"transcripts": 0, "tokens": 0, "share": 0.0, "flag": False}, "cost_usd": 1.25,
           "parse_errors": 0,
           "models": {"claude-opus-4-5": {"input": 10, "output": 20, "cache_read": 0, "cache_write": 0, "turns": 1,
                                          "cost_usd": 1.25}}}
    (tdir / "sessions-2026-10.jsonl").write_text(json.dumps(old) + "\n")
    out = io.StringIO()
    assert ledger.cost_report(str(tdir), 7, out, now=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc)) == 0
    assert "beta" in out.getvalue() and "$1.25" in out.getvalue()
    assert ledger.usage_cost(old["models"]["claude-opus-4-5"], PRICES["claude-opus-4-5"]) == round(
        (10 * 5 + 20 * 25) / 1e6, 6)


def cost_state(usd, start="2026-11-15T10:00:00.000Z", unknown=False):
    return json.dumps({"type": "cost-state", "sessionId": "s1", "totalCostUSD": usd, "startTime": start,
                       "hasUnknownModelCost": unknown, "modelUsage": {}, "totalDuration": 1})


def cc_entry(ledger, tmp_path, tdir, states, own_tokens=1_000_000):
    """A session whose own count is own_tokens output tokens of claude-opus-4-5 ($25 per million) plus states."""
    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True, exist_ok=True)
    main = proj / "s1.jsonl"
    main.write_text("\n".join([line("claude-opus-4-5", 0, own_tokens, req="r1"), *states]) + "\n")
    return ledger.build_entry({"session_id": "s1", "transcript_path": str(main)}, str(tdir), PRICES)


def test_no_cost_state_line_uses_the_own_count_and_marks_it(ledger, tmp_path, tdir):
    e = cc_entry(ledger, tmp_path, tdir, [])
    assert e["cost_usd_own"] == 25.0 and e["cost_usd_cc"] is None
    assert (e["cost_usd"], e["cost_basis"], e["cost_check"]) == (25.0, "own", "missing")


def test_snapshots_with_one_start_time_count_the_last(ledger, tmp_path, tdir):
    e = cc_entry(ledger, tmp_path, tdir, [cost_state(5.0), cost_state(20.0), cost_state(30.0)])
    assert e["cost_usd_cc"] == 30.0 and e["cost_usd_own"] == 25.0
    assert (e["cost_usd"], e["cost_basis"], e["cost_check"]) == (30.0, "claude-code", "ok")


def test_two_start_times_are_summed(ledger, tmp_path, tdir):
    e = cc_entry(ledger, tmp_path, tdir, [cost_state(10.0, "t1"), cost_state(15.0, "t1"),
                                          cost_state(3.0, "t2"), cost_state(12.0, "t2")])
    assert e["cost_usd_cc"] == 27.0 and e["cost_basis"] == "claude-code" and e["cost_usd"] == 27.0


def test_a_carried_over_figure_far_above_the_own_count_is_not_used(ledger, tmp_path, tdir):
    e = cc_entry(ledger, tmp_path, tdir, [cost_state(62.68)], own_tokens=48_400)  # own $1.21
    assert e["cost_usd_own"] == 1.21 and e["cost_usd_cc"] == 62.68
    assert (e["cost_usd"], e["cost_basis"], e["cost_check"]) == (1.21, "own", "out-of-range")


def test_a_figure_1_percent_below_the_own_count_is_used(ledger, tmp_path, tdir):
    e = cc_entry(ledger, tmp_path, tdir, [cost_state(24.75)])
    assert (e["cost_usd"], e["cost_basis"], e["cost_check"]) == (24.75, "claude-code", "ok")
    e = cc_entry(ledger, tmp_path, tdir, [cost_state(24.0)])  # 4 % below: out of range
    assert (e["cost_usd"], e["cost_basis"], e["cost_check"]) == (25.0, "own", "out-of-range")
    e = cc_entry(ledger, tmp_path, tdir, [cost_state(37.5)])  # exactly 1.5 times: still in range
    assert e["cost_basis"] == "claude-code"


def test_unknown_model_cost_falls_back_to_the_own_count(ledger, tmp_path, tdir):
    e = cc_entry(ledger, tmp_path, tdir, [cost_state(30.0, unknown=True)])
    assert e["cost_usd_cc"] == 30.0
    assert (e["cost_usd"], e["cost_basis"], e["cost_check"]) == (25.0, "own", "unknown-model-cost")


def test_an_unpriced_own_count_leaves_claude_codes_figure_unchecked(ledger, tmp_path, tdir):
    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True)
    main = proj / "s1.jsonl"
    main.write_text("\n".join([line("claude-opus-4-5", 0, 10, req="r1"), line("claude-fable-5-1", 0, 10, req="r2"),
                               cost_state(2.0)]) + "\n")
    e = ledger.build_entry({"session_id": "s1", "transcript_path": str(main)}, str(tdir), PRICES)
    assert e["cost_usd_own"] is None, "one unpriced model: no partial sum"
    assert (e["cost_usd"], e["cost_basis"], e["cost_check"]) == (2.0, "claude-code", "unchecked")


def test_bad_cost_state_lines_are_ignored_and_counted(ledger, tmp_path, tdir):
    states = [cost_state(None), cost_state("12"), cost_state(True),
              json.dumps({"type": "cost-state", "startTime": "t"}), json.dumps({"type": "cost-state"})[:-1],
              cost_state(26.0)]
    e = cc_entry(ledger, tmp_path, tdir, states)
    assert e["cost_usd_cc"] == 26.0 and e["cost_check"] == "ok"
    assert e["parse_errors"] == 5  # four ignored lines and one that is not JSON


def test_hook_never_raises_on_an_odd_cost_state(ledger, tmp_path, tdir):
    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True)
    main = proj / "s1.jsonl"
    main.write_text(json.dumps({"type": "cost-state", "totalCostUSD": 1.0, "startTime": {"a": [1]}}) + "\n"
                    + json.dumps({"type": "cost-state", "totalCostUSD": float("inf")}) + "\n")
    err = io.StringIO()
    raw = json.dumps({"session_id": "s1", "transcript_path": str(main)})
    assert ledger.main(["hook"], stdin=io.StringIO(raw), out=io.StringIO(), err=err) == 0
    assert err.getvalue() == ""
    month = next(f for f in os.listdir(tdir) if f.startswith("sessions-"))
    row = json.loads((tdir / month).read_text().splitlines()[0])
    assert "error" not in row and row["cost_usd_cc"] == 1.0 and row["cost_check"] == "unchecked"
    assert row["parse_errors"] == 1


def test_cost_report_counts_sessions_by_basis_and_marks(ledger, tdir):
    tdir.mkdir()
    base = {"ts": "2026-10-28T10:00:00Z", "project": "/Users/t/alpha", "spawns": [], "subagents": {}, "models": {}}
    rows = [dict(base, session="a", cost_basis="claude-code", cost_check="ok"),
            dict(base, session="b", cost_basis="own", cost_check="missing"),
            dict(base, session="c", cost_basis="own", cost_check="out-of-range"),
            dict(base, session="d", cost_basis="claude-code", cost_check="unchecked"),
            dict(base, session="e")]  # written before the basis existed
    (tdir / "sessions-2026-10.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = io.StringIO()
    ledger.cost_report(str(tdir), 7, out, now=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc))
    assert ("sessions by cost basis: claude-code 2, own 2, unrecorded 1; marked 3 "
            "(missing 1, out-of-range 1, unchecked 1)") in out.getvalue()


def marked_line(req, **extra):
    """An opus-4-5 request whose usage carries extra fields such as speed and inference_geo."""
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             **extra}
    return json.dumps({"type": "assistant", "requestId": req, "message": {"model": "claude-opus-4-5", "usage": usage}})


def test_requests_outside_the_standard_speed_and_geo_are_marked(ledger, tmp_path, tdir):
    proj = tmp_path / "projects" / "-p"
    sub = proj / "s1" / "subagents" / "workflows" / "wf_1"
    sub.mkdir(parents=True)
    (proj / "s1.jsonl").write_text("\n".join([
        marked_line("r1", speed="fast"),
        marked_line("r1", speed="fast"),  # streamed duplicate: one request
        marked_line("r2", speed="fast", inference_geo="us"),
        marked_line("r3", speed="standard", inference_geo="global"),
        marked_line("r4", speed=None, inference_geo="not_available"),
        marked_line("r5", speed="", inference_geo=None),
        marked_line("r6"),
        marked_line("r7", speed=2),  # not a string: named by its type
        marked_line("r8", inference_geo="x" * 30),  # cut at 20 characters
    ]) + "\n")
    (sub / "agent-a.jsonl").write_text(marked_line("w1", speed="fast") + "\n")
    e = ledger.build_entry({"session_id": "s1", "transcript_path": str(proj / "s1.jsonl")}, str(tdir), PRICES)
    assert e["unpriced"] == {"speed:fast": 3, "inference_geo:us": 1, "speed:int": 1, "inference_geo:" + "x" * 20: 1}
    assert e["cost_usd_own"] == round(9 * 30 / 1e6, 4), "the pricing does not change"


def test_a_session_without_marked_requests_writes_the_same_line_as_before(ledger, tmp_path, tdir):
    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True)
    (proj / "s1.jsonl").write_text("\n".join([marked_line("r1", speed="standard", inference_geo="global"),
                                              marked_line("r2", speed=None, inference_geo="not_available"),
                                              marked_line("r3")]) + "\n")
    e = ledger.build_entry({"session_id": "s1", "transcript_path": str(proj / "s1.jsonl")}, str(tdir), PRICES)
    assert sorted(e) == ["cost_basis", "cost_check", "cost_usd", "cost_usd_cc", "cost_usd_own", "models",
                         "parse_errors", "project", "reason", "session", "spawns", "subagents", "ts"]


def test_cost_report_names_sessions_with_unpriced_requests(ledger, tdir):
    tdir.mkdir()
    base = {"ts": "2026-10-28T10:00:00Z", "project": "/p", "spawns": [], "subagents": {}, "models": {},
            "cost_basis": "own", "cost_check": "missing"}
    rows = [dict(base, session="a", unpriced={"speed:fast": 3}),
            dict(base, session="b", unpriced={"speed:fast": 1, "inference_geo:us": 2}),
            dict(base, session="c")]
    (tdir / "sessions-2026-10.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = io.StringIO()
    ledger.cost_report(str(tdir), 7, out, now=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc))
    assert ("sessions with requests the ledger does not price: 2 (inference_geo:us 2, speed:fast 4)"
            in out.getvalue().splitlines())
    (tdir / "sessions-2026-10.jsonl").write_text(json.dumps(dict(base, session="c")) + "\n")
    out = io.StringIO()
    ledger.cost_report(str(tdir), 7, out, now=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc))
    assert "does not price" not in out.getvalue()


def report_lines(ledger, tdir, rows):
    tdir.mkdir(exist_ok=True)
    (tdir / "sessions-2026-10.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = io.StringIO()
    ledger.cost_report(str(tdir), 7, out, now=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc))
    return out.getvalue().splitlines()


def test_cost_report_totals_the_session_costs_and_names_what_it_left_out(ledger, tdir):
    base = {"ts": "2026-10-28T10:00:00Z", "project": "/p", "spawns": [], "subagents": {},
            "models": {"claude-opus-4-5": {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0, "turns": 1,
                                           "cost_usd": 0.1}}}
    rows = [dict(base, session="a", cost_basis="claude-code", cost_usd=1000.005),
            dict(base, session="b", cost_basis="own", cost_usd=234.555),
            dict(base, session="c", cost_basis="own", cost_usd=None),
            dict(base, session="d", cost_basis="own", cost_usd="12"),
            dict(base, session="e", cost_basis="own", cost_usd=True),
            dict(base, session="f", cost_usd=None)]  # written before 2026-11-15: no basis
    lines = report_lines(ledger, tdir, rows)
    table_end = next(i for i, ln in enumerate(lines) if ln.startswith("sessions by cost basis"))
    assert lines[table_end - 1] == ("total session cost: $1,234.56 over 2 sessions; left out: 4 "
                                    "(unrecorded 1, no cost 3)"), "right after the table"
    assert lines[table_end - 2].startswith("p "), "the table rows stay where they were"


def test_cost_report_total_without_anything_left_out(ledger, tdir):
    base = {"ts": "2026-10-28T10:00:00Z", "project": "/p", "spawns": [], "subagents": {}, "models": {}}
    lines = report_lines(ledger, tdir, [dict(base, session="a", cost_basis="own", cost_usd=2.5),
                                        dict(base, session="b", cost_basis="own", cost_usd=0)])
    assert "total session cost: $2.50 over 2 sessions" in lines
    lines = report_lines(ledger, tdir, [dict(base, session="a", cost_basis="own", cost_usd=float("nan"))])
    assert "total session cost: $0.00 over 0 sessions; left out: 1 (unrecorded 0, no cost 1)" in lines


# --- recount ------------------------------------------------------------------------------------------------------

RECOUNT_AT = dt.datetime(2026, 11, 16, 8, 0, tzinfo=dt.timezone.utc)


def old_row(session, ts="2026-11-10T09:00:00Z", project="/Users/t/alpha"):
    """A line as the hook wrote it before 2026-11-15: no cost_basis, a null cost_usd."""
    return {"ts": ts, "session": session, "project": project, "reason": "exit", "spawns": [], "parse_errors": 0,
            "subagents": {"transcripts": 0, "tokens": 0, "share": 0.0, "flag": False}, "cost_usd": None,
            "models": {"claude-opus-4-5": {"input": 0, "output": 493600, "cache_read": 0, "cache_write": 0,
                                           "turns": 1, "cost_usd": None}}}


def config_transcript(tmp_path, session, project="-p"):
    """A transcript under <CLAUDE_CONFIG_DIR>/projects/<project>/: 493,600 output tokens of opus 4.5 = $12.34."""
    proj = tmp_path / "cfg" / "projects" / project
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{session}.jsonl"
    path.write_text(line("claude-opus-4-5", 0, 493600, req="r1") + "\n")
    return path


def recount_setup(tmp_path, tdir, monkeypatch):
    """Two month files: a recountable line, one without a transcript, a current line, garbage, and a file with
    nothing to do. Returns {file name: bytes before}."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    tdir.mkdir()
    config_transcript(tmp_path, "aaaaaaaa-1111")
    current = {"ts": "2026-11-15T10:00:00Z", "session": "cccccccc-3333", "project": "/Users/t/gamma",
               "cost_basis": "own", "cost_check": "missing", "cost_usd": 1.0, "models": {}}
    config_transcript(tmp_path, "cccccccc-3333")  # has a transcript, but a basis: not a candidate
    (tdir / "sessions-2026-11.jsonl").write_bytes(b"".join([
        json.dumps(old_row("aaaaaaaa-1111")).encode() + b"\n",
        json.dumps(current).encode() + b"\n",
        b"not json at all\n",  # UTF-8: load_sessions (cost_report, below) reads the files as strict UTF-8
        json.dumps(old_row("bbbbbbbb-2222", ts="2026-11-10T10:00:00Z", project="/Users/t/beta")).encode() + b"\n",
    ]))
    (tdir / "sessions-2026-10.jsonl").write_bytes(json.dumps(dict(current, ts="2026-10-20T10:00:00Z",
                                                                  session="dddd")).encode() + b"\n")
    return {p.name: p.read_bytes() for p in tdir.iterdir()}


def file_lines(data: bytes) -> list:
    """The lines of a month file split on b"\\n" only (splitlines() would also split on \\r and other breaks)."""
    assert data.endswith(b"\n")
    return data[:-1].split(b"\n")


def assert_untouched(after: bytes, untouched: list) -> None:
    """Each untouched line is in the file exactly once, byte for byte, and they keep their order."""
    lines = file_lines(after)
    for kept in untouched:
        assert lines.count(kept) == 1, kept
    assert [ln for ln in lines if ln in untouched] == untouched


def test_recount_dry_run_prints_what_it_would_do_and_writes_nothing(ledger, tmp_path, tdir, monkeypatch):
    before = recount_setup(tmp_path, tdir, monkeypatch)
    out = io.StringIO()
    assert ledger.recount(str(tdir), False, out, now=RECOUNT_AT) == 0
    assert out.getvalue().splitlines() == [
        "2026-11-10T09:00:00Z aaaaaaaa alpha null -> $12.34 (own, missing)",
        "2026-11-10T10:00:00Z bbbbbbbb beta no transcript",
        "recount: 1 recounted ($12.34), 1 without a transcript, 0 with an incomplete transcript, 0 errors, "
        "1 unparsable lines kept; dry run, nothing written (--write applies it)"]
    assert {p.name: p.read_bytes() for p in tdir.iterdir()} == before, "no lock file, no change"


def test_recount_write_rebuilds_labels_and_keeps_every_line(ledger, tmp_path, tdir, monkeypatch):
    before = recount_setup(tmp_path, tdir, monkeypatch)
    out = io.StringIO()
    assert ledger.recount(str(tdir), True, out, now=RECOUNT_AT) == 0
    assert out.getvalue().splitlines()[-1].endswith("; written")
    month = tdir / "sessions-2026-11.jsonl"
    data = month.read_bytes()
    assert data.count(b"\n") == before[month.name].count(b"\n")
    assert_untouched(data, file_lines(before[month.name])[1:3])  # the current line and the garbage
    assert (tdir / "sessions-2026-10.jsonl").read_bytes() == before["sessions-2026-10.jsonl"]
    rows = {r["session"]: r for r in (json.loads(b) for b in file_lines(data) if not b.startswith(b"not json"))}
    new = rows["aaaaaaaa-1111"]
    assert (new["ts"], new["project"], new["reason"]) == ("2026-11-10T09:00:00Z", "/Users/t/alpha", "exit")
    assert (new["cost_usd"], new["cost_basis"], new["cost_check"]) == (12.34, "own", "missing")
    old = old_row("aaaaaaaa-1111")
    assert new["recount"] == {"at": "2026-11-16T08:00:00Z", "was": {
        k: old[k] for k in ("cost_usd", "models", "parse_errors", "spawns", "subagents")}}
    assert rows["bbbbbbbb-2222"] == dict(old_row("bbbbbbbb-2222", ts="2026-11-10T10:00:00Z", project="/Users/t/beta"),
                                         recount={"at": "2026-11-16T08:00:00Z", "transcript": "missing"})
    assert not os.path.exists(str(month) + ".tmp")
    written = {p.name: p.read_bytes() for p in tdir.iterdir()}
    out = io.StringIO()
    assert ledger.recount(str(tdir), True, out, now=RECOUNT_AT) == 0, "a second run finds nothing"
    assert out.getvalue().splitlines() == ["recount: 0 recounted ($0.00), 0 without a transcript, "
                                           "0 with an incomplete transcript, 0 errors, "
                                           "1 unparsable lines kept; nothing to write"]
    assert {p.name: p.read_bytes() for p in tdir.iterdir()} == written
    out = io.StringIO()
    ledger.cost_report(str(tdir), 30, out, now=RECOUNT_AT)
    # the two current lines and the recounted one have a basis; the line without a transcript stays unrecorded
    assert "sessions by cost basis: own 3, unrecorded 1; marked 3 (missing 3)" in out.getvalue()


def test_recount_leaves_a_failing_line_untouched_and_exits_1(ledger, tmp_path, tdir, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    tdir.mkdir()
    for sid in ("badts", "dup", "elsewhere", "good"):
        config_transcript(tmp_path, sid)
    unreadable = tmp_path / "cfg" / "projects" / "-p" / "dirlike.jsonl"
    unreadable.mkdir()  # a directory where the transcript should be: open() fails
    config_transcript(tmp_path, "twice", "-p")
    config_transcript(tmp_path, "twice", "-q")  # two hits: not evidence
    # the two dup lines differ (reason), so neither is safe to replace
    bad = [dict(old_row("badts"), ts="yesterday"), old_row("dirlike"), old_row("dup"), dict(old_row("dup"), reason="x"),
           dict(old_row("elsewhere"), ts="2026-10-31T23:00:00Z"), old_row(""), old_row("../x")]
    month = tdir / "sessions-2026-11.jsonl"
    month.write_text("\n".join(json.dumps(r) for r in bad + [old_row("twice"), old_row("good")]) + "\n")
    before = month.read_bytes()
    out = io.StringIO()
    assert ledger.recount(str(tdir), True, out, now=RECOUNT_AT) == 1
    text = out.getvalue().splitlines()
    assert text[0].startswith("yesterday badts ") and " error: ValueError: " in text[0]
    assert " error: IsADirectoryError: " in text[1]
    # bad ts, unreadable, dup twice, wrong month file, no session id (append_entry could not replace it)
    assert sum(" error: " in ln for ln in text) == 6, text
    assert text[-1] == ("recount: 1 recounted ($12.34), 2 without a transcript, 0 with an incomplete transcript, "
                        "6 errors, 0 unparsable lines kept; written")
    after = month.read_bytes()
    assert after.count(b"\n") == before.count(b"\n")
    assert_untouched(after, file_lines(before)[:6])
    rows = [json.loads(b) for b in file_lines(after)]
    assert {r["session"]: r["recount"].get("transcript") for r in rows if "recount" in r} == {
        "../x": "missing", "twice": "missing", "good": None}


def test_recount_verb_runs_from_main_as_a_dry_run(ledger, tmp_path, tdir, monkeypatch):
    before = recount_setup(tmp_path, tdir, monkeypatch)
    out = io.StringIO()
    assert ledger.main(["recount"], out=out) == 0
    assert "dry run, nothing written" in out.getvalue()
    assert {p.name: p.read_bytes() for p in tdir.iterdir()} == before
    assert "ledger.py recount" in ledger.__doc__


def run_recount(ledger, tdir, write):
    """(exit code, output lines) of one recount run."""
    out = io.StringIO()
    code = ledger.recount(str(tdir), write, out, now=RECOUNT_AT)
    return code, out.getvalue().splitlines()


def month_setup(tmp_path, tdir, monkeypatch, rows):
    """sessions-2026-11.jsonl holding `rows` (dicts are dumped, bytes are kept) and the current line last."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    tdir.mkdir()
    current = {"ts": "2026-11-15T10:00:00Z", "session": "cccccccc-3333", "project": "/Users/t/gamma",
               "cost_basis": "own", "cost_check": "missing", "cost_usd": 1.0, "models": {}}
    month = tdir / "sessions-2026-11.jsonl"
    month.write_bytes(b"".join((r if isinstance(r, bytes) else json.dumps(r).encode()) + b"\n"
                               for r in rows + [current]))
    return month


def summary(recounted="0 recounted ($0.00)", missing=0, incomplete=0, errors=0, tail="written"):
    return (f"recount: {recounted}, {missing} without a transcript, {incomplete} with an incomplete transcript, "
            f"{errors} errors, 0 unparsable lines kept; {tail}")


DRY = "dry run, nothing written (--write applies it)"


def test_recount_rebuilds_an_identical_pair_once(ledger, tmp_path, tdir, monkeypatch):
    pair = json.dumps(old_row("eeeeeeee-5555")).encode()
    month = month_setup(tmp_path, tdir, monkeypatch, [pair, pair])
    config_transcript(tmp_path, "eeeeeeee-5555")
    before = month.read_bytes()
    assert run_recount(ledger, tdir, False) == (0, [
        "2026-11-10T09:00:00Z eeeeeeee alpha null -> $12.34 (own, missing) (2 identical lines become one)",
        summary("1 recounted ($12.34)", tail=DRY)])
    assert month.read_bytes() == before and not (tdir / ledger.LOCK_FILE).exists()
    code, text = run_recount(ledger, tdir, True)
    assert (code, text[-1]) == (0, summary("1 recounted ($12.34)"))
    after = month.read_bytes()
    assert after.count(b"\n") == before.count(b"\n") - 1, "the pair becomes one line, nothing else goes"
    assert_untouched(after, file_lines(before)[2:])
    rows = [json.loads(b) for b in file_lines(after)]
    new = [r for r in rows if r["session"] == "eeeeeeee-5555"]
    assert len(new) == 1 and new[0]["cost_usd"] == 12.34 and new[0]["recount"]["lines"] == 2
    written = month.read_bytes()
    assert run_recount(ledger, tdir, True) == (0, [summary(tail="nothing to write")]), "a second run finds nothing"
    assert month.read_bytes() == written


def test_recount_labels_an_identical_pair_without_a_transcript_once(ledger, tmp_path, tdir, monkeypatch):
    row = old_row("ffffffff-6666")
    pair = json.dumps(row).encode()
    month = month_setup(tmp_path, tdir, monkeypatch, [pair, pair])
    before = month.read_bytes()
    assert run_recount(ledger, tdir, False) == (0, [
        "2026-11-10T09:00:00Z ffffffff alpha no transcript (2 identical lines become one)",
        summary(missing=1, tail=DRY)])
    assert month.read_bytes() == before
    assert run_recount(ledger, tdir, True)[0] == 0
    after = month.read_bytes()
    assert after.count(b"\n") == before.count(b"\n") - 1
    assert_untouched(after, file_lines(before)[2:])
    rows = [json.loads(b) for b in file_lines(after) if b"ffffffff" in b]
    assert rows == [dict(row, recount={"at": "2026-11-16T08:00:00Z", "transcript": "missing", "lines": 2})]


def test_recount_names_each_line_of_a_differing_pair_and_touches_neither(ledger, tmp_path, tdir, monkeypatch):
    month = month_setup(tmp_path, tdir, monkeypatch, [old_row("dup"), dict(old_row("dup"), reason="clear")])
    config_transcript(tmp_path, "dup")
    before = month.read_bytes()
    for write in (False, True):
        code, text = run_recount(ledger, tdir, write)
        assert code == 1
        assert [ln.split(" error: ")[1] for ln in text[:-1]] == [
            "ValueError: 2 differing lines with this session id in sessions-2026-11.jsonl"] * 2
        assert text[-1] == summary(errors=2, tail=DRY if not write else "nothing to write")
        assert month.read_bytes() == before


def test_recount_labels_an_incomplete_transcript_and_keeps_the_old_line(ledger, tmp_path, tdir, monkeypatch):
    for kind, body, tokens in (("empty", "", 0),
                               ("garbage", "not json\n[1, 2]\n{\"type\": \"assistant\", \"message\": 3}\n", 0),
                               ("fewer", line("claude-opus-4-5", 0, 1000, req="r1") + "\n", 1000)):
        base = tmp_path / kind
        base.mkdir()
        tel = base / "telemetry"
        row = old_row("gggggggg-7777")
        month = month_setup(base, tel, monkeypatch, [row])
        path = config_transcript(base, "gggggggg-7777")
        path.write_text(body)
        before = month.read_bytes()
        assert run_recount(ledger, tel, False) == (0, [
            f"2026-11-10T09:00:00Z gggggggg alpha incomplete transcript (old 493600 tokens, transcript {tokens})",
            summary(incomplete=1, tail=DRY)]), kind
        assert month.read_bytes() == before, kind
        assert run_recount(ledger, tel, True) == (0, [
            f"2026-11-10T09:00:00Z gggggggg alpha incomplete transcript (old 493600 tokens, transcript {tokens})",
            summary(incomplete=1)]), kind
        after = month.read_bytes()
        assert after.count(b"\n") == before.count(b"\n")
        assert_untouched(after, file_lines(before)[1:])
        rows = [json.loads(b) for b in file_lines(after) if b"gggggggg" in b]
        assert rows == [dict(row, recount={"at": "2026-11-16T08:00:00Z", "transcript": "incomplete"})], kind


def test_recount_treats_malformed_old_models_as_zero_and_keeps_was_as_it_stood(ledger, tmp_path, tdir, monkeypatch):
    lean = {k: v for k, v in old_row("hhhhhhhh-8888").items() if k not in ("spawns", "subagents")}
    lean["models"] = "garbled"
    month = month_setup(tmp_path, tdir, monkeypatch, [lean])
    config_transcript(tmp_path, "hhhhhhhh-8888")
    code, text = run_recount(ledger, tdir, True)
    assert (code, text[0]) == (0, "2026-11-10T09:00:00Z hhhhhhhh alpha null -> $12.34 (own, missing)")
    new = [json.loads(b) for b in file_lines(month.read_bytes()) if b"hhhhhhhh" in b][0]
    assert new["recount"]["was"] == {"cost_usd": None, "models": "garbled", "parse_errors": 0}, \
        "a key the old line did not have is left out"


def test_recount_names_a_line_whose_session_id_is_not_a_string(ledger, tmp_path, tdir, monkeypatch):
    month = month_setup(tmp_path, tdir, monkeypatch, [dict(old_row("x"), session=["a"])])
    before = month.read_bytes()
    code, text = run_recount(ledger, tdir, True)
    assert code == 1 and text[0].endswith(" error: ValueError: no session id, so the line cannot be replaced")
    assert month.read_bytes() == before
