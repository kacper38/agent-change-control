"""guard 0.12.1 on the real worktree: the listed review-panel starts silent, another name asks.

usage: python3 -I live_0121.py <worktree>. The events go to `hook pre` of the worktree's own guard on stdin; the
telemetry goes to a scratch folder; nothing a call names is run."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.argv[1])
guard = root / "tools" / "guard" / "guard.py"
with tempfile.TemporaryDirectory() as tel:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KZ_") and k != "CLAUDE_PROJECT_DIR"}
    env["KZ_TELEMETRY_DIR"] = tel
    for name in ("review-panel", "other"):
        event = {"cwd": str(root), "session_id": "live-0121", "transcript_path": "/x", "permission_mode": "default",
                 "hook_event_name": "PreToolUse", "tool_name": "Workflow",
                 "tool_input": {"name": name, "args": {"diff": "/tmp/x.diff"}}, "tool_use_id": f"toolu_{name}"}
        r = subprocess.run([sys.executable, str(guard), "hook", "pre", "--wrapper", "claude"], input=json.dumps(event),
                           capture_output=True, text=True, env=env, cwd=str(root))
        out = json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        answer = "silent" if out is None else out["permissionDecision"] + ": " + out["permissionDecisionReason"][:90]
        print(f"{name}: exit {r.returncode}, {answer}")
