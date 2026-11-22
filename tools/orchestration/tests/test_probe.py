"""The canary probe without a model: judges from hand-built evidence, the hook recorder, the scratch builder,
and main() against a fake `claude` binary."""
import argparse
import datetime as _dt
import io
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile

import pytest

PROBE = str(pathlib.Path(__file__).resolve().parents[1] / "probe.py")
RECORD = pathlib.Path(__file__).resolve().parents[1] / "verified.json"
WA = "workflow-subagent"
RAN, ALLOWED, FORBIDDEN = "touch ran.marker", "touch allowed.marker", "touch forbidden.marker"
ABS = "/private/tmp/scratch/"  # custom subagents were seen rewriting the touch with the absolute scratch path
DEPTH, BG = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
SUCCESS = {"type": "result", "subtype": "success", "is_error": False, "session_id": "s1"}
NAMES = ["workflow-by-name", "denial-exits-zero", "hook-blocks-workflow-agent", "hook-blocks-nested-subagent",
         "depth-pin", "spawn-log-workflow-agents", "workflow-background-off", "ledger-own-cost", "mcp-hook",
         "tool-list", "hook-failure-blocks", "workflow-agents-total"]


def pre(tool, agent_type=None, command=None, subagent_type=None, blocked=False, env=None):
    return {"event": "PreToolUse", "tool": tool, "agent_type": agent_type, "command": command,
            "subagent_type": subagent_type, "blocked": blocked, "env": env or {}}


def start(agent_type, env=None):
    return {"event": "SubagentStart", "tool": None, "agent_type": agent_type, "env": env or {}}


def ev(exit_code=0, result=None, error=None, rows=(), markers=(), spawns=(), **result_fields):
    res = dict(SUCCESS, **result_fields) if result is None else result
    return {"exit_code": exit_code, "result": res, "error": error, "hook_rows": list(rows),
            "markers": frozenset(markers), "spawn_rows": list(spawns)}


RAN_ROWS = [pre("Workflow"), start(WA), pre("Bash", WA, RAN)]
BG_ROWS = [dict(r, env={BG: "1"}) for r in RAN_ROWS]
DENIED = [{"tool_name": "Workflow", "tool_input": {}}]
SKILL_DENIED = [{"tool_name": "Skill", "tool_input": {"skill": "kit-probe-hook"}}]
WA_BLOCK = [start(WA), pre("Bash", WA, ALLOWED), pre("Bash", WA, FORBIDDEN, blocked=True)]
INNER_BLOCK = [pre("Agent", None, subagent_type="probe-outer"), start("probe-outer"),
               pre("Agent", "probe-outer", subagent_type="probe-inner"), start("probe-inner"),
               pre("Bash", "probe-inner", ALLOWED), pre("Bash", "probe-inner", FORBIDDEN, blocked=True)]
CHAIN = [start("probe-l1"), start("probe-l2"), start("probe-l3")]
BOTH = ["allowed.marker"]
RAN_ROWS_ABS = [pre("Workflow"), start(WA), pre("Bash", WA, "touch " + ABS + "ran.marker")]
MCP_BOTH = [pre("mcp__github__get_me"), pre("mcp__github__merge_pull_request", blocked=True)]


def mcp_ev(rows=(), calls=(), **kw):
    return dict(ev(rows=rows, **kw), server_rows=tuple({"tool": c} for c in calls))


def sp(total, session="s1"):
    return {"event": "SubagentStart", "session": session, "agent": WA, "tool": None, "total": total}


INNER_BLOCK_ABS = INNER_BLOCK[:4] + [pre("Bash", "probe-inner", "touch " + ABS + "allowed.marker"),
                                     pre("Bash", "probe-inner", "touch " + ABS + "forbidden.marker", blocked=True)]

