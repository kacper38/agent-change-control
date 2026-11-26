"""The data model: label families, the transition table, body parsing, markers."""
import itertools

import pytest


def test_label_families_cover_every_type_and_status(tracker):
    assert {f"type/{t}" for t in tracker.TYPES} <= set(tracker.LABELS)
    assert {f"status/{s}" for s in tracker.STATUSES} <= set(tracker.LABELS)
    assert len(tracker.LABELS) == len(tracker.TYPES) + len(tracker.STATUSES)


def test_every_triple_outside_the_table_raises(tracker):
    states = [None, *tracker.STATUSES]
    seen_ok = 0
    for frm, to, actor in itertools.product(states, tracker.STATUSES, (tracker.HUMAN, tracker.AGENT, tracker.DELEGATE)):
        allowed = tracker.TRANSITIONS.get((frm, to))
        if allowed and actor in allowed:
            tracker.check_transition(frm, to, actor)
            seen_ok += 1
        else:
            with pytest.raises(tracker.TransitionError):
                tracker.check_transition(frm, to, actor)
    assert seen_ok == sum(len(v) for v in tracker.TRANSITIONS.values())


HUMAN_ONLY = [("backlog", "ready"), ("blocked", "ready"), ("review", "done"), ("ready", "dropped"), ("done", "backlog")]
DELEGATED = HUMAN_ONLY[:3]  # #103: a session under the owner's committed delegation, through the `delegate` verbs


@pytest.mark.parametrize("frm,to", HUMAN_ONLY)
def test_human_only_transitions(tracker, frm, to):
    tracker.check_transition(frm, to, tracker.HUMAN)
    with pytest.raises(tracker.TransitionError, match="human, not agent"):
        tracker.check_transition(frm, to, tracker.AGENT)
    if (frm, to) in DELEGATED:
        tracker.check_transition(frm, to, tracker.DELEGATE)
    else:
        with pytest.raises(tracker.TransitionError, match="for human, not delegate"):
            tracker.check_transition(frm, to, tracker.DELEGATE)


def test_agent_transitions(tracker):
    for frm, to in [(None, "backlog"), ("ready", "in-progress"), ("in-progress", "blocked"), ("in-progress", "review")]:
        tracker.check_transition(frm, to, tracker.AGENT)
    with pytest.raises(tracker.TransitionError, match="no transition"):
        tracker.check_transition("backlog", "in-progress", tracker.AGENT)
    with pytest.raises(tracker.TransitionError):
        tracker.check_transition("done", "ready", tracker.HUMAN)


def test_compose_body_meets_definition_of_ready(tracker):
    body = tracker.compose_body(["tests pass", "docs updated"], "the CLI", "no UI", "plan step 2.5")
    assert tracker.definition_of_ready(body) == []
    assert tracker.parse_ac(body) == [(False, "tests pass"), (False, "docs updated")]
    assert tracker.section(body, "Scope").startswith("the CLI")
    assert tracker.section(body, "Source") == "plan step 2.5"


def test_issue_form_body_is_accepted(tracker):
    body = ("### Acceptance criteria\n\n- [x] one\n- [ ] two\n\n### Scope\n\nthe thing\n\n### Scope limit\n\n"
            "Scope limit: not the other thing\n\n### Source\n\nconversation 2026-10-29\n")
    assert tracker.definition_of_ready(body) == []
    assert tracker.parse_ac(body) == [(True, "one"), (False, "two")]


def test_definition_of_ready_names_what_is_missing(tracker):
    missing = tracker.definition_of_ready("just a title\n")
    assert len(missing) == 4
    missing = tracker.definition_of_ready("## Acceptance criteria\n- [ ] x\n## Scope\ny\nScope limit:\n## Source\nz")
    assert missing == ["a non-empty `Scope limit:` line"]


def test_body_hash_ignores_line_endings_and_checkbox_state(tracker):
    a = tracker.body_hash("## A\n- [ ] x\n")
    assert a == tracker.body_hash("## A\r\n- [ ] x\r\n\n")
    assert a == tracker.body_hash("## A\n- [x] x\n"), "ticking an acceptance box is not a change of the record"
    assert a != tracker.body_hash("## A\n- [ ] y\n")


def test_marks_roundtrip(tracker):
    issue = tracker.Issue(1, "t", "", [], "open", comments=[
        tracker.Comment("a", tracker.mark("claim", by="a", branch="b") + "\ntext"),
        tracker.Comment("h", "just a human comment"),
        tracker.Comment("a", tracker.mark("note", by="a")),
    ])
    assert [m["kind"] for m in tracker.marks(issue)] == ["claim", "note"]
    assert tracker.marks(issue, "claim")[0]["branch"] == "b" and tracker.marks(issue, "claim")[0]["_author"] == "a"
