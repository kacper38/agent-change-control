# Rules and what enforces them

Updated 2026-11-23 for Phase 1 plan step 1.6 (tracker item #70).

One row per rule of `AGENTS.md`: what enforces it, or `judgment` when nothing runs and a person or a session has to
remember it. An auditor reads here which rules a check carries and which rest on someone's care. The relaxations in
force during the build are below the rules, each with its end.

Enforcers, each checked to exist by `tools/tests/test_rules_table.py`:

- `guard:NAME`: a rule of the guard (a key of `RULES` in `tools/guard/guard.py`), run before each tool call in both harnesses
- `ci:JOB`: a job of a workflow in `.github/workflows/`, run on every pull request
- `test:PATH::NAME`: a test function, run by `pytest` in the `test` job
- `hook:PATH`: a script a hook of `.claude/settings.json` runs
- `judgment`: nothing runs

The second column quotes `AGENTS.md` word for word; the test fails when the quote is no longer in the item the id
names, when `AGENTS.md` has a rule with no row, and when a named enforcer does not exist. An enforcer often covers
part of a rule; the note says which part is left to judgment. A judgment rule that is broken twice gets a check or a
dated exception (plan rev 3, row 1.6). `## Harness notes` of `AGENTS.md` has no rows: it says which harness reads
which file and holds no rule.

## Rules

| id | AGENTS.md | enforcer | note |
|---|---|---|---|
| NN-1 | Plan first. | judgment | The tracker keeps the owner's `owner ready` mark on an item's frozen body, and one plan approval per phase covers its steps (S-1); nothing checks that a step plan was shown before code. |
| NN-2 | One topic = one commit. | `ci:commit-msg`, judgment | `tools/commit_msg.py` checks the form of every commit message of a pull request: type and scope, imperative, at most 72 characters, no closing keyword. One topic per commit is judgment. |
| NN-3 | Never claim something works without evidence. | `ci:test`, `ci:guards`, `hook:tools/testguard/testguard.py`, judgment | CI runs ruff and pytest on Python 3.9 and 3.13 for every pull request; the test guard flags a weakened or removed test, in the session and in CI. Showing the output in the session is judgment. |
| NN-4 | Never bury a decision. | judgment | `tools/orchestration/assert_run.py merge-ready` fails a pull request that adds no `DECISIONS.md` line, when it is run (OR-5). Whether each trade-off and its monthly cost is named is judgment. |
| NN-5 | Regulated context. | `guard:git-guard`, `guard:protected-branch`, `guard:tracker-guard`, judgment | The audit trail rests on history nobody rewrites: the guard denies a force push, `--no-verify` and rewrites of the refs it reads, keeps edits and commits off a protected branch, and changes issues and labels only through the tracker's verbs. Naming the compliance angle in a decision is judgment. |
| NN-6.1 | secrets in a vault (Secrets Manager / Key Vault), never in code, repo, or TF state | `guard:secret-write`, `guard:secret-read`, `guard:secret-shell`, judgment | The guard stops a session writing or reading a secret file and printing a stored secret. Nothing scans committed text or Terraform state for a secret, so where a secret lives is judgment. |
| NN-6.2 | OIDC / assumed roles in CI, no long-lived keys | judgment | This repository's CI holds no cloud credential (`permissions: contents: read`). A task repository's pipeline is judgment, helped by the `infra-reviewer` agent. |
| NN-6.3 | least privilege IAM/RBAC | judgment | Helped by the `infra-reviewer` and `gxp-compliance-reviewer` agents, when asked. |
| NN-6.4 | containers: multi-stage, non-root, minimal base, healthcheck | `test:tools/box/tests/test_image.py::test_the_image_starts_as_root_only_for_its_entrypoint`, `test:tools/box/tests/test_image.py::test_bases_are_pinned_by_digest_and_tools_by_exact_version`, judgment | For the box image only: root runs its entrypoint alone and its bases are pinned by digest. A task repository's Dockerfile is judgment, helped by the `infra-reviewer` agent. |
| NN-6.5 | image tags = git SHA, never `latest` | `hook:tools/scan/latest_tag.py`, `ci:guards`, judgment | The tag scan flags `:latest` and an untagged image in a written Dockerfile, compose file or workflow, and over the tracked tree in CI. That a tag is the git SHA is judgment. |
| NN-6.6 | client data never leaves the agreed boundary | `guard:egress-guard`, `guard:cloud-launch`, judgment | Inside a client boundary the guard asks before another vendor's LLM tool or API host is called, and it denies every way a session starts cloud work, which uploads the repository. What an allowed endpoint receives is judgment. |
| NN-6.7 | the AI session is inside that boundary too | `guard:secret-read`, `guard:secret-shell`, judgment | The guard keeps a session from reading a secret file or a stored credential. What a person pastes into a session is judgment. |
| NN-6.8 | per-client isolation | `test:tools/tests/test_install.py::test_a_new_target_gets_boundary_client_and_a_second_run_changes_nothing`, judgment | A new task repository gets `boundary: client` unless `--boundary own` is given. Separate accounts, state, vaults and registries are judgment. |
| NN-6.9 | an agent installs nothing on the developer machine | `guard:host-install`, judgment | The guard asks before a package or runtime installer and a fetch-and-run on the host; it matches command text, a second line of defence and no sandbox. It is silent in a container and in CI, where installs belong. Reporting a missing dependency is judgment. |
| NN-7 | Name what's deferred. | judgment | |
| NN-8 | Wrong path → back out. | judgment | |
| CP-1 | Think before coding. | judgment | |
| CP-2 | Simplicity first. | judgment | Helped by the `ponytail-review` skill, when asked. |
| CP-3 | Surgical changes. | judgment | |
| CP-4 | Goal-driven execution. | judgment | The test guard (NN-3) flags a test weakened to make it pass. |
| WF-1 | `README.md` — goal, scope, what this does NOT do and why, how to run | judgment | The `task-intake` skill creates the three working files; nothing checks them in a task repository. |
| WF-2 | `DECISIONS.md` — running decision log (ADR-light) | judgment | See NN-4. |
| WF-3 | `docs/SYSTEM.md` — one-page system description | judgment | Kept current by hand; this repository's file has an "Updated" line per release. |
| ST-1 | Python 3.12 + FastAPI, `ruff` + `pytest` | judgment | A default; a deviation is a `DECISIONS.md` line (NN-4). The same holds for every ST row. |
| ST-2 | Next.js + TypeScript (strict) for frontends | judgment | On the host `guard:host-install` asks before `npm install`; `npm ci` in CI is judgment. |
| ST-3 | Docker multi-stage; docker-compose for local deps (db, vector store) | judgment | |
| ST-4 | GitHub Actions or Azure Pipelines (same gates): lint → test → build → push (OIDC) | judgment | |
| ST-5 | Terraform, modular | judgment | |
| ST-6 | LLM access: private endpoints (Azure OpenAI in VNet / Bedrock) for client data; pgvector as default vector store | judgment | |
| ST-7 | client-system integrations: API pull with vault-stored credentials by default | judgment | |
| ST-8 | event-driven / glue workloads: Lambda (AWS) or Azure Functions | judgment | |
| ST-9 | Observability minimum: `/health` endpoint | judgment | |
| ST-10 | FinOps floor: client/project/env cost-allocation tags on every resource | judgment | |
| MR-1 | Plans, designs, architecture | judgment | `agents/platform-planner.md` pins `fable`; the session model is the person's choice. |
| MR-2 | Code, infra, verification, review | `test:tools/tests/test_agents.py::test_model_pinned`, `test:tools/orchestration/tests/test_workflow_pins.py::test_every_agent_call_is_pinned_and_meta_is_a_literal`, judgment | The tests fail when an agent file or a workflow's `agent()` call pins no model. That the pinned tier is Opus is not checked: judgment. |
| MR-3 | Plain lookups and summaries | judgment | |
| MR-4 | Take-home-sized mechanical packets | judgment | |
| MR-5 | at most 5 agents without asking | `guard:fan-out`, `guard:workflow-launch`, judgment | The guard logs every spawn and asks when a session's total crosses 6, 16, 26, …, a workflow's agents included, and asks before a workflow that `.claude/guard.json` does not list. The brief first and no two agents with one job are judgment. |
| MR-6 | At work, substitute the names the Copilot model picker offers | judgment | |
| OR-1 | one packet = one tracker item = one branch = one pull request | judgment | `tracker review N --pr` refuses a pull request whose head is not the claimed branch or whose body lacks `Refs #N`, and `brief_lint.py` rejects a brief with an empty field; each runs only when called. |
| OR-2 | the first packet runs end to end | judgment | |
| OR-3 | a worker's result is data | judgment | Helped by `assert_run.py worker` and `assert_run.py run`, when run. |
| OR-4 | a missing result is a gap, never a pass | judgment | |
| OR-5 | before any merge, `assert_run.py merge-ready N` | `guard:tracker-guard`, judgment | On the host `gh pr merge` asks the owner and `--admin` is denied; in a box a merge runs only as `gh pr merge N --match-head-commit SHA` with a fresh-review receipt for that head. Running `merge-ready` first is judgment. |

## Judgment controls of plan rev 3, D12

Cloud work rests on these as well as on the guard's `cloud-launch`, which stops only a launch an agent issues.

| id | plan rev 3, D12 | enforcer | note |
|---|---|---|---|
| D12-1 | A person typing the command, a session started from the web or the phone, and what the vendor's connection can reach are judgment controls | judgment | `cloud-launch` denies a launch an agent issues, not one a person starts. |
| D12-2 | `/web-setup` is not used while the machine's `gh` token reaches any strict repository | judgment | |
| D12-3 | installed on open repositories only and never on a client or strict repository | judgment | The Claude GitHub App; the one exception is the scratch repository of probe 4.1, which loses it after the probe. |
| D12-4 | its `allow_remote_sessions` policy is off | judgment | Where an organisation exists; none does yet. |
| D12-5 | Auto-fix stays off while the owner's approval is a comment | judgment | |

## Relaxations during the build

The rules the owner relaxed for the build, each with its end. Section 5 of `docs/PLAN-2026-11-phase-1.md` is their
source; at delivery (its section 11), on 2026-12-31 at the latest, they end and their rows leave this file. The test
fails once a row in force is past its end. The two local switches live in files git does not track: this table names
them and cannot read them.

| id | relaxation | source | ends | state |
|---|---|---|---|---|
| P5-1 | No prompts in a box before the box profile: `bin/box` set `KZ_RULES_OFF` for `delete-guard`, `guard-config`, `scratch-md`, `fan-out` and `tracker-guard` for pull requests B and C. Ended with step 1.0b (guard 0.11.0, PR #81, merged 2026-11-21 19:02 UTC); `tools/box/box.py` no longer sets it. | Phase 1 plan, section 5, row 1 | 2026-11-21 | ended 2026-11-21 |
| P5-2 | A host session starts a box (`bin/box run NAME --brief FILE`). | Phase 1 plan, section 5, row 2 | 2026-12-31 | in force |
| P5-3 | Owner verbs once per phase: one `owner ready` line per phase plan, one `owner done` line when the phase is merged. | Phase 1 plan, section 5, row 3 | 2026-12-31 | in force |
| P5-4 | `owner done --accept-all`: one confirmation accepts every criterion of the items listed. Proposed as permanent; by its end the owner keeps it as a rule or drops it. | Phase 1 plan, section 5, row 4 | 2026-12-31 | in force |
| P5-5 | One tracker item per pull request, not per step. | Phase 1 plan, section 5, row 5 | 2026-12-31 | in force |
| P5-6 | A seat per box: one item in progress per login and seat. | Phase 1 plan, section 5, row 6 | 2026-12-31 | in force |
| L-fleet | `FLEET_VERIFY=off` under `env` in `.claude/settings.local.json` on the owner's machine: the `fleet` plugin's verifier does not ask before a script runs in this repository. | `DECISIONS.md`, 2026-11-18, the owner's act | 2026-12-31 | in force |
| L-rules-off | `rules_off` with `guard-config` and `delete-guard` in the owner's `.claude/guard.local.json`: the asks of those rules are silenced in his checkout, each logged as `skipped`; their denies stand. | `DECISIONS.md`, the `rules_off` line, since 2026-11-01 | 2026-12-31 | in force |
| S-1 | The standing word: a session merges its own pull requests on green CI and a fresh review with no open finding (not one that touches `.github/workflows/` or removes a test), one plan approval per phase covers its guard steps, and a session settles open questions inside a phase and records them. Ends by its own text when plan steps 2.1 and 2.2 are in force. | `DECISIONS.md`, 2026-11-18, the owner's standing word | 2026-12-31 | in force |
| S-2 | Delegated owner verbs: while `"owner_verbs": "delegated"` stands in `.claude/guard.json` on the default branch, a session runs `tracker delegate ready` and `tracker delegate done` in this repository (an evidence line per criterion, no box ticked), and each mark says a session acted and quotes the owner's words. It takes the place of the owner's own lines of P5-3 and P5-4, which he can still run. Ends when plan steps 2.1 and 2.2 are in force: the line then leaves `.claude/guard.json`. | `DECISIONS.md`, 2026-11-26, the owner's "go" | 2026-12-31 | in force |
