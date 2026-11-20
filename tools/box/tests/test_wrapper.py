"""bin/box (tools/box/box.py) without a container: names, tokens, policy, judge settings, mounts, argv."""
import importlib.util
import io
import json
import os
import subprocess
import urllib.error

import pytest


def test_names_and_seats(box):
    for good in ("b", "build-1", "a" * 40):
        assert box.NAME.fullmatch(good)
    for bad in ("", "-x", "Upper", "a b", "a/b", "a" * 41, "../x"):
        assert not box.NAME.fullmatch(bad), bad


@pytest.mark.parametrize("url, slug", [
    ("https://github.com/kacper38/agent-change-control.git", "kacper38/agent-change-control"),
    ("https://github.com/kacper38/agent-change-control", "kacper38/agent-change-control"),
    ("git@github.com:kacper38/agent-change-control.git", "kacper38/agent-change-control"),
    ("ssh://git@github.com/o/r.git", "o/r"),
])
def test_repo_slug(box, url, slug):
    assert box.repo_slug(url) == slug


@pytest.mark.parametrize("url", ["https://gitlab.com/o/r.git", "https://github.com/o", "/local/path", "x"])
def test_repo_slug_refuses_what_is_not_github(box, url):
    with pytest.raises(box.BoxError, match="not a GitHub repository"):
        box.repo_slug(url)


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_github_sends_the_token_in_a_header_only(box):
    seen = []

    def opener(req, timeout):
        seen.append(req)
        return _Resp(200)

    box.check_github("secret-value", "o/r", opener=opener)
    (req,) = seen
    assert req.full_url == "https://api.github.com/repos/o/r" and "secret-value" not in req.full_url
    assert req.get_header("Authorization") == "Bearer secret-value"


@pytest.mark.parametrize("code, fragment", [(401, "expired or revoked"), (404, "cannot see"), (403, "refused")])
def test_check_github_names_the_keychain_entry_on_refusal(box, code, fragment):
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b""))

    with pytest.raises(box.BoxError, match=fragment) as exc:
        box.check_github("t", "o/r", opener=opener)
    assert "agent-box-github" in str(exc.value) and "t" != str(exc.value)


def test_check_github_fails_closed_offline(box):
    def opener(req, timeout):
        raise urllib.error.URLError("no network")

    with pytest.raises(box.BoxError, match="cannot check the token in agent-box-github"):
        box.check_github("t", "o/r", opener=opener)


def test_keychain_names_a_missing_entry_and_never_echoes(box, monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 44, "", "not found")

    monkeypatch.setattr(box.subprocess, "run", fake_run)
    with pytest.raises(box.BoxError, match="agent-box-claude is missing"):
        box.keychain("agent-box-claude")
    assert calls[0][:2] == ["security", "find-generic-password"] and "-w" in calls[0]


def git_repo(path, guard):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if guard is not None:
        (path / ".claude").mkdir()
        (path / ".claude" / "guard.json").write_text(guard, encoding="utf-8")
    (path / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q",
                    "-m", "init"], check=True)


@pytest.mark.parametrize("guard, boundary", [('{"boundary": "own"}', "own"), ('{"boundary": "client"}', "client"),
                                             ("{}", ""), ("not json", ""), (None, ""), ("[1]", "")])
def test_committed_boundary(box, tmp_path, guard, boundary):
    git_repo(tmp_path, guard)
    assert box.committed_boundary(str(tmp_path)) == boundary


def test_require_own_reads_the_commit_not_the_working_tree(box, tmp_path):
    git_repo(tmp_path, '{"boundary": "client"}')
    (tmp_path / ".claude" / "guard.json").write_text('{"boundary": "own"}', encoding="utf-8")  # uncommitted
    with pytest.raises(box.BoxError, match="boundary client, not own"):
        box.require_own(str(tmp_path), "HEAD", "the clone")


def test_managed_settings_from_the_real_project_settings(box, box_dir):
    data = box.managed_settings(str(box_dir.parents[1]))
    assert data["allowManagedHooksOnly"] is True and data["model"] == box.MODEL
    assert data["cleanupPeriodDays"] == 90
    commands = [h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]]
    assert commands and all(c.startswith("python3 /judge/tools/") for c in commands), commands
    assert any("guard.py hook pre" in c for c in commands)
    assert data["permissions"]["deny"], "the project's deny list travels with the hooks"


def test_managed_settings_fail_closed_on_a_hook_outside_the_judge(box, tmp_path):
    (tmp_path / ".claude").mkdir()
    settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": 'python3 "${CLAUDE_PROJECT_DIR:-.}"/tools/guard/guard.py hook pre'},
        {"type": "command", "command": "python3 /tmp/elsewhere.py"}]}]}}
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(box.BoxError, match="does not resolve to the judge"):
        box.managed_settings(str(tmp_path))


def test_mounts_are_the_four_and_the_judge_is_read_only(box, tmp_path):
    m = box.mounts(str(tmp_path), "b1", "/j", "/m.json")
    assert [(dst, ro) for _, dst, ro in m] == [("/work", False), ("/box-home", False), ("/judge", True),
                                               ("/etc/claude-code/managed-settings.json", True)]
    box.check_mounts(m)


@pytest.mark.parametrize("src", ["~", "~/.ssh", "~/.claude", "~/.claude/projects", "~/.config/gh",
                                 "/var/run/docker.sock", "~/.docker"])
def test_check_mounts_refuses_home_credentials_and_the_socket(box, src):
    with pytest.raises(box.BoxError, match="refused mount"):
        box.check_mounts([(os.path.expanduser(src), "/x", True)])


def test_docker_argv_passes_tokens_by_name_and_pins_the_model(box, tmp_path):
    m = box.mounts(str(tmp_path), "b1", "/j", "/m.json")
    argv = box.docker_argv("agent-box:abc", "b1", "s1", "def", m, ["claude"])
    joined = " ".join(argv)
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN"):
        i = argv.index(var)
        assert argv[i - 1] == "-e" and f"{var}=" not in joined
    assert "-e BOX_SEAT=s1" in joined and "-e BOX_JUDGE=def" in joined and "-e CLAUDE_CONFIG_DIR=/box-home" in joined
    assert "docker.sock" not in joined and "--privileged" not in joined
    assert "dst=/judge,readonly" in joined
    assert f"--model {box.MODEL} " in box.HEADLESS and "--dangerously-skip-permissions" in box.HEADLESS


def test_rules_off_names_only_rules_the_guard_has(box, box_dir):
    src = box_dir.parent / "guard" / "guard.py"
    spec = importlib.util.spec_from_file_location("guard_for_box", src)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    names = box.RULES_OFF.split(",")
    assert set(names) <= set(guard.RULES), set(names) - set(guard.RULES)


def test_run_without_a_terminal_needs_a_brief(box, monkeypatch):
    monkeypatch.setattr(box.sys, "stdin", io.StringIO())
    with pytest.raises(box.BoxError, match="needs a terminal"):
        box.run("b1", "b1", brief=None)


def test_run_refuses_a_missing_brief(box, tmp_path):
    with pytest.raises(box.BoxError, match="no brief"):
        box.run("b1", "b1", brief=str(tmp_path / "nope.md"))


@pytest.mark.parametrize("name, seat, fragment", [("Bad", "s", "not a box name"), ("ok", "a b", "not a seat")])
def test_prepare_refuses_bad_names_before_reading_any_token(box, monkeypatch, name, seat, fragment):
    monkeypatch.setattr(box, "keychain", lambda s: pytest.fail("a token was read"))
    with pytest.raises(box.BoxError, match=fragment):
        box.prepare(name, seat)
