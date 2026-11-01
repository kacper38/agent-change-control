#!/usr/bin/env python3
"""evidence-export — captured check outputs and closed change records for an evidence pack (plan step 3.7).

  evidence_export.py capture --tag TAG --name NAME -- CMD [ARG...]
      run CMD from the repo root, save its combined output verbatim to evidence/TAG/NAME.txt and record
      the command, exit code, sha256, size and the tool's `--version` line in evidence/TAG/captures.json;
      exits with CMD's own code, so a failing check still fails the step that captured it
  evidence_export.py export --tag TAG --from REF [--to REF] [--repo OWNER/NAME]
      read-only through `gh api`: pull requests whose merge commit lies in `git rev-list FROM..TO`
      (author, merger, merge SHA, reviews, check runs on the merge SHA), the issues they reference with
      `Refs #N` plus every issue closed in the window (labels, tracker markers, acceptance boxes,
      closed_by), the repository rulesets, the captures re-hashed (`intact`), and tool versions;
      writes evidence/TAG/change-records.json and prints its sha256
Standard library plus gh (auth reused); never writes to GitHub. `validation-evidence` calls both verbs.
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
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracker  # noqa: E402

VERSION = "0.1.0"
SCHEMA = "agent-change-control/change-records/1"
EVIDENCE_DIR = "evidence"
PER_PAGE = 100
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REFS_RE = re.compile(r"\bRefs #(\d+)\b")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc(iso: str) -> str:
    """git %cI (offset form) -> the Z form GitHub uses, so the two compare as strings."""
    return _dt.datetime.fromisoformat(iso.strip()).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    def __init__(self, repo: Optional[str] = None):
        self.backend = tracker.GitHubBackend(repo)

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


def _issue_record(api: Callable, repo: str, number: int) -> dict:
    d = api(f"repos/{repo}/issues/{number}")
    comments = list(paged(api, f"repos/{repo}/issues/{number}/comments"))
    issue = tracker.Issue(
        number=int(d["number"]), title=d.get("title", ""), body=d.get("body") or "",
        labels=[lb["name"] for lb in d.get("labels", [])], state=str(d.get("state", "")).lower(),
        comments=[tracker.Comment((c.get("user") or {}).get("login", ""), c.get("body") or "", c.get("created_at", ""))
                  for c in comments or []],
    )
    markers = []
    for m in tracker.marks(issue):
        author = m.pop("_author", "")
        markers.append({**m, "author": author})
    return {
        "number": issue.number,
        "title": issue.title,
        "url": d.get("html_url", ""),
        "state": issue.state,
        "labels": issue.labels,
        "type": tracker.type_of(issue),
        "status": next((lb[len("status/"):] for lb in issue.labels if lb.startswith("status/")), None),
        "created_at": d.get("created_at"),
        "closed_at": d.get("closed_at"),
        "closed_by": (d.get("closed_by") or {}).get("login"),
        "acceptance": [{"checked": checked, "text": text} for checked, text in tracker.parse_ac(issue.body)],
        "markers": markers,
        "pull_requests": [],
    }


def collect(api: Callable, git: Callable, repo: str, frm: str, to: str, captures_dir: str) -> dict:
    """Everything the records file holds except the tool table; pure given `api` and `git`."""
    from_sha, to_sha = git("rev-parse", f"{frm}^{{commit}}"), git("rev-parse", f"{to}^{{commit}}")
    since, until = to_utc(git("log", "-1", "--format=%cI", from_sha)), to_utc(git("log", "-1", "--format=%cI", to_sha))
    commits = git("rev-list", f"{from_sha}..{to_sha}").split()
    in_range = set(commits)
    prs, excluded = [], []
    for pr in paged(api, f"repos/{repo}/pulls", stop=lambda p: (p.get("updated_at") or "") < since,
                    state="closed", sort="updated", direction="desc"):
        if not pr.get("merged_at"):
            continue
        if pr.get("merge_commit_sha") not in in_range:
            if since <= pr["merged_at"] <= until:
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
        })
    prs.sort(key=lambda p: p["number"])
    numbers = {ref for p in prs for ref in p["refs"]}
    for it in paged(api, f"repos/{repo}/issues", state="closed", since=since, sort="updated", direction="desc"):
        if "pull_request" in it or not it.get("closed_at"):
            continue
        if since <= it["closed_at"] <= until:
            numbers.add(int(it["number"]))
    issues = [_issue_record(api, repo, n) for n in sorted(numbers)]
    for issue in issues:
        issue["pull_requests"] = [p["number"] for p in prs if issue["number"] in p["refs"]]
    rulesets = []
    for rs in api(f"repos/{repo}/rulesets") or []:
        d = api(f"repos/{repo}/rulesets/{rs['id']}")
        rulesets.append({k: d.get(k) for k in ("id", "name", "target", "enforcement", "conditions", "rules",
                                                "bypass_actors", "created_at", "updated_at")})
    captures = []
    for e in load_captures(os.path.join(captures_dir, "captures.json")):
        path = os.path.join(captures_dir, str(e.get("file") or ""))
        now = sha256_file(path) if os.path.isfile(path) else None
        captures.append({**e, "sha256_now": now, "intact": now == e.get("sha256")})
    return {
        "repo": repo,
        "range": {"from": frm, "from_sha": from_sha, "to": to, "to_sha": to_sha, "since": since, "until": until,
                  "commits": len(commits)},
        "pull_requests": prs,
        "pull_requests_merged_elsewhere": sorted(excluded),
        "issues": issues,
        "rulesets": rulesets,
        "captures": captures,
    }


def tool_table(root: str) -> dict:
    kit = None
    try:
        with open(os.path.join(root, ".claude", "kit-version"), encoding="utf-8") as fh:
            kit = fh.read().strip()
    except OSError:
        pass
    return {
        "evidence_export": VERSION,
        "tracker": tracker.VERSION,
        "gh": version_line(["gh"]),
        "git": version_line(["git"]),
        "python": sys.version.split()[0],
        "kit_version": kit,
    }


def cmd_export(tag: str, frm: str, to: str, repo: Optional[str], root: str, out, err, gh: Optional[Gh] = None) -> int:
    if not _NAME_RE.match(tag or ""):
        err.write("evidence-export: --tag takes letters, digits, dot, dash, underscore\n")
        return 2
    folder = os.path.join(root, EVIDENCE_DIR, tag)
    gh = gh or Gh(repo)
    try:
        name = gh.repo()
        records = collect(gh, make_git(root), name, frm, to, folder)
        login = gh.login()
    except (tracker.TrackerError, ValueError, KeyError, TypeError) as exc:
        err.write(f"evidence-export: {type(exc).__name__}: {exc}\n")
        return 1
    doc = {"schema": SCHEMA, "tag": tag, "generated_at": utcnow(), "generated_by": login, **records,
           "tools": tool_table(root)}
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "change-records.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    rel = os.path.relpath(path, root)
    out.write(f"wrote {rel}: {len(doc['pull_requests'])} pull request(s), {len(doc['issues'])} issue(s), "
              f"{len(doc['rulesets'])} ruleset(s), {len(doc['captures'])} capture(s); sha256 {sha256_file(path)}\n")
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main(argv: list, out=None, err=None, cwd: Optional[str] = None, gh: Optional[Gh] = None) -> int:
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
