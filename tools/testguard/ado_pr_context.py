#!/usr/bin/env python3
"""ado-pr-context — PR labels and title for the test-tampering guard on Azure Pipelines (plan step A4).

Azure Pipelines exposes System.PullRequest.* but neither the PR labels nor its title, so the
guards job reads both over the REST API with the job token and hands them to the next step as
pipeline variables (logging commands on stdout):

    ##vso[task.setvariable variable=PR_LABELS]test-removal-ok,other
    ##vso[task.setvariable variable=PR_LABELS_SET]1
    ##vso[task.setvariable variable=PR_TITLE]feat(x): the title

PR_LABELS_SET=1 tells check-test-tampering.sh that PR_LABELS is authoritative even when empty,
so an unlabelled PR fails a test removal instead of passing with a "no PR context" warning.

Usage (an Azure Pipelines step; the token must be mapped into the step's env explicitly):
    python3 tools/testguard/ado_pr_context.py

Env: SYSTEM_PULLREQUEST_PULLREQUESTID (set on build-validation runs only), SYSTEM_COLLECTIONURI,
SYSTEM_TEAMPROJECT, BUILD_REPOSITORY_NAME, BUILD_REASON (preset by Azure Pipelines),
SYSTEM_ACCESSTOKEN (`SYSTEM_ACCESSTOKEN: $(System.AccessToken)` under the step's `env:`).
No PR id and not a PR build: prints nothing, exit 0 (a main run has no PR context).
Any failure on a PR build: exit 1, so the guard fails closed rather than judging without labels.
Stdlib only; REST api-version 7.1.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "7.1"
TIMEOUT = 30
REQUIRED = ("SYSTEM_COLLECTIONURI", "SYSTEM_TEAMPROJECT", "BUILD_REPOSITORY_NAME", "SYSTEM_ACCESSTOKEN")


class ContextError(Exception):
    pass


def escape(value: str) -> str:
    """Escape a logging-command value: a title can never end the line or start a second command."""
    return value.replace("%", "%AZP25").replace("\r", "%0D").replace("\n", "%0A")


def get_json(url: str, token: str, urlopen) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    where = url.split("?", 1)[0]
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ContextError(f"HTTP {exc.code} from {where}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise ContextError(f"cannot reach {where}: {getattr(exc, 'reason', exc)}") from None
    except ValueError:  # an HTML sign-in page instead of JSON, or bytes that are not UTF-8
        raise ContextError(f"no JSON from {where} (token not accepted?)") from None
    if not isinstance(data, dict):
        raise ContextError(f"unexpected response shape from {where}")
    return data


def pr_context(env, urlopen) -> tuple:
    """(labels, title) of the PR the build validates."""
    pr_id = env["SYSTEM_PULLREQUEST_PULLREQUESTID"].strip()
    if not pr_id.isdigit():
        raise ContextError(f"System.PullRequest.PullRequestId is not a number: {pr_id!r}")
    base = "{}/{}/_apis/git/repositories/{}/pullRequests/{}".format(
        env["SYSTEM_COLLECTIONURI"].rstrip("/"),
        urllib.parse.quote(env["SYSTEM_TEAMPROJECT"], safe=""),
        urllib.parse.quote(env["BUILD_REPOSITORY_NAME"], safe=""),
        pr_id,
    )
    token = env["SYSTEM_ACCESSTOKEN"]
    pr = get_json(f"{base}?api-version={API_VERSION}", token, urlopen)
    title = pr.get("title")
    if not isinstance(title, str):
        raise ContextError(f"pull request {pr_id} has no title in the response")
    value = get_json(f"{base}/labels?api-version={API_VERSION}", token, urlopen).get("value")
    if not isinstance(value, list) or not all(isinstance(v, dict) and isinstance(v.get("name"), str) for v in value):
        raise ContextError(f"unexpected labels response for pull request {pr_id}")
    labels = [v["name"] for v in value if v.get("active", True) is not False]
    return labels, title


def main(env=None, urlopen=None, out=None, err=None) -> int:
    env = os.environ if env is None else env
    urlopen = urlopen or urllib.request.urlopen
    out = out or sys.stdout
    err = err or sys.stderr
    if not env.get("SYSTEM_PULLREQUEST_PULLREQUESTID", "").strip():
        if env.get("BUILD_REASON") == "PullRequest":
            err.write("ado-pr-context: Build.Reason is PullRequest but System.PullRequest.PullRequestId is unset;"
                      " failing closed\n")
            return 1
        return 0  # not a PR build: nothing to resolve
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        hint = ""
        if "SYSTEM_ACCESSTOKEN" in missing:
            hint = " (map SYSTEM_ACCESSTOKEN: $(System.AccessToken) into the step env)"
        err.write(f"ado-pr-context: missing env {', '.join(missing)}{hint}; failing closed\n")
        return 1
    try:
        labels, title = pr_context(env, urlopen)
    except ContextError as exc:
        err.write(f"ado-pr-context: {exc}; failing closed (the test-tampering guard needs the PR labels)\n")
        return 1
    out.write(f"##vso[task.setvariable variable=PR_LABELS]{escape(','.join(labels))}\n")
    out.write("##vso[task.setvariable variable=PR_LABELS_SET]1\n")
    out.write(f"##vso[task.setvariable variable=PR_TITLE]{escape(title)}\n")
    err.write(f"ado-pr-context: pull request {env['SYSTEM_PULLREQUEST_PULLREQUESTID'].strip()}: "
              f"{len(labels)} label(s)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
