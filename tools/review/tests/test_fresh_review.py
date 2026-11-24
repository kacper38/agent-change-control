"""fresh-review against a fake `claude` binary: screening first, receipt always, verdict drives the exit code."""
import hashlib
import io
import json
import os
import pathlib
import stat
import subprocess

import pytest

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
       "PATH": os.environ.get("PATH", "")}


def repo_with_branch(tmp_path, change="assert x == 1  # touched\n"):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "test_x.py").write_text("def test_x():\n    x = 1\n    assert x == 1\n")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", "feat: start"], check=True, env=ENV)
    subprocess.run(["git", "-C", str(r), "switch", "-q", "-c", "step-x"], check=True)
    (r / "test_x.py").write_text("def test_x():\n    x = 1\n    " + change)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-am", "fix: weaken"], check=True, env=ENV)
    return r


def fake_claude(tmp_path, verdict):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    marker = tmp_path / "called"
    payload = {"type": "result", "is_error": False, "total_cost_usd": 0.42, "duration_ms": 1234,
               "modelUsage": {"claude-opus-4-1": {"inputTokens": 10}}, "result": "x", "structured_output": verdict}
    script = d / "claude"
    script.write_text(f"#!/bin/sh\ncat > /dev/null\ntouch '{marker}'\ncat <<'EOF'\n{json.dumps(payload)}\nEOF\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script), marker


def test_blocker_writes_receipt_and_exits_1(review, tmp_path):
    r = repo_with_branch(tmp_path, change="assert True\n")
    finding = {"severity": "BLOCKER", "file": "test_x.py", "line": 3, "summary": "assert True replaces assert x == 1"}
    verdict = {"verdict": "BLOCKER", "summary": "assertion weakened", "findings": [finding]}
    claude, marker = fake_claude(tmp_path, verdict)
    out = io.StringIO()
    code = review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=out)
    assert code == 1 and marker.exists()
    text = out.getvalue()
    assert "BLOCKER (1 findings)" in text and "test_x.py:3" in text and "$0.42" in text
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    receipt = json.loads((r / ".git" / "fresh-review" / f"{head}.json").read_text())
    assert receipt["verdict"] == "BLOCKER" and receipt["sha"] == head and receipt["base"] == "main"
    assert receipt["models"] == ["claude-opus-4-1"] and len(receipt["diff_sha256"]) == 64
    assert receipt["prompt_file"].endswith("tools/review/prompt.md")


def test_approve_exits_0(review, tmp_path):
    r = repo_with_branch(tmp_path)
    claude, _ = fake_claude(tmp_path, {"verdict": "APPROVE", "summary": "", "findings": []})
    out = io.StringIO()
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=out) == 0
    assert out.getvalue().startswith("fresh-review: APPROVE (0 findings)")


def test_planted_secret_is_held_before_any_call(review, tmp_path):
    r = repo_with_branch(tmp_path, change="token = 'ghp_" + "A1" * 18 + "'\n")
    claude, marker = fake_claude(tmp_path, {"verdict": "APPROVE", "summary": "", "findings": []})
    out = io.StringIO()
    code = review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=out)
    assert code == 3 and "held by the egress screen" in out.getvalue() and "secret:github-token" in out.getvalue()
    assert not marker.exists(), "the model was never called"


def test_dry_run_and_empty_diff(review, tmp_path):
    r = repo_with_branch(tmp_path)
    out = io.StringIO()
    assert review.main(["--base", "main", "--dry-run"], cwd=str(r), out=out) == 0 and "dry run" in out.getvalue()
    out = io.StringIO()
    assert review.main(["--base", "HEAD", "--claude-bin", "/nonexistent"], cwd=str(r), out=out) == 0
    assert "nothing to review" in out.getvalue()


def test_model_failure_is_exit_2(review, tmp_path):
    r = repo_with_branch(tmp_path)
    out = io.StringIO()
    assert review.main(["--base", "main", "--claude-bin", "/nonexistent/claude"], cwd=str(r), out=out) == 2
    assert out.getvalue().startswith("fresh-review: error:")


def test_work_instructions_carry_the_same_prompt(review):
    root = pathlib.Path(review.HERE).parents[1]
    prompt = (root / "tools" / "review" / "prompt.md").read_text().strip()
    instr = (root / ".github" / "instructions" / "review.instructions.md").read_text()
    body = instr.split("---", 2)[2].strip()
    assert body == prompt, "review.instructions.md must stay a copy of prompt.md (plus the applyTo frontmatter)"
    assert instr.startswith("---\napplyTo:")


