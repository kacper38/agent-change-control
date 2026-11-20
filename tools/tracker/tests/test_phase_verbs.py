"""#64 (plan step 1.9): owner verbs for a phase, `owner done --accept-all`, a seat per box.

Written before the code: each test is an expected output of the item's criteria 2-6 and decisions D1-D8.
"""
import io
import json
import os

import pytest
from test_verbs import NEW, make_pr, run, statuses


@pytest.fixture
def fb(tracker):
    return tracker.FakeBackend(user="agent")


def backlog(tracker, fb, n):
    for _ in range(n):
        assert run(tracker, fb, NEW)[0] == 0


def in_review(tracker, fb, tmp_path, n, merged=(), tick=()):
    """Items 1..n in status/review, each on its own branch and PR; `merged` lists the unmerged ones by default."""
    backlog(tracker, fb, n)
    for i in range(1, n + 1):
        assert run(tracker, fb, ["owner", "ready", str(i)], human=True)[0] == 0
        assert run(tracker, fb, ["claim", str(i), "--branch", f"b{i}"], cwd=str(tmp_path))[0] == 0
        url = make_pr(tracker, fb, number=i, head=f"b{i}", body=f"Refs #{i}", sha=f"sha{i}", merged=i not in merged)
        assert run(tracker, fb, ["review", str(i), "--pr", url])[0] == 0
    for i in tick:
        fb.issues[i].body = fb.issues[i].body.replace("- [ ] tests pass", "- [x] tests pass")
    fb.log.clear()


def writes(fb):
    return [e for e in fb.log if e[0] in ("body", "comment", "add", "remove", "close")]


def accept(tracker, fb, argv, answers):
    """Run with an injected input function; returns (code, out, prompts asked)."""
    asked = []

    def ask():
        asked.append(True)
        if not answers:
            raise EOFError
        return answers.pop(0)

    out = io.StringIO()
    code = tracker.main(argv, backend=fb, human=True, out=out, ask=ask)
    return code, out.getvalue(), len(asked)


def seat(box_marker, value):
    box_marker.write_text(json.dumps({"schema": "agent-box/1", "name": "x", "seat": value}), encoding="utf-8")


# -- criterion 2, D1, D2: several numbers, check every item first -----------------------------------------------


def test_owner_ready_takes_several_numbers_in_order(tracker, fb):
    backlog(tracker, fb, 3)
    code, out = run(tracker, fb, ["owner", "ready", "3", "1", "2"], human=True)
    assert code == 0
    assert out.index("#3 ready") < out.index("#1 ready") < out.index("#2 ready")
    assert all(statuses(fb.get_issue(n)) == ["status/ready"] for n in (1, 2, 3))


def test_owner_ready_changes_none_when_one_fails_and_names_each(tracker, fb):
    backlog(tracker, fb, 1)
    fb.create_issue("no fields", "just text", ["type/todo", "status/backlog"])
    backlog(tracker, fb, 1)
    assert run(tracker, fb, ["owner", "ready", "3"], human=True)[0] == 0
    fb.log.clear()
    code, out = run(tracker, fb, ["owner", "ready", "1", "2", "3"], human=True)
    assert code == 2 and "nothing changed" in out
    assert "#1:" not in out
    line2 = next(ln for ln in out.splitlines() if ln.strip().startswith("#2:"))
    assert "acceptance criterion" in line2 and "## Scope" in line2 and "; " in line2, "every reason of #2, one line"
    line3 = next(ln for ln in out.splitlines() if ln.strip().startswith("#3:"))
    assert "ready -> ready" in line3
    assert writes(fb) == []
    assert statuses(fb.get_issue(1)) == ["status/backlog"]


def test_a_number_given_twice_is_refused_before_anything_is_read(tracker):
    class Counting(tracker.FakeBackend):
        reads = 0

        def get_issue(self, number):
            Counting.reads += 1
            return super().get_issue(number)

    fb = Counting(user="agent")
    backlog(tracker, fb, 2)
    Counting.reads = 0
    for argv in (["owner", "ready", "1", "2", "1"], ["owner", "done", "2", "2"]):
        code, out = run(tracker, fb, argv, human=True)
        assert code == 2 and "twice" in out, argv
    assert Counting.reads == 0


def test_owner_done_takes_several_numbers(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 2)
    for i in (1, 2):
        fb.issues[i].body = fb.issues[i].body.replace("- [ ]", "- [x]")
    code, out = run(tracker, fb, ["owner", "done", "1", "2"], human=True)
    assert code == 0 and "#1 done and closed" in out and "#2 done and closed" in out
    assert all(fb.get_issue(n).state == "closed" for n in (1, 2))


