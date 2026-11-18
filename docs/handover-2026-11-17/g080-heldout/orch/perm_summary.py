"""Count how the harness recorded its permission decision for each tool's calls in a transcript.

Usage: python3 -I perm_summary.py <transcript.jsonl> [<prefix of tool names>]

One line per tool and kind of record: decision, source, reason type, rule source. A call without a
record is counted as "no record".
"""
import collections
import json
import sys


def main():
    path = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    tool_of = {}
    record_of = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool_of[block.get("id")] = block.get("name")
                elif block.get("type") == "tool_result" and "permissionDecision" in entry:
                    record_of[block.get("tool_use_id")] = entry.get("permissionDecision")
    tally = collections.Counter()
    for call, tool in tool_of.items():
        if not str(tool).startswith(prefix):
            continue
        record = record_of.get(call)
        if isinstance(record, dict):
            key = (tool, record.get("decision"), record.get("source"), record.get("reasonType"),
                   record.get("ruleSource") or "-")
        else:
            key = (tool, "no record", "-", "-", "-")
        tally[key] += 1
    for key in sorted(tally):
        print(f"{tally[key]:4d} | " + " | ".join(str(part) for part in key))


if __name__ == "__main__":
    main()
