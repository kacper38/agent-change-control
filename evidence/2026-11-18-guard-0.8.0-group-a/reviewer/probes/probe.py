#!/usr/bin/env python3
"""Print the verdict of the shell rules for each command of a data file, for one or more guard files.
Commands are strings handed to rule functions; nothing runs.

usage: python3 -I probe.py <commands file> <guard.py> [<guard.py> ...] [--branch main] [--boundary client] [--diff]

Commands file: one command per line; a line that starts with a double quote is a JSON string (for commands
with line breaks); empty lines and lines that start with `#` are skipped.
"""
import importlib.util
import json
import sys

SHELL_RULES = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
               "tracker-guard", "host-install"]


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_probe_{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_commands(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln.strip() or ln.startswith("#"):
                continue
            out.append(json.loads(ln) if ln.startswith('"') else ln)
    return out


def verdicts(g, command, branch, boundary):
    cfg = dict(g.DEFAULTS)
    cfg["host_install"] = "ask"
    cfg["boundary"] = boundary
    g.current_branch = lambda cwd, b=branch: b
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                  "cwd": "/nonexistent-scratch"})
    got = []
    for r in SHELL_RULES:
        if r not in g.RULES:
            continue
        try:
            d = g.RULES[r](ev, cfg)
        except Exception as exc:  # a crash is a finding, print it
            got.append(f"{r}=CRASH:{type(exc).__name__}")
            continue
        if d:
            got.append(f"{r}={d[0]}")
    return ", ".join(got) or "silent"


def main(argv):
    args, branch, boundary, only_diff = [], "feat/x", "own", False
    it = iter(argv[1:])
    for a in it:
        if a == "--branch":
            branch = next(it)
        elif a == "--boundary":
            boundary = next(it)
        elif a == "--diff":
            only_diff = True
        else:
            args.append(a)
    commands = read_commands(args[0])
    guards = [load(p, n) for n, p in enumerate(args[1:])]
    print(f"guards: {' | '.join(g.VERSION for g in guards)} | branch {branch} | boundary {boundary}")
    differ = 0
    for command in commands:
        cells = [verdicts(g, command, branch, boundary) for g in guards]
        differ += len(set(cells)) > 1
        if not only_diff or len(set(cells)) > 1:
            print(f"{json.dumps(command)[:78]:80} " + "  ||  ".join(cells))
    if only_diff:
        print(f"rows {len(commands)}, differ {differ}")


if __name__ == "__main__":
    main(sys.argv)
