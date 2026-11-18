#!/usr/bin/env python3
"""List the rows of a rows file by state for one guard file: which rows of the given ids hold, or are red.
Commands are strings handed to rule functions; nothing runs.

usage: python3 -I rows_state.py <guard.py> <rows file> <hold|red> <id> [<id> ...]
"""
import importlib.util
import os
import sys


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    guard, rows, state, ids = argv[1], argv[2], argv[3], set(argv[4:])
    expect = load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "expect.py"), "expect_helper")
    g = expect.load(guard)
    n = 0
    for rid, branch, boundary, rule, expected, command in expect.rows_of(rows):
        if rid not in ids:
            continue
        got = expect.answer(g, branch, boundary, rule, command)
        ok = all(v == expected for v in got.values())
        if ok == (state == "hold"):
            n += 1
            shown = ", ".join(f"{k}={v}" for k, v in got.items() if v != "silent") or "silent"
            print(f"{rid} [{branch}@{boundary}] {rule} expected {expected}, got {shown} | {command}")
    print(f"guard {g.VERSION}: {n} rows of {sorted(ids)} are {state}")


if __name__ == "__main__":
    main(sys.argv)
