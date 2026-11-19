"""Print the last texts of an agent's transcript, and the input of its last hand-back call.

usage: python3 -I agent_tail.py <agent transcript.jsonl> [--texts N] [--max CHARS] [--tools]

Reads the JSON lines of a Claude Code agent transcript. Prints the last N assistant text blocks (default 3),
each cut to CHARS characters (default 6000), and the whole input of the last tool call whose name contains
"Handback". With --tools it prints one line per tool call instead: index, tool, first 160 characters of its input.
"""
import json
import sys


def blocks(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            message = row.get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                yield number, row.get("type"), {"type": "text", "text": content}, row.get("timestamp", "")
                continue
            for block in content or []:
                if isinstance(block, dict):
                    yield number, row.get("type"), block, row.get("timestamp", "")


def main(argv):
    path = argv[0]
    texts = int(argv[argv.index("--texts") + 1]) if "--texts" in argv else 3
    limit = int(argv[argv.index("--max") + 1]) if "--max" in argv else 6000
    found = []
    handback = None
    calls = []
    for number, kind, block, stamp in blocks(path):
        if kind == "assistant" and block.get("type") == "text" and block.get("text", "").strip():
            found.append((number, stamp, block["text"]))
        if kind == "assistant" and block.get("type") == "tool_use":
            calls.append((number, stamp, block.get("name", "?"), json.dumps(block.get("input"), ensure_ascii=False)))
            if "Handback" in block.get("name", ""):
                handback = (number, stamp, block.get("input"))
    if "--tools" in argv:
        for number, stamp, name, text in calls:
            print(f"{number:4} | {stamp[11:19]} | {name} | {text[:160]}")
        print(f"tool calls: {len(calls)}")
        return 0
    print(f"assistant texts: {len(found)} | tool calls: {len(calls)}")
    for number, stamp, text in found[-texts:]:
        print(f"--- line {number} | {stamp} | {len(text)} characters")
        print(text[:limit])
    if handback:
        number, stamp, data = handback
        print(f"=== hand-back call, line {number} | {stamp}")
        if isinstance(data, dict):
            for key, value in data.items():
                print(f"[{key}]")
                print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1))
        else:
            print(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
