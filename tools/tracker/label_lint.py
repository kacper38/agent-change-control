#!/usr/bin/env python3
"""label-lint — report label-family violations on issues; never edits labels (plan step 2.4).

Runs in GitHub Actions on issue events and nightly. For each offending issue it posts one
comment per distinct finding set (a fingerprint in a hidden marker keeps it idempotent) and
keeps a single tracking issue up to date. Fixing labels is a human's job through the UI or
the `tracker` verbs. Exit code is 0 unless gh itself fails.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker  # noqa: E402

TRACKING_TITLE = "label-lint: offending issues"
MARK = "<!-- label-lint:{fp} -->"
# Azure DevOps process mode: the status is System.State, which a board drag or a REST write can set
# without the tracker. Every status a verb sets leaves its marker, so a status whose marker is not the
# latest tracker marker was set outside the protocol. `backlog` (set at creation) and `dropped` (a human's
# board or UI action, no verb) leave no marker and are not checked here; problems_for still requires a closed
# item to be done or dropped.
MARK_OF = {"ready": "ready", "in-progress": "claim", "blocked": "block", "review": "review", "done": "done"}


def problems_for(issue: tracker.Issue) -> list:
    out = []
    statuses = [lb for lb in issue.labels if lb.startswith("status/")]
    types = [lb for lb in issue.labels if lb.startswith("type/")]
    if len(statuses) != 1:
        out.append(f"{len(statuses)} status labels ({', '.join(statuses) or 'none'}); exactly one is required")
    if len(types) > 1:
        out.append(f"{len(types)} type labels ({', '.join(types)}); at most one")
    for lb in statuses:
        if lb[len("status/") :] not in tracker.STATUSES:
            out.append(f"unknown status label {lb}")
    for lb in types:
        if lb[len("type/") :] not in tracker.TYPES:
            out.append(f"unknown type label {lb}")
    if len(statuses) == 1:
        st = statuses[0][len("status/") :]
        if issue.state == "closed" and st not in ("done", "dropped"):
            out.append(f"closed but status/{st}; closing goes through `tracker owner done` (or status/dropped)")
        if issue.state == "open" and st in ("done", "dropped"):
            out.append(f"open but status/{st}")
    return out


def marker_problems(issue: tracker.Issue) -> list:
    """Process mode: the status needs its own marker as the latest tracker marker (`issue` with comments)."""
    statuses = [lb[len("status/") :] for lb in issue.labels if lb.startswith("status/")]
    if len(statuses) != 1 or statuses[0] not in MARK_OF:
        return []
    want = MARK_OF[statuses[0]]
    kinds = [m["kind"] for m in tracker.marks(issue) if m.get("kind") in MARK_OF.values()]
    if kinds and kinds[-1] == want:
        return []
    return [f"state without a matching marker: status/{statuses[0]} needs a `{want}` marker, the latest is "
            f"{'`' + kinds[-1] + '`' if kinds else 'none'}; the state was set outside the tracker verbs"]


def findings(backend: tracker.Backend) -> list:
    out = []
    process = getattr(backend, "mode", "") == "process"
    for issue in backend.list_issues(state="all"):
        if issue.title == TRACKING_TITLE:
            continue
        probs = problems_for(issue)
        if process:
            probs += marker_problems(backend.get_issue(issue.number))
        if probs:
            out.append((issue, probs))
    return out


def fingerprint(probs: list) -> str:
    return hashlib.sha256("\n".join(probs).encode("utf-8")).hexdigest()[:12]


def report(backend: tracker.Backend, items: list, now: str) -> dict:
    counts = {"issues": len(items), "comments": 0, "tracking": "unchanged"}
    for issue, probs in items:
        fp = fingerprint(probs)
        full = backend.get_issue(issue.number)
        if any(MARK.format(fp=fp) in c.body for c in full.comments):
            continue
        body = MARK.format(fp=fp) + "\n**label-lint**: this issue breaks the label contract:\n" + "\n".join(
            f"- {p}" for p in probs
        ) + "\n\nInformational only; labels are changed by a human or the `tracker` verbs, never by this job."
        backend.comment(issue.number, body)
        counts["comments"] += 1
    tracking = next((i for i in backend.list_issues(state="open") if i.title == TRACKING_TITLE), None)
    if items:
        lines = [f"Last run {now}. Issues breaking the label contract:", ""]
        lines += [f"- #{i.number} {i.title}: " + "; ".join(p) for i, p in items]
        body = "\n".join(lines) + "\n"
        if tracking is None:
            backend.create_issue(TRACKING_TITLE, body, ["type/agent-note", "status/backlog"])
            counts["tracking"] = "created"
        else:
            backend.set_body(tracking.number, body)
            counts["tracking"] = "updated"
    elif tracking is not None:
        backend.set_body(tracking.number, f"Last run {now}. No offending issues; a human may drop this issue.\n")
        counts["tracking"] = "updated"
    return counts


def main(argv: list) -> int:
    try:
        backend = tracker.backend_for(argv[0] if argv else None)
        items = findings(backend)
        counts = report(backend, items, tracker.utcnow())
    except tracker.TrackerError as exc:
        print(f"label-lint: error: {exc}", file=sys.stderr)
        return 1
    print(f"label-lint: {counts['issues']} offending issue(s), {counts['comments']} new comment(s), "
          f"tracking issue {counts['tracking']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
