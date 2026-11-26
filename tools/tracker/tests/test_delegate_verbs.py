"""#103: `delegate ready` and `delegate done`, the owner verbs a session runs where the owner's committed file
delegates them. Written before the code: each test is an expected output of decisions 1-10 of the item."""
import base64
import hashlib
import json
import uuid

import pytest
from test_phase_verbs import backlog, writes
from test_verbs import make_pr, run, statuses

GUARD_ON = json.dumps({"boundary": "own", "owner_verbs": "delegated", "protected_branches": ["main"]}, indent=2)
SESSION = "0b5e55ed-0000-4000-8000-000000000103"
WORD = "do owner ready and owner done for me (2026-11-26)"
LINES = {"1": "tools/tracker/tests/test_delegate_verbs.py passes", "2": "https://fake/docs/103"}
TREE = {"tools/tracker/tests/test_delegate_verbs.py", "README.md", "docs/SYSTEM.md"}  # at each item's merge commit


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
        fb.trees[f"sha{i}"] = set(TREE)
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
@pytest.mark.parametrize("session", ["a b", "a\nb", "a-->b", "a" * 129], ids=["space", "newline", "-->", "long"])
def test_a_session_id_that_is_not_a_plain_token_refuses(tracker, fb, tmp_path, monkeypatch, verb, session):
    assert tracker._SEAT_RE.fullmatch(SESSION) and tracker._SEAT_RE.fullmatch(str(uuid.uuid4())), "a UUID passes"
    backlog(tracker, fb, 1)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    no_reads(fb)
    code, out = run(tracker, fb, ready_argv() if verb == "ready" else done_argv(tmp_path))
    assert code == 2 and "CLAUDE_CODE_SESSION_ID is not a plain token" in out, out


HTML = "the forge may drop it as HTML and hide part of the record"
MARKUP = ["ok --> then", "ok <!-- then", "ok --!> then", "ok <!x> then", "ok <?x> then", "ok <b> then", "ok </b> then"]
MARKUP_IDS = ["comment-end", "comment-start", "bang-end", "bang-tag", "question-tag", "tag", "end-tag"]


@pytest.mark.parametrize("verb", ["ready", "done"])
@pytest.mark.parametrize("word, reason", [("", "is empty"), ("   ", "is empty"), ("one\ntwo", "more than one line"),
                                          ("x" * 501, "longer than 500"), *((m, HTML) for m in MARKUP)],
                         ids=["empty", "blank", "two-lines", "too-long", *MARKUP_IDS])
def test_a_bad_word_refuses(tracker, fb, tmp_path, verb, word, reason):
    backlog(tracker, fb, 1)
    no_reads(fb)
    code, out = run(tracker, fb, ready_argv(word=word) if verb == "ready" else done_argv(tmp_path, word=word))
    assert code == 2 and "--word" in out and reason in out, out


def test_a_less_than_sign_that_opens_no_markup_is_allowed(tracker, fb, tmp_path):
    reviewed(tracker, fb, tmp_path, delegated=True)
    assert tracker.marks(fb.get_issue(1), "ready")[-1]["word"] == WORD
    code, out = run(tracker, fb, done_argv(tmp_path, line2("docs/SYSTEM.md: a < b, x<3"), word="a < b and x<3"))
    assert code == 0, out
    assert tracker.marks(fb.get_issue(1), "done")[-1]["word"] == "a < b and x<3"


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
    lines = issue.comments[-1].body.split("\n")
    assert lines[0] == tracker.mark("done", **{k: v for k, v in done.items() if k not in ("kind", "_author")})
    assert lines[1:] == [
        "Done with the account agent, by a session (next line). PR https://fake/pull/1 merged as sha1 by kacper.",
        f"Session `{SESSION}` did this on the owner's delegation: `.claude/guard.json` at blob `{blob(GUARD_ON)}` on "
        f'the default branch. The owner\'s words, as the session quotes them: "{WORD}"',
        "Checks on the merge commit:", "- c0: success (https://fake/checks/0)",
        "DECISIONS.md changed in this PR (decision record linked by the merge SHA).",
        "Evidence per acceptance criterion; no box was ticked by this verb:",
        f"1. tests pass: {LINES['1']}", f"2. docs updated: {LINES['2']}"]


