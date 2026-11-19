"""Save the reports agents handed back to the session, from a session transcript.

usage: python3 -I handback_msgs.py <transcript.jsonl> <out dir>

A hand-back is queued as a `queue-operation` record whose content starts with the sender's id and the words
"[Subagent hand-back]". The first record of each (sender, text) is written to <out dir>/hb-<n>-<sender>.md with
the report text only (the harness's frame lines around it are cut), and listed with its time and length.
Read-only on the transcript.
"""
import json
import re
import sys
from pathlib import Path


def main(argv):
    path, out = argv[0], Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    seen, n = set(), 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if "[Subagent hand-back]" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:  # a cut line of a transcript still being written: skip it
                continue
            content = record.get("content")
            if record.get("type") != "queue-operation" or not isinstance(content, str):
                continue
            sender = re.search(r'<agent-message from="([a-f0-9]+)">', content)
            body = re.search(r"<agent-message[^>]*>\n?(.*?)</agent-message>", content, re.S)
            if not sender or not body:
                continue
            text = body.group(1).strip()
            # the frame sentence of the harness ends at the first blank line
            report = text.split("\n\n", 1)[1].strip() if "\n\n" in text else text
            if (sender.group(1), report) in seen:
                continue
            seen.add((sender.group(1), report))
            n += 1
            name = f"hb-{n}-{sender.group(1)[:8]}.md"
            (out / name).write_text(report + "\n", encoding="utf-8")
            print(f"{name} | {record.get('timestamp')} | {len(report)} chars | {report.splitlines()[0][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
