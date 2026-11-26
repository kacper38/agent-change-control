"""#103: `delegate ready` and `delegate done`, the owner verbs a session runs where the owner's committed file
delegates them. Written before the code: each test is an expected output of decisions 1-10 of the item."""
import base64
import hashlib
import json

import pytest
from test_phase_verbs import backlog, writes
from test_verbs import make_pr, run, statuses

GUARD_ON = json.dumps({"boundary": "own", "owner_verbs": "delegated", "protected_branches": ["main"]}, indent=2)
SESSION = "0b5e55ed-0000-4000-8000-000000000103"
WORD = "do owner ready and owner done for me (2026-11-26)"
LINES = {"1": "tools/tracker/tests/test_delegate_verbs.py passes", "2": "https://fake/docs/103"}


def blob(text):
    """git's blob id of the text: what `git hash-object` and the GitHub contents API give for it."""
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def delegating(tracker, guard=GUARD_ON):
    fb = tracker.FakeBackend(user="agent")
    if guard is not None:
        fb.files[".claude/guard.json"] = guard
    return fb


@pytest.fixture
def fb(tracker):
    return delegating(tracker)


@pytest.fixture(autouse=True)
def a_session(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    monkeypatch.delenv("KZ_BOUNDARY", raising=False)


def ready_argv(*numbers, word=WORD):
    return ["delegate", "ready", *(numbers or ("1",)), "--word", word]


def done_argv(tmp_path, data=None, *numbers, word=WORD):
    numbers = numbers or ("1",)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({n: LINES for n in numbers} if data is None else data), encoding="utf-8")
    return ["delegate", "done", *numbers, "--word", word, "--evidence", str(path)]


def reviewed(tracker, fb, tmp_path, n=1, delegated=False, **pr):
    """Items 1..n in status/review, each made ready by `owner ready` or, with `delegated`, by `delegate ready`."""
    backlog(tracker, fb, n)
    for i in range(1, n + 1):
        argv = ready_argv(str(i)) if delegated else ["owner", "ready", str(i)]
        assert run(tracker, fb, argv, human=not delegated)[0] == 0
        assert run(tracker, fb, ["claim", str(i), "--branch", f"b{i}"], cwd=str(tmp_path))[0] == 0
        url = make_pr(tracker, fb, number=i, head=f"b{i}", body=f"Refs #{i}", sha=f"sha{i}", **pr)
        assert run(tracker, fb, ["review", str(i), "--pr", url])[0] == 0
    fb.log.clear()


def no_reads(fb):
    def read(number):
        raise AssertionError(f"#{number} was read before the delegation check refused")

    fb.get_issue = read


# -- decision 4: the delegation check, before any issue is read --------------------------------------------------

OFF = [(None, "does not exist"), ('{"boundary": "own"}', "owner_verbs None"),
       ('{"boundary": "own", "owner_verbs": "owner"}', "owner_verbs 'owner'"), ("{not json", "not a JSON object"),
       ("[1]", "not a JSON object"), ('{"owner_verbs": "delegated"}', "boundary None"),
       ('{"boundary": "client", "owner_verbs": "delegated"}', "boundary 'client'")]


@pytest.mark.parametrize("verb", ["ready", "done"])
@pytest.mark.parametrize("guard, reason", OFF, ids=["no-file", "no-key", "other-value", "not-json", "not-an-object",
                                                    "boundary-missing", "boundary-client"])
def test_without_the_committed_delegation_both_verbs_refuse(tracker, tmp_path, verb, guard, reason):
    fb = delegating(tracker, guard)
    backlog(tracker, fb, 1)
    no_reads(fb)
    code, out = run(tracker, fb, ready_argv() if verb == "ready" else done_argv(tmp_path))
    assert code == 2 and "has not delegated the owner verbs" in out and reason in out, out
    assert writes(fb) == []


@pytest.mark.parametrize("verb", ["ready", "done"])
@pytest.mark.parametrize("where, reason", [("box", "a box never"), ("KZ_BOUNDARY=client", "KZ_BOUNDARY"),
                                           ("KZ_BOUNDARY=", "KZ_BOUNDARY"), ("no-session", "CLAUDE_CODE_SESSION_ID"),
                                           ("blank-session", "CLAUDE_CODE_SESSION_ID")])
