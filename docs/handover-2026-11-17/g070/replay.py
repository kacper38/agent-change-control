#!/usr/bin/env python3
"""Replay the tool calls of real sessions against two guard files and list every verdict that changed.

usage: python3 -I replay.py <old guard.py> <new guard.py> <days> [--root DIR] [--boundary own|client]
                            [--show N] [--width N] [--no-text] [--log FILE]

Reads the Claude Code transcripts (*.jsonl, subagents included) under --root (default ~/.claude/projects) that
changed in the last <days> days. Every call of a tool the guard's hook is wired for goes to every rule both
guards have, with the call's own input, working directory and branch, as the hook would hand it over. Nothing
is run. A rule may read a file the call names, as it does in the hook; this script opens only transcripts.

Prints the counts, then two totals the after-build scripts look for:
  weaker:    a rule answers less than before (silent after ask or deny, ask after deny). Must be none.
  stronger:  a rule answers more than before. These are the prompts and denials the new guard adds.
Then the same per rule, and the calls behind them with how often each occurred.

The calls are real commands of real work, some of them from other repositories. The output belongs in a
local scratch folder. Numbers may go into a commit or a pull request; command text and branch names may not.
--no-text leaves both out, so that output can be kept as evidence; --log writes every changed cell as one JSON
line to a local file.

Not replayed: the rule `fan-out`, which counts spawns per session and would count this replay too.
"""
import collections
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time

WIRED = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Read", "Agent", "Task")
STATEFUL = ("fan-out",)
RANK = {"silent": 0, "ask": 1, "deny": 2}
NO_BRANCH = "feat/x"


