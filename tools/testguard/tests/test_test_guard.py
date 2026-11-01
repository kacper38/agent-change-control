"""check-test-tampering.sh (kit script + pytest rules + --worktree) and the PostToolUse wrapper (plan step 3.7)."""
import importlib.util
import io
import json
import os
import pathlib
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "check-test-tampering.sh"
TEST_PY = "import pytest\n\n\ndef test_one():\n    assert 1\n\n\nasync def test_two():\n    assert 2\n"
# Markers are assembled at runtime so this file's own diff never carries one (the guard scans test files).
SKIP, XFAIL, USKIP = "@pytest.mark." + "skip", "@pytest.mark." + "xfail(strict=True)", "@unittest." + "skip('x')"
PSKIP, ONLY = "pytest." + "skip('later')", "it." + "only('works', () => {});\n"


@pytest.fixture(scope="module")
def tg():
    spec = importlib.util.spec_from_file_location("testguard", HERE.parent / "testguard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """A repo on branch `feature` with `origin/main` behind it, one pytest file and one JS test file."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    git(r, "config", "commit.gpgsign", "false")
    write(r, "tests/test_a.py", TEST_PY)
    write(r, "src/x.py", "x = 1\n")
    write(r, "src/x.test.ts", "it('works', () => {});\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(r, "remote", "add", "origin", str(origin))
    git(r, "push", "-q", "origin", "main")
    git(r, "checkout", "-q", "-b", "feature")
    return r


def run(repo, *args, **env):
    e = {k: v for k, v in os.environ.items()
         if k not in ("BASE_REF", "PR_LABELS", "PR_LABELS_SET", "PR_TITLE", "PR_NUMBER")}
    e.update(env)
    r = subprocess.run(["bash", str(SCRIPT), *args], cwd=repo, capture_output=True, text=True, env=e)
    return r.returncode, r.stderr


def test_clean_tree_is_silent(repo):
    assert run(repo) == (0, "")
    assert run(repo, "--worktree") == (0, "")


def test_removed_test_function_in_worktree_then_committed_and_base_ref(repo):
    write(repo, "tests/test_a.py", TEST_PY.replace("\n\nasync def test_two():\n    assert 2\n", ""))
    code, err = run(repo, "--worktree", PR_LABELS="none")
    assert code == 1 and "FAIL(check-test-tampering): test files or test functions removed" in err
    assert "tests/test_a.py: test_two" in err and "test_one" not in err
    assert run(repo, PR_LABELS="none") == (0, ""), "committed mode: nothing on top of the base yet"
    git(repo, "commit", "-qam", "drop a test")
    code, err = run(repo, PR_LABELS="none")
    assert code == 1 and "tests/test_a.py: test_two" in err
    assert run(repo, BASE_REF="feature", PR_LABELS="none") == (0, ""), "BASE_REF = HEAD: nothing to compare"
    code, err = run(repo, BASE_REF="main", PR_LABELS="none")
    assert code == 1 and "test_two" in err, "a bare branch name resolves locally"
    code, err = run(repo, BASE_REF="nope", PR_LABELS="none")
    assert code == 1 and "cannot resolve base 'origin/nope'" in err


def test_azure_repos_inputs_base_ref_with_prefix_and_an_authoritative_empty_label_list(repo):
    write(repo, "tests/test_a.py", TEST_PY.replace("\n\nasync def test_two():\n    assert 2\n", ""))
    git(repo, "commit", "-qam", "drop a test")
    git(repo, "branch", "-D", "main")  # a CI checkout has origin/main only
    code, err = run(repo, BASE_REF="refs/heads/main", PR_LABELS="none")
    assert code == 1 and "tests/test_a.py: test_two" in err, "refs/heads/<name> resolves via origin/<name>"
    for labels in ({"PR_LABELS": ""}, {}):  # an unlabelled PR: Azure Pipelines may not export an empty variable
        code, err = run(repo, "--worktree", PR_LABELS_SET="1", **labels)
        assert code == 1 and "without the escape hatch" in err and "no PR context" not in err, labels
    code, err = run(repo, "--worktree", PR_LABELS_SET="1", PR_LABELS="test-removal-ok")
    assert code == 0 and "allowed by test-removal-ok" in err
    code, err = run(repo, "--worktree", PR_LABELS="")
    assert code == 0 and "no PR context" in err, "empty without PR_LABELS_SET keeps its old meaning: unknown"


def test_moved_or_renamed_test_function(repo):
    write(repo, "tests/test_a.py", TEST_PY.replace("\n\nasync def test_two():\n    assert 2\n", ""))
    write(repo, "tests/test_b.py", "async def test_two():\n    assert 2\n")  # untracked: counts in worktree mode
    assert run(repo, "--worktree", PR_LABELS="none") == (0, "")
    git(repo, "add", "tests/test_b.py")
    git(repo, "commit", "-qam", "move a test")
    assert run(repo, PR_LABELS="none") == (0, "")
    write(repo, "tests/test_b.py", "async def test_two_renamed():\n    assert 2\n")
    code, err = run(repo, "--worktree", PR_LABELS="none")
    assert code == 1 and "tests/test_a.py: test_two" in err, "reported where the base had it: diff-aware vs the base"


def test_added_markers_fail_but_conditional_skips_pass(repo):
    write(repo, "tests/test_a.py", TEST_PY.replace("def test_one", SKIP + "\ndef test_one"))
    code, err = run(repo, "--worktree")
    assert code == 1 and "focus/skip markers ADDED" in err and "tests/test_a.py:4: " + SKIP in err
    for marker in (XFAIL, USKIP):
        write(repo, "tests/test_a.py", TEST_PY.replace("def test_one", marker + "\ndef test_one"))
        assert run(repo, "--worktree")[0] == 1, marker
    write(repo, "tests/test_a.py", TEST_PY.replace("    assert 1", "    " + PSKIP))
    assert run(repo, "--worktree")[0] == 1
    for marker in ("@pytest.mark.skipif(True, reason='x')", "@unittest.skipIf(True, 'x')"):
        write(repo, "tests/test_a.py", TEST_PY.replace("def test_one", marker + "\ndef test_one"))
        assert run(repo, "--worktree") == (0, ""), marker
    write(repo, "tests/test_a.py", TEST_PY)
    write(repo, "src/x.test.ts", ONLY)
    code, err = run(repo, "--worktree")
    assert code == 1 and "src/x.test.ts:1: " + ONLY.strip() in err
    write(repo, "src/x.test.ts", "it('works', () => {});\n")
    write(repo, "tests/test_new.py", "import pytest\n" + SKIP + "\ndef test_new():\n    pass\n")  # untracked
    code, err = run(repo, "--worktree")
    assert code == 1 and "tests/test_new.py:2: " + SKIP in err, "an untracked test file is judged in worktree mode"
    assert run(repo) == (0, ""), "committed mode never sees untracked files; CI judges after the commit"


def test_deleted_test_file_needs_the_label(repo):
    (repo / "tests" / "test_a.py").unlink()
    code, err = run(repo, "--worktree", PR_LABELS="none")
    assert code == 1 and "tests/test_a.py (deleted)" in err
    assert "test_one" not in err, "a deleted file is one finding, not one per function"
    code, err = run(repo, "--worktree", PR_LABELS="other,test-removal-ok")
    assert code == 0 and "WARN(check-test-tampering)" in err and "allowed by test-removal-ok" in err
    code, err = run(repo, "--worktree")
    assert code == 0 and "no PR context" in err, "the hook never calls gh: WARN, and CI decides with the label"


def test_rename_out_of_the_test_glob_and_skip_ci_marker(repo):
    git(repo, "mv", "tests/test_a.py", "tests/helpers.py")
    git(repo, "commit", "-qm", "hide the tests [skip ci]")
    code, err = run(repo, PR_LABELS="none")
    assert code == 1
    assert "tests/test_a.py -> tests/helpers.py (renamed out of the test glob" in err
    assert "CI-skip markers found" in err and "hide the tests [skip ci]" in err
    code, err = run(repo, PR_LABELS="test-removal-ok", PR_TITLE="feat: x [ci skip]")
    assert code == 1 and "PR title: feat: x [ci skip]" in err


# --- the PostToolUse wrapper ---------------------------------------------------


def hook(tg, payload):
    out = io.StringIO()
    code = tg.main(["hook"], stdin=io.StringIO(payload if isinstance(payload, str) else json.dumps(payload)), out=out)
    return code, out.getvalue()


@pytest.mark.parametrize("path,command,expected", [
    ("/r/tools/x/tests/test_a.py", "", True),
    ("/r/a_test.py", "", True),
    ("/r/src/x.test.ts", "", True),
    ("/r/src/x.spec.js", "", True),
    ("/r/src/x.py", "", False),
    ("/r/tests/conftest.py", "", False),
    ("", "rm tests/test_a.py", True),
    ("", "git mv tools/x/tests/test_a.py tools/x/tests/a.py", True),
    ("", "sed -i 's/a/b/' src/x.test.ts", True),
    ("", "ls -la", False),
    ("", "python -m pytest -q", False),
])
def test_touches_tests(tg, path, command, expected):
    assert tg.touches_tests(path, command) is expected


def test_hook_feeds_findings_back_in_both_shapes(tg, repo):
    write(repo, "tests/test_a.py", TEST_PY.replace("\n\nasync def test_two():\n    assert 2\n", ""))
    claude = {"hook_event_name": "PostToolUse", "session_id": "s1", "cwd": str(repo), "tool_name": "Edit",
              "tool_input": {"file_path": str(repo / "tests" / "test_a.py"), "old_string": "x", "new_string": "y"}}
    code, out = hook(tg, claude)
    assert code == 0
    data = json.loads(out)
    assert data["decision"] == "block" and data["reason"].startswith("test-guard: WARN(check-test-tampering)")
    assert "tests/test_a.py: test_two" in data["reason"] and "CI needs the label" in data["reason"]
    assert "additionalContext" not in data
    copilot = {"hook_event_name": "PostToolUse", "session_id": "c1", "timestamp": "2026-10-29T10:00:00.000Z",
               "cwd": str(repo), "tool_name": "edit", "tool_input": {"path": str(repo / "tests" / "test_a.py")}}
    code, out = hook(tg, copilot)
    data = json.loads(out)
    assert code == 0 and set(data) == {"additionalContext"} and "test_two" in data["additionalContext"]
    cli = {"hookEventName": "postToolUse", "sessionId": "c2", "timestamp": 1761732000000, "toolName": "edit",
           "cwd": str(repo), "toolArgs": json.dumps({"path": str(repo / "tests" / "test_a.py")})}  # JSON-encoded
    code, out = hook(tg, cli)
    data = json.loads(out)
    assert code == 0 and set(data) == {"additionalContext"} and "test_two" in data["additionalContext"]
    (repo / "tests" / "test_a.py").unlink()
    bash = {"hook_event_name": "PostToolUse", "session_id": "s1", "cwd": str(repo), "tool_name": "Bash",
            "tool_input": {"command": "rm tests/test_a.py"}}
    code, out = hook(tg, bash)
    assert code == 0 and "tests/test_a.py (deleted)" in json.loads(out)["reason"]


def test_hook_is_silent_when_nothing_applies(tg, repo, tmp_path):
    clean = {"cwd": str(repo), "tool_name": "Edit", "tool_input": {"file_path": str(repo / "tests" / "test_a.py")}}
    assert hook(tg, clean) == (0, "")
    other = {"cwd": str(repo), "tool_name": "Edit", "tool_input": {"file_path": str(repo / "src" / "x.py")}}
    assert hook(tg, other) == (0, "")
    outside = tmp_path / "plain"
    outside.mkdir()
    write(outside, "test_z.py", "def test_z(): pass\n")
    assert hook(tg, {"cwd": str(outside), "tool_name": "Write",
                     "tool_input": {"file_path": str(outside / "test_z.py")}}) == (0, "")
    assert hook(tg, "{{{") == (0, "")
    assert hook(tg, "[1, 2]") == (0, "")
    assert hook(tg, {"toolName": "edit", "toolArgs": "not json", "timestamp": 1}) == (0, "")
    assert hook(tg, {"toolName": "edit", "toolArgs": "[1]", "timestamp": 1}) == (0, "")
    assert tg.main(["help"], stdin=io.StringIO(""), out=io.StringIO()) == 0
    assert tg.main(["bogus"], stdin=io.StringIO(""), out=io.StringIO()) == 1