def test_a_box_a_client_boundary_or_no_session_refuses(tracker, fb, tmp_path, monkeypatch, box_marker, verb, where,
                                                       reason):
    backlog(tracker, fb, 1)
    if where == "box":
        box_marker.write_text("{}", encoding="utf-8")
    elif where.startswith("KZ_BOUNDARY="):
        monkeypatch.setenv("KZ_BOUNDARY", where.split("=", 1)[1])
    elif where == "no-session":
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    else:
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "  ")
    no_reads(fb)
    code, out = run(tracker, fb, ready_argv() if verb == "ready" else done_argv(tmp_path))
    assert code == 2 and reason in out, out
    assert writes(fb) == []


@pytest.mark.parametrize("verb", ["ready", "done"])
@pytest.mark.parametrize("word, reason", [("", "is empty"), ("   ", "is empty"), ("one\ntwo", "more than one line"),
                                          ("x" * 501, "longer than 500"), ("ok --> then", "`-->`")],
                         ids=["empty", "blank", "two-lines", "too-long", "comment-end"])
def test_a_bad_word_refuses(tracker, fb, tmp_path, verb, word, reason):
    backlog(tracker, fb, 1)
    no_reads(fb)
    code, out = run(tracker, fb, ready_argv(word=word) if verb == "ready" else done_argv(tmp_path, word=word))
    assert code == 2 and "--word" in out and reason in out, out


# -- decisions 5, 6: delegate ready ----------------------------------------------------------------------------


def test_delegate_ready_from_backlog_and_from_blocked_marks_the_delegation(tracker, fb, tmp_path, monkeypatch):
    monkeypatch.setenv("KZ_BOUNDARY", "own")
    backlog(tracker, fb, 1)
    fb.log.clear()
    code, out = run(tracker, fb, ready_argv(word=f"  {WORD} "))
    assert code == 0 and "#1 ready" in out
    issue = fb.get_issue(1)
    assert statuses(issue) == ["status/ready"] and [e[0] for e in fb.log] == ["comment", "add", "remove"]
    ready = tracker.marks(issue, "ready")[-1]
    assert ready == {"kind": "ready", "by": "agent", "body_sha256": tracker.body_hash(issue.body), "ts": ready["ts"],
                     "delegated": True, "session": SESSION, "word": WORD, "_author": "agent",
                     "delegation": {"file": ".claude/guard.json", "blob": blob(GUARD_ON)}}
    text = issue.comments[-1].body.split("\n", 1)[1]
    assert f"Session `{SESSION}` did this on the owner's delegation: `.claude/guard.json` at blob " in text
    assert blob(GUARD_ON) in text and f'The owner\'s words, as the session quotes them: "{WORD}"' in text
    assert run(tracker, fb, ["claim", "1", "--branch", "a"], cwd=str(tmp_path))[0] == 0, "claim works after it"
    assert run(tracker, fb, ["block", "1", "--question", "is config.timeout right?"])[0] == 0
    assert run(tracker, fb, ready_argv())[0] == 0, "blocked -> ready"
    assert statuses(fb.get_issue(1)) == ["status/ready"] and len(tracker.marks(fb.get_issue(1), "ready")) == 2


def test_delegate_ready_changes_none_when_one_fails(tracker, fb):
    backlog(tracker, fb, 1)
    fb.create_issue("no fields", "just text", ["type/todo", "status/backlog"])
    fb.log.clear()
    code, out = run(tracker, fb, ready_argv("1", "2"))
    assert code == 2 and "`delegate ready`: 1 of 2 items fail; nothing changed" in out and "#2: definition" in out
    assert writes(fb) == [] and statuses(fb.get_issue(1)) == ["status/backlog"]
    code, out = run(tracker, fb, ["owner", "ready", "1", "2"], human=True)
    assert code == 2 and "`owner ready`: 1 of 2 items fail" in out, "the owner verb reads as before"


# -- decisions 7, 8: delegate done ------------------------------------------------------------------------------


