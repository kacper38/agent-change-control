"""evidence_export: captures with hashes and tool versions, change records from a fake gh api (plan step 3.7)."""
import hashlib
import io
import json
import os
import shlex
import subprocess
import sys


def run(ev, argv, cwd, gh=None):
    out, err = io.StringIO(), io.StringIO()
    code = ev.main(argv, out=out, err=err, cwd=str(cwd), gh=gh)
    return code, out.getvalue(), err.getvalue()


def test_capture_records_output_hash_exit_code_and_tool_version(ev, tmp_path):
    prog = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    cmd = [sys.executable, "-u", "-c", prog]  # unbuffered: the merged stream keeps the print order
    code, out, err = run(ev, ["capture", "--tag", "r1", "--name", "hello", "--", *cmd], tmp_path)
    assert code == 3 and err == "" and out.startswith("captured hello: exit 3, 8 bytes, sha256 ")
    path = tmp_path / "evidence" / "r1" / "hello.txt"
    assert path.read_bytes() == b"out\nerr\n"
    entries = json.loads((tmp_path / "evidence" / "r1" / "captures.json").read_text())
    assert len(entries) == 1
    e = entries[0]
    assert e["name"] == "hello" and e["exit_code"] == 3 and e["file"] == "hello.txt" and e["bytes"] == 8
    assert e["sha256"] == hashlib.sha256(b"out\nerr\n").hexdigest()
    assert e["tool_version"].startswith("Python 3.") and e["captured_at"].endswith("Z")
    assert e["command"] == shlex.join(cmd)
    argv = ["capture", "--tag", "r1", "--name", "hello", "--", sys.executable, "-c", "print(1)"]
    code, _, _ = run(ev, argv, tmp_path)
    assert code == 0
    entries = json.loads((tmp_path / "evidence" / "r1" / "captures.json").read_text())
    assert [e["name"] for e in entries] == ["hello"] and entries[0]["exit_code"] == 0, "same name: replaced"
    assert run(ev, ["capture", "--tag", "r1", "--name", "../x", "--", "true"], tmp_path)[0] == 2
    assert run(ev, ["capture", "--tag", "r1", "--name", "empty", "--"], tmp_path)[0] == 2
    code, _, err = run(ev, ["capture", "--tag", "r1", "--name", "nope", "--", "/no/such/tool"], tmp_path)
    assert code == 1 and "cannot run" in err


def test_version_line(ev):
    assert ev.version_line([sys.executable, "-c", "pass"]).startswith("Python 3.")
    assert ev.version_line([sys.executable, "-m", "json.tool", "x"]) == "unknown", "a usage error is not a version"
    assert ev.version_line(["/no/such/tool"]) == "unknown"


# --- change records against a fake api -----------------------------------------------------------

SINCE, UNTIL = "2026-10-29T12:00:00Z", "2026-10-29T14:00:00Z"


def pr(number, merged_at, sha, updated_at=None, body="", merged=True):
    return {"number": number, "title": f"pr {number}", "html_url": f"https://x/pull/{number}",
            "merged_at": merged_at if merged else None, "merge_commit_sha": sha, "updated_at": updated_at or merged_at,
            "user": {"login": "agent"}, "head": {"ref": f"step-{number}"}, "base": {"ref": "main"}, "body": body}


