"""Write the planted breaks of the fifth and the sixth fix round as one JSON list for mutate.py.

usage: python3 -I make_mutations_fix56.py <guard.py> <out.json> [--check-only]

The breaks come from proto/mutations_proto.py (fifth round, m..) and proto/mutations_proto5.py (sixth round,
n..). A break of the fifth round whose text the sixth round changed is rewritten here (FIXUPS) or dropped with
its reason (DROPPED). Every `old` must stand exactly once in the given guard.py; the script says which do not.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# id -> (old, new) as the text stands after the sixth round
FIXUPS = {
    "m03": (r'''"\\$\\[|\r|[\U000f0000''', r'''"\r|[\U000f0000'''),
    "m04": (r'''"\\$\\[|\r|[\U000f0000-\U000ffffd]")''', r'''"\\$\\[|\r")'''),
    "m27": ('''if head == "[[" and "=~" in words:''', "if False:"),
    "m31": ('''        words = tuple(_quiet_unmask(w) for w in masked_words)''', '''        words = tuple(masked_words)'''),
}
DROPPED = {"m13": "the same break as n21 since the sixth round", "m26": "the same break as n08 since the sixth round"}


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "proto", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MUTATIONS


def main(argv):
    guard, out = argv[0], argv[1]
    with open(guard, encoding="utf-8") as fh:
        text = fh.read()
    entries = []
    bad = 0
    for m in load("mutations_proto") + load("mutations_proto5"):
        if m["id"] in DROPPED:
            print(f"{m['id']} dropped: {DROPPED[m['id']]}")
            continue
        old, new = FIXUPS.get(m["id"], (m["old"], m["new"]))
        n = text.count(old)
        if n != 1:
            bad += 1
            print(f"{m['id']} stands {n} times | {m['why']} | {old[:90]!r}")
        entries.append({"id": m["id"], "what": m["why"], "old": old, "new": new})
    print(f"breaks {len(entries)} | not exactly once {bad}")
    if "--check-only" not in argv:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=True, indent=1)
        print("written " + out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
