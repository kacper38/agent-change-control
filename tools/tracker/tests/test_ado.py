"""Azure DevOps support: backend choice by origin host (A1), AdoBackend on the fake REST API (A2), process mode (A7)."""
import io

import pytest

ADO_REMOTES = [
    "https://org@dev.azure.com/org/My%20Project/_git/my-repo",
    "https://dev.azure.com/org/My%20Project/_git/my-repo",
    "git@ssh.dev.azure.com:v3/org/My%20Project/my-repo",
    "https://org.visualstudio.com/DefaultCollection/My%20Project/_git/my-repo",
    "https://org.visualstudio.com/My%20Project/_git/my-repo",
]
OTHER_REMOTES = [
    "https://github.com/owner/repo.git",
    "git@github.com:owner/repo.git",
    "https://github.com/owner/dev.azure.com",
    "https://dev.azure.com.example.net/org/p/_git/r",
    "",
]


@pytest.fixture
def no_backend_env(monkeypatch):
    monkeypatch.delenv("KZ_TRACKER_BACKEND", raising=False)


@pytest.mark.parametrize("url", ADO_REMOTES)
def test_ado_remotes_are_recognised(tracker, url):
    assert tracker.is_ado_remote(url)


@pytest.mark.parametrize("url", OTHER_REMOTES)
def test_other_origins_get_github(tracker, monkeypatch, no_backend_env, url):
    assert not tracker.is_ado_remote(url)
    monkeypatch.setattr(tracker, "origin_url", lambda cwd=None: url)
    assert isinstance(tracker.backend_for("owner/repo"), tracker.GitHubBackend)


def test_env_overrides_the_origin(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "origin_url", lambda cwd=None: ADO_REMOTES[0])
    monkeypatch.setenv("KZ_TRACKER_BACKEND", "GitHub")
    assert isinstance(tracker.backend_for("owner/repo"), tracker.GitHubBackend)


def test_unknown_backend_is_an_error_not_a_traceback(tracker, monkeypatch):
    monkeypatch.setenv("KZ_TRACKER_BACKEND", "jira")
    with pytest.raises(tracker.TrackerError, match="expected github or ado"):
        tracker.backend_for()
    out = io.StringIO()
    assert tracker.main(["list"], human=False, out=out) == 1
    assert "KZ_TRACKER_BACKEND='jira'" in out.getvalue()


# --- AdoBackend on the fake (plan A2) -------------------------------------------------------------

HUMAN = "4b1c2d3e-0000-4000-8000-0000000000aa"
BOT = "9f8e7d6c-0000-4000-8000-0000000000b0"
NEW = ["new", "--title", "Do the thing", "--ac", "tests pass", "--ac", "docs updated", "--scope", "the CLI",
       "--scope-limit", "no UI", "--source", "plan step A2"]
PR_URL = "https://dev.azure.com/org/proj/_git/repo/pullrequest/7"
DONE = ["owner", "done", "1", "--waive", "1", "covered by CI", "--waive", "2", "n/a"]


def run(tracker, backend, argv, human=False, cwd=None):
    out = io.StringIO()
    return tracker.main(argv, backend=backend, human=human, out=out, cwd=cwd), out.getvalue()


def in_review(tracker, backend, fake, tmp_path):
    assert run(tracker, backend, NEW)[0] == 0
    assert run(tracker, backend, ["owner", "ready", "1"], human=True)[0] == 0
    assert run(tracker, backend, ["claim", "1", "--branch", "step-x"], cwd=str(tmp_path))[0] == 0
    fake.add_pr(7, source="step-x", description="Implements the thing.\n\nRefs #1")
    code, out = run(tracker, backend, ["review", "1", "--pr", PR_URL])
    assert code == 0, out


@pytest.mark.parametrize("url,want", [
    ("https://org@dev.azure.com/org/My%20Project/_git/my%20repo", ("org", "My Project", "my repo")),
    ("git@ssh.dev.azure.com:v3/org/My%20Project/my-repo", ("org", "My Project", "my-repo")),
    ("https://org.visualstudio.com/DefaultCollection/proj/_git/repo", ("org", "proj", "repo")),
    ("https://org.visualstudio.com/proj/_git/repo/", ("org", "proj", "repo")),
    ("https://github.com/owner/repo.git", None),
])
def test_origin_parsing(ado, url, want):
    assert ado.parse_remote(url) == want


