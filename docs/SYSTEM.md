# System description — agent-change-control

Status: 2026-11-01, after step 3.7 and the rename to agent-change-control (3.4 remote and user-scope hooks, and Q6 pending the owner) of `docs/PLAN-2026-10-mature-setup.md`.
Components marked *planned* do not exist yet; the plan step that creates them is named.

## Purpose

A harness-neutral kit for AI-assisted platform engineering in regulated (GxP)
environments: a working agreement (`AGENTS.md`), skills, agents, deterministic
hooks and a task-tracker CLI, installed as files into a task repository so that
Claude Code and VS Code + GitHub Copilot enforce the same rules. The kit is
built to leave validation evidence behind: plan first, one topic per commit,
external verification with shown output, decisions recorded.

## Components and data flows

| Component | Today | Read by | Data |
|---|---|---|---|
| `AGENTS.md` (+ `CLAUDE.md` = `@AGENTS.md`) | exists | Claude Code; Copilot (VS Code, CLI, cloud); Codex; Gemini CLI | rules only |
| `agents/*.md` | exists (12, each pins `model:` opus/fable) | Claude Code via `~/.claude/agents` (`install.sh`); VS Code reads `.claude/agents` in task repos | prompts |
| `skills/*/SKILL.md` | exists | Claude Code via `~/.claude/skills`; Copilot via `.claude/skills` in task repos | procedures |
| `kit.manifest` + `install.sh --into <repo>` | exists (1.2) | — | copies the listed files into a task repo; writes `.claude/kit-version` and a hash manifest so locally edited files are kept |
| `tools/guard/guard.py` + `.claude/settings.json` + `.github/hooks/guard.json` | exists (1.2 engine + delete-guard; 1.4 secret-write/read/shell, git-guard, deploy-ask, egress-guard; 1.5 scratch-md; 2.1 guard-the-guard; 2.2 protected-branch; 2.3 fan-out + spawn log; 2.6 tracker-guard) | Claude Code hooks; Copilot hooks | hook JSON on stdin → `ask`/`deny` JSON (never `allow`); fixtures from both harnesses; no network |
| `tools/tracker/tracker.py` + label families + issue forms | exists (2.4, 2.5, 2.7: pr-prep and task-intake call it; session-start digest) | agents via the verbs, humans via `owner` verbs at a terminal; GitHub via `gh` | issues, labels, marker comments on GitHub |
| `tools/tracker/label_lint.py` + `.github/workflows/label-lint.yml` | exists (2.4) | GitHub Actions on issue events and nightly | comments and one tracking issue; never edits labels |
| `.githooks/commit-msg` + `tools/commit_msg.py` | exists (3.1) | git via `core.hooksPath`; CI job `commit-msg` on the PR range | commit messages |
| `tools/egress/egress_screen.py` | exists (3.2) | `fresh-review`, `gemini-review`, anything that sends material out | the material, held or sent, never dropped |
| `bin/fresh-review` + `tools/review/prompt.md` (= `.github/instructions/review.instructions.md`) | exists (3.3) | `claude -p` at home (Opus, no tools, JSON schema); Copilot code review at work | branch diff; receipt `.git/fresh-review/<sha>.json` |
| `tools/memory/memstore.py` + `~/.claude/memory-store.git` | exists (3.4 store + hook + push allowlist; 3.5 schema, `validate`, `index`, `triage`, `deprecate`) | Claude Code only: PostToolUse hook commits and validates, SessionStart digest | memory files under `~/.claude/projects/*/memory/`; one commit per write; push off until `KZ_MEMORY_PUSH` and a private remote |
| `tools/telemetry/ledger.py` + `prices.json` | exists (3.6; 3.7 one line per session id) | Claude Code SessionEnd hook; humans (`ledger.py cost --days 7`) | `~/.claude/telemetry/sessions-YYYY-MM.jsonl`: per-model tokens and cost, subagent share, spawns, parse errors; local only |
| `tools/testguard/check-test-tampering.sh` + `testguard.py` | exists (3.7; kit script + pytest rules) | PostToolUse in both harnesses when a Write/Edit/Bash names a test file; CI job `guards` | `git diff` vs the base (working tree in the hook); findings as hook feedback or a red check; no network from the hook |
| `tools/scan/latest_tag.py` | exists (3.7) | PostToolUse in both harnesses on a written Dockerfile, compose file or workflow; CI job `guards` | the file text only; `:latest` or untagged image references as feedback or a red check |
| `tools/tracker/evidence_export.py` + `evidence/<tag>/` | exists (3.7) | `validation-evidence` skill; humans; QA reviewers read the pack | `captures.json` (sha256, size, exit code, tool version per captured output) and `change-records.json` (PRs with merge SHAs, reviews, check runs; issues with markers and acceptance boxes; rulesets) from `gh api`, read-only; committed with the release |
| `~/.claude/telemetry/spawns.jsonl` | exists (2.3) | fan-out rule; humans (`tail`) | one line per subagent spawn: ts, harness, agent, model; local only |
| `~/.claude/telemetry/decisions.jsonl` | exists (3.6, guard 0.4.1) | `ledger.py cost` (prompts per rule) | one line per ask/deny: ts, verdict, rules, tool, harness, session; no command text; local only |

Flow: a human approves a plan → steps become GitHub issues (`tracker new`, a human
promotes with `owner ready`) → an agent claims one, works on a branch, opens a PR with `Refs #N` → CI and an independent
review → a human merges and closes with the protocol. Hooks sit in front of
every tool call in both harnesses.

## Environments

- Home: macOS, Claude Code (subscription), GitHub account `kacper38`; this repo dogfoods the kit.
- Work: VS Code + GitHub Copilot (hooks, skills and MCP policies enabled, per Kacper 2026-10-29);
  one pilot repo in plan step 3.9 with `KZ_BOUNDARY=client`. See `docs/USING-AT-WORK.md`.
- Deferred (plan Appendix A): self-hosted Forgejo, Proxmox host `pierun`, a CI runner VM.

## Interfaces

- GitHub via `gh` (issues, labels, PRs, checks, rulesets); GitHub Actions for CI (`test`, `commit-msg`, `guards`, aggregated by `ci`) and `label-lint`; a ruleset on `main` (PR + green `ci`, no force push, no deletion).
- Claude Code hooks (`.claude/settings.json`) and Copilot hooks (`.github/hooks/*.json`,
  `.claude/settings.json`): JSON on stdin, `permissionDecision` on stdout, exit 2 = deny;
  PostToolUse feedback as `decision`/`reason` (Claude Code) or `additionalContext` (Copilot), exit 0.
- `claude -p` for the home fresh-context review (through the egress screen); Copilot code review at work.

## Data classification

- This repo: public, MIT. No client data, no credentials, no transcripts, no hook captures before redaction. `evidence/<tag>/` holds only what GitHub already shows publicly plus check outputs of this repo.
- Telemetry (`~/.claude/telemetry/`) and raw hook captures: local to the machine; only redacted fixtures are committed.
- Memory: `~/.claude/memory-store.git` locally, pushed only to a private GitHub repo and only for allowlisted projects; own notes only; client facts never enter memory.
- Work pilot: only the kit's public files cross over; findings stay in the work repo's own `DECISIONS.md`.
