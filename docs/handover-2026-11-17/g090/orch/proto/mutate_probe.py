"""Planted breaks for the design probe of the fifth fix round: is every rule of the strict reading pinned by a row?

usage: python3 -u -I mutate_probe.py <probe guard.py> <mutations.json> <expect.py> <scratch folder> <rows file>...

mutations.json is a list of {"id", "why", "old", "new"}: `old` must stand exactly once in the probe and is
replaced by `new`. Each mutant is written to the scratch folder and handed, with the rows files, to expect.py
(which loads the guard file and hands it each row's command as a string; nothing is run). A mutant is KILLED when
a row turns red, SURVIVED when every row holds, NOT APPLIED when `old` does not stand exactly once, BROKEN when
expect.py fails without a count (the mutant does not load).
"""
import importlib.util
import json
import os
import re
import subprocess
import sys


def main(argv):
    probe, mutations, expect, folder = argv[:4]
    rows = argv[4:]
    os.makedirs(folder, exist_ok=True)
    with open(probe, encoding="utf-8") as fh:
        text = fh.read()
    if mutations.endswith(".py"):  # a data module with raw strings: MUTATIONS = [dict(id, why, old, new), ...]
        spec = importlib.util.spec_from_file_location("mutations_data", mutations)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        todo = mod.MUTATIONS
    else:
        with open(mutations, encoding="utf-8") as fh:
            todo = json.load(fh)
    tally = {"KILLED": 0, "SURVIVED": 0, "NOT APPLIED": 0, "BROKEN": 0}
    for m in todo:
        if text.count(m["old"]) != 1:
            tally["NOT APPLIED"] += 1
            print(f"{m['id']} NOT APPLIED ({text.count(m['old'])} places) | {m['why']}")
            continue
        path = os.path.join(folder, m["id"] + ".py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(m["old"], m["new"]))
        r = subprocess.run([sys.executable, "-I", expect, path] + rows, capture_output=True, text=True)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        found = re.search(r"red (\d+)", last)
        if not found:
            tally["BROKEN"] += 1
            print(f"{m['id']} BROKEN | {m['why']} | {(r.stderr.strip().splitlines() or [''])[-1][:120]}")
            continue
        red = int(found.group(1))
        state = "KILLED" if red else "SURVIVED"
        tally[state] += 1
        ids = sorted({line.split()[1] for line in r.stdout.splitlines() if line.startswith("RED")})
        print(f"{m['id']} {state} | red {red} {' '.join(ids)[:60]} | {m['why']}")
    print(" | ".join(f"{k} {v}" for k, v in tally.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
