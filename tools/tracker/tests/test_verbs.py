"""Verbs against the FakeBackend: guards first, one comment, then one label change."""
import io

import pytest

NEW = ["new", "--title", "Do the thing", "--ac", "tests pass", "--ac", "docs updated", "--scope", "the CLI",
       "--scope-limit", "no UI", "--source", "plan step 2.5"]


def run(tracker, fb, argv, human=False, cwd=None):
    out = io.StringIO()
    code = tracker.main(argv, backend=fb, human=human, out=out, cwd=cwd)
    return code, out.getvalue()


def statuses(issue):
    return [lb for lb in issue.labels if lb.startswith("status/")]


@pytest.fixture
def fb(tracker):
    return tracker.FakeBackend(user="agent")


def make_pr(tracker, fb, number=1, head="step-x", body="Refs #1", merged=True, merged_by="kacper", sha="abc123",
            checks=("success",), files=("DECISIONS.md",)):
    url = f"https://fake/pull/{number}"
    fb.prs[url] = tracker.PR(number, url, "t", body, head, "main", "merged" if merged else "open", merged,
                            merged_by if merged else "", sha if merged else "", list(files))
    fb.checks[sha] = [tracker.Check(f"c{i}", "completed", c, f"https://fake/checks/{i}") for i, c in enumerate(checks)]
    return url


def ready_issue(tracker, fb):
    assert run(tracker, fb, NEW)[0] == 0
    assert run(tracker, fb, ["owner", "ready", "1"], human=True)[0] == 0
    return fb.get_issue(1)


def test_new_creates_backlog_issue_with_dor_body(tracker, fb):
    code, out = run(tracker, fb, NEW)
    assert code == 0 and "created #1 in status/backlog" in out
    issue = fb.get_issue(1)
    assert set(issue.labels) == {"type/todo", "status/backlog"}
    assert tracker.definition_of_ready(issue.body) == []


def test_new_without_ac_is_refused(tracker, fb):
    argv = [a for a in NEW if a not in ("--ac", "tests pass", "docs updated")]
    code, out = run(tracker, fb, argv)
    assert code == 2 and "acceptance criterion" in out
    assert fb.issues == {}


def test_claim_on_backlog_is_refused(tracker, fb):
    run(tracker, fb, NEW)
    code, out = run(tracker, fb, ["claim", "1"])
    assert code == 2 and "not ready" in out and "owner ready 1" in out
    assert statuses(fb.get_issue(1)) == ["status/backlog"]


def test_owner_verbs_refuse_without_a_human(tracker, fb):
    run(tracker, fb, NEW)
    for argv in (["owner", "ready", "1"], ["owner", "done", "1"], ["owner", "labels-sync"]):
        code, out = run(tracker, fb, argv, human=False)
        assert code == 2 and "no TTY" in out, argv


def test_owner_ready_freezes_the_body(tracker, fb):
    issue = ready_issue(tracker, fb)
    assert statuses(issue) == ["status/ready"]
    ready = tracker.marks(issue, "ready")
    assert ready and ready[0]["body_sha256"] == tracker.body_hash(issue.body)


def test_claim_leaves_exactly_one_status_and_records_the_branch(tracker, fb, tmp_path):
    ready_issue(tracker, fb)
    fb.log.clear()
    code, out = run(tracker, fb, ["claim", "1", "--branch", "step-x"], cwd=str(tmp_path))
    assert code == 0 and "step-x" in out
    issue = fb.get_issue(1)
    assert statuses(issue) == ["status/in-progress"]
    claim = tracker.marks(issue, "claim")[0]
    assert claim["by"] == "agent" and claim["branch"] == "step-x" and claim["ts"].endswith("Z")
    assert [e[0] for e in fb.log] == ["comment", "add", "remove"], "comment first, then add, then remove siblings"


