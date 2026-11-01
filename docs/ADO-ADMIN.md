# Azure DevOps admin checklist

For the project administrator (and, for process mode, a process administrator)
who prepares an Azure DevOps Services project for this kit. The kit documents
these settings and does not enforce them: each item says what to set, why, the
REST GET that proves it, and what the kit still checks where the server
control is missing ("fallback"). Keep the GET responses with the validation
evidence of the first release, and record every deviation as a line in the
work repo's `DECISIONS.md`.

**Status of every item: verified offline only.** Read on Microsoft Learn on
2026-11-01 and, where the tracker makes the call itself, exercised against the
fake API in `tools/tracker/tests/fake_ado.py`; never run against a live
organisation (plan `docs/PLAN-2026-11-ado-port.md`, steps A0 and A9). Items
marked *unverified* are not settled by the docs either; the first live run
settles them. Azure DevOps Services only: Server lacks the group rules, the
Markdown fields and auditing.

Conventions: `{org}`, `{project}`, `{repo}`; read with an Entra token
(`az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv`),
never a PAT. Ids used below:

- project id and process: `GET https://dev.azure.com/{org}/_apis/projects/{project}?includeCapabilities=true&api-version=7.1`
  → `id`, `capabilities.processTemplate.templateTypeId`
- repository id: `GET https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}?api-version=7.1` → `id`
- permission bits by name: `GET https://dev.azure.com/{org}/_apis/securitynamespaces?api-version=7.1`
- an ACL: `GET https://dev.azure.com/{org}/_apis/accesscontrollists/{namespaceId}?token={token}&includeExtendedInfo=true&api-version=7.1`
  → per identity descriptor `allow`, `deny` and the effective bits

## 1. Process mode (`KZ_TRACKER_ADO_MODE=process`)

Skip this section in tags mode (the default): there `type/*` and `status/*`
are tags on `Task` items and the tracker plus the nightly label-lint enforce
them, as on GitHub.

### 1.1 Inherited process with the `Change` type

Set: an inherited process used by the project, with a custom work item type
`Change` and these states, in this order (the first Proposed state is the
default for new items; state names cannot be changed once created):

| State | Category | Tracker status |
|---|---|---|
| Backlog | Proposed | `status/backlog` |
| Ready | Proposed | `status/ready` |
| In Progress | In Progress | `status/in-progress` |
| Blocked | In Progress | `status/blocked` |
| Review | Resolved | `status/review` |
| Done | Completed | `status/done` |
| Removed | Removed | `status/dropped` |

Only one state may sit in Completed; adding Done removes or hides the default
one. Hide the type's other default states. Add a picklist field `ChangeType`
(reference name `Custom.ChangeType`), required, with exactly the values `bug`,
`todo`, `handoff`, `decision`, `agent-note`.

Why: the server then holds exactly one status per change, with revision
history; `tools/tracker/ado.py` maps the states one to one (`STATE_OF`) and
reads Completed and Removed as closed.

Prove:
- `GET https://dev.azure.com/{org}/_apis/work/processes/{templateTypeId}?$expand=projects&api-version=7.1`
  → `parentProcessTypeId` set (inherited) and the project listed
- `GET https://dev.azure.com/{org}/{project}/_apis/wit/workitemtypes/Change/states?api-version=7.1`
  → the seven names and categories (`tracker owner labels-sync` makes this call and refuses a missing state)
- `GET https://dev.azure.com/{org}/{project}/_apis/wit/workitemtypes/Change/fields/Custom.ChangeType?$expand=allowedValues&api-version=7.1`
  → the five values

*Unverified*: that the web UI offers the Removed category for a custom state
(the Learn state-categories page describes a custom Removed state there; the
workflow page lists four categories).

### 1.2 Change Owners group

Set: a project group `Change Owners` (for example the QA or product lead and
the tech lead). No identity that runs agents, no Build Service and no service
principal is a member.

Why: the transition rules in 1.3 name this group. The rule separates
identities, not sessions: a developer who is an owner and runs an agent under
the same identity defeats it.

Prove:
- `GET https://vssps.dev.azure.com/{org}/_apis/graph/descriptors/{projectId}?api-version=7.1-preview.1` → the project scope descriptor
- `GET https://vssps.dev.azure.com/{org}/_apis/graph/groups?scopeDescriptor={scopeDescriptor}&api-version=7.1-preview.1` → the group's `descriptor`
- `GET https://vssps.dev.azure.com/{org}/_apis/graph/Memberships/{groupDescriptor}?direction=down&api-version=7.1-preview.1` → its members