def test_repo_resolution_order(ado, tracker, ado_fake, monkeypatch):
    ado_fake()  # clears the env
    monkeypatch.setattr(tracker, "origin_url", lambda cwd=None: "git@ssh.dev.azure.com:v3/o4/p4/r4")
    assert ado.resolve(None) == ("https://dev.azure.com/o4", "p4", "r4")
    for k, v in (("SYSTEM_COLLECTIONURI", "https://dev.azure.com/o3/"), ("SYSTEM_TEAMPROJECT", "p3"),
                 ("BUILD_REPOSITORY_NAME", "r3")):
        monkeypatch.setenv(k, v)
    assert ado.resolve(None) == ("https://dev.azure.com/o3", "p3", "r3")
    monkeypatch.setenv("KZ_TRACKER_REPO", "o2/p%202/r2")
    assert ado.resolve(None) == ("https://dev.azure.com/o2", "p 2", "r2")
    assert ado.resolve("o1/p1/r1") == ("https://dev.azure.com/o1", "p1", "r1")
    with pytest.raises(tracker.TrackerError, match="expected org/project/repo"):
        ado.resolve("owner/name")


def test_backend_for_builds_the_ado_backend(tracker, ado, ado_fake, monkeypatch):
    ado_fake()
    monkeypatch.setenv("KZ_TRACKER_BACKEND", "ado")
    assert isinstance(tracker.backend_for("org/proj/repo"), ado.AdoBackend)


def test_token_from_the_pipeline_never_calls_az(ado, ado_fake, monkeypatch):
    backend, fake = ado_fake()
    monkeypatch.setattr(ado.subprocess, "run", lambda *a, **k: pytest.fail("az called"))
    assert backend.whoami() == fake.user


def test_token_from_az_and_its_failures(tracker, ado, ado_fake, monkeypatch):
    backend, fake = ado_fake(token="from-az")
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN")
    seen = []

    def az_ok(args, **kw):
        seen.append(args)
        return ado.subprocess.CompletedProcess(args, 0, "from-az\n", "")

    def az_logged_out(args, **kw):
        return ado.subprocess.CompletedProcess(args, 1, "", "Please run 'az login' to setup account.")

    def az_missing(args, **kw):
        raise FileNotFoundError("az")

    monkeypatch.setattr(ado.subprocess, "run", az_ok)
    assert backend.whoami() == fake.user
    assert seen[0][:3] == ["az", "account", "get-access-token"] and ado.ADO_RESOURCE in seen[0]
    for failure, match in ((az_logged_out, "az login"), (az_missing, "Azure CLI")):
        monkeypatch.setattr(ado.subprocess, "run", failure)
        with pytest.raises(tracker.TrackerError, match=match):
            ado.AdoBackend("org/proj/repo", transport=fake).whoami()


def test_http_errors_name_the_status_and_never_the_token(tracker, ado, ado_fake):
    ado_fake()

    def backend_answering(status, body=b"", exc=None):
        def send(method, url, headers, data):
            if exc:
                raise exc
            return status, {}, body
        return ado.AdoBackend("org/proj/repo", transport=send)

    with pytest.raises(tracker.TrackerError) as err:
        backend_answering(500, b"x" * 1000).whoami()
    assert "HTTP 500" in str(err.value) and "x" * 300 in str(err.value) and "x" * 301 not in str(err.value)
    with pytest.raises(tracker.TrackerError, match="az login") as err:
        backend_answering(401, b"denied").whoami()
    assert "fake-token" not in str(err.value)
    with pytest.raises(tracker.TrackerError, match="not JSON"):
        backend_answering(203, b"<html>sign in</html>").whoami()
    with pytest.raises(tracker.TrackerError, match="unreachable"):
        backend_answering(0, exc=ado.urllib.error.URLError("timed out")).whoami()
    with pytest.raises(tracker.TrackerError, match="expected a `value` list"):
        ado.values({"count": 0})


def test_unknown_items_raise_and_unknown_prs_are_none(tracker, ado_fake):
    backend, fake = ado_fake()
    with pytest.raises(tracker.TrackerError, match="#41 not found"):
        backend.get_issue(41)
    fake.add_pr(7)
    assert backend.pr("99") is None and backend.pr(PR_URL.replace("/7", "/99")) is None
    assert backend.pr(PR_URL.replace("_git/repo", "_git/other")) is None, "a PR URL of another repo"
    assert backend.pr("not a pr") is None
    assert backend.pr("7").number == backend.pr(PR_URL).number == 7


