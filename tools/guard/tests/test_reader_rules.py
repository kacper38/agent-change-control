"""guard 0.7.0, step 1: git-guard, tracker-guard, secret-shell, protected-branch and host-install read every
simple command the line runs (wrappers, nested scripts, substitutions), as deploy-ask and delete-guard do."""
import shlex

import pytest

RANK = {None: 0, "ask": 1, "deny": 2}

# wrapper and nesting forms: `{}` stands for the payload command
FORMS = [
    ("plain", "{}"),
    ("sudo", "sudo {}"),
    ("sudo -u", "sudo -u bob {}"),
    ("doas", "doas {}"),
    ("timeout", "timeout 30 {}"),
    ("timeout -k", "timeout -k 5 30 {}"),
    ("nice", "nice -n 5 {}"),
    ("ionice", "ionice -c3 {}"),
    ("env VAR", "env X=1 {}"),
    ("VAR=", "X=1 {}"),
    ("/usr/bin/env", "/usr/bin/env {}"),
    ("env -S", "env -S '{}'"),
    ("time", "time {}"),
    ("time -p", "time -p {}"),
    ("/usr/bin/time", "/usr/bin/time {}"),
    ("command", "command {}"),
    ("builtin command", "builtin command {}"),
    ("exec", "exec {}"),
    ("nohup", "nohup {}"),
    ("setsid", "setsid {}"),
    ("stdbuf", "stdbuf -oL {}"),
    ("caffeinate", "caffeinate -i {}"),
    ("arch", "arch -arm64 {}"),
    ("strace", "strace {}"),
    ("flock", "flock /tmp/l {}"),
    ("chroot", "chroot / {}"),
    ("xargs", "echo x | xargs {}"),
    ("find -exec", "find . -name x -exec {} \\;"),
    ("bash -c", "bash -c '{}'"),
    ("sh -c dq", 'sh -c "{}"'),
    ("bash -lc", "bash -lc '{}'"),
    ("bash -c -e", "bash -c -e '{}'"),
    ("bash -c --", "bash -c -- '{}'"),
    ("bash -o x -c", "bash -o pipefail -c '{}'"),
    ("zsh -c", "zsh -c '{}'"),
    ("su -c", "su -c '{}'"),
    ("$SHELL -c", "$SHELL -c '{}'"),
    ("bash <<<", "bash <<< '{}'"),
    ("two levels", "bash -c \"sh -c '{}'\""),
    ("eval dq", 'eval "{}"'),
    ("eval bare", "eval {}"),
    ("eval --", 'eval -- "{}"'),
    ("&&", "echo ok && {}"),
    ("||", "false || {}"),
    (";", "true; {}"),
    ("pipe", "true | {}"),
    ("newline", "true\n{}"),
    ("background", "{} &"),
    ("subshell", "({})"),
    ("subshell cd", "(cd . && {})"),
    ("braces", "{ {}; }"),
    ("if", "if true; then {}; fi"),
    ("while", "while true; do {}; break; done"),
    ("for", "for i in 1; do {}; done"),
    ("!", "! {}"),
    ("function", "function f { {}; }; f"),
    ("f()", "f() { {}; }; f"),
    ("coproc", "coproc {}"),
    ("$() in dq", 'echo "$({})"'),
    ("$() bare", "echo $({})"),
    ("backticks", "echo `{}`"),
    ("VAR=$()", "X=$({})"),
    ("redirect first", "2>/dev/null {}"),
    ("redirect first 2", "> log {}"),
    ("watch", "watch '{}'"),
    ("parallel", "parallel '{}' ::: a"),
    ("trap", "trap '{}' EXIT"),
    ("script -c", "script -q -c '{}' /dev/null"),
    ("backslash", "\\{}"),
    ("abs path", "/usr/bin/{}"),
    ("ssh (remote)", "ssh host '{}'"),
]

