"""List the agents' hand-backs in a session transcript: time, usage line and the start of each report.

usage: python3 -I handbacks.py <transcript.jsonl> [--full N] [--out DIR]

Reads the task notifications that carry a <result>. --full N prints the whole report number N. --out DIR writes
every report to DIR/handback-<n>.md (the report text only). Read-only on the transcript.
"""
import json
import re
import sys
from pathlib import Path


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
    path = argv[0]
    full = int(argv[argv.index("--full") + 1]) if "--full" in argv else None
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else None
    seen, n = set(), 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if "task-notification" not in line or "<result>" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:  # a cut line of a transcript still being written: skip it
                continue
            text = "\n".join(texts(record.get("message", {}).get("content")))
            for block in re.findall(r"<task-notification>(.*?)</task-notification>", text, re.S):
                result = re.search(r"<result>(.*?)</result>", block, re.S)
                if not result or result.group(1) in seen:
                    continue
                seen.add(result.group(1))
                n += 1
                usage = re.search(r"<usage>(.*?)</usage>", block, re.S)
                usage = " ".join(usage.group(1).split())[:200] if usage else "-"
                report = result.group(1).strip()
                if out:
                    out.mkdir(parents=True, exist_ok=True)
                    (out / f"handback-{n}.md").write_text(report + "\n", encoding="utf-8")
                if full is None:
                    print(f"===== {n} | {record.get('timestamp')} | usage: {usage}")
                    print("   " + " / ".join(report.splitlines())[:500])
                elif full == n:
                    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
