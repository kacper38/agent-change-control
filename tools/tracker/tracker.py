#!/usr/bin/env python3
"""tracker — task tracker CLI; GitHub Issues are the system of record (plan steps 2.4, 2.5).

Standard library only, Python >= 3.9. Labels carry the state. Every write runs all
guards first, then posts one comment, then makes one label change (add the new
status, then remove its siblings, so a crash leaves two labels rather than none).
No delete or force verb exists for agents. An issue closes through `owner done`,
which refuses without a terminal (a human), or through `delegate done`, which a
session runs only where the owner's delegation is merged on the default branch.

Verbs
  help                                   this text
  list [--status S] [--type T] [--all]   open issues (closed too with --all)
  show N                                 title, labels, acceptance criteria, tracker comments
  new --title X --ac A [--ac A2 ...] --scope S --scope-limit L --source SRC [--type T]
                                         create in status/backlog (type: todo|bug|handoff|decision|agent-note)
  claim N [--branch B]                   ready -> in-progress; one in-progress per login and seat (the box
                                         marker's `seat`; none on the host)
  block N --question Q                   in-progress -> blocked; Q must name a path or a field
  review N --pr URL|NUMBER               in-progress -> review; PR head = claimed branch, body has `Refs #N`
  note N TEXT                            comment on an issue, no status change
  owner labels-sync                      create or update the label families; never deletes
  owner ready N [N ...]                  backlog|blocked -> ready after the definition of ready; freezes the body;
                                         every item is checked first, and none changes when one fails
  owner done N [N ...] [--waive I "reason"]... | --accept-all
                                         review -> done after the closing protocol; closes the issue; every item
                                         is checked first; --waive with one number only; --accept-all prints
                                         each item, asks once and ticks every unchecked box
  delegate ready N [N ...] --word TEXT   `owner ready` for a session (CLAUDE_CODE_SESSION_ID set, no box marker,
                                         KZ_BOUNDARY unset or own) where .claude/guard.json on the default branch
                                         says "boundary": "own" and "owner_verbs": "delegated"; TEXT = the owner's
                                         words (one line, at most 500 characters, no `-->`); the mark names both
  delegate done N [N ...] --word TEXT --evidence FILE
                                         `owner done` with every check of it, under the same delegation; FILE is
                                         JSON {"N": {"criterion index": "line naming a path or URL"}}, one line for
                                         each criterion of each item; ticks no box, waives nothing; closes the issue

Options: --repo OWNER/NAME (GitHub) or ORG/PROJECT/REPO (Azure DevOps); default: the cwd's origin
Backend: env KZ_TRACKER_BACKEND=github|ado, else the origin host (dev.azure.com, *.visualstudio.com
         -> ado), else github
Exit codes: 0 ok; 2 refused by a guard or the transition table; 1 error.
"""

import argparse
import base64
import dataclasses
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Optional

VERSION = "0.3.0"
BOX_MARKER = "/etc/agent-box/box.json"  # tools/box/marker.py: root-owned, 0444, written once by the box's entrypoint
_SEAT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}")  # marker.py's plain token
DELEGATION_FILE = ".claude/guard.json"  # its copy on the default branch delegates the owner verbs, never the work tree
FREE_TEXT_MAX = 500  # --word and each evidence line

# ----------------------------------------------------------------------------
# Data model (step 2.4): label families and the transition table
# ----------------------------------------------------------------------------

TYPES = ("bug", "todo", "handoff", "decision", "agent-note")
STATUSES = ("backlog", "ready", "in-progress", "blocked", "review", "done", "dropped")
LABELS = {  # name -> (color, description)
    "type/bug": ("d73a4a", "Something is wrong"),
    "type/todo": ("0e8a16", "Work to do"),
    "type/handoff": ("5319e7", "Session handoff for the next agent"),
    "type/decision": ("fbca04", "Needs a human decision"),
    "type/agent-note": ("c5def5", "Agent observation; no action required"),
    "status/backlog": ("ededed", "Captured, not yet ready"),
    "status/ready": ("0075ca", "Definition of ready met (a human promoted it)"),
    "status/in-progress": ("1d76db", "Claimed by one actor"),
    "status/blocked": ("b60205", "Waiting for a human answer"),
    "status/review": ("6f42c1", "PR open; awaiting review and merge"),
    "status/done": ("0e8a16", "Closed by the protocol"),
    "status/dropped": ("cfd3d7", "Closed without doing"),
}
HUMAN, AGENT = "human", "agent"
DELEGATE = "delegate"  # a session under the owner's committed delegation; only the `delegate` verbs act as it
TRANSITIONS: dict = {
    (None, "backlog"): {HUMAN, AGENT},
    ("backlog", "ready"): {HUMAN, DELEGATE},
    ("blocked", "ready"): {HUMAN, DELEGATE},
    ("ready", "in-progress"): {HUMAN, AGENT},
    ("in-progress", "blocked"): {HUMAN, AGENT},
    ("in-progress", "review"): {HUMAN, AGENT},
    ("review", "done"): {HUMAN, DELEGATE},
    ("done", "backlog"): {HUMAN},
    ("dropped", "backlog"): {HUMAN},
}
for _s in ("backlog", "ready", "in-progress", "blocked", "review"):
    TRANSITIONS[(_s, "dropped")] = {HUMAN}


class TrackerError(Exception):
    """Operational failure (gh, network, bad input): exit 1."""


class Refused(Exception):
    """A guard or the transition table said no: exit 2."""


class TransitionError(Refused):
    pass


def check_transition(frm: Optional[str], to: str, actor: str) -> None:
    allowed = TRANSITIONS.get((frm, to))
    if allowed is None:
        raise TransitionError(f"no transition {frm or 'new'} -> {to}")
    if actor not in allowed:
        who = " or ".join(sorted(allowed))
        raise TransitionError(f"{frm or 'new'} -> {to} is for {who}, not {actor}")


@dataclasses.dataclass
class Comment:
    author: str
    body: str
    created_at: str = ""


@dataclasses.dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: list
    state: str  # open | closed
    author: str = ""
    url: str = ""
    comments: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class PR:
    number: int
    url: str
    title: str
    body: str
    head: str
    base: str
    state: str  # open | closed | merged
    merged: bool
    merged_by: str
    merge_sha: str
    files: list
    completion_options: dict = dataclasses.field(default_factory=dict)  # Azure Repos completionOptions