# (case id, canary, {run key: evidence kwargs}, status, reason fragment)
CASES = [
    ("wf-1-unclean-is-error", "workflow-by-name", {"run": ev(is_error=True, subtype="error_max_budget_usd")},
     "inconclusive", "error_max_budget_usd"),
    ("wf-1-unclean-runner-error", "workflow-by-name", {"run": ev(exit_code=None, result={}, error="timed out")},
     "inconclusive", "timed out"),
    ("wf-1-unclean-exit-code", "workflow-by-name", {"run": ev(exit_code=1)}, "inconclusive", "exit code 1"),
    ("wf-2-env-not-visible", "workflow-background-off", {"run": ev(rows=RAN_ROWS, markers=["ran.marker"])},
     "inconclusive", "was not visible"),
    ("wf-3-denied", "workflow-by-name", {"run": ev(permission_denials=DENIED)}, "fails", "denied"),
    ("wf-4-holds", "workflow-by-name", {"run": ev(rows=RAN_ROWS, markers=["ran.marker"])}, "holds", ""),
    ("wf-4-holds-with-env", "workflow-background-off", {"run": ev(rows=BG_ROWS, markers=["ran.marker"])},
     "holds", ""),
    ("wf-4-holds-absolute-path", "workflow-by-name", {"run": ev(rows=RAN_ROWS_ABS, markers=["ran.marker"])},
     "holds", ""),
    ("wf-1-skill-denied-no-rows", "workflow-by-name", {"run": ev(permission_denials=SKILL_DENIED)},
     "inconclusive", "did not call"),
    ("wf-5-marker-only", "workflow-by-name", {"run": ev(markers=["ran.marker"])}, "inconclusive", "no workflow agent"),
    ("wf-6-called-none-started", "workflow-by-name", {"run": ev(rows=[pre("Workflow")])}, "fails", "no workflow agent"),
    ("wf-7-started-no-command", "workflow-by-name", {"run": ev(rows=[pre("Workflow"), start(WA)])},
     "inconclusive", "did not run"),
    ("wf-8-clean-empty", "workflow-by-name", {"run": ev()}, "inconclusive", "did not call"),
    ("wf-8-clean-empty-bg", "workflow-background-off", {"run": ev()}, "inconclusive", "was not visible"),
    ("deny-1-broken", "denial-exits-zero", {"run": ev(rows=[{"error": "unreadable hook input: x"}])},
     "inconclusive", "hook recorder error"),
    ("deny-2-agent-started", "denial-exits-zero", {"run": ev(rows=[start(WA)], permission_denials=DENIED)},
     "fails", "without the allow rule"),
    ("deny-3-no-denial", "denial-exits-zero", {"run": ev()}, "inconclusive", "no Workflow denial"),
    ("deny-4-holds", "denial-exits-zero", {"run": ev(permission_denials=DENIED)}, "holds", ""),
    ("deny-5-exit-code", "denial-exits-zero", {"run": ev(exit_code=1, permission_denials=DENIED)},
     "fails", "exit status"),
    ("deny-5-is-error", "denial-exits-zero", {"run": ev(is_error=True, permission_denials=DENIED)},
     "fails", "exit status"),
    ("block-1-broken", "hook-blocks-workflow-agent", {"run": ev(result="x")},
     "inconclusive", "no JSON result"),
    ("block-2-forbidden-no-rows", "hook-blocks-workflow-agent", {"run": ev(markers=["forbidden.marker"])},
     "fails", "forbidden command ran"),
    ("block-2-forbidden-nested", "hook-blocks-nested-subagent", {"run": ev(markers=["forbidden.marker"])},
     "fails", "forbidden command ran"),
    ("block-3-unclean", "hook-blocks-workflow-agent", {"run": ev(exit_code=1, rows=WA_BLOCK, markers=BOTH)},
     "inconclusive", "exit code 1"),
    ("block-4-clean-empty", "hook-blocks-workflow-agent", {"run": ev()}, "inconclusive", "no workflow-subagent agent"),
    ("block-4-clean-empty-nested", "hook-blocks-nested-subagent", {"run": ev()}, "inconclusive", "no probe-inner"),
    ("block-4-skill-denied-no-rows", "hook-blocks-workflow-agent", {"run": ev(permission_denials=SKILL_DENIED)},
     "inconclusive", "no workflow-subagent agent"),
    ("block-5-no-control", "hook-blocks-workflow-agent", {"run": ev(rows=WA_BLOCK)}, "inconclusive", "control"),
    ("block-6-not-from-parent", "hook-blocks-nested-subagent",
     {"run": ev(rows=[r for r in INNER_BLOCK if r.get("agent_type") != "probe-outer"], markers=BOTH)},
     "inconclusive", "started from inside probe-outer"),
    ("block-7-holds", "hook-blocks-workflow-agent", {"run": ev(rows=WA_BLOCK, markers=BOTH)}, "holds", ""),
    ("block-7-holds-nested", "hook-blocks-nested-subagent", {"run": ev(rows=INNER_BLOCK, markers=BOTH)}, "holds", ""),
    ("block-7-holds-nested-absolute-path", "hook-blocks-nested-subagent",
     {"run": ev(rows=INNER_BLOCK_ABS, markers=BOTH)}, "holds", ""),
    ("depth-1-control-unclean", "depth-pin", {"control": ev(exit_code=None, result={}, error="timed out after 1 s"),
                                              "pinned": ev(rows=CHAIN[:2])}, "inconclusive", "control run: timed out"),
    ("depth-1-pinned-unclean", "depth-pin", {"control": ev(rows=CHAIN), "pinned": ev(exit_code=4)},
     "inconclusive", "pinned run: exit code 4"),
    ("depth-2-clean-empty", "depth-pin", {"control": ev(), "pinned": ev()}, "inconclusive", "did not reach layer 3"),
    ("depth-3-layer-3-under-pin", "depth-pin", {"control": ev(rows=CHAIN), "pinned": ev(rows=CHAIN)},
     "fails", "layer 3 started"),
    ("depth-4-holds", "depth-pin", {"control": ev(rows=CHAIN), "pinned": ev(rows=CHAIN[:2])}, "holds", ""),
    ("depth-5-requested-not-started", "depth-pin",
     {"control": ev(rows=CHAIN), "pinned": ev(rows=[start("probe-l1"), pre("Agent", "probe-l1", None, "probe-l2")])},
     "fails", "layer 2 was requested"),
    ("depth-6-never-requested", "depth-pin", {"control": ev(rows=CHAIN), "pinned": ev(rows=CHAIN[:1])},
     "inconclusive", "never requested"),
    ("spawn-1-unclean", "spawn-log-workflow-agents", {"run": ev(exit_code=2)}, "inconclusive", "exit code 2"),
    ("spawn-2-holds", "spawn-log-workflow-agents",
     {"run": ev(spawns=[{"event": "SubagentStart", "agent": WA, "session": "s1"}])}, "holds", ""),
    ("spawn-3-ran-not-logged", "spawn-log-workflow-agents", {"run": ev(rows=RAN_ROWS, markers=["ran.marker"])},
     "fails", "no workflow-subagent row"),
    ("spawn-1-corrupt-spawn-row", "spawn-log-workflow-agents",
     {"run": ev(rows=RAN_ROWS, markers=["ran.marker"], spawns=[{"error": "unparseable row"}])},
     "inconclusive", "spawn log error"),
    ("spawn-4-clean-empty", "spawn-log-workflow-agents", {"run": ev()}, "inconclusive", "nothing to see"),
    ("ledger-1-unclean", "ledger-own-cost", {"run": ev(exit_code=1)}, "inconclusive", "exit code 1"),
    ("ledger-2-no-cost-field", "ledger-own-cost", {"run": ev()}, "inconclusive", "no total_cost_usd"),
    ("ledger-3-no-transcript", "ledger-own-cost", {"run": ev(total_cost_usd=0.01)}, "inconclusive",
     "transcript was not found"),
    ("ledger-3-transcript-gone", "ledger-own-cost",
     {"run": dict(ev(total_cost_usd=0.01), transcript="/nonexistent/s1.jsonl")}, "inconclusive",
     "transcript was not found"),
    # the lookup itself is tested in test_find_transcript_refuses_a_session_id_in_two_project_folders
    ("ledger-3-no-transcript-reason-names-both-causes", "ledger-own-cost", {"run": ev(total_cost_usd=0.01)},
     "inconclusive", "more than one file carries its session id"),
    # item #65, D11: is the hook called for a tool of an MCP server named github, and does its exit 2 block it
    ("mcp-1-holds", "mcp-hook", {"run": mcp_ev(MCP_BOTH, ["get_me"])}, "holds", ""),
    ("mcp-2-a-call-without-a-hook-row-fails", "mcp-hook", {"run": mcp_ev((), ["get_me", "merge_pull_request"])},
     "fails", "get_me, merge_pull_request and the hook has no row"),
    ("mcp-3-one-row-missing-fails", "mcp-hook", {"run": mcp_ev(MCP_BOTH[:1], ["get_me", "merge_pull_request"])},
     "fails", "merge_pull_request and the hook has no row"),
    ("mcp-4-no-call-is-inconclusive", "mcp-hook", {"run": mcp_ev()}, "inconclusive", "did not call both tools"),
    ("mcp-5-block-ignored-fails", "mcp-hook", {"run": mcp_ev(MCP_BOTH, ["get_me", "merge_pull_request"])},
     "fails", "reached the server all the same"),
    ("mcp-5-unblocked-merge-reached", "mcp-hook",
     {"run": mcp_ev(MCP_BOTH[:1] + [pre("mcp__github__merge_pull_request")], ["get_me", "merge_pull_request"])},
     "inconclusive", "the hook did not block it"),
    ("mcp-5-stopped-but-not-by-the-hook", "mcp-hook",
     {"run": mcp_ev(MCP_BOTH[:1] + [pre("mcp__github__merge_pull_request")], ["get_me"])},
     "inconclusive", "not because the hook blocked it"),
    ("mcp-6-allowed-call-missing", "mcp-hook", {"run": mcp_ev(MCP_BOTH)}, "inconclusive", "did not reach the server"),
    ("mcp-7-runner-error", "mcp-hook", {"run": mcp_ev(MCP_BOTH, ["get_me"], error="timed out after 300 s")},
     "inconclusive", "timed out"),
    ("mcp-8-a-blocked-run-may-end-unclean", "mcp-hook",
     {"run": mcp_ev(MCP_BOTH, ["get_me"], exit_code=1, is_error=True)}, "holds", ""),
    # the tool list of the init message against KNOWN_CLAUDE_TOOLS (the hold and the added name: tests below)
    ("tools-1-no-init", "tool-list", {"run": ev()}, "inconclusive", "no init message"),
    ("tools-2-removed", "tool-list", {"run": dict(ev(), init={"type": "system", "subtype": "init", "tools": ["Bash"]})},
     "fails", "added none; removed CronCreate"),
    ("tools-3-runner-error", "tool-list", {"run": ev(error="timed out after 300 s")}, "inconclusive", "timed out"),
    ("tools-4-not-a-list", "tool-list", {"run": dict(ev(), init={"tools": "Bash"})}, "inconclusive", "no init"),
    # item #67, D2 (a): a failed pre hook fails open without onFailure, and blocks with onFailure block
    ("fail-1-holds", "hook-failure-blocks", {"open-timeout": ev(rows=[pre("Bash", None, RAN)], markers=["ran.marker"]),
                                             "block-timeout": ev(rows=[pre("Bash", None, RAN)]),
                                             "block-exit1": ev(rows=[pre("Bash", None, RAN)])}, "holds", ""),
    ("fail-2-block-timeout-ran", "hook-failure-blocks",
     {"open-timeout": ev(rows=[pre("Bash", None, RAN)], markers=["ran.marker"]),
      "block-timeout": ev(rows=[pre("Bash", None, RAN)], markers=["ran.marker"]),
      "block-exit1": ev(rows=[pre("Bash", None, RAN)])}, "fails", "the block-timeout run"),
    ("fail-3-block-exit1-ran", "hook-failure-blocks",
     {"open-timeout": ev(rows=[pre("Bash", None, RAN)], markers=["ran.marker"]),
      "block-timeout": ev(rows=[pre("Bash", None, RAN)]),
      "block-exit1": ev(rows=[pre("Bash", None, RAN)], markers=["ran.marker"])}, "fails", "the block-exit1 run"),
    ("fail-4-control-did-not-run", "hook-failure-blocks",
     {"open-timeout": ev(rows=[pre("Bash", None, RAN)]), "block-timeout": ev(rows=[pre("Bash", None, RAN)]),
      "block-exit1": ev(rows=[pre("Bash", None, RAN)])}, "inconclusive", "the control"),
    ("fail-5-no-hook-row", "hook-failure-blocks",
     {"open-timeout": ev(rows=[pre("Bash", None, RAN)], markers=["ran.marker"]), "block-timeout": ev(),
      "block-exit1": ev(rows=[pre("Bash", None, RAN)])}, "inconclusive", "block-timeout run has no hook row"),
    ("fail-6-unclean", "hook-failure-blocks",
     {"open-timeout": ev(rows=[pre("Bash", None, RAN)], markers=["ran.marker"]),
      "block-timeout": ev(exit_code=1, rows=[pre("Bash", None, RAN)]),
      "block-exit1": ev(rows=[pre("Bash", None, RAN)])}, "inconclusive", "block-timeout run: exit code 1"),
    ("fail-7-runner-error", "hook-failure-blocks",
     {"open-timeout": ev(error="timed out after 300 s"), "block-timeout": ev(), "block-exit1": ev()},
     "inconclusive", "open-timeout run: timed out"),
    # item #67, D2 (b): six workflow agents, the sixth SubagentStart row carries the session total 6
    ("total-1-holds", "workflow-agents-total", {"run": ev(spawns=[sp(n) for n in range(1, 7)])}, "holds", ""),
    ("total-2-wrong-total", "workflow-agents-total",
     {"run": ev(spawns=[sp(n) for n in range(1, 6)] + [sp(5)])}, "fails", "total 5, not 6"),
    ("total-3-no-total", "workflow-agents-total",
     {"run": ev(spawns=[sp(n) for n in range(1, 6)] + [sp(None)])}, "fails", "total None"),
    ("total-4-five-rows", "workflow-agents-total", {"run": ev(spawns=[sp(n) for n in range(1, 6)])},
     "inconclusive", "5 SubagentStart rows"),
    ("total-5-other-session", "workflow-agents-total",
     {"run": ev(spawns=[sp(n, session="s2") for n in range(1, 7)])}, "inconclusive", "0 SubagentStart rows"),
    ("total-6-unclean", "workflow-agents-total",
     {"run": ev(is_error=True, subtype="error_max_budget_usd", spawns=[sp(n) for n in range(1, 7)])},
     "inconclusive", "error_max_budget_usd"),
]


