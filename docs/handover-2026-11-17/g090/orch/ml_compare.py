"""Compare two result files of multiline_meta.py: which turns they hold, and which commands are in one only.

usage: python3 -I ml_compare.py <old.json> <new.json> [--show]

Prints per file the number of weaker cells per turn (deny>ask, ask>silent, deny>silent) and of distinct
commands, then the commands that stand in the new file only, each with its rewritings, rules and turns
(with --show also every command of the new file). Read-only; nothing is run.
"""
import collections
import json
import sys


def cells_of(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        for key in ("cells", "weaker", "rows"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    return data


def turn_of(cell):
    for a, b in (("as_written", "rewritten"), ("plain", "rewritten"), ("old", "new"), ("base", "got")):
        if a in cell and b in cell:
            return f"{cell[a]}>{cell[b]}"
    return str(cell.get("turn", "?"))


def command_of(cell):
    for key in ("command", "cmd", "plain_command", "text"):
        if key in cell:
            return cell[key]
    return "?"


def summary(cells):
    turns = collections.Counter(turn_of(c) for c in cells)
    commands = collections.OrderedDict()
    for c in cells:
        commands.setdefault(command_of(c), []).append(c)
    return turns, commands


def describe(cells):
    kinds = collections.Counter((c.get("rewriting", c.get("kind", "?")), c.get("rule", "?"), turn_of(c)) for c in cells)
    return ", ".join(f"{k[0]}/{k[1]} {k[2]} x{n}" for k, n in sorted(kinds.items()))


def main(argv):
    show = "--show" in argv
    argv = [a for a in argv if a != "--show"]
    old, new = cells_of(argv[0]), cells_of(argv[1])
    if new and isinstance(new[0], dict):
        print("keys of a cell:", sorted(new[0].keys()))
    t_old, c_old = summary(old)
    t_new, c_new = summary(new)
    print(f"old: cells {len(old)} | commands {len(c_old)} | turns {dict(t_old)}")
    print(f"new: cells {len(new)} | commands {len(c_new)} | turns {dict(t_new)}")
    only_new = [c for c in c_new if c not in c_old]
    only_old = [c for c in c_old if c not in c_new]
    print(f"commands in the new file only: {len(only_new)} | in the old file only: {len(only_old)}")
    for c in only_new:
        print(f"  NEW  {json.dumps(c)} | {describe(c_new[c])}")
    for c in only_old:
        print(f"  GONE {json.dumps(c)} | {describe(c_old[c])}")
    changed = [c for c in c_new if c in c_old and len(c_new[c]) != len(c_old[c])]
    for c in changed:
        print(f"  COUNT {json.dumps(c)} | old {len(c_old[c])} | new {len(c_new[c])}")
    if show:
        for c, cells in c_new.items():
            print(f"  ALL  {json.dumps(c)} | {describe(cells)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
