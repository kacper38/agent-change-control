"""The box probe's judges and plumbing, on recorded facts. Offline; nothing here starts a container."""
import io
import json
import sys

import pytest

USER_FACTS = {"uid": 1000, "euid": 1000, "dockerenv": True, "docker_sock": False, "cap_eff": "0000000000000000",
              "no_new_privs": "1", "iptables_as_user_exit": 4,
              "marker": {"exists": True, "uid": 0, "mode": "0o444", "writable": False, "dir_writable": False,
                         "schema": "agent-box/1"},
              "net": {"example.com": False, "api.anthropic.com": True, "github.com": True, "1.1.1.1:53": False}}


def facts(probe, value, exit_code=0, output=""):
    return probe.Facts(exit_code, value, output)


def session(probe, **over):
    base = {"uid": 1000, "exit": 0, "stderr_tail": "",
            "init": {"permission_mode": "bypassPermissions", "model": "claude-haiku-5-5", "mcp_servers": [],
                     "mcp_tools": []},
            "result": {"subtype": "success", "is_error": False, "total_cost_usd": 0.01, "num_turns": 4},
            "markers": ["allowed.marker"],
            "hook_rows": [{"role": "gate", "command": "touch allowed.marker", "verdict": None},
                          {"role": "gate", "command": "touch forbidden.marker", "verdict": "deny"},
                          {"role": "gate", "command": "touch asked.marker", "verdict": "ask"}],
            "hosts": [["api.anthropic.com", True]], "transcripts_in_config_dir": 1, "transcripts_in_home": 0}
    base.update(over)
    return facts(probe, base)


CLOSED = (70, None, "box: the firewall could not be set; no session starts")


def test_firewall_holds_on_the_recorded_box(probe):
    status, reason, observed = probe.j_firewall(facts(probe, USER_FACTS), probe.Facts(*CLOSED))
    assert (status, reason) == ("holds", "")
    assert observed["without_net_admin"] == {"exit": 70, "session_started": False}


@pytest.mark.parametrize("change, fragment", [
    ({"net": {"example.com": True, "api.anthropic.com": True, "github.com": True}}, "example.com is reachable"),
    ({"net": {"example.com": False, "api.anthropic.com": False, "github.com": True}}, "api.anthropic.com"),
    ({"cap_eff": "00000000a80425fb"}, "keeps capabilities"),
    ({"no_new_privs": "0"}, "no-new-privs"),
    ({"iptables_as_user_exit": 0}, "can read iptables"),
    ({"net": {**USER_FACTS["net"], "1.1.1.1:53": True}}, "port 53 off the resolver"),
])
def test_firewall_fails_on_each_gap(probe, change, fragment):
    status, reason, _ = probe.j_firewall(facts(probe, {**USER_FACTS, **change}), probe.Facts(*CLOSED))
    assert status == "fails" and fragment in reason


def test_firewall_fails_when_a_box_without_net_admin_starts(probe):
    status, reason, _ = probe.j_firewall(facts(probe, USER_FACTS), facts(probe, USER_FACTS))
    assert status == "fails" and "without NET_ADMIN" in reason


def test_firewall_is_inconclusive_without_facts(probe):
    assert probe.j_firewall(probe.Facts(1, None, "boom"), probe.Facts(*CLOSED))[0] == "inconclusive"


@pytest.mark.parametrize("change, fragment", [
    ({"writable": True}, "writable by the session's user"),
    ({"uid": 1000}, "not owned by root"),
    ({"exists": False}, "missing"),
    ({"dir_writable": True}, "folder is writable"),
])
def test_marker_fails_on_each_gap(probe, change, fragment):
    status, reason, _ = probe.j_marker(facts(probe, {**USER_FACTS, "marker": {**USER_FACTS["marker"], **change}}))
    assert status == "fails" and fragment in reason


def test_marker_fails_when_the_session_is_root(probe):
    status, reason, _ = probe.j_marker(facts(probe, {**USER_FACTS, "uid": 0}))
    assert status == "fails" and "runs as root" in reason


def test_dockerenv(probe):
    assert probe.j_dockerenv(facts(probe, USER_FACTS))[0] == "holds"
    assert probe.j_dockerenv(facts(probe, {**USER_FACTS, "dockerenv": False}))[0] == "fails"


