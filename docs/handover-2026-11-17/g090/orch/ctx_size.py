"""Print the size of an agent's context at its last requests, from the usage fields of its transcript.

usage: python3 -I ctx_size.py <agent transcript.jsonl> [N]

Read-only. For the last N assistant messages (default 3) that carry a usage block: the time, the input tokens
(fresh, cache write, cache read) and their sum, which is the size of the context that request was sent with.
"""
import json
import sys


def main(argv):
    path = argv[0]
    last = int(argv[1]) if len(argv) > 1 else 3
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            usage = (row.get("message") or {}).get("usage") if isinstance(row.get("message"), dict) else None
            if row.get("type") == "assistant" and usage:
                fresh = usage.get("input_tokens") or 0
                write = usage.get("cache_creation_input_tokens") or 0
                read = usage.get("cache_read_input_tokens") or 0
                rows.append((row.get("timestamp", ""), fresh, write, read, usage.get("output_tokens") or 0))
    for stamp, fresh, write, read, out in rows[-last:]:
        print(f"{stamp} | input {fresh} + cache write {write} + cache read {read} = {fresh + write + read} | output {out}")
    print(f"assistant messages with usage: {len(rows)} | largest context: {max((r[1] + r[2] + r[3] for r in rows), default=0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
