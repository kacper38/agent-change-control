#!/usr/bin/env python3
"""Compare two guard files over every command of the given files and print each cell where the second guard
answers weaker than the first. A cell is one command, one context (branch and boundary) and one shell rule.
Commands are strings handed to rule functions; nothing runs.

usage: python3 -I weaker.py <expect.py> <old guard.py> <new guard.py> <file> [<file> ...] [--allow <file>]

A file is a rows file (five fields, the command is the last) or a list of commands (one per line; a line that
starts with a double quote is a JSON string). Every command is judged in three contexts: feat/x and own,
main and own, feat/x and client; a row's own context is added to them.
--allow names a file of commands whose weaker cells are expected and are counted apart.
Exit 1 when a cell is weaker and not allowed.
"""
import importlib.util
import json
import sys

RANK = {"silent": 0, "ask": 1, "deny": 2}
CONTEXTS = [("feat/x", "own"), ("main", "own"), ("feat/x", "client")]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def commands_of(path):
    """(command, extra context or None) for each line of a rows file or a list of commands."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln.strip() or ln.startswith("#"):
                continue
            parts = ln.split(" | ", 4)
            extra = None
            if len(parts) == 5 and parts[3].strip() in RANK:
                if parts[1].strip() in ("Read", "Write", "Edit"):
                    continue  # a row for the file tools: another checker
                branch, _, boundary = parts[1].strip().partition("@")
                extra = (branch, boundary or "own")
                ln = parts[4].strip()
            try:
                out.append((json.loads(ln) if ln.startswith('"') else ln, extra))
            except ValueError:
                out.append((ln, extra))
    return out


def main(argv):
    args, allow_paths, stronger_mode = [], [], False
    it = iter(argv[1:])
    for a in it:
        if a == "--allow":
            allow_paths.append(next(it))
        elif a == "--stronger":  # report the cells where the second guard answers more, not less
            stronger_mode = True
        else:
            args.append(a)
    expect = load(args[0], "expect_helper")
    old, new = expect.load(args[1]), load(args[2], "guard_new")
    if stronger_mode:
        RANK.update({"silent": 2, "ask": 1, "deny": 0})  # the same walk with the order turned round
    allowed = {c for p in allow_paths for c, _ in commands_of(p)}
    seen = set()
    cells = weaker = excused = crashes = 0
    for path in args[3:]:
        for command, extra in commands_of(path):
            for branch, boundary in CONTEXTS + ([extra] if extra and extra not in CONTEXTS else []):
                key = (command, branch, boundary)
                if key in seen:
                    continue
                seen.add(key)
                o = expect.answer(old, branch, boundary, "shell", command)
                n = expect.answer(new, branch, boundary, "shell", command)
                for rule in o:
                    cells += 1
                    if n[rule].startswith("CRASH"):
                        crashes += 1
                        print(f"CRASH [{branch}@{boundary}] {rule}: {n[rule]} | {json.dumps(command)[:150]}")
                    elif RANK.get(n[rule], 3) < RANK.get(o[rule], 3):
                        if command in allowed:
                            excused += 1
                            continue
                        weaker += 1
                        word = "STRONGER" if stronger_mode else "WEAKER"
                        print(f"{word} [{branch}@{boundary}] {rule}: {o[rule]} -> {n[rule]} | "
                              f"{json.dumps(command)[:150]}")
    word = "stronger" if stronger_mode else "weaker"
    print(f"old {old.VERSION} {args[1].rsplit('/', 1)[-1]} | new {new.VERSION} {args[2].rsplit('/', 1)[-1]}")
    print(f"commands in context {len(seen)} | cells {cells} | {word} {weaker} | allowed {word} {excused} | "
          f"crashes {crashes}")
    return 1 if weaker or crashes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
