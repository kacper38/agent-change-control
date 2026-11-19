"""Print the Bash commands of a session transcript that hold one of the given words.

usage: python3 -I find_cmds.py <transcript.jsonl> <word> [<word> ...]

Read-only. Each match is printed once, cut to 900 characters, with the record's time.
"""
import json
import sys


def main(argv):
    path, words = argv[0], argv[1:]
    seen = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash":
                    cmd = (part.get("input") or {}).get("command", "")
                    if any(w in cmd for w in words) and cmd not in seen:
                        seen.add(cmd)
                        print(f"--- {rec.get('timestamp', '')}\n{cmd[:900]}\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