def plain(value):
    return value is None or isinstance(value, (int, bool, str)) or (
        isinstance(value, list) and all(isinstance(v, str) for v in value))


@pytest.mark.parametrize("name,runs,status,fragment", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_judge_tables(probe, name, runs, status, fragment):
    evidence = {key: probe.Evidence(**kw) for key, kw in runs.items()}
    got_status, reason, observed = probe.CANARY_BY_NAME[name].judge(evidence)
    assert got_status == status, reason
    assert (reason == "") if status == "holds" else (fragment in reason)
    assert all(plain(v) for v in observed.values()), observed


def test_every_judge_reports_the_same_keys_for_any_evidence(probe):
    keys = {}
    for _, name, runs, _, _ in CASES:
        observed = probe.CANARY_BY_NAME[name].judge({k: probe.Evidence(**kw) for k, kw in runs.items()})[2]
        keys.setdefault(name, set(observed))
        assert set(observed) == keys[name]
    assert set(keys) == set(NAMES)


@pytest.mark.parametrize("command,name", [
    ("touch allowed.marker", "allowed.marker"),
    ("touch /x/y/allowed.marker", "allowed.marker"),
    ("touch a && echo b", None),
    ("touch -c a", None),
    ("echo a", None),
    (None, None),
    (["touch", "a"], None),
    ("touch 'allowed.marker", None),
], ids=["relative", "absolute", "chained", "flag", "other-command", "none", "non-string", "unbalanced-quote"])
def test_touched_reads_the_file_name(probe, command, name):
    assert probe.touched(command) == name


# --- the hook recorder -------------------------------------------------------------------------------------------

def hook(tmp_path, payload, *args, env=None, log=None):
    log = log or tmp_path / "hook.jsonl"
    base = {k: v for k, v in os.environ.items() if k not in (DEPTH, BG)}
    data = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run([sys.executable, "-I", PROBE, "hook", str(log), *args], input=data, capture_output=True,
                       text=True, env=dict(base, **(env or {})))
    assert r.stdout == ""
    rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return r, rows


def bash(command, agent_type=None):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s1", "agent_id": "a1",
            "agent_type": agent_type, "tool_input": {"command": command}}


def test_hook_allowed_command_passes_in_block_mode(tmp_path):
    r, rows = hook(tmp_path, bash(" touch allowed.marker\n", WA), "--only-allow", "allowed.marker")
    assert r.returncode == 0 and r.stderr == ""
    assert rows == [{"event": "PreToolUse", "tool": "Bash", "agent_id": "a1", "agent_type": WA, "session_id": "s1",
                     "command": " touch allowed.marker\n", "subagent_type": None, "workflow": None,
                     "blocked": False, "env": {}}]


def test_hook_other_bash_command_is_blocked_in_block_mode(tmp_path):
    r, rows = hook(tmp_path, bash(FORBIDDEN, WA), "--only-allow", "allowed.marker")
    assert r.returncode == 2
    assert "probe hook: blocked by the canary rule" in r.stderr
    assert rows[0]["blocked"] is True and rows[0]["command"] == FORBIDDEN


