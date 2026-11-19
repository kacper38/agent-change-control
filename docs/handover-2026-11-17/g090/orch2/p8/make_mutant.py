"""Write a guard file with one planted break of a list applied.

usage: python3 -I make_mutant.py <guard.py> <mutations.json> <id> <out.py>

The break's `old` must stand exactly once in the guard file. Nothing is run.
"""
import json
import sys


def main(argv):
    guard, spec, ident, out = argv
    with open(guard, encoding="utf-8") as fh:
        text = fh.read()
    with open(spec, encoding="utf-8") as fh:
        m = next(m for m in json.load(fh) if m["id"] == ident)
    if text.count(m["old"]) != 1:
        sys.exit(f"{ident}: old text stands {text.count(m['old'])} times")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text.replace(m["old"], m["new"]))
    print(f"{ident}: {m['what']} -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(sys.argv[1:])
