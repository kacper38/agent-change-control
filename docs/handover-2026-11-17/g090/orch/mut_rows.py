"""For planted breaks of the guard: which rows of a rows file turn red under each one?

usage: python3 -I mut_rows.py <guard.py> <mutations.json> <expect.py> <rows file> <out folder> <id> [<id> ...]

For each named mutation the changed guard is written into the out folder (never over the guard given) and
expect.py checks the rows against it. Prints, per mutation, how many rows are red and their ids and commands.
A mutation with no red row is not caught by these rows. The commands are data; nothing runs.
"""
import json
import os
import subprocess
import sys


def main(argv):
    guard, spec, expect, rows, out = argv[:5]
    wanted = argv[5:]
    with open(guard, encoding="utf-8") as handle:
        original = handle.read()
    with open(spec, encoding="utf-8") as handle:
        mutations = {m["id"]: m for m in json.load(handle)}
    os.makedirs(out, exist_ok=True)
    for name in wanted:
        m = mutations[name]
        if original.count(m["old"]) != 1:
            print(f"{name}: NOT APPLIED (old text stands {original.count(m['old'])} times)")
            continue
        target = os.path.join(out, f"guard-{name}.py")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(original.replace(m["old"], m["new"]))
        proc = subprocess.run([sys.executable, "-I", expect, target, rows, "--red"], capture_output=True, text=True)
        # only the rows that hold on the unchanged guard (ids Fs and Fm) can show a break; the due rows are red anyway
        red = [line for line in proc.stdout.splitlines() if line.startswith(("RED Fs ", "RED Fm "))]
        print(f"{name}: red must-hold rows {len(red)} | {m['what']}")
        for line in red[:6]:
            print("    " + line[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