@dataclasses.dataclass
class Check:
    name: str
    status: str
    conclusion: str
    url: str


def status_of(issue: Issue) -> Optional[str]:
    found = [lb[len("status/") :] for lb in issue.labels if lb.startswith("status/")]
    if len(found) != 1:
        raise Refused(f"#{issue.number} carries {len(found)} status labels ({', '.join(found) or 'none'}); "
                      "a human fixes that in the UI and label-lint reports it")
    return found[0]


def type_of(issue: Issue) -> Optional[str]:
    found = [lb[len("type/") :] for lb in issue.labels if lb.startswith("type/")]
    return found[0] if found else None


# ----------------------------------------------------------------------------
# Issue body: acceptance criteria, scope, source
# ----------------------------------------------------------------------------

_AC_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.+?)\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.MULTILINE)
SCOPE_LIMIT_KEY = "Scope limit:"


def parse_ac(body: str) -> list:
    """[(checked, text)] in document order."""
    return [(m.group(1).lower() == "x", m.group(2)) for m in _AC_RE.finditer(body or "")]


def section(body: str, name: str) -> str:
    """Text under a `## name` / `### name` heading up to the next heading (issue forms use ###)."""
    heads = list(_HEADING_RE.finditer(body or ""))
    for i, h in enumerate(heads):
        if h.group(1).strip().lower() == name.lower():
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            return body[h.end() : end].strip()
    return ""


def definition_of_ready(body: str) -> list:
    """What is missing for status/ready; empty means ready."""
    missing = []
    if not parse_ac(body):
        missing.append("at least one acceptance criterion (`- [ ] ...` under `## Acceptance criteria`)")
    scope = section(body, "Scope")
    if not scope:
        missing.append("a `## Scope` section")
    if not re.search(re.escape(SCOPE_LIMIT_KEY) + r"[ \t]*\S", body or ""):
        missing.append(f"a non-empty `{SCOPE_LIMIT_KEY}` line")
    if not section(body, "Source"):
        missing.append("a `## Source` section (plan step, conversation, incident, ...)")
    return missing


def compose_body(ac: list, scope: str, scope_limit: str, source: str) -> str:
    lines = ["## Acceptance criteria", ""]
    lines += [f"- [ ] {a.strip()}" for a in ac if a.strip()]
    lines += ["", "## Scope", "", scope.strip(), "", f"{SCOPE_LIMIT_KEY} {scope_limit.strip()}", "", "## Source", "",
              source.strip(), ""]
    return "\n".join(lines)


_CHECKED_RE = re.compile(r"^(\s*[-*]\s+)\[[xX]\]", re.MULTILINE)


def body_hash(body: str) -> str:
    """Hash of the change record: line endings and the state of acceptance boxes do not count."""
    text = _CHECKED_RE.sub(r"\1[ ]", (body or "").replace("\r\n", "\n").strip())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------
# Machine-readable comment markers: first line `<!-- tracker:{json} -->`
# ----------------------------------------------------------------------------

_MARK_RE = re.compile(r"^<!-- tracker:(\{.*?\}) -->", re.DOTALL)


def mark(kind: str, **fields) -> str:
    data = {"kind": kind, **fields}
    return "<!-- tracker:" + json.dumps(data, sort_keys=True) + " -->"


def marks(issue: Issue, kind: Optional[str] = None) -> list:
    out = []
    for c in issue.comments:
        m = _MARK_RE.match(c.body.strip())
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if kind is None or data.get("kind") == kind:
            data["_author"] = c.author
            out.append(data)
    return out


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------
# Backend protocol: FakeBackend for tests, GitHubBackend through gh
# ----------------------------------------------------------------------------


class Backend:
    name = "abstract"

    def whoami(self) -> str:
        raise NotImplementedError

    def get_issue(self, number: int) -> Issue:
        raise NotImplementedError

    def list_issues(self, labels: Optional[list] = None, state: str = "open") -> list:
        raise NotImplementedError

    def create_issue(self, title: str, body: str, labels: list) -> Issue:
        raise NotImplementedError

    def set_body(self, number: int, body: str) -> None:
        raise NotImplementedError

    def add_labels(self, number: int, labels: list) -> None:
        raise NotImplementedError

    def remove_labels(self, number: int, labels: list) -> None:
        raise NotImplementedError

    def comment(self, number: int, body: str) -> None:
        raise NotImplementedError

    def close_issue(self, number: int) -> None:
        raise NotImplementedError

    def ensure_label(self, name: str, color: str, description: str) -> str:
        """'created' | 'updated'."""
        raise NotImplementedError

    def list_labels(self) -> list:
        raise NotImplementedError

    def pr(self, ref: str) -> Optional[PR]:
        raise NotImplementedError

    def pr_checks(self, sha: str) -> list:
        raise NotImplementedError

    def committed_file(self, path: str) -> Optional[tuple]:
        """(blob id, text) of a file on the forge's default branch; None when it is not there."""
        raise Refused(f"delegated verbs are not available on the {self.name} backend")


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, user: str = "agent"):
        self.user = user
        self.issues: dict = {}
        self.labels: dict = {}
        self.prs: dict = {}
        self.checks: dict = {}
        self.files: dict = {}  # path -> text, the default branch
        self.log: list = []
        self._next = 1

    def whoami(self) -> str:
        return self.user

    def get_issue(self, number: int) -> Issue:
        if number not in self.issues:
            raise TrackerError(f"issue #{number} not found")
        src = self.issues[number]
        return dataclasses.replace(src, labels=list(src.labels), comments=list(src.comments))

    def list_issues(self, labels: Optional[list] = None, state: str = "open") -> list:
        out = []
        for i in self.issues.values():
            if state != "all" and i.state != state:
                continue
            if labels and not all(lb in i.labels for lb in labels):
                continue
            out.append(self.get_issue(i.number))
        return out

    def create_issue(self, title: str, body: str, labels: list) -> Issue:
        n = self._next
        self._next += 1
        self.issues[n] = Issue(n, title, body, list(labels), "open", self.user, f"https://fake/issues/{n}")
        self.log.append(("create", n, tuple(labels)))
        return self.get_issue(n)

    def set_body(self, number: int, body: str) -> None:
        self.issues[number].body = body
        self.log.append(("body", number))

    def add_labels(self, number: int, labels: list) -> None:
        for lb in labels:
            if lb not in self.issues[number].labels:
                self.issues[number].labels.append(lb)
        self.log.append(("add", number, tuple(labels)))

    def remove_labels(self, number: int, labels: list) -> None:
        self.issues[number].labels = [lb for lb in self.issues[number].labels if lb not in labels]
        self.log.append(("remove", number, tuple(labels)))

    def comment(self, number: int, body: str) -> None:
        self.issues[number].comments.append(Comment(self.user, body, utcnow()))
        self.log.append(("comment", number))

    def close_issue(self, number: int) -> None:
        self.issues[number].state = "closed"
        self.log.append(("close", number))

    def ensure_label(self, name: str, color: str, description: str) -> str:
        verb = "updated" if name in self.labels else "created"
        self.labels[name] = (color, description)
        return verb

    def list_labels(self) -> list:
        return sorted(self.labels)

    def pr(self, ref: str) -> Optional[PR]:
        for p in self.prs.values():
            if ref in (p.url, str(p.number)):
                return p
        return None

    def pr_checks(self, sha: str) -> list:
        return list(self.checks.get(sha, []))

    def committed_file(self, path: str) -> Optional[tuple]:
        if path not in self.files:
            return None
        data = self.files[path].encode("utf-8")
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(), self.files[path]  # git's blob id


