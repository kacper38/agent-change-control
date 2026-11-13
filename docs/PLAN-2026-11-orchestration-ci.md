# Plan — one orchestrating session, worker agents and sub-workers, compatible with GitHub CI, shipped through the kit

Status: APPROVED rev 2 by Kacper on 2026-11-13 ("yeah i approve plan"). Rev 2 records his answers to Q1 (a subscription token in CI for now, the lower-cost route), Q2 (a GitHub App as the agent identity) and Q8 (the Gemini plan review is dropped for now). Q3–Q7 run on their defaults. No step is implemented yet.
Method: the talk "Rethinking Claude Code Best Practices" (Lydia Hallie, AI Engineer; read through the event page, no transcript); ten official Claude Code doc pages; the source and docs of `anthropics/claude-code-action`; one research workflow (four lanes with distinct jobs plus one batched verifier: 71 findings, the 20 most decision-relevant checked against primary sources → 16 confirmed, 3 corrected, 1 unverifiable; 33 flagged findings were left unverified by the cap); three probes in a scratch project on Claude Code 2.1.323.

Every fact below carries its evidence class, so a later reader knows what to re-check first:

| Class | Meaning |
|---|---|
| **T** | tested here on 2026-11-13, Claude Code 2.1.323 |
| **V** | confirmed against a primary source by the separate verifier |
| **D** | read in primary docs or source, not independently verified |
| **R** | third-party report (issue, blog, another repo); treat as a lead |
| **I** | my inference from the facts above; needs a probe |

## 0. What the request means (two readings, both in scope)

1. **Orchestrated work flows through CI.** One session plans and splits the work; each worker produces a branch and a pull request; the same `ci` check runs on every PR however the session was configured; a person approves. This is the talk's model.
2. **The orchestration itself runs headless in CI.** A saved workflow is started by `claude -p` or the GitHub Action inside a job.

Phases 1 and 2 deliver reading 1 and the read-only part of reading 2 (review). An agent that writes code from inside CI is below the cut line (section 8).

What this plan does NOT do: it does not adopt Projects, cloud sessions, Code Review, routines or agent teams (section 2, facts 11–12); it does not make any model review a merge gate; it does not port the CI jobs to Azure Pipelines yet.

## 1. What the kit already has (the plan is a gap list)

| Capability | Today | Gap |
|---|---|---|
| Model routing | Fable or Opus pinned in all 12 agents; `tools/tests/test_agents.py` enforces it | workflow stages have no pin and no test |
| Fan-out control | `guard` logs every spawn on `SubagentStart` and asks at the 6th `Agent`/`Task` spawn | workflow agents are logged (5 rows today, `model: null`) but never reach the ask, because they do not pass through `Agent` (**T**). The `revisit if: Workflow agents bypass it` trigger in `DECISIONS.md` has fired |
| Guard hook placement | `PreToolUse` in `.claude/settings.json`, which is the place that works inside subagents and workflow agents (**T**, **V**) | timeout 5 s and no `onFailure: "block"`, so a timeout fails open (**D**); the `Workflow` tool is not in the matcher |
| Independent review | `bin/fresh-review`: one `claude -p` call, no tools, egress-screened, receipt, advisory | local only; single lens; no CI job |
| CI | `ci.yml`: lint, tests, guards, one aggregate check; ruleset requires `ci`, approvals 0 | no check that an agent-authored PR had a human approval; no Claude step |
| Procedure | skills for intake, flow, PR prep, evidence | no orchestration procedure, no brief template |
| Saved workflows | none | — |
| Copilot | shared hooks and agents | nothing written down about subagents there |

## 2. Verified facts that shape the design (surprises first)