ROOT_SAID = "--dangerously-skip-permissions cannot be used with root/sudo privileges for security reasons"


def test_flag_holds_when_root_is_refused_and_the_user_is_not(probe):
    user = facts(probe, {"uid": 1000, "exit": 1, "said": "Not logged in · Please run /login"})
    assert probe.j_flag(user, probe.Facts(1, None, ROOT_SAID))[0] == "holds"


def test_flag_fails_when_root_is_not_refused(probe):
    user = facts(probe, {"uid": 1000, "exit": 1, "said": "Not logged in"})
    status, reason, _ = probe.j_flag(user, probe.Facts(0, None, "ok"))
    assert status == "fails" and "root was not refused" in reason


def test_flag_fails_when_the_user_is_refused_as_root(probe):
    user = facts(probe, {"uid": 1000, "exit": 1, "said": ROOT_SAID})
    status, reason, _ = probe.j_flag(user, probe.Facts(1, None, ROOT_SAID))
    assert status == "fails" and "user run was refused" in reason


def test_session_questions_hold_on_a_clean_run(probe):
    run = {"gate": session(probe)}
    for name in ("headless-token", "hook-deny-checks-off", "hook-ask-checks-off", "cli-hosts", "connectors",
                 "config-dir"):
        status, reason, _ = probe.BY_NAME[name].judge(run)
        assert (name, status, reason) == (name, "holds", "")


def test_deny_fails_when_the_denied_command_ran(probe):
    status, reason, _ = probe.j_deny(session(probe, markers=["allowed.marker", "forbidden.marker"]))
    assert status == "fails" and "denied command ran" in reason


def test_deny_is_inconclusive_when_checks_off_was_not_shown_or_never_tried(probe):
    assert probe.j_deny(session(probe, markers=[]))[0] == "inconclusive"
    rows = [{"role": "gate", "command": "touch allowed.marker", "verdict": None}]
    assert probe.j_deny(session(probe, hook_rows=rows))[0] == "inconclusive"


def test_ask_fails_when_the_asked_command_ran_unanswered(probe):
    status, reason, _ = probe.j_ask(session(probe, markers=["allowed.marker", "asked.marker"]))
    assert status == "fails" and "1.0b" in reason


def test_a_run_with_an_error_result_is_never_a_hold(probe):
    bad = session(probe, result={"subtype": "error_during_execution", "is_error": True})
    for judge in (probe.j_headless, probe.j_deny, probe.j_ask, probe.j_hosts, probe.j_config_dir):
        assert judge(bad)[0] in ("fails", "inconclusive"), judge.__name__


def test_headless_fails_when_checks_were_not_off(probe):
    run = session(probe, init={"permission_mode": "default", "mcp_servers": [], "mcp_tools": []})
    status, reason, _ = probe.j_headless(run)
    assert status == "fails" and "default" in reason


def test_managed_hooks(probe):
    rows = [{"role": "managed", "command": "touch ran.marker"}]
    assert probe.j_managed(session(probe, markers=["ran.marker"], hook_rows=rows))[0] == "holds"
    status, reason, _ = probe.j_managed(session(probe, markers=["ran.marker"],
                                                hook_rows=rows + [{"role": "project", "command": "touch ran.marker"}]))
    assert status == "fails" and "allowManagedHooksOnly" in reason
    status, reason, _ = probe.j_managed(session(probe, markers=["ran.marker"], hook_rows=[]))
    assert status == "fails" and "did not fire" in reason


def test_hosts_off_the_list_fail(probe):
    status, reason, observed = probe.j_hosts(session(probe, hosts=[["api.anthropic.com", True],
                                                                   ["statsig.anthropic.com", False]]))
    assert status == "fails" and observed["outside_allowlist"] == ["statsig.anthropic.com"]


def test_connectors_fail_when_any_mcp_server_loads(probe):
    run = session(probe, init={"permission_mode": "bypassPermissions", "mcp_servers": ["claude.ai Gmail"],
                               "mcp_tools": ["mcp__claude_ai_Gmail__search_threads"]})
    status, reason, _ = probe.j_connectors(run)
    assert status == "fails" and "Gmail" in reason


def test_config_dir_fails_when_a_transcript_lands_in_home(probe):
    assert probe.j_config_dir(session(probe, transcripts_in_home=1))[0] == "fails"
    assert probe.j_config_dir(session(probe, transcripts_in_config_dir=0))[0] == "fails"


