"""For the lines of the guard's decision log that belong to one session and name a given rule: which tool call
of the session or of one of its agents stood at that time?

usage: python3 -I declog_calls.py <decisions.jsonl> <session transcript.jsonl> <rule> [<rule> ...] [--width N]

The log of guard 0.6.1 holds no call id, so the join is by time: for each log line, the Bash calls whose record
is at most three seconds older, in the session's transcript and in the transcripts of its agents. Printed per
log line: time, rule and answer, who (main or the agent's id), and the first N characters of the command, with
the home folder and the scratch folder cut. Read-only.
"""
import datetime as dt
import glob
import json
import os
import sys


def stamp(text):
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def calls_of(path, who):
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"tool_use"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            when = stamp(str(rec.get("timestamp", "")))
            content = (rec.get("message") or {}).get("content")
            if when is None or not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash":
                    out.append((when, who, str((part.get("input") or {}).get("command", ""))))
    return out


def main(argv):
    width = 150
    if "--width" in argv:
        width = int(argv[argv.index("--width") + 1])
        argv = [a for k, a in enumerate(argv) if a != "--width" and argv[k - 1] != "--width"]
    window = 3
    if "--window" in argv:
        window = int(argv[argv.index("--window") + 1])
        argv = [a for k, a in enumerate(argv) if a != "--window" and argv[k - 1] != "--window"]
    log, transcript, rules = argv[0], argv[1], set(argv[2:])
    session = os.path.basename(transcript)[: -len(".jsonl")]
    calls = calls_of(transcript, "main")
    for path in sorted(glob.glob(os.path.join(os.path.dirname(transcript), session, "subagents", "**", "*.jsonl"),
                                 recursive=True)):
        calls.extend(calls_of(path, os.path.basename(path)[: -len(".jsonl")].replace("agent-", "")[:8]))
    home = os.path.expanduser("~")
    with open(log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if session not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            named = row.get("rules") or {}
            if row.get("session") != session or not (rules & set(named)):
                continue
            when = stamp(str(row.get("ts", "")))
            near = sorted((c for c in calls if when and abs((when - c[0]).total_seconds()) <= window),
                          key=lambda c: abs((when - c[0]).total_seconds()), reverse=True)
            answer = ",".join(f"{r}={a}" for r, a in sorted(named.items()))
            if not near:
                print(f"{row.get('ts')} | {answer} | no Bash call found within three seconds")
            for _when, who, command in near[-1:]:
                shown = command.replace(home, "~").replace("\n", " ⏎ ")
                shown = shown.replace("<TMP>/-Users-" + os.path.basename(home) + "-Developer-agent-change-control/" + session + "/scratchpad", "<PAD>")
                print(f"{row.get('ts')} | {answer} | {who} | {shown[:width]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
