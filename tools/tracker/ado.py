"""ado — the tracker's Azure DevOps backend: Boards work items, Repos PRs, Pipelines builds (plan A2).

Standard library only, Python >= 3.9; REST api-version 7.1 over urllib. `tracker.backend_for()` loads
it when the origin is on Azure DevOps or KZ_TRACKER_BACKEND=ado. An issue is a work item.

Repository  --repo ORG/PROJECT/REPO, else KZ_TRACKER_REPO, else the pipeline variables
            SYSTEM_COLLECTIONURI + SYSTEM_TEAMPROJECT + BUILD_REPOSITORY_NAME, else the origin URL
Token       SYSTEM_ACCESSTOKEN (pipelines), else `az account get-access-token` (Entra, about 1 h).
            No PAT code path; the token never appears in an error message
Scope       work items of type KZ_TRACKER_ADO_TYPE (default Task; Change in process mode) under the area
            path KZ_TRACKER_AREA (default: the project); anything outside is refused, never written
Identity    IdentityRef.id GUIDs, lowercase: whoami, comment authors, PR closedBy (KZ_TRACKER_BOTS lists GUIDs)
Labels      KZ_TRACKER_ADO_MODE=tags (default): type/* and status/* are System.Tags.
            KZ_TRACKER_ADO_MODE=process: status/* is System.State (STATE_OF), type/* is Custom.ChangeType,
            so the server holds exactly one status; removing a status is a no-op. Other labels stay tags.
            Every write is a JSON Patch led by `test /rev`
Text        Descriptions are created in Markdown mode; HTML items are refused. Markers are Markdown comments
"""
import http.client
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

import tracker

ADO_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"  # the Azure DevOps application id in Entra
API = "7.1"
COMMENTS_API = "7.1-preview.4"
TAGS_API = "7.1-preview.1"
CONNECTION_API = "7.1-preview"
TIMEOUT = 30
PATCH_TYPE = "application/json-patch+json"
BATCH = 200  # workitemsbatch limit
BUILD_PAGES = 5  # pr_checks searches the 1000 most recent builds of the project for the SHA
CLOSED_CATEGORIES = ("Completed", "Removed")
MODES = ("tags", "process")
TYPE_FIELD = "Custom.ChangeType"
STATE_OF = {"backlog": "Backlog", "ready": "Ready", "in-progress": "In Progress", "blocked": "Blocked",
            "review": "Review", "done": "Done", "dropped": "Removed"}  # process mode: status -> System.State
STATUS_OF = {state: status for status, state in STATE_OF.items()}
_PR_URL_RE = re.compile(r"/([^/]+)/_git/([^/?#]+)/pullrequest/(\d+)", re.IGNORECASE)
_REMOTES = (
    re.compile(r"^https://(?:[^@/]+@)?dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/(?P<repo>[^/?#]+)"),
    re.compile(r"^(?:ssh://)?git@ssh\.dev\.azure\.com[:/]v3/(?P<org>[^/]+)/(?P<project>[^/]+)/(?P<repo>[^/?#]+)"),
    re.compile(r"^https://(?:[^@/]+@)?(?P<org>[^./@]+)\.visualstudio\.com/(?:DefaultCollection/)?"
               r"(?P<project>[^/]+)/_git/(?P<repo>[^/?#]+)"),
)


class NotFound(tracker.TrackerError):
    """HTTP 404 from Azure DevOps."""


def q(segment: str) -> str:
    return urllib.parse.quote(segment, safe="")


def parse_remote(url: str) -> Optional[tuple]:
    """(org, project, repo), URL-decoded, from an Azure Repos clone URL; None for anything else."""
    for rx in _REMOTES:
        m = rx.match((url or "").strip())
        if m:
            return tuple(urllib.parse.unquote(m.group(k)) for k in ("org", "project", "repo"))
    return None


