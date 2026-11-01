# Plan — the kit on Azure DevOps (Repos + Boards + Pipelines), additive to GitHub

Status: APPROVED rev 1 by Kacper on 2026-11-01, by instruction ("implement it, now ... without me
creating scratch ado"): no scratch Azure DevOps organisation for now, so A0 and every live
verification are deferred to the first real ADO target; A1 to A8 are built against a fake ADO
REST API in the test suite (documented shapes, recorded fixtures) and the gap is named in each
step's verify column and in DECISIONS.md. Open questions keep their defaults until answered on #15.
Trigger: the deferred item in `docs/PLAN-2026-10-mature-setup.md` ("Jira/ADO adapters behind
the fixed `Backend` protocol + contract test: the first work repo that is not on GitHub").
Method: coupling inventory of the kit (60 findings) → two claim-verification passes against
Microsoft Learn, VS Code and GitHub docs (29 claims: 2 refuted, 14 corrected, 13 confirmed) →
two independent designs (minimal adapter; maximal server-enforced controls) → this synthesis.
"Verified" below means read on learn.microsoft.com, devblogs.microsoft.com or
code.visualstudio.com on 2026-11-01; "unverified" items are settled by the spike (A0) first.

## 0. What already works on an ADO repo (no change)

| Kit piece | Why |
|---|---|
| `AGENTS.md`/`CLAUDE.md`, `.claude/skills`, `.claude/agents`, `.github/hooks/guard.json`, `.github/instructions/*` | VS Code + Copilot reads them from the working tree; Azure DevOps workspaces are named as supported (VS Code hooks doc, 2026-10-28). `.github/` there means Copilot, not GitHub the forge |
| `tools/guard` (every rule except tracker-guard's `gh` patterns), the testguard and latest-tag hooks, `.githooks/commit-msg`, the egress screen, memory, ledger | local git and filesystem only; no forge call |
| Tracker data model, transition table, verb logic, body helpers, markers, `is_human()`, `FakeBackend`, `test_verbs.py`, `test_model.py` | reach the forge only through `Backend` |
| `evidence_export capture` and the git half of `collect()` | local |
| `fresh-review` | git diff + `claude -p`; only the default base name `origin/main` is an assumption |

What touches GitHub: `GitHubBackend` and the three places that construct it directly
(`tracker.main`, `label_lint`, `session_start`); `evidence_export`'s `Gh` wrapper (bypasses
the seam); the two workflows; the issue forms; `kit.manifest` (ships the GitHub files into
every target); tracker-guard's `gh` regexes; wording in skills, agents and docs.

## 1. Verified facts that shape the design (surprises first)

1. **Closing keywords DO move work items on Azure Repos** (claim refuted). With the repo
   setting "Commit mention work item resolution" ON (the default), `Fixes #N`, `Resolves #N`,
   `Closes #N` and ANY valid state name before `#N` in a PR description transition the item
   on merge; `#N` in a commit links it. The kit's ban matters more on ADO, and the setting
   must be OFF in every kit repo. The completion dialog's "Complete linked work items after
   merging" (`completionOptions.transitionWorkItems`) remembers each user's last choice and
   cannot be disabled server-side. (Learn: auto-complete-work-items-pull-requests, 2026-02-28.)
2. **Copilot code review exists for Azure Repos PRs** (claim refuted): public preview on
   Services since Sprint 279 (2026-09-04); auto-requested by a branch policy; reads
   `.github/copilot-instructions.md` and `.github/instructions/*.instructions.md` (with
   `applyTo`) from the target branch; always votes "Comment", never counts toward reviewer
   policies, never blocks; billed per review in GitHub AI credits on a linked Azure
   subscription (1 credit = 0.01 USD; per-review price unverified). The Copilot coding agent
   still needs a GitHub repo.
3. **Server-enforced transitions exist, Services only**: an inherited-process rule
   "current user is not a member of group → restrict the transition to state X" applies to
   REST updates too, except for identities holding "Bypass rules on work item updates"
   (`bypassRules=true`). Required and read-only fields by state are rules as well. Azure
   DevOps Server lacks the group condition. (Learn: apply-rules-to-workflow-states, 2026-03-24.)
4. **Work item text fields are HTML by default**; Markdown is GA on Services since July 2025,
   opt-in per field per work item (`/multilineFieldsFormat/System.Description`), irreversible,
   absent on Server. Server-side HTML normalisation is undocumented, so the body-freeze hash
   needs a round-trip test. (DevOps blog 2025-07-07.)
5. **Revisions are the audit trail**: every field change is a revision with ChangedBy and
   ChangedDate (`/revisions`, `/updates`); comment edits and deletes keep versions. But
   Contributors can delete work items to the recycle bin by default, and the organisation
   audit log records no work-item field events, keeps 90 days, is off by default and in
   preview. (Learn: auditing-events 2026-09-10; manage-work-items 2026-02-28.)
6. **Pipelines**: YAML `pr:` triggers are ignored on Azure Repos; PR validation is a branch
   policy outside the repo; it runs on a preview merge commit (`refs/pull/N/merge`), skips
   draft PRs, exposes `System.PullRequest.*` but no PR labels or title (REST with
   `System.AccessToken`). Run retention is a project setting and logs die with the run unless
   leased. Tasks pin to `Name@X.Y.Z` at best, never a SHA; hosted images update weekly and
   cannot reach private endpoints. (Learn: variables, azure-repos-git, retention, hosted agents.)
7. **Auth**: `az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798`
   gives a ~1 h Entra token; global PATs are being retired (date in flux: Learn 2026-12-01,
   blog 2026-10-23 says postponed); tenant policies can restrict PATs. The `azure-devops` CLI
   extension cannot read comments, cannot list or edit PR labels after creation, and
   `az devops invoke` is a generic REST writer the guard must cover. Service principals can
   be ADO users (Basic licence) with no secret stored on the ADO side.
8. **Pricing**: Basic free for 5 users, then 6 USD/user/month; one free hosted parallel job
   (1,800 min/month) after linking an Azure subscription; one free self-hosted job. GHAzDO:
   Secret Protection 19 USD, Code Security 30 USD per active committer per month.

Unverified (A0 decides): `<!-- -->` markers surviving in Markdown comments; Markdown Description
round trip (whitespace, CRLF, after a web edit); the 404 shape of the PR endpoint; whether a
no-fast-forward completion reuses the validated commit; `closedBy` vs `autoCompleteSetBy`; the
PR web-URL key in `_links`; descriptor prefixes of Build Service and service-principal
identities; whether a restricted-transition rule combines with a from-state condition; whether
the commit-mention setting is readable over REST.

## 2. Design decisions (recommendation; the alternative is named)

1. **One `AdoBackend` behind the existing `Backend` seam**, plus `backend_for()` keyed on the
   origin host (`dev.azure.com`, `ssh.dev.azure.com`, `*.visualstudio.com`) or
   `KZ_TRACKER_BACKEND`, used by all three entry points. Rejected: a plugin layer (one consumer).
2. **Transport = stdlib `urllib`, REST api-version 7.1, Entra bearer token**
   (`SYSTEM_ACCESSTOKEN` in pipelines, else `az account get-access-token`). No PAT code path,
   no `az boards` writes, no token cache in v1 (the SessionStart digest is best-effort and
   already silent on timeout). Rejected: shelling to `az boards` as `gh`'s analogue (too slow
   for the 2–3 s budgets, cannot read comments or labels).
3. **Two status modes, one backend.** `tags` mode (default, no admin rights): `type/*` and
   `status/*` live in `System.Tags`; add-then-remove-siblings, the "2 status labels" refusal
   and `label-lint` work unchanged; enforcement = the GitHub level. `process` mode
   (recommended for client projects; needs a process admin once): `status/*` =
   `System.State` of a custom work item type `Change` in an inherited process, `type/*` = a
   required picklist, human-only transitions to Ready/Done/Removed as a group-restricted rule,
   Description read-only after Ready for non-owners; the kit's own checks stay as layer two.
   See Q-ADO-2.
4. **Description created in Markdown mode**; `get_issue` refuses HTML items with a message
   naming the fix. Markers = Markdown Discussion comments, all pages, oldest first; the
   fallback marker form is decided by A0 (Q-ADO-8).
5. **Canonical identity = `IdentityRef.id` GUID** for whoami, marker `by`, comment author and
   `closedBy`; Build Service and service-principal GUIDs in `KZ_TRACKER_BOTS`; the evidence
   pack adds display names.
6. **Repo settings documented in `docs/ADO-ADMIN.md`, not enforced by the kit**: commit-mention
   resolution OFF; build validation on `main`; minimum 1 reviewer with "prohibit the most
   recent pusher" and no self-approval; reset votes on push; comment resolution; linked work
   items; no-fast-forward only; Force push denied. `done` additionally refuses when
   `completionOptions.transitionWorkItems` or `bypassPolicy` is true; the PR-body closing
   regex gains the ADO built-in state names and the `AB#N` form.
7. **Pipelines mirror the GitHub split**: `azure-pipelines.yml` (init, target-owned: test
   matrix, commit-msg on `HEAD^1..HEAD^2`, guards with labels and title over REST failing
   closed, aggregate gate) and `azure-pipelines-label-lint.yml` (managed, nightly with
   `always: true`). `trigger: main` so `pr_checks(merge_sha)` finds a build on the real merge
   commit; a retention lease on `main` runs.
8. **Evidence schema → `agent-change-control/change-records/2`** for both forges: `/1` plus
   `forge`, `api_version`, per-PR `completion_options`, `reviews[].commit_id` nullable, and
   forge-specific sections (`rulesets` on GitHub; `policies`, `branch_acl`, `revisions` on
   ADO). Rejected: additive keys under `/1` (ADO vocabulary under the GitHub id misleads a
   reader). See Q-ADO-6.
9. **Installer forge column** in `kit.manifest`: ADO targets receive the pipeline files and
   `docs/ADO-ADMIN.md`, not the workflows and issue forms (inactive files read as controls).
10. **Copilot code review for Azure Repos = advisory**, enabled by branch policy where the org
    allows, with a credit cap; `fresh-review` receipts (home) and the human approval (both)
    remain the review evidence. The kit's `review.instructions.md` already carries `applyTo`.
11. **Out of v1**: Azure DevOps Server, Jira, service hooks for work-item events, a token
    cache, an MCP server, GHAzDO as a dependency (recommended at work, not required).

## 3. Open questions (defaults apply unless you object)

| # | Question | Why it matters | Default |
|---|---|---|---|
| Q-ADO-1 | Services (dev.azure.com) or Server at work? | Server: no Markdown fields, no Entra identities, no group transition rules, capped api-versions | Services; Server out of v1 |
| Q-ADO-2 | May a process admin create an inherited process with the `Change` type, states and rules on the pilot project? | Decides whether status exclusivity and human-only transitions are server rules or kit checks | tags mode first; process mode as A7 when granted |
| Q-ADO-3 | Who are the Change Owners at work; are they different people from the developers running agents? | The rule separates identities, not sessions; a developer-owner's agent session could still transition | QA or product lead + tech lead; developers excluded; the TTY gate stays as layer two |
| Q-ADO-4 | A free personal ADO org (5 Basic users, synthetic data only) for the spike and the live contract suite? Hosted minutes (needs an Azure subscription link) or a self-hosted agent on the Mac? | Nothing can be verified without a live target | Yes; self-hosted agent on the Mac first (0 USD) |
| Q-ADO-5 | Agent identity on developer machines: the developer's Entra user or a service principal? | A service principal needs a federated credential or certificate on the machine and a Basic licence | Developer identity; service principal only for unattended runs |
| Q-ADO-6 | Schema `/2` for both forges? | Changes the GitHub output, additively | Yes |
| Q-ADO-7 | Enable Copilot code review for Azure Repos at work as advisory, with a credit cap? | Per-review billing on the linked subscription | Yes if the org allows; cap recorded in the work DECISIONS |
| Q-ADO-8 | If `<!-- -->` is stripped from Markdown comments, is a visible ```` ```tracker ```` fence acceptable as the marker on both forges? | `_MARK_RE` is shared | Yes; GitHub keeps writing the hidden form |
| Q-ADO-9 | Merge type on `main`: no-fast-forward only? | One merge commit = GitHub semantics; squash changes the SHA the checks ran on | No-fast-forward only |
| Q-ADO-10 | One repo per ADO project at work? | Work items are project-scoped; multi-repo projects need an area path per repo | One repo; `KZ_TRACKER_AREA` for the rest |

## 4. Step plan (one step = one PR-sized commit with its verification; S < 1 h, M ≈ half day, L = days)

| # | Step | Effort | Verify |
|---|---|---|---|
| A0 | Spike on the scratch org: a throwaway `urllib` script in the scratchpad (never committed) settles the nine unverified facts of §1; each becomes a DECISIONS line | S–M (one day incl. org setup) | nine DECISIONS lines "verified on <date>" or "failed → fallback X"; raw JSON samples kept in the scratchpad |
| A1 | `backend_for()` in `tracker.py`, used by `tracker`, `label_lint`, `session_start`; `--repo` accepts `org/project/repo`; the contract suite gains an `ado` parameter gated by `KZ_TRACKER_TEST_ADO`; `hasattr(signal, "SIGALRM")` guard in `session_start` (Windows shops) | S | `pytest tools/tracker -q` green on fake; the `KZ_TRACKER_TEST_REPO` GitHub run unchanged; `ruff check tools` |
| A2 | `tools/tracker/ado.py`: AdoBackend in tags mode (~250 lines, stdlib): transport, `{count,value}` unwrap, continuation-token paging, 404 → `None`, origin parsing, whoami via `connectionData`, WIQL scoped to the area path + `workitemsbatch`, JSON Patch with `test /rev`, Markdown Description, Markdown comments, `close_issue` = the type's Completed state, emulated label registry (two contract assertions `xfail(strict)` on ado), `pr()` from web URL or id with `refs/heads/` and leading `/` stripped, `pr_checks()` = builds by `sourceVersion` + policy evaluations (partiallySucceeded never passes), `done` refusals on `transitionWorkItems`/`bypassPolicy`, closing regex + ADO state names + `AB#N` | L | `KZ_TRACKER_TEST_ADO=… pytest tools/tracker/tests/test_contract.py -k ado` green except the two xfails; `new → claim → review → owner done` on the scratch project writes `merge_sha`, `merged_by` GUID, `decisions_md` |
| A3 | Guards and scans: tracker-guard denies `az boards work-item create\|update\|delete\|relation`, `az devops invoke`, `az rest`/curl/wget writes to `*/_apis/wit/*`, any `bypassRules`, `az repos pr … --bypass-policy\|--transition-work-items\|--status completed`; deploy-ask exempts `az repos pr create`, adds `az pipelines run`; ADO PAT pattern (84 chars, `AZDO` at 76–80) in redaction and the egress screen; `~/.azure` in secret dirs; `AB#N` in `commit_msg.py`; `azure-pipelines*.yml` in `latest_tag.py` | S | one fixture per new deny/ask; `pytest tools/guard tools/egress tools/scan tools/tests -q`; one hook run < 2 s |
| A4 | `ci/azure-pipelines.yml` (init) + `ci/azure-pipelines-label-lint.yml` (managed); testguard reads `BASE_REF` from `System.PullRequest.targetBranchName`, labels and title over REST, fails closed when `PullRequestId` is set and labels are unreadable (shared fix: unset ≠ empty `PR_LABELS`); retention lease step on `main`; script steps over Marketplace tasks, tasks pinned `@X.Y.Z` | M | on the scratch project: a PR deleting a test fails the gate and passes with `test-removal-ok`; `Fixes #1` fails commit-msg; a draft PR does not run; the nightly lint posts one comment; a `main` run shows a lease |
| A5 | Forge column (`github\|ado`) in `kit.manifest`; `install.sh --forge` or origin detection; ADO targets get the pipeline files and `docs/ADO-ADMIN.md`, not workflows and issue forms; `kit-version` records the forge | S | install into a scratch ADO clone: no `.github/workflows`, both pipeline files, second run "changes: 0"; GitHub idempotence test unchanged |
| A6 | Evidence export for ADO + schema `/2`: AdoReader (GET only) for PRs completed to `main` in the git range (detail per PR), vote threads, policy evaluations, builds on `lastMergeCommit`, `completionOptions`, work items with `/updates` revisions and comment versions, policy configurations, branch ACL, retention values; datetime comparison for windows; `forge`/`api_version` on both forges | L | export on the scratch project lists the completed PR, its checks, the issue with four markers and its revisions; GitHub output unchanged except the new keys; recorded-fixture tests |
| A7 | Process mode (gated on Q-ADO-2 and A0): state↔status table, `remove_labels(status/*)` no-op, `labels-sync` verifies the states exist, capability flags in the contract suite, label-lint reports "state without matching marker"; `docs/ADO-ADMIN.md`: process spec, Change Owners group, denies (bypass rules, delete), area node, Build Service rights, repo settings, branch policies, retention, auditing stream, each with the REST GET that proves it | M | contract suite green in process mode on the scratch org; a REST PATCH to Ready by a non-owner is rejected by the server; the export shows the process rules |
| A8 | Docs and skills: USING-AT-WORK ADO section (adapter, required settings, bots list, Copilot review as advisory), SYSTEM.md interfaces, README, AGENTS.md harness notes, pr-prep (`az repos pr create --description` with `Refs #N` first, 4000-unit cap, pass the web URL), gxp-check (grep pipeline files), platform-flow and validation-evidence vocabulary, infra-reviewer pipeline block; DECISIONS lines from §6 | S | prompt-equality test green; `grep -rn 'GitHub only'` empty; Kacper reviews |
| A9 | Work pilot on ADO (= plan step 3.9 with the ADO specifics): install, admin checklist, one change through `new → done`, evidence pack; findings into the work repo's own DECISIONS.md | M | the pilot's `change-records.json` shows policy evaluations, revisions and a leased build; a QA walkthrough |

Order: A0 → A1 → A2 and A3 in parallel → A4 → A5 → A6 → A8; A7 when Q-ADO-2 is answered;
A9 last. Roughly 6–8 part-time working days of Claude-executed, Kacper-reviewed work; the
spike is the first day. Each step from A1 on becomes an issue in this repo's tracker.

## 5. Trade-offs

| Choice | Taken | Why | Compliance angle | USD/month |
|---|---|---|---|---|
| Transport: urllib + Entra token vs `az boards` vs PAT | urllib + Entra | hooks and the digest must finish in 2–3 s; no long-lived secret; the CLI cannot read comments or labels | every write attributable to an Entra identity; tokens live ~1 h | 0 |
| Status: tags vs `System.State` | both modes, tags first | tags need no admin and keep the contract untouched; State is the only server-enforced exclusivity and transition control | process mode turns "who may transition" into a server rule with revision evidence | 0 |
| Markers: hidden HTML comment vs visible fence | spike decides | the hidden form is unverified on ADO | the marker is the protocol record; either form is machine-readable | 0 |
| Pipelines: two files vs one | two, mirroring init/managed | the lint job must update with the kit; CI belongs to the target | PR validation is a branch policy outside the repo, so the export captures the policy | 0 on the free tier; 40 per extra hosted job |
| Evidence schema: `/1` additive vs `/2` | `/2` for both forges | one schema, self-describing, no GitHub vocabulary over ADO data | records name their source and API version | 0 |
| Bot identity: Build Service vs service principal | Build Service in pipelines; SP only unattended | no secret to store; job-scoped tokens; an SP costs a licence and a credential | bots never read as human mergers | 0; ~6 per SP |
| AI review: Copilot review for Azure Repos vs fresh-review | both, advisory | the preview cannot approve or block | review evidence stays in PR threads and receipts | credits per review (cap) |
| Secret push protection: GHAzDO vs egress screen only | recommend Secret Protection at work | preventive server control the client-side screen cannot give | its own audit record | 19 per active committer |
| Audit log: in-product 90 days vs streaming | streaming at work | 90 days is fixed; bypass-on-push appears only there | audit trail beyond 90 days | 5–15 |
| Run retention: default vs lease | lease `main` runs | logs die with the run; the default is undocumented | validation evidence stays reproducible | ~0 |

## 6. DECISIONS.md lines (paste at approval)

- ADO support is additive: `AdoBackend` behind the existing `Backend` seam, `backend_for()` by origin host, the GitHub path untouched; the Jira/ADO trigger from the mature-setup plan fired with the first non-GitHub work repo; revisit if: a third forge appears (then the factory grows one line). 0 USD.
- ADO transport = stdlib urllib, REST 7.1, Entra bearer tokens (`SYSTEM_ACCESSTOKEN` in pipelines, `az account get-access-token` locally); no PAT code path, no `az boards` writes, no token cache; the `azure-devops` CLI extension cannot read comments or PR labels and starts too slowly for hooks; global PATs are being retired; revisit if: the session digest never appears on ADO (then a 0600 cache deleted on expiry) or a Server client needs a PAT via env. Compliance: every write attributable, nothing long-lived. 0 USD.
- ADO status model: tags mode default (`type/*`, `status/*` in `System.Tags`, GitHub-level enforcement, label-lint unchanged); process mode (custom WIT `Change`, `System.State`, required picklist, group-restricted transitions to Ready/Done/Removed, Description read-only after Ready) recommended for client projects and the only server-enforced form; revisit if: a client already has a change WIT (map onto it). Compliance: in process mode "who may transition" is an exported server rule plus revision history; in tags mode it is a kit check, named as a gap. 0 USD.
- ADO work items are created with the Description in Markdown mode (irreversible, Services only); HTML items are refused with the fix named; revisit if: the A0 round trip shows text changes (then `System.Rev` at ready compared with `/updates`). Compliance: body freeze after ready = original and accurate record. 0 USD.
- Canonical ADO identity = `IdentityRef.id`; Build Service and service-principal GUIDs in `KZ_TRACKER_BOTS`; display names added in the evidence pack; revisit if: auditors need names in markers. Compliance: attributable; automation never counts as a human merger. 0 USD.
- Closing keywords on ADO: the repo setting "Commit mention work item resolution" is OFF in every kit repo (any state name before `#N` in a PR description would move items on merge); `done` refuses on `completionOptions.transitionWorkItems` or `bypassPolicy`; the PR-body regex also rejects ADO state names and `AB#N`; the setting is documented and attested, not exportable (unverified); revisit if: a REST read of the setting is confirmed (then exported). Compliance: the tracker stays the only state writer. 0 USD.
- Azure Pipelines: `azure-pipelines.yml` (init) and `azure-pipelines-label-lint.yml` (managed) mirror the GitHub split; PR runs come from the build-validation policy; `trigger: main` so checks exist on the real merge commit; labels and title read over REST, fail closed; `main` runs leased; tasks pinned `@X.Y.Z`, script steps preferred (no SHA pin exists: named gap); revisit if: two registrations per repo prove a burden (then one file with `Build.Reason` conditions). Compliance: policy configuration and retention values exported with the evidence. 0 USD on the free tier; 40 USD per extra hosted job.
- Evidence schema `agent-change-control/change-records/2` for both forges: `/1` plus `forge`, `api_version`, `completion_options`, nullable `reviews[].commit_id`, forge-specific `rulesets` (GitHub) or `policies` + `branch_acl` + `revisions` (ADO); revisit if: a consumer depends on `/1` (then a `/1` writer behind a flag). Compliance: records describe their own source. 0 USD.
- Installer gains a forge column; ADO targets receive pipeline files and `docs/ADO-ADMIN.md`, never the GitHub workflows or issue forms; revisit if: never. Compliance: no inactive file can be read as an active control. 0 USD.
- Copilot code review for Azure Repos (public preview) is advisory only, auto-requested by policy where the org allows, with a credit cap; `fresh-review` receipts and the human approval remain the review evidence; revisit if: it can vote or count toward reviewer policies. Cost: per review in AI credits, price unverified.
- Out of v1 and named: Azure DevOps Server, Jira, service hooks for work-item events, token cache, MCP server, GHAzDO as a dependency (Secret Protection recommended at work, 19 USD per active committer), audit streaming (5–15 USD/month at work). Compliance: deferred items are listed so absent controls are not read as present.

## 7. Cut line

A0–A5 + A8 make the kit usable on an ADO repo (tracker, CI, guards). A6 is required before
any validation pack on ADO. A7 is the GxP upgrade and needs a process admin. A9 is the work
pilot. Drop first if time tightens: A7, then the `/2` schema (ship additive keys under `/1`
with `forge` set), then the lease step.

## 8. What an auditor gains on ADO (and does not)

Gains, in process mode: exactly one state per change record, server-side; transitions to
Ready/Done/Removed restricted to a named owner group, including over REST (separation of
duties as a rule, not a habit); the definition of ready as required fields; field-level
revision history with identity and timestamp; a "linked work item" branch policy; bypass at
PR completion recorded on the PR; force-push denial exportable as ACEs; `completionOptions`
showing whether the forge touched the record; retention leases that keep a run and its logs.
In tags mode: the revision history, branch policies and completion options; exclusivity and
transitions stay kit checks plus nightly lint, as on GitHub today.

Does not gain: bypass-on-push evidence beyond the 90-day audit log unless streamed; SHA-pinned
pipeline tasks or a pinned hosted image; protection against a Contributor deleting a work item
unless the deny is set; detection-only coverage of the "complete linked work items" checkbox
(the Done rule blocks it in process mode); proof that a human review was substantive.

## 9. Files that will exist at the end

New: `tools/tracker/ado.py`, `ci/azure-pipelines.yml`, `ci/azure-pipelines-label-lint.yml`,
`docs/ADO-ADMIN.md`, this plan, ADO fixtures and tests under `tools/tracker/tests/`.
Changed: `tools/tracker/{tracker,label_lint,session_start,evidence_export}.py`,
`tools/guard/guard.py`, `tools/commit_msg.py`, `tools/egress/egress_screen.py`,
`tools/scan/latest_tag.py`, `tools/testguard/check-test-tampering.sh`, `install.sh`,
`kit.manifest`, `README.md`, `AGENTS.md`, `DECISIONS.md`, `docs/SYSTEM.md`,
`docs/USING-AT-WORK.md`, `skills/{pr-prep,gxp-check,platform-flow,validation-evidence}/SKILL.md`,
`agents/infra-reviewer.md`.

## 10. Budget

Home: 0 USD (free ADO org, synthetic data, self-hosted agent on the Mac). Work: the org's
existing ADO licences and Copilot seat; optional GHAzDO Secret Protection 19 USD per active
committer per month; optional audit streaming 5–15 USD/month; Copilot review credits per
review under a cap; a service principal ~6 USD/month only if unattended runs need one.
