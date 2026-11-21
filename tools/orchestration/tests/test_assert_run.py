"""assert_run.py (plan step 2.3): the D4 post-step on run files, the worker result of D1, and merge-ready.

The check functions take parsed data; the gather functions (git, gh, files) are patched or fed a temporary git
repository. No test touches the network.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
RUNS = HERE / "fixtures" / "run"
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools" / "review"))
import fresh_review  # noqa: E402  the receipt naming scheme the merge-ready check must follow

SHA = "a" * 40
OTHER = "b" * 40


@pytest.fixture(scope="module")
def ar():
    spec = importlib.util.spec_from_file_location("assert_run", HERE.parent / "assert_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_mode(ar, name):
    return ar.check_run(ar.load_messages(str(RUNS / name)), name)


def fails(problems):
    return [p for p in problems if p.startswith("FAIL: ")]


def gaps(problems):
    return [p for p in problems if p.startswith("GAP: ")]


# --- mode run -------------------------------------------------------------------------------------------------------

def test_success_passes_with_result_index_one(ar):
    assert run_mode(ar, "success.json") == []


def test_denial_fails_naming_the_tool(ar):
    problems = run_mode(ar, "denial.json")
    assert len(problems) == 1 and problems[0].startswith("FAIL: ") and "Workflow" in problems[0]


def test_null_stage_fails_naming_key_and_index(ar):
    problems = run_mode(ar, "null-stage.json")
    assert len(fails(problems)) == 2 and not gaps(problems)
    assert any('"review"' in p for p in problems) and any("stages[1]" in p for p in problems)


def test_background_outstanding_fails_on_the_last_of_two_results(ar):
    msgs = ar.load_messages(str(RUNS / "background-outstanding.jsonl"))
    assert sum(1 for m in msgs if m.get("type") == "result") == 2
    problems = ar.check_run(msgs, "x")
    assert len(fails(problems)) == 2 and not gaps(problems)
    assert any("subagent" in p for p in problems) and any("queued" in p for p in problems)


@pytest.mark.parametrize("name", ["missing-output.jsonl", "not-json.txt", "no-such-file.json"])
def test_no_result_message_is_a_gap(ar, name):
    assert run_mode(ar, name) == [f"GAP: no result message in {name}"]


def test_error_subtype_fails(ar):
    msg = json.loads((RUNS / "success.json").read_text())
    msg.update(subtype="error_max_turns", is_error=True)
    assert len(fails(ar.check_run([msg], "x"))) == 1


def test_denial_on_an_earlier_result_fails_and_missing_field_is_a_gap(ar):
    good = json.loads((RUNS / "success.json").read_text())
    early = dict(good, permission_denials=[{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {}}])
    last = {k: v for k, v in good.items() if k != "permission_denials"}
    problems = ar.check_run([early, last], "x")
    assert len(fails(problems)) == 1 and "Bash" in fails(problems)[0]
    assert len(gaps(problems)) == 1 and "permission_denials" in gaps(problems)[0]


@pytest.mark.parametrize("drop", ["structured_output", "subagent_stats"])
def test_missing_structured_output_or_stats_is_a_gap(ar, drop):
    msg = json.loads((RUNS / "success.json").read_text())
    msg[drop] = None
    problems = ar.check_run([msg], "x")
    assert len(problems) == 1 and problems[0].startswith("GAP: ")


def test_run_main_prints_problems_and_summary(ar, capsys):
    assert ar.main(["run", str(RUNS / "denial.json")]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "assert_run run: FAIL (1 problems)" and lines[0].startswith("FAIL: ")
    assert ar.main(["run", str(RUNS / "success.json")]) == 0
    assert capsys.readouterr().out.splitlines() == ["assert_run run: PASS"]


@pytest.mark.parametrize("argv", [[], ["run"], ["frob", "x"], ["merge-ready", "abc"], ["merge-ready", "0"]])
def test_usage_exits_2(ar, argv):
    with pytest.raises(SystemExit) as exc:
        ar.main(argv)
    assert exc.value.code == 2


# --- mode worker ----------------------------------------------------------------------------------------------------

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    for n in (1, 2):
        (r / "f.txt").write_text(f"{n}\n")
        git(r, "add", "f.txt")
        git(r, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", f"c{n}")
    git(r, "branch", "feat/x")
    return r


def worker(head, checks=None, **kw):
    data = {"schema": "worker-result/1", "branch": "feat/x", "head": head,
            "checks": checks if checks is not None else [{"command": "pytest -q", "exit_code": 0}],
            "not_verified": ["the live run"]}
    data.update(kw)
    return data


def write_worker(tmp_path, data):
    p = tmp_path / "result.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_worker_good_passes_and_prints_not_verified(ar, repo, tmp_path, capsys):
    path = write_worker(tmp_path, worker(git(repo, "rev-parse", "HEAD")))
    assert ar.main(["worker", path, "--repo", str(repo)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["NOT VERIFIED: the live run", "assert_run worker: PASS"]


def test_worker_head_behind_the_tip_fails(ar, repo, tmp_path, capsys):
    behind, tip = git(repo, "rev-parse", "HEAD~1"), git(repo, "rev-parse", "HEAD")
    assert ar.main(["worker", write_worker(tmp_path, worker(behind)), "--repo", str(repo)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert f"FAIL: head {behind} is not the tip {tip} of feat/x" in out
    assert "NOT VERIFIED: the live run" in out and out[-1] == "assert_run worker: FAIL (1 problems)"


def test_worker_branch_from_origin_when_no_local_branch(ar, repo):
    tip = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/feat/y", tip)
    assert ar.branch_tip(str(repo), "feat/y") == tip
    assert ar.branch_tip(str(repo), "feat/none") is None


def test_worker_non_zero_check_fails_naming_it(ar):
    checks = [{"command": "ruff check tools", "exit_code": 0}, {"command": "pytest -q", "exit_code": 1},
              {"command": "true", "exit_code": False}]
    problems = ar.check_worker(worker(SHA, checks), SHA)
    assert len(fails(problems)) == 2 and not gaps(problems)
    assert any("pytest -q" in p for p in problems) and any("true" in p for p in problems)


@pytest.mark.parametrize("data", [None, [], {"schema": "worker-result/2"}])
def test_no_worker_result_is_a_gap(ar, data):
    assert ar.check_worker(data, SHA) == ["GAP: no worker result"]


def test_worker_main_on_a_missing_file_is_a_gap(ar, tmp_path, capsys):
    assert ar.main(["worker", str(tmp_path / "none.json"), "--repo", str(tmp_path)]) == 1
    assert capsys.readouterr().out.splitlines() == ["GAP: no worker result", "assert_run worker: FAIL (1 problems)"]


@pytest.mark.parametrize("field,value", [("branch", ""), ("head", "A" * 40), ("head", "abc"), ("checks", []),
                                         ("not_verified", "none")])
def test_worker_bad_field_is_a_gap_naming_it(ar, field, value):
    problems = ar.check_worker(worker(SHA, **{field: value}), SHA)
    assert any(p.startswith("GAP: ") and field in p for p in problems)


def test_worker_branch_not_found_is_a_gap(ar):
    assert ar.check_worker(worker(SHA), None) == ["GAP: branch feat/x not found locally or at origin"]


# --- mode merge-ready -----------------------------------------------------------------------------------------------

def pr(**kw):
    data = {"number": 7, "state": "OPEN", "headRefName": "feat/x", "headRefOid": SHA,
            "statusCheckRollup": [
                {"__typename": "CheckRun", "name": "test (3.9)", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"__typename": "CheckRun", "name": "docs", "status": "COMPLETED", "conclusion": "SKIPPED"},
                {"__typename": "StatusContext", "context": "ci/ext", "state": "SUCCESS"}],
            "files": [{"path": "DECISIONS.md", "additions": 3, "deletions": 0},
                      {"path": "tools/x.py", "additions": 10, "deletions": 1}]}
    data.update(kw)
    return data


GOOD_RECEIPT = ("x.json", {"sha": SHA, "verdict": "COMMENT"})


def test_merge_ready_good_has_no_problem(ar):
    assert ar.check_merge(pr(), SHA, SHA, GOOD_RECEIPT) == []
    assert ar.check_merge(pr(), SHA, None, GOOD_RECEIPT) == []


def test_merge_ready_head_with_no_receipt_fails(ar):
    assert ar.check_merge(pr(), SHA, SHA, None) == [f"FAIL: no fresh-review receipt for {SHA}"]


@pytest.mark.parametrize("receipt", [("x.json", {"sha": SHA, "verdict": "BLOCKER"}),
                                     ("x.json", {"sha": OTHER, "verdict": "APPROVE"}), ("x.json", None)])
def test_merge_ready_bad_receipt_fails(ar, receipt):
    assert len(fails(ar.check_merge(pr(), SHA, SHA, receipt))) == 1


def test_merge_ready_tips(ar):
    assert len(fails(ar.check_merge(pr(), OTHER, SHA, GOOD_RECEIPT))) == 1
    assert len(fails(ar.check_merge(pr(), SHA, OTHER, GOOD_RECEIPT))) == 1
    assert len(gaps(ar.check_merge(pr(), None, None, GOOD_RECEIPT))) == 1
    assert len(gaps(ar.check_merge(pr(headRefOid="xyz"), SHA, None, None))) == 1


def test_merge_ready_state_and_gh_output(ar):
    assert len(fails(ar.check_merge(pr(state="MERGED"), SHA, None, GOOD_RECEIPT))) == 1
    assert len(gaps(ar.check_merge(None, None, None, None))) == 1
    assert len(gaps(ar.check_merge({"number": 7}, None, None, None))) == 1


@pytest.mark.parametrize("rollup", [
    [],
    [{"__typename": "CheckRun", "name": "t", "status": "IN_PROGRESS", "conclusion": ""}],
    [{"__typename": "CheckRun", "name": "t", "status": "COMPLETED", "conclusion": "FAILURE"}],
    [{"__typename": "StatusContext", "context": "c", "state": "PENDING"}],
    [{"__typename": "Other", "name": "t"}],
    [{"__typename": "CheckRun", "name": "t", "status": "COMPLETED", "conclusion": "SKIPPED"}],
])
def test_merge_ready_checks_not_green_fail(ar, rollup):
    assert len(fails(ar.check_merge(pr(statusCheckRollup=rollup), SHA, None, GOOD_RECEIPT))) == 1


@pytest.mark.parametrize("files", [[], [{"path": "DECISIONS.md", "additions": 0, "deletions": 2}],
                                   [{"path": "docs/DECISIONS.md", "additions": 1}]])
def test_merge_ready_without_a_decisions_line_fails(ar, files):
    assert fails(ar.check_merge(pr(files=files), SHA, None, GOOD_RECEIPT)) == [
        "FAIL: the pull request adds no DECISIONS.md line"]


def test_newest_receipt_follows_fresh_review_naming(ar, tmp_path):
    folder = str(tmp_path)
    assert ar.read_receipt(folder, SHA) is None
    first = fresh_review.receipt_path(folder, SHA)
    pathlib.Path(first).write_text(json.dumps({"sha": SHA, "verdict": "BLOCKER"}))
    second = fresh_review.receipt_path(folder, SHA)
    assert second != first
    pathlib.Path(second).write_text(json.dumps({"sha": SHA, "verdict": "APPROVE"}))
    pathlib.Path(fresh_review.receipt_path(folder, OTHER)).write_text("{}")
    name, data = ar.read_receipt(folder, SHA)
    assert name == pathlib.Path(second).name and data["verdict"] == "APPROVE"
    pathlib.Path(fresh_review.receipt_path(folder, SHA)).write_text("not json")
    assert ar.read_receipt(folder, SHA)[1] is None


def test_merge_ready_main_prints_the_merge_command_only_on_pass(ar, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ar, "gh_pr_view", lambda n, repo: pr(number=n))
    monkeypatch.setattr(ar, "remote_tip", lambda repo, b: SHA)
    monkeypatch.setattr(ar, "branch_ref", lambda repo, ref: None)
    monkeypatch.setattr(ar, "receipt_folder", lambda repo: str(tmp_path))
    assert ar.main(["merge-ready", "7", "--repo", str(tmp_path)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out == [f"FAIL: no fresh-review receipt for {SHA}", "assert_run merge-ready: FAIL (1 problems)"]
    pathlib.Path(fresh_review.receipt_path(str(tmp_path), SHA)).write_text(json.dumps({"sha": SHA,
                                                                                       "verdict": "APPROVE"}))
    assert ar.main(["merge-ready", "7", "--repo", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == [f"gh pr merge 7 --merge --match-head-commit {SHA}",
                                                    "assert_run merge-ready: PASS"]


def test_receipt_folder_is_the_git_dir(ar, repo):
    assert ar.receipt_folder(str(repo)) == str(repo / ".git" / "fresh-review")