def test_owner_done_changes_none_when_one_fails(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 3, merged=(2,))
    for i in (1, 2, 3):
        fb.issues[i].body = fb.issues[i].body.replace("- [ ]", "- [x]")
    fb.issues[3].body += "\nscope creep\n"
    code, out = run(tracker, fb, ["owner", "done", "1", "2", "3"], human=True)
    assert code == 2 and "nothing changed" in out
    assert "#1:" not in out
    assert any(ln.strip().startswith("#2:") and "not merged" in ln for ln in out.splitlines())
    assert any(ln.strip().startswith("#3:") and "body changed since ready" in ln for ln in out.splitlines())
    assert writes(fb) == []
    assert all(fb.get_issue(n).state == "open" and statuses(fb.get_issue(n)) == ["status/review"] for n in (1, 2, 3))


def test_a_forge_error_in_the_write_phase_names_written_and_untouched(tracker):
    class Flaky(tracker.FakeBackend):
        def comment(self, number, body):
            if number == 2 and "tracker:" in body and '"ready"' in body:
                raise tracker.TrackerError("HTTP 502")
            super().comment(number, body)

    fb = Flaky(user="agent")
    backlog(tracker, fb, 3)
    code, out = run(tracker, fb, ["owner", "ready", "1", "2", "3"], human=True)
    assert code == 1 and "HTTP 502" in out
    assert "written: #1" in out and "not touched: #3" in out and "#2" in out
    assert statuses(fb.get_issue(1)) == ["status/ready"]
    assert statuses(fb.get_issue(3)) == ["status/backlog"]


# -- D3: flag combinations ------------------------------------------------------------------------------------


def test_waive_with_several_numbers_and_accept_all_with_waive_are_refused(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 2)
    code, out = run(tracker, fb, ["owner", "done", "1", "2", "--waive", "1", "x"], human=True)
    assert code == 2 and "--waive" in out
    code, out = run(tracker, fb, ["owner", "done", "1", "--accept-all", "--waive", "1", "x"], human=True)
    assert code == 2 and "--accept-all" in out and "--waive" in out
    code, _ = run(tracker, fb, ["owner", "ready", "1", "--accept-all"], human=True)
    assert code == 1, "the flag exists on `owner done` only"
    assert writes(fb) == []


# -- criterion 3, 5, D4: --accept-all ---------------------------------------------------------------------------


def test_accept_all_prints_asks_once_ticks_and_records(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 2, tick=(2,))
    before = {i: fb.issues[i].body for i in (1, 2)}
    frozen = {i: tracker.marks(fb.get_issue(i), "ready")[-1]["body_sha256"] for i in (1, 2)}
    code, out, asked = accept(tracker, fb, ["owner", "done", "1", "2", "--accept-all"], ["accept 2"])
    assert code == 0 and asked == 1
    for i in (1, 2):
        assert f"#{i} Do the thing" in out
        assert f"https://fake/pull/{i}" in out and f"sha{i}" in out and "kacper" in out
    assert "  1. [ ] tests pass" in out and "  2. [ ] docs updated" in out and "  1. [x] tests pass" in out
    assert "c0: success" in out
    assert 'Type "accept 2" to accept every criterion of these 2 items: ' in out
    assert out.index("#2 Do the thing") < out.index('Type "accept 2"')
    for i in (1, 2):
        issue = fb.get_issue(i)
        assert issue.body == before[i].replace("- [ ]", "- [x]"), "only the boxes change"
        assert all(checked for checked, _ in tracker.parse_ac(issue.body))
        assert tracker.body_hash(issue.body) == frozen[i], "the frozen hash holds through the ticks"
        assert issue.state == "closed" and statuses(issue) == ["status/done"]
        done = tracker.marks(issue, "done")[-1]
        assert done["criteria"] == "accepted-all"
        assert ("Acceptance criteria accepted by agent in one confirmation for 2 items (#1, #2)."
                in issue.comments[-1].body)
    assert tracker.marks(fb.get_issue(1), "done")[-1]["ticked"] == [1, 2]
    assert tracker.marks(fb.get_issue(2), "done")[-1]["ticked"] == [2], "a box ticked in the UI is not claimed"
    assert "Ticked by this confirmation: criteria 1, 2." in fb.get_issue(1).comments[-1].body
    assert "Ticked by this confirmation: criterion 2." in fb.get_issue(2).comments[-1].body
    assert [e[0] for e in fb.log if e[1] == 1] == ["body", "comment", "add", "remove", "close"]


