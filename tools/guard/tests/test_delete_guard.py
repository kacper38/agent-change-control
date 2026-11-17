import json
import pathlib
import shlex
import subprocess
import sys

import pytest

FIX = pathlib.Path(__file__).parent / "fixtures"


def _cases():
    for harness in ("claude", "copilot"):
        for decision in ("ask", "allow"):
            for f in sorted((FIX / "delete-guard" / harness / decision).glob("*.json")):
                yield harness, decision, f


@pytest.mark.parametrize("harness,decision,path", list(_cases()), ids=lambda x: getattr(x, "name", str(x)))
def test_fixture(guard, harness, decision, path):
    ev = guard.Event(json.loads(path.read_text()))
    assert ev.harness == harness
    got = guard.rule_delete_guard(ev, {})
    if decision == "allow":
        assert got is None, f"{path.name}: unexpected {got}"
    else:
        assert got is not None and got[0] == "ask", f"{path.name}: expected ask, got {got}"
        assert "never auto-approve deletions" in got[1]


def test_script_invoked_by_path_is_scanned(guard, tmp_path):
    (tmp_path / "cleanup.py").write_text("import shutil\nshutil.rmtree('build')\n")
    (tmp_path / "ok.py").write_text("print('hello')\n")
    base = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path)}
    bad = guard.Event({**base, "tool_input": {"command": "python3 cleanup.py --dry-run"}})
    good = guard.Event({**base, "tool_input": {"command": "python3 ok.py"}})
    missing = guard.Event({**base, "tool_input": {"command": "python3 nope.py"}})
    assert guard.rule_delete_guard(bad, {})[1].startswith("Deletion guard")
    assert "script cleanup.py" in guard.rule_delete_guard(bad, {})[1]
    assert guard.rule_delete_guard(good, {}) is None
    assert guard.rule_delete_guard(missing, {}) is None


def test_only_shell_pretooluse(guard):
    post = guard.Event(
        {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf x"}}
    )
    write = guard.Event(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "rm", "content": "rm -rf x"},
        }
    )
    assert guard.rule_delete_guard(post, {}) is None
    assert guard.rule_delete_guard(write, {}) is None


def _ev(guard, command):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/work/repo",
                        "tool_input": {"command": command}})


# forms the text pass misses (measured on 0.6.0): only the token pass can see them
TOKEN_PASS_ASKS = [
    "sudo -u root rm -rf build", "env -i rm -rf build", "timeout 5 rm -rf build", "nice rm -rf build",
    "command -p rm -rf build", "\\rm -rf build", "\"rm\" -rf build", "/opt/homebrew/bin/rm -rf build",
    "if true; then rm -rf build; fi", "for f in a b; do rm \"$f\"; done", "{ rm -rf build; }", "! rm -rf build",
    "bash -c 'rm -rf build'", "bash -lc \"rm -rf build\"", "eval \"rm -rf build\"",
    "find . -name x -exec sudo rm {} +", "FOO=1 timeout 5 rm -rf build", "ssh host \"rm -rf /tmp/x\"",
    "npm --prefix web uninstall lodash", "pnpm --filter web remove lodash", "yarn --cwd web remove lodash",
    "docker --context prod rm c1", "docker compose -f x.yml down", "docker-compose down -v",
    "kubectl -n prod delete pod x", "helm -n prod uninstall r", "pip --no-input uninstall x",
    "pip3.12 --no-input uninstall x", "git -c core.pager=cat reset --hard", "git --no-pager clean -fd",
    "git --no-pager stash drop", "git -c a=b branch -D foo", "git -c a=b push origin --delete old",
    "npx --no-install prisma --schema db/main migrate reset", "docker --context prod system prune -af",
]


@pytest.mark.parametrize("command", TOKEN_PASS_ASKS)
def test_token_pass_asks_where_the_text_pass_is_blind(guard, command):
    assert not guard.DELETE_RE.search(command), "the text pass already sees it: not a token-pass case"
    got = guard.rule_delete_guard(_ev(guard, command), {})
    assert got is not None and got[0] == "ask", command
    assert "never auto-approve deletions" in got[1]


