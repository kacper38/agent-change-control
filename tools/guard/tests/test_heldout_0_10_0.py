"""guard 0.10.0 (tracker item #65): the held-out rows. The host session wrote them before the build and committed
only their sha256 (`heldout-0.10.0.sha256`, the branch's first commit); the session that built 0.10.0 did not see
them. Each row is handed to `guard.py hook pre --wrapper claude` through the real entry point; nothing runs."""
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROWS = HERE / "heldout-0.10.0.txt"
CLEARED = ("CLAUDE_CODE_REMOTE", "CLAUDE_PROJECT_DIR")


def _rows():
    out = []
    for line in ROWS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            out.append(tuple(p.strip() for p in line.split(" | ", 4)))
    return out


def test_the_rows_are_the_ones_committed_before_the_code():
    want = (HERE / "heldout-0.10.0.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(ROWS.read_bytes()).hexdigest() == want


@pytest.fixture(scope="module")
def repos(tmp_path_factory):
    made = {}
    for boundary in ("own", "client"):
        repo = tmp_path_factory.mktemp(f"heldout-{boundary}")
        subprocess.run(["git", "init", "-q", "-b", "feat/x", str(repo)], check=True)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "guard.json").write_text(json.dumps({"boundary": boundary, "protected_branches": ["main"]}))
        made[boundary] = repo
    return made


@pytest.mark.parametrize("rid, env, expect, tool, text", _rows(), ids=[r[0] for r in _rows()])
def test_heldout_row(rid, env, expect, tool, text, repos, guard_path, tmp_path):
    e = {k: v for k, v in os.environ.items() if not k.startswith("KZ_") and k not in CLEARED}
    e["KZ_TELEMETRY_DIR"] = str(tmp_path / "telemetry")
    repo = repos["own"]
    for item in ([] if env == "-" else env.split(",")):
        if item == "cloud":
            e["CLAUDE_CODE_REMOTE"] = "true"
        elif item == "file=client":
            repo = repos["client"]
        elif item.startswith("rules_off="):
            e["KZ_RULES_OFF"] = item.split("=", 1)[1]
        elif item.startswith("KZ_BOUNDARY="):
            e["KZ_BOUNDARY"] = item.split("=", 1)[1]
        else:
            raise AssertionError(f"{rid}: unknown env item {item!r}")
    tool_input = {"command": text} if tool == "Bash" else json.loads(text)
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(repo),
             "session_id": "heldout", "transcript_path": "/x", "permission_mode": "default"}
    r = subprocess.run([sys.executable, guard_path, "hook", "pre", "--wrapper", "claude"], input=json.dumps(event),
                       capture_output=True, text=True, env=e, cwd=str(repo))
    assert r.returncode in (0, 2), r.stderr
    got = json.loads(r.stdout)["permissionDecision"] if r.stdout.strip() else "silent"
    assert got == expect, f"{rid}: {r.stdout or r.stderr}"
