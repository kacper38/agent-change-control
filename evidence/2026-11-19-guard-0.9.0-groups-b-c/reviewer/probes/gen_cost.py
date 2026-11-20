"""Build 100 kB commands from cost-units.txt (name, prefix, unit, suffix; tab-separated) and time the eight shell
rules of a guard on each, as probe.py calls them. Commands are data handed to rule functions; nothing runs.
usage: python3 -I gen_cost.py <folder> <guard.py> [boundary]"""
import importlib.util
import sys
import time

HERE, GUARD = sys.argv[1], sys.argv[2]
BOUNDARY = sys.argv[3] if len(sys.argv) > 3 else "own"
SIZE = int(sys.argv[4]) if len(sys.argv) > 4 else 100_000
RULES = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
         "tracker-guard", "host-install"]

spec = importlib.util.spec_from_file_location("g", GUARD)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
g.current_branch = lambda cwd: "main"

with open(HERE + "/cost-units.txt", encoding="utf-8") as fh:
    for ln in fh:
        ln = ln.rstrip("\n")
        if not ln.strip():
            continue
        name, prefix, unit, suffix = ln.split("\t")
        n = max(1, (SIZE - len(prefix) - len(suffix)) // len(unit))
        cmd = prefix + unit * n + suffix
        cfg = dict(g.DEFAULTS)
        cfg["host_install"] = "ask"
        cfg["boundary"] = BOUNDARY
        ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
                      "cwd": "/nonexistent-scratch"})
        got, slow = [], []
        t0 = time.perf_counter()
        for r in RULES:
            t1 = time.perf_counter()
            try:
                d = g.RULES[r](ev, cfg)
            except Exception as exc:
                d = ("CRASH", type(exc).__name__)
            dt1 = time.perf_counter() - t1
            if dt1 > 0.3:
                slow.append(f"{r}:{dt1:.1f}")
            if d:
                got.append(f"{r}={d[0]}")
        dt = time.perf_counter() - t0
        print(f"{name:18s} {len(cmd):7d} {dt:6.2f}s  slow[{' '.join(slow)}]  {', '.join(got) or 'silent'}"[:230])
