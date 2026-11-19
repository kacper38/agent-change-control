"""Print what the person typed in a session transcript: time and text of each user message that is no tool result.

usage: python3 -I user_words.py <transcript.jsonl> [<from HH:MM> [<to HH:MM>]]

Read-only. Lines the harness adds (system reminders, task notifications, command output) are left out as far as
their markers show them. Times are the transcript's own (UTC).
"""
import json
import sys

SKIP = ("<system-reminder>", "<task-notification>", "<local-command", "<command-name>", "[SYSTEM NOTIFICATION",
        "<cross-session-message", "Another Claude session sent")


def texts(content):
    if isinstance(content, str):
        return [content]
    out = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(block.get("text", ""))
    return out


def main(argv):
    lo = argv[1] if len(argv) > 1 else "00:00"
    hi = argv[2] if len(argv) > 2 else "23:59"
    with open(argv[0], encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "user" or row.get("isSidechain"):
                continue
            stamp = row.get("timestamp", "")
            clock = stamp[11:16]
            if not (lo <= clock <= hi):
                continue
            for text in texts((row.get("message") or {}).get("content")):
                text = text.strip()
                if not text or any(text.startswith(mark) for mark in SKIP):
                    continue
                print(f"{stamp[:19]} | {text[:400]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
