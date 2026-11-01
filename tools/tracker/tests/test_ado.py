"""Azure DevOps support: backend choice by origin host."""
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