NOWHERE = "criterion 2 (docs updated): the line names no file or folder that exists at the merge commit sha1 "
CAP = "a1.md a2.md a3.md a4.md a5.md a6.md README.md"


def line2(line):
    return {"1": {**LINES, "2": line}}


@pytest.mark.parametrize("data, reason", [
    ({"1": {"1": LINES["1"]}}, "criterion 2 (docs updated): no evidence line"),
    (line2("looked at it, fine"), NOWHERE + "(none found in the line) and no URL under https://fake/"),
    (line2("fine at 10:30"), NOWHERE + "(none found in the line)"), (line2("ok v1.2"), NOWHERE + "(tried v1.2)"),
    (line2("see e.g"), NOWHERE + "(tried e.g)"), (line2("docs/MISSING.md here"), NOWHERE + "(tried docs/MISSING.md)"),
    (line2("/work/.githooks/commit-msg"), NOWHERE + "(none found in the line)"),
    (line2("https://elsewhere/docs/103"), NOWHERE + "(none found in the line) and no URL under https://fake/"),
    (line2(CAP), NOWHERE + "(tried a1.md, a2.md, a3.md, a4.md, a5.md, a6.md)"),
    (line2("a.py\nb.py"), "the line has more than one line"),
    (line2("a.py " + "x" * 500), "the line is longer than 500 characters"),
    *((line2("docs/SYSTEM.md " + m), "criterion 2 (docs updated): the line contains `<` before") for m in MARKUP[3:]),
    *((line2("docs/SYSTEM.md " + m), HTML) for m in MARKUP[:3]),
    ({"1": {**LINES, "3": "c.py"}}, "evidence for criterion 3, which #1 does not have"),
    ({"1": LINES, "2": LINES}, "evidence for #2, which is not given"),
], ids=["missing", "no-path", "a-time", "a-version", "e.g", "not-in-the-tree", "absolute", "other-host", "cap-of-6",
        "two-lines", "too-long", *MARKUP_IDS[3:], *MARKUP_IDS[:3], "no-such-criterion", "item-not-given"])
def test_evidence_that_does_not_cover_every_criterion_refuses(tracker, fb, tmp_path, data, reason):
    reviewed(tracker, fb, tmp_path)
    code, out = run(tracker, fb, done_argv(tmp_path, data))
    assert code == 2 and reason in out, out
    assert writes(fb) == [] and fb.get_issue(1).state == "open"


@pytest.mark.parametrize("line", ["see (docs/SYSTEM.md).", "tools/tracker covers it", "README.md:12-14",
                                  CAP.replace("a6.md", "a1.md"), "https://fake/actions/runs/7",
                                  "https://fake/blob/main/docs/a%20b.md"],
                         ids=["file", "folder", "line-reference", "six-distinct", "url-under-the-repo", "url-escape"])
def test_a_line_that_points_at_something_that_exists_passes(tracker, fb, tmp_path, line):
    reviewed(tracker, fb, tmp_path)
    code, out = run(tracker, fb, done_argv(tmp_path, line2(line)))
    assert code == 0, out


def test_a_url_counts_only_under_the_repository_of_the_pull_request(tracker, fb):
    t, pr = tracker.Tracker(fb, tracker.DELEGATE), "https://github.com/o/r/pull/7"
    assert t.evidence_target_problem("run https://github.com/o/r/actions/runs/1 green", pr, "sha1") is None
    for url in ("https://github.com/o/r2/x", "https://github.com/o/other/x", "https://gitlab.com/o/r/x",
                "https://github.com/o/r/../evil/x", "https://github.com/o/r/%2e%2e/evil/x",
                "https://github.com/o/r/%2E%2E/evil/x", "https://github.com/o/r/%2e./evil/x",
                "https://github.com/o/r%2f../evil/x"):
        assert "no URL under https://github.com/o/r/" in t.evidence_target_problem(url, pr, "sha1"), url
    ado = "https://dev.azure.com/org/p/_git/r/pullrequest/7"
    assert t.evidence_target_problem("https://dev.azure.com/org/p/_git/r/x", ado, "sha1"), "no /pull/: no URL counts"


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
    code, out = run(tracker, fb, done_argv(tmp_path))  # evidence that holds at the merge commit
    assert code == 2 and reason in out, out
    assert "exists at the merge commit" not in out, "the done check refuses, not the evidence"
    assert ("no merge commit to check the evidence against" in out) == (change == "unmerged")
    assert writes(fb) == [] and fb.get_issue(1).state == "open"