def load(path, name):
    """One guard file as a module of its own, so that two versions can be asked side by side."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def transcripts(root, days):
    """Paths of the transcripts under root that changed in the last `days` days, oldest first."""
    since = time.time() - days * 86400
    found = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(folder, name)
            try:
                changed = os.path.getmtime(path)
            except OSError:  # the file went away while the folder was read: nothing to replay from it
                continue
            if changed >= since:
                found.append((changed, path))
    return [path for _changed, path in sorted(found)]


def calls_of(path):
    """(tool, input, cwd, branch) for each wired tool call an assistant entry of one transcript holds."""
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:  # unreadable transcript: reported by the caller through the count of files read
        return
    with handle:
        for line in handle:
            if '"tool_use"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:  # a cut or foreign line is no tool call
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if entry.get("type") != "assistant" or not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") in WIRED and isinstance(block.get("input"), dict):
                    yield block["name"], block["input"], entry.get("cwd") or "", entry.get("gitBranch") or ""


def verdicts(guard, names, tool, tool_input, cwd, branch, boundary):
    """What each named rule of one guard answers for one call: silent, ask, deny, or CRASH:<error>."""
    cfg = dict(guard.DEFAULTS)
    cfg["host_install"] = "ask"  # judged as on a developer machine, whatever machine runs the replay
    cfg["boundary"] = boundary
    guard.current_branch = lambda _cwd, b=branch: b
    event = guard.Event({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                         "cwd": cwd, "session_id": "replay", "transcript_path": "replay"})
    got = {}
    for name in names:
        try:
            decision = guard.RULES[name](event, cfg)
        except Exception as exc:  # a crash is a finding of the replay, not its end
            got[name] = f"CRASH:{type(exc).__name__}"
            continue
        got[name] = decision[0] if decision else "silent"
    return got


def head(tool, tool_input, width):
    """The part of a call a reader needs to recognise it, on one line."""
    if tool == "Bash":
        text = str(tool_input.get("command", ""))
    elif tool in ("Agent", "Task"):
        text = str(tool_input.get("subagent_type", "")) + " " + str(tool_input.get("description", ""))
    else:
        text = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    return json.dumps(text)[1:-1][:width]


def options(argv):
    """Positional arguments and the options of the usage line."""
    args = []
    opts = {"root": os.path.join(os.path.expanduser("~"), ".claude", "projects"), "boundary": "own",
            "show": 40, "width": 140, "text": True, "log": None}
    it = iter(argv)
    for arg in it:
        if arg == "--root":
            opts["root"] = next(it)
        elif arg == "--boundary":
            opts["boundary"] = next(it)
        elif arg == "--show":
            opts["show"] = int(next(it))
        elif arg == "--width":
            opts["width"] = int(next(it))
        elif arg == "--no-text":
            opts["text"] = False
        elif arg == "--log":
            opts["log"] = next(it)
        else:
            args.append(arg)
    if len(args) != 3:
        sys.exit(__doc__.strip().split("\n\n")[1] if "\n\n" in __doc__ else "usage: see the file's head")
    return args[0], args[1], int(args[2]), opts


def collect(paths):
    """Distinct calls with their count, and the totals per tool."""
    distinct = collections.OrderedDict()
    per_tool = collections.Counter()
    no_branch = 0
    for path in paths:
        for tool, tool_input, cwd, branch in calls_of(path):
            per_tool[tool] += 1
            if not branch or branch == "HEAD":
                no_branch += 1
                branch = NO_BRANCH
            key = hashlib.sha256(json.dumps([tool, tool_input, cwd, branch], sort_keys=True,
                                            default=str).encode("utf-8")).hexdigest()
            if key in distinct:
                distinct[key][0] += 1
            else:
                distinct[key] = [1, tool, tool_input, cwd, branch]
    return distinct, per_tool, no_branch


def main(argv):
    old_path, new_path, days, opts = options(argv)
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["KZ_TELEMETRY_DIR"] = scratch  # nothing a rule writes reaches the real telemetry folder
        old, new = load(old_path, "guard_replay_old"), load(new_path, "guard_replay_new")
        names = [n for n in new.RULES if n in old.RULES and n not in STATEFUL]
        only_new = [n for n in new.RULES if n not in old.RULES]
        paths = transcripts(opts["root"], days)
        distinct, per_tool, no_branch = collect(paths)
        total = sum(per_tool.values())
        print(f"transcripts: {len(paths)} changed in the last {days} days")
        print(f"tool calls: {total} | distinct: {len(distinct)} | "
              + ", ".join(f"{tool} {per_tool[tool]}" for tool in WIRED if per_tool[tool]))
        print(f"guards: {old.VERSION} | {new.VERSION} | boundary {opts['boundary']} | branch as recorded per call "
              f"({no_branch} calls without one judged as {NO_BRANCH})")
        print(f"rules compared: {', '.join(names)}"
              + (f" | only in the new guard, not compared: {', '.join(only_new)}" if only_new else ""))
        changed = []
        crashes = collections.Counter()
        for done, (count, tool, tool_input, cwd, branch) in enumerate(distinct.values(), 1):
            where = cwd if cwd and os.path.isdir(cwd) else "/nonexistent-scratch"
            before = verdicts(old, names, tool, tool_input, where, branch, opts["boundary"])
            after = verdicts(new, names, tool, tool_input, where, branch, opts["boundary"])
            for name in names:
                a, b = before[name], after[name]
                if a.startswith("CRASH") or b.startswith("CRASH"):
                    crashes[(name, a, b)] += count
                if a != b:
                    changed.append((count, name, a, b, tool, branch, tool_input))
            if done % 2000 == 0:
                print(f"  … {done} of {len(distinct)} distinct calls", file=sys.stderr)
        report(changed, crashes, total, days, opts)
    return 1 if any(RANK.get(b, -1) < RANK.get(a, -1) for _c, _n, a, b, _t, _br, _i in changed) else 0


def report(changed, crashes, total, days, opts):
    """The totals, the table per rule and the calls behind them."""
    weaker = [c for c in changed if RANK.get(c[3], -1) < RANK.get(c[2], -1)]
    stronger = [c for c in changed if RANK.get(c[3], -1) > RANK.get(c[2], -1)]
    w_calls, s_calls = sum(c[0] for c in weaker), sum(c[0] for c in stronger)
    print(f"weaker: {w_calls} occurrences in {len(weaker)} distinct cells")
    print(f"stronger: {s_calls} occurrences in {len(stronger)} distinct cells "
          f"({s_calls / max(days, 1):.1f} a day over {days} days, of {total} calls)")
    for (name, a, b), count in sorted(crashes.items()):
        print(f"crash: {name} {a} -> {b}: {count} occurrences")
    print("=== stronger per rule: rule | change | occurrences | distinct")
    per_rule = collections.OrderedDict()
    for count, name, a, b, _tool, _branch, _input in stronger:
        cell = per_rule.setdefault((name, f"{a}->{b}"), [0, 0])
        cell[0] += count
        cell[1] += 1
    for (name, change), (count, cells) in sorted(per_rule.items()):
        print(f"{name} | {change} | {count} | {cells}")
    lists = (("stronger, by occurrences", stronger, opts["show"]), ("weaker, every cell", weaker, None))
    for title, cells, limit in lists:
        print(f"=== {title}: occurrences | rule | change | tool" + (" | branch | call" if opts["text"] else ""))
        for count, name, a, b, tool, branch, tool_input in sorted(cells, key=lambda c: -c[0])[:limit]:
            line = f"{count} | {name} | {a}->{b} | {tool}"
            print(line + (f" | {branch} | {head(tool, tool_input, opts['width'])}" if opts["text"] else ""))
    if opts["log"]:
        with open(opts["log"], "w", encoding="utf-8") as handle:
            for count, name, a, b, tool, branch, tool_input in changed:
                handle.write(json.dumps({"count": count, "rule": name, "old": a, "new": b, "tool": tool,
                                         "branch": branch, "call": head(tool, tool_input, 2000)}) + "\n")
        print(f"log: {len(changed)} changed cells written")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
