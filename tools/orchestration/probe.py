#!/usr/bin/env python3
"""probe — re-run the orchestration canaries against the installed Claude Code CLI (plan step 0.1, D8).

  python3 tools/orchestration/probe.py [--only NAME ...] [--model haiku] [--claude-bin claude]
                                       [--out PATH] [--workdir DIR]
  python3 tools/orchestration/probe.py hook LOG [--only-allow NAME]     (internal: the hook recorder)

Each canary is one scripted `claude -p` run (depth-pin uses two; ledger-own-cost judges the workflow-by-name
run and pays for none) in a fresh scratch project under the workdir. The verdict (holds / fails /
inconclusive) comes only from hook rows, marker files, the run's result JSON and its transcripts, never from
model prose; missing evidence is inconclusive. A full run writes the record
(default verified.json next to this file); --only never writes it. Nothing is ever deleted.
Exit codes: 0 every selected canary holds, 1 otherwise, 2 usage or environment error (no usable CLI,
workdir collision). The hook recorder exits 2 to block a call or when it cannot do its job.
"""
import argparse
import datetime as _dt
import glob
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from typing import Callable, NamedTuple, Optional

TIMEOUT_S = 300
BUDGET_USD = 0.25
RAN = "ran.marker"
ALLOWED = "allowed.marker"
FORBIDDEN = "forbidden.marker"
RAN_CMD = f"touch {RAN}"  # the command texts are for the prompts only; rows are matched with touched()
ALLOWED_CMD = f"touch {ALLOWED}"
FORBIDDEN_CMD = f"touch {FORBIDDEN}"
WORKFLOW_AGENT = "workflow-subagent"
DEPTH_VAR = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
BG_VAR = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"

HERE = os.path.dirname(os.path.realpath(__file__))
PROBE = os.path.join(HERE, "probe.py")
GUARD = os.path.join(os.path.dirname(HERE), "guard", "guard.py")
LEDGER = os.path.join(os.path.dirname(HERE), "telemetry", "ledger.py")
LEDGER_TOLERANCE = 0.02  # the ledger's own count may differ from the run's total_cost_usd by this share
SCHEMA = "orchestration-probe/1"

RUN_PROMPT = "Run this Bash command exactly once, exactly as written, then answer with the single word done: " + RAN_CMD
TWO_CMDS_PROMPT = (f"Run these two Bash commands one at a time, exactly as written, and do not retry or rephrase "
                   f"either one: (1) {ALLOWED_CMD} (2) {FORBIDDEN_CMD}. Then answer with the single word done. A "
                   "blocked command is an expected outcome: report it and stop.")
MAIN_SPAWN = ("Use the Agent tool exactly once to start a subagent of type {agent} with the prompt \"go\". Wait for "
              "its reply, then answer with the single word done. Do not use any other tool.")
RELAY = ("You are a relay in an automated test. Use the Agent tool exactly once to start a subagent of type {next} "
         "with the prompt \"go\". Wait for its reply, then answer with that reply and nothing else. Do not do the work "
         "yourself. If you have no Agent tool, answer with the words no agent tool.")
LEAF_BASH = "You are the last step of an automated test. " + TWO_CMDS_PROMPT
LEAF = "You are the last step of an automated test. Answer with the single word leaf. Use no tools."

WORKFLOWS = {  # name: (description, prompt, label)
    "kit-probe-run": ("Canary: one agent runs one fixed Bash command", RUN_PROMPT, "ran"),
    "kit-probe-hook": ("Canary: one agent runs an allowed and a forbidden Bash command", TWO_CMDS_PROMPT, "hook"),
}
AGENTS = {  # name: (description, tools, body)
    "probe-outer": ("Canary relay: starts probe-inner", "Agent", RELAY.format(next="probe-inner")),
    "probe-inner": ("Canary leaf: runs an allowed and a forbidden Bash command", "Bash", LEAF_BASH),
    "probe-l1": ("Canary relay layer 1: starts probe-l2", "Agent", RELAY.format(next="probe-l2")),
    "probe-l2": ("Canary relay layer 2: starts probe-l3", "Agent", RELAY.format(next="probe-l3")),
    "probe-l3": ("Canary leaf layer 3: answers leaf", "Read", LEAF),
}
CHAIN = ["probe-l1", "probe-l2", "probe-l3"]


