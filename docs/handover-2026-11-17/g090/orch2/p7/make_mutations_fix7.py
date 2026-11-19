"""Write the planted breaks of the seventh fix round as one JSON list for mutate.py.

usage: python3 -I make_mutations_fix7.py <guard.py> <out.json> [--check-only]

The breaks come from mutations_proto6.py beside this file (g..). One is dropped with its reason (DROPPED).
Every `old` must stand exactly once in the given guard.py; the script says which do not and exits 1.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DROPPED = {"g04": "changes a verdict only where a shell word stands between an assignment and git: on seven such "
                  "lines neither zsh nor bash runs git (run3.log)"}


def main(argv):
    guard, out = argv[0], argv[1]
    spec = importlib.util.spec_from_file_location("mutations_proto6", os.path.join(HERE, "mutations_proto6.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(guard, encoding="utf-8") as fh:
        text = fh.read()
    listed, bad = [], 0
    for m in mod.MUTATIONS:
        if m["id"] in DROPPED:
            print(f"{m['id']} dropped: {DROPPED[m['id']]}")
            continue
        n = text.count(m["old"])
        if n != 1:
            bad += 1
            print(f"{m['id']} NOT ONCE ({n}): {m['why']}")
        listed.append({"id": m["id"], "what": m["why"], "old": m["old"], "new": m["new"]})
    print(f"breaks {len(listed)} | not once {bad} | dropped {len(DROPPED)}")
    if bad:
        return 1
    if "--check-only" not in argv:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(listed, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
