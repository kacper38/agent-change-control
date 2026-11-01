#!/usr/bin/env python3
"""evidence-export — captured check outputs and closed change records for an evidence pack (plan steps 3.7, A6).

  evidence_export.py capture --tag TAG --name NAME -- CMD [ARG...]
      run CMD from the repo root, save its combined output verbatim to evidence/TAG/NAME.txt and record
      the command, exit code, sha256, size and the tool's `--version` line in evidence/TAG/captures.json;
      exits with CMD's own code, so a failing check still fails the step that captured it
  evidence_export.py export --tag TAG --from REF [--to REF] [--repo OWNER/NAME | ORG/PROJECT/REPO]
      read-only, on the forge `tracker.backend_for()` picks: pull requests whose merge commit lies in
      `git rev-list FROM..TO` (author, merger, merge SHA, reviews, checks on the merge SHA), the issues they
      reference with `Refs #N` plus every issue closed in the window (labels, tracker markers, acceptance
      boxes, closed_by), the branch protection, the captures re-hashed (`intact`), and tool versions;
      writes evidence/TAG/change-records.json and prints its sha256
  GitHub        `gh api` (auth reused); branch protection = the repository rulesets
  Azure DevOps  REST 7.1 through the tracker's AdoBackend: GETs, plus the WIQL query (a read sent as POST);
                reviews = vote threads plus the reviewers' current votes, checks = builds on the merge SHA plus
                the PR's policy evaluations, completionOptions per PR, work item revisions (field names only),
                the default branch's policy configurations, build retention; branch_acl stays null with a
                branch_acl_note (the ACL token form is unconfirmed)
Schema change-records/2 = /1 plus forge, api_version, tools.transport, completion_options (per PR), revisions
(per issue), policies, branch_acl, branch_acl_note and retention; a section the forge lacks is null (rulesets on
Azure DevOps, the Azure DevOps sections on GitHub). On Azure DevOps a review also carries `vote` (the raw value
its state maps from) and `source`, a check `raw_result` and `blocking`. Timestamps stay as the forge wrote them
and compare as datetimes. Standard library plus gh on GitHub; never writes to the forge. `validation-evidence`
calls both verbs.
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
from typing import Callable, Optional, Union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker  # noqa: E402

VERSION = "0.2.0"
SCHEMA = "agent-change-control/change-records/2"
EVIDENCE_DIR = "evidence"
PER_PAGE = 100
GITHUB_API = "2022-11-28"  # the GitHub REST version the records are read with (the API's default)
ADO_API = "7.1"
EVALUATIONS_API = "7.1-preview.1"
GIT_NAMESPACE = "2e9eb7ed-3c0a-47d4-87c1-0ffdd275fd87"  # the Git Repositories security namespace
CLOSED_DATE = "Microsoft.VSTS.Common.ClosedDate"
CLOSED_BY = "Microsoft.VSTS.Common.ClosedBy"
VOTE_STATE = {10: "APPROVED", 5: "APPROVED", 0: "COMMENTED", -5: "COMMENTED", -10: "CHANGES_REQUESTED"}
POLICY_CONCLUSION = {"approved": "success", "rejected": "failure", "broken": "failure", "notApplicable": "skipped"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REFS_RE = re.compile(r"\bRefs #(\d+)\b")
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc(iso: str) -> str:
    """git %cI (offset form) -> the Z form GitHub uses, for the record's window bounds."""
    return _dt.datetime.fromisoformat(iso.strip()).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(text: Optional[str]) -> Optional[_dt.datetime]:
    """An API or git timestamp as an aware UTC datetime: any fraction length (Azure DevOps sends up to seven
    digits, which Python 3.9 cannot parse), `Z`, an offset, or none (read as UTC). Empty -> None; anything
    else -> ValueError. Strings do not compare: '12:00:00.5Z' < '12:00:00Z' because '.' sorts before 'Z'."""
    if not text:
        return None
    m = _TS_RE.match(text.strip())
    if not m:
        raise ValueError(f"not an ISO 8601 timestamp: {text!r}")
    base, frac, zone = m.groups()
    frac = "." + frac[:6].ljust(6, "0") if frac else ""
    zone = "+00:00" if zone in (None, "Z") else zone
    return _dt.datetime.fromisoformat(base + frac + zone).astimezone(_dt.timezone.utc)