1. **A workflow is flat.** Agents started by a workflow script have no spawn tool, for the default agent type and for `general-purpose` (**T**, from the agents' own tool lists). The script may call one child workflow, one level deep (**D**). Real nesting exists only through the `Agent` tool.
2. **A CI job can go green having done nothing.** `claude-code-action` stops reading at the first result message while background subagents are still running; action issues #1499, #1852 and #1646 are open with no maintainer reply (**V**). The community mitigation is `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` (**V** that it is documented and reported to work; one report says it must go through the action's `settings` input because a step-level `env:` did not reach the CLI, **R**).
3. **The exit code does not report a denial.** A saved workflow that was denied at launch still exits `0` with `subtype: success`; the denial appears only in `permission_denials` of the JSON output (**T**). Inside a workflow, a failed agent resolves to `null` rather than failing the run (**D**).
4. **Starting a saved workflow by name works headless.** `claude -p "/<name>" --permission-mode dontAsk --allowedTools "Workflow(<name>)"` runs `.claude/workflows/<name>.js`; without the rule the launch is denied (**T**). GitHub's own `gh-aw` does the same with a bare `Workflow` rule and keeps the feature off by default (**V**); 3 of its last 8 smoke runs failed, cause not established (**V** for the count).
5. **Settings hooks fire where they must.** A `PreToolUse` hook from project `.claude/settings.json` ran inside a workflow agent (`agent_type: workflow-subagent`) and its exit 2 blocked the call (**T**); the docs say the same for subagents (**V**). Hooks in agent frontmatter are skipped in `-p` runs (**V**), and issues report them not firing in other paths (**R**).
6. **Hooks fail open on timeout unless told otherwise.** `onFailure: "block"` makes a timeout or crash block the call; it needs 2.1.295 or later (**D**). Copilot has no equivalent: its hook timeouts always fail open (**V**).
7. **On a pull request, the action restores `.claude/` from the base branch but leaves the rest at PR head** (**D**). The kit's hook command is `python3 "$CLAUDE_PROJECT_DIR"/tools/guard/guard.py`, a repo-relative script, so in a PR-triggered job the PR supplies the guard (**I**). Structural controls have to carry such a job; the hook is a second line.
8. **Nesting depth is a moving default.** Off in 2.1.217–2.1.218, three layers from 2.1.219 (**V**). One hardening repo says the default arrives by remote flag and pins it (**R**). `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` pins it (**D**).
9. **`--max-budget-usd` is the only hard spend cap.** It stops background subagents too (**V**). The 200-spawns-per-session cap was removed in 2.1.224 (**V**). Users report runaway workflow runs, one of about $606 (**R**).
10. **The action defaults to auto permission mode**, which its own docs call "a review, not a boundary" (**D**). A strict allowlist needs an explicit `--permission-mode`. Plain `claude -p` starts in Manual mode since 2.1.302 (**D**). `--bare` skips hooks and is announced as the future default for `-p` (**D**), so flags must be explicit.
11. **Agent teams do not run headless**: no teammates are spawned in `-p` or SDK sessions (**D**).
12. **Cloud features leave the boundary.** Projects, Code Review, ultrareview, routines and PR auto-fix run on Anthropic infrastructure and are unavailable on Bedrock or Foundry; self-hosted environments still send the transcript to Anthropic (**D**). The in-boundary path is the action or `claude -p` on our own runner with Bedrock or Foundry through OIDC.
13. **`agent-approval-check` detects agent work by committer e-mail or PR creator login, not by the `Co-Authored-By` trailer**, and the PR author's `/approve <head-sha>` comment counts as one approval (**D**, source read 2026-11-13). Local sessions commit under the owner's identity, so today the check would report "no agent activity" (**I**).
14. **Copilot limits.** VS Code subagents do not nest unless `chat.subagents.allowInvocationsFromSubagents` is on, depth at most five; the harness that supports nesting and handoffs is deprecated with removal announced for February 2027; a worker model above the main model's cost tier does not run; the cloud agent ignores handoffs (**V**). No dynamic workflows exist there.
15. **What the docs now say to stop doing**: using subagents to protect context or to get a better answer, emphasis in capitals, "keep going" prompts, describing the file layout in the instructions file (**D**). The cost guardrails already in use (brief first, distinct lenses, five agents) match this.

## 3. Design decisions (recommendation; the alternative is named)

**D1 — Three levels, depth pinned at two.**
- Level 0, the orchestrator: the interactive session on Fable. It plans, writes the brief, splits the work into packets (one packet = one tracker item = one branch = one PR) and reads results. It does not merge.
- Level 1, workers: the Opus engineer agents, one packet each, each in its own worktree. A worker returns a structured result: branch, checks run with exit codes, open risks.
- Level 2, sub-workers: read-only helpers a worker may start (a search, one verifier). They never write.
- Alternative: keep the default depth of three. Rejected: each layer multiplies tokens and nobody reads level-3 output.

**D2 — The shape follows the job.**

| Job | Mechanism |
|---|---|
| up to five packets, a person present | `Agent` fan-out from the session, with a written brief |
| repeatable, or headless | a saved workflow; it is flat, so its verify stage replaces level 2 |
| many PRs over days, non-client repo | Projects, by hand, outside the kit |
| client repo, any size | never a cloud feature; own runner with Bedrock or Foundry |

**D3 — Stage gates are separate runs.** A workflow takes no input mid-run, so each stage is its own run and the human decision sits between them in the tracker or the PR: plan → approval → implement → `ci` → review → approval → merge.

**D4 — One contract for every headless Claude job** (the consequence of facts 2, 3, 9 and 10):
1. explicit `--permission-mode dontAsk` with narrow allow rules, including `Workflow(<name>)` for exactly the workflows the job may start. Alternative: auto mode plus an egress-firewall runner, which is what `anthropics/claude-code` enforces in its own CI (**R**); rejected here because an allowlist is deterministic and auditable.
2. `--max-budget-usd`, `--max-turns` as a runaway backstop, a job timeout and a concurrency group.
3. background tasks disabled through the `settings` input.
4. `--json-schema` output, and a deterministic post-step that fails the job on missing structured output, a non-empty `permission_denials`, a `null` stage result or outstanding background tasks. The exit code is not evidence.
5. a read-only job token for review jobs and the action pinned to a commit SHA. Model access through OIDC with no stored key is the target, and the rule for client repos; own repos use a subscription token for now (Q1).
6. a receipt (verdict, head SHA, model, cost, versions) uploaded with an explicit retention.

**D5 — Model review in CI stays advisory and scales with risk.** The single-call `fresh-review` remains the default (existing decision). A panel workflow (the three existing reviewer agents as lenses plus one batched verifier, four agents) runs only on a label. The gates are `ci` and the human approval. Alternative: panel on every PR; rejected on cost (section 11) and on the existing $20-a-month trigger.

**D6 — The human approval becomes a required check.** `agent-approval-check` with `required_approvals: 1`: on a solo repo the owner's `/approve <head-sha>` is a recorded approval bound to the exact commit. Agent commits are detectable because agent sessions commit and push as a GitHub App (Q2).

**D7 — The guard learns about workflows.** `Workflow` joins the `PreToolUse` matcher: the launch is logged; a name listed in `.claude/guard.json` is allowed; an inline script or an unknown name gets `ask` (which is a denial in a `dontAsk` job). Workflow agents count toward the fan-out total. `.claude/workflows/**` joins the paths where an edit asks. The guard hook gets `onFailure: "block"`.

**D8 — Assumptions are data with a probe, not prose.** `tools/orchestration/probe.py` re-runs the canaries behind every **T** fact against the installed CLI and writes the result with version and date. The kit repo runs it when the CLI version moves; task repos inherit the result through the kit version. Section 12 lists the triggers.

**D9 — Distribution through the kit.** The procedure ships as a skill, `orchestrate`, with the brief template; the workflow script, the CI files, the probe and the post-step are `managed` manifest entries. Setting changes go into the `init` template plus an upgrade note (open question Q5).

**D10 — Copilot gets the subset that works there**: the skill and the `AGENTS.md` section, flat fan-out only, no workflows, guard hooks advisory. Recorded in `docs/USING-AT-WORK.md`.

## 4. Open questions (defaults apply unless you object)

1. **Q1 — Model access for CI on your own repos. Settled 2026-11-13: the lower-cost route for now.** A subscription token (`claude setup-token`) stored as `CLAUDE_CODE_OAUTH_TOKEN`: no extra money, and runs draw on the plan's limits. It is a long-lived secret, so it is a recorded deviation from non-negotiable 6, limited to own non-client repos and mitigated: the secret lives in a GitHub environment that only the review job references, the job runs on a label from same-repo branches (fork pull requests get no secrets), its GitHub token is read-only, and the token is rotated on a calendar. The alternative, workload identity federation with a Console organisation (no stored secret, billed per token), replaces it when a trigger in section 12 fires. Client repos always use Bedrock or Foundry through OIDC.
2. **Q2 — How an agent commit is recognised (the old Q6, bot identity). Settled 2026-11-13: a GitHub App.** The owner creates and installs the App; agent sessions commit and push as `<app>[bot]` with installation tokens that expire within the hour, minted by a small token helper from the App's private key. The key stays in the OS keychain and never enters the repo, the settings or a transcript. This also unlocks two earlier decisions: one required approval in the ruleset, and human-only tracker transitions enforced by principal. The alternative, a committer identity set through settings, was dropped: it works in Claude Code only and may mark commits unverified. The App key is itself a long-lived credential; step 2.1 records where it lives and how it is rotated.
3. **Q3 — What triggers the panel.** Default: the label `review/panel` only; a path list (guard, CI, IaC) later, once the cost is measured.
4. **Q4 — Node in CI for the offline workflow test.** The runner already has Node and the test needs no package. Default: yes.
5. **Q5 — Repos that already have the kit.** `.claude/settings.json` is an `init` file, so they keep their old settings. Default: an upgrade note with the three lines to add; the probe reports the effective values.
6. **Q6 — Does this public repo run the Claude review job itself?** Default: yes, as dogfood, with the job skipped unless a repository variable enables it, so a fresh install is inert.
7. **Q7 — Azure Pipelines.** Default: deferred until the first Azure DevOps repo needs it; `claude -p` with Foundry and the same post-step is the expected shape.
8. **Q8 — A second opinion from another vendor. Settled for now on 2026-11-13: the Gemini plan review is dropped.** It is no longer proposed or run. An OpenAI model for reviews is under consideration and not decided. Nothing is built for it here. If a second vendor is added, it is one more lens in the panel, behind the egress screen: own repos through the vendor's API, client repos only through an in-boundary endpoint (Azure OpenAI on a private endpoint is already the default stack for client data). Default: decide once the panel has 20 runs in the ledger.

## 5. Step plan (one step = one commit with its verification; S < 1 h, M ≈ half day)

### Phase 0 — probes before anything depends on them (≈ 0.5 day)

| # | Step | Effort | Verify |
|---|---|---|---|
| 0.1 | `tools/orchestration/probe.py`: the three scratch probes (saved workflow by name; denial without the rule and its exit code; settings hook blocks inside a workflow agent) plus three new ones (settings hook blocks inside a nested subagent; the depth pin is honoured; the spawn log sees workflow agents). Writes `tools/orchestration/verified.json` with CLI version, date and one result per canary | M | run it; six results recorded; measured cost stated (the three existing probes cost $0.02 together) |
| 0.2 | Fill the null rows in `tools/telemetry/prices.json` for the current models, from the current price list | S | `ledger` prices today's session instead of reporting tokens only |
| 0.3 | Action probes in a scratch repository, with the subscription token (Q1): does `execution_file` carry `permission_denials`; does `settings` env reach the CLI; does disabling background tasks cure the green-but-empty run; does pinning the action SHA pin the CLI version | M | one `DECISIONS.md` line per answer, with the run URL |

### Phase 1 — local orchestration, no CI change (≈ 1.5 days)

| # | Step | Effort | Verify |
|---|---|---|---|
| 1.1 | Settings: `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2` under `env`; `onFailure: "block"` on the guard hook; `Workflow` in the matcher | S | probe 0.1 shows depth 2 and a blocked call when the guard is made to time out; VS Code still loads the file (manual check, recorded) |
| 1.2 | Guard rule `workflow-launch` (D7) with allow, ask, deny and crash fixtures; workflow agents counted in the fan-out total; `.claude/workflows/**` added to `guard-config` | M | `pytest tools/guard`; a sixth spawn through a workflow is reported in `spawns.jsonl` with the session total |
| 1.3 | Skill `orchestrate` with `brief-template.md` (goal, decisions not to reopen, scope, what to ignore, output format, size limit) and a section of at most 12 lines in `AGENTS.md` (D1–D3) | S | `tools/tests/test_install.py` sees the skill in a target repo; the section fits the line budget |
| 1.4 | `.claude/workflows/review-panel.js`: three lenses on a prepared diff file, one batched verifier, models pinned per stage, `null` results reported not dropped, a cap that is logged | M | offline test against a mock `agent()` (success, one lens `null`, verifier error); one live run on a real diff with tokens and cost recorded |
| 1.5 | Static test: every `agent()` call in `.claude/workflows/*.js` names a model or an agent type with a pinned model; `meta` is a literal | S | `pytest tools/orchestration`; a script without a pin fails it |

### Phase 2 — CI, read-only (≈ 2 days)

| # | Step | Effort | Verify |
|---|---|---|---|
| 2.1 | GitHub App as the agent identity (Q2): the owner creates and installs the App (owner action); `tools/identity/app_token.py` mints an installation token from the key in the OS keychain; sessions commit and push as the App | M | a session-made commit and PR show `<app>[bot]`; the token expires within the hour; the key is absent from the repo, the settings and the shell history; signature status and the rotation date recorded |
| 2.2 | `.github/workflows/agent-approval-check.yml`, action pinned to a SHA, `required_approvals: 1`, `agent_logins` and `agent_emails` set to the App and the Claude App; the owner adds it to the ruleset and raises required approvals from 0 to 1 | S | a PR with an agent commit is pending; `/approve <head-sha>` turns it green; a push makes the approval stale; a PR without agent commits passes |
| 2.3 | `tools/orchestration/assert_run.py`: the deterministic post-step of D4, standard library only | M | unit tests on fixture run files: success, denial, `null` stage, outstanding background task, missing output |
| 2.4 | `.github/workflows/claude-review.yml`: label-triggered, the subscription token read from a GitHub environment that only this job references, egress screen before the model sees the diff, the D4 contract, receipt artifact with `retention-days` set | M | a labelled PR produces a receipt; removing the allow rule makes the job fail, not pass; an unlabelled PR does not start it |
| 2.5 | `kit.manifest`, installer test, `docs/SYSTEM.md`, `docs/USING-AT-WORK.md`, `README.md`, the upgrade note | S | the idempotence check in `ci.yml`; a fresh target has the new files and an inert job |

### Phase 3 — staying current (≈ 0.5 day)

| # | Step | Effort | Verify |
|---|---|---|---|
| 3.1 | Scheduled and manual probe run in this repo only; it opens or updates one issue when a canary changes or the CLI version differs from `verified.json` | S | a forced canary failure opens the issue |
| 3.2 | Changelog watch: list the upstream changelog entries between the verified version and the current one that match a keyword list (subagent, workflow, hook, bare, permission); no model call | S | the list for 2.1.323 → current is attached to the issue from 3.1 |

### Deferred (one `DECISIONS.md` line each, with its trigger)

- A writing agent in CI (issue to PR, CI auto-fix). Trigger: Phase 2 has run for a month without a false-green. Precondition: the job checks out the base branch at the root and the PR head in a subdirectory, so hooks resolve through base files (fact 7).
- A `work-packets` workflow that implements packets in worktrees. Trigger: three orchestrated tasks done by hand with the skill.
- Azure Pipelines port (Q7).
- Nested subagents under Copilot. Trigger: the replacement for the deprecated harness is documented.
- Auto mode in CI. Trigger: an egress-controlled runner exists.
- A reviewer from a second vendor (Q8). Trigger: 20 panel runs in the ledger, and Kacper's decision.
- Workload identity federation for CI on own repos (Q1). Trigger: API billing is set up, a second person needs the job, or the job reaches a client-adjacent repo.

## 6. Trade-offs

| Choice | Gain | Cost |
|---|---|---|
| Depth 2, not 3 | bounded tokens, every output has a reader | a worker cannot hand a sub-task to a helper that delegates again |
| Flat workflow with a scripted verify stage | the plan is a reviewed file; same script locally and in CI | no ad-hoc delegation inside a run |
| `dontAsk` allowlist, not auto mode | deterministic, auditable, no classifier in the control path | every new tool need is a config change |
| Panel on a label | cost stays under the existing trigger | a risky PR without the label gets the single-lens review only |
| GitHub App as the agent identity | short-lived tokens, a real bot author in every harness, one required approval becomes possible | owner setup; a private key to protect and rotate; a token helper to maintain |
| Subscription token in CI for now | no extra money | a long-lived secret tied to one person's plan; runs draw on the plan's limits |
| The action, not raw `claude -p` | base-branch restore of `.claude/`, actor checks, federation built in | less control over the CLI version and the output format |

## 7. `DECISIONS.md` lines (pasted into `DECISIONS.md` at approval, 2026-11-13)

- Orchestration = three levels with `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2`: a Fable session orchestrates, Opus workers take one packet each in a worktree, read-only sub-workers only; why: each layer multiplies tokens and level-3 output has no reader; the default depth moved twice in 2026 (2.1.217, 2.1.219); compliance: one packet = one tracker item = one PR keeps attribution; revisit if: a task needs a delegating helper twice in a month.
- Headless orchestration = saved workflows started by name with a `Workflow(<name>)` allow rule under `dontAsk`; workflows are flat (tested 2026-11-13 on 2.1.323), so the verify stage is in the script; why: the plan becomes a reviewed file and the allow rule names exactly what CI may run; revisit if: workflow agents gain a spawn tool.
- Every headless Claude job follows one contract: explicit permission mode, budget and turn caps, background tasks off, JSON-schema output, and a deterministic post-step that fails on denials, `null` stages or missing output; why: a denied or empty run exits 0 (tested) and the action can end before background agents report (action issues #1499, #1852, #1646, open); compliance: the receipt is the validation evidence, not the job colour; revisit if: those issues close and a probe confirms it.
- Model review in CI is advisory and label-triggered (`review/panel`: three lenses plus one verifier); the gates stay `ci` and the human approval; cost: API-equivalent about $1–3 a run by estimate, up to $12 by one third-party report, so $10–30 a month at ten labelled PRs, and $0 in money while CI uses the subscription token; capped per run by `--max-budget-usd`; revisit if: the API-equivalent monthly figure passes $20 or the panel finds nothing the single review missed over 20 PRs.
- CI model access on own repos = a subscription token in a GitHub environment secret, for now (cost: $0 extra, runs draw on the plan's limits); a recorded deviation from "no long-lived keys", own non-client repos only, mitigated by the environment scope, the label trigger, a read-only job token and calendar rotation; client repos use Bedrock or Foundry through OIDC, always; revisit if: API billing is set up, a second person needs the job, or the job reaches a client-adjacent repo (then workload identity federation).
- Agent identity = a GitHub App (settles Q6 of the 2026-10 plan): sessions commit and push as `<app>[bot]` with installation tokens that expire within the hour; the private key stays in the OS keychain; why: a real bot principal in every harness, so the approval check and the ruleset can tell agent work from the owner's; compliance: attributable (ALCOA+), the person appears as approver and not as author of agent work; revisit if: the key cannot be kept out of sessions.
- `agent-approval-check` is a required status with one approval; on a solo repo the owner's `/approve <head-sha>` is the recorded approval; the ruleset's required approvals go from 0 to 1 once the App authors the PRs; compliance: approval is bound to the exact commit and goes stale on a push; revisit if: a second maintainer joins (then two approvals).
- The guard gates workflow launches (`ask` unless the name is listed) and counts workflow agents in the fan-out total; the guard hook sets `onFailure: "block"`; why: workflow agents bypassed the ask (five spawned unprompted on 2026-11-13) and a timed-out hook failed open; revisit if: never.
- Cloud features (Projects, Code Review, ultrareview, routines, PR auto-fix, self-hosted environments) are not used for client repos; why: they run on, or send the transcript to, vendor infrastructure; client CI uses the action or `claude -p` on our runner with Bedrock or Foundry through OIDC; revisit if: a feature documents an in-boundary mode that covers the transcript.
- Orchestration assumptions live in `tools/orchestration/verified.json` and are re-probed when the CLI version moves (about $0.05 a run); why: three defaults this plan rests on changed within four months; revisit if: never.
- The Gemini plan review is not proposed or run for now (Kacper, 2026-11-13), which suspends the "Gemini plans only" part of the routing decision of 2026-10-29; a second vendor for reviews (an OpenAI model) is undecided and would enter as one panel lens behind the egress screen, on client repos only through an in-boundary endpoint; revisit if: Kacper asks for it again, or the panel has 20 runs in the ledger.
- Skeleton vs production-grade at the end of Phase 2: review job and approval check are production-grade except for model access, where the subscription token is the interim; the panel's cost figure is an estimate until 20 runs are in the ledger; a writing agent in CI, the Azure Pipelines port and the Copilot nesting story are not built.

## 8. Cut line

Phases 0 and 1 are worth doing even if nothing else follows: they close the fan-out bypass, the fail-open timeout and the missing procedure. Phase 2 steps 2.2 and 2.3 are the next most valuable. Step 2.4 (the model job in CI) and Phase 3 can wait; a writing agent in CI is out.

## 9. What an auditor gains (and does not)

- Gains: an approval bound to a commit SHA for every agent-authored PR; a receipt per model review (verdict, SHA, model, cost, versions) with a retention; a spawn log that includes workflow agents; orchestration scripts under version control and under the guard's edit rule; a dated record of which tool behaviours were tested on which version.
- Does not gain: assurance that a model review is correct (it stays advisory); a hard control under Copilot (hook timeouts fail open there); a sandbox (the allowlist and the read-only token limit the job, they do not isolate it).

## 10. Files that will exist at the end

- New: `skills/orchestrate/SKILL.md`, `skills/orchestrate/brief-template.md`, `.claude/workflows/review-panel.js`, `tools/orchestration/probe.py`, `tools/orchestration/verified.json`, `tools/orchestration/assert_run.py`, `tools/orchestration/tests/`, `tools/identity/app_token.py`, `.github/workflows/agent-approval-check.yml`, `.github/workflows/claude-review.yml`, `.github/workflows/orchestration-probe.yml` (this repo only).
- Changed: `.claude/settings.json`, `.claude/guard.json`, `tools/guard/guard.py` and its fixtures, `tools/telemetry/prices.json`, `AGENTS.md`, `kit.manifest`, `DECISIONS.md`, `docs/SYSTEM.md`, `docs/USING-AT-WORK.md`, `README.md`.

## 11. Budget

- Effort: about 4.5 working days across the four phases, plus the owner's setup of the GitHub App.
- Research already spent: one workflow of 5 agents, about 560,000 subagent tokens, 14.5 minutes.
- Running cost, estimates until the ledger has data: probe about $0.05 a run; panel about $1–3 a run on the Opus 4.5 price row (the current models have no price in `prices.json` yet, step 0.2), with $12 a round reported by one repository as an upper reference; GitHub-hosted runner minutes for a public repo are free.
- CI uses the subscription token for now (Q1), so the model cost is zero in money and counts against the plan's limits; the dollar figures above are the API-equivalent.

## 12. Staying current

Re-run the probe and re-read the facts of that class when one of these happens:

| Trigger | Re-check |
|---|---|
| the Claude Code version differs from `verified.json` | all **T** facts (probe), then the changelog watch |
| a new release of `claude-code-action`, or issues #1499, #1852, #1646 close | facts 2, 7, 10 and the pinned SHA |
| `--bare` becomes the `-p` default | every job passes its flags explicitly; confirm hooks still load |
| February 2027, removal of the VS Code harness that supports nesting | fact 14 and D10 |
| a cloud feature documents an in-boundary mode | fact 12 |
| API billing is set up, a second person needs the CI job, or it reaches a client-adjacent repo | replace the subscription token with workload identity federation (Q1) |
| the subscription token or the App key reaches its rotation date | rotate, and record the date |
| 2027-02-13 | everything still marked **D**, **R** or **I** |

## Sources

Talk: ai.engineer/talks/vlfCjWuv4es-rethinking-claude-code-best-practices. Docs (code.claude.com/docs/en): `agents`, `sub-agents`, `workflows`, `best-practices`, `headless`, `github-actions`, `hooks`, `permission-modes`, `agent-teams`, `claude-projects`, `self-hosted-environments`, `env-vars`, `agent-sdk/subagents`. Repositories: `anthropics/claude-code-action` (`docs/security.md`, `docs/usage.md`, `examples/claude-wif.yml`, `examples/agent-approval-check.yml`, `agent-approval-check/`), `anthropics/claude-code` (`CHANGELOG.md`, its CI hardening script), `github/gh-aw`, `yorkie-team/yorkie`, `ROCm/MAD`. VS Code and GitHub Copilot docs on subagents, custom agents and hooks, read 2026-11-13.
