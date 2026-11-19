"""Count the lines of the guard's decision log that belong to one Claude Code session, by rule, verdict and tool.

usage: python3 -I declog.py <decisions.jsonl> <session id> [--tsv OUT]

The log holds lines of every repository that wires the guard; only the lines whose `session` field is the given
id are read further, and nothing of the other lines is printed. The log of guard 0.6.1 (the guard the main
checkout runs) has the fields event, harness, rules, session, tool, ts, verdict; `rules` maps a rule to its
answer. --tsv writes time, tool, verdict and the rules for the matching lines: no command text and no path,
the log holds neither.
"""
import collections
import json
import sys


def main(argv):
    log, session = argv[0], argv[1]
    tsv = argv[argv.index("--tsv") + 1] if "--tsv" in argv else None
    total = 0
    by = collections.Counter()
    rows = []
    with open(log, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            total += 1
            if session not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("session") != session:
                continue
            rules = row.get("rules") or {}
            named = ",".join(f"{rule}={answer}" for rule, answer in sorted(rules.items())) if isinstance(rules, dict) else str(rules)
            by[(named, row.get("verdict", "?"), row.get("tool", "?"))] += 1
            rows.append((row.get("ts", ""), row.get("tool", ""), row.get("verdict", ""), named, row.get("harness", "")))
    print(f"log lines {total} | of this session {len(rows)}"
          + (f" | first {rows[0][0]} | last {rows[-1][0]}" if rows else ""))
    for key, count in sorted(by.items()):
        print(f"  {count:4} | {key[0]} | verdict {key[1]} | tool {key[2]}")
    if tsv:
        with open(tsv, "w", encoding="utf-8") as out:
            out.write("time\ttool\tverdict\trules\tharness\n")
            for row in rows:
                out.write("\t".join(str(c) for c in row) + "\n")
        print(f"written: {tsv} ({len(rows)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
