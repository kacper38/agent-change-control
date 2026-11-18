#!/usr/bin/env python3
"""Time the eight shell rules, in process, on a pipe into a chain of remote hops, for one guard file.
The command is built from a pattern in a data file beside this script; nothing runs.

usage: python3 -I chain_time.py <guard.py> <hops> [<hops> ...]
"""
import importlib.util
import json
import os
import sys
import time

RULES = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
         "tracker-guard", "host-install"]


def main(argv):
    spec = importlib.util.spec_from_file_location("guard_timed", argv[1])
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "chain_pattern.json"), encoding="utf-8") as fh:
        pattern = json.load(fh)
    cfg = dict(g.DEFAULTS)
    cfg["host_install"] = "ask"
    g.current_branch = lambda cwd: "feat/x"
    for hops in (int(a) for a in argv[2:]):
        for name, head, hop, tail in pattern:
            command = head + "".join(hop.format(n=n) for n in range(hops)) + tail
            ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                          "cwd": "/nonexistent-scratch"})
            start = time.perf_counter()
            got = [(r, g.RULES[r](ev, cfg)) for r in RULES]
            took = time.perf_counter() - start
            said = ", ".join(f"{r}={d[0]}" for r, d in got if d) or "silent"
            print(f"{hops:3} hops | {name:28} | {took:7.3f} s | {said}")


if __name__ == "__main__":
    main(sys.argv)
