# Using this setup at work (VS Code + GitHub Copilot)

For a work machine with VS Code and GitHub Copilot, where Claude Code is not
installed. Status 2026-10-29: plan step 1.1 is done, so §1 is usable today;
§2 lists what each later step adds. Copilot's hooks, skills and MCP policies
are enabled in the org (confirmed by Kacper).

## 0. Boundaries first

- Only the kit's public MIT files cross over. Nothing from home: no memory,
  telemetry, tokens, transcripts or hook captures.
- Client data never enters the kit, a hook fixture, a memory file or a prompt
  beyond the endpoint the org approved. `AGENTS.md` rule 6 applies on day one.
- Findings about the work environment (model names, policies, tool ids) go to
  the work repo's own `DECISIONS.md`, never to this repo.
- Pick one low-risk pilot repo you are allowed to configure, on GitHub
  Enterprise if possible (plan question Q-B); on Azure DevOps, see §7. Work on
  a branch and open a PR.

## 1. Usable today

Copy into the pilot repo:

```bash
cp AGENTS.md <repo>/AGENTS.md
mkdir -p <repo>/.claude && cp -R skills <repo>/.claude/skills && cp -R agents <repo>/.claude/agents
```

Then adapt, in the work repo:

1. **`AGENTS.md`**: keep the eight non-negotiables and the four coding
   principles; replace "Default stack choices" with the org's stack; in the
   routing table, substitute the model names the Copilot picker offers.
   Record every change as a DECISIONS line.
2. **Instructions attach?** Open a new Copilot chat and check the references
   list shows `AGENTS.md`. If not, the org has `chat.useAgentsMdFile` off:
   add `.github/copilot-instructions.md` containing one line, "Read AGENTS.md
   first and follow it", and record it.
3. **Skills**: `.claude/skills/` is read by Copilot as is. Type `/skills` to
   see them; the ones that matter first are task-intake, platform-flow,
   gxp-check, validation-evidence, verify, pr-prep and post-mortem.
4. **Agents**: `.claude/agents/` appears in the agent picker. Ask the
   `infra-reviewer` to change a file: it must refuse. If it does not, Claude
   tool names are ignored there; add Copilot identifiers in the same
   frontmatter (`tools: ['read', 'search']`) and record it.
5. **Scaffold** each task repo with `/task-intake`: README, DECISIONS.md,
   docs/SYSTEM.md, a plan approved before code.
6. **Walk test** in a fresh chat: "Quote non-negotiable 3 verbatim" must come
   back from `AGENTS.md`; "where does task state live" must name the tracker
   (`tools/tracker`, GitHub Issues or Azure Boards work items, with the
   `type/*` and `status/*` families).

## 2. What later plan steps add, and what to do with each at work

| Plan step | Kit piece | At work |
|---|---|---|
| 1.2–1.5 | `tools/guard` with `.claude/settings.json` and `.github/hooks/guard.json` | copy both wrappers and `tools/guard`; test: `cat .env` → ask, `git push --force` → deny, `terraform apply` → ask; the cloud agent turns `ask` into `deny`; hooks must finish under 2 s because Copilot timeouts fail open |
| 1.6 | model pins in agent frontmatter | substitute picker names; the cloud agent ignores `model:` |
| 2.2 | protected-branch hook | set the protected list in `.claude/guard.json` to the org's branches |
| 2.4–2.7 | `tracker` on GitHub Issues, label families, `label-lint.yml` | works as is on GitHub Enterprise after `gh auth login --hostname <ghe>`; on Azure DevOps through the adapter `tools/tracker/ado.py` (§7); on Jira the CLI stays read-only until an adapter exists; put the ticket key in the commit trailer meanwhile |
| 3.1 | `commit-msg` hook | `git config core.hooksPath .githooks` per clone; if the org forbids AI attribution, disable the trailer knob and record it |
| 3.2 | egress screen | in front of anything that leaves the machine; the client marker list comes from the work repo |
| 3.3 | review instructions | commit `.github/instructions/review.instructions.md`; Copilot code review on the PR follows it; the human approval stays the control |
| 3.9 | work pilot | the formal step: run the checks above, write the pilot's DECISIONS lines, demo to the team |

## 3. Org-level pieces (propose, do not do alone)

These need platform or security sign-off and are the ones an auditor counts
as controls rather than habits:

- Custom agents for every repo in the org: `agents/*.md` in the org's
  `.github-private` repository (test them under `.github/agents/` there first).
- Enterprise `copilot/managed-settings.json` in the designated
  `.github-private`: policy developers cannot override.
- A bot identity (GitHub App) for agent-authored PRs, so the author is never
  the approver.
- Rulesets on `main`: required checks, CODEOWNERS, one human approval; Copilot
  code review auto-requested.
