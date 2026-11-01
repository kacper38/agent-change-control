import json
import os
import pathlib
import subprocess
import sys

FIX = pathlib.Path(__file__).parent / "fixtures"


def run(guard_path, args, payload):
    data = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    raw = data.encode() if isinstance(data, str) else data
    return subprocess.run([sys.executable, guard_path, *args], input=raw, capture_output=True)


def _bash(harness, cmd):
    shape = "claude/PreToolUse-Bash.json" if harness == "claude" else "copilot/PreToolUse-bash.json"
    d = json.loads((FIX / "_shapes" / shape).read_text())
    d["tool_input"] = {"command": cmd}
    return d


def test_ask_exit_0_with_both_decision_keys(guard_path):
    r = run(guard_path, ["hook", "pre"], _bash("claude", "rm -rf build"))
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["permissionDecision"] == "ask"
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert out["permissionDecisionReason"] == out["hookSpecificOutput"]["permissionDecisionReason"]


def test_allow_is_silent(guard_path):
    r = run(guard_path, ["hook", "pre"], _bash("claude", "git status"))
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""


def test_deny_exit_2_json_and_stderr(guard, capsys):
    code = guard.respond(("deny", "nope"), "PreToolUse")
    captured = capsys.readouterr()
    assert code == 2
    assert json.loads(captured.out)["permissionDecision"] == "deny"
    assert captured.err.strip() == "nope"


def test_combine_prefers_deny_and_joins_reasons(guard):
    assert guard.combine([]) is None
    assert guard.combine([("ask", "a"), ("ask", "a"), ("ask", "b")]) == ("ask", "a | b")
    assert guard.combine([("ask", "a"), ("deny", "d")]) == ("deny", "d")


def test_copilot_event_through_claude_wrapper_is_a_noop(guard_path):
    r = run(guard_path, ["hook", "pre", "--wrapper", "claude"], _bash("copilot", "rm -rf build"))
    assert r.returncode == 0 and r.stdout == b""
    r = run(guard_path, ["hook", "pre", "--wrapper", "github"], _bash("copilot", "rm -rf build"))
    assert r.returncode == 0 and json.loads(r.stdout)["permissionDecision"] == "ask"
    r = run(guard_path, ["hook", "pre", "--wrapper", "claude"], _bash("claude", "rm -rf build"))
    assert json.loads(r.stdout)["permissionDecision"] == "ask"


def test_single_rule_and_unknown_rule(guard_path):
    r = run(guard_path, ["hook", "delete-guard"], _bash("claude", "rm -rf build"))
    assert r.returncode == 0 and b"ask" in r.stdout
    r = run(guard_path, ["hook", "no-such-rule"], _bash("claude", "ls"))
    assert r.returncode == 1 and b"unknown rule" in r.stderr and r.stdout == b""


def test_capture_writes_redacted_file(guard_path, tmp_path, monkeypatch):
    monkeypatch.setenv("KZ_TELEMETRY_DIR", str(tmp_path / "t"))
    d = _bash("claude", "echo ghp_abcdefghijklmnopqrstuvwxyz0123 > /dev/null")
    env = {**os.environ, "KZ_TELEMETRY_DIR": str(tmp_path / "t")}
    r = subprocess.run([sys.executable, guard_path, "hook", "capture"], input=json.dumps(d).encode(),
                       capture_output=True, env=env)
    assert r.returncode == 0 and r.stdout == b""
    files = list((tmp_path / "t" / "captures" / "claude").glob("PreToolUse-Bash-*.json"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "ghp_" not in text and "<redacted>" in text


def test_redact_masks_ado_pats_and_entra_tokens(guard):
    pat = "Ab3x" * 19 + "AZDO" + "Q7rT"  # synthetic, built at runtime: 84 chars, AZDO at [76:80]
    jwt = "eyJ" + "hbGciOiJSUzI1NiJ9" + ".eyJ" + "hdWQiOiI0OTliODRhYyJ9" + "." + "c2lnbmF0dXJlLXBhcnQ"
    out = guard.redact({"command": f"echo {pat}", "tool_response": {"stdout": jwt + "\n"}})
    assert out == {"command": "echo <redacted>", "tool_response": {"stdout": "<redacted>\n"}}
    legacy = "abcdefghijklmnopqrstuvwxyz234567" + "abcdefghijklmnopqrst"  # 52-char base32 PAT: left out on purpose
    assert guard.redact(legacy) == legacy


def test_help_version_rules(guard, guard_path):
    assert run(guard_path, ["version"], "").stdout.strip().decode() == guard.VERSION
    assert b"delete-guard" in run(guard_path, ["rules"], "").stdout
    assert b"Usage" in run(guard_path, ["help"], "").stdout


def test_ask_and_deny_are_logged_to_decisions_jsonl(guard_path, tmp_path, monkeypatch):
    monkeypatch.setenv("KZ_TELEMETRY_DIR", str(tmp_path / "t"))  # the env wins over guard.json
    assert run(guard_path, ["hook", "pre"], _bash("claude", "rm -rf build")).returncode == 0
    assert run(guard_path, ["hook", "pre"], _bash("claude", "git push --force origin main")).returncode == 2
    assert run(guard_path, ["hook", "pre"], _bash("claude", "git status")).returncode == 0
    rows = [json.loads(ln) for ln in (tmp_path / "t" / "decisions.jsonl").read_text().splitlines()]
    assert [r["verdict"] for r in rows] == ["ask", "deny"]
    assert rows[0]["rules"] == {"delete-guard": "ask"} and rows[0]["tool"] == "Bash" and rows[0]["harness"] == "claude"
    assert rows[1]["rules"]["git-guard"] == "deny"
    assert all(v == "ask" for k, v in rows[1]["rules"].items() if k != "git-guard")  # per-rule, not the combined one
    assert not any("rm -rf" in json.dumps(r) or "--force" in json.dumps(r) for r in rows)  # no command text