def test_delegate_done_closes_with_one_evidence_line_per_criterion(tracker, fb, tmp_path):
    reviewed(tracker, fb, tmp_path)
    before = fb.issues[1].body
    code, out = run(tracker, fb, done_argv(tmp_path))
    assert code == 0 and "#1 done and closed" in out
    issue = fb.get_issue(1)
    assert issue.state == "closed" and statuses(issue) == ["status/done"] and issue.body == before
    assert [e[0] for e in fb.log] == ["comment", "add", "remove", "close"], "no body write: no box is ticked"
    done = tracker.marks(issue, "done")[-1]
    assert (done["delegated"], done["session"], done["word"], done["criteria"]) == (True, SESSION, WORD, "evidence")
    assert done["delegation"] == {"file": ".claude/guard.json", "blob": blob(GUARD_ON)} and done["evidence"] == LINES
    assert (done["pr"], done["merge_sha"], done["merged_by"], done["waived"]) == ("https://fake/pull/1", "sha1",
                                                                                  "kacper", {})
    text = issue.comments[-1].body
    assert f"Session `{SESSION}` did this on the owner's delegation" in text
    assert "Evidence per acceptance criterion; no box was ticked by this verb:" in text
    assert f"1. tests pass: {LINES['1']}" in text and f"2. docs updated: {LINES['2']}" in text


@pytest.mark.parametrize("data, reason", [
    ({"1": {"1": LINES["1"]}}, "criterion 2 (docs updated): no evidence line"),
    ({"1": {**LINES, "2": "looked at it, fine"}}, "criterion 2 (docs updated): the line names no path or URL"),
    ({"1": {**LINES, "2": "a.py\nb.py"}}, "the line has more than one line"),
    ({"1": {**LINES, "2": "a.py " + "x" * 500}}, "the line is longer than 500 characters"),
    ({"1": {**LINES, "2": "a.py --> b"}}, "the line contains `-->`"),
    ({"1": {**LINES, "3": "c.py"}}, "evidence for criterion 3, which #1 does not have"),
    ({"1": LINES, "2": LINES}, "evidence for #2, which is not given"),
], ids=["missing", "no-path", "two-lines", "too-long", "comment-end", "no-such-criterion", "item-not-given"])
def test_evidence_that_does_not_cover_every_criterion_refuses(tracker, fb, tmp_path, data, reason):
    reviewed(tracker, fb, tmp_path)
    code, out = run(tracker, fb, done_argv(tmp_path, data))
    assert code == 2 and reason in out, out
    assert writes(fb) == [] and fb.get_issue(1).state == "open"


@pytest.mark.parametrize("content", [None, "{not json", "[1]", '{"1": ["a.py"]}', '{"one": {}}', '{"1": {"x": "a.py"}}',
                                     '{"1": {"1": 7}}'])
def test_an_unreadable_or_malformed_evidence_file_is_an_error(tracker, fb, tmp_path, content):
    reviewed(tracker, fb, tmp_path)
    path = tmp_path / "given.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    code, out = run(tracker, fb, ["delegate", "done", "1", "--word", WORD, "--evidence", str(path)])
    assert code == 1 and "--evidence" in out, out
    assert writes(fb) == []


def test_delegate_done_changes_none_when_one_fails(tracker, fb, tmp_path):
    reviewed(tracker, fb, tmp_path, 2)
    code, out = run(tracker, fb, done_argv(tmp_path, {"1": LINES, "2": {"1": LINES["1"]}}, "1", "2"))
    assert code == 2 and "`delegate done`: 1 of 2 items fail; nothing changed" in out and "#2: " in out
    assert writes(fb) == [] and all(fb.get_issue(n).state == "open" for n in (1, 2))


@pytest.mark.parametrize("change, reason", [
    ("unmerged", "PR #1 is not merged"), ("bot", "not a human"), ("red", "check `c0` is failure"),
    ("body", "body changed since ready"), ("no-claim", "no claim record")])
def test_the_checks_of_owner_done_still_bite(tracker, fb, tmp_path, change, reason):
    pr = {"unmerged": {"merged": False}, "bot": {"merged_by": "github-actions[bot]"}, "red": {"checks": ("failure",)}}
    reviewed(tracker, fb, tmp_path, **pr.get(change, {}))
    if change == "body":
        fb.issues[1].body += "\nscope creep\n"
    if change == "no-claim":
        fb.issues[1].comments = [c for c in fb.issues[1].comments if '"kind": "claim"' not in c.body]
    code, out = run(tracker, fb, done_argv(tmp_path))
    assert code == 2 and reason in out, out
    assert writes(fb) == [] and fb.get_issue(1).state == "open"