- MCP allowlist by org policy (this kit needs no MCP server).
- On Azure DevOps: the process, group rules, denies, branch policies,
  retention and audit streaming in `docs/ADO-ADMIN.md`.

## 4. Saying it in GxP terms

- Hooks are technical controls: deterministic, tested with fixtures in CI,
  versioned by the commit in `.claude/kit-version`.
- The tracker protocol is "who may perform which transition" as code; the PR
  with green checks on the merge SHA is the evidence; `Refs #N` (or the Jira
  key) is the traceability link to the change record.
- AI review is supporting evidence. The human approval is the control.
- The evidence pack (`/validation-evidence`) is the requirement → implementation
  → test matrix with captured outputs, ready for a CSV package.

## 5. Differences to keep in mind

| Claude Code | Copilot |
|---|---|
| hook timeout = the hook's decision is lost, call blocked by default settings | timeout fails open, every event |
| `ask` prompts the user | VS Code prompts; CLI prompts; cloud agent denies |
| tool names `Bash`, `Read`, `Write`, `Edit`, `Agent` | `bash`, `view`, `create`, `edit`, `task` (guard normalizes) |
| `permissions.deny` in settings | ignored; the PreToolUse hook carries the rule |
| SessionEnd ledger, statusline | none in VS Code; use the org's Copilot usage dashboard |
| `model:` aliases (`opus`) | picker display names; ignored by the cloud agent |

## 6. First-day checklist

1. Pilot repo chosen; branch created.
2. `AGENTS.md` adapted; instructions attach in a fresh chat (or the fallback file exists).
3. `.claude/skills` and `.claude/agents` copied; `/skills` and the picker show them.
4. A read-only agent refuses to edit.
5. Walk test passes.
6. Work repo `DECISIONS.md` records: harness facts, model mapping, what was skipped and why.
7. PR opened; a teammate reviews the scaffold.

## 7. On Azure DevOps

Status 2026-11-01: plan steps A1–A5, A7 and A8 of
`docs/PLAN-2026-11-ado-port.md` are built and verified offline (unit tests
and a fake Azure DevOps REST API in `tools/tracker/tests/fake_ado.py`); no
live organisation has run them. Read every Azure DevOps behaviour below as
"verified offline; live run deferred" until the pilot records it. Azure
DevOps Services (`dev.azure.com`) only; Server is out of v1.

**Works unchanged.** `AGENTS.md`, `CLAUDE.md`, `.claude/`, and the kit's
`.github/hooks/` and `.github/instructions/` (harness files Copilot reads from
the working tree on any forge); the guard, the testguard and latest-tag hooks,
`.githooks/commit-msg`, the egress screen, `fresh-review`; the tracker's verbs
and transition table.

**Install.** `install.sh --into <repo>` picks the forge from the target's
origin (`dev.azure.com`, `ssh.dev.azure.com`, `*.visualstudio.com` → ado);
`--forge github|ado` overrides it. An Azure DevOps target gets
`azure-pipelines.yml` (init: the project owns it), `azure-pipelines-label-lint.yml`
(managed) and `docs/ADO-ADMIN.md` (init), and no `.github/workflows/` or
`.github/ISSUE_TEMPLATE/`: inactive files would read as controls.
`.claude/kit-version` records `forge: ado`.

**Pipelines.** Register both files as pipelines. `azure-pipelines.yml` runs
on `main`, so a build exists on the real merge commit that `owner done`
checks, and on every PR through a build-validation branch policy (YAML `pr:`
is ignored on Azure Repos; draft PRs do not run). Jobs: `test` (Python 3.9
and 3.13), `commit_msg` on `HEAD^1..HEAD^2`, `guards` (PR labels and title
read over REST by `tools/testguard/ado_pr_context.py`, failing closed), and
`ci`, which fails unless every needed job succeeded and leases every run that
is not a PR build. `azure-pipelines-label-lint.yml` runs nightly (UTC) with
`always: true`.

**The adapter.** `tools/tracker/ado.py` reads and writes Boards work items,
Repos PRs and Pipelines builds over REST api-version 7.1 with stdlib `urllib`.
Token: `SYSTEM_ACCESSTOKEN` in pipelines, else `az account get-access-token`
(run `az login` first; an Entra token lasts about an hour). No PAT code path;
`az boards` is never used. `tracker new` creates the Description in Markdown;
an item made in the web UI keeps HTML and is refused with the fix named
(switch its Description to Markdown, irreversible). Markers are Markdown
comments. `tracker review N --pr` takes the web URL
`https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}` or the bare
PR number. Environment:

