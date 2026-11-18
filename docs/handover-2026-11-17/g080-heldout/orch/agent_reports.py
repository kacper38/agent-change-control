"""Write each report an agent handed back to its own file, from the agent's transcript.

  agent_reports.py <agent transcript .jsonl> <out dir> <name prefix> [prefix=replacement ...]

A report is the `message` of a SubagentHandback call, the tool an agent of this harness ends a run with.
Each `prefix=replacement` cuts a machine path out of the text. Reads only the transcript.
"""

import json
import os
import sys

transcript, out_dir, name = sys.argv[1:4]
cuts = [arg.split("=", 1) for arg in sys.argv[4:]]

reports = []
with open(transcript, encoding="utf-8") as fh:
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
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "SubagentHandback":
                reports.append((entry.get("timestamp"), str((block.get("input") or {}).get("message") or "")))

os.makedirs(out_dir, exist_ok=True)
for number, (when, text) in enumerate(reports, 1):
    for prefix, replacement in cuts:
        text = text.replace(prefix, replacement)
    path = os.path.join(out_dir, f"{name}-{number}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
    print(f"{path}: handed back {when}, {len(text)} characters")
