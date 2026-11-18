"""Time one `hook pre` call of a guard for a few commands (median of runs), the event on stdin.

usage: python3 -I hooktime.py <timing.json> <guard.py> [<guard.py> ...]
The commands come from the data file; nothing in them runs, the hook only reads the event.
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

RUNS = 5


def commands(spec, base):
    """(label, command) pairs from the data file."""
    out = [("plain", spec["plain"])]
    longest = ""
    for name in spec["row_files"]:
        with open(os.path.join(base, name), encoding="utf-8") as fh:
            for ln in fh:
                if ln.strip() and not ln.startswith("#"):
                    c = ln.rstrip("\n").split(" | ", 4)[4].strip()
                    c = json.loads(c) if c.startswith('"') else c
                    longest = max(longest, c, key=len)
    out.append(("longest row", longest))
    n = spec["big_bytes"]
    for label, unit in (("100 kB", spec["big_unit"]), ("100 kB capitals", spec["big_caps_unit"])):
        out.append((label, (unit * (n // len(unit) + 1))[:n]))
    return out


def one(guard, command, cwd, env):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "cwd": cwd, "session_id": "timing", "transcript_path": "timing"}
    start = time.perf_counter()
    proc = subprocess.run([sys.executable, guard, "hook", "pre", "--wrapper", "claude"], input=json.dumps(event),
                          capture_output=True, text=True, env=env, cwd=cwd, timeout=60)
    took = time.perf_counter() - start
    verdict = json.loads(proc.stdout)["permissionDecision"] if proc.stdout.strip() else "silent"
    return took, verdict


def main(argv):
    with open(argv[0], encoding="utf-8") as fh:
        spec = json.load(fh)
    cmds = commands(spec, os.path.dirname(os.path.abspath(argv[0])))
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, KZ_TELEMETRY_DIR=tmp)
        for guard in argv[1:]:
            print(guard)
            for label, command in cmds:
                runs = [one(guard, command, tmp, env) for _ in range(RUNS)]
                med = statistics.median(t for t, _v in runs)
                print(f"  {label:16} {len(command):7} B  median {med * 1000:7.1f} ms  verdict {runs[0][1]}")


if __name__ == "__main__":
    main(sys.argv[1:])