@pytest.mark.parametrize("command,code", [
    ("touch " + ABS + "allowed.marker", 0),
    ("touch " + ABS + "forbidden.marker", 2),
    ("touch allowed.marker && echo x", 2),
], ids=["absolute-allowed", "absolute-forbidden", "chained-allowed"])
def test_hook_block_mode_judges_the_touched_file_name(tmp_path, command, code):
    r, rows = hook(tmp_path, bash(command, "probe-inner"), "--only-allow", "allowed.marker")
    assert r.returncode == code
    assert rows[0]["blocked"] is (code == 2) and rows[0]["command"] == command


def test_hook_agent_call_passes_in_block_mode(tmp_path):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {"subagent_type": "probe-l2"}}
    r, rows = hook(tmp_path, payload, "--only-allow", "allowed.marker")
    assert r.returncode == 0
    assert rows[0]["subagent_type"] == "probe-l2" and rows[0]["blocked"] is False and rows[0]["session_id"] is None


def test_hook_record_mode_never_blocks(tmp_path):
    workflow = {"hook_event_name": "PreToolUse", "tool_name": "Workflow", "tool_input": {"name": "kit-probe-run"}}
    for payload in (bash(FORBIDDEN), workflow, {"hook_event_name": "SubagentStart", "agent_type": WA}):
        assert hook(tmp_path, payload)[0].returncode == 0
    rows = hook(tmp_path, {"hook_event_name": "PreToolUse", "tool_input": "not a dict"})[1]
    assert [r["blocked"] for r in rows] == [False] * 4
    assert rows[1]["workflow"] == "kit-probe-run" and rows[2]["agent_type"] == WA and rows[3]["command"] is None


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", ""])
def test_hook_unreadable_input_fails_closed(tmp_path, stdin):
    r, rows = hook(tmp_path, stdin)
    assert r.returncode == 2
    assert "unreadable hook input" in r.stderr
    assert len(rows) == 1 and rows[0]["error"].startswith("unreadable hook input: ")


def test_hook_unwritable_log_fails_closed(tmp_path):
    log = tmp_path / "missing-dir" / "hook.jsonl"
    r, _ = hook(tmp_path, bash(ALLOWED), log=log)
    assert r.returncode == 2
    assert f"probe hook: cannot write {log}" in r.stderr


def test_hook_records_the_variables_under_test(tmp_path):
    _, rows = hook(tmp_path, bash(ALLOWED), env={DEPTH: "2", BG: "1", "OTHER": "x"})
    assert rows[0]["env"] == {DEPTH: "2", BG: "1"}


# --- the scratch builder -----------------------------------------------------------------------------------------

ALLOW_WF = ["Skill(kit-probe-run)", "Workflow(kit-probe-run)", "Bash(touch ran.marker)", "Bash(touch */ran.marker)"]
ALLOW_RAN = ["Bash(touch ran.marker)", "Bash(touch */ran.marker)"]
ALLOW_TWO = ["Bash(touch allowed.marker)", "Bash(touch */allowed.marker)", "Bash(touch forbidden.marker)",
             "Bash(touch */forbidden.marker)"]
TABLE = {  # (canary, run key): (prompt start, allow rules, workflows, agents, block mode, env, fan-out hook)
    ("workflow-by-name", "run"): ("/kit-probe-run", ALLOW_WF, ["kit-probe-run"], [], False, {}, False),
    ("denial-exits-zero", "run"): ("/kit-probe-run", ["Skill(kit-probe-run)"], ["kit-probe-run"], [], False, {}, False),
    ("hook-blocks-workflow-agent", "run"): (
        "/kit-probe-hook", ["Skill(kit-probe-hook)", "Workflow(kit-probe-hook)", *ALLOW_TWO],
        ["kit-probe-hook"], [], True, {}, False),
    ("hook-blocks-nested-subagent", "run"): (
        "Use the Agent tool", ["Agent", *ALLOW_TWO], [],
        ["probe-outer", "probe-inner"], True, {DEPTH: "2"}, False),
    ("depth-pin", "control"): ("Use the Agent tool", ["Agent"], [], ["probe-l1", "probe-l2", "probe-l3"], False,
                               {DEPTH: "3"}, False),
    ("depth-pin", "pinned"): ("Use the Agent tool", ["Agent"], [], ["probe-l1", "probe-l2", "probe-l3"], False,
                              {DEPTH: "2"}, False),
    ("spawn-log-workflow-agents", "run"): ("/kit-probe-run", ALLOW_WF, ["kit-probe-run"], [], False, {}, True),
    ("workflow-background-off", "run"): ("/kit-probe-run", ALLOW_WF, ["kit-probe-run"], [], False, {BG: "1"}, False),
    ("hook-failure-blocks", "open-timeout"): ("Run this Bash command", ALLOW_RAN, [], [], False, {}, False),
    ("hook-failure-blocks", "block-timeout"): ("Run this Bash command", ALLOW_RAN, [], [], False, {}, False),
    ("hook-failure-blocks", "block-exit1"): ("Run this Bash command", ALLOW_RAN, [], [], False, {}, False),
    ("workflow-agents-total", "run"): ("/kit-probe-six", ["Skill(kit-probe-six)", "Workflow(kit-probe-six)"],
                                       ["kit-probe-six"], [], False, {}, True),
}
# item #67, D2: the recorder hook entry of each run (timeout, onFailure, extra arguments); every other run keeps
# the entry it had, byte for byte
HOOK_ENTRY = {
    ("hook-failure-blocks", "open-timeout"): (2, None, " --sleep 8"),
    ("hook-failure-blocks", "block-timeout"): (2, "block", " --sleep 8"),
    ("hook-failure-blocks", "block-exit1"): (10, "block", " --exit-code 1"),
}


def _init(tools):
    return {"type": "system", "subtype": "init", "tools": tools}


def test_tool_list_holds_on_the_known_names_and_leaves_mcp_tools_out(probe):
    known = sorted(probe.load_guard().KNOWN_CLAUDE_TOOLS)
    status, reason, observed = probe.CANARY_BY_NAME["tool-list"].judge(
        {"run": probe.Evidence(**dict(ev(is_error=True), init=_init(known + ["mcp__github__get_me"])))})
    assert (status, reason) == ("holds", "") and observed["tools"] == known and observed["added"] == []


def test_tool_list_fails_naming_an_added_tool(probe):
    known = sorted(probe.load_guard().KNOWN_CLAUDE_TOOLS)
    status, reason, observed = probe.CANARY_BY_NAME["tool-list"].judge(
        {"run": probe.Evidence(**dict(ev(), init=_init(known + ["NewTool"])))})
    assert status == "fails" and "added NewTool; removed none" in reason
    assert observed["added"] == ["NewTool"] and observed["removed"] == []


def test_stream_messages_keep_the_first_init_and_the_last_result(probe):
    lines = [json.dumps(_init(["Bash"])), "not json", json.dumps([1]), json.dumps(_init(["Read"])),
             json.dumps(dict(SUCCESS, n=1)), json.dumps(dict(SUCCESS, n=2))]
    result, init = probe.stream_messages("\n".join(lines))
    assert init["tools"] == ["Bash"] and result["n"] == 2
    assert probe.stream_messages("") == (None, None)


def test_hook_blocks_the_named_tool(tmp_path):
    call = {"hook_event_name": "PreToolUse", "tool_name": "mcp__github__merge_pull_request", "tool_input": {}}
    r, rows = hook(tmp_path, call, "--block-tool", "mcp__github__merge_pull_request")
    assert r.returncode == 2 and rows[-1]["blocked"] is True
    r, rows = hook(tmp_path, dict(call, tool_name="mcp__github__get_me"), "--block-tool",
                   "mcp__github__merge_pull_request")
    assert r.returncode == 0 and rows[-1]["blocked"] is False and rows[-1]["tool"] == "mcp__github__get_me"