def test_rerun_never_overwrites_a_receipt(review, tmp_path):
    r = repo_with_branch(tmp_path)
    blocker = {"verdict": "BLOCKER", "summary": "s", "findings": []}
    claude, _ = fake_claude(tmp_path, blocker)
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=io.StringIO()) == 1
    claude, _ = fake_claude(tmp_path, {"verdict": "APPROVE", "summary": "", "findings": []})
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=io.StringIO()) == 0
    receipts = sorted(p.name for p in (r / ".git" / "fresh-review").iterdir())
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert receipts == [f"{head}.2.json", f"{head}.json"]
    assert json.loads((r / ".git" / "fresh-review" / f"{head}.json").read_text())["verdict"] == "BLOCKER"


def test_malformed_model_answer_is_exit_2(review, tmp_path):
    r = repo_with_branch(tmp_path)
    for bad in (None, {"verdict": "MAYBE", "findings": []}, {"verdict": "APPROVE", "findings": "none"}):
        claude, _ = fake_claude(tmp_path, bad)
        out = io.StringIO()
        assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=out) == 2, bad
        assert "no usable structured verdict" in out.getvalue()


def test_blocker_finding_overrides_a_softer_verdict(review, tmp_path):
    r = repo_with_branch(tmp_path)
    finding = {"severity": "BLOCKER", "file": "test_x.py", "line": 3, "summary": "weakened"}
    claude, _ = fake_claude(tmp_path, {"verdict": "COMMENT", "summary": "s", "findings": [finding]})
    out = io.StringIO()
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=out) == 1
    assert out.getvalue().startswith("fresh-review: BLOCKER")
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    receipt = json.loads((r / ".git" / "fresh-review" / f"{head}.json").read_text())
    assert receipt["verdict"] == "BLOCKER" and receipt["verdict_as_answered"] == "COMMENT"
    assert review.effective_verdict("APPROVE", [{"severity": "MINOR"}]) == "COMMENT"
    assert review.effective_verdict("APPROVE", []) == "APPROVE"



def rev(r, what):
    return subprocess.run(["git", "-C", str(r), "rev-parse", what], capture_output=True, text=True,
                          check=True).stdout.strip()


def newest_receipt(r):
    head = rev(r, "HEAD")
    d = r / ".git" / "fresh-review"
    n = 1
    while (d / f"{head}.{n + 1}.json").exists():
        n += 1
    path = d / (f"{head}.json" if n == 1 else f"{head}.{n}.json")
    return path, json.loads(path.read_text())


def test_hash_ignores_a_global_diff_config(review, tmp_path, monkeypatch):
    r = repo_with_branch(tmp_path)
    (r / "\u00e9.txt").write_text("x\n")  # core.quotePath, which no flag pins, quotes this name or not
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", "feat: name"], check=True, env=ENV)
    approve = {"verdict": "APPROVE", "summary": "", "findings": []}
    claude, _ = fake_claude(tmp_path, approve)
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=io.StringIO()) == 0
    _, plain = newest_receipt(r)
    home = tmp_path / "home"
    home.mkdir()
    cfg = home / ".gitconfig"
    cfg.write_text("[diff]\n\talgorithm = patience\n\tnoprefix = true\n[core]\n\tquotePath = false\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    noprefix = subprocess.run(["git", "-C", str(r), "diff", "main...HEAD"], capture_output=True, text=True).stdout
    assert "--- test_x.py" in noprefix, "the global config really is read by plain git"
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=io.StringIO()) == 0
    _, configured = newest_receipt(r)
    assert configured["diff_sha256"] == plain["diff_sha256"]
    assert review.diff_text(rev(r, "main"), rev(r, "HEAD"), str(r))[0].startswith("diff --git a/test_x.py b/test_x.py")


def test_receipt_diff_command_recomputes_the_hash(review, tmp_path):
    r = repo_with_branch(tmp_path)
    claude, _ = fake_claude(tmp_path, {"verdict": "APPROVE", "summary": "", "findings": []})
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=io.StringIO()) == 0
    _, receipt = newest_receipt(r)
    cmd = receipt["diff_command"]
    assert cmd.startswith("GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git diff --full-index")
    assert f"{rev(r, 'main')}...{rev(r, 'HEAD')}" in cmd
    text = subprocess.run(cmd, shell=True, cwd=str(r), capture_output=True, check=True).stdout
    assert hashlib.sha256(text).hexdigest() == receipt["diff_sha256"]