# (rule, payload, the verdict of the plain command)
PAYLOADS = [
    ("git-guard", "git commit --no-verify -m x", "deny"),
    ("git-guard", "git push --force origin feat", "deny"),
    ("git-guard", "git push origin main", "deny"),
    ("tracker-guard", "gh issue close 3", "deny"),
    ("tracker-guard", "python3 tools/tracker/tracker.py owner done 3", "deny"),
    ("tracker-guard", "gh api -X POST repos/o/r/issues -f title=x", "deny"),
    ("secret-shell", "cat .env", "ask"),
    ("secret-shell", "cp x .env", "deny"),
    ("protected-branch", "git commit -m x", "deny"),
    ("host-install", "npm install", "ask"),
    ("host-install", "uv run pytest", "ask"),
    ("deploy-ask", "terraform apply", "ask"),
    ("delete-guard", "rm -rf build", "ask"),
]

# the remote route: an install or a commit over ssh happens on another machine, in another checkout
EXCEPTIONS = {("host-install", "ssh (remote)"), ("protected-branch", "ssh (remote)")}

FIVE = ["git-guard", "tracker-guard", "secret-shell", "protected-branch", "host-install"]

# mentions, quoted text and harmless calls: all five rules stay silent (on a branch that is not protected)
SILENT = [
    'git commit -m "docs: say why git push --force is denied"',
    "git commit -m 'note: `git push origin main` is refused by the guard'",
    'git commit -m "chore: npm install note"',
    'echo "git push --force origin main"',
    'echo "cp x .env"',
    'grep -rn "git commit --no-verify" docs/',
    'gh pr create --title "x" --body "closes nothing, gh issue close 3 is the owner\'s verb"',
    'git log --grep "tracker.py owner done"',
    'python3 tools/tracker/tracker.py note 3 "owner done comes later"',
    "bash -c 'echo \"npm install\"'",
    "bash -c 'git push origin feat/x'",
    "timeout 30 git push origin feat/x",
    "sudo -u bob git status",
    "watch -n 5 'git status'",
    "find . -name '*.py' -exec grep -l \"git push\" {} +",
    "xargs -n1 git log -1 --format=%s",
    "git push origin feat/x",
    "git -C sub log --oneline",
    "uv run --offline --no-project --with pytest --python 3.13 python -m pytest -q tools/guard/tests",
    "python3 -m pytest -q",
    "npx --no-install eslint .",
    "env NODE_ENV=production npm run build",
    'docker run --rm -v "$PWD":/w node:20 npm ci',
    "tmux new-session -d 'npm run dev'",
    "ssh host 'npm install'",
    "ssh host 'ls -la'",
]


def _ev(guard, command, cwd="/work/repo"):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
                        "tool_input": {"command": command}})


def _verdict(guard, rule, command):
    got = guard.RULES[rule](_ev(guard, command), dict(guard.DEFAULTS))
    return got[0] if got else None


@pytest.fixture
def on_main(guard, monkeypatch):
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "main")


@pytest.fixture
def on_feature(guard, monkeypatch):
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "feat/x")


def _cells():
    for rule, payload, base in PAYLOADS:
        for form_name, form in FORMS:
            want = None if (rule, form_name) in EXCEPTIONS else base
            yield pytest.param(rule, form.replace("{}", payload), want, id=f"{rule}|{form_name}|{payload}")


@pytest.mark.parametrize("rule,command,want", list(_cells()))
def test_matrix_cell_is_at_least_the_plain_verdict(guard, on_main, rule, command, want):
    got = _verdict(guard, rule, command)
    if want is None:
        assert got is None, f"{command!r}: {rule} said {got}, the remote route stays silent"
    else:
        assert RANK[got] >= RANK[want], f"{command!r}: {rule} said {got}, want at least {want}"


def test_matrix_has_every_cell():
    assert len(FORMS) * len(PAYLOADS) == 923


