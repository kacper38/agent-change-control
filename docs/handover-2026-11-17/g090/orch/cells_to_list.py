"""Write the rewritten texts of the weaker cells of a multi-line check as a commands list for probe.py.

usage: python3 -I cells_to_list.py <cells.json> <out list> [--turn ask>silent] [--plain]

Each distinct text becomes one JSON-string line, so a text with a line break stays one command. With --plain the
command as written goes out instead of the rewritten text. Commands are data: nothing is run.
"""
import json
import sys


def main(argv):
    turn, plain, args = None, False, []
    it = iter(argv)
    for a in it:
        if a == "--turn":
            turn = next(it)
        elif a == "--plain":
            plain = True
        else:
            args.append(a)
    cells = json.load(open(args[0], encoding="utf-8"))
    seen, out = set(), []
    for c in cells:
        if turn and f"{c['as_written']}>{c['rewritten']}" != turn:
            continue
        text = c["command"] if plain else c["text"]
        if text in seen:
            continue
        seen.add(text)
        out.append(json.dumps(text))
    with open(args[1], "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"{len(out)} distinct texts of {len(cells)} cells -> {args[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
