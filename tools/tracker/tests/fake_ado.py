"""In-memory fake of the Azure DevOps REST endpoints AdoBackend calls; a transport for the tests (plan A2).

Not a model of Azure DevOps: it knows the routes, api-versions, WIQL shapes and JSON Patch ops the backend
emits and answers 400 to anything else, so a new kind of call fails here until the fake (and a live run)
covers it. Shapes follow the REST 7.1 reference; what only a live run can settle is named in the report of
plan step A2. Lists page `page` items at a time so continuation tokens are exercised.

    fake = FakeAdo()
    backend = ado.AdoBackend("org/proj/repo", transport=fake)   # with SYSTEM_ACCESSTOKEN=fake.token
    fake.add_pr(7, source="step-x", description="Refs #1"); fake.complete_pr(7, merge_sha="abc")
    fake.add_build("abc", result="succeeded")
"""
import json
import re
import urllib.parse

AGILE_TASK = [("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed"), ("Removed", "Removed")]
WRITABLE = {"System.Title", "System.Description", "System.AreaPath", "System.Tags", "System.State"}
_COND_RE = re.compile(r"\[(?P<field>[\w.]+)\] (?P<op>UNDER|=|CONTAINS|NOT IN|IN) "
                      r"(?P<value>'(?:[^']|'')*'|\('(?:[^']|'')*'(?:, '(?:[^']|'')*')*\))")
_STR_RE = re.compile(r"'((?:[^']|'')*)'")
_WIQL_RE = re.compile(r"SELECT \[System\.Id\] FROM WorkItems WHERE (?P<where>.+) ORDER BY \[System\.Id\]", re.S)


