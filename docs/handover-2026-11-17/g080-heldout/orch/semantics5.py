#!/usr/bin/env python3
"""Measure what a tool does with a spelling, in a fresh scratch repository. The argument lists come from a
data file; each entry is {"argv": [...], "env": {...}, "note": "..."}. Only reads are listed there.

usage: python3 -I semantics5.py <cases.json>
"""
import json
import os
import subprocess
import sys
import tempfile


def main(argv):
    with open(argv[1], encoding="utf-8") as fh:
        cases = json.load(fh)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", "-q", tmp], check=True)
        for case in cases:
            env = dict(os.environ, **case.get("env", {}))
            env["GIT_CONFIG_GLOBAL"] = os.devnull  # the scratch repository only
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            proc = subprocess.run(case["argv"], cwd=tmp, env=env, capture_output=True, text=True, timeout=30)
            print("$ " + " ".join(f"{k}={v}" for k, v in case.get("env", {}).items()) + " " + " ".join(case["argv"]))
            for line in (proc.stdout + proc.stderr).strip().splitlines()[:4]:
                print("  " + line[:160])
            print(f"-> exit {proc.returncode}   ({case.get('note', '')})")


if __name__ == "__main__":
    main(sys.argv)