@pytest.mark.parametrize("answers", [["accept 1"], ["yes"], ["accept 2 "], []])
def test_accept_all_without_the_exact_answer_changes_nothing(tracker, fb, tmp_path, answers):
    in_review(tracker, fb, tmp_path, 2)
    code, out, asked = accept(tracker, fb, ["owner", "done", "1", "2", "--accept-all"], answers)
    assert code == 2 and asked == 1 and "not confirmed; nothing changed" in out
    assert writes(fb) == []
    assert all(fb.get_issue(n).state == "open" for n in (1, 2))


def test_accept_all_refuses_other_problems_before_any_print(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 2, merged=(2,))
    code, out, asked = accept(tracker, fb, ["owner", "done", "1", "2", "--accept-all"], ["accept 2"])
    assert code == 2 and asked == 0
    assert "not merged" in out and "unchecked" not in out
    assert "Type" not in out and "Do the thing" not in out
    assert writes(fb) == []


def test_accept_all_rereads_and_never_overwrites_a_body_edited_during_the_prompt(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 2)
    edited = fb.issues[1].body + "\n\nScope added while the prompt waited.\n"

    def ask():
        fb.issues[1].body = edited
        return "accept 2"

    out = io.StringIO()
    code = tracker.main(["owner", "done", "1", "2", "--accept-all"], backend=fb, human=True, out=out, ask=ask)
    out = out.getvalue()
    assert code == 1 and "#1" in out and "body changed" in out and "not touched: #2" in out
    assert fb.issues[1].body == edited, "the edit made during the prompt survives"
    assert writes(fb) == []
    assert all(fb.get_issue(n).state == "open" for n in (1, 2))


def test_accept_all_takes_ticks_made_during_the_prompt(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 1)

    def ask():
        fb.issues[1].body = fb.issues[1].body.replace("- [ ] tests pass", "- [x] tests pass")
        return "accept 1"

    out = io.StringIO()
    assert tracker.main(["owner", "done", "1", "--accept-all"], backend=fb, human=True, out=out, ask=ask) == 0
    assert tracker.marks(fb.get_issue(1), "done")[-1]["ticked"] == [2]


def test_the_real_reader_strips_the_line_end_and_raises_on_eof(tracker, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("accept 2\r\n"))
    assert tracker.read_line() == "accept 2"
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(EOFError):
        tracker.read_line()


def test_without_the_flag_unchecked_criteria_still_refuse(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 1)
    code, out, asked = accept(tracker, fb, ["owner", "done", "1"], ["accept 1"])
    assert code == 2 and asked == 0 and "criterion 1 unchecked" in out


# -- criterion 4, D5: agent sessions and boxes ------------------------------------------------------------------


def test_an_agent_session_is_refused_both_verbs_and_the_flag(tracker, fb, tmp_path):
    in_review(tracker, fb, tmp_path, 1)
    backlog(tracker, fb, 1)
    for argv in (["owner", "ready", "2"], ["owner", "done", "1"], ["owner", "done", "1", "--accept-all"]):
        out = io.StringIO()
        code = tracker.main(argv, backend=fb, human=False, out=out, ask=lambda: "accept 1")
        assert code == 2 and "no TTY" in out.getvalue(), argv
    assert writes(fb) == []


class Tty(io.StringIO):
    def isatty(self):
        return True


def at_terminal(monkeypatch):
    """In the test body: pytest's capture replaces sys.stdout again after a fixture's setup."""
    monkeypatch.setattr("sys.stdin", Tty())
    monkeypatch.setattr("sys.stdout", Tty())
    monkeypatch.delenv("CLAUDECODE", raising=False)


def test_inside_a_box_a_terminal_is_no_human(tracker, fb, monkeypatch, box_marker):
    at_terminal(monkeypatch)
    assert tracker.is_human() is True, "a terminal outside a box"
    seat(box_marker, "s1")
    assert tracker.is_human() is False
    backlog(tracker, fb, 1)
    out = io.StringIO()
    assert tracker.main(["owner", "ready", "1"], backend=fb, out=out) == 2 and "box" in out.getvalue()


@pytest.mark.parametrize("content", ["", "not json", "[1]"])
def test_a_broken_or_empty_marker_still_means_a_box(tracker, monkeypatch, box_marker, content):
    at_terminal(monkeypatch)
    assert tracker.is_human() is True
    box_marker.write_text(content, encoding="utf-8")
    assert tracker.is_human() is False


def test_an_unreadable_marker_still_means_a_box(tracker, monkeypatch, box_marker):
    at_terminal(monkeypatch)
    assert tracker.is_human() is True
    os.symlink(str(box_marker.parent / "missing"), str(box_marker))
    assert tracker.is_human() is False


# -- criterion 6, D6: one item in progress per login and seat ---------------------------------------------------


