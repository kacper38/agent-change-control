"""The weaker cells of an unexplained.json whose command the session has not read yet.

usage: python3 -I unread_cells.py <unexplained.json> <cells-read.txt> [--minus <older unexplained.json>]

Prints every distinct command that is not in cells-read.txt, with the rules and turns of its cells. With --minus
only the commands that the older file does not hold either: what is new since a head whose list was read.
Nothing is run.
"""
import collections
import json
import sys


def commands_of(path):
    with open(path, encoding="utf-8") as handle:
        cells = json.load(handle)
    found = collections.OrderedDict()
    for cell in cells:
        turn = f"{cell.get('rule')}: {cell.get('old')}>{cell.get('new')}"
        found.setdefault(cell["command"], set()).add(turn)
    return found


def main(argv):
    source, known = argv[0], argv[1]
    older = argv[argv.index("--minus") + 1] if "--minus" in argv else None
    have = set()
    with open(known, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line.startswith('"'):
                have.add(json.loads(line))
    before = set(commands_of(older)) if older else set()
    found = commands_of(source)
    unread = [c for c in found if c not in have]
    fresh = [c for c in unread if c not in before]
    print(f"distinct commands {len(found)} | read before {len(found) - len(unread)} | unread {len(unread)}"
          + (f" | not in the older list either {len(fresh)}" if older else ""))
    for command in (fresh if older else unread):
        print(f"  {json.dumps(command)[:170]} | {', '.join(sorted(found[command]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