def test_the_mcp_server_lists_its_tools_and_logs_each_call(tmp_path):
    log = tmp_path / "mcp.jsonl"
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_me", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "no/such"}]
    r = subprocess.run([sys.executable, "-I", PROBE, "mcp-server", str(log)], capture_output=True, text=True,
                       input="\n".join(json.dumps(m) for m in msgs) + "\nnot json\n", timeout=30)
    replies = [json.loads(line) for line in r.stdout.splitlines()]
    assert r.returncode == 0 and [m["id"] for m in replies] == [1, 2, 3, 4]
    assert replies[0]["result"]["serverInfo"]["name"] == "kit-probe-github"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == ["get_me", "merge_pull_request"]
    assert replies[2]["result"]["content"][0]["text"] == "ok" and replies[3]["error"]["code"] == -32601
    assert [json.loads(line)["tool"] for line in log.read_text().splitlines()] == ["get_me"]


def test_the_mcp_run_registers_the_server_and_matches_its_tools(probe, tmp_path):
    run = probe.CANARY_BY_NAME["mcp-hook"].runs[0]
    probe.build_scratch(str(tmp_path), run, "haiku")
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    (group,) = settings["hooks"]["PreToolUse"]
    assert group["matcher"] == "mcp__github__.*"
    assert group["hooks"][0]["command"].endswith(" --block-tool mcp__github__merge_pull_request")
    server = json.loads((tmp_path / "mcp.json").read_text())["mcpServers"]["github"]
    assert server["command"] == sys.executable and server["args"][:3] == ["-I", PROBE, "mcp-server"]
    argv = probe.run_argv(run, "haiku", "claude")
    assert argv[argv.index("--allowedTools") + 1:][:2] == ["mcp__github__get_me", "mcp__github__merge_pull_request"]
    assert argv[-5:] == ["--mcp-config", "mcp.json", "--strict-mcp-config", "--output-format", "json"]


def test_the_tool_list_run_keeps_the_init_message(probe):
    argv = probe.run_argv(probe.CANARY_BY_NAME["tool-list"].runs[0], "haiku", "claude")
    assert argv[-4:] == ["--strict-mcp-config", "--output-format", "stream-json", "--verbose"]
    assert "--mcp-config" not in argv and "--allowedTools" not in argv


def test_every_workflow_run_allows_both_routes(probe):
    runs = [(c.name, r) for c in probe.CANARIES for r in c.runs if r.workflows]
    assert runs
    for name, run in runs:
        for wf in run.workflows:
            assert f"Skill({wf})" in run.allowed, name
            assert (f"Workflow({wf})" in run.allowed) is (name != "denial-exits-zero"), name


def test_skill_denial_shows_in_the_block_observation(probe):
    status, _, observed = probe.CANARY_BY_NAME["hook-blocks-workflow-agent"].judge(
        {"run": probe.Evidence(**ev(permission_denials=SKILL_DENIED))})
    assert status == "inconclusive" and observed["denied_tools"] == ["Skill"]


def test_canary_names_and_runs_match_the_table(probe):
    assert [c.name for c in probe.CANARIES] == NAMES
    # the runs of mcp-hook and tool-list have their own argv and settings tests (item #65); every other run is here
    special = [(c.name, r.key) for c in probe.CANARIES for r in c.runs if r.mcp or r.stream]
    assert {name for name, _ in special} == {"mcp-hook", "tool-list"}, special
    assert [(c.name, r.key) for c in probe.CANARIES for r in c.runs if not (r.mcp or r.stream)] == list(TABLE)
    assert all(c.expect and c.backs for c in probe.CANARIES)


@pytest.mark.parametrize("name,key", list(TABLE), ids=[f"{n}-{k}" for n, k in TABLE])
def test_scratch_project_for_every_run(probe, tmp_path, name, key):
    prompt, allow, workflows, agents, block, env, fanout = TABLE[(name, key)]
    run = next(r for r in probe.CANARY_BY_NAME[name].runs if r.key == key)
    scratch = tmp_path / "s"
    scratch.mkdir()
    probe.build_scratch(str(scratch), run, "sonnet")
    settings = json.loads((scratch / ".claude" / "settings.json").read_text())
    (pre_group,) = settings["hooks"]["PreToolUse"]
    assert pre_group["matcher"] == "Bash|Agent|Workflow"
    pre_cmd = pre_group["hooks"][0]["command"]
    timeout, on_failure, extra = HOOK_ENTRY.get((name, key), (10, None, ""))
    want = {"type": "command", "command": pre_cmd, "timeout": timeout}
    if on_failure:
        want["onFailure"] = on_failure
    assert pre_group["hooks"][0] == want
    assert pre_cmd.endswith(extra) and (bool(extra) or not re.search(r" --(sleep|exit-code)\b", pre_cmd))
    start_cmds = [h["command"] for h in settings["hooks"]["SubagentStart"][0]["hooks"]]
    for cmd in (pre_cmd, start_cmds[0]):
        assert cmd.startswith(f"{sys.executable} -I ") and cmd.split()[3:5] == ["hook", str(scratch / "hook.jsonl")]
    assert pre_cmd.endswith(" --only-allow allowed.marker") is block
    assert "--only-allow" not in start_cmds[0]
    assert settings.get("env", {}) == env
    assert len(start_cmds) == (2 if fanout else 1)
    if fanout:
        assert start_cmds[1].startswith(f"KZ_TELEMETRY_DIR={scratch / 'telemetry'} ")
        assert start_cmds[1].endswith("guard.py hook fan-out --wrapper claude")
    for wf in workflows:
        text = (scratch / ".claude" / "workflows" / f"{wf}.js").read_text()
        assert text.startswith("export const meta = {\n") and f"name: '{wf}'," in text and "model: 'sonnet'" in text
    found = sorted(p.stem for p in (scratch / ".claude").glob("agents/*.md"))
    assert found == sorted(agents)
    for agent in agents:
        text = (scratch / ".claude" / "agents" / f"{agent}.md").read_text()
        assert f"\nname: {agent}\n" in text and "\nmodel: sonnet\n" in text
    argv = probe.run_argv(run, "sonnet", "claude")
    assert argv[:3] == ["claude", "-p", argv[2]] and argv[2].startswith(prompt)
    assert argv[3:11] == ["--model", "sonnet", "--permission-mode", "dontAsk", "--setting-sources", "project",
                          "--max-budget-usd", str(probe.BUDGET_USD)]
    assert argv[-2:] == ["--output-format", "json"]
    assert argv[11:-2] == (["--allowedTools", *allow] if allow else [])


# --- main() against a fake claude --------------------------------------------------------------------------------

RESULT = dict(SUCCESS, result="done", total_cost_usd=0.01, modelUsage={"claude-fake-1": {}})


