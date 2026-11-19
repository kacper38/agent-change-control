"""Print the weaker cells of one rule from the replay's detail file, for reading on this machine only.

usage: python3 -I replay_show.py <detail.json> <boundary> <rule> [<width>]

The output holds real command text of recorded work: it is for the session's eyes and goes into no file of the
repository, no issue and no pull request.
"""
import json
import sys

RANK = {"silent": 0, None: 0, "": 0, "allow": 0, "ask": 1, "deny": 2}


def main(argv):
    with open(argv[0], encoding="utf-8") as fh:
        doc = json.load(fh)
    width = int(argv[3]) if len(argv) > 3 else 300
    for c in doc["boundaries"][argv[1]]["changed"]:
        if c["rule"] != argv[2] or RANK.get(c["new"], 0) >= RANK.get(c["old"], 0):
            continue
        call = " ".join(c["call"].split())
        print(f"[{c['count']}x {c['old']}>{c['new'] or 'silent'}] why_old: {c['why_old'][:160]}")
        print("   " + call[:width] + (" …" if len(call) > width else ""))


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1:])