def readied(tracker, fb, n):
    backlog(tracker, fb, n)
    assert run(tracker, fb, ["owner", "ready", *map(str, range(1, n + 1))], human=True)[0] == 0


def test_the_limit_counts_per_login_and_seat(tracker, fb, tmp_path, box_marker):
    readied(tracker, fb, 4)
    seat(box_marker, "s1")
    code, out = run(tracker, fb, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))
    assert code == 0
    claim = tracker.marks(fb.get_issue(1), "claim")[-1]
    assert claim["seat"] == "s1" and "seat `s1`" in fb.get_issue(1).comments[-1].body
    code, out = run(tracker, fb, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))
    assert code == 2 and "agent (seat s1) already has #1 in progress" in out
    assert statuses(fb.get_issue(2)) == ["status/ready"]
    seat(box_marker, "s2")
    assert run(tracker, fb, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))[0] == 0, "another seat"
    box_marker.unlink()
    code, out = run(tracker, fb, ["claim", "3", "--branch", "c"], cwd=str(tmp_path))
    assert code == 0, "the host is a seat of its own"
    claim = tracker.marks(fb.get_issue(3), "claim")[-1]
    assert claim["seat"] is None and "seat" not in fb.get_issue(3).comments[-1].body.split("\n", 1)[1]
    code, out = run(tracker, fb, ["claim", "4", "--branch", "d"], cwd=str(tmp_path))
    assert code == 2 and "agent (host) already has #3 in progress" in out
    assert "tracker review" in out and "tracker block" in out, "today's advice stays"


def test_an_environment_variable_gives_no_seat(tracker, fb, tmp_path, monkeypatch):
    monkeypatch.setenv("BOX_SEAT", "s1")
    readied(tracker, fb, 2)
    assert run(tracker, fb, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))[0] == 0
    assert tracker.marks(fb.get_issue(1), "claim")[-1]["seat"] is None
    code, out = run(tracker, fb, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))
    assert code == 2 and "agent (host) already has #1" in out
    assert tracker.seat_of() is None


def test_a_claim_mark_without_a_seat_counts_as_the_host(tracker, fb, tmp_path, box_marker):
    readied(tracker, fb, 2)
    fb.comment(1, tracker.mark("claim", by="agent", branch="a", worktree="/w", ts="2026-11-01T00:00:00Z"))
    fb.add_labels(1, ["status/in-progress"])
    fb.remove_labels(1, ["status/ready"])
    code, out = run(tracker, fb, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))
    assert code == 2 and "agent (host) already has #1" in out
    seat(box_marker, "s1")
    assert run(tracker, fb, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))[0] == 0


def test_only_the_last_claim_mark_counts(tracker, fb, tmp_path):
    readied(tracker, fb, 2)
    fb.comment(1, tracker.mark("claim", by="agent", branch="a", worktree="/w", ts="2026-11-01T00:00:00Z", seat=None))
    fb.comment(1, tracker.mark("claim", by="other", branch="a", worktree="/w", ts="2026-11-02T00:00:00Z", seat=None))
    fb.add_labels(1, ["status/in-progress"])
    fb.remove_labels(1, ["status/ready"])
    assert run(tracker, fb, ["claim", "2", "--branch", "b"], cwd=str(tmp_path))[0] == 0


@pytest.mark.parametrize("content", ["not json", "[1]", json.dumps({"name": "x"}), json.dumps({"seat": "a b"}),
                                     json.dumps({"seat": ""}), json.dumps({"seat": 7})])
def test_a_marker_without_a_plain_seat_refuses_the_claim(tracker, fb, tmp_path, box_marker, content):
    readied(tracker, fb, 1)
    fb.log.clear()
    box_marker.write_text(content, encoding="utf-8")
    code, out = run(tracker, fb, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))
    assert code == 2 and str(box_marker) in out
    assert statuses(fb.get_issue(1)) == ["status/ready"] and writes(fb) == []


def test_an_unreadable_marker_refuses_the_claim(tracker, fb, tmp_path, box_marker):
    readied(tracker, fb, 1)
    os.symlink(str(box_marker.parent / "missing"), str(box_marker))
    code, out = run(tracker, fb, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))
    assert code == 2 and str(box_marker) in out
    assert statuses(fb.get_issue(1)) == ["status/ready"]


# -- D7, D8 -----------------------------------------------------------------------------------------------------


def test_version_and_usage(tracker):
    assert tracker.VERSION == "0.2.0"
    assert "owner ready N [N ...]" in tracker.__doc__
    assert "owner done N [N ...]" in tracker.__doc__ and "--accept-all" in tracker.__doc__


def test_tests_never_see_the_real_marker(tracker, tmp_path):
    assert tracker.BOX_MARKER.startswith(str(tmp_path))
