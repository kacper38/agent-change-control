"""Which commands of a weaker_cells.py log are no command of a rows file?

usage: python3 -I cells_outside.py <weaker_cells log> <rows file>

Reads the lines `UNEXPLAINED [context] rule: a -> b | <command as a JSON string>` and prints the distinct
commands with their turn and the number of cells, marking with `+` those that no row of the rows file holds.
Nothing is run.
"""
import collections
import json
import sys


def main(argv):
    log, rows_file = argv
    with open(rows_file, encoding="utf-8") as fh:
        rows = set()
        for line in fh:
            if line.strip() and not line.startswith("#"):
                command = line.rstrip("\n").split(" | ", 4)[4]
                rows.add(json.loads(command) if command.startswith('"') else command)
    cells = collections.Counter()
    with open(log, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("UNEXPLAINED"):
                head, _, command = line.rstrip("\n").partition(" | ")
                cells[(json.loads(command), head.split(": ", 1)[1])] += 1
    outside = 0
    for (command, turn), n in sorted(cells.items()):
        mark = " " if command in rows else "+"
        outside += mark == "+"
        print(f"{mark} {n} {turn} | {command}")
    print(f"distinct commands {len(cells)} | not in the rows file {outside}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
