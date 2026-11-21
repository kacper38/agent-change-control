"""bin/box (tools/box/box.py) without a container: names, tokens, policy, judge settings, mounts, argv."""
import io
import json
import os
import pathlib
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
        box.check_github("ghp_distinctive_value_9f3a", "o/r", opener=opener)
    assert "agent-box-github" in str(exc.value) and "ghp_distinctive_value_9f3a" not in str(exc.value)


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
    h = box.HEADLESS
    assert h[h.index("--model") + 1] == box.MODEL and "--dangerously-skip-permissions" in h
    assert not [a for a in h if ">" in a or "<" in a], "no shell redirect: the host captures the output"


def test_rules_off_names_only_rules_the_guard_has(box, box_dir):
    """Guard 0.11.0 (item #66, D9): the box profile replaces the wrapper's KZ_RULES_OFF, so the wrapper sets none,
    and no file of the box or of bin/ names the variable except to say that it is no longer set."""
    argv = box.docker_argv("agent-box:abc", "b1", "s1", "def", [], ["claude"])
    assert not [a for a in argv if "KZ_RULES_OFF" in a], argv
    assert not hasattr(box, "RULES_OFF")
    here = pathlib.Path(__file__).resolve()
    # source files only: a run that writes bytecode leaves __pycache__/*.pyc of this module, whose docstring names
    # the variable (CI does; the owner's Mac sets PYTHONDONTWRITEBYTECODE)
    files = [p for p in [*box_dir.rglob("*"), *(box_dir.parent.parent / "bin").iterdir()]
             if p.is_file() and p != here and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            assert "KZ_RULES_OFF" not in line or "no longer" in line, f"{path}: {line}"


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


PROBED = "agent-box:" + "a" * 40


def gate_record(tmp_path, cli="2.1.323", status="holds", image=PROBED):
    path = tmp_path / "verified.json"
    path.write_text(json.dumps({"canaries": {}, "box": {"cli_version": cli, "image": image, "questions": {
        "hook-deny-checks-off": {"status": status}}}}), encoding="utf-8")
    return str(path)


def unchanged(sha):
    return False


def test_probe_gate_passes_only_on_a_hold_for_the_pinned_cli(box, tmp_path):
    pins = {"CLAUDE_CODE": "2.1.323"}
    box.probe_gate(pins, gate_record(tmp_path), changed=unchanged)
    for cli, status in (("2.1.323", "not_run"), ("2.1.323", "fails"), ("2.1.323", "inconclusive"),
                        ("2.1.300", "holds")):
        with pytest.raises(box.BoxError, match="has not shown that a hook's deny holds"):
            box.probe_gate(pins, gate_record(tmp_path, cli, status), changed=unchanged)
    with pytest.raises(box.BoxError, match="no probe record"):
        box.probe_gate(pins, str(tmp_path / "missing.json"))


def test_the_committed_record_gates_today(box):
    """Until the token questions have run, the committed record must stop every session."""
    record = json.loads(open(box.VERIFIED, encoding="utf-8").read())["box"]["questions"][box.GATE]["status"]
    if record != "holds":
        with pytest.raises(box.BoxError):
            box.probe_gate(box.read_pins())


def test_prepare_checks_the_gate_before_any_token(box, monkeypatch):
    monkeypatch.setattr(box, "keychain", lambda s: pytest.fail("a token was read"))
    monkeypatch.setattr(box, "probe_gate", lambda pins: (_ for _ in ()).throw(box.BoxError("gate")))
    with pytest.raises(box.BoxError, match="gate"):
        box.prepare("b1", "b1")


def test_parse_clone_facts(box):
    sha = "a" * 40
    facts = box.parse_clone_facts(0, f"{sha}\nfeat/x\n{{\"boundary\": \"own\"}}\n")
    assert facts == {"head": sha, "branch": "feat/x", "boundary": "own"}
    assert box.parse_clone_facts(0, f"{sha}\nmain\n")["boundary"] == ""
    for code, out in ((1, f"{sha}\nmain\n"), (0, "not a sha\nmain\n"), (0, "")):
        with pytest.raises(box.BoxError, match="cannot read the box's clone"):
            box.parse_clone_facts(code, out)


def test_clone_facts_never_runs_the_owners_git_in_the_clone(box, monkeypatch):
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "a" * 40 + "\nmain\n{}\n", "")

    monkeypatch.setattr(box.subprocess, "run", fake_run)
    box.clone_facts("agent-box:abc", "/c")
    (argv,) = seen
    assert argv[:2] == ["docker", "run"] and "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "type=bind,src=/c,dst=/work,readonly" in argv


