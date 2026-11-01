"""Backend contract: the same assertions on the FakeBackend and on live scratch targets when their env is set
(KZ_TRACKER_TEST_REPO: GitHub; KZ_TRACKER_TEST_ADO: Azure DevOps)."""
import os
import uuid

import pytest


def backends(tracker):
    yield pytest.param("fake", id="fake")
    if os.environ.get("KZ_TRACKER_TEST_REPO"):
        yield pytest.param("github", id="github")


def live(name, var, example):
    return pytest.param(name, marks=pytest.mark.skipif(not os.environ.get(var), reason=f"set {var}={example}"))


BACKENDS = [
    "fake",
    "ado-fake",  # AdoBackend on the in-memory Azure DevOps of tests/fake_ado.py
    live("github", "KZ_TRACKER_TEST_REPO", "owner/scratch-repo"),
    live("ado", "KZ_TRACKER_TEST_ADO", "org/scratch-project/repo"),  # mode from KZ_TRACKER_ADO_MODE
]


@pytest.fixture
def backend(request, tracker):
    if request.param == "fake":
        return tracker.FakeBackend(user="me")
    if request.param == "ado-fake":
        return request.getfixturevalue("ado_fake")()[0]
    if request.param == "ado":
        return request.getfixturevalue("ado").AdoBackend(os.environ["KZ_TRACKER_TEST_ADO"])
    return tracker.GitHubBackend(os.environ["KZ_TRACKER_TEST_REPO"])


@pytest.mark.parametrize("backend", BACKENDS, indirect=True)
def test_issue_lifecycle_contract(tracker, backend):
    tag = uuid.uuid4().hex[:8]
    for name, (color, desc) in tracker.LABELS.items():
        assert backend.ensure_label(name, color, desc) in ("created", "updated")
    assert set(tracker.LABELS) <= set(backend.list_labels())
    body = tracker.compose_body(["one"], "contract test", "nothing else", f"test {tag}")
    issue = backend.create_issue(f"contract {tag}", body, ["type/agent-note", "status/backlog"])
    try:
        got = backend.get_issue(issue.number)
        assert got.title == f"contract {tag}" and got.body.strip() == body.strip()
        assert set(got.labels) == {"type/agent-note", "status/backlog"} and got.state == "open"
        backend.add_labels(issue.number, ["status/ready"])
        backend.remove_labels(issue.number, ["status/backlog"])
        assert [lb for lb in backend.get_issue(issue.number).labels if lb.startswith("status/")] == ["status/ready"]
        backend.comment(issue.number, tracker.mark("note", by=backend.whoami()) + "\ncontract")
        got = backend.get_issue(issue.number)
        assert tracker.marks(got, "note")[0]["_author"] == backend.whoami()
        backend.set_body(issue.number, body + "\nmore\n")
        assert backend.get_issue(issue.number).body.rstrip().endswith("more")
        listed = backend.list_issues(["status/ready"], state="open")
        assert any(i.number == issue.number for i in listed)
    finally:
        backend.close_issue(issue.number)
    assert backend.get_issue(issue.number).state == "closed"
    assert all(i.number != issue.number for i in backend.list_issues(state="open"))