def test_html_and_out_of_scope_items_are_refused(tracker, ado_fake, monkeypatch):
    backend, fake = ado_fake()
    html = fake.seed_item(description="<div>- [ ] a</div>", markdown=False)
    with pytest.raises(tracker.TrackerError, match="Markdown"):
        backend.get_issue(html)
    with pytest.raises(tracker.TrackerError, match="Markdown"):
        backend.add_labels(html, ["status/ready"])
    other = fake.seed_item(**{"System.AreaPath": "proj\\team-b"})
    monkeypatch.setenv("KZ_TRACKER_AREA", "proj\\team-a")
    scoped = type(backend)("org/proj/repo", transport=fake)
    with pytest.raises(tracker.TrackerError, match="outside the tracker's scope"):
        scoped.get_issue(other)
    with pytest.raises(tracker.TrackerError, match="outside the tracker's scope"):
        scoped.add_labels(other, ["status/ready"])
    assert scoped.list_issues(state="all") == []
    assert "System.Tags" not in fake.items[other]["fields"], "nothing written outside the scope"


def test_writes_are_markdown_and_guarded_by_rev(tracker, ado_fake):
    backend, fake = ado_fake()
    issue = backend.create_issue("t", "## Body\n", ["type/todo", "status/backlog"])
    assert fake.items[issue.number]["format"] == {"System.Description": "markdown"}
    backend.comment(issue.number, tracker.mark("note", by="x") + "\nhi")
    assert fake.comments[issue.number][0]["format"] == "markdown"
    backend.add_labels(issue.number, ["status/ready"])
    method, _, _, ops = fake.calls[-1]
    assert method == "PATCH" and ops[0] == {"op": "test", "path": "/rev", "value": 1}
    backend.add_labels(issue.number, ["Status/Ready"])
    assert fake.calls[-1][0] == "GET", "a tag already there (any case) is not written again"
    with pytest.raises(tracker.TrackerError, match="HTTP 412"):
        backend._patch(issue.number, 1, {"System.Title": "stale"})
    assert backend.get_issue(issue.number).title == "t"


def test_comments_come_back_complete_and_oldest_first(tracker, ado_fake):
    backend, fake = ado_fake(page=2)
    issue = backend.create_issue("t", "b", ["status/backlog"])
    for k in range(5):
        backend.comment(issue.number, f"c{k}")
    fake.calls.clear()
    assert [c.body for c in backend.get_issue(issue.number).comments] == [f"c{k}" for k in range(5)]
    pages = [c for c in fake.calls if c[0] == "GET" and c[1].endswith("/comments")]
    assert len(pages) == 3 and pages[1][2]["continuationToken"] == "2"


def test_build_results_map_to_check_conclusions(ado_fake):
    backend, fake = ado_fake(page=2)
    fake.add_build("abc", result="failed", name="ci")
    fake.add_build("abc", result="partiallySucceeded", name="lint")
    fake.add_build("abc", result="canceled", name="deploy")
    fake.add_build("abc", status="inProgress", name="slow")
    fake.add_build("other", name="ci")
    fake.add_build("abc", result="succeeded", name="ci")  # the re-run is the newest
    got = {c.name: (c.status, c.conclusion) for c in backend.pr_checks("abc")}
    assert got == {"ci": ("completed", "success"), "lint": ("completed", "failure"),
                   "deploy": ("completed", "failure"), "slow": ("in_progress", "")}
    assert backend.pr_checks("abc")[0].url.startswith("https://dev.azure.com/org/proj/_build/results")
    assert backend.pr_checks("nope") == []


def test_build_search_stops_after_the_page_cap(ado, ado_fake):
    backend, fake = ado_fake(page=1)
    fake.add_build("old")
    for _ in range(ado.BUILD_PAGES + 2):
        fake.add_build("newer")
    assert backend.pr_checks("old") == []
    assert len([c for c in fake.calls if c[1].endswith("/builds")]) == ado.BUILD_PAGES


