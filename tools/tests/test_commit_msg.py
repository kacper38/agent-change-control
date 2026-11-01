"""commit-msg rules (plan step 3.1)."""
import importlib.util
import pathlib
import subprocess

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "commit_msg.py"
spec = importlib.util.spec_from_file_location("commit_msg", SRC)
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)

OK = [
    "feat(guard): add scratch-md rule",
    "fix: handle unborn branches in current_branch",
    "docs: how to use the kit at work",
    "feat(tracker)!: drop the urllib backend",
    "chore: bump ruff\n\nRefs #12\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>\n",
    "Merge branch 'step-1.5' into main",
    "Revert \"feat: x\"\n\nThis reverts commit abc.",
    "fixup! feat: x",
    "amend! feat: x",
    "feat: add CI matrix for 3.9 and 3.13",
    "feat: add x\n\n# a template comment saying fixes #12 is stripped by git\n",
]
BAD = [
    ("fixes #12", "subject must be"),
    ("Added guard rule", "subject must be"),
    ("feat: Added guard rule", "imperative"),
    ("feat: adding guard rule", "imperative"),
    ("feat: Add guard rule", "lower-case"),
    ("feature: add x", "not in"),
    ("feat: add x.", "trailing period"),
    ("feat: " + "x" * 80, "max 72"),
    ("feat: add x\nbody right under subject", "blank line"),
    ("feat: add x\n\nFixes #12", "closing keyword `Fixes #12`"),
    ("feat: add x\n\ncloses kacper38/repo#3", "closing keyword"),
    ("feat: add x\n\nsome prose\nCo-Authored-By: A <a@b>", "trailer block mixes"),
    ("", "empty"),
    ("Merge stuff together", "subject must be"),
    ("Revert the thing", "subject must be"),
]


@pytest.mark.parametrize("msg", OK, ids=lambda m: m.splitlines()[0][:40])
def test_accepted(msg):
    assert cm.problems(msg) == []


@pytest.mark.parametrize("msg,needle", BAD, ids=lambda m: str(m).splitlines()[0][:40] if m else "empty")
def test_rejected(msg, needle):
    probs = cm.problems(msg)
    assert probs and any(needle in p for p in probs), probs


@pytest.mark.parametrize("msg,closing", [
    ("feat: add x\n\nFixes AB#12", "Fixes AB#12"),
    ("feat: add x\n\nresolves: ab#7", "resolves: ab#7"),
    ("feat: add x\n\nCloses AB#3, see #4", "Closes AB#3"),
])
def test_azure_boards_closing_form_is_rejected(msg, closing):
    assert f"closing keyword `{closing}` closes an issue behind the tracker; write `Refs #N`" in cm.problems(msg)


def test_azure_boards_link_mention_passes():
    assert cm.problems("feat: add x\n\nRefs AB#12") == []


def test_refs_is_not_a_closing_keyword():
    assert cm.problems("feat: add x\n\nRefs #12, see also #13") == []


def test_hook_file_and_cli(tmp_path):
    f = tmp_path / "MSG"
    f.write_text("feat: add x\n")
    assert cm.main([str(f)]) == 0
    f.write_text("Fixes #12\n")
    assert cm.main([str(f)]) == 1
    assert cm.main(["--message", "fix: x"]) == 0
    assert cm.main([]) == 2


def test_range_check_in_a_tmp_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (tmp_path / "a").write_text("1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "feat: start"], check=True, env={**env, **dict(
        PATH="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")})
    for content, msg in (("2", "Fixed it"), ("3", "fix: mend it")):
        (tmp_path / "a").write_text(content)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-am", msg], check=True, env={**env, **dict(
            PATH="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")})
    r = subprocess.run(["python3", str(SRC), "--range", "HEAD~2..HEAD"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 1 and "1 rejected" in r.stderr and "2 commit(s) checked" in r.stderr


def test_githooks_shim_exists_and_is_executable():
    shim = SRC.parents[1] / ".githooks" / "commit-msg"
    assert shim.exists() and shim.stat().st_mode & 0o111


def test_verbose_commit_diff_below_scissors_is_ignored():
    raw = ("feat: add x\n\nbody\n\n# Please enter the commit message\n"
           "# ------------------------ >8 ------------------------\n"
           "# Do not modify or remove the line above.\n"
           "diff --git a/t.py b/t.py\n+# Fixes #12 in a comment inside the diff\n+Co-Authored-By: not a trailer\n")
    assert cm.problems(raw) == []


def test_fixups_pass_the_hook_but_not_the_range_gate():
    assert cm.problems("fixup! feat: x") == []
    probs = cm.problems("fixup! feat: x", allow_fixups=False)
    assert probs == ["fixup!/squash! commits must be squashed before the PR gate"]