class GitHubBackend(Backend):
    """Shells to gh so its auth is reused; one method per gh call."""

    name = "github"

    def __init__(self, repo: Optional[str] = None):
        self.repo = repo or os.environ.get("KZ_TRACKER_REPO") or os.environ.get("GITHUB_REPOSITORY") or None
        self._login: Optional[str] = None

    def _run(self, args: list, input_text: Optional[str] = None) -> str:
        try:
            r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_text, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TrackerError(f"gh {' '.join(args[:2])}: {exc}") from exc
        if r.returncode != 0:
            raise TrackerError(f"gh {' '.join(args[:2])} failed: {r.stderr.strip()[:400]}")
        return r.stdout

    def _repo_args(self) -> list:
        return ["-R", self.repo] if self.repo else []

    def repo_full(self) -> str:
        if not self.repo:
            self.repo = self._run(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).strip()
        return self.repo

    def whoami(self) -> str:
        if self._login is None:
            self._login = self._run(["api", "user", "--jq", ".login"]).strip()
        return self._login

    @staticmethod
    def _issue(d: dict) -> Issue:
        return Issue(
            number=int(d["number"]),
            title=d.get("title", ""),
            body=d.get("body") or "",
            labels=[lb["name"] for lb in d.get("labels", [])],
            state=str(d.get("state", "")).lower(),
            author=(d.get("author") or {}).get("login", ""),
            url=d.get("url", ""),
            comments=[
                Comment((c.get("author") or {}).get("login", ""), c.get("body", ""), c.get("createdAt", ""))
                for c in d.get("comments", [])
            ],
        )

    def get_issue(self, number: int) -> Issue:
        fields = "number,title,body,labels,state,author,url,comments"
        return self._issue(json.loads(self._run(["issue", "view", str(number), *self._repo_args(), "--json", fields])))

    def list_issues(self, labels: Optional[list] = None, state: str = "open") -> list:
        args = ["issue", "list", *self._repo_args(), "--state", state, "--limit", "200",
                "--json", "number,title,labels,state,url"]
        for lb in labels or []:
            args += ["--label", lb]
        return [self._issue(d) for d in json.loads(self._run(args))]

    def create_issue(self, title: str, body: str, labels: list) -> Issue:
        args = ["issue", "create", *self._repo_args(), "--title", title, "--body-file", "-"]
        for lb in labels:
            args += ["--label", lb]
        url = self._run(args, input_text=body).strip().splitlines()[-1]
        return self.get_issue(int(url.rstrip("/").rsplit("/", 1)[1]))

    def set_body(self, number: int, body: str) -> None:
        self._run(["issue", "edit", str(number), *self._repo_args(), "--body-file", "-"], input_text=body)

    def add_labels(self, number: int, labels: list) -> None:
        self._run(["issue", "edit", str(number), *self._repo_args(), "--add-label", ",".join(labels)])

    def remove_labels(self, number: int, labels: list) -> None:
        self._run(["issue", "edit", str(number), *self._repo_args(), "--remove-label", ",".join(labels)])

    def comment(self, number: int, body: str) -> None:
        self._run(["issue", "comment", str(number), *self._repo_args(), "--body-file", "-"], input_text=body)

    def close_issue(self, number: int) -> None:
        self._run(["issue", "close", str(number), *self._repo_args()])

    def ensure_label(self, name: str, color: str, description: str) -> str:
        existed = name in self.list_labels()
        args = ["label", "create", name, *self._repo_args(), "--color", color, "--description", description, "--force"]
        self._run(args)
        return "updated" if existed else "created"

    def list_labels(self) -> list:
        out = json.loads(self._run(["label", "list", *self._repo_args(), "--limit", "200", "--json", "name"]))
        return sorted(d["name"] for d in out)

    def pr(self, ref: str) -> Optional[PR]:
        fields = "number,url,title,body,headRefName,baseRefName,state,mergedAt,mergedBy,mergeCommit,files"
        repo = self._repo_args() if ref.isdigit() else []
        try:
            d = json.loads(self._run(["pr", "view", ref, *repo, "--json", fields]))
        except TrackerError as exc:
            if "no pull requests found" in str(exc).lower() or "could not resolve" in str(exc).lower():
                return None
            raise
        return PR(
            number=int(d["number"]), url=d.get("url", ""), title=d.get("title", ""), body=d.get("body") or "",
            head=d.get("headRefName", ""), base=d.get("baseRefName", ""), state=str(d.get("state", "")).lower(),
            merged=bool(d.get("mergedAt")), merged_by=(d.get("mergedBy") or {}).get("login", ""),
            merge_sha=(d.get("mergeCommit") or {}).get("oid", ""), files=[f["path"] for f in d.get("files", [])],
        )

    def pr_checks(self, sha: str) -> list:
        jq = r'.check_runs[] | [.name, .status, (.conclusion // ""), .html_url] | @tsv'
        out = self._run(["api", f"repos/{self.repo_full()}/commits/{sha}/check-runs", "--paginate", "--jq", jq])
        checks = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                checks.append(Check(*parts))
        return checks

    def committed_file(self, path: str) -> Optional[tuple]:
        """The contents API without a ref reads the default branch; only an HTTP 404 means the file is not there."""
        api = f"repos/{self.repo_full()}/contents/{path}"
        try:
            raw = self._run(["api", api])
        except TrackerError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        try:
            d = json.loads(raw)
            return d["sha"], base64.b64decode(d["content"]).decode("utf-8")
        except (KeyError, TypeError, ValueError) as exc:  # binascii.Error and UnicodeDecodeError are ValueErrors
            raise TrackerError(f"gh api {api}: no file content in the answer ({exc})") from exc