def test_one_in_progress_per_actor(tracker, fb, tmp_path):
    ready_issue(tracker, fb)
    run(tracker, fb, NEW)
    run(tracker, fb, ["owner", "ready", "2"], human=True)
    assert run(tracker, fb, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))[0] == 0
    code, out = run(tracker, fb, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))
    assert code == 2 and "already has #1 in progress" in out
    assert statuses(fb.get_issue(2)) == ["status/ready"]


def test_one_in_progress_per_actor_on_a_listing_without_comments(tracker, fb, tmp_path):
    """#26: GitHub's `issue list` and the ADO batch read carry no comments, so the claim markers were invisible."""
    import dataclasses

    class Listing(type(fb)):
        def list_issues(self, labels=None, state="open"):
            return [dataclasses.replace(i, comments=[]) for i in super().list_issues(labels, state)]

    live = Listing(user="agent")
    ready_issue(tracker, live)
    run(tracker, live, NEW)
    run(tracker, live, ["owner", "ready", "2"], human=True)
    assert run(tracker, live, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))[0] == 0
    assert all(not i.comments for i in live.list_issues(["status/in-progress"])), "the listing hides the markers"
    code, out = run(tracker, live, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))
    assert code == 2 and "already has #1 in progress" in out
    assert statuses(live.get_issue(2)) == ["status/ready"]


def test_block_needs_a_path_or_field(tracker, fb, tmp_path):
    ready_issue(tracker, fb)
    run(tracker, fb, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))
    code, out = run(tracker, fb, ["block", "1", "--question", "what now?"])
    assert code == 2 and "path or field" in out
    code, out = run(tracker, fb, ["block", "1", "--question", "should config.timeout stay 30s?"])
    assert code == 0 and statuses(fb.get_issue(1)) == ["status/blocked"]
    assert run(tracker, fb, ["owner", "ready", "1"], human=True)[0] == 0, "blocked -> ready is the human's move"


def test_review_guards(tracker, fb, tmp_path):
    ready_issue(tracker, fb)
    run(tracker, fb, ["claim", "1", "--branch", "step-x"], cwd=str(tmp_path))
    url = make_pr(tracker, fb, body="Fixes #1", merged=False)
    code, out = run(tracker, fb, ["review", "1", "--pr", url])
    assert code == 2 and "closing keyword `Fixes #1`" in out
    url = make_pr(tracker, fb, number=2, head="other", merged=False)
    code, out = run(tracker, fb, ["review", "1", "--pr", url])
    assert code == 2 and "`other`" in out and "`step-x`" in out
    url = make_pr(tracker, fb, number=3, body="no reference", merged=False)
    code, out = run(tracker, fb, ["review", "1", "--pr", url])
    assert code == 2 and "Refs #1" in out
    code, out = run(tracker, fb, ["review", "1", "--pr", "https://fake/pull/99"])
    assert code == 2 and "no pull request" in out
    assert statuses(fb.get_issue(1)) == ["status/in-progress"]
    url = make_pr(tracker, fb, number=4, merged=False)
    code, out = run(tracker, fb, ["review", "1", "--pr", url])
    assert code == 0 and statuses(fb.get_issue(1)) == ["status/review"]
    assert tracker.marks(fb.get_issue(1), "review")[0]["pr"] == url


def in_review(tracker, fb, tmp_path, **pr):
    ready_issue(tracker, fb)
    run(tracker, fb, ["claim", "1", "--branch", "step-x"], cwd=str(tmp_path))
    url = make_pr(tracker, fb, **pr)
    assert run(tracker, fb, ["review", "1", "--pr", url])[0] == 0
    return url


def test_owner_done_refuses_unmerged_bot_merged_and_red(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, merged=False)
    code, out = run(tracker, fb, ["owner", "done", "1"], human=True)
    assert code == 2 and "not merged" in out
    fb.prs["https://fake/pull/1"].merged, fb.prs["https://fake/pull/1"].merged_by = True, "github-actions[bot]"
    fb.prs["https://fake/pull/1"].merge_sha = "abc123"
    code, out = run(tracker, fb, ["owner", "done", "1"], human=True)
    assert code == 2 and "not a human" in out
    fb.prs["https://fake/pull/1"].merged_by = "kacper"
    fb.checks["abc123"][0].conclusion = "failure"
    code, out = run(tracker, fb, ["owner", "done", "1"], human=True)
    assert code == 2 and "check `c0` is failure" in out
    assert fb.get_issue(1).state == "open" and statuses(fb.get_issue(1)) == ["status/review"]


