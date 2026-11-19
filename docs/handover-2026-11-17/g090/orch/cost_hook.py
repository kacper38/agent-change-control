"""Time one `hook pre` call of each guard on long commands built from repeated units, at the real entry point.

usage: python3 -I cost_hook.py <units.txt> <size in bytes> <boundary: own|client> <guard.py> [<guard.py> ...]

units.txt: one unit per line, tab-separated: name, prefix, unit, suffix. The command is prefix + unit repeated
to the size + suffix. The commands are data handed to the hook on stdin; nothing in them runs. The hook keeps
its own time budget, so a call that overruns comes back as an ask that names the budget. Prints, per unit and
guard: size, wall time of one call, the verdict, and whether the answer names the budget.
"""
import json
import os
import subprocess
import sys
import tempfile
import time


def one(guard, command, cwd, env):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "cwd": cwd, "session_id": "timing", "transcript_path": "timing"}
    start = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, guard, "hook", "pre", "--wrapper", "claude"],
                              input=json.dumps(event), capture_output=True, text=True, env=env, cwd=cwd, timeout=60)
    except subprocess.TimeoutExpired:
        return time.perf_counter() - start, "NO ANSWER IN 60 s", ""
    took = time.perf_counter() - start
    if not proc.stdout.strip():
        return took, "silent", ""
    answer = json.loads(proc.stdout)
    inner = answer.get("hookSpecificOutput", answer)
    reason = inner.get("permissionDecisionReason", "") or ""
    note = "budget" if "budget" in reason else ""
    rules = sorted({word.rstrip(":") for word in reason.replace("\n", " ").split() if word.rstrip(":").endswith(
        ("-guard", "-ask", "-shell", "-branch", "-install"))})
    return took, inner.get("permissionDecision", "?"), (note + " " + ",".join(rules)).strip()


def main(argv):
    units, size, boundary, guards = argv[0], int(argv[1]), argv[2], argv[3:]
    with open(units, encoding="utf-8") as handle:
        rows = [line.rstrip("\n").split("\t") for line in handle if line.strip()]
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, ".claude"))
        with open(os.path.join(tmp, ".claude", "guard.json"), "w", encoding="utf-8") as handle:
            json.dump({"boundary": boundary}, handle)
        env = dict(os.environ, KZ_TELEMETRY_DIR=os.path.join(tmp, "telemetry"))
        print(f"size {size} B | boundary {boundary} | guards: {', '.join(os.path.basename(g) for g in guards)}")
        for name, prefix, unit, suffix in rows:
            count = max(1, (size - len(prefix) - len(suffix)) // len(unit))
            command = prefix + unit * count + suffix
            cells = []
            for guard in guards:
                took, verdict, note = one(guard, command, tmp, env)
                cells.append(f"{took * 1000:8.0f} ms {verdict:6} {note}")
            print(f"{name:18} {len(command):7} B | " + " | ".join(cells), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
