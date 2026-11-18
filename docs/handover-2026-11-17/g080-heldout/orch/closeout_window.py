#!/usr/bin/env python3
"""The time span the replayed transcripts really cover: first and last day with a wired tool call, days with calls.

usage: python3 -I closeout_window.py <g070 dir> <days>
Reads transcripts only; prints dates and counts, no call text and no path.
"""
import collections
import json
import os
import sys


def main(argv):
    kit, days = argv[0], int(argv[1])
    sys.path.insert(0, kit)
    import replay
    root = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    paths = replay.transcripts(root, days)
    per_day = collections.Counter()
    projects = set()
    undated = 0
    for path in paths:
        projects.add(os.path.relpath(path, root).split(os.sep)[0])
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"tool_use"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if entry.get("type") != "assistant" or not isinstance(content, list):
                    continue
                wired = sum(1 for block in content if isinstance(block, dict) and block.get("type") == "tool_use"
                            and block.get("name") in replay.WIRED and isinstance(block.get("input"), dict))
                if not wired:
                    continue
                stamp = str(entry.get("timestamp") or "")[:10]
                if len(stamp) == 10:
                    per_day[stamp] += wired
                else:
                    undated += wired
    days_seen = sorted(per_day)
    print(f"transcripts {len(paths)} in {len(projects)} project folders")
    print(f"wired tool calls {sum(per_day.values())} dated, {undated} undated")
    print(f"first day {days_seen[0]} | last day {days_seen[-1]} | days with calls {len(days_seen)}")
    by_week = collections.Counter()
    for day, count in per_day.items():
        by_week[day[:7]] += count
    print("calls per month: " + ", ".join(f"{month} {count}" for month, count in sorted(by_week.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
