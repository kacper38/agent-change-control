"""Rewrite every row of a rows file whose command is a JSON string with a character above U+FFFF, so that the
command is spelled with JSON escapes only: no character of a private plane stands raw in a file of the repository.

usage: python3 -I rows_escape.py <rows file>
Comment lines and every other row stay byte for byte as they are. Prints the number of rows it rewrote.
"""
import json
import sys


def main(argv):
    path = argv[0]
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    changed = 0
    for n, line in enumerate(lines):
        if line.startswith("#") or " | " not in line:
            continue
        head, command = line.rsplit(" | ", 1) if line.count(" | ") == 4 else (None, None)
        if head is None:
            parts = line.split(" | ", 4)
            head, command = " | ".join(parts[:4]), parts[4]
        if command.startswith('"') and any(ord(c) > 0xFFFF for c in command):
            lines[n] = head + " | " + json.dumps(json.loads(command), ensure_ascii=True)
            changed += 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"rows rewritten with escapes: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