def test_every_question_has_its_runs(probe, tmp_path):
    specs = probe.run_specs("agent-box:abc", "haiku", str(tmp_path))
    for q in probe.QUESTIONS:
        assert set(q.runs) <= set(specs), q.name
        assert all(specs[r][1] == q.needs_token for r in q.runs), q.name


def test_the_token_is_passed_by_name_only(probe, tmp_path):
    for argv, needs_token in probe.run_specs("agent-box:abc", "haiku", str(tmp_path)).values():
        joined = " ".join(argv)
        assert ("-e CLAUDE_CODE_OAUTH_TOKEN " in joined + " ") == needs_token
        assert "CLAUDE_CODE_OAUTH_TOKEN=" not in joined
        assert "/var/run/docker.sock" not in joined and "type=bind,src=/Users," not in joined


def test_last_facts_reads_the_tagged_line(probe):
    out = "noise\nBOXPROBE {\"a\": 1}\nmore noise\n"
    assert probe.last_facts(out) == {"a": 1}
    assert probe.last_facts("BOXPROBE [1]\n") is None
    assert probe.last_facts("BOXPROBE {broken\n") is None
    assert probe.last_facts("nothing\n") is None


def test_parse_stream_keeps_init_and_result(probe):
    lines = [{"type": "system", "subtype": "init", "permissionMode": "bypassPermissions", "model": "m",
              "mcp_servers": [{"name": "x", "status": "connected"}], "tools": ["Bash", "mcp__x__y"]},
             {"type": "assistant"}, {"type": "result", "subtype": "success", "is_error": False,
                                     "total_cost_usd": 0.02, "num_turns": 3}]
    parsed = probe.parse_stream("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    assert parsed["init"] == {"permission_mode": "bypassPermissions", "model": "m", "mcp_servers": ["x"],
                              "mcp_tools": ["mcp__x__y"]}
    assert parsed["result"]["total_cost_usd"] == 0.02


def test_write_record_keeps_the_other_keys(probe, tmp_path):
    path = tmp_path / "verified.json"
    path.write_text(json.dumps({"schema": "orchestration-probe/1", "canaries": {"a": 1}}), encoding="utf-8")
    probe.write_record(str(path), {"schema": "box-probe/1"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"schema": "orchestration-probe/1", "canaries": {"a": 1}, "box": {"schema": "box-probe/1"}}


def run_hook(probe, monkeypatch, role, log, event):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = probe.hook_main(role, str(log))
    return code, out.getvalue()


EVENT = {"hook_event_name": "PreToolUse", "tool_name": "Bash"}


def test_gate_hook_denies_in_the_guards_shape(probe, monkeypatch, tmp_path):
    log = tmp_path / "hooks.jsonl"
    code, out = run_hook(probe, monkeypatch, "gate", log,
                         {**EVENT, "tool_input": {"command": "touch forbidden.marker"}})
    payload = json.loads(out)
    assert code == 2 and payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert json.loads(log.read_text(encoding="utf-8"))["verdict"] == "deny"


def test_gate_hook_asks_and_stays_silent_otherwise(probe, monkeypatch, tmp_path):
    log = tmp_path / "hooks.jsonl"
    code, out = run_hook(probe, monkeypatch, "gate", log, {**EVENT, "tool_input": {"command": "touch asked.marker"}})
    assert code == 0 and json.loads(out)["permissionDecision"] == "ask"
    code, out = run_hook(probe, monkeypatch, "gate", log, {**EVENT, "tool_input": {"command": "touch allowed.marker"}})
    assert (code, out) == (0, "")
    code, out = run_hook(probe, monkeypatch, "managed", log,
                         {**EVENT, "tool_input": {"command": "touch forbidden.marker"}})
    assert (code, out) == (0, "")  # only the gate role decides
    assert len(log.read_text(encoding="utf-8").splitlines()) == 3


def test_hook_fails_closed_on_unreadable_input(probe, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert probe.hook_main("gate", str(tmp_path / "hooks.jsonl")) == 2


def test_host_main_refuses_a_bad_model_name(probe):
    out = io.StringIO()
    assert probe.host_main(["--model", "haiku; rm"], out=out) == 2
    assert "not a model name" in out.getvalue()
