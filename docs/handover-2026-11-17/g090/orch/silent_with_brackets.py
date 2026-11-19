"""List the rows that expect silence, whose command holds a bracket, a backtick, `function`, `coproc` or
`alias`, and whose silence under secret-shell is new since the old guard (the old guard asked).

usage: python3 -I silent_with_brackets.py <expect.py> <old guard.py> <new guard.py> <rows file> [...]

These are the rows a stricter quiet-report check could turn red: read each before the check is tightened.
Commands are strings handed to rule functions; nothing runs.
"""
import importlib.util
import json
import re
import sys

MARK = re.compile(r"[()`]|\bfunction\b|\bcoproc\b|\balias\b")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    expect = load(argv[0], "expect_helper")
    old, new = expect.load(argv[1]), load(argv[2], "guard_new")
    seen = set()
    hits = 0
    rows = 0
    for path in argv[3:]:
        for rid, branch, boundary, rule, expected, command in expect.rows_of(path):
            if expected != "silent" or rule not in ("shell", "secret-shell"):
                continue
            rows += 1
            if not MARK.search(command) or (command, branch, boundary) in seen:
                continue
            seen.add((command, branch, boundary))
            o = expect.answer(old, branch, boundary, "shell", command)["secret-shell"]
            n = expect.answer(new, branch, boundary, "shell", command)["secret-shell"]
            if o != "silent" and n == "silent":
                hits += 1
                print(f"{path.rsplit('/', 1)[-1]:22} {rid:4} [{branch}@{boundary}] {o}>{n} | {json.dumps(command)[:170]}")
    print(f"silent rows read {rows} | with a mark and newly silent under secret-shell: {hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
