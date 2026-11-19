"""Cut every line that holds a given text out of the given files, in place.

usage: python3 -I drop_lines.py <text> <file> [<file> ...]

Prints the number of lines cut per file, never a line.
"""
import sys


def main(argv):
    text, paths = argv[0], argv[1:]
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines(keepends=True)
        kept = [ln for ln in lines if text not in ln]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(kept))
        print(f"{path.rsplit('/', 1)[-1]}: cut {len(lines) - len(kept)} of {len(lines)} lines")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
