"""Which lines of a rows file hold a character outside ASCII, and what does a JSON-string row decode to?

usage: python3 -I rows_ascii.py <rows file>
Prints per line with such a character its number, whether it is a comment, and the code points; then, for every
row whose command is a JSON string with a `\\u` escape, the code points above U+FFFF it decodes to.
"""
import json
import sys


def main(argv):
    with open(argv[0], encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    for n, line in enumerate(lines, 1):
        odd = sorted({f"U+{ord(c):04X}" for c in line if ord(c) > 126})
        if odd:
            print(f"line {n} | {'comment' if line.startswith('#') else 'ROW'} | {' '.join(odd)}")
        if not line.startswith("#") and "\\u" in line:
            command = line.split(" | ", 4)[4]
            decoded = json.loads(command)
            high = " ".join(f"U+{ord(c):05X}" for c in decoded if ord(c) > 0xFFFF)
            print(f"line {n} | JSON row decodes to {len(decoded)} characters, above U+FFFF: {high}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