Fallback: the `owner` verbs refuse without a terminal on both ends.

### 1.3 Group-restricted transitions to Ready, Done and Removed

Set: three rules on `Change`, each "Current user is not member of group
`Change Owners`" → "Restrict the transition to state" Ready, Done, Removed.
Optional (plan §2.3): Description read-only after Ready for non-owners.

Why: the rules apply to REST updates too, so an agent's token cannot promote,
close or drop a change. They also stop "Complete linked work items after
merging" when a non-owner completes the PR (workflow rules prevent the
transition). Holders of "Bypass rules on work item updates" are exempt (1.4).

Prove: `GET https://dev.azure.com/{org}/_apis/work/processes/{templateTypeId}/workItemTypes/{witRefName}/rules?api-version=7.1`
(`witRefName` from `.../work/processes/{templateTypeId}/workitemtypes?api-version=7.1`)
→ three enabled rules with the condition `whenCurrentUserIsNotMemberOfGroup`.
*Unverified*: the REST action type behind "Restrict the transition" (the 7.1
enum has no such name; `disallowValue` on `System.State` is expected), and
whether a group condition combines with a state condition (the optional rule).
Live test: a PATCH to Ready by a non-owner is rejected.

Fallback: the `owner` verbs need a terminal; label-lint reports "state without
a matching marker" for a state set outside the verbs (a board drag, a REST
write).

### 1.4 Denies for agent identities

Set: Deny, at project level, for the identities that run agents (or a group
holding them), the Build Service and service principals: "Bypass rules on work
item updates" (`BYPASS_RULES`) and "Delete and restore work items"
(`WORK_ITEM_DELETE`). "Permanently delete work items" stays with the Project
Administrators.

Why: bypass lets a save ignore every rule (`bypassRules=true`); Contributors
can delete work items to the Recycle Bin by default, and the audit log records
no work item delete.

Prove: the ACL GET on the Project namespace `52d39943-cb85-4d7f-8fa8-c6baac873819`,
token `$PROJECT:vstfs:///Classification/TeamProject/{projectId}` → both bits in
`deny` for those descriptors. As the agent identity:
`GET https://dev.azure.com/{org}/_apis/permissions/52d39943-cb85-4d7f-8fa8-c6baac873819/{bit}?tokens=$PROJECT:vstfs:///Classification/TeamProject/{projectId}&api-version=7.1`
→ `[false]`.

Fallback (both modes): tracker-guard denies any command carrying
`bypassRules=true` or `--bypass-rules`, `az boards work-item` writes,
`az devops invoke` and REST writes under `_apis/wit`; the tracker has no
delete verb.

## 2. Both modes

### 2.1 Area node and "Edit work items in this node"

Set: one area node per repository (`KZ_TRACKER_AREA`, default: the project
root). "View work items in this node" and "Edit work items in this node"
allowed on it for the agent identities and the Build Service, nothing broader.

Why: work item ids are organisation-wide; the tracker queries
`[System.AreaPath] UNDER` the node and refuses items outside it. label-lint
comments and keeps its tracking item there as the Build Service.

Prove: `GET https://dev.azure.com/{org}/{project}/_apis/wit/classificationnodes/Areas/{path}?api-version=7.1`
→ `identifier`; the ACL GET on the CSS namespace `83e28ad4-2d72-4ceb-97b0-c7726d5502c3`,
token `vstfs:///Classification/Node/{rootIdentifier}:vstfs:///Classification/Node/{nodeIdentifier}`
(the root node alone for the project root) → `WORK_ITEM_READ` and
`WORK_ITEM_WRITE` allowed. *Unverified*: the chained token form for area
nodes (Learn shows it for iterations).

Fallback: none needed; without the right the tracker fails with HTTP 403.

### 2.2 Build Service and the bots list

Set:
- Project settings > Pipelines > Settings: "Limit job authorization scope to
  current project for non-release pipelines" and "Protect access to
  repositories in YAML pipelines" on, so the job token is the project's
  `{project} Build Service ({org})` identity.
