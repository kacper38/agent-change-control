"""Count the replay's weaker cells per kind of group C, without printing a command.

usage: python3 -I replay_kinds.py <cell_kinds.py> <detail.json> [--shape]

Reads the detail file of the close-out replay (it holds real command text and stays local). For every cell whose
verdict at the new guard is weaker than at the old one, the kind is guessed with the patterns of cell_kinds.py
(the sorter of the cell check). Prints, per boundary: rule | change | kind | occurrences. --shape prints the
layout of the file (key names and types only) and stops.
"""
import collections
import importlib.util
import json
import sys

RANK = {"silent": 0, None: 0, "": 0, "allow": 0, "ask": 1, "deny": 2}


def shape(obj, depth=0, limit=5):
    pad = "  " * depth
    if isinstance(obj, dict):
        for k in list(obj)[:12]:
            v = obj[k]
            print(f"{pad}{k if depth == 0 or len(str(k)) < 24 else '<key>'}: {type(v).__name__}"
                  + (f" len {len(v)}" if hasattr(v, "__len__") and not isinstance(v, str) else ""))
            if depth < limit and isinstance(v, (dict, list)):
                shape(v, depth + 1, limit)
    elif isinstance(obj, list) and obj:
        print(f"{pad}[0]: {type(obj[0]).__name__}")
        if depth < limit and isinstance(obj[0], (dict, list)):
            shape(obj[0], depth + 1, limit)


def main(argv):
    spec = importlib.util.spec_from_file_location("cell_kinds", argv[0])
    ck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ck)
    with open(argv[1], encoding="utf-8") as fh:
        doc = json.load(fh)
    if "--shape" in argv:
        shape(doc)
        return 0
    for name, part in doc["boundaries"].items():
        rows = collections.Counter()
        cells = collections.Counter()
        for c in part["changed"]:
            old, new = RANK.get(c["old"], 0), RANK.get(c["new"], 0)
            if new >= old:
                continue
            kind = ck.kind_of(c["rule"], c["call"]) if c["tool"] == "Bash" else "not a shell call: " + c["tool"]
            key = (c["rule"], f"{c['old']}>{c['new'] or 'silent'}", kind)
            rows[key] += c["count"]
            cells[key] += 1
        print(f"== boundary {name}: weaker occurrences {sum(rows.values())} in {sum(cells.values())} distinct cells")
        print("rule | change | kind (the sorter's guess from the words of the command) | occurrences | distinct")
        for key in sorted(rows):
            print(" | ".join(key) + f" | {rows[key]} | {cells[key]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
