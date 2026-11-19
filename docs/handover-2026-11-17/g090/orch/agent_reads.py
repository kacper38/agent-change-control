"""Count what an agent's tool calls touched: did the engineer (or reviewer) read a folder it was told to leave?

usage: python3 -I agent_reads.py <agent transcript.jsonl> <needle> [<needle> ...]

Read-only. Looks only at the inputs of the agent's own tool calls (not at the prompts it was given, where the
folder names stand as "do not read"). Prints per needle the number of tool calls that name it, and for each hit
the tool, the time and the first 220 characters of the input. Exit 1 when a needle was found.
"""
import json
import sys
from collections import Counter


def main(argv):
    path, needles = argv[0], argv[1:]
    calls = Counter()
    hits = []
    rows = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            rows += 1
            if row.get("type") != "assistant":
                continue
            for block in (row.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                calls[block.get("name", "?")] += 1
                text = json.dumps(block.get("input", {}), ensure_ascii=False)
                for needle in needles:
                    if needle in text:
                        hits.append((needle, block.get("name", "?"), row.get("timestamp", "")[:19], text[:220]))
    print(f"transcript rows {rows} | tool calls {sum(calls.values())} | " +
          ", ".join(f"{name} {count}" for name, count in calls.most_common()))
    for needle in needles:
        found = [hit for hit in hits if hit[0] == needle]
        print(f"needle {needle!r}: {len(found)} tool calls")
        for _, name, stamp, text in found[:12]:
            print(f"   {stamp} {name}: {text}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
