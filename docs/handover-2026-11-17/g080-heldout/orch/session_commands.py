"""Write every shell command of the given transcripts to a list file, one JSON string per line, each once.

  session_commands.py <out file> <transcript .jsonl> [<transcript .jsonl> ...]

The list is input for weaker.py: the commands are data there, handed to rule functions and never run.
Reads only the transcripts. Prints how many commands were found per transcript and how many are distinct.
"""

import json
import os
import sys

out_path = sys.argv[1]
seen = {}
for path in sys.argv[2:]:
    count = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            content = message.get("content")
            if entry.get("type") != "assistant" or not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                    command = (block.get("input") or {}).get("command")
                    if isinstance(command, str) and command.strip():
                        count += 1
                        seen.setdefault(command, None)
    print(f"{os.path.basename(path)[:30]}: {count} shell commands")

with open(out_path, "w", encoding="utf-8") as fh:
    for command in seen:
        fh.write(json.dumps(command) + "\n")
print(f"distinct: {len(seen)}")
