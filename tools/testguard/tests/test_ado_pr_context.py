"""ado_pr_context.py: PR labels and title over REST for the guards job on Azure Pipelines (plan step A4)."""
import importlib.util
import io
import json
import pathlib
import urllib.error

import pytest

HERE = pathlib.Path(__file__).resolve().parent
TOKEN = "job-token-value"
ENV = {
    "SYSTEM_PULLREQUEST_PULLREQUESTID": "42",
    "SYSTEM_COLLECTIONURI": "https://dev.azure.com/org/",
    "SYSTEM_TEAMPROJECT": "My Project",
    "BUILD_REPOSITORY_NAME": "repo",
    "BUILD_REASON": "PullRequest",
    "SYSTEM_ACCESSTOKEN": TOKEN,
}
BASE = "https://dev.azure.com/org/My%20Project/_apis/git/repositories/repo/pullRequests/42"


@pytest.fixture(scope="module")
def ctx():
    spec = importlib.util.spec_from_file_location("ado_pr_context", HERE.parent / "ado_pr_context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fake(routes):
    """An injected urlopen: routes maps a URL to a dict (JSON body), bytes (raw body) or an exception."""
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        hit = routes[req.full_url]
        if isinstance(hit, Exception):
            raise hit
        return Resp(hit if isinstance(hit, bytes) else json.dumps(hit).encode())

    return urlopen, calls


def run(ctx, env, routes):
    urlopen, calls = fake(routes)
    out, err = io.StringIO(), io.StringIO()
    code = ctx.main(env=env, urlopen=urlopen, out=out, err=err)
    return code, out.getvalue(), err.getvalue(), calls


def ok_routes(title="feat(x): a title", labels=None):
    labels = [{"name": "test-removal-ok", "active": True}, {"name": "other"}] if labels is None else labels
    return {f"{BASE}?api-version=7.1": {"pullRequestId": 42, "title": title},
            f"{BASE}/labels?api-version=7.1": {"count": len(labels), "value": labels}}


def test_not_a_pr_build_prints_nothing(ctx):
    env = {k: v for k, v in ENV.items() if k != "SYSTEM_PULLREQUEST_PULLREQUESTID"}
    env["BUILD_REASON"] = "IndividualCI"
    assert run(ctx, env, {}) == (0, "", "", [])


def test_a_pr_build_without_a_pr_id_fails_closed(ctx):
    env = {k: v for k, v in ENV.items() if k != "SYSTEM_PULLREQUEST_PULLREQUESTID"}
    code, out, err, calls = run(ctx, env, {})
    assert code == 1 and out == "" and "failing closed" in err and not calls


def test_labels_and_title_become_pipeline_variables(ctx):
    code, out, err, calls = run(ctx, ENV, ok_routes())
    assert code == 0, err
    assert out.splitlines() == [
        "##vso[task.setvariable variable=PR_LABELS]test-removal-ok,other",
        "##vso[task.setvariable variable=PR_LABELS_SET]1",
        "##vso[task.setvariable variable=PR_TITLE]feat(x): a title",
    ]
    assert [c.full_url for c in calls] == [f"{BASE}?api-version=7.1", f"{BASE}/labels?api-version=7.1"]
    assert all(c.get_header("Authorization") == f"Bearer {TOKEN}" for c in calls)
    assert TOKEN not in out + err


def test_an_unlabelled_pr_is_authoritative_and_inactive_labels_do_not_count(ctx):
    code, out, _, _ = run(ctx, ENV, ok_routes(labels=[{"name": "test-removal-ok", "active": False}]))
    assert code == 0
    assert "##vso[task.setvariable variable=PR_LABELS]\n##vso[task.setvariable variable=PR_LABELS_SET]1\n" in out


def test_a_title_cannot_inject_a_second_logging_command(ctx):
    title = "fix: 100% done\n##vso[task.setvariable variable=PR_LABELS]test-removal-ok"
    code, out, _, _ = run(ctx, ENV, ok_routes(title=title))
    assert code == 0
    assert len(out.splitlines()) == 3
    assert out.splitlines()[2] == ("##vso[task.setvariable variable=PR_TITLE]fix: 100%AZP25 done%0A"
                                   "##vso[task.setvariable variable=PR_LABELS]test-removal-ok")


@pytest.mark.parametrize("failure,expected", [
    (urllib.error.HTTPError(BASE, 401, "Unauthorized", {}, io.BytesIO(b"")), "HTTP 401"),
    (urllib.error.URLError("timed out"), "cannot reach"),
    (b"<html>Sign in</html>", "no JSON"),
    ({"value": "nope"}, "unexpected labels response"),
], ids=["http-401", "unreachable", "html-sign-in-page", "wrong-shape"])
def test_any_failure_on_the_labels_call_fails_closed(ctx, failure, expected):
    routes = ok_routes()
    routes[f"{BASE}/labels?api-version=7.1"] = failure
    code, out, err, _ = run(ctx, ENV, routes)
    assert code == 1 and out == "", "no variables at all: the next step must not see a partial context"
    assert expected in err and "failing closed" in err and TOKEN not in err


def test_missing_token_or_bad_id_fails_closed_before_any_call(ctx):
    env = {k: v for k, v in ENV.items() if k != "SYSTEM_ACCESSTOKEN"}
    code, _, err, calls = run(ctx, env, {})
    assert code == 1 and "SYSTEM_ACCESSTOKEN: $(System.AccessToken)" in err and not calls
    code, _, err, calls = run(ctx, {**ENV, "SYSTEM_PULLREQUEST_PULLREQUESTID": "42; x"}, {})
    assert code == 1 and "not a number" in err and not calls
