"""Join the guard's decision log with the session transcripts: which call touched which file, and who made it.

  export_decisions.py <decisions.jsonl> <transcript.jsonl> <subagents-dir> [--dialog]

Reads only. Prints one tab-separated line per decision-log line that names the rule `guard-config`:
  ts, event, tool, outcome of the rule, actor, path
The path is cut to the repository (the build worktree), or marked as the handover checkout or the
session's scratch folder, so that no absolute path of the machine is printed. The three folders come
from the environment: CUT_WORKTREE, CUT_CHECKOUT, CUT_SCRATCH. A path under none of them is printed whole.
With --dialog it prints the dialogs of the session (question, options, answer) instead.
"""

import json
import os
import sys

log_path, transcript, sub_dir = sys.argv[1:4]
dialog = "--dialog" in sys.argv[4:]


def lines(path):
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue


def blocks(entry):
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return content if isinstance(content, list) else []


sources = [("session", transcript)]
for name in sorted(os.listdir(sub_dir)):
    if name.endswith(".jsonl"):
        meta_path = os.path.join(sub_dir, name[: -len(".jsonl")] + ".meta.json")
        kind = "agent"
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            kind = str(meta.get("agentType") or meta.get("subagent_type") or meta.get("agent") or "agent")
        sources.append((kind, os.path.join(sub_dir, name)))

calls = {}
uses = {}
results = {}
for actor, path in sources:
    for entry in lines(path):
        for block in blocks(entry):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls[block.get("id")] = (actor, block.get("name"), block.get("input") or {}, entry.get("timestamp"))
                if block.get("name") == "AskUserQuestion":
                    uses[block.get("id")] = (block.get("input") or {}, entry.get("timestamp"))
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in uses:
                results[block.get("tool_use_id")] = (block.get("content"), entry.get("timestamp"),
                                                     entry.get("toolUseResult"))

if dialog:
    for call_id, (inp, asked_at) in uses.items():
        print("ASKED", asked_at)
        for q in inp.get("questions", []):
            print("  QUESTION:", q.get("question"))
            for opt in q.get("options", []):
                print("    OPTION:", opt.get("label"), "|", opt.get("description"))
        got = results.get(call_id)
        if got:
            content, answered_at, structured = got
            print("ANSWERED", answered_at)
            print("  RESULT:", json.dumps(content, ensure_ascii=False)[:3000])
            if structured:
                print("  STRUCTURED:", json.dumps(structured, ensure_ascii=False)[:3000])
        print()
    sys.exit(0)


CUTS = [  # the longest prefix first: the build worktree lies inside the handover checkout
    (os.environ.get("CUT_WORKTREE", ""), ""),
    (os.environ.get("CUT_CHECKOUT", ""), "handover-checkout:"),
    (os.environ.get("CUT_SCRATCH", ""), "scratch:"),
]


def cut(path):
    path = str(path or "")
    for prefix, label in CUTS:
        if prefix and path.startswith(prefix.rstrip("/") + "/"):
            return label + path[len(prefix.rstrip("/")) + 1:]
    return path


missing = 0
print("\t".join(["ts", "event", "tool", "guard-config", "who", "file"]))
for row in lines(log_path):
    rules = row.get("rules") or {}
    if "guard-config" not in rules:
        continue
    actor, name, inp, _ts = calls.get(row.get("call"), ("?", "?", {}, None))
    if actor == "?":
        missing += 1
    print("\t".join([row.get("ts", ""), row.get("event", ""), row.get("tool", ""), rules["guard-config"], actor,
                     cut(inp.get("file_path"))]))
print(f"# calls not found in a transcript: {missing}", file=sys.stderr)
