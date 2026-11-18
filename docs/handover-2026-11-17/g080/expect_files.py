#!/usr/bin/env python3
"""Check a guard file against acceptance rows for the file tools (Read, Write, Edit). The path is a string
handed to a rule function; no file is opened, written or created.

usage: python3 -I expect_files.py <guard.py> <rows file> [<rows file> ...] [--red]

Row: five fields separated by ` | `: id, tool, rule, expected, path.
  tool      Read, Write or Edit
  rule      one rule name (secret-read, secret-write, guard-config, ...)
  expected  silent, ask or deny; compared exactly with what that rule answers
  path      as the tool call names it; a relative path is joined to the scratch cwd of the event
Lines that are empty or start with `#` are skipped.
Prints the counts per id, every row that does not hold, and a total. With --red only the red rows.
Exit 1 when a row is red.
"""
import collections
import importlib.util
import sys

INPUT = {
    "Read": lambda p: {"file_path": p},
    "Write": lambda p: {"file_path": p, "content": "NAME=value\n"},
    "Edit": lambda p: {"file_path": p, "old_string": "a", "new_string": "b"},
}


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
            parts = [p.strip() for p in ln.split(" | ", 4)]
            if len(parts) != 5:
                sys.exit(f"{path}:{n}: expected five fields, got {len(parts)}")
            rid, tool, rule, expected, target = parts
            if tool not in INPUT:
                sys.exit(f"{path}:{n}: tool is {tool!r}")
            if expected not in ("silent", "ask", "deny"):
                sys.exit(f"{path}:{n}: expected is {expected!r}")
            yield rid, tool, rule, expected, target


def answer(g, tool, rule, target):
    cfg = dict(g.DEFAULTS)
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": INPUT[tool](target),
                  "cwd": "/nonexistent-scratch"})
    try:
        d = g.RULES[rule](ev, cfg)
    except Exception as exc:  # a crash is a finding
        return f"CRASH:{type(exc).__name__}"
    return d[0] if d else "silent"


def main(argv):
    only_red = "--red" in argv
    args = [a for a in argv[1:] if a != "--red"]
    g = load(args[0])
    per = collections.OrderedDict()
    red_total = total = 0
    for path in args[1:]:
        for rid, tool, rule, expected, target in rows_of(path):
            got = answer(g, tool, rule, target)
            ok = got == expected
            c = per.setdefault(rid, [0, 0])
            c[0] += 1
            c[1] += ok
            total += 1
            if not ok:
                red_total += 1
                print(f"RED {rid} {tool} {rule} expected {expected}, got {got} | {target}")
    if not only_red:
        for rid, (n, ok) in per.items():
            print(f"{rid}: rows {n} | hold {ok} | red {n - ok}")
    print(f"guard {g.VERSION} {args[0]}")
    print(f"total rows {total} | hold {total - red_total} | red {red_total}")
    return 1 if red_total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
