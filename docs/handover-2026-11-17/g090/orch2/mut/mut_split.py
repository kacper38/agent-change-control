"""Split the planted breaks of several lists into chunks, one JSON file per chunk, for runs side by side.

usage: python3 -I mut_split.py <guard.py> <out folder> <chunks> <name>=<mutations.json> [<name>=<mutations.json> ...]

Every break keeps its fields; its id gets the list name in front (`fix7:g01`). A break whose `old` does not stand
exactly once in the given guard.py is left out and listed (the code it broke was replaced by a later round).
Chunk i holds every break whose place in the whole list is i modulo <chunks>. Nothing is run.
"""
import json
import os
import sys


def main(argv):
    guard, out, chunks = argv[0], argv[1], int(argv[2])
    with open(guard, encoding="utf-8") as fh:
        text = fh.read()
    os.makedirs(out, exist_ok=True)
    kept, left = [], []
    for pair in argv[3:]:
        name, _, path = pair.partition("=")
        with open(path, encoding="utf-8") as fh:
            for m in json.load(fh):
                m = dict(m, id=f"{name}:{m['id']}")
                (kept if text.count(m["old"]) == 1 else left).append(m)
    for i in range(chunks):
        with open(os.path.join(out, f"chunk-{i}.json"), "w", encoding="utf-8") as fh:
            json.dump(kept[i::chunks], fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    print(f"breaks {len(kept) + len(left)} | applied {len(kept)} in {chunks} chunks | old not exactly once {len(left)}")
    for m in left:
        print(f"NOT ONCE {m['id']} | {m.get('what', '')[:150]}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    main(sys.argv[1:])
