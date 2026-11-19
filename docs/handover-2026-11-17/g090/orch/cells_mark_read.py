"""Append the distinct commands of an unexplained.json to the list of cells the session has read.

usage: python3 -I cells_mark_read.py <unexplained.json> <cells-read.txt> <note>

Only called after every command of that file was read against its kind. Each command is written as one JSON
string per line under a comment line with the note; commands already in the list are skipped.
"""
import json
import sys


def main(argv):
    source, target, note = argv[0], argv[1], argv[2]
    with open(source, encoding="utf-8") as handle:
        cells = json.load(handle)
    have = set()
    with open(target, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line.startswith('"'):
                have.add(json.loads(line))
    fresh = []
    for cell in cells:
        if cell["command"] not in have and cell["command"] not in fresh:
            fresh.append(cell["command"])
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"# {note}\n")
        for command in fresh:
            handle.write(json.dumps(command, ensure_ascii=False) + "\n")
    print(f"added {len(fresh)} commands, {len(have)} were in the list")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