def make_api(tracker, in_range_sha="bbb"):
    repo = "o/r"
    pulls = [
        pr(12, "2026-10-29T13:00:00Z", in_range_sha, body="Summary.\n\nRefs #5\nRefs #7"),
        pr(11, "2026-10-29T12:30:00Z", "zzz"),  # merged in the window but not into this range (another branch)
        pr(10, "2026-10-29T12:10:00Z", None, merged=False),
        pr(9, "2026-10-01T10:00:00Z", "yyy"),  # older than the window: the page stops here
        pr(8, "2026-10-29T13:30:00Z", in_range_sha),  # never reached: after the stop
    ]
    issues = {
        5: {"number": 5, "title": "do it", "html_url": "https://x/issues/5", "state": "closed",
            "labels": [{"name": "type/todo"}, {"name": "status/done"}], "created_at": "2026-10-28T09:00:00Z",
            "closed_at": "2026-10-29T13:05:00Z", "closed_by": {"login": "kacper"},
            "body": "## Acceptance criteria\n\n- [x] one\n- [ ] two\n\n## Scope\n\nx\n\n"
                    "Scope limit: y\n\n## Source\n\nz\n"},
        6: {"number": 6, "title": "dropped", "html_url": "https://x/issues/6", "state": "closed",
            "labels": [{"name": "status/dropped"}], "closed_at": "2026-10-29T12:45:00Z",
            "closed_by": {"login": "kacper"}, "body": ""},
        7: {"number": 7, "title": "still open", "html_url": "https://x/issues/7", "state": "open",
            "labels": [{"name": "type/todo"}, {"name": "status/review"}], "closed_at": None, "closed_by": None,
            "body": "- [ ] later"},
    }
    done = tracker.mark("done", by="kacper", merge_sha=in_range_sha, pr="https://x/pull/12") + "\nDone."
    plain = {"user": {"login": "someone"}, "created_at": "2026-10-29T13:06:00Z", "body": "plain comment"}
    # 100 plain comments fill page 1; the done marker is the 101st, visible only when paging continues
    comments = {5: {1: [plain] * 100, 2: [{"user": {"login": "kacper"}, "created_at": "2026-10-29T13:05:00Z",
                                           "body": done}]}}
    calls = []

    def api(path, **params):
        calls.append((path, params))
        if path == f"repos/{repo}/pulls":
            assert params["state"] == "closed" and params["sort"] == "updated" and params["direction"] == "desc"
            return pulls if params.get("page", 1) == 1 else []
        if path == f"repos/{repo}/pulls/12":
            return {"merged_by": {"login": "kacper"}}
        if path == f"repos/{repo}/pulls/12/reviews":
            if params.get("page", 1) > 1:
                return []
            return [{"user": {"login": "reviewer"}, "state": "APPROVED", "submitted_at": "2026-10-29T12:50:00Z",
                     "commit_id": "abc"}]
        if path == f"repos/{repo}/commits/{in_range_sha}/check-runs":
            if params.get("page", 1) > 1:
                return {"total_count": 2, "check_runs": []}
            return {"total_count": 2, "check_runs": [
                {"name": "ci", "status": "completed", "conclusion": "success", "app": {"slug": "github-actions"},
                 "started_at": "2026-10-29T13:01:00Z", "completed_at": "2026-10-29T13:02:00Z",
                 "html_url": "https://x/c/1"},
                {"name": "commit-msg", "status": "completed", "conclusion": "skipped",
                 "app": {"slug": "github-actions"}, "started_at": None, "completed_at": None,
                 "html_url": "https://x/c/2"}]}
        if path == f"repos/{repo}/issues":
            assert params["state"] == "closed" and params["since"]
            if params.get("page", 1) > 1:
                return []
            return [{"number": 13, "closed_at": "2026-10-29T13:00:00Z", "pull_request": {"url": "x"}},
                    {"number": 6, "closed_at": "2026-10-29T12:45:00Z"},
                    {"number": 14, "closed_at": "2026-10-29T15:00:00Z"},  # after `until`
                    {"number": 15, "closed_at": None}]
        if path.startswith(f"repos/{repo}/issues/"):
            n = int(path.split("/")[4])
            if path.endswith("/comments"):
                assert params["per_page"] == 100
                return comments.get(n, {}).get(params.get("page", 1), [])
            return issues[n]
        if path == f"repos/{repo}/rulesets":
            return [{"id": 1, "name": "main"}]
        if path == f"repos/{repo}/rulesets/1":
            return {"id": 1, "name": "main", "target": "branch", "enforcement": "active", "node_id": "noise",
                    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}}, "rules": [{"type": "pull_request"}],
                    "bypass_actors": [], "created_at": "2026-10-29T10:00:00Z", "updated_at": "2026-10-29T10:00:00Z",
                    "_links": {"self": "noise"}}
        raise AssertionError(f"unexpected api call {path} {params}")

    api.calls = calls
    return api


def fake_git(*args):
    if args[0] == "rev-parse":
        return {"v1^{commit}": "aaa", "HEAD^{commit}": "ccc"}[args[1]]
    if args[0] == "log":
        return {"aaa": "2026-10-29T13:00:00+01:00", "ccc": "2026-10-29T15:00:00+01:00"}[args[-1]]
    if args[0] == "rev-list":
        assert args[1] == "aaa..ccc"
        return "ccc\nbbb"
    raise AssertionError(args)