def test_write_new_never_replaces_or_follows(box, tmp_path):
    path = tmp_path / "result.json"
    box.write_new(str(path), {"a": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    with pytest.raises(FileExistsError):
        box.write_new(str(path), {"a": 2})
    target = tmp_path / "elsewhere"
    target.write_text("keep", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(OSError):
        box.write_new(str(link), {"a": 3})
    assert target.read_text(encoding="utf-8") == "keep"


def test_no_mount_source_holds_the_results_folder(box, tmp_path):
    root = str(tmp_path)
    results = os.path.join(root, "boxes", "b1", "results", "20261120T100000Z")
    m = box.mounts(root, "b1", os.path.join(root, "judge", "x"), os.path.join(root, "boxes", "b1", "m.json"))
    for src, dst, _ in m:
        src = os.path.realpath(src)
        assert not (results == src or results.startswith(src.rstrip(os.sep) + os.sep)), (src, dst)


def test_probe_gate_refuses_when_tools_box_changed_or_the_record_was_dirty(box, tmp_path):
    pins = {"CLAUDE_CODE": "2.1.323"}
    with pytest.raises(box.BoxError, match="changed since the probed image"):
        box.probe_gate(pins, gate_record(tmp_path), changed=lambda sha: True)
    with pytest.raises(box.BoxError, match="changed since the probed image"):
        box.probe_gate(pins, gate_record(tmp_path, image=PROBED + "-dirty"), changed=unchanged)


def test_box_changed_since(box):
    head = box.git("rev-parse", "HEAD")
    assert box.box_changed_since(head) is False
    assert box.box_changed_since("0" * 40) is True  # not a commit here: counts as changed


def fake_box_run(box, monkeypatch, tmp_path, stdout_text, after_fails=False):
    """run() with the containers faked: what it records from the container's stdout and the clone reads."""
    root = tmp_path / "root"
    monkeypatch.setattr(box, "box_root", lambda: str(root))
    mounts_ = box.mounts(str(root), "b1", "/j", "/m.json")
    monkeypatch.setattr(box, "prepare", lambda name, seat: ("agent-box:abc", "def", mounts_, {}))
    heads = iter(["1" * 40, "2" * 40])

    def facts(image, clone):
        head = next(heads)
        if after_fails and head.startswith("2"):
            raise box.BoxError("cannot read the box's clone")
        return {"head": head, "branch": "feat/x", "boundary": "own"}

    monkeypatch.setattr(box, "clone_facts", facts)
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["stdin"] = argv, kw["stdin"].read()
        kw["stdout"].write(stdout_text.encode())
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(box.subprocess, "run", fake_run)
    brief = tmp_path / "brief.md"
    brief.write_text("do the thing\n", encoding="utf-8")
    out = io.StringIO()
    code = box.run("b1", "b1", brief=str(brief), out=out)
    path = out.getvalue().split("result ", 1)[1].strip()
    return code, json.loads(open(path, encoding="utf-8").read()), seen


RESULT = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.5, "num_turns": 3,
          "session_id": "s1", "result": "done"}


def test_run_records_the_last_stdout_line_and_both_heads(box, monkeypatch, tmp_path):
    code, record, seen = fake_box_run(box, monkeypatch, tmp_path,
                                      "firewall: set\n" + json.dumps(RESULT) + "\n")
    assert code == 0 and record["result"]["session_id"] == "s1" and record["result"]["total_cost_usd"] == 0.5
    assert (record["head_before"], record["head_after"], record["branch_after"]) == ("1" * 40, "2" * 40, "feat/x")
    assert seen["stdin"] == b"do the thing\n" and seen["argv"][-len(box.HEADLESS):] == box.HEADLESS
    assert record["brief_sha256"] and record["model"] == box.MODEL


def test_run_fails_on_output_it_cannot_read(box, monkeypatch, tmp_path):
    code, record, _ = fake_box_run(box, monkeypatch, tmp_path, "not json at all\n")
    assert code == 1 and record["result"] is None
    (tmp_path / "2").mkdir()
    code, record, _ = fake_box_run(box, monkeypatch, tmp_path / "2", json.dumps(RESULT, indent=2) + "\n")
    assert code == 1 and record["result"] is None  # multi-line JSON is not the CLI's form; it fails, never guesses


def test_run_records_a_clone_it_cannot_read_after(box, monkeypatch, tmp_path):
    code, record, _ = fake_box_run(box, monkeypatch, tmp_path, json.dumps(RESULT) + "\n", after_fails=True)
    assert code == 0 and record["head_after"] is None and record["head_before"] == "1" * 40
