# agent-change-control

A change-control kit for **AI-assisted platform engineering in regulated
(GxP) environments**: a working agreement, deterministic hooks, a tracker on
GitHub Issues or Azure Boards and an evidence export, shipped as plain files that
[Claude Code](https://claude.com/claude-code) and VS Code + GitHub Copilot
read the same way. Built for taking a service from ticket to running,
auditable infrastructure, with AI/RAG workloads as a first-class concern.

The premise: the engineer decides, plans, and verifies; the agent executes.
Every change must be defensible as validation evidence — plan first, one topic
per commit, external verification with shown output, decisions recorded.

## Install

Into a task repository, for any harness:

```bash
git clone https://github.com/kacper38/agent-change-control.git
./agent-change-control/install.sh --into <your-task-repo>
                                       # copies what kit.manifest lists,
                                       # writes .claude/kit-version
                                       # forge from the origin; override
                                       # with --forge github|ado
```

An Azure DevOps target gets `azure-pipelines.yml`, `azure-pipelines-label-lint.yml`
and `docs/ADO-ADMIN.md` instead of the GitHub workflows and issue forms; see
[`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md) §7.

Into the home account, Claude Code only (agents and skills under `~/.claude`):

```bash
./agent-change-control/install.sh      # backs up anything it would overwrite,
                                       # writes an uninstall manifest
cd <your-task-repo> && claude
/task-intake                           # paste the task — the rest follows
```

Remove the home install cleanly with `./install.sh --uninstall` (deletes
exactly what the manifest lists; backups stay in `~/.claude/backups/`).

## Agents

Process & compliance core:

| Agent | Role |
|---|---|
| `platform-planner` | Plan before code: assumptions, questions, steps with a verification command each, trade-offs, cut line |
| `infra-reviewer` | Dockerfile / GitHub Actions / Azure Pipelines / Terraform / compose review — correctness and best practices |
| `gxp-compliance-reviewer` | Same artifacts through a GAMP 5 auditor's lens: audit trail, ALCOA+, validation evidence |
| `rag-infra-advisor` | AI-infra decisions: vector store, private LLM endpoints, model+prompt+index versioning, eval in CI, cost, data residency |

Execution bench:

| Agent | Role |
|---|---|
| `python-engineer` | Production Python: FastAPI, CLIs, automation; uv + ruff + mypy + pytest |
| `node-engineer` | Production TypeScript: Next.js frontends, zod at boundaries; npm ci + tsc + vitest |
| `shell-engineer` | Bash that survives production: `set -euo pipefail`, quoting, shellcheck, traps — and knows when to switch to Python |
| `k8s-engineer` | Manifests (probes, limits, securityContext), Kustomize/Helm, pod-debugging runbook, EKS/AKS, GitOps |
| `git-surgeon` | Conflicts, reflog recovery, bisect, history surgery behind a backup branch; signed commits as audit trail |
| `observability-engineer` | Prometheus/Grafana as code, symptom-based alerting, SLOs, correlation ids, LLM cost metrics |
| `postgres-engineer` | Non-blocking migrations, EXPLAIN/indexing, restore-tested backups, RLS, pgvector tuning |
| `code-reviewer` | General code review: correctness, security, maintainability |

## Skills — task lifecycle

| Skill | When |
|---|---|
| `/task-intake` | New task/ticket → assumptions, questions, scaffolding (README, DECISIONS.md, AGENTS.md), approved plan |
| `/platform-flow` | The chain: local dev → Docker → CI → Terraform → CD → observability → security |
| `/rag-stack` | RAG component: pgvector, traceability-first schema, idempotent ingestion, private endpoints, eval + cost hooks |
| `/data-pipeline` | Data feed/ETL: source contract + quarantine, idempotent load, lineage row per run, quality gates, scheduled job |
| `/gxp-check` | Before significant commits — secrets/tags/IAM/vuln-scan/pipeline-lineage sweep mapped to GxP vocabulary |
| `/validation-evidence` | Before release/handoff — evidence pack: requirement→implementation→test matrix, captured outputs, change trail |
| `/post-mortem` | After an incident — blameless write-up with owners and a validation note |

Plus general support: `verify`, `code-review`, `pr-prep`, `systematic-debugging`,
`verification-before-completion`.

Anti-over-engineering (the lazy family):

| Skill | When |
|---|---|
| `/ponytail` | Lazy mode for the whole session — the YAGNI → stdlib → native → installed-dep → one-line ladder (`lite\|full\|ultra`) |
| `/ponytail-review` | Review the current diff for things to DELETE: reinvented stdlib, unneeded deps, speculative abstractions |
| `/ponytail-audit` | Same lens over the whole repo — ranked by removable lines/deps |
| `/ponytail-debt` | Harvest `ponytail:` markers into a debt ledger with upgrade triggers |

## Tracker — GitHub Issues or Azure Boards as the system of record

`tools/tracker/tracker.py` is the only writer of issues and labels an agent uses
(the `tracker-guard` hook denies `gh issue …`, `gh label …`, `az boards work-item`
writes, `az devops invoke`, any `bypassRules` and raw API writes).
State lives in two label families, `type/*` and `status/*`, with a transition
table that says who may move what:

```
tracker new --title "…" --ac "…" --scope "…" --scope-limit "…" --source "…"   # agent: lands in status/backlog
tracker owner ready N          # human at a terminal: definition of ready, freezes the body
tracker claim N                # agent: ready -> in-progress, one per actor, records the branch
tracker block N --question "…" # agent: in-progress -> blocked, question must name a path or field
tracker review N --pr <url>    # agent: in-progress -> review; PR head = claimed branch, body has `Refs #N`
tracker owner done N           # human: merged PR, green checks on the merge SHA, every box ticked or waived
tracker list | show N | note N "…" | owner labels-sync
```

Owner verbs refuse without a TTY, so an agent cannot promote or close. The
`label-lint` workflow reports label mistakes (comment + one tracking issue) and
never edits them. Issue forms under `.github/ISSUE_TEMPLATE/` carry the
definition-of-ready fields.

The backend follows the origin (`KZ_TRACKER_BACKEND=github|ado` overrides it).
On Azure DevOps, `tools/tracker/ado.py` keeps the same verbs over the REST API
with an Entra token (no PAT): issues are work items under one area path,
labels are tags (`tags` mode, the default) or, in `process` mode, the
`System.State` of a custom `Change` type with server-side transition rules.
label-lint runs as the nightly `azure-pipelines-label-lint.yml`. Verified
offline against a fake API; live run deferred. Settings and env vars:
[`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md) §7 and
[`docs/ADO-ADMIN.md`](docs/ADO-ADMIN.md).

## Review and egress

- `bin/fresh-review` sends `origin/main...HEAD` (through the egress screen) to a
  fresh Opus context with `tools/review/prompt.md` and writes a receipt to
  `.git/fresh-review/<sha>.json`; `/pr-prep` pastes the verdict. At work the
  same prompt is `.github/instructions/review.instructions.md` for Copilot code review.
- `tools/egress/egress_screen.py --target <name> [--pass] [files]` is the last
  check before anything leaves the machine: secrets, gitleaks, client markers,
  size, and the client boundary. Held items are listed, counted and never dropped (exit 3).
- `.githooks/commit-msg` (`core.hooksPath`, set by the installer) enforces
  `type(scope): imperative subject`, no closing keywords; CI re-checks the PR range.
- On Azure DevOps, `azure-pipelines.yml` runs the same gates (test, commit-msg,
  guards, aggregated by `ci`) on `main` and, through a build-validation branch
  policy, on every PR; it leases every run that is not a PR build, so the logs
  of `main` outlive the retention period.

## Guards (hook feedback now, CI red later)

- `tools/guard/guard.py` (PreToolUse, both harnesses) takes its knobs from the committed
  `.claude/guard.json`; a gitignored `.claude/guard.local.json` beside it (its `rules_off` list,
  nothing else is read) silences the named rules' asks for one checkout, `KZ_RULES_OFF=rule,rule`
  for one shell; denies stand, and both count only under a repo root whose committed file says
  `"boundary": "own"` itself, so a client repo's policy is the committed file alone. A silenced
  ask is logged as `skipped` in the decision log. Gitignore the local file in a task repo yourself:
  the installer never edits `.gitignore`.
- `tools/testguard/check-test-tampering.sh` (the harness kit's guard plus pytest rules):
  deleted or renamed test files, a `def test_` that disappears, added skip/focus
  markers, `[skip ci]` in commits or the PR title. The PostToolUse wrapper
  `testguard.py hook` runs it against the working tree whenever a tool touches a
  test file; the CI job `guards` runs it against the PR base. A removal passes only
  with the human-applied `test-removal-ok` PR label.
- `tools/scan/latest_tag.py`: `:latest` or untagged image references in Dockerfiles,
  compose files, workflows and `azure-pipelines*.yml` (digests, build stages and `scratch` pass). `hook` judges
  the file just written; `scan [PATH...]` walks the tracked tree in CI, exit 1 on findings.

## Evidence pack

- `tools/tracker/evidence_export.py capture --tag T --name N -- <command>` keeps a check's
  output verbatim under `evidence/T/` with its sha256, size, exit code and tool version.
- `evidence_export.py export --tag T --from <ref> --to <ref>` writes `change-records.json`
  from `gh api`: PRs merged in the git range (merge SHAs, reviews, check runs), the
  issues they reference or that closed in the window (tracker markers, acceptance boxes),
  rulesets, the captures re-hashed, tool versions. `/validation-evidence` runs both.
- On Azure DevOps, `capture` works as is and `export` reads the forge the origin names
  (schema `agent-change-control/change-records/2` on both forges: completed PRs, votes,
  builds and policy evaluations, completion options, work item revisions, policy
  configurations, retention; a section a forge lacks is null, the branch ACL on both
  for now). Verified against a fake Azure DevOps API only; the first live run is plan
  step A0 (`docs/PLAN-2026-11-ado-port.md`).

## Memory and ledger (Claude Code, home machine)

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

## Working agreement

[`AGENTS.md`](AGENTS.md) — eight non-negotiables (plan first, small steps,
evidence over claims, DECISIONS.md, regulated context, security reflexes,
named gaps, back out of bad paths), the four Karpathy coding principles
(think before coding, simplicity first, surgical changes, goal-driven
execution — adapted from
[andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills)),
the model-routing table and notes on which harness reads what. `CLAUDE.md`
is the one line `@AGENTS.md`, so Claude Code loads the same file that GitHub
Copilot, Codex and Gemini CLI read directly. `/task-intake` copies both into
the task repo, so the principles are always active where you work.

Decisions live in [`DECISIONS.md`](DECISIONS.md); the one-page system
description in [`docs/SYSTEM.md`](docs/SYSTEM.md); the current plan in
[`docs/PLAN-2026-10-mature-setup.md`](docs/PLAN-2026-10-mature-setup.md), the Azure
DevOps port in [`docs/PLAN-2026-11-ado-port.md`](docs/PLAN-2026-11-ado-port.md).

A one-page visual overview lives in
[`setup-overview.html`](setup-overview.html) (Polish). A non-normative study
guide for the target role's tech stack (with a personal CV gap map) lives in
[`tech-primer.html`](tech-primer.html) — the `.md` files are the authority.

## Install into a repo (the kit)

The kit is the set of repo-level files that Claude Code **and** VS Code +
GitHub Copilot read the same way: `AGENTS.md`, `.claude/settings.json`
(hooks), `.claude/skills/`, `.claude/agents/`, `.github/hooks/`,
`tools/guard`, `tools/tracker` and the rest of `kit.manifest`.
`install.sh --into <repo>` copies them, keeps files the target edited
locally (unless `--force`) and writes `.claude/kit-version` with the source
commit and the forge (`--forge github|ado`, default: from the origin; entries
marked `@github` or `@ado` in `kit.manifest` go to that forge only). Where the
installer may not run, copy by hand:

```bash
cp AGENTS.md <repo>/AGENTS.md && printf '@AGENTS.md\n' > <repo>/CLAUDE.md
mkdir -p <repo>/.claude && cp -R skills <repo>/.claude/skills && cp -R agents <repo>/.claude/agents
```

Using it on a work machine with VS Code + GitHub Copilot:
[`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md).

## License

MIT