_REMOTE_HOST_RE = re.compile(r"^(?:[A-Za-z][\w+.-]*://)?(?:[^@/]+@)?([^/:]+)")


def is_ado_remote(url: str) -> bool:
    """dev.azure.com, ssh.dev.azure.com or *.visualstudio.com, in https or scp-like ssh form."""
    m = _REMOTE_HOST_RE.match(url or "")
    host = m.group(1).lower() if m else ""
    return host in ("dev.azure.com", "ssh.dev.azure.com") or host.endswith(".visualstudio.com")


def origin_url(cwd: Optional[str] = None) -> str:
    """`git remote get-url origin`, or "" outside a checkout."""
    try:
        r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def backend_for(repo: Optional[str] = None) -> Backend:
    """The forge backend: env KZ_TRACKER_BACKEND=github|ado, else the origin host, else GitHub."""
    choice = os.environ.get("KZ_TRACKER_BACKEND", "").strip().lower()
    if not choice:
        choice = "ado" if is_ado_remote(origin_url()) else "github"
    if choice == "github":
        return GitHubBackend(repo)
    if choice == "ado":
        import ado  # lazy: the GitHub path never loads it

        return ado.AdoBackend(repo)
    raise TrackerError(f"KZ_TRACKER_BACKEND={choice!r}: expected github or ado")


# ----------------------------------------------------------------------------
# Verbs
# ----------------------------------------------------------------------------

STATUS_PREFIX = "status/"
# GitHub's closing keywords, plus every state name Azure Repos honours before `#N` in a PR description
# (its default process states and the kit's own), each also in the `AB#N` form.
_STATE_WORDS = ("new", "active", "resolved", "closed", "removed", "done", "to do", "doing", "approved", "committed",
                "proposed", "in progress", "backlog", "ready", "blocked", "review", "dropped")
_CLOSING_RE = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?|"
                         + "|".join(w.replace(" ", r"\s+") for w in _STATE_WORDS)
                         + r")\s*:?\s+(?:AB)?#\d+", re.IGNORECASE)
_PATHLIKE_RE = re.compile(r"[\w-]+(?:[./:][\w-]+)+")
_INDEX_RE = re.compile(r"0|[1-9][0-9]*")


def free_text_problem(text: str) -> Optional[str]:
    """Why a stripped --word or evidence line cannot go into a mark and its comment; None when it can."""
    if not text:
        return "is empty"
    if len(text.splitlines()) > 1:
        return "has more than one line"
    if len(text) > FREE_TEXT_MAX:
        return f"is longer than {FREE_TEXT_MAX} characters"
    if "-->" in text:
        return "contains `-->`, which would end the HTML comment that carries the mark"
    return None


def evidence_problem(line: Optional[str]) -> Optional[str]:
    """Why an evidence line does not answer its criterion; None when it does."""
    if line is None:
        return "no evidence line"
    bad = free_text_problem(line)
    if bad:
        return "the line " + bad
    if not _PATHLIKE_RE.search(line):
        return "the line names no path or URL"
    return None


