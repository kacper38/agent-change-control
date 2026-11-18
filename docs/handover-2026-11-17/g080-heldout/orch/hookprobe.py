#!/usr/bin/env python3
"""Feed synthetic PreToolUse events to a guard's hook and print the verdict of each.

usage: python3 -I hookprobe.py <guard.py> <cases.json> [cwd]

cases.json is a list of {"tool": "Bash"|"Edit"|"Write"|"Read"|"Agent", "command"|"path": "...", "note": "..."}.
Nothing in a case is ever run: the hook only reads the event. The decision log goes to a temporary folder.
"""
import json
import os
import subprocess
import sys
import tempfile


def main(argv):
    guard, cases_path = argv[0], argv[1]
    cwd = argv[2] if len(argv) > 2 else os.getcwd()
    with open(cases_path, encoding="utf-8") as fh:
        cases = json.load(fh)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, KZ_TELEMETRY_DIR=tmp)
        for case in cases:
            tool = case["tool"]
            if tool == "Bash":
                tool_input = {"command": case["command"]}
            elif tool in ("Agent", "Task"):
                tool_input = {"subagent_type": case.get("agent", "x"), "prompt": "x", "description": "x"}
            else:
                tool_input = {"file_path": case["path"]}
                if tool == "Write":
                    tool_input["content"] = case.get("content", "x")
                if tool == "Edit":
                    tool_input.update(old_string="a", new_string="b")
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": tool_input,
                "cwd": cwd,
                "session_id": "probe",
                "transcript_path": "probe",
            }
            proc = subprocess.run(
                [sys.executable, guard, "hook", "pre", "--wrapper", "claude"],
                input=json.dumps(event), capture_output=True, text=True, env=env, cwd=cwd, timeout=30,
            )
            verdict, reason = "silent", ""
            if proc.stdout.strip():
                out = json.loads(proc.stdout)
                verdict, reason = out["permissionDecision"], out["permissionDecisionReason"]
            shown = case.get("command") or case.get("path") or case.get("agent")
            print(f"{verdict:6} exit={proc.returncode} | {tool:5} | {shown}")
            if reason:
                print(f"       reason: {reason[:300]}")
            if proc.stderr.strip() and verdict != "deny":
                print(f"       stderr: {proc.stderr.strip()[:300]}")
            if case.get("note"):
                print(f"       note: {case['note']}")
        skipped = os.path.join(tmp, "decisions.jsonl")
        if os.path.exists(skipped):
            with open(skipped, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            n_skip = sum(1 for r in rows if r.get("verdict") == "skipped")
            print(f"-- decision log: {len(rows)} lines, {n_skip} skipped (rules_off or host-install knob)")
            for r in rows:
                if r.get("verdict") == "skipped":
                    print(f"   skipped: {r.get('rules')} tool={r.get('tool')}")


if __name__ == "__main__":
    main(sys.argv[1:])