@pytest.mark.parametrize("command", SILENT)
def test_mentions_and_harmless_calls_stay_silent(guard, on_feature, command):
    got = {rule: _verdict(guard, rule, command) for rule in FIVE}
    assert not any(got.values()), f"{command!r}: {got}"


def _nest(command, depth):
    for _ in range(depth):
        command = "sh -c " + shlex.quote(command)
    return command


def test_a_line_the_reader_cannot_read_asks_in_every_rule(guard, on_main):
    command = _nest("git push origin main", 6)
    for rule in FIVE:
        got = guard.RULES[rule](_ev(guard, command), dict(guard.DEFAULTS))
        assert got and got[0] == "ask", (rule, got)
        assert "not read" in got[1], (rule, got)


def test_a_first_pass_deny_survives_a_reader_that_raises(guard, on_main, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(guard, "nested_commands", boom)
    for rule, command in [("git-guard", "git push --force origin feat"), ("tracker-guard", "gh issue close 3"),
                          ("secret-shell", "cp x .env"), ("protected-branch", "git commit -m x")]:
        assert _verdict(guard, rule, command) == "deny", rule
    for rule in FIVE:
        got = guard.RULES[rule](_ev(guard, "ls"), dict(guard.DEFAULTS))
        assert got and got[0] == "ask" and "could not be read (RuntimeError)" in got[1], (rule, got)


def test_a_reader_that_stops_keeps_the_first_pass_deny(guard, on_main, monkeypatch):
    def stop(*_a, **_k):
        raise guard.CommandNotRead("synthetic stop")
    monkeypatch.setattr(guard, "nested_commands", stop)
    assert _verdict(guard, "git-guard", "git push --force origin feat") == "deny"
    got = guard.rule_git_guard(_ev(guard, "ls"), dict(guard.DEFAULTS))
    assert got and got[0] == "ask" and "synthetic stop" in got[1]


def test_secret_shell_reader_turns_a_read_into_a_deny(guard):
    assert _verdict(guard, "secret-shell", "timeout 5 cp x .env") == "deny"
    assert _verdict(guard, "secret-shell", "timeout 5 cat .env") == "ask"


def test_a_here_document_body_stays_data(guard, on_main):
    command = ("cat > notes.md <<'EOF'\ngit push --force origin main\nnpm install\ngit commit --no-verify -m x\n"
               "gh issue close 3\ncp x .env\nEOF")
    got = {rule: _verdict(guard, rule, command) for rule in FIVE}
    assert not any(got.values()), got


def test_local_reading_stops_at_a_container_or_remote_tool(guard):
    assert guard.nested_commands("ssh host 'npm install'", local=True) == ()
    assert guard.nested_commands("sudo docker exec web sh -c 'npm install'", local=True) == (("sudo",),)
    assert guard.nested_commands("docker exec web bash <<< 'npm install'", local=True) == ()
    full = guard.nested_commands("ssh host 'npm install'")
    assert ("npm", "install") in full, "the full reading still takes the remote script"


def test_local_reading_keeps_substitutions_the_host_runs(guard):
    got = guard.nested_commands('ssh host "$(npm install)"', local=True)
    assert ("npm", "install") in got
    assert _verdict(guard, "host-install", 'ssh host "$(npm install)"') == "ask"


def test_protected_branch_reads_git_c_behind_a_wrapper(guard, monkeypatch):
    seen = []
    monkeypatch.setattr(guard, "current_branch", lambda cwd: seen.append(cwd) or "feat/x")
    assert _verdict(guard, "protected-branch", "timeout 30 git -C /elsewhere commit -m x") is None
    assert "/elsewhere" in seen
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "main" if cwd == "/elsewhere" else "feat/x")
    assert _verdict(guard, "protected-branch", "timeout 30 git -C /elsewhere commit -m x") == "deny"


def test_command_word_indexes_is_memoised(guard):
    toks = ("sudo", "-u", "bob", "git", "push")
    assert guard.command_word_indexes(toks) is guard.command_word_indexes(list(toks))
