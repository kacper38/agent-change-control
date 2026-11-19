"""Write the given text files into one, in the order given.

usage: python3 -I join.py <out> <file> [<file> ...]

Every file is read as UTF-8 and ends with a line break in the output. Nothing else changes.
"""
import sys


def main(argv):
    out, parts = argv[0], argv[1:]
    chunks = []
    for path in parts:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        chunks.append(text if text.endswith("\n") or not text else text + "\n")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("".join(chunks))
    print(f"{out}: {len(parts)} files, {sum(c.count(chr(10)) for c in chunks)} lines")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
