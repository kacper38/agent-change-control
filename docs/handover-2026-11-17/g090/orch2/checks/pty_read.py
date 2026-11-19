"""Read a log of pty_probe.py and count what matters.

usage: python3 -I pty_read.py <log> <index of the guard under review, from 0> [--list]

Per row: `id expectation letters pipe:XX pty:XX | command`. Counts the rows where the guard under review does not
answer as the row expects, the rows where it is silent and a shell showed the marker (the one outcome that must
not be), the rows where it asks and a shell showed it, and the rows where it asks and no shell did. A run that
was cut (`t`) is counted apart. --list prints the rows of the first two counts and the rows where the letters of
the guards differ.
"""
import collections
import re
import sys

ROW = re.compile(r"^(\S+)\s+(\S+)\s+([sad!?]+)\s+pipe:(\S\S)\s+pty:(\S\S)\s+\|\s(.*)$")


def main(argv):
    path, at = argv[0], int(argv[1])
    show = "--list" in argv
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if m:
                rows.append(m.groups())
    want = {"ask": "a", "silent": "s", "deny": "d"}
    wrong, leak, ask_print, ask_quiet, silent_quiet, cut = [], [], 0, 0, 0, 0
    by_id = collections.Counter()
    for rid, exp, letters, pipe, pty_, command in rows:
        got = letters[at]
        shown = any(c in "ZB" for c in pipe + pty_)
        if "t" in pipe + pty_:
            cut += 1
        if want.get(exp) != got:
            wrong.append((rid, exp, letters, pipe, pty_, command))
        if got == "s" and shown:
            leak.append((rid, exp, letters, pipe, pty_, command))
        elif got == "s":
            silent_quiet += 1
        elif shown:
            ask_print += 1
        else:
            ask_quiet += 1
        by_id[(rid, got, "prints" if shown else "quiet")] += 1
    print(f"rows {len(rows)} | guard {at} answers as expected {len(rows) - len(wrong)} | not {len(wrong)}")
    print(f"silent and a shell shows the marker: {len(leak)} | silent and none shows it: {silent_quiet} | "
          f"asks and a shell shows it: {ask_print} | asks and none shows it: {ask_quiet} | rows with a cut run: {cut}")
    for key in sorted(by_id):
        print(f"  {key[0]:<5} {key[1]} {key[2]:<6} {by_id[key]}")
    letters_seen = collections.Counter(r[2] for r in rows)
    print("letters per guard: " + ", ".join(f"{k} {v}" for k, v in sorted(letters_seen.items())))
    if show:
        for name, bag in (("NOT AS EXPECTED", wrong), ("SILENT AND SHOWN", leak)):
            for r in bag:
                print(f"{name} | {r[0]} {r[1]} {r[2]} pipe:{r[3]} pty:{r[4]} | {r[5][:150]}")
    return 1 if wrong or leak else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
