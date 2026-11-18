#!/usr/bin/env python3
"""Break each new code path of the guard once, in a scratch copy of the tree, and see that a test fails.

usage: python3 -I mutate.py <scratch copy of the checkout> <mutations.json> [<test path> ...]

mutations.json is a list of {"id": "...", "what": "...", "old": "...", "new": "..."}: one exact replacement in
tools/guard/guard.py; `old` must stand in the file exactly once. For each one the script writes the changed
file into the scratch copy, runs the tests there and notes whether any test failed, then writes the original
text back. The checkout under review is never touched.
Prints one line per mutation: KILLED (a test failed), SURVIVED (all passed) or NOT APPLIED.
Exit 1 when a mutation survived or was not applied.
"""
import json
import os
import re
import subprocess
import sys


def run_tests(root, paths):
    cmd = ["uv", "run", "--directory", root, "--offline", "--no-project", "--with", "pytest", "--python", "3.13",
           "python", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-o", "addopts=", *paths]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1:] or [proc.stderr.strip()[-200:]]
    failed = re.search(r"^(FAILED|ERROR) (\S+)", proc.stdout, re.MULTILINE)
    return proc.returncode, tail[0], failed.group(2) if failed else ""


def main(argv):
    root, spec = argv[1], argv[2]
    paths = argv[3:] or ["tools/guard/tests/test_bypass_forms.py"]
    target = os.path.join(root, "tools", "guard", "guard.py")
    with open(target, encoding="utf-8") as fh:
        original = fh.read()
    with open(spec, encoding="utf-8") as fh:
        mutations = json.load(fh)
    code, tail, _ = run_tests(root, paths)
    print(f"unchanged: exit {code} | {tail}")
    if code != 0:
        print("the unchanged copy does not pass: stop")
        return 2
    bad = 0
    try:
        for m in mutations:
            count = original.count(m["old"])
            if count != 1:
                bad += 1
                print(f"NOT APPLIED {m['id']:5} old text stands {count} times | {m['what']}")
                continue
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original.replace(m["old"], m["new"]))
            code, tail, first = run_tests(root, paths)
            if code == 0:
                bad += 1
                print(f"SURVIVED    {m['id']:5} {m['what']} | {tail}")
            else:
                print(f"KILLED      {m['id']:5} {m['what']} | first: {first[-90:] or tail[-90:]}")
    finally:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(original)
    print(f"mutations {len(mutations)} | not killed {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
