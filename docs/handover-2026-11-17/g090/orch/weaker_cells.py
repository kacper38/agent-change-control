#!/usr/bin/env python3
"""Every cell where the new guard answers weaker than the old one, with the acceptance row that asks for it.

usage: python3 -I weaker_cells.py <expect.py> <old guard.py> <new guard.py> <file> [<file> ...] [--list]

A file is a rows file (id | branch[@boundary] | rule | expected | command) or a list of commands (one per
line; a line that starts with a double quote is a JSON string). Every command is judged in three contexts
(feat/x own, main own, feat/x client) and in its row's own. A cell is one command, one context, one shell rule.

A weaker cell is "asked for" when a due row names the same command and the same rule (or `shell`) and expects
exactly the verdict the new guard gives. A due row has an id that ends in a digit (R1, K11) or is HR; ids
that end in s or t, HS and HO pin or observe a verdict and ask for no change. "same context": the row's
context is the cell's; "other context": the row stands for another branch or boundary. Every other weaker
cell is unexplained. Prints the counts per row id, and each unexplained cell; with --list also each cell that
is asked for. Exit 1 when a cell is unexplained or a rule crashed. Commands are strings handed to rule
functions; nothing runs.
"""
import collections
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


def lines_of(path):
    """(command, row or None) per line; a row is (id, (branch, boundary), rule, expected)."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln.strip() or ln.startswith("#"):
                continue
            parts = ln.split(" | ", 4)
            row = None
            if len(parts) == 5 and parts[3].strip() in RANK:
                if parts[1].strip() in ("Read", "Write", "Edit"):
                    continue  # a row for the file tools: another checker
                branch, _, boundary = parts[1].strip().partition("@")
                row = (parts[0].strip(), (branch, boundary or "own"), parts[2].strip(), parts[3].strip())
                ln = parts[4].strip()
            try:
                command = json.loads(ln) if ln.startswith('"') else ln
            except ValueError:
                command = ln
            out.append((command, row))
    return out


def is_due(rid):
    return rid == "HR" or rid[-1:].isdigit()


def main(argv):
    show = "--list" in argv
    cells_out = None
    if "--json" in argv:  # --json OUT: the unexplained cells with the whole command, for cell_kinds.py
        at = argv.index("--json")
        cells_out = argv[at + 1]
        argv = argv[:at] + argv[at + 2:]
    whole = []
    args = [a for a in argv[1:] if a != "--list"]
    expect = load(args[0], "expect_helper")
    old, new = expect.load(args[1]), load(args[2], "guard_new")
    rows = collections.defaultdict(list)  # command -> due rows
    contexts = collections.OrderedDict()  # command -> contexts to judge it in
    for path in args[3:]:
        for command, row in lines_of(path):
            wanted = contexts.setdefault(command, list(CONTEXTS))
            if row:
                if row[1] not in wanted:
                    wanted.append(row[1])
                if is_due(row[0]):
                    rows[command].append(row)
    cells = weaker = crashes = 0
    same = collections.Counter()
    other = collections.Counter()
    unexplained = []
    listed = []
    for command, wanted in contexts.items():
        for branch, boundary in wanted:
            o = expect.answer(old, branch, boundary, "shell", command)
            n = expect.answer(new, branch, boundary, "shell", command)
            for rule in o:
                cells += 1
                if n[rule].startswith("CRASH"):
                    crashes += 1
                    print(f"CRASH [{branch}@{boundary}] {rule}: {n[rule]} | {json.dumps(command)[:150]}")
                    continue
                if RANK.get(n[rule], 3) >= RANK.get(o[rule], 3):
                    continue
                weaker += 1
                asking = [r for r in rows[command] if r[2] in (rule, "shell") and r[3] == n[rule]]
                here = [r for r in asking if r[1] == (branch, boundary)]
                line = f"[{branch}@{boundary}] {rule}: {o[rule]} -> {n[rule]} | {json.dumps(command)[:150]}"
                if here:
                    same[here[0][0]] += 1
                    listed.append(f"ASKED {here[0][0]} {line}")
                elif asking:
                    other[asking[0][0]] += 1
                    listed.append(f"ASKED {asking[0][0]} (row in {asking[0][1][0]}@{asking[0][1][1]}) {line}")
                else:
                    unexplained.append(line)
                    whole.append({"branch": branch, "boundary": boundary, "rule": rule, "old": o[rule],
                                  "new": n[rule], "command": command})
    if cells_out:
        with open(cells_out, "w", encoding="utf-8") as fh:
            json.dump(whole, fh, indent=0)
    if show:
        for line in listed:
            print(line)
    for line in unexplained:
        print("UNEXPLAINED " + line)
    def per(counter):
        return ", ".join(f"{k} {v}" for k, v in sorted(counter.items())) or "none"
    print(f"old {old.VERSION} | new {new.VERSION} | commands {len(contexts)} | cells {cells} | weaker {weaker} | "
          f"asked for by a due row, same context {sum(same.values())} | other context {sum(other.values())} | "
          f"unexplained {len(unexplained)} | crashes {crashes}")
    print(f"same context, per id: {per(same)}")
    print(f"other context, per id: {per(other)}")
    return 1 if unexplained or crashes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