def fake_claude(tmp_path, body):
    script = tmp_path / "fake-claude"
    script.write_text(f"#!{sys.executable}\nimport json, os, sys, time\n"
                      "if sys.argv[1:] == ['--version']:\n    print('9.9.9 (Claude Code)')\n    sys.exit(0)\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def run_main(probe, tmp_path, bin_path, *extra):
    out, record, workdir = io.StringIO(), tmp_path / "verified.json", tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    code = probe.main(["--claude-bin", bin_path, "--out", str(record), "--workdir", str(workdir), *extra], out=out)
    return code, out.getvalue(), record


def test_success_that_does_nothing_holds_nothing(probe, tmp_path):
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, f"print(json.dumps({RESULT!r}))\n"))
    assert code == 1
    data = json.loads(record.read_text())
    assert list(data) == ["schema", "cli_version", "date", "model", "models", "cost_usd", "canaries"]
    assert data["schema"] == "orchestration-probe/1" and data["cli_version"] == "9.9.9" and data["model"] == "haiku"
    assert data["models"] == ["claude-fake-1"] and data["cost_usd"] == 0.14
    assert list(data["canaries"]) == NAMES
    assert [c["status"] for c in data["canaries"].values()] == ["inconclusive"] * 12
    assert data["canaries"]["depth-pin"]["cost_usd"] == 0.02
    assert list(data["canaries"]["workflow-by-name"]) == ["status", "reason", "expect", "backs", "observed",
                                                          "cost_usd"]
    assert text.splitlines()[0] == "inconclusive  workflow-by-name              $0.0100"
    assert data["canaries"]["ledger-own-cost"]["cost_usd"] == 0.0, "a reused run is paid for once"
    assert text.splitlines()[-1] == f"probe: CLI 9.9.9, 0 of 12 canaries hold, $0.1400; wrote {record}"
    assert not record.with_name("verified.json.tmp").exists()


def test_denied_tools_are_named_in_every_reason_that_can_see_them(probe, tmp_path):
    denials = [{"tool_name": "Skill", "tool_input": {}}, {"tool_name": "Workflow", "tool_input": {}}]
    result = dict(RESULT, permission_denials=denials)
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, f"print(json.dumps({result!r}))\n"))
    assert code == 1
    canaries = json.loads(record.read_text())["canaries"]
    assert canaries["denial-exits-zero"]["status"] == "holds" and canaries["denial-exits-zero"]["reason"] == ""
    lines = text.splitlines()
    for name, entry in canaries.items():
        if entry["status"] == "holds":
            continue
        reason_line = lines[lines.index(next(x for x in lines if x.split()[1:2] == [name])) + 1].strip()
        assert reason_line == entry["reason"]
        if "denied_tools" in entry["observed"]:
            assert entry["reason"].endswith("; denied tools: Skill, Workflow"), name
        else:  # depth-pin and spawn-log judges do not observe denials (no judge logic changes in this step)
            assert "denied tools" not in entry["reason"], name


def test_only_runs_one_canary_and_writes_nothing(probe, tmp_path):
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, f"print(json.dumps({RESULT!r}))\n"),
                                  "--only", "workflow-by-name")
    assert code == 1 and not record.exists()
    lines = text.splitlines()
    assert len(lines) == 3 and lines[0].split()[1] == "workflow-by-name"
    assert lines[-1].endswith("0 of 1 canaries hold, $0.0100; not written (--only)")


def test_garbage_output_is_inconclusive_everywhere(probe, tmp_path):
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, "print('oops')\nsys.exit(3)\n"))
    assert code == 1
    canaries = json.loads(record.read_text())["canaries"].values()
    assert all(c["status"] == "inconclusive" and "no JSON result" in c["reason"] for c in canaries)
    assert all(c["cost_usd"] is None for c in canaries)
    assert "no JSON result (exit 3): oops" in text and "$n/a" not in text and " n/a" in text


def test_hung_cli_times_out(probe, tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "TIMEOUT_S", 1)
    code, text, _ = run_main(probe, tmp_path, fake_claude(tmp_path, "time.sleep(10)\n"), "--only", "denial-exits-zero")
    assert code == 1
    assert text.splitlines()[1].strip() == "timed out after 1 s"


def test_the_written_record_holds_no_local_path(probe, tmp_path):
    body = "print(os.path.expanduser('~') + ' ' + os.getcwd())\nsys.exit(3)\n"  # lands in every reason
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, body))
    workdir, home = os.path.realpath(str(tmp_path / "work")), os.path.expanduser("~")
    assert code == 1 and workdir + "/" in text and home in text, "the terminal keeps the real paths"
    written = record.read_text()
    for local in (workdir, str(tmp_path), os.path.realpath(str(tmp_path)), home):
        assert local not in written, local
    reason = json.loads(written)["canaries"]["workflow-by-name"]["reason"]
    assert reason == "no JSON result (exit 3): ~ <workdir>/workflow-by-name-run"


def test_scrub_replaces_the_longest_path_first_at_any_depth(probe):
    tmp, home = tempfile.gettempdir(), os.path.expanduser("~")
    workdir = os.path.join(tmp, "w")
    real_tmp = os.path.realpath(tmp)
    record = {"a": [f"{workdir}/x {tmp}/y", {"b": f"{real_tmp}/z {home}/q {os.path.realpath(workdir)}"}], "n": 3}
    assert probe.scrub(record, probe.local_paths(workdir)) == {
        "a": ["<workdir>/x <tmp>/y", {"b": "<tmp>/z ~/q <workdir>"}], "n": 3}


def test_the_committed_record_holds_no_local_path():
    text = RECORD.read_text()
    for local in ("/Users/", "/home/", "/private/", "/var/folders/", "/tmp/"):
        assert local not in text, local


def test_missing_cli_exits_2(probe, tmp_path):
    missing = str(tmp_path / "no-such-claude")
    code, text, record = run_main(probe, tmp_path, missing)
    assert code == 2 and not record.exists()
    assert text.startswith(f"probe: no usable CLI at {missing}: ")


def test_workdir_collision_exits_2(probe, tmp_path):
    (tmp_path / "work" / "depth-pin-pinned").mkdir(parents=True)
    called = tmp_path / "called"
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, f"open({str(called)!r}, 'w').close()\n"))
    assert code == 2 and not record.exists() and not called.exists()
    assert "depth-pin-pinned" in text


def test_workdir_collision_on_a_reused_run_exits_2(probe, tmp_path):
    (tmp_path / "work" / "workflow-by-name-run").mkdir(parents=True)
    called = tmp_path / "called"
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, f"open({str(called)!r}, 'w').close()\n"),
                                  "--only", "ledger-own-cost")
    assert code == 2 and not record.exists() and not called.exists()
    assert "workflow-by-name-run" in text