class ProbeError(Exception):
    pass


class Evidence(NamedTuple):
    exit_code: Optional[int]   # None when the process did not finish
    result: Optional[dict]     # the parsed result JSON, None when there was none
    error: Optional[str]       # runner-level problem, None when the run completed
    hook_rows: list            # rows of <scratch>/hook.jsonl
    markers: frozenset         # names of *.marker files in the scratch root
    spawn_rows: list           # rows of <scratch>/telemetry/spawns.jsonl
    transcript: Optional[str] = None  # the run's main transcript under <config dir>/projects/, None if not found


class Run(NamedTuple):
    key: str
    prompt: str
    allowed: tuple
    workflows: tuple
    agents: tuple
    block: bool
    env: dict
    fanout: bool


class Canary(NamedTuple):
    name: str
    expect: str
    backs: str
    runs: tuple
    judge: Callable[[dict], tuple]  # {run key: Evidence} -> (status, reason, observed)
    reuses: Optional[str] = None    # judge the evidence of this canary's runs instead of paying for runs of its own


# --- the hook recorder ---------------------------------------------------------------------------------------------

def hook_main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="probe.py hook")
    ap.add_argument("log")
    ap.add_argument("--only-allow")
    ns = ap.parse_args(argv)
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    except ValueError as exc:
        msg = f"unreadable hook input: {exc}"
        try:
            append_row(ns.log, {"error": msg})
        except OSError:
            pass  # the stderr line and exit 2 below still fail closed
        sys.stderr.write(f"probe hook: {msg}\n")
        return 2
    tool_input = data.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    event, tool, command = data.get("hook_event_name"), data.get("tool_name"), tool_input.get("command")
    # Anything that is not exactly `touch <path to NAME>` is blocked, a non-string command included: fail closed.
    blocked = bool(ns.only_allow is not None and event == "PreToolUse" and tool == "Bash"
                   and touched(command) != ns.only_allow)
    row = {"event": event, "tool": tool, "agent_id": data.get("agent_id"), "agent_type": data.get("agent_type"),
           "session_id": data.get("session_id"), "command": command, "subagent_type": tool_input.get("subagent_type"),
           "workflow": tool_input.get("name") if tool == "Workflow" else None, "blocked": blocked,
           "env": {k: os.environ[k] for k in (DEPTH_VAR, BG_VAR) if k in os.environ}}
    try:
        append_row(ns.log, row)
    except OSError as exc:
        sys.stderr.write(f"probe hook: cannot write {ns.log}: {exc}\n")
        return 2
    if blocked:
        sys.stderr.write("probe hook: blocked by the canary rule\n")
        return 2
    return 0


def touched(command) -> Optional[str]:
    """The file name a plain `touch <one path>` creates, else None. Subagents may write the path relative or
    absolute, so the scripted commands are recognised by the file name, not by the exact text."""
    if not isinstance(command, str):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if len(tokens) != 2 or tokens[0] != "touch":
        return None
    return os.path.basename(tokens[1])