def test_collect_assembles_prs_issues_rulesets_and_captures(ev, tracker, tmp_path):
    (tmp_path / "ok.txt").write_bytes(b"fine\n")
    (tmp_path / "tampered.txt").write_bytes(b"changed\n")
    (tmp_path / "captures.json").write_text(json.dumps([
        {"name": "ok", "file": "ok.txt", "sha256": hashlib.sha256(b"fine\n").hexdigest(), "tool_version": "t 1"},
        {"name": "tampered", "file": "tampered.txt", "sha256": "0" * 64, "tool_version": "t 1"},
        {"name": "gone", "file": "gone.txt", "sha256": "1" * 64, "tool_version": "t 1"},
    ]))
    api = make_api(tracker)
    rec = ev.collect(api, fake_git, "o/r", "v1", "HEAD", str(tmp_path))
    assert rec["range"] == {"from": "v1", "from_sha": "aaa", "to": "HEAD", "to_sha": "ccc", "since": SINCE,
                            "until": UNTIL, "commits": 2}
    assert [p["number"] for p in rec["pull_requests"]] == [12]
    p = rec["pull_requests"][0]
    assert p["merged_by"] == "kacper" and p["author"] == "agent" and p["merge_sha"] == "bbb" and p["refs"] == [5, 7]
    assert p["reviews"][0]["state"] == "APPROVED" and [c["name"] for c in p["checks"]] == ["ci", "commit-msg"]
    assert p["checks"][0]["app"] == "github-actions" and p["checks"][1]["conclusion"] == "skipped"
    assert rec["pull_requests_merged_elsewhere"] == [11]
    assert [i["number"] for i in rec["issues"]] == [5, 6, 7], "referenced by a PR in range, or closed in the window"
    five = rec["issues"][0]
    assert five["type"] == "todo" and five["status"] == "done" and five["closed_by"] == "kacper"
    assert five["acceptance"] == [{"checked": True, "text": "one"}, {"checked": False, "text": "two"}]
    assert five["markers"] == [{"kind": "done", "by": "kacper", "merge_sha": "bbb", "pr": "https://x/pull/12",
                                "author": "kacper"}], "the marker on page 2 of the comments is read"
    assert five["pull_requests"] == [12] and rec["issues"][1]["pull_requests"] == []
    assert rec["issues"][2]["state"] == "open" and rec["issues"][2]["pull_requests"] == [12]
    assert rec["rulesets"] == [{"id": 1, "name": "main", "target": "branch", "enforcement": "active",
                                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
                                "rules": [{"type": "pull_request"}], "bypass_actors": [],
                                "created_at": "2026-10-29T10:00:00Z", "updated_at": "2026-10-29T10:00:00Z"}]
    caps = {c["name"]: c for c in rec["captures"]}
    assert caps["ok"]["intact"] is True and caps["ok"]["sha256_now"] == caps["ok"]["sha256"]
    assert caps["tampered"]["intact"] is False and caps["gone"]["intact"] is False
    assert caps["gone"]["sha256_now"] is None
    assert not any(path.endswith("/pulls/8") for path, _ in api.calls), "paging stopped at the first old PR"
    assert [p for p, q in api.calls if p == "repos/o/r/issues" and q.get("since") == SINCE], "window from the range"


def git(cwd, *args, date=None):
    env = {**os.environ, **({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {})}
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class FakeGh:
    def __init__(self, api):
        self.api = api

    def repo(self):
        return "o/r"

    def __call__(self, path, **params):
        return self.api(path, **params)

    def login(self):
        return "me"


def test_export_cli_writes_the_records_file_with_tool_versions(ev, tracker, tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "a").write_text("a")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "first", date="2026-10-29T13:00:00+01:00")  # the window of make_api
    first = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "b").write_text("b")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "second", date="2026-10-29T15:00:00+01:00")
    head = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "kit-version").write_text("commit: deadbeef\n")
    api = make_api(tracker, in_range_sha=head)
    gh = FakeGh(api)
    code, out, err = run(ev, ["export", "--tag", "rel-1", "--from", first], tmp_path, gh=gh)
    assert code == 0 and err == "", err
    path = tmp_path / "evidence" / "rel-1" / "change-records.json"
    assert out.startswith("wrote evidence/rel-1/change-records.json: 1 pull request(s), 3 issue(s), 1 ruleset(s), ")
    assert out.rstrip().endswith(hashlib.sha256(path.read_bytes()).hexdigest())
    doc = json.loads(path.read_text())
    assert doc["schema"] == ev.SCHEMA and doc["tag"] == "rel-1" and doc["generated_by"] == "me"
    assert doc["repo"] == "o/r" and doc["range"]["since"] == SINCE and doc["range"]["until"] == UNTIL
    assert doc["range"]["from_sha"] == first and doc["range"]["to_sha"] == head and doc["range"]["to"] == "HEAD"
    assert doc["pull_requests"][0]["merge_sha"] == head and doc["captures"] == []
    assert doc["tools"]["evidence_export"] == ev.VERSION and doc["tools"]["tracker"] == tracker.VERSION
    assert doc["tools"]["kit_version"] == "commit: deadbeef" and doc["tools"]["python"] == sys.version.split()[0]
    assert set(doc["tools"]) == {"evidence_export", "tracker", "gh", "git", "python", "kit_version"}
    assert run(ev, ["export", "--tag", "bad tag", "--from", first], tmp_path, gh=gh)[0] == 2
    code, _, err = run(ev, ["export", "--tag", "rel-2", "--from", "no-such-ref"], tmp_path, gh=gh)
    assert code == 1 and "TrackerError" in err
    assert run(ev, [], tmp_path)[0] == 0 and run(ev, ["bogus"], tmp_path)[0] == 2