def test_relative_workdir_still_gives_the_hooks_absolute_paths(probe, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    binary = fake_claude(tmp_path, f"print(json.dumps({RESULT!r}))\n")
    probe.main(["--claude-bin", binary, "--workdir", "rel", "--only", "workflow-by-name"], out=io.StringIO())
    scratch = tmp_path.resolve() / "rel" / "workflow-by-name-run"
    settings = json.loads((scratch / ".claude" / "settings.json").read_text())
    assert str(scratch / "hook.jsonl") in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_unwritable_scratch_project_is_inconclusive_and_never_starts_claude(probe, tmp_path, monkeypatch):
    def disk_full(*args):
        raise OSError("disk full")

    monkeypatch.setattr(probe, "build_scratch", disk_full)
    called = tmp_path / "called"
    code, text, _ = run_main(probe, tmp_path, fake_claude(tmp_path, f"open({str(called)!r}, 'w').close()\n"),
                             "--only", "workflow-by-name")
    assert code == 1 and not called.exists()
    assert text.splitlines()[0].startswith("inconclusive")
    assert text.splitlines()[1].strip() == "scratch project could not be written: disk full"


def test_invalid_utf8_in_the_output_still_parses(probe, tmp_path):
    payload = json.dumps(dict(RESULT, result="RESULT_TEXT")).encode().replace(b"RESULT_TEXT", b"d\xffone")
    body = f"sys.stdout.buffer.write({payload!r})\n"
    code, text, _ = run_main(probe, tmp_path, fake_claude(tmp_path, body), "--only", "workflow-by-name")
    assert code == 1
    assert "no JSON result" not in text and "the model did not call the Workflow tool" in text


@pytest.mark.parametrize("name", ["claude-haiku-5-5", "us.anthropic.claude-haiku-5-5-v1:0", "haiku"])
def test_model_names_are_accepted(probe, name):
    assert probe.model_name(name) == name


def test_model_with_quote_and_space_is_rejected_before_any_run(probe, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    with pytest.raises(SystemExit) as exc:
        probe.main(["--model", "x' y", "--claude-bin", str(tmp_path / "none"), "--workdir", str(workdir),
                    "--out", str(tmp_path / "verified.json")], out=io.StringIO())
    assert exc.value.code == 2
    assert list(workdir.iterdir()) == [] and not (tmp_path / "verified.json").exists()
    with pytest.raises(argparse.ArgumentTypeError, match="not a model name"):
        probe.model_name("a\nb")


def test_child_environment_drops_the_caller_variables(probe, tmp_path, monkeypatch):
    dump = tmp_path / "env.json"
    for var in ("KZ_EGRESS_OFF", DEPTH, BG):
        monkeypatch.setenv(var, "1")
    monkeypatch.setenv("PROBE_TEST_KEEP", "yes")
    body = f"json.dump(dict(os.environ), open({str(dump)!r}, 'w'))\nprint(json.dumps({RESULT!r}))\n"
    run_main(probe, tmp_path, fake_claude(tmp_path, body), "--only", "workflow-by-name")
    env = json.loads(dump.read_text())
    assert env["PROBE_TEST_KEEP"] == "yes"
    assert not [k for k in env if k.startswith("KZ_") or k in (DEPTH, BG)]


# --- the committed record ----------------------------------------------------------------------------------------

def test_committed_record_matches_the_canary_list(probe):
    data = json.loads(RECORD.read_text())
    assert data["schema"] == "orchestration-probe/1"
    assert re.fullmatch(r"\d+\.\d+\.\d+", data["cli_version"])
    _dt.date.fromisoformat(data["date"])
    assert list(data["canaries"]) == [c.name for c in probe.CANARIES]
    assert all(c["status"] in ("holds", "fails", "inconclusive") for c in data["canaries"].values())


# --- the ledger cost canary --------------------------------------------------------------------------------------

def haiku_line(req, inp=10_000, out=1_000):  # claude-haiku-5-5 at $0.10 / $0.50 per million: $0.0015 a line
    return json.dumps({"type": "assistant", "requestId": req,
                       "message": {"model": "claude-haiku-5-5", "usage": {"input_tokens": inp, "output_tokens": out,
                                                                          "cache_read_input_tokens": 0,
                                                                          "cache_creation_input_tokens": 0}}})


def probe_session(config_dir, session="s1", main_lines=None, workflow_lines=None):
    """A synthetic probe session under <config_dir>/projects/: main transcript, one workflow agent, a journal."""
    proj = config_dir / "projects" / "-private-tmp-scratch-workflow-by-name-run"
    proj.mkdir(parents=True, exist_ok=True)
    main = proj / f"{session}.jsonl"
    main.write_text("\n".join(main_lines if main_lines is not None else [haiku_line("m1")]) + "\n")
    wf = proj / session / "subagents" / "workflows" / "wf_1"
    wf.mkdir(parents=True, exist_ok=True)
    if workflow_lines is not False:
        (wf / "agent-a.jsonl").write_text("\n".join(workflow_lines or [haiku_line("w1")]) + "\n")
    (wf / "journal.jsonl").write_text(haiku_line("j1", 10 ** 9, 10 ** 9) + "\n")  # no usage counted from it
    return main


@pytest.mark.parametrize("run_usd,status,fragment", [
    (0.003, "holds", ""),
    (0.00303, "holds", ""),       # 1 % above the own count
    (0.00295, "holds", ""),       # the own count is about 1.7 % above the run's figure
    (0.0031, "fails", "by 3.2%"),
    (0.0025, "fails", "more than 2%"),
    (0.0, "inconclusive", "no cost"),
    (0.003 / 1.02, "holds", ""),  # the own count exactly 2 % above the run's figure
    (0.003 / 0.98, "holds", ""),  # the own count exactly 2 % below the run's figure
    (0.003 / 1.021, "fails", "by 2.1%"),
    (0.003 / 0.979, "fails", "by 2.1%"),
], ids=["equal", "1-percent", "2-percent", "3-percent", "20-percent", "zero", "exactly-2-percent-above",
        "exactly-2-percent-below", "2.1-percent-above", "2.1-percent-below"])
def test_ledger_judge_compares_the_own_count_with_the_run(probe, tmp_path, run_usd, status, fragment):
    main = probe_session(tmp_path)
    got, reason, observed = probe.judge_ledger_cost(probe.Evidence(**dict(ev(total_cost_usd=run_usd),
                                                                         transcript=str(main))))
    assert got == status, reason
    assert (reason == "") if status == "holds" else (fragment in reason)
    assert observed["own_micro_usd"] == 3000 and observed["workflow_transcripts"] == 1
    assert observed["agent_transcripts"] == 1 and observed["parse_errors"] == 0
    assert all(plain(v) for v in observed.values()), observed


def test_ledger_judge_needs_a_workflow_agent_a_price_and_clean_transcripts(probe, tmp_path):
    def judge(main):
        return probe.judge_ledger_cost(probe.Evidence(**dict(ev(total_cost_usd=0.003), transcript=str(main))))

    assert judge(probe_session(tmp_path / "a", workflow_lines=False))[1].startswith("no workflow-agent transcript")
    unpriced = json.dumps({"type": "assistant", "requestId": "u1",
                           "message": {"model": "claude-unknown-9", "usage": {"input_tokens": 5, "output_tokens": 5}}})
    status, reason, _ = judge(probe_session(tmp_path / "b", main_lines=[haiku_line("m1"), unpriced]))
    assert status == "inconclusive" and "no price" in reason
    status, reason, observed = judge(probe_session(tmp_path / "c", main_lines=[haiku_line("m1"), "not json"]))
    assert status == "inconclusive" and "parse errors" in reason and observed["parse_errors"] == 1


def test_ledger_judge_without_the_ledger_is_inconclusive(probe, tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "LEDGER", str(tmp_path / "missing" / "ledger.py"))
    status, reason, _ = probe.judge_ledger_cost(probe.Evidence(**dict(ev(total_cost_usd=0.003),
                                                                     transcript=str(probe_session(tmp_path)))))
    assert status == "inconclusive" and reason.startswith("the ledger could not be loaded")


@pytest.mark.parametrize("run_usd", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "minus-inf"])
def test_ledger_judge_with_a_non_finite_cost_is_inconclusive(probe, tmp_path, run_usd):
    status, reason, observed = probe.judge_ledger_cost(probe.Evidence(**dict(ev(total_cost_usd=run_usd),
                                                                             transcript=str(probe_session(tmp_path)))))
    assert status == "inconclusive" and "no total_cost_usd" in reason
    assert observed["run_micro_usd"] is None


def test_ledger_judge_with_a_broken_ledger_file_is_inconclusive(probe, tmp_path, monkeypatch):
    broken_ledger = tmp_path / "ledger.py"
    broken_ledger.write_text("def broken(:\n")
    monkeypatch.setattr(probe, "LEDGER", str(broken_ledger))
    status, reason, _ = probe.judge_ledger_cost(probe.Evidence(**dict(ev(total_cost_usd=0.003),
                                                                     transcript=str(probe_session(tmp_path)))))
    assert status == "inconclusive" and reason.startswith("the ledger could not be loaded")
    assert "SyntaxError" in reason


def test_ledger_judge_whose_count_raises_is_inconclusive(probe, tmp_path, monkeypatch):
    def read_session(*_args):
        raise KeyError("cache_write_1h")

    stub = type("StubLedger", (), {"load_prices": staticmethod(lambda: {}),
                                   "read_session": staticmethod(read_session)})
    monkeypatch.setattr(probe, "load_ledger", lambda: stub)
    status, reason, _ = probe.judge_ledger_cost(probe.Evidence(**dict(ev(total_cost_usd=0.003),
                                                                     transcript=str(probe_session(tmp_path)))))
    assert status == "inconclusive" and "KeyError" in reason


@pytest.mark.parametrize("own", [float("nan"), float("inf")], ids=["nan", "inf"])
def test_ledger_judge_with_a_non_finite_own_count_is_inconclusive(probe, tmp_path, monkeypatch, own):
    read = {"errors": 0, "transcripts": 1, "workflow_transcripts": 1}
    stub = type("StubLedger", (), {"load_prices": staticmethod(lambda: {}),
                                   "read_session": staticmethod(lambda *_args: read),
                                   "session_models": staticmethod(lambda *_args: {}),
                                   "own_cost": staticmethod(lambda _models: own)})
    monkeypatch.setattr(probe, "load_ledger", lambda: stub)
    status, reason, observed = probe.judge_ledger_cost(probe.Evidence(**dict(ev(total_cost_usd=0.003),
                                                                             transcript=str(probe_session(tmp_path)))))
    assert status == "inconclusive" and "not a finite number" in reason
    assert observed["own_micro_usd"] is None and observed["diff_bp"] is None


@pytest.mark.parametrize("session_id", [None, 7, "../x", "a b", "*"])
def test_find_transcript_takes_only_a_plain_session_id(probe, tmp_path, monkeypatch, session_id):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    probe_session(tmp_path, session="x")
    assert probe.find_transcript(session_id) is None


def test_find_transcript_refuses_a_session_id_in_two_project_folders(probe, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    probe_session(tmp_path, session="dup")
    other = tmp_path / "projects" / "-another-project"
    other.mkdir(parents=True)
    (other / "dup.jsonl").write_text(haiku_line("o1") + "\n")
    assert probe.find_transcript("dup") is None


def test_only_the_ledger_canary_runs_its_source_run_and_finds_the_transcript(probe, tmp_path, monkeypatch):
    config = tmp_path / "config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    main = probe_session(config, session="run-1")
    assert probe.find_transcript("run-1") == str(main)
    result = dict(RESULT, session_id="run-1", total_cost_usd=0.003)
    code, text, record = run_main(probe, tmp_path, fake_claude(tmp_path, f"print(json.dumps({result!r}))\n"),
                                  "--only", "ledger-own-cost")
    assert code == 0 and not record.exists()
    assert (tmp_path / "work" / "workflow-by-name-run").is_dir()
    lines = text.splitlines()
    assert lines[0] == "holds         ledger-own-cost               $0.0030"
    assert lines[-1].endswith("1 of 1 canaries hold, $0.0030; not written (--only)")


def test_keep_box_key(probe, tmp_path):
    import json
    path = tmp_path / "verified.json"
    assert probe.keep_box_key(str(path)) == {}
    path.write_text(json.dumps({"canaries": {}}), encoding="utf-8")
    assert probe.keep_box_key(str(path)) == {}
    path.write_text(json.dumps({"canaries": {}, "box": {"schema": "box-probe/1"}}), encoding="utf-8")
    assert probe.keep_box_key(str(path)) == {"box": {"schema": "box-probe/1"}}


# --- item #67, D2: the recorder's failure modes, the defaults, the six-agent workflow -----------------------------

def test_hook_sleeps_after_writing_the_row(tmp_path):
    import time
    t = time.monotonic()
    r, rows = hook(tmp_path, bash(RAN), "--sleep", "0.5")
    assert r.returncode == 0 and time.monotonic() - t >= 0.5
    assert len(rows) == 1 and rows[0]["command"] == RAN and rows[0]["blocked"] is False


def test_hook_exits_with_the_asked_code_after_writing_the_row(tmp_path):
    r, rows = hook(tmp_path, bash(RAN), "--exit-code", "1")
    assert r.returncode == 1 and len(rows) == 1 and rows[0]["command"] == RAN


def test_the_new_run_fields_default_to_the_old_scratch_project(probe, tmp_path):
    # every run that sets none of the new fields writes the settings it wrote before them, byte for byte
    for canary in probe.CANARIES:
        for run in canary.runs:
            if (canary.name, run.key) in HOOK_ENTRY:
                continue
            assert (run.pre_timeout, run.on_failure, run.hook_mode) == (10, None, ()), (canary.name, run.key)
            old = probe.Run(*run[:10])  # the ten fields a Run had before item #67
            a, b = tmp_path / f"{canary.name}-{run.key}-a", tmp_path / f"{canary.name}-{run.key}-b"
            probe.build_scratch(str(a), run, "haiku")
            probe.build_scratch(str(b), old, "haiku")
            got = (a / ".claude" / "settings.json").read_text().replace(str(a), "<s>")
            assert got == (b / ".claude" / "settings.json").read_text().replace(str(b), "<s>")
            assert '"onFailure"' not in got and "--sleep" not in got and "--exit-code" not in got


def test_the_six_agent_workflow_starts_six_leaf_agents_in_sequence(probe, tmp_path):
    run = probe.CANARY_BY_NAME["workflow-agents-total"].runs[0]
    probe.build_scratch(str(tmp_path), run, "haiku")
    text = (tmp_path / ".claude" / "workflows" / "kit-probe-six.js").read_text()
    assert text.startswith("export const meta = {\n  name: 'kit-probe-six',")
    assert "for (let i = 1; i <= 6; i++)" in text and text.count("await agent(") == 1
    assert json.dumps(probe.LEAF) in text and "model: 'haiku'" in text
    one = (tmp_path / "one")
    probe.build_scratch(str(one), probe.CANARY_BY_NAME["workflow-by-name"].runs[0], "haiku")
    assert (one / ".claude" / "workflows" / "kit-probe-run.js").read_text().count("await agent(") == 1
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "Bash|Agent|Workflow"
    assert "guard.py" not in json.dumps(settings["hooks"]["PreToolUse"]), "the scratch project runs no guard pre hook"