def read_evidence(path: str) -> dict:
    """--evidence FILE, JSON {"<item>": {"<criterion>": "<line>"}} -> {item: {criterion: stripped line}}."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise TrackerError(f"--evidence {path} cannot be read as JSON: {exc}") from exc
    shape = TrackerError(f'--evidence {path} is not shaped {{"<item number>": {{"<criterion index>": "<line>"}}}}')
    if not isinstance(data, dict):
        raise shape
    out: dict = {}
    for item, lines in data.items():
        if not _INDEX_RE.fullmatch(item) or not isinstance(lines, dict):
            raise shape
        if not all(_INDEX_RE.fullmatch(k) and isinstance(line, str) for k, line in lines.items()):
            raise shape
        out[int(item)] = {int(k): line.strip() for k, line in lines.items()}
    return out


def delegation_note(d: dict) -> str:
    return (f"Session `{d['session']}` did this on the owner's delegation: `{d['delegation']['file']}` at blob "
            f"`{d['delegation']['blob']}` on the default branch. The owner's words, as the session quotes them: "
            f"\"{d['word']}\"")


def is_human() -> bool:
    """A terminal on both ends, not inside an agent session and not inside a box (the marker exists, even broken)."""
    return (sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("CLAUDECODE")
            and not os.path.lexists(BOX_MARKER))


def seat_of() -> Optional[str]:
    """The box's seat from its marker; None on the host. No environment variable counts (BOX_SEAT included)."""
    if not os.path.lexists(BOX_MARKER):
        return None
    try:
        with open(BOX_MARKER, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise Refused(f"the box marker {BOX_MARKER} cannot be read ({exc}); no claim without a seat") from exc
    seat = data.get("seat") if isinstance(data, dict) else None
    if not isinstance(seat, str) or not _SEAT_RE.fullmatch(seat):
        raise Refused(f"the box marker {BOX_MARKER} has no plain-token `seat`; no claim without a seat")
    return seat


def read_line() -> str:
    """One line from stdin; EOF raises EOFError."""
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\r\n")


class Tracker:
    def __init__(self, backend: Backend, actor: str, out=None, cwd: Optional[str] = None, ask=None):
        self.b = backend
        self.actor = actor
        self.out = out or sys.stdout
        self.cwd = cwd or os.getcwd()
        self.ask = ask or read_line

    def say(self, text: str) -> None:
        self.out.write(text + "\n")

    # -- shared steps ---------------------------------------------------------

    def set_status(self, issue: Issue, new: str) -> None:
        """Add the new status first, then remove the siblings: a crash leaves two labels, never none."""
        self.b.add_labels(issue.number, [STATUS_PREFIX + new])
        siblings = [lb for lb in issue.labels if lb.startswith(STATUS_PREFIX) and lb != STATUS_PREFIX + new]
        if siblings:
            self.b.remove_labels(issue.number, siblings)

    def _git(self, *args: str) -> str:
        try:
            r = subprocess.run(["git", *args], cwd=self.cwd, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""

    # -- read verbs -----------------------------------------------------------

    def list(self, status: Optional[str] = None, type_: Optional[str] = None, all_: bool = False) -> int:
        labels = []
        if status:
            labels.append(STATUS_PREFIX + status)
        if type_:
            labels.append("type/" + type_)
        issues = self.b.list_issues(labels or None, state="all" if all_ else "open")
        for i in sorted(issues, key=lambda x: x.number):
            st = next((lb[7:] for lb in i.labels if lb.startswith(STATUS_PREFIX)), "-")
            ty = type_of(i) or "-"
            self.say(f"#{i.number:<5} {st:<12} {ty:<11} {i.title}")
        if not issues:
            self.say("(no issues)")
        return 0

    def show(self, number: int) -> int:
        i = self.b.get_issue(number)
        self.say(f"#{i.number} {i.title}  [{i.state}]  {i.url}")
        self.say("labels: " + ", ".join(i.labels))
        ac = parse_ac(i.body)
        if ac:
            self.say("acceptance criteria:")
            for k, (checked, text) in enumerate(ac, 1):
                self.say(f"  {k}. [{'x' if checked else ' '}] {text}")
        missing = definition_of_ready(i.body)
        if missing:
            self.say("definition of ready, missing: " + "; ".join(missing))
        for m in marks(i):
            extra = {k: v for k, v in m.items() if k not in ("kind", "_author")}
            self.say(f"  {m['kind']:<7} by {m['_author']}: {json.dumps(extra, sort_keys=True)}")
        return 0

    # -- agent verbs ----------------------------------------------------------

    def new(self, title: str, ac: list, scope: str, scope_limit: str, source: str, type_: str = "todo") -> int:
        if type_ not in TYPES:
            raise Refused(f"type must be one of {', '.join(TYPES)}")
        body = compose_body(ac, scope, scope_limit, source)
        missing = definition_of_ready(body)
        if missing:
            raise Refused("an agent-created issue must already satisfy the definition of ready; missing: "
                          + "; ".join(missing))
        check_transition(None, "backlog", self.actor)
        issue = self.b.create_issue(title, body, ["type/" + type_, STATUS_PREFIX + "backlog"])
        self.say(f"created #{issue.number} in status/backlog: {issue.url}")
        self.say("a human promotes it with: tracker owner ready " + str(issue.number))
        return 0

    def claim(self, number: int, branch: Optional[str] = None) -> int:
        issue = self.b.get_issue(number)
        status = status_of(issue)
        if status != "ready":
            raise Refused(f"#{number} is not ready (status/{status}); "
                          f"a human promotes it with `tracker owner ready {number}`")
        check_transition(status, "in-progress", self.actor)
        me = self.b.whoami()
        seat = seat_of()
        for listed in self.b.list_issues([STATUS_PREFIX + "in-progress"]):
            other = self.b.get_issue(listed.number)  # listings carry no or partial comments; few items, one GET each
            claims = marks(other, "claim")
            if claims and claims[-1].get("by") == me and claims[-1].get("seat") == seat:
                raise Refused(f"{me} ({'seat ' + seat if seat else 'host'}) already has #{other.number} in progress; "
                              f"finish it (`tracker review`) or block it (`tracker block`) first")
        branch = branch or self._git("branch", "--show-current") or "(no branch)"
        worktree = self._git("rev-parse", "--show-toplevel") or self.cwd
        ts = utcnow()
        body = mark("claim", by=me, seat=seat, branch=branch, worktree=worktree, ts=ts) + (
            f"\nClaimed by {me}{f' (seat `{seat}`)' if seat else ''} at {ts} on branch `{branch}` "
            f"(worktree `{worktree}`)."
        )
        self.b.comment(number, body)
        self.set_status(issue, "in-progress")
        self.say(f"#{number} claimed: status/in-progress, branch {branch}")
        return 0

    def block(self, number: int, question: str) -> int:
        issue = self.b.get_issue(number)
        status = status_of(issue)
        check_transition(status, "blocked", self.actor)
        if not _PATHLIKE_RE.search(question or ""):
            raise Refused("the question must name the path or field it is about (e.g. `src/app.py`, `config.timeout`)")
        me = self.b.whoami()
        self.b.comment(number, mark("block", by=me, ts=utcnow()) + f"\n**Blocked, question for a human:** {question}")
        self.set_status(issue, "blocked")
        self.say(f"#{number} blocked; a human answers and runs `tracker owner ready {number}`")
        return 0

    def review(self, number: int, pr_ref: str) -> int:
        issue = self.b.get_issue(number)
        status = status_of(issue)
        check_transition(status, "review", self.actor)
        claims = marks(issue, "claim")
        if not claims:
            raise Refused(f"#{number} has no claim comment; `tracker claim {number}` first")
        pr = self.b.pr(pr_ref)
        if pr is None:
            raise Refused(f"no pull request found for {pr_ref}")
        if pr.state == "closed" and not pr.merged:
            raise Refused(f"PR #{pr.number} is closed without merging")
        branch = claims[-1].get("branch")
        if pr.head != branch:
            raise Refused(f"PR head is `{pr.head}` but #{number} was claimed on `{branch}`")
        kw = _CLOSING_RE.search(pr.body)
        if kw:
            raise Refused(f"PR body contains the closing keyword `{kw.group(0)}`; use `Refs #{number}` only")
        if not re.search(rf"\bRefs #{number}\b", pr.body):
            raise Refused(f"PR body must contain `Refs #{number}` (closing is the owner's protocol, not GitHub's)")
        me = self.b.whoami()
        self.b.comment(number, mark("review", by=me, pr=pr.url, head=pr.head, ts=utcnow()) + f"\nIn review: {pr.url}")
        self.set_status(issue, "review")
        self.say(f"#{number} in review: {pr.url}")
        return 0

    def note(self, number: int, text: str) -> int:
        issue = self.b.get_issue(number)
        status_of(issue)  # a broken label set is reported, even for a note
        me = self.b.whoami()
        self.b.comment(number, mark("note", by=me, ts=utcnow()) + "\n" + text.strip())
        self.say(f"#{number}: note posted")
        return 0

    # -- owner verbs ----------------------------------------------------------

    def _owner_only(self) -> None:
        if self.actor != HUMAN:
            raise Refused("owner verbs need a human at a terminal outside a box (no TTY here, or a box marker); "
                          "ask the owner to run it")

    def labels_sync(self) -> int:
        self._owner_only()
        counts = {"created": 0, "updated": 0}
        for name, (color, desc) in LABELS.items():
            counts[self.b.ensure_label(name, color, desc)] += 1
        self.say(f"labels: {counts['created']} created, {counts['updated']} updated, 0 deleted (never)")
        return 0

    def _check_all(self, verb: str, numbers: list, check) -> list:
        """Check phase: read every item, write nothing; refuse naming each failing item. [(issue, facts)]."""
        twice = sorted({n for n in numbers if numbers.count(n) > 1})
        if twice:
            raise Refused(f"{', '.join(f'#{n}' for n in twice)} given twice; give each number once")
        items, failing = [], []
        for n in numbers:
            issue = self.b.get_issue(n)
            try:
                problems, facts = check(issue)
            except Refused as exc:
                problems, facts = [str(exc)], {}
            if problems:
                failing.append(f"#{n}: " + "; ".join(problems))
            items.append((issue, facts))
        if failing:
            raise Refused(f"`{verb}`: {len(failing)} of {len(items)} items fail; nothing changed:\n  "
                          + "\n  ".join(failing))
        return items

    def _write_all(self, items: list, write) -> None:
        """Write phase, per item in order; a forge error stops it and names what was written and what not."""
        written = []
        for k, (issue, facts) in enumerate(items):
            try:
                write(issue, facts)
            except TrackerError as exc:
                rest = [f"#{i.number}" for i, _ in items[k + 1 :]]
                raise TrackerError(f"#{issue.number}: {exc}; stopped there (#{issue.number} may be partly written); "
                                   f"written: {', '.join(f'#{n}' for n in written) or 'none'}; "
                                   f"not touched: {', '.join(rest) or 'none'}") from exc
            written.append(issue.number)

    def _ready_problems(self, issue: Issue, actor: Optional[str] = None) -> tuple:
        check_transition(status_of(issue), "ready", actor or self.actor)
        return ["definition of ready not met, missing " + m for m in definition_of_ready(issue.body)], {}

    def _write_ready(self, issue: Issue, facts: dict, delegated: Optional[dict] = None) -> None:
        number = issue.number
        me = self.b.whoami()
        sha = body_hash(issue.body)
        frozen = f"\nReady. Body frozen at sha256 {sha}; edits after this point fail `owner done`"
        text = f"{frozen} and `delegate done`.\n{delegation_note(delegated)}" if delegated else f"{frozen}."
        self.b.comment(number, mark("ready", by=me, body_sha256=sha, ts=utcnow(), **(delegated or {})) + text)
        self.set_status(issue, "ready")
        self.say(f"#{number} ready (body {sha})")

    def ready(self, numbers: list) -> int:
        self._owner_only()
        self._write_all(self._check_all("owner ready", numbers, self._ready_problems), self._write_ready)
        return 0

    def done_checks(self, issue: Issue, waived: dict, accept: bool = False) -> tuple:
        """Read-only part of the closing protocol: (problems, facts)."""
        problems, facts = [], {}
        status = status_of(issue)
        if status != "review":
            problems.append(f"status/{status} is not review")
        readies = marks(issue, "ready")
        if not readies:
            problems.append("no `owner ready` record")
        else:
            frozen = readies[-1].get("body_sha256")
            now = body_hash(issue.body)
            if frozen != now:
                problems.append(f"body changed since ready (frozen {frozen}, now {now}); re-run `owner ready` or drop")
        if not marks(issue, "claim"):
            problems.append("no claim record")
        reviews = marks(issue, "review")
        pr = self.b.pr(reviews[-1]["pr"]) if reviews and reviews[-1].get("pr") else None
        if pr is None:
            problems.append("no review record with a pull request")
        else:
            facts["pr"] = pr.url
            opts = pr.completion_options or {}
            if opts.get("transitionWorkItems"):
                problems.append(f"PR #{pr.number} was completed with `transitionWorkItems`: the forge may have moved "
                                "the linked work items, and the tracker is the only state writer (check the history)")
            if opts.get("bypassPolicy"):
                problems.append(f"PR #{pr.number} was completed with `bypassPolicy` "
                                f"({opts.get('bypassReason') or 'no reason given'}): branch policies did not hold")
            if not re.search(rf"\bRefs #{issue.number}\b", pr.body):
                problems.append(f"PR body lacks `Refs #{issue.number}`")
            if not pr.merged:
                problems.append(f"PR #{pr.number} is not merged")
            else:
                facts["merge_sha"] = pr.merge_sha
                if not pr.merged_by or pr.merged_by.endswith("[bot]") or pr.merged_by in bot_logins():
                    problems.append(f"PR merged by `{pr.merged_by or '?'}`, not a human")
                facts["merged_by"] = pr.merged_by
                checks = self.b.pr_checks(pr.merge_sha) if pr.merge_sha else []
                if not checks:
                    problems.append(f"no checks found on merge commit {pr.merge_sha[:10] or '?'}")
                bad = [c for c in checks if c.conclusion not in ("success", "skipped")]
                for c in bad:
                    problems.append(f"check `{c.name}` is {c.conclusion or c.status} ({c.url})")
                facts["checks"] = [{"name": c.name, "conclusion": c.conclusion, "url": c.url} for c in checks]
                facts["decisions_md"] = "DECISIONS.md" in pr.files
        for k, (checked, text) in enumerate(parse_ac(issue.body), 1):
            if checked:
                continue
            if k in waived or accept:  # --accept-all: the one confirmation accepts it
                continue
            problems.append(f"acceptance criterion {k} unchecked: {text} "
                            f"(tick it in the UI or `--waive {k} \"reason\"`)")
        facts["waived"] = waived
        return problems, facts

    def done(self, numbers: list, waive: Optional[list] = None, accept_all: bool = False) -> int:
        self._owner_only()
        if accept_all and waive:
            raise Refused("--accept-all and --waive exclude each other; accept every criterion or waive some")
        if waive and len(numbers) > 1:
            raise Refused("--waive takes one item (its indexes are per item); give one number with it")
        waived = {}
        for idx, reason in waive or []:
            waived[int(idx)] = reason

        def check(issue: Issue) -> tuple:
            check_transition(status_of(issue), "done", self.actor)
            return self.done_checks(issue, waived, accept_all)

        items = self._check_all("owner done", numbers, check)
        if not accept_all:
            self._write_all(items, self._write_done)
            return 0
        for issue, facts in items:
            self.say(f"#{issue.number} {issue.title}")
            for k, (checked, text) in enumerate(parse_ac(issue.body), 1):
                self.say(f"  {k}. [{'x' if checked else ' '}] {text}")
            self.say(f"  pull request: {facts['pr']}")
            self.say(f"  merge commit: {facts['merge_sha']}, merged by {facts['merged_by']}")
            for c in facts["checks"]:
                self.say(f"  {c['name']}: {c['conclusion']}")
        count = len(items)
        seen = {issue.number: body_hash(issue.body) for issue, _ in items}  # the bodies the owner is shown
        self.out.write(f'Type "accept {count}" to accept every criterion of these {count} items: ')
        self.out.flush()
        try:
            answer = self.ask()
        except EOFError:
            answer = None
        if answer != f"accept {count}":
            self.say("not confirmed; nothing changed")
            return 2
        accepted = (f"Acceptance criteria accepted by {self.b.whoami()} in one confirmation for {count} items "
                    f"({', '.join(f'#{i.number}' for i, _ in items)}).")
        self._write_all(items, lambda issue, facts: self._write_done(issue, facts, accepted, seen[issue.number]))
        return 0

    def _write_done(self, issue: Issue, facts: dict, accepted: str = "", seen: str = "") -> None:
        number, waived = issue.number, facts["waived"]
        if accepted:
            # The prompt may have waited: read the body again, and never write over an edit made meanwhile.
            body = self.b.get_issue(number).body
            if body_hash(body) != seen:
                raise TrackerError(f"body changed since the check (shown {seen}, now {body_hash(body)}); "
                                   "nothing written for it, run the verb again")
            ticked = [k for k, (checked, _) in enumerate(parse_ac(body), 1) if not checked]
            new = _AC_RE.sub(lambda m: m.group(0).replace("[ ]", "[x]", 1) if m.group(1) == " " else m.group(0),
                             body)
            if new != body:
                self.b.set_body(number, new)
            facts = {**facts, "criteria": "accepted-all", "ticked": ticked}
            if ticked:
                word = "criterion" if len(ticked) == 1 else "criteria"
                accepted += f"\nTicked by this confirmation: {word} {', '.join(map(str, ticked))}."
        me = self.b.whoami()
        lines = [mark("done", by=me, ts=utcnow(), **{k: v for k, v in facts.items() if k != "checks"}),
                 f"Done by {me}. PR {facts['pr']} merged as {facts['merge_sha']} by {facts['merged_by']}.",
                 "Checks on the merge commit:"]
        lines += [f"- {c['name']}: {c['conclusion']} ({c['url']})" for c in facts["checks"]]
        if facts.get("decisions_md"):
            lines.append("DECISIONS.md changed in this PR (decision record linked by the merge SHA).")
        for k, reason in sorted(waived.items()):
            lines.append(f"Waived acceptance criterion {k}: {reason}")
        if accepted:
            lines.append(accepted)
        if facts.get("delegated"):
            lines += [delegation_note(facts), "Evidence per acceptance criterion; no box was ticked by this verb:"]
            for k, (_, text) in enumerate(parse_ac(issue.body), 1):
                lines.append(f"{k}. {text}: {facts['evidence'][str(k)]}")
        self.b.comment(number, "\n".join(lines))
        self.set_status(issue, "done")
        self.b.close_issue(number)
        self.say(f"#{number} done and closed ({facts['merge_sha'][:10]})")

    # -- delegated owner verbs (#103) -------------------------------------------

    def _delegation(self, word: str) -> dict:
        """The delegation check, before any issue is read: the fields the marks of the delegated verbs carry."""
        if os.path.lexists(BOX_MARKER):
            raise Refused(f"a box never promotes or closes an item (the box marker {BOX_MARKER} exists)")
        boundary = os.environ.get("KZ_BOUNDARY")
        if boundary is not None and boundary.strip() != "own":
            raise Refused(f"KZ_BOUNDARY is {boundary!r}; the delegated verbs run only where the boundary is own")
        session = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
        if not session:
            raise Refused("CLAUDE_CODE_SESSION_ID is empty: the delegated verbs are a session's; "
                          "at a terminal the owner runs `tracker owner ...`")
        word = (word or "").strip()
        bad = free_text_problem(word)
        if bad:
            raise Refused(f"--word {bad}; give the owner's words as one line of at most {FREE_TEXT_MAX} characters")
        found = self.b.committed_file(DELEGATION_FILE)
        off = f"the owner has not delegated the owner verbs: {DELEGATION_FILE} on the default branch "
        if found is None:
            raise Refused(off + "does not exist")
        blob, text = found
        try:
            cfg = json.loads(text)
        except ValueError:
            cfg = None
        if not isinstance(cfg, dict):
            raise Refused(off + "is not a JSON object")
        for key, want in (("boundary", "own"), ("owner_verbs", "delegated")):
            if cfg.get(key) != want:
                raise Refused(off + f"says {key} {cfg.get(key)!r}, not {want!r}")
        return {"delegated": True, "session": session, "word": word,
                "delegation": {"file": DELEGATION_FILE, "blob": blob}}

    def delegate_ready(self, numbers: list, word: str) -> int:
        fields = self._delegation(word)
        items = self._check_all("delegate ready", numbers, lambda issue: self._ready_problems(issue, DELEGATE))
        self._write_all(items, lambda issue, facts: self._write_ready(issue, facts, fields))
        return 0

    def delegate_done(self, numbers: list, word: str, evidence_file: str) -> int:
        fields = self._delegation(word)
        evidence = read_evidence(evidence_file)
        stray = sorted(set(evidence) - set(numbers))
        if stray:
            raise Refused(f"{evidence_file} has evidence for {', '.join(f'#{n}' for n in stray)}, which is not "
                          "given; nothing changed")

        def check(issue: Issue) -> tuple:
            check_transition(status_of(issue), "done", DELEGATE)
            problems, facts = self.done_checks(issue, {}, accept=True)  # unticked boxes: the evidence answers them
            lines, criteria = evidence.get(issue.number, {}), parse_ac(issue.body)
            for k, (_, text) in enumerate(criteria, 1):
                bad = evidence_problem(lines.get(k))
                if bad:
                    problems.append(f"acceptance criterion {k} ({text}): {bad}")
            problems += [f"evidence for criterion {k}, which #{issue.number} does not have ({len(criteria)} criteria)"
                         for k in sorted(lines) if not 1 <= k <= len(criteria)]
            return problems, {**facts, **fields, "criteria": "evidence",
                              "evidence": {str(k): line for k, line in sorted(lines.items())}}

        self._write_all(self._check_all("delegate done", numbers, check), self._write_done)
        return 0


def bot_logins() -> set:
    return {s.strip() for s in os.environ.get("KZ_TRACKER_BOTS", "").split(",") if s.strip()}


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tracker", add_help=False)
    p.add_argument("--repo", help="OWNER/NAME on GitHub, ORG/PROJECT/REPO on Azure DevOps")
    sub = p.add_subparsers(dest="verb")
    sub.add_parser("help")
    sub.add_parser("version")
    s = sub.add_parser("list")
    s.add_argument("--status", choices=STATUSES)
    s.add_argument("--type", dest="type_", choices=TYPES)
    s.add_argument("--all", dest="all_", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("number", type=int)
    s = sub.add_parser("new")
    s.add_argument("--title", required=True)
    s.add_argument("--ac", action="append", default=[], help="acceptance criterion; repeatable")
    s.add_argument("--scope", required=True)
    s.add_argument("--scope-limit", required=True)
    s.add_argument("--source", required=True)
    s.add_argument("--type", dest="type_", default="todo", choices=TYPES)
    s = sub.add_parser("claim")
    s.add_argument("number", type=int)
    s.add_argument("--branch")
    s = sub.add_parser("block")
    s.add_argument("number", type=int)
    s.add_argument("--question", required=True)
    s = sub.add_parser("review")
    s.add_argument("number", type=int)
    s.add_argument("--pr", required=True)
    s = sub.add_parser("note")
    s.add_argument("number", type=int)
    s.add_argument("text")
    o = sub.add_parser("owner")
    osub = o.add_subparsers(dest="owner_verb")
    osub.add_parser("labels-sync")
    s = osub.add_parser("ready")
    s.add_argument("numbers", type=int, nargs="+")
    s = osub.add_parser("done")
    s.add_argument("numbers", type=int, nargs="+")
    s.add_argument("--waive", nargs=2, action="append", metavar=("INDEX", "REASON"), default=[])
    s.add_argument("--accept-all", action="store_true")
    d = sub.add_parser("delegate")
    dsub = d.add_subparsers(dest="delegate_verb")
    s = dsub.add_parser("ready")
    s.add_argument("numbers", type=int, nargs="+")
    s.add_argument("--word", required=True)
    s = dsub.add_parser("done")
    s.add_argument("numbers", type=int, nargs="+")
    s.add_argument("--word", required=True)
    s.add_argument("--evidence", required=True)
    return p


def main(argv: list, backend: Optional[Backend] = None, human: Optional[bool] = None, out=None,
         cwd: Optional[str] = None, ask=None) -> int:
    out = out or sys.stdout
    parser = build_parser()
    if not argv or argv[0] in ("help", "-h", "--help"):
        out.write(__doc__.strip() + "\n")
        return 0
    try:
        ns = parser.parse_args(argv)
    except SystemExit:
        return 1
    if ns.verb == "version":
        out.write(VERSION + "\n")
        return 0
    if (ns.verb is None or (ns.verb == "owner" and ns.owner_verb is None)
            or (ns.verb == "delegate" and ns.delegate_verb is None)):
        out.write(__doc__.strip() + "\n")
        return 1
    actor = HUMAN if (is_human() if human is None else human) else AGENT
    try:
        t = Tracker(backend or backend_for(ns.repo), actor, out, cwd, ask)
        if ns.verb == "list":
            return t.list(ns.status, ns.type_, ns.all_)
        if ns.verb == "show":
            return t.show(ns.number)
        if ns.verb == "new":
            return t.new(ns.title, ns.ac, ns.scope, ns.scope_limit, ns.source, ns.type_)
        if ns.verb == "claim":
            return t.claim(ns.number, ns.branch)
        if ns.verb == "block":
            return t.block(ns.number, ns.question)
        if ns.verb == "review":
            return t.review(ns.number, ns.pr)
        if ns.verb == "note":
            return t.note(ns.number, ns.text)
        if ns.verb == "owner":
            if ns.owner_verb == "labels-sync":
                return t.labels_sync()
            if ns.owner_verb == "ready":
                return t.ready(ns.numbers)
            if ns.owner_verb == "done":
                return t.done(ns.numbers, ns.waive, ns.accept_all)
        if ns.verb == "delegate":
            if ns.delegate_verb == "ready":
                return t.delegate_ready(ns.numbers, ns.word)
            if ns.delegate_verb == "done":
                return t.delegate_done(ns.numbers, ns.word, ns.evidence)
    except Refused as exc:
        out.write(f"tracker: refused: {exc}\n")
        return 2
    except TrackerError as exc:
        out.write(f"tracker: error: {exc}\n")
        return 1
    out.write(__doc__.strip() + "\n")
    return 1


if __name__ == "__main__":
    sys.modules.setdefault("tracker", sys.modules[__name__])  # `import tracker` in ado.py gets this module
    sys.exit(main(sys.argv[1:]))
