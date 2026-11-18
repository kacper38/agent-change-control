#!/usr/bin/env python3
"""Read a held-out rows file and the log expect.py wrote for it (with --red) and print, per id, which rows hold
and which are red, in the three groupings that need a look before the build.

usage: python3 -I heldout_report.py <held-out rows file> <expect log>
"""
import json
import sys


def main(argv):
    rows = []
    with open(argv[1], encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if ln.strip() and not ln.startswith("#"):
                parts = ln.split(" | ", 4)
                rows.append((parts[0].strip(), parts[2].strip(), parts[3].strip(), parts[4]))
    red = {}
    with open(argv[2], encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith("RED "):
                # the first " | " ends the verdict part; the command (a JSON string) may hold more of them
                head, _sep, tail = ln.rstrip("\n").partition(" | ")
                red[(head.split()[1], tail)] = head
    counts = {}
    for rid, _rule, _expected, command in rows:
        key = (rid, "red" if (rid, json.dumps(command)[:110]) in red else "hold")
        counts[key] = counts.get(key, 0) + 1
    print("per id: " + ", ".join(f"{rid} {state} {n}" for (rid, state), n in sorted(counts.items())))
    for title, want_id, want_state in (
        ("HS rows that are red (the row is wrong about today, or a finding)", "HS", "red"),
        ("HR rows that hold already", "HR", "hold"),
        ("HO rows that answer as written already", "HO", "hold"),
    ):
        print(f"== {title}")
        for rid, rule, expected, command in rows:
            state = "red" if (rid, json.dumps(command)[:110]) in red else "hold"
            if rid == want_id and state == want_state:
                got = red.get((rid, json.dumps(command)[:110]), "")
                got = got.split("got ", 1)[1] if "got " in got else ""
                print(f"   {rule} expected {expected}{' | got ' + got if got else ''} | {command[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