def test_a_merge_without_a_merge_commit_refuses_the_evidence(tracker, fb, tmp_path):
    reviewed(tracker, fb, tmp_path)
    fb.prs["https://fake/pull/1"].merge_sha = ""
    code, out = run(tracker, fb, done_argv(tmp_path))
    assert code == 2 and "#1: " in out and "no merge commit to check the evidence against" in out, out
    assert out.count("no merge commit to check the evidence against") == 1, "once per item"
    assert writes(fb) == [] and fb.get_issue(1).state == "open"


def test_a_forge_error_while_the_evidence_is_checked_writes_nothing(tracker, fb, tmp_path):
    reviewed(tracker, fb, tmp_path, 2)

    def has_path(ref, path):
        raise tracker.TrackerError(f"gh api repos/o/r/contents/{path}?ref={ref} failed: gh: Bad Gateway (HTTP 502)")

    fb.has_path = has_path
    code, out = run(tracker, fb, done_argv(tmp_path, None, "1", "2"))
    assert code == 1 and "HTTP 502" in out, out
    assert writes(fb) == [] and all(statuses(fb.get_issue(n)) == ["status/review"] for n in (1, 2))


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
    done = tracker.marks(other.get_issue(1), "done")[-1]
    assert "delegated" not in done
    assert other.get_issue(1).comments[-1].body.split("\n") == [  # the comment of `owner done` is unchanged
        tracker.mark("done", **{k: v for k, v in done.items() if k not in ("kind", "_author")}),
        "Done by agent. PR https://fake/pull/1 merged as sha1 by kacper.", "Checks on the merge commit:",
        "- c0: success (https://fake/checks/0)",
        "DECISIONS.md changed in this PR (decision record linked by the merge SHA).",
        "Waived acceptance criterion 1: a", "Waived acceptance criterion 2: b"]


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


def test_github_asks_the_contents_api_at_the_merge_commit_for_the_type_only(tracker, monkeypatch):
    gh, calls = tracker.GitHubBackend("o/r"), []
    for answer, found in (("file\n", True), ("dir\n", True), ("HTTP 404", False), ("HTTP 502", "HTTP 502")):
        def answers(args, input_text=None, answer=answer):
            calls.append(args)
            if answer.startswith("HTTP"):
                raise tracker.TrackerError(f"gh api {args[1]} failed: gh: Not Found ({answer})")
            return answer

        monkeypatch.setattr(gh, "_run", answers)
        if isinstance(found, bool):
            assert gh.has_path("abc123", "docs/SYSTEM.md") is found, answer
        else:
            with pytest.raises(tracker.TrackerError, match=found):
                gh.has_path("abc123", "docs/SYSTEM.md")
    assert calls[0][:2] == ["api", "repos/o/r/contents/docs/SYSTEM.md?ref=abc123"] and calls[0][2] == "--jq"


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


def test_label_lint_reads_a_delegated_record_as_before(tracker, label_lint, fb, tmp_path):
    reviewed(tracker, fb, tmp_path, delegated=True)
    assert run(tracker, fb, done_argv(tmp_path))[0] == 0
    issue = fb.get_issue(1)
    done = tracker.marks(issue, "done")[-1]
    assert not any(checked for checked, _ in tracker.parse_ac(issue.body)), "the boxes stay unticked"
    assert (done["waived"], done["criteria"], issue.state) == ({}, "evidence", "closed")
    assert label_lint.problems_for(issue) == [] and label_lint.marker_problems(issue) == []
    fb.mode = "process"
    assert label_lint.findings(fb) == []


def test_help_names_both_verbs_and_delegate_alone_prints_the_usage(tracker, fb):
    code, out = run(tracker, fb, ["help"])
    assert code == 0 and "delegate ready N [N ...] --word TEXT" in out
    assert "delegate done N [N ...] --word TEXT --evidence FILE" in out
    assert run(tracker, fb, ["delegate"]) == (1, tracker.__doc__.strip() + "\n")
    assert tracker.VERSION == "0.3.0"
