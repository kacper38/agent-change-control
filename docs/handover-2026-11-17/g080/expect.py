#!/usr/bin/env python3
"""Check a guard file against acceptance rows. Commands are strings handed to rule functions; nothing runs.

usage: python3 -I expect.py <guard.py> <rows file> [<rows file> ...] [--red]

Row: five fields separated by ` | ` (space, bar, space): id, branch, rule, expected, command.
  branch    the checked-out branch the rules are told (`feat/x`, `main`); `@client` behind it sets the boundary
            to client (default own), as in `feat/x@client`
  rule      one rule name, or `shell` for the eight shell rules together (only with expected `silent`)
  expected  silent, ask or deny; compared exactly with what that rule answers
  command   the last field; it may hold ` | ` itself; a command that starts with a double quote is a JSON
            string (for commands with line breaks)
Lines that are empty or start with `#` are skipped.
Prints the counts per id, every row that does not hold, and a total. With --red it prints only the red rows.
Exit 1 when a row is red.
"""
import collections
import importlib.util
import json
import sys

SHELL_RULES = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
               "tracker-guard", "host-install"]


def load(path):
    spec = importlib.util.spec_from_file_location("guard_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rows_of(path):
    with open(path, encoding="utf-8") as fh:
        for n, ln in enumerate(fh, 1):
            ln = ln.rstrip("\n")
            if not ln.strip() or ln.startswith("#"):
                continue
            parts = ln.split(" | ", 4)
            if len(parts) != 5:
                sys.exit(f"{path}:{n}: expected five fields, got {len(parts)}")
            rid, branch, rule, expected, command = (p.strip() for p in parts)
            if command.startswith('"'):
                command = json.loads(command)
            branch, _, boundary = branch.partition("@")
            if expected not in ("silent", "ask", "deny"):
                sys.exit(f"{path}:{n}: expected is {expected!r}")
            if rule == "shell" and expected != "silent":
                sys.exit(f"{path}:{n}: rule `shell` goes with `silent` only")
            yield rid, branch, boundary or "own", rule, expected, command


def answer(g, branch, boundary, rule, command):
    cfg = dict(g.DEFAULTS)
    cfg["host_install"] = "ask"
    cfg["boundary"] = boundary
    g.current_branch = lambda cwd, b=branch: b
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                  "cwd": "/nonexistent-scratch"})
    names = SHELL_RULES if rule == "shell" else [rule]
    got = {}
    for r in names:
        try:
            d = g.RULES[r](ev, cfg)
        except Exception as exc:  # a crash is a finding
            got[r] = f"CRASH:{type(exc).__name__}"
            continue
        got[r] = d[0] if d else "silent"
    return got


def main(argv):
    only_red = "--red" in argv
    args = [a for a in argv[1:] if a != "--red"]
    g = load(args[0])
    per = collections.OrderedDict()
    red_total = total = 0
    for path in args[1:]:
        for rid, branch, boundary, rule, expected, command in rows_of(path):
            got = answer(g, branch, boundary, rule, command)
            ok = all(v == expected for v in got.values())
            c = per.setdefault(rid, [0, 0])
            c[0] += 1
            c[1] += ok
            total += 1
            if not ok:
                red_total += 1
                shown = ", ".join(f"{k}={v}" for k, v in got.items() if v != expected)
                print(f"RED {rid} [{branch}@{boundary}] {rule} expected {expected}, got {shown} | {json.dumps(command)[:110]}")
    if not only_red:
        for rid, (n, ok) in per.items():
            print(f"{rid}: rows {n} | hold {ok} | red {n - ok}")
    print(f"guard {g.VERSION} {args[0]}")
    print(f"total rows {total} | hold {total - red_total} | red {red_total}")
    return 1 if red_total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