def test_receipt_carries_the_tree_ids(review, tmp_path):
    r = repo_with_branch(tmp_path)
    claude, _ = fake_claude(tmp_path, {"verdict": "APPROVE", "summary": "", "findings": []})
    assert review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=io.StringIO()) == 0
    _, receipt = newest_receipt(r)
    assert receipt["merge_base"] == rev(r, "main")
    assert receipt["base_tree"] == rev(r, "main^{tree}")
    assert receipt["head_tree"] == rev(r, "HEAD^{tree}")
    assert receipt["base_sha"] == rev(r, "main") and receipt["base"] == "main"


def fake_gh(tmp_path, code=0):
    d = tmp_path / "ghbin"
    d.mkdir(exist_ok=True)
    log = tmp_path / "gh-args"
    body = tmp_path / "gh-body"
    script = d / "gh"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{log}'\ncp \"$5\" '{body}'\nexit {code}\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script), log, body


def test_pr_posts_the_receipt_as_a_comment(review, tmp_path):
    r = repo_with_branch(tmp_path)
    claude, _ = fake_claude(tmp_path, {"verdict": "BLOCKER", "summary": "s", "findings": []})
    gh, log, body = fake_gh(tmp_path)
    out = io.StringIO()
    assert review.main(["--base", "main", "--claude-bin", claude, "--pr", "7", "--gh-bin", gh],
                       cwd=str(r), out=out) == 1
    args = log.read_text().splitlines()
    assert args[:4] == ["pr", "comment", "7", "--body-file"] and len(args) == 5
    path, receipt = newest_receipt(r)
    text = body.read_text()
    assert text.splitlines()[0] == f"<!-- fresh-review-receipt: {rev(r, 'HEAD')} -->"
    assert "BLOCKER" in text.splitlines()[1] and path.name in text.splitlines()[1]
    assert json.loads(text.split("```json\n", 1)[1].rsplit("\n```", 1)[0]) == receipt


def test_a_failed_post_is_exit_2_and_keeps_the_receipt(review, tmp_path):
    r = repo_with_branch(tmp_path)
    claude, _ = fake_claude(tmp_path, {"verdict": "APPROVE", "summary": "", "findings": []})
    for gh in (fake_gh(tmp_path, code=1)[0], str(tmp_path / "no-such-gh")):
        out = io.StringIO()
        assert review.main(["--base", "main", "--claude-bin", claude, "--pr", "7", "--gh-bin", gh],
                           cwd=str(r), out=out) == 2
        path, _ = newest_receipt(r)
        assert path.exists() and path.name in out.getvalue() and "--pr 7 --post-only" in out.getvalue()


def test_an_oversized_comment_is_not_posted(review, tmp_path):
    r = repo_with_branch(tmp_path)
    claude, _ = fake_claude(tmp_path, {"verdict": "APPROVE", "summary": "x" * 70000, "findings": []})
    gh, log, _ = fake_gh(tmp_path)
    out = io.StringIO()
    assert review.main(["--base", "main", "--claude-bin", claude, "--pr", "7", "--gh-bin", gh],
                       cwd=str(r), out=out) == 2
    assert not log.exists(), "gh was never called"
    path, _ = newest_receipt(r)
    assert path.name in out.getvalue() and "--pr 7 --post-only" in out.getvalue()


def test_post_only_posts_the_newest_receipt_without_the_model(review, tmp_path):
    r = repo_with_branch(tmp_path)
    gh, log, body = fake_gh(tmp_path)
    out = io.StringIO()
    assert review.main(["--base", "main", "--pr", "7", "--post-only", "--gh-bin", gh], cwd=str(r), out=out) == 2
    assert not log.exists() and "no receipt" in out.getvalue()
    for verdict in ("BLOCKER", "APPROVE"):
        claude, _ = fake_claude(tmp_path, {"verdict": verdict, "summary": verdict, "findings": []})
        review.main(["--base", "main", "--claude-bin", claude], cwd=str(r), out=io.StringIO())
    out = io.StringIO()
    code = review.main(["--pr", "7", "--post-only", "--gh-bin", gh, "--claude-bin", "/nonexistent/claude"],
                       cwd=str(r), out=out)
    assert code == 0, out.getvalue()
    assert f"{rev(r, 'HEAD')}.2.json" in body.read_text().splitlines()[1]
    with pytest.raises(SystemExit) as exc:
        review.main(["--post-only"], cwd=str(r), out=io.StringIO())
    assert exc.value.code == 2