def append_row(path: str, row: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


# --- the scratch project and one run -------------------------------------------------------------------------------

def build_scratch(scratch: str, run: Run, model: str) -> None:
    q = shlex.quote
    rec = f"{q(sys.executable)} -I {q(PROBE)} hook {q(os.path.join(scratch, 'hook.jsonl'))}"
    pre_cmd = rec + (f" --only-allow {q(ALLOWED)}" if run.block else "")
    start_hooks = [{"type": "command", "command": rec, "timeout": 10}]
    if run.fanout:
        fanout = (f"KZ_TELEMETRY_DIR={q(os.path.join(scratch, 'telemetry'))} {q(sys.executable)} {q(GUARD)} "
                  "hook fan-out --wrapper claude")
        start_hooks.append({"type": "command", "command": fanout, "timeout": 10})
    settings: dict = {"hooks": {
        "PreToolUse": [{"matcher": "Bash|Agent|Workflow",
                        "hooks": [{"type": "command", "command": pre_cmd, "timeout": 10}]}],
        "SubagentStart": [{"hooks": start_hooks}],
    }}
    if run.env:
        settings["env"] = dict(run.env)
    write(os.path.join(scratch, ".claude", "settings.json"), json.dumps(settings, indent=2) + "\n")
    for name in run.workflows:
        description, prompt, label = WORKFLOWS[name]
        write(os.path.join(scratch, ".claude", "workflows", f"{name}.js"),
              f"export const meta = {{\n  name: '{name}',\n  description: '{description}',\n}}\n\n"
              f"const reply = await agent({json.dumps(prompt)}, {{ model: '{model}', label: '{label}' }})\n"
              "return { reply }\n")
    for name in run.agents:
        description, tools, body = AGENTS[name]
        write(os.path.join(scratch, ".claude", "agents", f"{name}.md"),
              f"---\nname: {name}\ndescription: {description}\ntools: {tools}\nmodel: {model}\n---\n{body}\n")


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def run_argv(run: Run, model: str, claude_bin: str) -> list:
    argv = [claude_bin, "-p", run.prompt, "--model", model, "--permission-mode", "dontAsk",
            "--setting-sources", "project", "--max-budget-usd", str(BUDGET_USD)]
    if run.allowed:
        argv += ["--allowedTools", *run.allowed]  # variadic: must be followed by another flag
    return argv + ["--output-format", "json"]


def child_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("KZ_") and k not in (DEPTH_VAR, BG_VAR)}