def test_pr_mapping(ado_fake):
    backend, fake = ado_fake(page=1)
    fake.add_pr(7, source="step-x", files=("DECISIONS.md", "src/app.py"))
    open_pr = backend.pr("7")
    assert (open_pr.head, open_pr.base, open_pr.state, open_pr.merged, open_pr.merge_sha) == \
        ("step-x", "main", "open", False, "")
    assert open_pr.files == ["DECISIONS.md", "src/app.py"] and open_pr.url == PR_URL
    fake.complete_pr(7, merge_sha="m3rg3", closed_by=HUMAN)
    merged = backend.pr(PR_URL)
    assert (merged.state, merged.merged, merged.merged_by, merged.merge_sha) == ("merged", True, HUMAN, "m3rg3")
    fake.prs[7]["status"] = "abandoned"
    assert backend.pr("7").state == "closed"


def test_labels_are_tags_with_emulated_sync(tracker, ado_fake):
    backend, fake = ado_fake()
    code, out = run(tracker, backend, ["owner", "labels-sync"], human=True)
    assert code == 0 and "12 created, 0 updated" in out and fake.tags == [], "nothing is written"
    backend.create_issue("t", "b", ["type/todo", "status/backlog", "custom"])
    assert backend.ensure_label("type/todo", "", "") == "updated"
    assert backend.ensure_label("type/bug", "", "") == "created"
    assert "custom" in backend.list_labels()


@pytest.mark.parametrize("body", ["Fixes #1", "fixes AB#1", "Done #1", "Resolved #1", "In Progress #1", "to do: #1",
                                  "Review #1", "ready #1", "Closes AB#12", "Removed #1", "Dropped #1"])
def test_closing_words_and_state_names_are_refused(tracker, body):
    assert tracker._CLOSING_RE.search(body), body


@pytest.mark.parametrize("body", ["Refs #1", "Refs AB#1", "Ready for review, see #1", "Reviewed in #1",
                                  "Done. Refs #1", "Fixed the parser (Refs #1)"])
def test_references_are_not_closing_words(tracker, body):
    assert not tracker._CLOSING_RE.search(body), body


def test_owner_done_end_to_end(tracker, ado_fake, tmp_path):
    backend, fake = ado_fake(page=2)
    in_review(tracker, backend, fake, tmp_path)
    fake.complete_pr(7, merge_sha="m3rg3", closed_by=HUMAN)
    fake.add_build("m3rg3")
    code, out = run(tracker, backend, DONE, human=True)
    assert code == 0, out
    issue = backend.get_issue(1)
    assert issue.state == "closed" and [lb for lb in issue.labels if lb.startswith("status/")] == ["status/done"]
    assert fake.items[1]["fields"]["System.State"] == "Closed"
    done = tracker.marks(issue, "done")[0]
    assert (done["merge_sha"], done["merged_by"], done["decisions_md"], done["pr"]) == ("m3rg3", HUMAN, True, PR_URL)
    assert [m["kind"] for m in tracker.marks(issue)] == ["ready", "claim", "review", "done"]


def test_review_refuses_ado_state_words_and_unknown_prs(tracker, ado_fake, tmp_path):
    backend, fake = ado_fake()
    assert run(tracker, backend, NEW)[0] == 0
    assert run(tracker, backend, ["owner", "ready", "1"], human=True)[0] == 0
    assert run(tracker, backend, ["claim", "1", "--branch", "step-x"], cwd=str(tmp_path))[0] == 0
    fake.add_pr(7, source="step-x", description="Refs #1\nDone #1")
    code, out = run(tracker, backend, ["review", "1", "--pr", "7"])
    assert code == 2 and "closing keyword `Done #1`" in out
    code, out = run(tracker, backend, ["review", "1", "--pr", "8"])
    assert code == 2 and "no pull request found" in out


@pytest.mark.parametrize("completion,why", [
    ({"transitionWorkItems": True}, "transitionWorkItems"),
    ({"bypassPolicy": True, "bypassReason": "hotfix"}, "bypassPolicy` (hotfix)"),
])
def test_owner_done_refuses_forge_side_completion(tracker, ado_fake, tmp_path, completion, why):
    backend, fake = ado_fake()
    in_review(tracker, backend, fake, tmp_path)
    fake.complete_pr(7, merge_sha="m3rg3", closed_by=HUMAN, **completion)
    fake.add_build("m3rg3")
    code, out = run(tracker, backend, DONE, human=True)
    assert code == 2 and why in out
    assert backend.get_issue(1).state == "open"


