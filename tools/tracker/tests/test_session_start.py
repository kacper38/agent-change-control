"""The session-start digest: short, grouped, silent on failure."""
import io
import signal
from contextlib import redirect_stdout

import pytest


def test_digest_groups_and_caps(tracker, session_start):
    fb = tracker.FakeBackend()
    fb.create_issue("handoff: db migration", "", ["type/handoff", "status/backlog"])
    fb.create_issue("blocked one", "", ["type/todo", "status/blocked"])
    for k in range(6):
        fb.create_issue(f"ready {k}", "", ["type/todo", "status/ready"])
    done = fb.create_issue("done", "", ["type/todo", "status/done"])
    fb.issues[done.number].state = "closed"
    lines = session_start.digest(fb)
    assert len(lines) == 3 and lines[0].startswith("Open handoffs") and "#1 handoff: db migration" in lines[0]
    assert "Blocked" in lines[1] and "ready 3" in lines[2] and "+2 more" in lines[2] and "done" not in " ".join(lines)
    assert all(len(line) < 400 for line in lines)


def test_empty_repo_prints_nothing(tracker, session_start):
    assert session_start.digest(tracker.FakeBackend()) == []


def test_failure_is_silent(session_start, monkeypatch):
    trk = session_start.tracker  # the module session_start imported, not the fixture's copy

    class Broken(trk.Backend):
        def __init__(self, repo=None):
            pass

        def list_issues(self, labels=None, state="open"):
            raise trk.TrackerError("gh: not logged in")

    monkeypatch.setattr(session_start.tracker, "backend_for", Broken)
    out = io.StringIO()
    with redirect_stdout(out):
        code = session_start.main([])
    assert code == 0 and out.getvalue() == ""


def test_digest_runs_where_sigalrm_is_missing(session_start, monkeypatch):
    trk = session_start.tracker
    fb = trk.FakeBackend()
    fb.create_issue("ready one", "", ["type/todo", "status/ready"])
    monkeypatch.delattr(session_start.signal, "SIGALRM")  # Windows
    monkeypatch.setattr(trk, "backend_for", lambda repo=None: fb)
    out = io.StringIO()
    with redirect_stdout(out):
        code = session_start.main([])
    assert code == 0 and "#1 ready one" in out.getvalue()


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="no SIGALRM on this platform (Windows)")
def test_failure_leaves_no_alarm_behind(session_start, monkeypatch):
    trk = session_start.tracker
    sig = session_start.signal

    class Broken(trk.Backend):
        def __init__(self, repo=None):
            pass

        def list_issues(self, labels=None, state="open"):
            raise trk.TrackerError("gh: not logged in")

    monkeypatch.setattr(trk, "backend_for", Broken)
    before = sig.getsignal(sig.SIGALRM)
    with redirect_stdout(io.StringIO()):
        session_start.main([])
    assert sig.alarm(0) == 0, "a pending alarm fires inside whatever runs next (seen as a killed git push)"
    assert sig.getsignal(sig.SIGALRM) is before
