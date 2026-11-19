"""Write the planted breaks of the eighth fix round as one JSON list for mutate.py.

usage: python3 -I make_mutations_fix8.py <guard.py> <out.json> [--check-only]

The breaks come from mutations_proto8.py beside this file (h..). Every `old` must stand exactly once in the given
guard.py; the script says which do not and exits 1. Nothing is run.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    guard, out = argv[0], argv[1]
    spec = importlib.util.spec_from_file_location("mutations_proto8", os.path.join(HERE, "mutations_proto8.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(guard, encoding="utf-8") as fh:
        text = fh.read()
    listed, bad = [], 0
    for m in mod.MUTATIONS:
        n = text.count(m["old"])
        if n != 1:
            bad += 1
            print(f"{m['id']} NOT ONCE ({n}): {m['why']}")
        listed.append({"id": m["id"], "what": m["why"], "old": m["old"], "new": m["new"]})
    print(f"breaks {len(listed)} | not once {bad}")
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