def within(text: Optional[str], since: _dt.datetime, until: _dt.datetime) -> bool:
    t = parse_ts(text)
    return t is not None and since <= t <= until


def before(text: Optional[str], bound: _dt.datetime) -> bool:
    """True when the timestamp is earlier than `bound` or missing (a list sorted desc by it ends there)."""
    t = parse_ts(text)
    return t is None or t < bound


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def version_line(cmd: list, cwd: Optional[str] = None) -> str:
    """`<tool> --version` for the command's entry point (`python -m x` asks module x)."""
    if len(cmd) >= 3 and cmd[1] == "-m" and os.path.basename(cmd[0]).startswith("python"):
        probe = [cmd[0], "-m", cmd[2], "--version"]
    else:
        probe = [cmd[0], "--version"]
    try:
        r = subprocess.run(probe, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if r.returncode != 0:  # an error line is not a version
        return "unknown"
    return first_line(r.stdout) or first_line(r.stderr) or "unknown"


def repo_root(cwd: Optional[str] = None) -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.SubprocessError):
        r = None
    return r.stdout.strip() if r and r.returncode == 0 and r.stdout.strip() else (cwd or os.getcwd())


def load_captures(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


# ----------------------------------------------------------------------------
# capture
# ----------------------------------------------------------------------------


def cmd_capture(tag: str, name: str, cmd: list, root: str, out, err) -> int:
    if not _NAME_RE.match(name or "") or not _NAME_RE.match(tag or ""):
        err.write("evidence-export: --tag and --name take letters, digits, dot, dash, underscore\n")
        return 2
    if not cmd:
        err.write("evidence-export: nothing to run after `--`\n")
        return 2
    folder = os.path.join(root, EVIDENCE_DIR, tag)
    os.makedirs(folder, exist_ok=True)
    try:
        r = subprocess.run(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        err.write(f"evidence-export: cannot run {cmd[0]}: {exc}\n")
        return 1
    rel = f"{name}.txt"
    path = os.path.join(folder, rel)
    with open(path, "wb") as fh:
        fh.write(r.stdout)
    entry = {
        "name": name,
        "command": shlex.join(cmd),
        "exit_code": r.returncode,
        "file": rel,
        "bytes": len(r.stdout),
        "sha256": sha256_file(path),
        "tool_version": version_line(cmd, root),
        "captured_at": utcnow(),
    }
    manifest = os.path.join(folder, "captures.json")
    entries = [e for e in load_captures(manifest) if e.get("name") != name] + [entry]
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(sorted(entries, key=lambda e: e.get("name", "")), fh, indent=2, sort_keys=True)
        fh.write("\n")
    out.write(f"captured {name}: exit {r.returncode}, {entry['bytes']} bytes, sha256 {entry['sha256'][:16]}, "
              f"{entry['tool_version']}\n")
    return r.returncode


# ----------------------------------------------------------------------------
# export
# ----------------------------------------------------------------------------


class Gh:
    """`gh api` reads through the tracker's backend, so auth and the repo default are the same."""

    def __init__(self, repo: Optional[str] = None, backend: Optional[tracker.GitHubBackend] = None):
        self.backend = backend or tracker.GitHubBackend(repo)

    def repo(self) -> str:
        return self.backend.repo_full()

    def __call__(self, path: str, **params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return json.loads(self.backend._run(["api", f"{path}?{query}" if query else path]))

    def login(self) -> str:
        return self.backend.whoami()


def make_git(root: str) -> Callable:
    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise tracker.TrackerError(f"git {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
        return r.stdout.strip()
    return git


def paged(api: Callable, path: str, stop: Optional[Callable] = None, **params):
    """Items across pages; stops after the first item `stop` rejects (lists sorted desc by that key)."""
    page = 1
    while True:
        items = api(path, per_page=PER_PAGE, page=page, **params)
        if not isinstance(items, list):
            return
        for item in items:
            if stop and stop(item):
                return
            yield item
        if len(items) < PER_PAGE:
            return
        page += 1


def check_runs(api: Callable, repo: str, sha: str) -> list:
    """Every check run on a commit (the endpoint wraps its list, so `paged` does not fit)."""
    runs, page = [], 1
    while True:
        batch = (api(f"repos/{repo}/commits/{sha}/check-runs", per_page=PER_PAGE, page=page) or {}).get("check_runs")
        runs += batch or []
        if len(batch or []) < PER_PAGE:
            return runs
        page += 1


def _issue_common(issue: tracker.Issue) -> dict:
    """The parts of an issue record both forges derive the same way from a tracker.Issue."""
    markers = []
    for m in tracker.marks(issue):
        author = m.pop("_author", "")
        markers.append({**m, "author": author})
    return {
        "number": issue.number,
        "title": issue.title,
        "state": issue.state,
        "labels": issue.labels,
        "type": tracker.type_of(issue),
        "status": next((lb[len("status/"):] for lb in issue.labels if lb.startswith("status/")), None),
        "acceptance": [{"checked": checked, "text": text} for checked, text in tracker.parse_ac(issue.body)],
        "markers": markers,
    }


def _issue_record(api: Callable, repo: str, number: int) -> dict:
    d = api(f"repos/{repo}/issues/{number}")
    comments = list(paged(api, f"repos/{repo}/issues/{number}/comments"))
    issue = tracker.Issue(
        number=int(d["number"]), title=d.get("title", ""), body=d.get("body") or "",
        labels=[lb["name"] for lb in d.get("labels", [])], state=str(d.get("state", "")).lower(),
        comments=[tracker.Comment((c.get("user") or {}).get("login", ""), c.get("body") or "", c.get("created_at", ""))
                  for c in comments or []],
    )
    return {
        **_issue_common(issue),
        "url": d.get("html_url", ""),
        "created_at": d.get("created_at"),
        "closed_at": d.get("closed_at"),
        "closed_by": (d.get("closed_by") or {}).get("login"),
        "pull_requests": [],
        "revisions": None,
    }


def git_range(git: Callable, frm: str, to: str) -> tuple:
    """(the record's `range`, the commits FROM..TO); the window is the two commits' committer dates."""
    from_sha, to_sha = git("rev-parse", f"{frm}^{{commit}}"), git("rev-parse", f"{to}^{{commit}}")
    since, until = to_utc(git("log", "-1", "--format=%cI", from_sha)), to_utc(git("log", "-1", "--format=%cI", to_sha))
    commits = git("rev-list", f"{from_sha}..{to_sha}").split()
    return {"from": frm, "from_sha": from_sha, "to": to, "to_sha": to_sha, "since": since, "until": until,
            "commits": len(commits)}, commits


def recheck_captures(captures_dir: str) -> list:
    captures = []
    for e in load_captures(os.path.join(captures_dir, "captures.json")):
        path = os.path.join(captures_dir, str(e.get("file") or ""))
        now = sha256_file(path) if os.path.isfile(path) else None
        captures.append({**e, "sha256_now": now, "intact": now == e.get("sha256")})
    return captures


def collect(api: Callable, git: Callable, repo: str, frm: str, to: str, captures_dir: str) -> dict:
    """Everything the records file holds except the tool table; pure given `api` and `git`."""
    rng, commits = git_range(git, frm, to)
    since, until = parse_ts(rng["since"]), parse_ts(rng["until"])
    in_range = set(commits)
    prs, excluded = [], []
    for pr in paged(api, f"repos/{repo}/pulls", stop=lambda p: before(p.get("updated_at"), since),
                    state="closed", sort="updated", direction="desc"):
        if not pr.get("merged_at"):
            continue
        if pr.get("merge_commit_sha") not in in_range:
            if within(pr["merged_at"], since, until):
                excluded.append(pr["number"])
            continue
        n = int(pr["number"])
        detail = api(f"repos/{repo}/pulls/{n}")
        reviews = list(paged(api, f"repos/{repo}/pulls/{n}/reviews"))
        runs = check_runs(api, repo, pr["merge_commit_sha"])
        prs.append({
            "number": n,
            "title": pr.get("title", ""),
            "url": pr.get("html_url", ""),
            "author": (pr.get("user") or {}).get("login"),
            "head": (pr.get("head") or {}).get("ref"),
            "base": (pr.get("base") or {}).get("ref"),
            "merged_at": pr.get("merged_at"),
            "merged_by": (detail.get("merged_by") or {}).get("login"),
            "merge_sha": pr.get("merge_commit_sha"),
            "refs": sorted({int(x) for x in _REFS_RE.findall(pr.get("body") or "")}),
            "reviews": [{"user": (r.get("user") or {}).get("login"), "state": r.get("state"),
                         "submitted_at": r.get("submitted_at"), "commit_id": r.get("commit_id")} for r in reviews],
            "checks": [{"name": c.get("name"), "status": c.get("status"), "conclusion": c.get("conclusion"),
                        "app": (c.get("app") or {}).get("slug"), "started_at": c.get("started_at"),
                        "completed_at": c.get("completed_at"), "url": c.get("html_url")}
                       for c in runs],
            "completion_options": None,
        })
    prs.sort(key=lambda p: p["number"])
    numbers = {ref for p in prs for ref in p["refs"]}
    for it in paged(api, f"repos/{repo}/issues", state="closed", since=rng["since"], sort="updated",
                    direction="desc"):
        if "pull_request" in it or not it.get("closed_at"):
            continue
        if within(it["closed_at"], since, until):
            numbers.add(int(it["number"]))
    issues = [_issue_record(api, repo, n) for n in sorted(numbers)]
    for issue in issues:
        issue["pull_requests"] = [p["number"] for p in prs if issue["number"] in p["refs"]]
    rulesets = []
    for rs in api(f"repos/{repo}/rulesets") or []:
        d = api(f"repos/{repo}/rulesets/{rs['id']}")
        rulesets.append({k: d.get(k) for k in ("id", "name", "target", "enforcement", "conditions", "rules",
                                                "bypass_actors", "created_at", "updated_at")})
    return {
        "repo": repo,
        "forge": "github",
        "api_version": GITHUB_API,
        "range": rng,
        "pull_requests": prs,
        "pull_requests_merged_elsewhere": sorted(excluded),
        "issues": issues,
        "rulesets": rulesets,
        "policies": None,
        "branch_acl": None,
        "branch_acl_note": None,
        "retention": None,
        "captures": recheck_captures(captures_dir),
    }


# ----------------------------------------------------------------------------
# export on Azure DevOps
# ----------------------------------------------------------------------------
# `import ado` stays inside the functions, as in tracker.backend_for(): the GitHub path never loads it.


class AdoReader:
    """Azure DevOps reads for the export through AdoBackend._request, so the token, the repository and the
    scope are the tracker's. GETs only, plus `wiql()`: the WIQL query is a read the API takes as a POST."""

    def __init__(self, backend: tracker.Backend):
        self.backend = backend

    def repo(self) -> str:
        """org/project/repo, the form --repo takes."""
        b = self.backend
        parts = urllib.parse.urlsplit(b.base)
        host = (parts.hostname or "").lower()
        org = host.split(".")[0] if host.endswith(".visualstudio.com") else urllib.parse.unquote(parts.path.strip("/"))
        return f"{org}/{b.project}/{b.repo}"

    def login(self) -> str:
        return self.backend.whoami()

    def __call__(self, path: str, api_version: str = ADO_API):
        return self.backend._request("GET", path, api_version=api_version)

    def pages(self, path: str) -> list:
        """A list that pages by continuation token (body field or x-ms-continuationtoken header)."""
        return self.backend._pages(path)

    def skip_pages(self, path: str, top: int = PER_PAGE, api_version: str = ADO_API, max_pages: int = 200) -> list:
        """A list that pages by $top/$skip, read until an empty page, so a server that caps $top below the
        asked size still yields every item. More than `max_pages` pages is an error, never a truncation."""
        import ado

        out: list = []
        sep = "&" if "?" in path else "?"
        for _ in range(max_pages):
            batch = ado.values(self(f"{path}{sep}$top={top}&$skip={len(out)}", api_version))
            if not batch:
                return out
            out += batch
        raise tracker.TrackerError(f"Azure DevOps {path.split('?')[0]}: more than {max_pages} pages")

    def wiql(self, query: str) -> list:
        import ado

        found = self.backend._request("POST", "_apis/wit/wiql", {"query": query})
        return [int(w["id"]) for w in ado.values(found, "workItems")]


def vote_state(vote: int) -> str:
    """10 approved and 5 approved with suggestions -> APPROVED; -10 rejected -> CHANGES_REQUESTED;
    -5 waiting for the author, 0 no vote (a reset) and any unknown value -> COMMENTED."""
    return VOTE_STATE.get(vote, "COMMENTED")


def _value(prop):
    """A PR thread property {"$type": ..., "$value": x} -> x."""
    return prop.get("$value") if isinstance(prop, dict) else prop


def ado_reviews(threads: list, reviewers: list) -> list:
    """The vote history from the system threads that carry CodeReviewVoteResult (source `thread`, oldest
    first), then each reviewer's vote at export time (source `reviewer`, no timestamp). `vote` keeps the
    value the state was mapped from; Azure DevOps ties no commit to a vote, so commit_id is null."""
    import ado

    out = []
    for t in sorted(threads, key=lambda t: int(t.get("id") or 0)):
        props = t.get("properties") or {}
        if "CodeReviewVoteResult" not in props or t.get("isDeleted"):
            continue
        vote = int(_value(props["CodeReviewVoteResult"]))
        voter = (t.get("identities") or {}).get(str(_value(props.get("CodeReviewVotedByIdentity"))))
        first = (t.get("comments") or [{}])[0]
        out.append({"user": ado.ident(voter) or ado.ident(first.get("author")) or None, "state": vote_state(vote),
                    "submitted_at": t.get("publishedDate"), "commit_id": None, "vote": vote, "source": "thread"})
    for r in reviewers:
        vote = int(r.get("vote") or 0)
        out.append({"user": ado.ident(r) or None, "state": vote_state(vote), "submitted_at": None,
                    "commit_id": None, "vote": vote, "source": "reviewer"})
    return out


def build_record(b: dict) -> dict:
    """A build as a check, normalised as pr_checks does (ado.build_check); raw_result keeps the build result."""
    import ado

    c = ado.build_check(b)
    return {"name": c.name, "status": c.status, "conclusion": c.conclusion, "app": "azure-pipelines",
            "started_at": b.get("startTime"), "completed_at": b.get("finishTime"), "url": c.url or None,
            "raw_result": b.get("result"), "blocking": None}


def policy_record(e: dict) -> dict:
    """A policy evaluation as a check: approved -> success; rejected, broken -> failure; notApplicable ->
    skipped; queued and running are not completed. `blocking` is whether the policy gates completion."""
    cfg = e.get("configuration") or {}
    status = e.get("status") or ""
    done = status in POLICY_CONCLUSION
    return {"name": (cfg.get("type") or {}).get("displayName") or f"policy {cfg.get('id')}",
            "status": "completed" if done else ("queued" if status == "queued" else "in_progress"),
            "conclusion": POLICY_CONCLUSION.get(status, ""), "app": "azure-repos-policy",
            "started_at": e.get("startedDate"), "completed_at": e.get("completedDate"), "url": None,
            "raw_result": status, "blocking": cfg.get("isBlocking")}


def _ado_pr(reader: AdoReader, number: int, sha: str, project_id: str, builds: list) -> dict:
    import ado

    b = reader.backend
    path = f"_apis/git/repositories/{ado.q(b.repo)}/pullrequests/{number}"
    d = reader(path)  # the detail: list items may truncate the description that holds `Refs #N`
    threads = ado.values(reader(f"{path}/threads"))
    artifact = ado.q(f"vstfs:///CodeReview/CodeReviewId/{project_id}/{number}")
    evaluations = reader.skip_pages(f"_apis/policy/evaluations?artifactId={artifact}&includeNotApplicable=true",
                                    api_version=EVALUATIONS_API)
    opts = d.get("completionOptions") or {}
    return {
        "number": number,
        "title": d.get("title", ""),
        "url": b.pr_url(number),
        "author": ado.ident(d.get("createdBy")) or None,
        "head": ado.strip_ref(d.get("sourceRefName")),
        "base": ado.strip_ref(d.get("targetRefName")),
        "merged_at": d.get("closedDate"),
        "merged_by": ado.ident(d.get("closedBy")) or None,
        "merge_sha": sha,
        "refs": sorted({int(x) for x in _REFS_RE.findall(d.get("description") or "")}),
        "reviews": ado_reviews(threads, d.get("reviewers") or []),
        "checks": [build_record(x) for x in builds if x.get("sourceVersion") == sha]
                  + [policy_record(e) for e in evaluations],
        "completion_options": {k: opts.get(k) for k in ("transitionWorkItems", "bypassPolicy", "bypassReason",
                                                         "mergeStrategy")},
    }


def _ado_issue_record(reader: AdoReader, number: int, item: Optional[dict] = None) -> dict:
    """A work item as the backend reads it (labels, type, status, state, markers), outside its scope check,
    plus the revisions: rev, who, when and the names of the changed fields, never their values."""
    import ado

    b = reader.backend
    d = item or reader(f"_apis/wit/workitems/{int(number)}")
    issue = b._issue(d, b._comments(number))
    f = d.get("fields") or {}
    updates = reader.skip_pages(f"_apis/wit/workItems/{int(number)}/updates", top=200)
    return {
        **_issue_common(issue),
        "url": issue.url,
        "created_at": f.get("System.CreatedDate"),
        "closed_at": f.get(CLOSED_DATE),
        "closed_by": ado.ident(f.get(CLOSED_BY)) or None,
        "pull_requests": [],
        "revisions": [{"rev": u.get("rev"), "revised_by": ado.ident(u.get("revisedBy")) or None,
                       "revised_at": u.get("revisedDate"), "fields": sorted(u.get("fields") or {})}
                      for u in updates],
    }


def collect_ado(reader: AdoReader, git: Callable, repo: str, frm: str, to: str, captures_dir: str) -> dict:
    """collect() for Azure DevOps: the same keys from the Azure DevOps sources; pure given `reader` and `git`."""
    import ado

    b = reader.backend
    rng, commits = git_range(git, frm, to)
    since, until = parse_ts(rng["since"]), parse_ts(rng["until"])
    in_range = set(commits)
    repo_path = f"_apis/git/repositories/{ado.q(b.repo)}"
    repository = reader(repo_path)
    repo_id, project_id = repository["id"], repository["project"]["id"]
    branch = repository.get("defaultBranch") or "refs/heads/main"
    listing = reader.skip_pages(f"{repo_path}/pullrequests?searchCriteria.status=completed"
                                f"&searchCriteria.targetRefName={ado.q(branch)}")
    members, excluded = [], []
    for item in listing:
        number, sha = int(item["pullRequestId"]), (item.get("lastMergeCommit") or {}).get("commitId")
        if sha in in_range:
            members.append((number, sha))
        elif within(item.get("closedDate"), since, until):
            excluded.append(number)
    builds = reader.pages(f"_apis/build/builds?queryOrder=queueTimeDescending&$top=200&repositoryId={repo_id}"
                          f"&repositoryType=TfsGit&branchName={ado.q(branch)}") if members else []
    prs = sorted((_ado_pr(reader, n, sha, project_id, builds) for n, sha in members), key=lambda p: p["number"])
    numbers = {ref for p in prs for ref in p["refs"]}
    # WIQL compares dates without a time unless timePrecision is set, and in the caller's time zone: ask
    # for a day more on each side, then cut the window exactly here
    day = _dt.timedelta(days=1)
    query = ("SELECT [System.Id] FROM WorkItems WHERE "
             f"[System.AreaPath] UNDER {ado.wiql_str(b.area)} AND [System.WorkItemType] = {ado.wiql_str(b.wit)} "
             f"AND [{CLOSED_DATE}] >= '{since - day:%Y-%m-%d}' AND [{CLOSED_DATE}] <= '{until + day:%Y-%m-%d}' "
             "ORDER BY [System.Id]")
    closed = {}
    for n in reader.wiql(query):
        d = reader(f"_apis/wit/workitems/{n}")
        if within((d.get("fields") or {}).get(CLOSED_DATE), since, until):
            closed[n] = d
    issues = [_ado_issue_record(reader, n, closed.get(n)) for n in sorted(numbers | set(closed))]
    for issue in issues:
        issue["pull_requests"] = [p["number"] for p in prs if issue["number"] in p["refs"]]
    configs = reader.pages(f"_apis/git/policy/configurations?repositoryId={repo_id}&refName={ado.q(branch)}")
    policies = [{"id": c.get("id"), "type": (c.get("type") or {}).get("displayName"), "isEnabled": c.get("isEnabled"),
                 "isBlocking": c.get("isBlocking"), "settings": c.get("settings")} for c in configs]
    note = (f"not exported: the branch token of the Git Repositories security namespace ({GIT_NAMESPACE}) is "
            f"unconfirmed offline (candidate repoV2/{project_id}/{repo_id}/{branch}, possibly with hex-encoded "
            "branch segments); a token that matches nothing returns an empty ACL, which would read as no restriction")
    return {
        "repo": repo,
        "forge": "ado",
        "api_version": ADO_API,
        "range": rng,
        "pull_requests": prs,
        "pull_requests_merged_elsewhere": sorted(excluded),
        "issues": issues,
        "rulesets": None,
        "policies": policies,
        "branch_acl": None,
        "branch_acl_note": note,
        "retention": reader("_apis/build/retention"),
        "captures": recheck_captures(captures_dir),
    }


def tool_table(root: str, forge: str = "github") -> dict:
    """`transport` is what read the forge: the gh version line, or urllib (gh is null on Azure DevOps)."""
    kit = None
    try:
        with open(os.path.join(root, ".claude", "kit-version"), encoding="utf-8") as fh:
            kit = fh.read().strip()
    except OSError:
        pass
    gh = version_line(["gh"]) if forge == "github" else None
    return {
        "evidence_export": VERSION,
        "tracker": tracker.VERSION,
        "gh": gh,
        "git": version_line(["git"]),
        "python": sys.version.split()[0],
        "kit_version": kit,
        "transport": gh if forge == "github" else "urllib",
    }


def reader_for(repo: Optional[str]) -> Union[Gh, AdoReader]:
    """The export's reader for the backend tracker.backend_for() picks: Gh on GitHub, AdoReader on Azure DevOps."""
    backend = tracker.backend_for(repo)
    if isinstance(backend, tracker.GitHubBackend):
        return Gh(backend=backend)
    if backend.name == "ado":
        return AdoReader(backend)
    raise tracker.TrackerError(f"no evidence reader for the {backend.name} backend")


def cmd_export(tag: str, frm: str, to: str, repo: Optional[str], root: str, out, err,
               gh: Optional[Union[Gh, AdoReader]] = None) -> int:
    """`gh` (tests): a ready reader, Gh-like or AdoReader; else the one for the backend backend_for() picks."""
    if not _NAME_RE.match(tag or ""):
        err.write("evidence-export: --tag takes letters, digits, dot, dash, underscore\n")
        return 2
    folder = os.path.join(root, EVIDENCE_DIR, tag)
    try:
        reader = gh if gh is not None else reader_for(repo)
        name = reader.repo()
        gather = collect_ado if isinstance(reader, AdoReader) else collect
        records = gather(reader, make_git(root), name, frm, to, folder)
        login = reader.login()
    except (tracker.TrackerError, ValueError, KeyError, TypeError) as exc:
        err.write(f"evidence-export: {type(exc).__name__}: {exc}\n")
        return 1
    doc = {"schema": SCHEMA, "tag": tag, "generated_at": utcnow(), "generated_by": login, **records,
           "tools": tool_table(root, records["forge"])}
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "change-records.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    rel = os.path.relpath(path, root)
    protection = (f"{len(doc['rulesets'])} ruleset(s)" if doc["rulesets"] is not None
                  else f"{len(doc['policies'])} policy configuration(s)")
    out.write(f"wrote {rel}: {len(doc['pull_requests'])} pull request(s), {len(doc['issues'])} issue(s), "
              f"{protection}, {len(doc['captures'])} capture(s); sha256 {sha256_file(path)}\n")
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main(argv: list, out=None, err=None, cwd: Optional[str] = None,
         gh: Optional[Union[Gh, AdoReader]] = None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    if not argv or argv[0] in ("help", "-h", "--help"):
        out.write(__doc__.strip() + "\n")
        return 0
    ap = argparse.ArgumentParser(prog="evidence_export", add_help=False)
    sub = ap.add_subparsers(dest="verb")
    c = sub.add_parser("capture", add_help=False)
    c.add_argument("--tag", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("cmd", nargs=argparse.REMAINDER)
    e = sub.add_parser("export", add_help=False)
    e.add_argument("--tag", required=True)
    e.add_argument("--from", dest="frm", required=True)
    e.add_argument("--to", default="HEAD")
    e.add_argument("--repo")
    try:
        ns = ap.parse_args(argv)
    except SystemExit:
        err.write(__doc__.strip() + "\n")
        return 2
    root = repo_root(cwd)
    if ns.verb == "capture":
        cmd = ns.cmd[1:] if ns.cmd[:1] == ["--"] else ns.cmd
        return cmd_capture(ns.tag, ns.name, cmd, root, out, err)
    if ns.verb == "export":
        return cmd_export(ns.tag, ns.frm, ns.to, ns.repo, root, out, err, gh=gh)
    err.write(__doc__.strip() + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
