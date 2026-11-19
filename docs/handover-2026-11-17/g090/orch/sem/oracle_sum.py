"""Add up the logs the processes of oracle-head.sh wrote.

usage: python3 -I oracle_sum.py <folder with s<i>.log and s<i>.json> <processes>
Prints the product size, the lines judged, the silent lines, the lines run by the shells, the holes and the
crashes over all processes, and up to ten holes. Exit 1 when a log is not complete or a hole or crash is there.
"""
import json
import os
import re
import sys


def main(argv):
    folder, n = argv[0], int(argv[1])
    judged = silent = ran = holes = crashes = 0
    product = None
    incomplete = []
    shown = []
    for i in range(n):
        with open(os.path.join(folder, f"s{i}.log"), encoding="utf-8") as fh:
            text = fh.read()
        size = re.search(r"lines in the product: (\d+)", text)
        done = re.search(r"lines judged (\d+)", text)
        line = re.search(r"silent (\d+) \| run by the shells (\d+) \| HOLES[^0-9]*(\d+) \| crashes (\d+)", text)
        if not (size and done and line):
            incomplete.append(i)
            continue
        product = int(size.group(1))
        judged += int(done.group(1))
        silent += int(line.group(1))
        ran += int(line.group(2))
        holes += int(line.group(3))
        crashes += int(line.group(4))
        with open(os.path.join(folder, f"s{i}.json"), encoding="utf-8") as fh:
            for found in json.load(fh).values():
                shown.extend(found)
    print(f"processes {n} | incomplete {incomplete or 'none'} | lines in the product {product} | lines judged {judged}"
          f" | silent {silent} | run by the shells {ran} | HOLES {holes} | crashes {crashes}")
    for h in shown[:10]:
        print(f"   zsh {h['shells']['zsh']:7} bash {h['shells']['bash']:7} | {json.dumps(h['line'])}")
    return 1 if (incomplete or holes or crashes or judged != product) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