@pytest.mark.parametrize("command", [
    "grep -rn \"rmdir\" src/", "echo \"please do not rm this\"", "echo rm", "ls rm", "command -v rm",
    "docker run --rm alpine ls", "docker compose -f x.yml up -d", "npm --prefix web run build",
    "git -c core.pager=cat log --oneline", "git --no-pager diff --stat", "timeout 5 ls", "bash -c 'ls -la'",
    "kubectl -n prod get pods", "helm --kube-context prod template web ./chart", "which rm rmdir",
])
def test_token_pass_stays_silent_on_mentions(guard, command):
    assert guard.rule_delete_guard(_ev(guard, command), {}) is None, command


def test_a_nul_byte_in_a_script_name_asks(guard):
    """open() raises ValueError on a NUL byte: an unreadable name, not a crash that lets the command run."""
    got = guard.rule_delete_guard(_ev(guard, "timeout 5 rm -rf build; python3 a\x00b.py"), {})
    assert got is not None and got[0] == "ask"
    assert guard.rule_delete_guard(_ev(guard, "python3 a\x00b.py"), {}) is None


# fix brief point 6: command words are found behind wrappers, and a search for a delete word is no delete
@pytest.mark.parametrize("command", [
    "time -p rm -rf build", "ssh host rm -rf /data", "2>/dev/null rm -rf build", "coproc rm -rf build",
    "function f { rm -rf build; }; f", "setsid rm -rf build", "strace rm -rf build", "chroot / rm -rf build",
])
def test_command_words_behind_wrappers_ask(guard, command):
    got = guard.rule_delete_guard(_ev(guard, command), {})
    assert got is not None and got[0] == "ask", command


@pytest.mark.parametrize("command", [
    "sudo grep -rn rm /etc", "timeout 10 grep -rn shred .", "find . -exec grep -n unlink {} +",
    "find . -type d -name trash", "ssh host cat /var/log/rm", "watch -n 5 ls rm",
])
def test_searches_for_a_delete_word_stay_silent(guard, command):
    assert guard.rule_delete_guard(_ev(guard, command), {}) is None, command


# forms the fix pass still missed: found by a held-out check after it (inputs the engineer never saw)
@pytest.mark.parametrize("command", [
    "coproc { rm -rf build; }", "time { rm -rf build; }", "script -q /dev/null rm -rf build",
    "parallel 'rm {}' ::: a b", "trap 'rm -rf \"$tmp\"' EXIT", "bash<<<'rm -rf build'", "env -S'rm -rf build'",
    "tmux new-session -d 'rm -rf build'",
])
def test_held_out_forms_ask(guard, command):
    assert not guard.DELETE_RE.search(command), "the text pass already sees it: not a token-pass case"
    got = guard.rule_delete_guard(_ev(guard, command), {})
    assert got is not None and got[0] == "ask", command


@pytest.mark.parametrize("command", [
    "trap cleanup EXIT", "trap - EXIT", "parallel echo ::: a b", "tmux send-keys 'git status' Enter",
    "time { ls rm; }", "script /dev/null ls rm", "env LC_ALL=C sort -S10M rm.txt", "bash -c '-x; ls'",
    "cat<<<'rm -rf build'",
])
def test_held_out_forms_stay_silent_without_a_delete(guard, command):
    assert guard.rule_delete_guard(_ev(guard, command), {}) is None, command


def test_a_too_deep_nest_asks(guard):
    command = "echo hi"
    for _ in range(guard._HI_MAX_DEPTH + 1):
        command = "bash -c " + shlex.quote(command)
    assert guard.rule_delete_guard(_ev(guard, command), {}) == (
        "ask", guard.DELETE_MSG.format(what=guard._HI_NOT_READ))


@pytest.mark.parametrize("path", sorted((FIX / "_crash").iterdir()), ids=lambda p: p.name)
def test_crash_fixtures_exit_1_with_nothing_on_stdout(guard_path, path):
    r = subprocess.run(
        [sys.executable, guard_path, "hook", "pre"], input=path.read_bytes(), capture_output=True
    )
    assert r.returncode == 1, r
    assert r.stdout == b""
    assert b"guard: error" in r.stderr