def test_owner_done_refuses_a_bot_merger_and_a_partial_build(tracker, ado_fake, tmp_path, monkeypatch):
    backend, fake = ado_fake()
    in_review(tracker, backend, fake, tmp_path)
    fake.complete_pr(7, merge_sha="m3rg3", closed_by=BOT)
    fake.add_build("m3rg3", result="partiallySucceeded")
    monkeypatch.setenv("KZ_TRACKER_BOTS", BOT)
    code, out = run(tracker, backend, DONE, human=True)
    assert code == 2 and "not a human" in out and "check `ci` is failure" in out


# --- process mode: status/* is System.State (plan A7) ---------------------------------------------


def test_mode_comes_from_the_env_and_is_checked(tracker, ado, ado_fake, monkeypatch):
    _, fake = ado_fake()
    monkeypatch.setenv("KZ_TRACKER_ADO_MODE", "process")
    backend = ado.AdoBackend("org/proj/repo", transport=fake)
    assert (backend.mode, backend.wit) == ("process", "Change")
    monkeypatch.setenv("KZ_TRACKER_ADO_MODE", "states")
    with pytest.raises(tracker.TrackerError, match="expected tags or process"):
        ado.AdoBackend("org/proj/repo", transport=fake)


def test_process_mode_maps_status_and_type_to_fields(tracker, ado_fake):
    backend, fake = ado_fake("process")
    issue = backend.create_issue("t", "b", ["type/bug", "status/backlog", "custom"])
    f = fake.items[issue.number]["fields"]
    assert (f["System.State"], f["Custom.ChangeType"], f["System.Tags"]) == ("Backlog", "bug", "custom")
    assert sorted(backend.get_issue(issue.number).labels) == ["custom", "status/backlog", "type/bug"]
    backend.add_labels(issue.number, ["status/in-progress"])
    assert fake.items[issue.number]["fields"]["System.State"] == "In Progress"
    calls = len(fake.calls)
    backend.remove_labels(issue.number, ["status/backlog", "type/bug"])
    assert all(c[0] == "GET" for c in fake.calls[calls:]), "removing a status or type writes nothing"
    assert [i.number for i in backend.list_issues(["status/in-progress", "type/bug"])] == [issue.number]
    assert backend.list_issues(["status/ready"]) == []
    wiql = [c[3]["query"] for c in fake.calls if c[1].endswith("/wiql")][-1]
    assert "[System.State] = 'Ready'" in wiql and "System.Tags" not in wiql


def test_process_mode_labels_sync_checks_the_process(tracker, ado_fake):
    backend, fake = ado_fake("process")
    code, out = run(tracker, backend, ["owner", "labels-sync"], human=True)
    assert code == 0 and "0 created, 12 updated" in out
    assert {"status/dropped", "status/in-progress", "type/agent-note"} <= set(backend.list_labels())
    fake.states["Change"] = [s for s in fake.states["Change"] if s[0] != "Blocked"]
    backend._states.clear()
    code, out = run(tracker, backend, ["owner", "labels-sync"], human=True)
    assert code == 2 and "no System.State `Blocked`" in out and "process admin" in out
    fake.picklists["Custom.ChangeType"].remove("handoff")
    with pytest.raises(tracker.Refused, match="Custom.ChangeType `handoff`"):
        backend.ensure_label("type/handoff", "", "")


def test_process_mode_end_to_end_and_the_board_drag_lint(tracker, label_lint, ado_fake, tmp_path):
    backend, fake = ado_fake("process")
    in_review(tracker, backend, fake, tmp_path)
    assert fake.items[1]["fields"]["System.State"] == "Review"
    fake.complete_pr(7, merge_sha="m3rg3", closed_by=HUMAN)
    fake.add_build("m3rg3")
    code, out = run(tracker, backend, DONE, human=True)
    assert code == 0, out
    assert backend.get_issue(1).state == "closed" and fake.items[1]["fields"]["System.State"] == "Done"
    assert label_lint.findings(backend) == []
    other = backend.create_issue("dragged", "b", ["type/todo", "status/backlog"])
    fake.items[other.number]["fields"]["System.State"] = "Ready"  # a board drag, no tracker verb
    found = {i.number: p for i, p in label_lint.findings(backend)}
    assert list(found) == [other.number] and "state without a matching marker" in found[other.number][0]