| Variable | Read by | Meaning |
|---|---|---|
| `KZ_TRACKER_BACKEND` | tracker, label-lint, session start | `github` or `ado`; unset: the origin host decides |
| `KZ_TRACKER_REPO` | `ado.py` | `org/project/repo` (GitHub: `owner/name`); `--repo` wins; unset: the pipeline variables, else the origin URL |
| `KZ_TRACKER_AREA` | `ado.py` | area path the tracker works under (`Project\Team`); default: the project; items outside are refused |
| `KZ_TRACKER_ADO_MODE` | `ado.py`, label-lint | `tags` (default) or `process` |
| `KZ_TRACKER_ADO_TYPE` | `ado.py` | work item type; default `Task` in tags mode, `Change` in process mode |
| `KZ_TRACKER_BOTS` | `tracker owner done` | comma-separated identity GUIDs, lowercase, that never count as a human merger |
| `KZ_TRACKER_TEST_ADO` | `test_contract.py` | `org/project/repo` of a scratch project: runs the contract suite live (mode from `KZ_TRACKER_ADO_MODE`); unset: skipped |
| `SYSTEM_ACCESSTOKEN` | `ado.py`, `ado_pr_context.py`, the lease step | the job token; map it under the step's `env:` (`SYSTEM_ACCESSTOKEN: $(System.AccessToken)`), it is not exported by default |
| `SYSTEM_COLLECTIONURI`, `SYSTEM_TEAMPROJECT`, `BUILD_REPOSITORY_NAME` | `ado.py`, `ado_pr_context.py` | preset by Azure Pipelines; the repository when `KZ_TRACKER_REPO` is unset |
| `SYSTEM_PULLREQUEST_PULLREQUESTID`, `BUILD_REASON` | `ado_pr_context.py` | the PR a build validates; a PR build without an id fails closed |
| `SYSTEM_PULLREQUEST_TARGETBRANCHNAME` (else `SYSTEM_PULLREQUEST_TARGETBRANCH`) | the `guards` job, as `BASE_REF` | the PR base for the test-tampering diff; `refs/heads/` is stripped |
| `PR_LABELS`, `PR_LABELS_SET`, `PR_TITLE` | `check-test-tampering.sh` | set by `ado_pr_context.py`; `PR_LABELS_SET=1` makes an empty label list authoritative |
| `SYSTEM_DEFINITIONID`, `BUILD_BUILDID`, `BUILD_REQUESTEDFORID`, `SYSTEM_TEAMPROJECTID` | the lease step | the run to lease and its owner |

**Two status modes.** `tags` (default, no admin rights): `type/*` and
`status/*` are `System.Tags` on `Task` items; enforcement is the GitHub level
(the verbs and the nightly label-lint). `process` (recommended for client
projects; a process admin sets it up once): `status/*` is `System.State` of a
custom `Change` type and `type/*` the picklist `Custom.ChangeType`, so the
server holds exactly one status; transitions to Ready, Done and Removed are
restricted to a Change Owners group by server rules; `owner labels-sync`
refuses when a state or type value is missing; label-lint adds "state without
a matching marker". Set `KZ_TRACKER_ADO_MODE=process` wherever the tracker
runs, the label-lint pipeline's variables included.

**Required settings**, each with its reason and the REST GET that proves it
in `docs/ADO-ADMIN.md`: "Commit mention work item resolution" OFF (while on,
`Fixes #N` or any state name before `#N` in a PR description moves the item
on merge); build validation on `main`; at least one reviewer, the most recent
pusher prohibited from approving, no self-approval, votes reset on push;
comment resolution; linked work items; no-fast-forward merges only; Force
push denied; "Bypass rules on work item updates" and "Delete and restore work
items" denied for agent identities. `owner done` also refuses a PR completed
with "Complete linked work items after merging" (`transitionWorkItems`) or a
policy bypass.

**Build Service and bots.** Pipelines act as the project's Build Service
identity (limit the job authorization scope to the project). It reads PRs and
PR labels, edits work items in the area node (label-lint) and creates the
retention leases. Azure DevOps identities have no `[bot]` suffix, so put the
Build Service GUID, and any service principal's, in `KZ_TRACKER_BOTS`: in the
pipeline variables and in the shell where a human runs `owner done`.

**Copilot code review for Azure Repos** (public preview, Services): advisory.
A branch policy can request it automatically; it reads
`.github/instructions/review.instructions.md` from the target branch, always
votes Comment and never counts toward the reviewer policy. It is billed per
review in GitHub AI credits on the linked Azure subscription: set a cap and
record it in the work repo's `DECISIONS.md`. The human approval stays the
control.

**Not yet on Azure DevOps.** `evidence_export.py export` reads GitHub through
`gh`; its Azure DevOps reader and schema `/2` are plan step A6. The
session-start digest may stay silent: `az account get-access-token` plus one
REST read must fit its three-second budget, and v1 has no token cache.
