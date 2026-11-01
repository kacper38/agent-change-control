# agent-change-control

A change-control kit for **AI-assisted platform engineering in regulated
(GxP) environments**. It is a working agreement, deterministic hooks, a tracker
over GitHub Issues or Azure Boards, CI gates and an evidence export, shipped as
plain files that [Claude Code](https://claude.com/claude-code) and VS Code +
GitHub Copilot read the same way. Built for taking a service from ticket to
running, auditable infrastructure, with AI/RAG workloads as a first-class
concern.

The premise: the engineer decides, plans and verifies; the agent executes.
Every change must be defensible as validation evidence: plan first, one topic
per commit, external verification with shown output, decisions recorded.

Status 2026-11-01: the GitHub path is in daily use on this repository. The
Azure DevOps path is built and verified offline against a fake REST API; no
live organisation has run it yet. Details in [Status](#status-and-verification).

## What it is, and is not

It is:

- a working agreement, [`AGENTS.md`](AGENTS.md), that every harness loads;
- a guard hook that denies or asks before dangerous tool calls, in Claude Code
  and in Copilot, under two seconds and without network;
- one command, `tracker`, that is the only way an agent writes issues, work
  items or labels, with a transition table that says who may move what;
- CI gates (tests, commit messages, test-tampering, image tags) on GitHub
  Actions and on Azure Pipelines, with the same results;
- an evidence export that turns merged PRs, reviews, checks and tracker
  records into one JSON pack for a release.

It is not:

- an MCP server or a Claude plugin: everything is a committed file, so the
  policy version is a commit;
- an LLM judge inside hooks: every hook decision is a regular expression or a
  path rule with fixtures from both harnesses;
- a replacement for branch protection or for a human approval. The server
  settings it needs (rulesets on GitHub, branch policies and process rules on
  Azure DevOps) are documented with the API call that proves each one, not
  enforced by the kit;
- a bot identity. Until a GitHub App exists, PRs in this repository are
  authored and merged by the owner;
- support for Azure DevOps Server, Jira or Forgejo (deferred), service hooks,
  a token cache, or a dependency on GitHub Advanced Security.

Where the harness weakens a hook, the kit says so: Copilot hook timeouts fail
open, and the Copilot cloud agent turns every `ask` into `deny`.

## How a change flows

Issues are the system of record. State lives in two label families, `type/*`
and `status/*` (tags or work item states on Azure DevOps). An agent may create,
claim, block and submit for review; only a human at a terminal may promote or
close.

| State | Moved by | Verb | What is checked |
|---|---|---|---|
| backlog | agent | `tracker new` | title, acceptance criteria, scope, scope limit, source |
| ready | human | `tracker owner ready N` | definition of ready; the body is frozen from here |
| in-progress | agent | `tracker claim N --branch B` | one item in progress per actor; the branch is recorded |
| blocked | agent | `tracker block N --question "…"` | the question names a path or a field |
| review | agent | `tracker review N --pr URL` | PR head is the claimed branch; the body carries `Refs #N` |
| done | human | `tracker owner done N` | merged by a human, green checks on the merge commit, every box ticked or waived |

```
tracker new --title "…" --ac "…" --scope "…" --scope-limit "…" --source "…"
tracker owner ready N          # human only: refuses without a terminal
tracker claim N --branch B
tracker block N --question "…"
tracker review N --pr <url>
tracker owner done N
tracker list | show N | note N "…" | owner labels-sync
```

PR bodies say `Refs #N`, never `Fixes` or `Closes`: closing is the owner's
protocol, not the forge's. Before the PR, `bin/fresh-review` sends the diff to
a fresh model context and writes a receipt; the PR carries its verdict. The
`/pr-prep` skill does these steps in order.

## Install

Requirements: Python 3.9 or newer and git. On GitHub, `gh` signed in; on
Azure DevOps, the Azure CLI signed in (`az login`, Entra token, no PAT).
Claude Code, or VS Code with GitHub Copilot.

Into a task repository, for any harness:

```bash
git clone https://github.com/kacper38/agent-change-control.git
./agent-change-control/install.sh --into <your-task-repo>
```

The installer copies what [`kit.manifest`](kit.manifest) lists (`AGENTS.md`,
`CLAUDE.md`, `.claude/settings.json`, `.claude/skills/`, `.claude/agents/`,
`.github/hooks/`, `.github/instructions/`, the guard, tracker, egress and
review tools, `.githooks/commit-msg`, the CI files), keeps files the target edited locally unless `--force`, sets
`core.hooksPath` when it is unset, and writes `.claude/kit-version` with the
source commit and the forge. The forge comes from the target's origin:
`dev.azure.com` or `*.visualstudio.com` selects Azure DevOps, anything else
GitHub; `--forge github|ado` overrides it. A GitHub target gets the workflows
and issue forms; an Azure DevOps target gets `azure-pipelines.yml`,
`azure-pipelines-label-lint.yml` and `docs/ADO-ADMIN.md` instead, because
inactive files would read as controls.

Into the home account, Claude Code only (agents and skills under `~/.claude`):

```bash
./agent-change-control/install.sh      # backs up anything it would overwrite
cd <your-task-repo> && claude
/task-intake                           # paste the task; the rest follows
```

`./install.sh --uninstall` removes exactly what the manifest lists; backups
stay in `~/.claude/backups/`. Where the installer may not run, copy by hand:

```bash
cp AGENTS.md <repo>/AGENTS.md && printf '@AGENTS.md\n' > <repo>/CLAUDE.md
mkdir -p <repo>/.claude && cp -R skills <repo>/.claude/skills && cp -R agents <repo>/.claude/agents
```

On a work machine with VS Code + GitHub Copilot, follow
[`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md); its §7 covers Azure DevOps
and [`docs/ADO-ADMIN.md`](docs/ADO-ADMIN.md) is the project administrator's
checklist.

## What is enforced where

On the laptop, before a tool call runs:

- `tools/guard/guard.py` (PreToolUse in Claude Code through
  `.claude/settings.json`, in Copilot through `.github/hooks/guard.json`):
  asks before secret files are read or anything deploys; denies force-push and
  protected-branch commits, `gh issue …`, `gh label …`, `az boards work-item`
  writes, `az devops invoke`, any `bypassRules` and raw API writes; counts
  subagent spawns. Every rule ships with allow, ask, deny and crash fixtures
  from both harnesses.
- `.githooks/commit-msg`: `type(scope): imperative subject`, no closing keywords.
- `tools/egress/egress_screen.py`: the last check before anything leaves the
  machine (secrets, gitleaks, client markers, size, the client boundary); held
  items are listed and never dropped.

In the tracker, on every write: all guards first, then one comment, then one
label change (add the new status, then remove its siblings, so a crash leaves
two labels rather than none). Owner verbs refuse without a TTY. Items outside
the configured repository or area path are refused.

On the server and in CI:

- GitHub: a ruleset on `main` with the required check `ci`; the `ci.yml`
  workflow runs tests on Python 3.9 and 3.13, the commit-msg check over the PR
  range and the guards (test tampering, image tags); `label-lint.yml` reports
  label mistakes on issue events and nightly, as a comment plus one tracking
  issue, and never edits.
- Azure DevOps: `azure-pipelines.yml` runs the same gates on `main` and, through
  a build-validation branch policy, on every PR, and leases every run that is
  not a PR build so the logs of `main` outlive retention;
  `azure-pipelines-label-lint.yml` runs nightly. Branch policies, denies for
  agent identities and the optional process rules are listed in
  [`docs/ADO-ADMIN.md`](docs/ADO-ADMIN.md).

## Status and verification

- This repository dogfoods the kit: every change goes through the tracker, the
  hooks, CI and a `fresh-review` receipt, and every trade-off is a line in
  [`DECISIONS.md`](DECISIONS.md).
- GitHub path: the steps of [`docs/PLAN-2026-10-mature-setup.md`](docs/PLAN-2026-10-mature-setup.md)
  up to the evidence export are merged and in use. Waiting for the owner: the
  bot identity for agent sessions and the work pilot.
- Azure DevOps path: steps A1 to A8 of [`docs/PLAN-2026-11-ado-port.md`](docs/PLAN-2026-11-ado-port.md)
  are merged. They were verified against unit tests and a fake Azure DevOps
  REST API only; the first live run (step A0 on a scratch organisation, then
  the pilot A9) settles the response shapes, the branch ACL token and whether
  the session-start digest fits its time budget.
- Tests: `uv run --no-project --with pytest python -m pytest -o addopts= -q`
  (add `--python /usr/bin/python3` for 3.9); lint: `uvx ruff check .`.

## Reference

### Tracker

`tools/tracker/tracker.py` is the only writer of issues and labels an agent
uses. The backend follows the origin; `KZ_TRACKER_BACKEND=github|ado`
overrides it. On GitHub it goes through `gh`; issue forms under
`.github/ISSUE_TEMPLATE/` carry the definition-of-ready fields. On Azure
DevOps, `tools/tracker/ado.py` keeps the same verbs over the REST API with an
Entra token: issues are work items of one type under one area path, labels
are tags (`tags` mode, the default) or, in `process` mode, the `System.State`
of a custom `Change` type with server-side transition rules. Environment
variables (`KZ_TRACKER_REPO`, `KZ_TRACKER_AREA`, `KZ_TRACKER_ADO_MODE`,
`KZ_TRACKER_BOTS` and the pipeline ones) are tabled in
[`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md) §7.

### Guards

- `tools/guard/guard.py` takes its knobs from the committed `.claude/guard.json`
  (`protected_branches`, `boundary`, `scratch_md_mode`, telemetry dir). A
  gitignored `.claude/guard.local.json` beside it (its `rules_off` list,
  nothing else is read) silences the named rules' asks for one checkout,
  `KZ_RULES_OFF=rule,rule` for one shell; denies stand, and both count only
  under a repo root whose committed file says `"boundary": "own"` itself, so
  a client repo's policy is the committed file alone. A silenced ask is logged
  as `skipped` in the decision log. Gitignore the local file in a task repo
  yourself: the installer never edits `.gitignore`.
- `tools/testguard/check-test-tampering.sh` (the harness kit's guard plus
  pytest rules): deleted or renamed test files, a `def test_` that disappears,
  added skip/focus markers, `[skip ci]` in commits or the PR title. The
  PostToolUse wrapper `testguard.py hook` runs it against the working tree
  whenever a tool touches a test file; the CI job `guards` runs it against the
  PR base. A removal passes only with the human-applied `test-removal-ok` PR label.
- `tools/scan/latest_tag.py`: `:latest` or untagged image references in
  Dockerfiles, compose files, workflows and `azure-pipelines*.yml` (digests,
  build stages and `scratch` pass). `hook` judges the file just written;
  `scan [PATH...]` walks the tracked tree in CI, exit 1 on findings.

### Review and egress

- `bin/fresh-review` sends `origin/main...HEAD` (through the egress screen) to a
  fresh Opus context with `tools/review/prompt.md` and writes a receipt to
  `.git/fresh-review/<sha>.json`; `/pr-prep` pastes the verdict. At work the
  same prompt is `.github/instructions/review.instructions.md` for Copilot code
  review, on GitHub and on Azure Repos.
- `tools/egress/egress_screen.py --target <name> [--pass] [files]`: exit 3 with
  the held items listed when anything must not leave.

### Evidence pack

- `tools/tracker/evidence_export.py capture --tag T --name N -- <command>` keeps
  a check's output verbatim under `evidence/T/` with its sha256, size, exit code
  and tool version.
- `evidence_export.py export --tag T --from <ref> --to <ref>` writes
  `change-records.json` (schema `agent-change-control/change-records/2` on both
  forges): PRs merged in the git range with merge SHAs, reviews or votes, check
  runs or builds and policy evaluations, completion options; the issues or work
  items they reference or that closed in the window, with tracker markers,
  acceptance boxes and revisions; rulesets or branch policies; the captures
  re-hashed; tool versions. A section a forge lacks is null.
  `/validation-evidence` runs both.

### Agents

Process and compliance core:

| Agent | Role |
|---|---|
| `platform-planner` | Plan before code: assumptions, questions, steps with a verification command each, trade-offs, cut line |
| `infra-reviewer` | Dockerfile / GitHub Actions / Azure Pipelines / Terraform / compose review: correctness and best practices |
| `gxp-compliance-reviewer` | Same artifacts through a GAMP 5 auditor's lens: audit trail, ALCOA+, validation evidence |
| `rag-infra-advisor` | AI-infra decisions: vector store, private LLM endpoints, model+prompt+index versioning, eval in CI, cost, data residency |

Execution bench:

| Agent | Role |
|---|---|
| `python-engineer` | Production Python: FastAPI, CLIs, automation; uv + ruff + mypy + pytest |
| `node-engineer` | Production TypeScript: Next.js frontends, zod at boundaries; npm ci + tsc + vitest |
| `shell-engineer` | Bash that survives production: `set -euo pipefail`, quoting, shellcheck, traps, and knows when to switch to Python |
| `k8s-engineer` | Manifests (probes, limits, securityContext), Kustomize/Helm, pod-debugging runbook, EKS/AKS, GitOps |
| `git-surgeon` | Conflicts, reflog recovery, bisect, history surgery behind a backup branch; signed commits as audit trail |
| `observability-engineer` | Prometheus/Grafana as code, symptom-based alerting, SLOs, correlation ids, LLM cost metrics |
| `postgres-engineer` | Non-blocking migrations, EXPLAIN/indexing, restore-tested backups, RLS, pgvector tuning |
| `code-reviewer` | General code review: correctness, security, maintainability |

Reviewer and planner agents have no Edit or Write tools; a test asserts it.
Models are pinned per task class in the agent frontmatter (see the routing
table in `AGENTS.md`).

### Skills

Task lifecycle:

| Skill | When |
|---|---|
| `/task-intake` | New task/ticket: assumptions, questions, scaffolding (README, DECISIONS.md, AGENTS.md), approved plan |
| `/platform-flow` | The chain: local dev, Docker, CI, Terraform, CD, observability, security |
| `/rag-stack` | RAG component: pgvector, traceability-first schema, idempotent ingestion, private endpoints, eval + cost hooks |
| `/data-pipeline` | Data feed/ETL: source contract + quarantine, idempotent load, lineage row per run, quality gates, scheduled job |
| `/gxp-check` | Before significant commits: secrets/tags/IAM/vuln-scan/pipeline-lineage sweep mapped to GxP vocabulary |
| `/validation-evidence` | Before release/handoff: evidence pack with requirement to implementation to test matrix, captured outputs, change trail |
| `/post-mortem` | After an incident: blameless write-up with owners and a validation note |

General support: `verify`, `code-review`, `pr-prep`, `systematic-debugging`,
`verification-before-completion`.

Anti-over-engineering (the lazy family):

| Skill | When |
|---|---|
| `/ponytail` | Lazy mode for the whole session: the YAGNI, stdlib, native, installed-dep, one-line ladder (`lite\|full\|ultra`) |
| `/ponytail-review` | Review the current diff for things to DELETE: reinvented stdlib, unneeded deps, speculative abstractions |
| `/ponytail-audit` | Same lens over the whole repo, ranked by removable lines/deps |
| `/ponytail-debt` | Harvest `ponytail:` markers into a debt ledger with upgrade triggers |

### Memory and ledger (Claude Code, home machine only)

- `tools/memory/memstore.py init` puts `~/.claude/projects/*/memory/**` under a
  bare repo (`~/.claude/memory-store.git`); the PostToolUse hook commits every
  memory write and validates the frontmatter (`type`, `status`, `stale_after`
  for project/reference facts, `verified_on`). `index --write` rebuilds
  `MEMORY.md`, `triage` lists stale or unverified files, `deprecate` retires one.
  Push stays off until a private remote exists and `KZ_MEMORY_PUSH` names the projects.
- `tools/telemetry/ledger.py hook` (SessionEnd) writes one line per session id with
  per-model tokens and cost, subagent share and spawns; `ledger.py cost --days 7`
  prints the week per project and model plus hook prompts per guard rule.
  Prices live in `tools/telemetry/prices.json` (dated; unknown tiers stay `null`).
- Nothing from here is installed at work: no memory, telemetry, tokens or
  transcripts cross the boundary.

### Working agreement

[`AGENTS.md`](AGENTS.md): eight non-negotiables (plan first, small steps,
evidence over claims, DECISIONS.md, regulated context, security reflexes,
named gaps, back out of bad paths), the four Karpathy coding principles
(think before coding, simplicity first, surgical changes, goal-driven
execution, adapted from
[andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills)),
the model-routing table and notes on which harness reads what. `CLAUDE.md`
is the one line `@AGENTS.md`, so Claude Code loads the same file that GitHub
Copilot, Codex and Gemini CLI read directly. `/task-intake` copies both into
the task repo, so the principles are always active where you work.

### Documents

| File | What it is |
|---|---|
| [`AGENTS.md`](AGENTS.md) | the working agreement, canonical |
| [`DECISIONS.md`](DECISIONS.md) | every trade-off, one line each, newest block last |
| [`docs/SYSTEM.md`](docs/SYSTEM.md) | one-page system description, kept current |
| [`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md) | VS Code + Copilot at work; §7 Azure DevOps |
| [`docs/ADO-ADMIN.md`](docs/ADO-ADMIN.md) | Azure DevOps administrator checklist with the proving API calls |
| [`docs/PLAN-2026-10-mature-setup.md`](docs/PLAN-2026-10-mature-setup.md) | the plan behind the GitHub path |
| [`docs/PLAN-2026-11-ado-port.md`](docs/PLAN-2026-11-ado-port.md) | the plan behind the Azure DevOps port |
| [`kit.manifest`](kit.manifest) | what the installer copies, per forge |
| [`setup-overview.html`](setup-overview.html), [`tech-primer.html`](tech-primer.html) | non-normative overview (Polish) and study guide; the `.md` files are the authority |

## License

MIT