def execute(scratch: str, run: Run, model: str, claude_bin: str) -> Evidence:
    exit_code, result, error = None, None, None
    try:
        g = subprocess.run(["git", "init", "-q", scratch], capture_output=True, text=True)
        git_error = g.stderr.strip() if g.returncode != 0 else None
    except OSError as exc:
        git_error = str(exc)
    if git_error is not None:
        error = f"git init failed: {git_error}"
    else:
        try:
            build_scratch(scratch, run, model)
        except OSError as exc:
            error = f"scratch project could not be written: {exc}"
    if error is None:
        try:
            # Explicit decoding: the locale must not decide, and a stray byte must not raise.
            r = subprocess.run(run_argv(run, model, claude_bin), cwd=scratch, env=child_env(),
                               stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace",
                               timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            error = f"timed out after {TIMEOUT_S} s"
        except OSError as exc:
            error = f"{claude_bin}: {exc}"
        else:
            exit_code = r.returncode
            try:
                parsed = json.loads(r.stdout)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("type") == "result":
                result = parsed
            else:
                error = f"no JSON result (exit {exit_code}): {(r.stderr.strip() or r.stdout.strip())[:200]}"
    markers = frozenset(n for n in os.listdir(scratch)
                        if n.endswith(".marker") and os.path.isfile(os.path.join(scratch, n)))
    return Evidence(exit_code, result, error, read_rows(os.path.join(scratch, "hook.jsonl")), markers,
                    read_rows(os.path.join(scratch, "telemetry", "spawns.jsonl")),
                    find_transcript(result.get("session_id") if result else None))


def find_transcript(session_id) -> Optional[str]:
    """<config dir>/projects/<project>/<session id>.jsonl, where Claude Code wrote the run's main transcript."""
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        return None
    root = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    hits = sorted(glob.glob(os.path.join(root, "projects", "*", session_id + ".jsonl")))
    return hits[0] if hits else None


def read_rows(path: str) -> list:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            rows.append(row if isinstance(row, dict) else {"error": "unparseable row"})
    return rows


# --- evidence helpers and judges -----------------------------------------------------------------------------------

def broken(ev: Evidence) -> Optional[str]:
    if ev.error:
        return ev.error
    if not isinstance(ev.result, dict):
        return "no JSON result"
    for row in ev.hook_rows:
        if "error" in row:
            return f"hook recorder error: {row['error']}"
    for row in ev.spawn_rows:
        if "error" in row:
            return f"spawn log error: {row['error']}"
    return None


def unclean(ev: Evidence) -> Optional[str]:
    reason = broken(ev)
    if reason:
        return reason
    assert isinstance(ev.result, dict)
    if ev.result.get("is_error"):
        return f"the run reported an error ({ev.result.get('subtype')})"
    if ev.exit_code != 0:
        return f"exit code {ev.exit_code}"
    return None


def result_field(ev: Evidence, key: str):
    return ev.result.get(key) if isinstance(ev.result, dict) else None


def denied_tools(ev: Evidence) -> list:
    denials = result_field(ev, "permission_denials")
    denials = denials if isinstance(denials, list) else []
    return sorted({str(d.get("tool_name")) for d in denials if isinstance(d, dict)})


def rows_where(ev: Evidence, **match) -> list:
    return [r for r in ev.hook_rows if all(r.get(k) == v for k, v in match.items())]


def workflow_agents_started(ev: Evidence) -> int:
    return len(rows_where(ev, event="SubagentStart", agent_type=WORKFLOW_AGENT))


def ran_in_workflow_agent(ev: Evidence) -> bool:
    rows = rows_where(ev, event="PreToolUse", tool="Bash", agent_type=WORKFLOW_AGENT)
    return RAN in ev.markers and any(touched(r.get("command")) == RAN for r in rows)


def judge_workflow(ev: Evidence, need_env: Optional[tuple] = None) -> tuple:
    index = result_field(ev, "result_index")
    observed = {"exit_code": ev.exit_code, "denied_tools": denied_tools(ev),
                "workflow_calls": len(rows_where(ev, event="PreToolUse", tool="Workflow")),
                "workflow_agents_started": workflow_agents_started(ev), "marker": "ran.marker" in ev.markers,
                "result_messages": index + 1 if isinstance(index, int) and not isinstance(index, bool) else None}
    reason = unclean(ev)
    if reason:
        return "inconclusive", reason, observed
    if need_env and not any((r.get("env") or {}).get(need_env[0]) == need_env[1] for r in ev.hook_rows):
        return ("inconclusive", f"{need_env[0]} was not visible in the hook environment, so the run does not show "
                "that the setting took effect", observed)
    if "Workflow" in observed["denied_tools"]:
        return "fails", "the launch was denied although the allow rule names the workflow", observed
    if ran_in_workflow_agent(ev):
        return "holds", "", observed
    if observed["marker"]:
        return "inconclusive", "ran.marker exists but no workflow agent is on record for the command", observed
    if observed["workflow_calls"] > 0 and observed["workflow_agents_started"] == 0:
        return "fails", "the Workflow tool was called and not denied, yet no workflow agent started", observed
    if observed["workflow_agents_started"] > 0:
        return "inconclusive", "a workflow agent started but did not run the scripted command", observed
    return "inconclusive", "the model did not call the Workflow tool", observed


def judge_denial(ev: Evidence) -> tuple:
    observed = {"exit_code": ev.exit_code, "subtype": result_field(ev, "subtype"),
                "is_error": result_field(ev, "is_error"), "denied_tools": denied_tools(ev),
                "workflow_agents_started": workflow_agents_started(ev)}
    reason = broken(ev)
    if reason:
        return "inconclusive", reason, observed
    if observed["workflow_agents_started"] > 0:
        return "fails", "a workflow agent started without the allow rule", observed
    if "Workflow" not in observed["denied_tools"]:
        return "inconclusive", "no Workflow denial is on record: the model may not have tried to launch it", observed
    if ev.exit_code == 0 and observed["subtype"] == "success" and not observed["is_error"]:
        return "holds", "", observed
    return "fails", "a denied launch now shows in the exit status or the result subtype", observed


def judge_block(ev: Evidence, agent_type: str, spawned_from: Optional[str] = None) -> tuple:
    def attempts(name: str) -> int:
        rows = rows_where(ev, event="PreToolUse", tool="Bash", agent_type=agent_type)
        return sum(1 for r in rows if touched(r.get("command")) == name)

    from_parent = None if spawned_from is None else bool(
        rows_where(ev, event="PreToolUse", tool="Agent", agent_type=spawned_from, subagent_type=agent_type))
    observed = {"allowed_marker": "allowed.marker" in ev.markers, "forbidden_marker": "forbidden.marker" in ev.markers,
                "allowed_attempts": attempts(ALLOWED), "forbidden_attempts": attempts(FORBIDDEN),
                "blocked_rows": len(rows_where(ev, agent_type=agent_type, blocked=True)),
                "spawned_from_parent": from_parent, "denied_tools": denied_tools(ev)}
    reason = broken(ev)
    if reason:
        return "inconclusive", reason, observed
    # Before anything else: if hooks never fire inside the agent there are no rows, and the marker is the evidence.
    if observed["forbidden_marker"]:
        return "fails", "the forbidden command ran", observed
    reason = unclean(ev)
    if reason:
        return "inconclusive", reason, observed
    if observed["forbidden_attempts"] == 0:
        return "inconclusive", f"no {agent_type} agent attempted the forbidden command", observed
    if not (observed["allowed_marker"] and observed["allowed_attempts"] > 0):
        return ("inconclusive", "the control command did not run in that agent, so a missing forbidden marker "
                "proves nothing", observed)
    if spawned_from is not None and not from_parent:
        return "inconclusive", f"no record that {agent_type} was started from inside {spawned_from}", observed
    return "holds", "", observed


def judge_depth(control: Evidence, pinned: Evidence) -> tuple:
    def started(ev: Evidence) -> list:
        return [a for a in CHAIN if rows_where(ev, event="SubagentStart", agent_type=a)]

    def max_depth(ev: Evidence):
        stats = result_field(ev, "subagent_stats")
        return stats.get("max_depth") if isinstance(stats, dict) else None

    def pin_seen(ev: Evidence):
        return next((r["env"][DEPTH_VAR] for r in ev.hook_rows
                     if isinstance(r.get("env"), dict) and DEPTH_VAR in r["env"]), None)

    observed = {"control_layers": len(started(control)), "pinned_layers": len(started(pinned)),
                "control_max_depth": max_depth(control), "pinned_max_depth": max_depth(pinned),
                "control_env": pin_seen(control), "pinned_env": pin_seen(pinned)}
    for key, ev in (("control", control), ("pinned", pinned)):
        reason = unclean(ev)
        if reason:
            return "inconclusive", f"{key} run: {reason}", observed
    if started(control) != CHAIN:
        return "inconclusive", "the control run at pin 3 did not reach layer 3, so the pinned run proves nothing", \
            observed
    if "probe-l3" in started(pinned):
        return "fails", "layer 3 started under pin 2", observed
    if started(pinned) == CHAIN[:2]:
        return "holds", "", observed
    if rows_where(pinned, event="PreToolUse", tool="Agent", agent_type="probe-l1", subagent_type="probe-l2"):
        return "fails", "layer 2 was requested and did not start under pin 2", observed
    return "inconclusive", "layer 1 never requested layer 2 in the pinned run", observed


def judge_spawn_log(ev: Evidence) -> tuple:
    rows = [r for r in ev.spawn_rows if r.get("event") == "SubagentStart"]
    session = result_field(ev, "session_id")
    observed = {"spawn_rows": len(rows), "agent_labels": sorted({str(r.get("agent")) for r in rows}),
                "same_session": all(r.get("session") == session for r in rows) if rows else None,
                "marker": "ran.marker" in ev.markers}
    reason = unclean(ev)
    if reason:
        return "inconclusive", reason, observed
    if any(r.get("agent") == WORKFLOW_AGENT for r in rows):
        return "holds", "", observed
    if ran_in_workflow_agent(ev):
        return "fails", "a workflow agent ran and the spawn log has no workflow-subagent row", observed
    return "inconclusive", "no workflow agent ran, so the spawn log had nothing to see", observed


def load_ledger():
    """tools/telemetry/ledger.py as a module, loaded from its path like the tests load it."""
    spec = importlib.util.spec_from_file_location("kit_ledger", LEDGER)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {LEDGER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def judge_ledger_cost(ev: Evidence) -> tuple:
    observed = {"transcript": ev.transcript is not None, "agent_transcripts": None, "workflow_transcripts": None,
                "parse_errors": None, "own_micro_usd": None, "run_micro_usd": None, "diff_bp": None}
    reason = unclean(ev)
    if reason:
        return "inconclusive", reason, observed
    run = result_field(ev, "total_cost_usd")
    if isinstance(run, bool) or not isinstance(run, (int, float)):
        return "inconclusive", "the result has no total_cost_usd", observed
    observed["run_micro_usd"] = round(run * 1_000_000)
    if not ev.transcript or not os.path.isfile(ev.transcript):
        return "inconclusive", "the run's transcript was not found", observed
    try:
        ledger = load_ledger()
    except (OSError, ImportError) as exc:
        return "inconclusive", f"the ledger could not be loaded: {exc}", observed
    prices = ledger.load_prices()
    session = os.path.basename(ev.transcript)[:-len(".jsonl")]
    read = ledger.read_session(ev.transcript, session, prices)
    own = ledger.own_cost(ledger.session_models(read, prices))
    observed.update(agent_transcripts=read["transcripts"], workflow_transcripts=read["workflow_transcripts"],
                    parse_errors=read["errors"])
    if read["errors"]:
        return "inconclusive", "the run's transcripts have parse errors, so the count may be short", observed
    if read["workflow_transcripts"] == 0:
        return "inconclusive", "no workflow-agent transcript, so the run does not test that the ledger reads it", \
            observed
    if own is None:
        return "inconclusive", "a model of the run has no price in prices.json", observed
    observed["own_micro_usd"] = round(own * 1_000_000)
    if run <= 0:
        return "inconclusive", "the run reports no cost, so there is nothing to compare", observed
    diff = abs(own - run) / run
    observed["diff_bp"] = round(diff * 10_000)
    if diff <= LEDGER_TOLERANCE:
        return "holds", "", observed
    return ("fails", f"the ledger's own count ${own:.6f} differs from the run's total_cost_usd ${run:.6f} by "
            f"{diff:.1%}, more than {LEDGER_TOLERANCE:.0%}", observed)


# --- the canaries --------------------------------------------------------------------------------------------------

# The Skill rule: a saved workflow is also listed as a skill, and the model may route `/name` through the Skill
# tool instead of calling Workflow directly (seen 2026-11-13 on CLI 2.1.323; the counts are in DECISIONS.md).
ALLOW_RUN = ("Skill(kit-probe-run)", "Workflow(kit-probe-run)", f"Bash(touch {RAN})", f"Bash(touch */{RAN})")
ALLOW_TWO = (f"Bash(touch {ALLOWED})", f"Bash(touch */{ALLOWED})", f"Bash(touch {FORBIDDEN})",
             f"Bash(touch */{FORBIDDEN})")


def wf_run(allowed: tuple = ALLOW_RUN, env: Optional[dict] = None, fanout: bool = False) -> Run:
    return Run("run", "/kit-probe-run", allowed, ("kit-probe-run",), (), False, env or {}, fanout)


def depth_run(key: str, pin: str) -> Run:
    return Run(key, MAIN_SPAWN.format(agent="probe-l1"), ("Agent",), (), tuple(CHAIN), False, {DEPTH_VAR: pin}, False)


CANARIES = (
    Canary("workflow-by-name",
           "a saved workflow starts by name under dontAsk when allow rules name it for both routes the model may "
           "take, Workflow(<name>) and Skill(<name>), and its agent runs",
           "fact 4, D2", (wf_run(),), lambda e: judge_workflow(e["run"])),
    Canary("denial-exits-zero",
           "without the Workflow(<name>) allow rule the launch is denied, also when Skill(<name>) is allowed, and "
           "the run still exits 0 with subtype success",
           "fact 3, D4", (wf_run(allowed=("Skill(kit-probe-run)",)),), lambda e: judge_denial(e["run"])),
    Canary("hook-blocks-workflow-agent",
           "a PreToolUse hook from project settings fires inside a workflow agent and its exit 2 blocks the call",
           "fact 5, D7",
           (Run("run", "/kit-probe-hook", ("Skill(kit-probe-hook)", "Workflow(kit-probe-hook)", *ALLOW_TWO),
                ("kit-probe-hook",), (), True, {}, False),),
           lambda e: judge_block(e["run"], WORKFLOW_AGENT)),
    Canary("hook-blocks-nested-subagent",
           "a PreToolUse hook from project settings fires inside a subagent started by a subagent and its exit 2 "
           "blocks the call",
           "fact 5, D1",
           (Run("run", MAIN_SPAWN.format(agent="probe-outer"), ("Agent", *ALLOW_TWO), (),
                ("probe-outer", "probe-inner"), True, {DEPTH_VAR: "2"}, False),),
           lambda e: judge_block(e["run"], "probe-inner", spawned_from="probe-outer")),
    Canary("depth-pin",
           "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 in settings env allows a second subagent layer and no third",
           "fact 8, D1, step 1.1", (depth_run("control", "3"), depth_run("pinned", "2")),
           lambda e: judge_depth(e["control"], e["pinned"])),
    Canary("spawn-log-workflow-agents",
           "the guard's SubagentStart hook logs a workflow agent to spawns.jsonl as workflow-subagent",
           "section 1 (fan-out control), step 1.2", (wf_run(fanout=True),), lambda e: judge_spawn_log(e["run"])),
    Canary("workflow-background-off",
           "a saved workflow still starts by name and its agent runs with CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 in "
           "settings env",
           "D4 item 3 with D2, step 2.4", (wf_run(env={BG_VAR: "1"}),),
           lambda e: judge_workflow(e["run"], need_env=(BG_VAR, "1"))),
    Canary("ledger-own-cost",
           "the ledger's own count over a probe run's transcripts, workflow agent included, is within 2 % of the "
           "run's total_cost_usd (judged on the workflow-by-name run, no run of its own)",
           "step 0.2 (#38)", (), lambda e: judge_ledger_cost(e["run"]), reuses="workflow-by-name"),
)
CANARY_BY_NAME = {c.name: c for c in CANARIES}


# --- main ----------------------------------------------------------------------------------------------------------

def model_name(value: str) -> str:
    """argparse type: the model goes into generated JS and YAML, so quotes, spaces and newlines must not pass."""
    if not re.fullmatch(r"[A-Za-z0-9._:/@\[\]-]+", value):
        raise argparse.ArgumentTypeError(f"not a model name: {value!r}")
    return value


def cli_version(claude_bin: str) -> str:
    try:
        r = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(str(exc)) from exc
    if r.returncode != 0:
        raise ProbeError(f"exit {r.returncode}: {r.stderr.strip()[:200]}")
    m = re.match(r"^\s*(\d+\.\d+\.\d+)", r.stdout)
    if not m:
        raise ProbeError(f"no version in {r.stdout.strip()[:200]!r}")
    return m.group(1)


def cost_of(evidence: list) -> Optional[float]:
    costs = [c for c in (result_field(ev, "total_cost_usd") for ev in evidence)
             if isinstance(c, (int, float)) and not isinstance(c, bool)]
    return round(sum(costs), 4) if costs else None


def money(cost: Optional[float]) -> str:
    return "n/a" if cost is None else f"${cost:.4f}"


def main(argv: list, out=None) -> int:
    out = out or sys.stdout
    if argv[:1] == ["hook"]:
        return hook_main(argv[1:])
    ap = argparse.ArgumentParser(prog="probe", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", choices=[c.name for c in CANARIES], metavar="NAME")
    ap.add_argument("--model", default="haiku", type=model_name)
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--out", default=os.path.join(HERE, "verified.json"))
    ap.add_argument("--workdir")
    ns = ap.parse_args(argv)
    selected = [c for c in CANARIES if not ns.only or c.name in ns.only]
    try:
        version = cli_version(ns.claude_bin)
    except ProbeError as exc:
        out.write(f"probe: no usable CLI at {ns.claude_bin}: {exc}\n")
        return 2
    if ns.workdir:
        workdir = os.path.realpath(ns.workdir)  # hook commands run from the scratch project, so paths are absolute
    else:
        workdir = os.path.realpath(tempfile.mkdtemp(prefix="orchestration-probe-"))
        out.write(f"probe: scratch projects in {workdir}\n")  # the evidence stays there for inspection
    # All run directories are created before the first run, so a collision costs no model spend. A canary that
    # reuses another's runs needs that canary's directories, also when only it was selected.
    scratches = {}
    for canary in selected:
        source = CANARY_BY_NAME[canary.reuses] if canary.reuses else canary
        for run in source.runs:
            if (source.name, run.key) in scratches:
                continue
            path = os.path.join(workdir, f"{source.name}-{run.key}")
            try:
                os.makedirs(path, exist_ok=False)
            except FileExistsError:
                out.write(f"probe: {path} already exists; nothing is deleted, pick a fresh --workdir\n")
                return 2
            scratches[(source.name, run.key)] = path
    started = _dt.datetime.now(_dt.timezone.utc)
    entries, models, holding = {}, set(), 0
    evidence_of: dict = {}
    for canary in selected:
        source = CANARY_BY_NAME[canary.reuses] if canary.reuses else canary
        fresh = source.name not in evidence_of
        if fresh:
            evidence_of[source.name] = {run.key: execute(scratches[(source.name, run.key)], run, ns.model,
                                                         ns.claude_bin) for run in source.runs}
        evidence = evidence_of[source.name]
        for ev in evidence.values() if fresh else ():
            usage = result_field(ev, "modelUsage")
            models.update(usage if isinstance(usage, dict) else ())
        status, reason, observed = canary.judge(evidence)
        if status != "holds" and observed.get("denied_tools"):
            # A denial is often the whole story, and with --only this line is all the operator sees.
            reason += "; denied tools: " + ", ".join(observed["denied_tools"])
        cost = cost_of(list(evidence.values()))
        if cost is not None and not fresh:
            cost = 0.0  # reused runs were paid for once, under the canary that ran them
        entries[canary.name] = {"status": status, "reason": reason, "expect": canary.expect, "backs": canary.backs,
                                "observed": observed, "cost_usd": cost}
        holding += status == "holds"
        out.write(f"{status:<14}{canary.name:<30}{money(cost)}\n")
        if status != "holds":
            out.write(f"{'':<14}{reason}\n")
    total = round(sum(e["cost_usd"] for e in entries.values() if e["cost_usd"] is not None), 4)
    if ns.only:
        tail = "not written (--only)"
    else:
        record = {"schema": SCHEMA, "cli_version": version, "date": started.date().isoformat(), "model": ns.model,
                  "models": sorted(models), "cost_usd": total, "canaries": entries}
        try:
            with open(ns.out + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(record, fh, indent=2)
                fh.write("\n")
            os.replace(ns.out + ".tmp", ns.out)
        except OSError as exc:
            out.write(f"probe: cannot write {ns.out}: {exc}\n")
            return 2
        tail = f"wrote {ns.out}"
    out.write(f"probe: CLI {version}, {holding} of {len(selected)} canaries hold, {money(total)}; {tail}\n")
    return 0 if holding == len(selected) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