class FakeError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class FakeAdo:
    def __init__(self, org: str = "org", project: str = "proj", repo: str = "repo",
                 user: str = "0a1b2c3d-0000-4000-8000-00000000a11c", token: str = "fake-token", page: int = 2):
        self.org, self.project, self.repo = org, project, repo
        self.base = f"https://dev.azure.com/{org}"
        self.user, self.token, self.page = user, token, page
        self.states = {"Task": list(AGILE_TASK)}
        self.items: dict = {}
        self.comments: dict = {}
        self.tags: list = []
        self.prs: dict = {}
        self.changes: dict = {}
        self.builds: list = []
        self._definitions: dict = {}
        self.calls: list = []  # (method, path, query, body)
        self._next = {"item": 1, "comment": 1, "build": 1}
        self.routes = [
            ("GET", r"_apis/connectionData", "7.1-preview", self._connection),
            ("POST", r"[^/]+/_apis/wit/workitems/\$(?P<wit>[^/]+)", "7.1", self._create),
            ("GET", r"[^/]+/_apis/wit/workitems/(?P<id>\d+)", "7.1", self._get_item),
            ("PATCH", r"[^/]+/_apis/wit/workitems/(?P<id>\d+)", "7.1", self._patch_item),
            ("POST", r"[^/]+/_apis/wit/wiql", "7.1", self._wiql),
            ("POST", r"[^/]+/_apis/wit/workitemsbatch", "7.1", self._batch),
            ("GET", r"[^/]+/_apis/wit/workItems/(?P<id>\d+)/comments", "7.1-preview.4", self._list_comments),
            ("POST", r"[^/]+/_apis/wit/workItems/(?P<id>\d+)/comments", "7.1-preview.4", self._add_comment),
            ("GET", r"[^/]+/_apis/wit/tags", "7.1-preview.1", self._tags),
            ("GET", r"[^/]+/_apis/wit/workitemtypes/(?P<wit>[^/]+)/states", "7.1", self._states),
            ("GET", r"[^/]+/_apis/git/repositories/(?P<repo>[^/]+)/pullrequests/(?P<id>\d+)", "7.1", self._get_pr),
            ("GET", r"[^/]+/_apis/git/repositories/(?P<repo>[^/]+)/pullrequests/(?P<id>\d+)/iterations", "7.1",
             self._iterations),
            ("GET", r"[^/]+/_apis/git/repositories/(?P<repo>[^/]+)/pullrequests/(?P<id>\d+)/iterations/"
                    r"(?P<it>\d+)/changes", "7.1", self._changes),
            ("GET", r"[^/]+/_apis/build/builds", "7.1", self._builds),
        ]

    # -- seeding helpers for tests ---------------------------------------------

    def identity(self, gid: str = "") -> dict:
        gid = gid or self.user
        return {"id": gid, "displayName": f"user {gid[-4:]}", "uniqueName": f"{gid[-4:]}@example.invalid"}

    def seed_item(self, title: str = "seeded", description: str = "", markdown: bool = True, wit: str = "Task",
                  **fields) -> int:
        """A work item as the web UI would create it (markdown=False: the default HTML Description)."""
        n = self._new_item(wit)
        self.items[n]["fields"].update({"System.Title": title, "System.Description": description, **fields})
        if markdown:
            self.items[n]["format"]["System.Description"] = "markdown"
        return n

    def add_pr(self, number: int, source: str = "step-x", target: str = "main", description: str = "",
               title: str = "a change", files: tuple = ("DECISIONS.md",), iterations: int = 2) -> None:
        self.prs[number] = {
            "pullRequestId": number, "status": "active", "title": title, "description": description,
            "sourceRefName": "refs/heads/" + source, "targetRefName": "refs/heads/" + target,
            "createdBy": self.identity(), "completionOptions": {}, "lastMergeCommit": {"commitId": "pr-preview"},
            "repository": {"name": self.repo, "project": {"name": self.project}},
            "url": f"{self.base}/{self.project}/_apis/git/repositories/{self.repo}/pullRequests/{number}",
        }
        self.changes[number] = (iterations, ["/" + f for f in files] + ["/"])  # "/" stands for a folder entry

    def complete_pr(self, number: int, merge_sha: str, closed_by: str = "", **completion) -> None:
        self.prs[number].update(status="completed", closedBy=self.identity(closed_by),
                                lastMergeCommit={"commitId": merge_sha}, completionOptions=completion)

    def add_build(self, sha: str, result: str = "succeeded", status: str = "completed", name: str = "ci") -> None:
        """Newest last; the API lists newest first."""
        n = self._take("build")
        self._definitions.setdefault(name, len(self._definitions) + 1)
        self.builds.append({"id": n, "definition": {"id": self._definitions[name], "name": name},
                            "sourceVersion": sha, "status": status, "result": result if status == "completed" else None,
                            "_links": {"web": {"href": f"{self.base}/{self.project}/_build/results?buildId={n}"}}})

    # -- transport -------------------------------------------------------------

    def __call__(self, method: str, url: str, headers: dict, data) -> tuple:
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        path = urllib.parse.unquote(parts.path)
        body = json.loads(data.decode("utf-8")) if data else None
        self.calls.append((method, path, query, body))
        try:
            if headers.get("Authorization") != "Bearer " + self.token:
                raise FakeError(401, "TF400813: The user is not authorized to access this resource.")
            status, payload, extra = self._route(method, path, query, body, headers)
        except FakeError as exc:
            status, payload, extra = exc.status, {"$id": "1", "message": exc.message}, {}
        return status, {"content-type": "application/json", **extra}, json.dumps(payload).encode("utf-8")

    def _route(self, method, path, query, body, headers) -> tuple:
        prefix = f"/{self.org}/"
        if not path.startswith(prefix):
            raise FakeError(404, f"no organisation in {path}")
        rest = path[len(prefix) :]
        for verb, pattern, version, handler in self.routes:
            m = re.fullmatch(pattern, rest, re.IGNORECASE)
            if m and verb == method:
                if query.get("api-version") != version:
                    raise FakeError(400, f"{rest}: api-version {query.get('api-version')!r}, fake expects {version}")
                if rest.split("/")[0] != "_apis" and rest.split("/")[0] != self.project:
                    raise FakeError(404, f"project {rest.split('/')[0]} does not exist")
                if handler in (self._create, self._patch_item) \
                        and headers.get("Content-Type") != "application/json-patch+json":
                    raise FakeError(415, "work item writes take application/json-patch+json")
                result = handler(query=query, body=body, **m.groupdict())
                return result if isinstance(result, tuple) else (200, result, {})
        raise FakeError(400, f"the fake does not know {method} {rest}")

    def _take(self, kind: str) -> int:
        n = self._next[kind]
        self._next[kind] += 1
        return n

    # -- work items ------------------------------------------------------------

    def _new_item(self, wit: str) -> int:
        if wit not in self.states:
            raise FakeError(404, f"VS402323: work item type {wit} does not exist")
        n = self._take("item")
        self.items[n] = {"id": n, "rev": 1, "format": {}, "fields": {
            "System.Id": n, "System.WorkItemType": wit, "System.TeamProject": self.project,
            "System.AreaPath": self.project, "System.State": self.states[wit][0][0],
            "System.CreatedBy": self.identity()}}
        self.comments[n] = []
        return n

    def _item(self, id) -> dict:
        if int(id) not in self.items:
            raise FakeError(404, f"TF401232: Work item {id} does not exist, or you do not have permissions to read it.")
        return self.items[int(id)]

    def _shape(self, item: dict, fields=None) -> dict:
        """As the API returns it: empty fields omitted; multilineFieldsFormat only without `fields=`."""
        f = {k: v for k, v in item["fields"].items() if v not in ("", None) and (fields is None or k in fields)}
        out = {"id": item["id"], "rev": item["rev"], "fields": f,
               "url": f"{self.base}/{self.project}/_apis/wit/workItems/{item['id']}"}
        if fields is None and item["format"]:
            out["multilineFieldsFormat"] = dict(item["format"])
        return out

    def _set(self, item: dict, field: str, value) -> None:
        if field not in WRITABLE:
            raise FakeError(400, f"TF51535: Cannot find field {field}.")
        wit = item["fields"]["System.WorkItemType"]
        if field == "System.State" and value not in [s for s, _ in self.states[wit]]:
            raise FakeError(400, f"TF401320: Rule Error for field State: {value!r} is not an allowed value")
        if field == "System.AreaPath" and not (value == self.project or value.startswith(self.project + "\\")):
            raise FakeError(400, f"TF401347: Invalid tree name given for work item, field 'System.AreaPath': {value}")
        if field == "System.Tags":
            names: list = []
            for t in (s.strip() for s in str(value).split(";")):
                if t and t.lower() not in [n.lower() for n in names]:
                    names.append(next((k for k in self.tags if k.lower() == t.lower()), t))
            for t in names:
                if t.lower() not in [k.lower() for k in self.tags]:
                    self.tags.append(t)
            value = "; ".join(names)
        item["fields"][field] = value

    def _apply(self, item: dict, ops) -> None:
        if not isinstance(ops, list) or not ops:
            raise FakeError(400, "a JSON Patch document (a non-empty list) is required")
        for op in ops:
            kind, path, value = op.get("op"), op.get("path", ""), op.get("value")
            if kind == "test" and path == "/rev":
                if value != item["rev"]:
                    raise FakeError(412, "TF26071: This work item has been changed by someone else since you "
                                         "opened it.")
            elif kind in ("add", "replace") and path.startswith("/fields/"):
                self._set(item, path[len("/fields/") :], value)
            elif kind == "add" and path == "/multilineFieldsFormat/System.Description" and value == "Markdown":
                item["format"]["System.Description"] = "markdown"
            else:
                raise FakeError(400, f"the fake does not support {kind} {path}")

    def _create(self, query, body, wit) -> dict:
        n = self._new_item(wit)
        try:
            self._apply(self.items[n], body)
        except FakeError:
            del self.items[n]
            raise
        return self._shape(self.items[n])

    def _get_item(self, query, body, id) -> dict:
        fields = query["fields"].split(",") if "fields" in query else None
        return self._shape(self._item(id), fields)

    def _patch_item(self, query, body, id) -> dict:
        item = self._item(id)
        snapshot = json.loads(json.dumps(item))
        try:
            self._apply(item, body)
        except FakeError:
            self.items[int(id)] = snapshot  # all or nothing, as on the server
            raise
        item["rev"] += 1
        return self._shape(item)

    def _matches(self, item: dict, field: str, op: str, value: str) -> bool:
        have = str(item["fields"].get(field, "") or "")
        if op == "UNDER":
            return have.lower() == value.lower() or have.lower().startswith(value.lower() + "\\")
        if op == "=":
            return have.lower() == value.lower()
        if op == "CONTAINS" and field == "System.Tags":
            return value.lower() in [t.strip().lower() for t in have.split(";")]
        if op in ("IN", "NOT IN"):
            inside = have.lower() in [v.lower() for v in value]
            return inside if op == "IN" else not inside
        raise FakeError(400, f"the fake does not support [{field}] {op}")

    def _wiql(self, query, body) -> dict:
        m = _WIQL_RE.fullmatch((body or {}).get("query", ""))
        if not m:
            raise FakeError(400, f"TF51006: the fake cannot parse {body!r}")
        where, pos, conds = m.group("where"), 0, []
        while True:
            c = _COND_RE.match(where, pos)
            if not c:
                raise FakeError(400, f"TF51006: the fake cannot parse the condition at {where[pos:]!r}")
            raw = c.group("value")
            value = [s.replace("''", "'") for s in _STR_RE.findall(raw)]
            conds.append((c.group("field"), c.group("op"), value if raw.startswith("(") else value[0]))
            pos = c.end()
            if pos == len(where):
                break
            if not where.startswith(" AND ", pos):
                raise FakeError(400, f"TF51006: the fake supports AND only, at {where[pos:]!r}")
            pos += len(" AND ")
        hits = [n for n, item in sorted(self.items.items()) if all(self._matches(item, *cond) for cond in conds)]
        return {"queryType": "flat", "workItems": [{"id": n, "url": f"{self.base}/_apis/wit/workItems/{n}"}
                                                   for n in hits]}

    def _batch(self, query, body) -> dict:
        ids, fields = body.get("ids") or [], body.get("fields")
        if len(ids) > 200:
            raise FakeError(400, "VS403474: at most 200 ids per workitemsbatch call")
        for f in fields or []:
            if f not in WRITABLE | {"System.Id", "System.WorkItemType", "System.CreatedBy"}:
                raise FakeError(400, f"TF51535: Cannot find field {f}.")
        found = [self._shape(self._item(i), fields) for i in ids]
        return {"count": len(found), "value": found}

    def _list_comments(self, query, body, id) -> dict:
        self._item(id)
        rows = sorted(self.comments[int(id)], key=lambda c: c["id"], reverse=query.get("order") == "desc")
        start = int(query.get("continuationToken") or 0)
        size = min(int(query.get("$top") or 200), self.page)
        page = rows[start : start + size]
        out = {"totalCount": len(rows), "count": len(page), "comments": page}
        if start + size < len(rows):
            out["continuationToken"] = str(start + size)
        return out

    def _add_comment(self, query, body, id) -> dict:
        self._item(id)
        c = {"id": self._take("comment"), "workItemId": int(id), "version": 1, "text": body["text"],
             "format": query.get("format", "html"), "createdBy": self.identity(), "isDeleted": False,
             "createdDate": f"2026-11-01T00:00:{len(self.comments[int(id)]):02d}.123Z"}
        self.comments[int(id)].append(c)
        return c

    def _tags(self, query, body) -> dict:
        return {"count": len(self.tags), "value": [{"id": f"tag-{i}", "name": t} for i, t in enumerate(self.tags)]}

    def _states(self, query, body, wit) -> dict:
        if wit not in self.states:
            raise FakeError(404, f"VS402323: work item type {wit} does not exist")
        rows = [{"name": s, "color": "b2b2b2", "category": c} for s, c in self.states[wit]]
        return {"count": len(rows), "value": rows}

    # -- pull requests and builds -----------------------------------------------

    def _pr(self, repo, id) -> dict:
        if repo.lower() != self.repo.lower() or int(id) not in self.prs:
            raise FakeError(404, "TF401180: The requested pull request was not found.")
        return self.prs[int(id)]

    def _get_pr(self, query, body, repo, id) -> dict:
        return self._pr(repo, id)

    def _iterations(self, query, body, repo, id) -> dict:
        self._pr(repo, id)
        n = self.changes[int(id)][0]
        return {"count": n, "value": [{"id": i} for i in range(1, n + 1)]}

    def _changes(self, query, body, repo, id, it) -> dict:
        self._pr(repo, id)
        last, paths = self.changes[int(id)]
        if int(it) != last:
            return {"changeEntries": []}  # earlier iterations: not what the backend should read
        skip, top = int(query.get("$skip") or 0), min(int(query.get("$top") or 100), self.page)
        rows = [{"changeType": "edit", "item": {"path": p, **({"isFolder": True} if p == "/" else {})}}
                for p in paths[skip : skip + top]]
        out = {"changeEntries": rows}
        if skip + top < len(paths):
            out.update(nextSkip=skip + top, nextTop=top)
        return out

    def _builds(self, query, body) -> tuple:
        if query.get("queryOrder") != "queueTimeDescending":
            raise FakeError(400, "the fake lists builds newest first only")
        rows = list(reversed(self.builds))
        start = int(query.get("continuationToken") or 0)
        size = min(int(query.get("$top") or 1000), self.page)
        extra = {"x-ms-continuationtoken": str(start + size)} if start + size < len(rows) else {}
        page = rows[start : start + size]
        return 200, {"count": len(page), "value": page}, extra

    def _connection(self, query, body) -> dict:
        return {"authenticatedUser": self.identity(), "instanceId": "00000000-0000-4000-8000-000000000001"}