def test_owner_ready_then_delegate_done_and_delegate_ready_then_owner_done(tracker, fb, tmp_path):
    reviewed(tracker, fb, tmp_path)
    m = tracker.marks(fb.get_issue(1), "ready")[0]
    ready = next(c.body for c in fb.issues[1].comments if '"kind": "ready"' in c.body)
    assert ready == (tracker.mark("ready", by="agent", body_sha256=m["body_sha256"], ts=m["ts"])
                     + f"\nReady. Body frozen at sha256 {m['body_sha256']}; edits after this point fail `owner done`."
                     ), "the comment of `owner ready` is unchanged"
    assert run(tracker, fb, done_argv(tmp_path))[0] == 0 and fb.get_issue(1).state == "closed"
    other = delegating(tracker)
    reviewed(tracker, other, tmp_path, delegated=True)
    code, out = run(tracker, other, ["owner", "done", "1", "--waive", "1", "a", "--waive", "2", "b"], human=True)
    assert code == 0 and other.get_issue(1).state == "closed"
    assert "delegated" not in tracker.marks(other.get_issue(1), "done")[-1]


def test_with_the_delegation_on_a_session_still_cannot_run_the_owner_verbs(tracker, fb, tmp_path):
    reviewed(tracker, fb, tmp_path)
    backlog(tracker, fb, 1)
    for argv in (["owner", "ready", "2"], ["owner", "done", "1", "--accept-all"]):
        code, out = run(tracker, fb, argv)
        assert code == 2 and "no TTY" in out, argv
    assert writes(fb) == []


# -- decision 3: the backends -----------------------------------------------------------------------------------


def test_azure_devops_refuses_the_delegated_verbs(tracker, ado_fake, tmp_path):
    backend, _ = ado_fake()
    for argv in (ready_argv(), done_argv(tmp_path)):
        code, out = run(tracker, backend, argv)
        assert code == 2 and "delegated verbs are not available on the ado backend" in out, out


def test_github_reads_the_file_of_the_default_branch_through_the_contents_api(tracker, monkeypatch):
    gh = tracker.GitHubBackend("o/r")
    calls = []
    encoded = base64.b64encode(GUARD_ON.encode("utf-8")).decode("ascii")
    answer = json.dumps({"sha": "b" * 40, "content": encoded[:30] + "\n" + encoded[30:] + "\n", "encoding": "base64"})

    def answers(args, input_text=None):
        calls.append(args)
        return answer

    monkeypatch.setattr(gh, "_run", answers)
    assert gh.committed_file(".claude/guard.json") == ("b" * 40, GUARD_ON)
    assert calls == [["api", "repos/o/r/contents/.claude/guard.json"]]
    for error, found in (("gh: Not Found (HTTP 404)", None), ("gh: Server Error (HTTP 502)", "HTTP 502")):
        def fails(args, input_text=None, error=error):
            raise tracker.TrackerError(f"gh api repos/o/r/contents/.claude/guard.json failed: {error}")

        monkeypatch.setattr(gh, "_run", fails)
        if found is None:
            assert gh.committed_file(".claude/guard.json") is None
        else:
            with pytest.raises(tracker.TrackerError, match=found):
                gh.committed_file(".claude/guard.json")


# -- the record and the usage -----------------------------------------------------------------------------------


def test_the_delegated_fields_reach_the_evidence_export(tracker, ev, fb, tmp_path):
    reviewed(tracker, fb, tmp_path, delegated=True)
    assert run(tracker, fb, done_argv(tmp_path))[0] == 0
    markers = {m["kind"]: m for m in ev._issue_common(fb.get_issue(1))["markers"]}
    for kind in ("ready", "done"):
        m = markers[kind]
        assert (m["delegated"], m["session"], m["word"]) == (True, SESSION, WORD), kind
        assert m["delegation"] == {"file": ".claude/guard.json", "blob": blob(GUARD_ON)}, kind
    assert markers["done"]["criteria"] == "evidence" and markers["done"]["evidence"] == LINES


def test_help_names_both_verbs_and_delegate_alone_prints_the_usage(tracker, fb):
    code, out = run(tracker, fb, ["help"])
    assert code == 0 and "delegate ready N [N ...] --word TEXT" in out
    assert "delegate done N [N ...] --word TEXT --evidence FILE" in out
    assert run(tracker, fb, ["delegate"]) == (1, tracker.__doc__.strip() + "\n")
    assert tracker.VERSION == "0.3.0"