def resolve(repo: Optional[str]) -> tuple:
    """(collection URL, project, repo) from the argument, the env, the pipeline variables or the origin."""
    spec = repo or os.environ.get("KZ_TRACKER_REPO", "")
    if spec:
        parts = [urllib.parse.unquote(p) for p in spec.strip().strip("/").split("/")]
        if len(parts) != 3 or not all(parts):
            raise tracker.TrackerError(f"Azure DevOps repository {spec!r}: expected org/project/repo")
        return f"https://dev.azure.com/{q(parts[0])}", parts[1], parts[2]
    env = [os.environ.get(k, "") for k in ("SYSTEM_COLLECTIONURI", "SYSTEM_TEAMPROJECT", "BUILD_REPOSITORY_NAME")]
    if all(env):
        return env[0].rstrip("/"), env[1], env[2]
    found = parse_remote(tracker.origin_url())
    if found:
        return f"https://dev.azure.com/{q(found[0])}", found[1], found[2]
    raise tracker.TrackerError("no Azure DevOps repository: pass --repo org/project/repo or set KZ_TRACKER_REPO")


def urllib_transport(method: str, url: str, headers: dict, data: Optional[bytes]) -> tuple:
    """(status, lowercase headers, body bytes). HTTP errors are returned; network errors raise OSError."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read()


def values(data: dict, key: str = "value") -> list:
    """The list inside an ADO `{count, value}` envelope; any other shape is an error, never an empty result."""
    found = data.get(key) if isinstance(data, dict) else None
    if not isinstance(found, list):
        raise tracker.TrackerError(f"Azure DevOps: expected a `{key}` list, got {str(data)[:200]}")
    return found


def ident(ref) -> str:
    return str(ref.get("id") or "").lower() if isinstance(ref, dict) else ""


def split_tags(text: str) -> list:
    return [t.strip() for t in (text or "").split(";") if t.strip()]


def wiql_str(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def status_label(state: str) -> str:
    """status/<x> for a System.State; a state outside STATE_OF keeps its own name (label-lint reports it)."""
    return "status/" + STATUS_OF.get(state, state.lower().replace(" ", "-"))


def strip_ref(ref: Optional[str]) -> str:
    ref = ref or ""
    return ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref


def build_check(b: dict) -> tracker.Check:
    """succeeded -> success; partiallySucceeded, failed, canceled -> failure; not completed -> in_progress."""
    name = (b.get("definition") or {}).get("name") or f"build {b.get('id')}"
    url = ((b.get("_links") or {}).get("web") or {}).get("href", "")
    if b.get("status") != "completed":
        return tracker.Check(name, "in_progress", "", url)
    return tracker.Check(name, "completed", "success" if b.get("result") == "succeeded" else "failure", url)


class AdoBackend(tracker.Backend):
    """Azure DevOps Services over REST; reads are GETs, writes are JSON Patch with `test /rev` first."""

    name = "ado"

    def __init__(self, repo: Optional[str] = None, transport=None, mode: Optional[str] = None):
        self.base, self.project, self.repo = resolve(repo)
        self.mode = (mode or os.environ.get("KZ_TRACKER_ADO_MODE") or "tags").strip().lower()
        if self.mode not in MODES:
            raise tracker.TrackerError(f"KZ_TRACKER_ADO_MODE={self.mode!r}: expected tags or process")
        self.wit = os.environ.get("KZ_TRACKER_ADO_TYPE") or ("Change" if self.mode == "process" else "Task")
        self.area = os.environ.get("KZ_TRACKER_AREA") or self.project
        self.transport = transport or urllib_transport
        self._token: Optional[str] = None
        self._me: Optional[str] = None
        self._states: dict = {}
        self._ensured: set = set()

    # -- transport ------------------------------------------------------------

    def token(self) -> str:
        if self._token is None:
            tok = os.environ.get("SYSTEM_ACCESSTOKEN", "").strip()
            if not tok:
                args = ["az", "account", "get-access-token", "--resource", ADO_RESOURCE,
                        "--query", "accessToken", "-o", "tsv"]
                try:
                    r = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise tracker.TrackerError(f"az account get-access-token: {exc} (install the Azure CLI, "
                                               "`az login`, or set SYSTEM_ACCESSTOKEN in a pipeline)") from exc
                if r.returncode != 0:
                    raise tracker.TrackerError(f"az account get-access-token failed (`az login`?): "
                                               f"{r.stderr.strip()[:300]}")
                tok = r.stdout.strip()
            if not tok:
                raise tracker.TrackerError("no Azure DevOps token: set SYSTEM_ACCESSTOKEN or run `az login`")
            self._token = tok
        return self._token

    def _call(self, method: str, path: str, body=None, api_version: str = API, absolute: bool = False,
              content_type: str = "application/json") -> tuple:
        """(parsed JSON, lowercase headers). `path` is under {collection}/{project}/ unless `absolute`."""
        url = path if absolute else f"{self.base}/{q(self.project)}/{path}"
        url += ("&" if "?" in url else "?") + "api-version=" + api_version
        where = f"Azure DevOps {method} {url.split('?')[0]}"
        headers = {"Authorization": "Bearer " + self.token(), "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type
        try:
            status, rheaders, raw = self.transport(method, url, headers, data)
        except (OSError, http.client.HTTPException) as exc:
            raise tracker.TrackerError(f"{where}: unreachable: {exc}") from exc
        text = raw.decode("utf-8", "replace")
        if status == 404:
            raise NotFound(f"{where}: HTTP 404: {text[:300]}")
        if status in (401, 403):
            raise tracker.TrackerError(f"{where}: HTTP {status}, the token was refused or lacks access "
                                       f"(SYSTEM_ACCESSTOKEN, else `az login`): {text[:300]}")
        if not 200 <= status < 300:
            raise tracker.TrackerError(f"{where}: HTTP {status}: {text[:300]}")
        try:
            return (json.loads(text) if text.strip() else {}), rheaders
        except ValueError:
            raise tracker.TrackerError(f"{where}: HTTP {status} but not JSON (a sign-in page means the token "
                                       f"was refused): {text[:300]}") from None

    def _request(self, method: str, path: str, body=None, api_version: str = API, absolute: bool = False,
                 content_type: str = "application/json"):
        return self._call(method, path, body, api_version, absolute, content_type)[0]

    def _pages(self, path: str, key: str = "value", api_version: str = API, max_pages: int = 100,
               strict: bool = True) -> list:
        """Every page of a list, following `continuationToken` (body) or `x-ms-continuationtoken` (header)."""
        out: list = []
        token = None
        for _ in range(max_pages):
            page = path + (("&" if "?" in path else "?") + "continuationToken=" + q(token) if token else "")
            data, headers = self._call("GET", page, api_version=api_version)
            out += values(data, key)
            nxt = data.get("continuationToken") or headers.get("x-ms-continuationtoken")
            if not nxt or nxt == token:
                return out
            token = nxt
        if strict:
            raise tracker.TrackerError(f"Azure DevOps {path.split('?')[0]}: more than {max_pages} pages")
        return out

    # -- work items -----------------------------------------------------------

    def whoami(self) -> str:
        if self._me is None:
            data = self._request("GET", f"{self.base}/_apis/connectionData", api_version=CONNECTION_API,
                                 absolute=True)
            self._me = ident(data.get("authenticatedUser"))
            if not self._me:
                raise tracker.TrackerError("Azure DevOps connectionData has no authenticatedUser.id")
        return self._me

    def _wit_states(self, wit: Optional[str] = None) -> list:
        wit = wit or self.wit
        if wit not in self._states:
            self._states[wit] = values(self._request("GET", f"_apis/wit/workitemtypes/{q(wit)}/states"))
        return self._states[wit]

    def _item(self, number: int) -> dict:
        """The full work item (no `fields=`, which would drop multilineFieldsFormat), checked for scope and format."""
        try:
            d = self._request("GET", f"_apis/wit/workitems/{int(number)}")
        except NotFound:
            raise tracker.TrackerError(f"work item #{number} not found") from None
        f = d.get("fields") or {}
        area, wit = str(f.get("System.AreaPath", "")), str(f.get("System.WorkItemType", ""))
        if not (area.lower() == self.area.lower() or area.lower().startswith(self.area.lower() + "\\")) \
                or wit.lower() != self.wit.lower():
            raise tracker.TrackerError(f"work item #{number} ({wit} in {area}) is outside the tracker's scope "
                                       f"({self.wit} under {self.area}); set KZ_TRACKER_AREA / KZ_TRACKER_ADO_TYPE")
        fmt = str((d.get("multilineFieldsFormat") or {}).get("System.Description", "")).lower()
        if fmt != "markdown":
            raise tracker.TrackerError(f"work item #{number} keeps its Description as HTML; the tracker needs "
                                       "Markdown: switch the Description to Markdown in the web UI (irreversible) "
                                       "or record the change with `tracker new`")
        return d

    def _split(self, labels: list) -> tuple:
        """(fields, tags) for a write: in process mode status/* and type/* are fields, the rest tags."""
        fields: dict = {}
        tags: list = []
        for lb in labels:
            kind, _, value = lb.partition("/")
            if self.mode == "process" and kind == "status":
                fields["System.State"] = STATE_OF.get(value, value)
            elif self.mode == "process" and kind == "type":
                fields[TYPE_FIELD] = value
            else:
                tags.append(lb)
        return fields, tags

    def _labels(self, f: dict) -> list:
        labels = split_tags(f.get("System.Tags", ""))
        if self.mode == "process":
            labels.append(status_label(f.get("System.State", "")))
            if f.get(TYPE_FIELD):
                labels.append("type/" + f[TYPE_FIELD])
        return labels

    def _issue(self, d: dict, comments: list) -> tracker.Issue:
        f = d.get("fields") or {}
        n = int(d.get("id") or f.get("System.Id"))
        cats = {s.get("name"): s.get("category") for s in self._wit_states(f.get("System.WorkItemType"))}
        return tracker.Issue(
            number=n, title=f.get("System.Title", ""), body=f.get("System.Description") or "",
            labels=self._labels(f), state="closed" if cats.get(f.get("System.State")) in CLOSED_CATEGORIES else "open",
            author=ident(f.get("System.CreatedBy")), url=f"{self.base}/{q(self.project)}/_workitems/edit/{n}",
            comments=comments,
        )

    def _comments(self, number: int) -> list:
        raw = self._pages(f"_apis/wit/workItems/{int(number)}/comments?order=asc&$top=200", key="comments",
                          api_version=COMMENTS_API)
        raw.sort(key=lambda c: int(c.get("id") or 0))  # oldest first, whatever order the pages came in
        return [tracker.Comment(ident(c.get("createdBy")), c.get("text") or "", c.get("createdDate", ""))
                for c in raw if not c.get("isDeleted")]

    def get_issue(self, number: int) -> tracker.Issue:
        return self._issue(self._item(number), self._comments(number))

    def _label_cond(self, label: str) -> str:
        fields, _ = self._split([label])
        if fields:
            field, value = next(iter(fields.items()))
            return f"[{field}] = {wiql_str(value)}"
        return f"[System.Tags] CONTAINS {wiql_str(label)}"

    def list_issues(self, labels: Optional[list] = None, state: str = "open") -> list:
        conds = [f"[System.AreaPath] UNDER {wiql_str(self.area)}", f"[System.WorkItemType] = {wiql_str(self.wit)}"]
        conds += [self._label_cond(lb) for lb in labels or []]
        if state in ("open", "closed"):
            closed = [s["name"] for s in self._wit_states() if s.get("category") in CLOSED_CATEGORIES]
            if closed:
                op = "IN" if state == "closed" else "NOT IN"
                conds.append(f"[System.State] {op} ({', '.join(wiql_str(s) for s in closed)})")
        query = "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(conds) + " ORDER BY [System.Id]"
        ids = [int(w["id"]) for w in values(self._request("POST", "_apis/wit/wiql", {"query": query}), "workItems")]
        fields = ["System.Id", "System.Title", "System.Tags", "System.State", "System.WorkItemType",
                  "System.CreatedBy"] + ([TYPE_FIELD] if self.mode == "process" else [])
        out = []
        for i in range(0, len(ids), BATCH):
            batch = self._request("POST", "_apis/wit/workitemsbatch", {"ids": ids[i : i + BATCH], "fields": fields})
            for d in values(batch):
                issue = self._issue(d, [])
                # re-checked here: WIQL CONTAINS on tags is not documented as an exact-name match
                if state in ("all", issue.state) and all(lb in issue.labels for lb in labels or []):
                    out.append(issue)
        return out

    def _patch(self, number: int, rev: int, fields: dict) -> None:
        ops = [{"op": "test", "path": "/rev", "value": rev}]
        ops += [{"op": "add", "path": f"/fields/{k}", "value": v} for k, v in fields.items()]
        self._request("PATCH", f"_apis/wit/workitems/{int(number)}", ops, content_type=PATCH_TYPE)

    def create_issue(self, title: str, body: str, labels: list) -> tracker.Issue:
        ops = [{"op": "add", "path": "/fields/System.Title", "value": title},
               {"op": "add", "path": "/fields/System.Description", "value": body},
               {"op": "add", "path": "/multilineFieldsFormat/System.Description", "value": "Markdown"},
               {"op": "add", "path": "/fields/System.AreaPath", "value": self.area}]
        fields, tags = self._split(labels)
        if tags:
            fields["System.Tags"] = "; ".join(tags)
        ops += [{"op": "add", "path": f"/fields/{k}", "value": v} for k, v in fields.items()]
        d = self._request("POST", f"_apis/wit/workitems/${q(self.wit)}", ops, content_type=PATCH_TYPE)
        return self.get_issue(int(d["id"]))

    def set_body(self, number: int, body: str) -> None:
        d = self._item(number)
        self._patch(number, d["rev"], {"System.Description": body})

    def _relabel(self, number: int, add: list, remove: list) -> None:
        """Read-modify-write under `test /rev`; tags compare case-insensitively, as on the server. In process
        mode a removed status or type is a no-op: the field is single-valued and the add replaced it."""
        d = self._item(number)
        f = d.get("fields") or {}
        fields, add_tags = self._split(add)
        fields = {k: v for k, v in fields.items() if f.get(k) != v}
        tags = split_tags(f.get("System.Tags", ""))
        drop = {lb.lower() for lb in self._split(remove)[1]}
        new = [t for t in tags if t.lower() not in drop]
        new += [lb for lb in add_tags if lb.lower() not in {t.lower() for t in new}]
        if new != tags:
            fields["System.Tags"] = "; ".join(new)
        if fields:
            self._patch(number, d["rev"], fields)

    def add_labels(self, number: int, labels: list) -> None:
        self._relabel(number, labels, [])

    def remove_labels(self, number: int, labels: list) -> None:
        self._relabel(number, [], labels)

    def comment(self, number: int, body: str) -> None:
        self._request("POST", f"_apis/wit/workItems/{int(number)}/comments?format=markdown", {"text": body},
                      api_version=COMMENTS_API)

    def close_issue(self, number: int) -> None:
        """Move to the type's Completed-category state (no-op when already Completed or Removed)."""
        d = self._item(number)
        f = d.get("fields") or {}
        states = self._wit_states(f.get("System.WorkItemType"))
        if {s.get("name"): s.get("category") for s in states}.get(f.get("System.State")) in CLOSED_CATEGORIES:
            return
        done = next((s["name"] for s in states if s.get("category") == "Completed"), None)
        if done is None:
            raise tracker.TrackerError(f"work item type {f.get('System.WorkItemType')} has no Completed state")
        self._patch(number, d["rev"], {"System.State": done})

    def _tag_names(self) -> list:
        return [t.get("name", "") for t in values(self._request("GET", "_apis/wit/tags", api_version=TAGS_API))]

    def _allowed(self, field: str) -> list:
        """The values the work item type accepts: its states, or a picklist field's allowed values."""
        if field == "System.State":
            return [s.get("name") for s in self._wit_states()]
        d = self._request("GET", f"_apis/wit/workitemtypes/{q(self.wit)}/fields/{q(field)}?$expand=allowedValues")
        return list(d.get("allowedValues") or [])

    def ensure_label(self, name: str, color: str, description: str) -> str:
        """Tags have no colour, description or create call; one exists once a work item uses it.
        So: 'updated' when the project knows the tag, else 'created'; nothing is written.
        Process mode, status/* and type/*: 'updated' when the type has the state or value, else refused."""
        fields, _ = self._split([name])
        if fields:
            field, value = next(iter(fields.items()))
            if value not in self._allowed(field):
                raise tracker.Refused(f"{name}: work item type {self.wit} has no {field} `{value}`; "
                                      "a process admin adds it to the inherited process")
            return "updated"
        known = {t.lower() for t in self._tag_names()}
        self._ensured.add(name)
        return "updated" if name.lower() in known else "created"

    def list_labels(self) -> list:
        """The project's tags plus the names ensured by this process (a tag appears on first use);
        in process mode also the type's states as status/<x> and its change types as type/<x>."""
        names = set(self._tag_names()) | self._ensured
        if self.mode == "process":
            names |= {status_label(s) for s in self._allowed("System.State")}
            names |= {"type/" + v for v in self._allowed(TYPE_FIELD)}
        return sorted(names)

    # -- pull requests and builds ---------------------------------------------

    def pr_url(self, number: int) -> str:
        return f"{self.base}/{q(self.project)}/_git/{q(self.repo)}/pullrequest/{number}"

    def pr(self, ref: str) -> Optional[tracker.PR]:
        """By web URL (this project and repo only) or number; None when there is no such PR."""
        ref = (ref or "").strip()
        m = _PR_URL_RE.search(ref)
        if m:
            project, repo = (urllib.parse.unquote(m.group(k)).lower() for k in (1, 2))
            if (project, repo) != (self.project.lower(), self.repo.lower()):
                return None
            number = int(m.group(3))
        elif ref.isdigit():
            number = int(ref)
        else:
            return None
        path = f"_apis/git/repositories/{q(self.repo)}/pullrequests/{number}"
        try:
            d = self._request("GET", path)
        except NotFound:
            return None
        status = d.get("status", "")
        merged = status == "completed"
        return tracker.PR(
            number=number, url=self.pr_url(number), title=d.get("title", ""), body=d.get("description") or "",
            head=strip_ref(d.get("sourceRefName")), base=strip_ref(d.get("targetRefName")),
            state={"active": "open", "completed": "merged", "abandoned": "closed"}.get(status, status),
            merged=merged, merged_by=ident(d.get("closedBy")) if merged else "",
            merge_sha=(d.get("lastMergeCommit") or {}).get("commitId", "") if merged else "",
            files=self._pr_files(path), completion_options=d.get("completionOptions") or {},
        )

    def _pr_files(self, path: str) -> list:
        """Paths changed by the last iteration against the merge base, without the leading `/`."""
        iterations = values(self._request("GET", f"{path}/iterations"))
        if not iterations:
            return []
        last = max(int(i["id"]) for i in iterations)
        files: list = []
        skip = 0
        while True:
            d = self._request("GET", f"{path}/iterations/{last}/changes?$top=2000&$skip={skip}")
            for c in values(d, "changeEntries"):
                item = c.get("item") or {}
                if item.get("path") and not item.get("isFolder"):
                    files.append(item["path"].lstrip("/"))
            nxt = int(d.get("nextSkip") or 0)
            if nxt <= skip:
                return files
            skip = nxt

    def pr_checks(self, sha: str) -> list:
        """The newest build per definition whose sourceVersion is `sha` (needs a CI trigger on main)."""
        builds = self._pages("_apis/build/builds?queryOrder=queueTimeDescending&$top=200", max_pages=BUILD_PAGES,
                             strict=False)
        latest: dict = {}
        for b in builds:
            if b.get("sourceVersion") == sha:
                d = b.get("definition") or {}
                latest.setdefault(d.get("id") or d.get("name"), b)
        return [build_check(b) for b in latest.values()]
