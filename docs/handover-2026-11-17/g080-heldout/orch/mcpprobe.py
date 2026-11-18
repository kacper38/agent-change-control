#!/usr/bin/env python3
"""Feed synthetic PreToolUse events of any tool to a guard's hook and print the verdict of each.

usage: python3 -I mcpprobe.py <guard.py> <cases.json> [cwd]

cases.json is a list of {"tool": "<tool name>", "input": {...}, "twin": "<the same act in a shell>"}.
Nothing in a case is ever run or sent: the hook only reads the event. The decision log goes to a
temporary folder. Beside the verdict the line shows what the guard's event reader took from the
input: its kind of tool, and whether it found a command, a path or content to judge.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile


def load(guard):
    spec = importlib.util.spec_from_file_location("guard_under_probe", guard)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv):
    guard, cases_path = argv[0], argv[1]
    cwd = argv[2] if len(argv) > 2 else os.getcwd()
    module = load(guard)
    with open(cases_path, encoding="utf-8") as fh:
        cases = json.load(fh)
    print("guard", module.VERSION)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, KZ_TELEMETRY_DIR=tmp)
        for case in cases:
            event = {
                "hook_event_name": "PreToolUse",
                "tool_name": case["tool"],
                "tool_input": case["input"],
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
                inner = out.get("hookSpecificOutput", out)
                verdict = inner.get("permissionDecision", "?")
                reason = inner.get("permissionDecisionReason", "")
            ev = module.Event(event)
            seen = [name for name in ("command", "path", "content") if getattr(ev, name)]
            brief = json.dumps(case["input"], sort_keys=True)
            print(f"{verdict:6} exit={proc.returncode} | kind={ev.kind:6} reads={','.join(seen) or '-':13} | "
                  f"{case['tool']} {brief[:150]}")
            if reason:
                print(f"       reason: {reason[:260]}")
            if proc.stderr.strip() and verdict != "deny":
                print(f"       stderr: {proc.stderr.strip()[:260]}")
            if case.get("twin"):
                print(f"       twin in a shell: {case['twin']}")


if __name__ == "__main__":
    main(sys.argv[1:])
