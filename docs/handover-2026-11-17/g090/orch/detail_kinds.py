"""Group the changed cells of the close-out replay by rule, direction and the guards' own reasons.

usage: python3 -I detail_kinds.py <detail.json> [--lines]

Reads the file closeout_detail.py writes. Prints counts and the guards' reason texts only; with --lines also,
per changed cell, the one line of the call that holds the word the reason names (cut to 150 characters), so a
cell can be put to a kind without reading the whole call. The output is for the local session: nothing of it
goes into the repository but the counts and the kinds.
"""
import collections
import json
import re
import sys

RANK = {"silent": 0, "ask": 1, "deny": 2}


def named(reason):
    """Words the reason puts between backquotes: the tool, the path or the verb it speaks about."""
    return re.findall(r"`([^`]{1,60})`", reason or "")


def main(argv):
    with open(argv[0], encoding="utf-8") as handle:
        data = json.load(handle)
    lines = "--lines" in argv
    print(f"transcripts {data['transcripts']} | calls {data['calls']} | distinct {data['distinct']}")
    for boundary, part in data["boundaries"].items():
        changed = part["changed"]
        print(f"\n== boundary {boundary}: {part['cells']} cells, {len(changed)} changed")
        groups = collections.defaultdict(list)
        for index, cell in enumerate(changed):
            direction = "weaker" if RANK[cell["new"]] < RANK[cell["old"]] else "stronger"
            groups[(direction, cell["rule"], cell["old"], cell["new"])].append((index, cell))
        for key in sorted(groups):
            cells = groups[key]
            occurrences = sum(cell["count"] for _, cell in cells)
            print(f"-- {key[0]} | {key[1]} {key[2]}->{key[3]} | distinct cells {len(cells)} | occurrences {occurrences}")
            side = "why_old" if key[0] == "weaker" else "why_new"
            reasons = collections.Counter()
            for _, cell in cells:
                reasons[re.sub(r"\s+", " ", cell[side])[:170]] += cell["count"]
            for reason, count in reasons.most_common(12):
                print(f"     {count:3} x {side}: {reason}")
            if not lines:
                continue
            for index, cell in cells:
                try:
                    call = json.loads('"' + cell["call"] + '"')
                except ValueError:
                    call = cell["call"]
                words = named(cell[side])
                picked = [ln.strip() for ln in str(call).splitlines() if any(w and w in ln for w in words)]
                if not picked:
                    picked = [ln.strip() for ln in str(call).splitlines()[:1]]
                print(f"     [{index}] {cell['tool']} x{cell['count']} call length {len(cell['call'])} | lines {len(str(call).splitlines())}")
                for ln in picked[:3]:
                    print(f"          {ln[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
