#!/usr/bin/env python3
"""Session start: at most ten lines of tracker context, silent when offline or outside a tracked repo.

Wired as a SessionStart hook in both harnesses (plan step 2.7). One list read on the forge the
origin points at (`tracker.backend_for`), three seconds budget where SIGALRM exists; anything
that goes wrong prints nothing and exits 0, because a session must start.
"""
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker  # noqa: E402

BUDGET_SECONDS = 3
MAX_LINES = 10
PER_LINE = 4


def _titles(issues: list) -> str:
    shown = "; ".join(f"#{i.number} {i.title}" for i in issues[:PER_LINE])
    more = len(issues) - PER_LINE
    return shown + (f"; +{more} more" if more > 0 else "")


def digest(backend: tracker.Backend) -> list:
    """Open handoffs, blocked, in-progress and ready issues; empty when the repo has none."""
    issues = backend.list_issues(state="open")
    groups = [
        ("Open handoffs (read before touching code)", lambda i: "type/handoff" in i.labels),
        ("Blocked, waiting for a human", lambda i: "status/blocked" in i.labels),
        ("In progress", lambda i: "status/in-progress" in i.labels),
        ("Ready to claim (tracker claim N)", lambda i: "status/ready" in i.labels),
    ]
    lines = []
    for label, pick in groups:
        picked = [i for i in issues if pick(i)]
        if picked:
            lines.append(f"{label}: {_titles(picked)}")
    return lines[:MAX_LINES]


def main(argv: list) -> int:
    def _timeout(signum, frame):
        raise TimeoutError

    alarm = hasattr(signal, "SIGALRM")  # Windows has none: the backend's own timeouts are the budget there
    try:
        if alarm:
            previous = signal.signal(signal.SIGALRM, _timeout)
            signal.alarm(BUDGET_SECONDS)
        try:
            lines = digest(tracker.backend_for(argv[0] if argv else None))
        finally:
            if alarm:  # on failure too: a pending alarm fires inside whatever runs next in this process
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
    except (TimeoutError, tracker.TrackerError, OSError, ValueError):
        return 0
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
