"""Write a copy of the guard with one planted break each, for probing a mutation that no test caught.

usage: python3 -I mutant.py <guard.py> <mutations.json> <out dir> <id> [<id> ...]

Writes <out dir>/guard-<id>.py for each id; `old` must stand in the guard exactly once. The copies are scratch
files: nothing in a checkout is touched.
"""
import json
import sys
from pathlib import Path


def main(argv):
    guard, spec, out, ids = argv[0], argv[1], Path(argv[2]), argv[3:]
    text = Path(guard).read_text(encoding="utf-8")
    by_id = {m["id"]: m for m in json.loads(Path(spec).read_text(encoding="utf-8"))}
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for ident in ids:
        m = by_id.get(ident)
        if m is None or text.count(m["old"]) != 1:
            bad += 1
            print(f"not written: {ident}")
            continue
        (out / f"guard-{ident}.py").write_text(text.replace(m["old"], m["new"]), encoding="utf-8")
        print(f"guard-{ident}.py | {m['what']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
