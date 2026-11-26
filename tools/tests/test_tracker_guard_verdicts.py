"""#103: the guard rule `tracker-guard` denies `tracker owner ...` to a session and stays silent on
`tracker delegate ...`, whose own delegation check decides. The hook runs as Claude Code calls it."""

import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "guard" / "guard.py"
TRACKER = "python3 tools/tracker/tracker.py"


def verdict(tmp_path: pathlib.Path, command: str) -> subprocess.CompletedProcess:
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
             "cwd": str(tmp_path), "session_id": "verdicts", "transcript_path": "/x", "permission_mode": "default"}
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "KZ_TELEMETRY_DIR": str(tmp_path / "telemetry"),
           "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-config")}
    return subprocess.run([sys.executable, str(GUARD), "hook", "pre", "--wrapper", "claude"], input=json.dumps(event),
                          capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60)


@pytest.mark.parametrize("command", [f"{TRACKER} owner done 1 --accept-all", f"{TRACKER} owner ready 1"])
def test_tracker_owner_is_denied(tmp_path, command):
    r = verdict(tmp_path, command)
    assert r.returncode in (0, 2), r.stderr
    out = json.loads(r.stdout)
    assert out["permissionDecision"] == "deny", r.stdout
    assert "tracker-guard: `tracker owner` is the human's verb" in r.stdout


@pytest.mark.parametrize("command", [f'{TRACKER} delegate done 1 --word "w" --evidence e.json',
                                     f'{TRACKER} delegate ready 1 --word "w"'])
def test_tracker_delegate_gets_no_verdict(tmp_path, command):
    r = verdict(tmp_path, command)
    assert (r.returncode, r.stdout) == (0, ""), r.stdout + r.stderr
