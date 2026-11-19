"""Probe one planted break by hand: write the guard with the break of one id into a scratch file and print the
verdicts of the plain guard beside it for the commands of a data file.

usage: python3 -I mutant_probe.py <probe.py> <guard.py> <mutations.json> <id> <commands file> [--branch B]
       [--boundary own|client]

Nothing of the checkout is touched: the mutant is written next to this script as mutant-<id>.py.
"""
import importlib.util
import json
import os
import sys


def main(argv):
    probe_path, guard_path, spec_path, ident, commands_path = argv[:5]
    branch, boundary = "feat/x", "own"
    rest = argv[5:]
    if "--branch" in rest:
        branch = rest[rest.index("--branch") + 1]
    if "--boundary" in rest:
        boundary = rest[rest.index("--boundary") + 1]
    with open(spec_path, encoding="utf-8") as fh:
        mutation = next(m for m in json.load(fh) if m["id"] == ident)
    with open(guard_path, encoding="utf-8") as fh:
        text = fh.read()
    if text.count(mutation["old"]) != 1:
        print(f"old text stands {text.count(mutation['old'])} times")
        return 2
    mutant_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"mutant-{ident}.py")
    with open(mutant_path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(mutation["old"], mutation["new"]))
    spec = importlib.util.spec_from_file_location("probe_helper", probe_path)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    plain, mutant = probe.load(guard_path, 0), probe.load(mutant_path, 1)
    print(f"{ident}: {mutation['what']}")
    differ = 0
    for command in probe.read_commands(commands_path):
        a = probe.verdicts(plain, command, branch, boundary)
        b = probe.verdicts(mutant, command, branch, boundary)
        differ += a != b
        print(f"{'DIFFER' if a != b else 'same  '} {json.dumps(command)[:90]:92} {a}  ||  {b}"[:230])
    print(f"commands that tell the break: {differ}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