- That identity may read the repository, its PRs and PR labels
  (`tools/testguard/ado_pr_context.py`), edit work items in the area node
  (label-lint) and create retention leases (2.5). *Unverified*: the permission
  a lease needs (candidate: the Build namespace's `RetainIndefinitely`).
  It never holds `ForcePush`, `PolicyExempt`, `PullRequestBypassPolicy`,
  `BYPASS_RULES` or `WORK_ITEM_DELETE`.
- `KZ_TRACKER_BOTS`: the lowercase GUIDs of the Build Service and of every
  service principal, comma-separated, as a pipeline variable and in the shell
  where a human runs `tracker owner done`.

Why: Azure DevOps identities carry no `[bot]` suffix; `owner done` refuses a
merge whose `closedBy.id` is on the list, and nothing else tells a pipeline
merge from a human one.

Prove: `GET https://dev.azure.com/{org}/{project}/_apis/build/generalsettings?api-version=7.1`
→ `enforceJobAuthScope: true`, `enforceReferencedRepoScopedToken: true`. The
GUID: from a pipeline step with the job token,
`GET {System.CollectionUri}_apis/connectionData?api-version=7.1-preview` →
`authenticatedUser.id` (what the tracker's `whoami` reads).

Fallback: none; an empty list is a named gap.

### 2.3 Repository settings

Set: Project settings > Repositories > `{repo}` > Settings: **Commit mention
work item resolution OFF**. "Commit mention linking" may stay on (it only
links).

Why: while it is on (the default), `Fixes #N`, `Resolves #N`, `Closes #N` and
any valid state name before `#N` in a PR description move the item on merge:
with this process, `Ready #12`, `Review #12` or `Done #12` in ordinary prose
would change a record behind the tracker. Commits pushed with such a mention
do the same. The tracker must stay the only writer of state. The completion
dialog's "Complete linked work items after merging" remembers each user's last
choice and cannot be turned off server-side: rule 1.3 blocks it in process
mode, and `owner done` refuses a PR completed with `transitionWorkItems` in
both modes.

Prove: *unverified*: no documented REST read of the setting. Attest it with a
dated line in the work repo's `DECISIONS.md` (who checked, when).

Fallback: the commit-msg hook and the CI `commit_msg` job reject `Fixes #N`
and `Fixes AB#N`; `tracker review` refuses a PR body with a closing keyword,
an Azure DevOps or kit state name before `#N`, or the `AB#N` form.

### 2.4 Branch policies and permissions on `main`

Set (Repos > Branches > `main` > Branch policies):

| Policy | Setting | Why |
|---|---|---|
| Build validation | the `azure-pipelines.yml` pipeline, required | YAML `pr:` is ignored on Azure Repos; PR runs come only from this policy (draft PRs do not run) |
| Minimum number of reviewers | at least 1; requestors may not approve their own changes; prohibit the most recent pusher from approving; reset all approval votes on push | the author is never the approver; an approval covers the code that merges |
| Check for comment resolution | required | open review threads block completion |
| Check for linked work items | required | every PR traces to a change record, next to `Refs #N` |
| Limit merge types | Merge (no fast-forward) only | one merge commit, as on GitHub; squash and rebase change the SHA the checks ran on |

Security on `main` (Repos > Branches > `main` > Branch security): deny "Force
push (rewrite history, delete branches and tags)" to every non-admin group;
"Bypass policies when pushing" and "Bypass policies when completing pull
requests" only for a small admin group, never for agent identities or the
Build Service. Do not deny Contribute: that also blocks completing PRs.

Prove:
- `GET https://dev.azure.com/{org}/{project}/_apis/git/policy/configurations?repositoryId={repoId}&refName=refs/heads/main&api-version=7.1`
  → per policy `type.displayName`, `isEnabled`, `isBlocking`, `settings`
  (expected keys, *unverified*: `buildDefinitionId`; `minimumApproverCount`,
  `creatorVoteCounts: false`, `blockLastPusherVote: true`, `resetOnSourcePush: true`;
  `allowNoFastForward: true` with `allowSquash`, `allowRebase`, `allowRebaseMerge` false)
- `GET https://dev.azure.com/{org}/{project}/_apis/policy/types?api-version=7.1` → the type ids and names
- the ACL GET on the Git Repositories namespace `2e9eb7ed-3c0a-47d4-87c1-0ffdd275fd87`,
  token `repoV2/{projectId}/{repoId}/refs/heads/6d00610069006e00/` (`main` as
  hex UTF-16LE, per the DevOps blog "Git repo tokens for the security service";
  *unverified*) → `ForcePush` denied; `PolicyExempt` and
  `PullRequestBypassPolicy` not allowed for agent identities

*Unverified*: whether a no-fast-forward completion reuses the validated merge
commit.

Fallback: `tracker review` (PR head = claimed branch, `Refs #N`); `owner done`
(merged, merger not on the bots list, green builds on the merge commit, no
`bypassPolicy`); the guard denies `git push --force` locally. A bypass on push
leaves no PR record; only the audit log (2.6) shows it.

### 2.5 Pipeline retention and the lease

Set: record the project's retention values (Project settings > Pipelines >
Settings) in the work repo's `DECISIONS.md`. The `ci` job of
`azure-pipelines.yml` leases every run that is not a PR build for 36500 days,
green or red; a failed lease fails the job.

Why: deleting a run deletes its logs, artifacts and test results; the docs do
not state the default; per-pipeline rules no longer exist. PR validation runs
are not leased: `owner done` reads the build on the merge commit of `main`.

Prove:
- `GET https://dev.azure.com/{org}/{project}/_apis/build/retention?api-version=7.1`
  → `purgeRuns`, `purgePullRequestRuns`, `retainRunsPerProtectedBranch`,
  `purgeArtifacts`, each with `min`, `max`, `value`
- `GET https://dev.azure.com/{org}/{project}/_apis/build/builds/{buildId}/leases?api-version=7.1`
  → a lease with `validUntil` about a hundred years out on each `main` run

Fallback: none on the server; capture the run's output with
`evidence_export.py capture` before it expires.

### 2.6 Organisation auditing, streamed

Set: Organization settings > Policies > "Log Audit Events" on, and an audit
stream (Azure Monitor Logs, Splunk or Azure Event Grid) to a destination whose
retention is set explicitly to the client's record retention period; write the
period down. Rough cost 5 to 15 USD/month (plan §5).

Why: the in-product log keeps 90 days (fixed), is off by default, in preview
and Entra-backed organisations only. A policy bypass on push
(`Git.RefUpdatePoliciesBypassed`) appears only there. It has no work item
field events: work item lineage comes from the revisions.

Prove: `GET https://auditservice.dev.azure.com/{org}/_apis/audit/streams?api-version=7.1-preview.1`
→ a stream with `status: enabled` and its `consumerType` (needs audit log read
permission). The retention period lives in the destination, outside Azure
DevOps: attest it.

Fallback: none in the kit; without a stream, bypass-on-push evidence ends
after 90 days (named gap).

### 2.7 Optional: GitHub Advanced Security for Azure DevOps, Secret Protection

Set: Secret Protection (secret scanning and push protection) on the
repository; 19 USD per active committer per month (committers of the last 90
days).

Why: a preventive server-side control that the client-side screens cannot
give, with its own audit record.

Prove: *unverified*: no REST read confirmed; attest from the repository's
Advanced Security settings with a dated `DECISIONS.md` line.

Fallback: the guard's secret rules and redaction (Azure DevOps PAT pattern
included), the egress screen, `gitleaks` in `/gxp-check`; all client-side.

### 2.8 Optional: Copilot code review for Azure Repos, advisory

Set: the branch policy that automatically requests Copilot code review on
`main`, where the organisation allows the preview, with a credit cap on the
linked Azure subscription (GitHub AI credits, 1 credit = 0.01 USD; the price
per review is *unverified*).

Why: it reads `.github/copilot-instructions.md` and
`.github/instructions/*.instructions.md` (with `applyTo`) from the target
branch, so the kit's review instructions steer it. It always votes Comment,
never approves, never counts toward the reviewer policy, never blocks and does
not re-review new pushes: supporting evidence only. The human approval (2.4)
is the control.

Prove: the policy appears in the policy configurations GET of 2.4 (its type
name is *unverified*).

Fallback: `fresh-review` receipts at home; the human approval everywhere.

## Not covered

Azure DevOps Server, Jira and service hooks for work item events. The evidence
export (`evidence_export.py export`, schema `/2`) collects the policy
configurations and the retention settings itself; it still writes the branch
ACL as null, so keep that response by hand until the first live run (plan
step A0) settles the security token.
