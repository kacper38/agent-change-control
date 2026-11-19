"""Save the continuation summaries of a session transcript, one file each.

usage: python3 -I summaries.py <transcript.jsonl> <out dir>

A summary is a user-role record whose text starts with the sentence the harness puts in front of it. Writes
<out dir>/summary-<n>.md and lists each with its time and length. Read-only on the transcript.
"""
import json
import sys
from pathlib import Path

MARK = "This session is being continued from a previous conversation"


def texts(node):
    """Every string inside a message content, whatever its nesting."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for part in node:
            yield from texts(part)
    elif isinstance(node, dict):
        for key in ("text", "content"):
            if key in node:
                yield from texts(node[key])


def main(argv):
    path, out = argv[0], Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    seen, n = set(), 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if MARK not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:  # a cut line of a transcript still being written: skip it
                continue
            if record.get("type") != "user":
                continue
            text = "\n".join(texts(record.get("message", {}).get("content")))
            at = text.find(MARK)
            if at < 0 or at > 2000:
                continue
            text = text[at:]
            if text[:3000] in seen:
                continue
            seen.add(text[:3000])
            n += 1
            (out / f"summary-{n}.md").write_text(text + "\n", encoding="utf-8")
            print(f"summary-{n}.md | {record.get('timestamp')} | {len(text)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