def test_owner_done_requires_checked_or_waived_ac_and_frozen_body(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path)
    code, out = run(tracker, fb, ["owner", "done", "1"], human=True)
    assert code == 2 and "criterion 1 unchecked" in out and "criterion 2 unchecked" in out
    issue = fb.issues[1]
    issue.body = issue.body.replace("- [ ] tests pass", "- [x] tests pass")
    code, out = run(tracker, fb, ["owner", "done", "1", "--waive", "2", "docs come with 2.7"], human=True)
    assert code == 0, "ticking a box is not a change of the record"
    fb2 = tracker.FakeBackend(user="agent")
    in_review(tracker, fb2, tmp_path)
    fb2.issues[1].body += "\nscope creep\n"
    code, out = run(tracker, fb2, ["owner", "done", "1", "--waive", "1", "a", "--waive", "2", "b"], human=True)
    assert code == 2 and "body changed since ready" in out


def test_owner_done_happy_path_writes_once_then_closes(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, checks=("success", "skipped"))
    fb.log.clear()
    argv = ["owner", "done", "1", "--waive", "1", "covered by CI", "--waive", "2", "n/a"]
    code, out = run(tracker, fb, argv, human=True)
    assert code == 0 and "done and closed" in out
    issue = fb.get_issue(1)
    assert issue.state == "closed" and statuses(issue) == ["status/done"]
    assert [e[0] for e in fb.log] == ["comment", "add", "remove", "close"]
    done = tracker.marks(issue, "done")[0]
    assert done["merge_sha"] == "abc123" and done["merged_by"] == "kacper" and done["decisions_md"] is True
    text = issue.comments[-1].body
    assert "c0: success" in text and "Waived acceptance criterion 1: covered by CI" in text


def test_labels_sync_creates_then_updates_never_deletes(tracker, fb):
    fb.labels["custom"] = ("ffffff", "keep me")
    code, out = run(tracker, fb, ["owner", "labels-sync"], human=True)
    assert code == 0 and "12 created, 0 updated, 0 deleted" in out
    code, out = run(tracker, fb, ["owner", "labels-sync"], human=True)
    assert "0 created, 12 updated" in out and "custom" in fb.list_labels()


def test_note_comments_without_status_change(tracker, fb):
    run(tracker, fb, NEW)
    code, out = run(tracker, fb, ["note", "1", "found a flaky test in x"])
    assert code == 0 and statuses(fb.get_issue(1)) == ["status/backlog"]
    assert tracker.marks(fb.get_issue(1), "note")[0]["by"] == "agent"


def test_two_status_labels_block_every_write(tracker, fb):
    ready_issue(tracker, fb)
    fb.add_labels(1, ["status/blocked"])
    code, out = run(tracker, fb, ["claim", "1"])
    assert code == 2 and "2 status labels" in out
    code, out = run(tracker, fb, ["note", "1", "x"])
    assert code == 2


def test_list_and_show(tracker, fb):
    ready_issue(tracker, fb)
    run(tracker, fb, NEW)
    code, out = run(tracker, fb, ["list"])
    assert code == 0 and "#1" in out and "ready" in out and "#2" in out and "backlog" in out
    code, out = run(tracker, fb, ["list", "--status", "ready"])
    assert "#2" not in out
    code, out = run(tracker, fb, ["show", "1"])
    assert code == 0 and "1. [ ] tests pass" in out and "ready " in out


def test_help_and_bad_usage(tracker, fb):
    assert run(tracker, fb, [])[1].startswith("tracker —")
    assert run(tracker, fb, ["help"])[0] == 0
    assert run(tracker, fb, ["owner"])[0] == 1
    assert run(tracker, fb, ["bogus"])[0] == 1
