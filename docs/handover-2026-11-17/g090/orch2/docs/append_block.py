"""Append one block to the end of a decision record.

usage: python3 -I append_block.py <DECISIONS.md> <block file> [--check]

The block must start with `## ` and hold no `@@NAME@@` placeholder. It is written behind the last line of the
record with one empty line between, and the file ends with one line break. A block whose heading the record
already holds is refused. With --check nothing is written.
"""
import re
import sys


def main(argv):
    record, block_path = argv[0], argv[1]
    with open(block_path, encoding="utf-8") as fh:
        block = fh.read().strip("\n")
    if not block.startswith("## "):
        sys.exit("the block does not start with a heading")
    left = sorted(set(re.findall(r"@@([A-Z0-9]+)@@", block)))
    if left:
        sys.exit(f"placeholders left: {left}")
    with open(record, encoding="utf-8") as fh:
        text = fh.read()
    heading = block.split("\n", 1)[0]
    if heading in text:
        sys.exit("the record already holds this heading")
    new = text.rstrip("\n") + "\n\n" + block + "\n"
    print(f"record {len(text)} chars -> {len(new)} | block {len(block)} chars, {block.count(chr(10)) + 1} lines | "
          f"heading: {heading[:90]}")
    if "--check" not in argv:
        with open(record, "w", encoding="utf-8") as fh:
            fh.write(new)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
