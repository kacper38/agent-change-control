# Plan — the task page (#77): a local, read-only HTML record of a task

Status: APPROVED by the owner on 2026-11-21 ("i agree to 77"), with the session's recommended answers to the four open questions (section 6). Not part of Phase 1 (`docs/PLAN-2026-11-phase-1.md`); tracker item #77, filed in `status/backlog` on 2026-11-20.

Method: written by the Opus session that put it up, not by the `platform-planner` agent on Fable: the Fable limit was reached on 2026-11-20 (reset 2026-11-24) and the owner chose not to wait (`DECISIONS.md`, block of 2026-11-21).

## 1. What it is

One command writes one static HTML file that shows what happened in the tasks of a project over the last N days: sessions, agents, every tool call with the guard's answer, review findings and their re-tests, evidence paths and cost. It is the record of a task, read after the fact. It is not a live console: live state is what a terminal multiplexer such as herdr shows.

The frame is a penetration test's: scope, activity log, gate decisions, findings, evidence, re-test.

## 2. What was checked on 2026-11-21 (main `6a1e3f6`)

- Every line of `<telemetry>/decisions.jsonl` (guard ≥ 0.7.0) carries `call` (the tool-use id), `session`, `tool`, `rules`, `verdict`, `ts`, `harness`, `profile`, and a `ran` line follows an asked call that went ahead (`hook post`). The same id is the `id` of the `tool_use` block in the transcript, so a tool call and the guard's answer join on it. The lines hold no tool input.
- Transcript lines carry `gitBranch`, `cwd`, `aiTitle`, and some `prNumber`. The tracker binds an item to a branch at `claim`, so a branch is a task without a network call.
- `ledger.read_agents(transcript, tdir, prices)` and `ledger.find_session` give the agent tree with state, duration, cost, tool count and model; `ledger.scan_transcript` already walks every `tool_use` block.
- A `fresh-review` receipt `.git/fresh-review/<sha>.json` holds `sha`, `ts`, `verdict`, `base`, `cost_usd` and `findings` (`file`, `line`, `severity`, `summary`).
- Box sessions write under `~/.agent-box/claude-home/` (transcripts and the guard's telemetry, `docs/SYSTEM.md` row 40), and each box run leaves `boxes/NAME/results/<UTC>/result.json`.

## 3. Decided

- Static HTML, generated on demand; no server, no port, no network call, no JavaScript. The page carries `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">`, so a browser loads nothing from outside the file. Collapsing uses `<details>`.
- Python standard library, in `tools/telemetry/page.py`, importing `ledger`; `ledger.py` keeps its text verbs.
- Every text taken from a transcript, a log or a receipt goes through `html.escape`.
- Output: `<telemetry>/pages/<UTC>.html` by default (directory 0700, file 0600); `--out PATH` is refused inside a git work tree. The file is never committed and never published.
- Both homes are read: `~/.claude` (or `CLAUDE_CONFIG_DIR`) and `~/.agent-box/claude-home`; each session is labelled `host` or `box`.

## 4. The page

| Section | Pentest frame | Source |
|---|---|---|
| Task list: branch, PR, sessions, cost, asks and denies | engagements | transcripts, `sessions-*.jsonl`, `decisions.jsonl` |
| Scope per session: title, branch, folder, model, host or box | scope | transcript (`aiTitle`, `gitBranch`, `cwd`), `result.json` for a box run |
| Agents: tree, state, duration, cost, tool calls | team | `ledger.read_agents` |
| Timeline: time, agent, tool name, guard verdict, ran | traffic log | transcripts + `decisions.jsonl` joined on `call` |
| Gate: every ask and deny with its rule | approvals | `decisions.jsonl` |
| Findings: each review, verdict, findings with file and line | findings | `.git/fresh-review/*.json` of the session's `cwd` |
| Re-test: the reviews of one branch in order, what went and what stayed | re-test | consecutive receipts compared by file, line and summary |
| Evidence: `evidence/` paths the branch changed | evidence | `git log --name-only origin/main..<branch>`, local |
| Cost | token use | ledger |

## 5. Steps (one commit each, check shown)

| Step | What | Files | Check |
|---|---|---|---|
| 0 | This plan and its `DECISIONS.md` lines | `docs/PLAN-2026-11-dashboard.md`, `DECISIONS.md` | `uv run --offline pytest tools/tests -q` |
| 1 | `collect(project, days, homes)`: sessions of both homes grouped by branch, tool calls joined with the guard log, receipts, evidence paths | `tools/telemetry/page.py`, `tools/telemetry/tests/test_page.py`, fixtures (host and box) | `uv run --offline pytest tools/telemetry -q`, `uv run --offline ruff check tools/telemetry` |
| 2 | `render(data) -> str` | same | tests: no `<script`, no `http`, the CSP present, planted markup shown as text, a planted secret in a fixture's tool input absent from the page |
| 3 | CLI: `page.py [--days 7] [--session ID] [--out PATH]`, output place and modes, refusal inside a work tree, prints the path | same | tests for modes, the refusal, the default place |
| 4 | Into the kit: `kit.manifest`, `install.sh`, `docs/SYSTEM.md` row, `README.md` line | those files | full `uv run --offline pytest -q`, `ruff check` |
| 5 | A live run on this repository: size, counts of `http`, `<script` and the planted marker in the real file (the file itself stays local); `fresh-review`; the pull request | none committed but the record in `DECISIONS.md` | the command output in the pull request body |

The owner promotes #77 with `tracker owner ready 77` before the item is claimed. Merging follows the standing word of 2026-11-18 (green checks and a `fresh-review` with no open finding).

## 6. The owner's answers (2026-11-21, the recommended ones)

1. Tool-call content (commands, paths, outputs): not shown in this version; the timeline shows the tool name, the guard's answer and the time.
2. Tracker data from the forge: none; the branch and the PR number from the transcript name the task.
3. One page for all sessions of the last N days, grouped by task.
4. Copilot sessions: deferred (Copilot leaves the guard log only, no transcript).

## 7. Deferred (skeleton, not production)

Live refresh; tracker titles and states; tool-call content, even redacted; Copilot sessions; an exploration graph; a re-test button (re-test stays a manual `fresh-review`, the page compares). Each is named in the `DECISIONS.md` block of 2026-11-21.
