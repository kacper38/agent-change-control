---
name: orchestrate
description: Split a task into packets and run them with worker agents — a linted brief per packet, the first packet end to end, worker results and headless runs checked by assert_run.py, merge-ready before any merge. Use when a task is big enough for more than one agent, or when a headless Claude job or a fan-out has to be planned or checked.
user_invocable: true
---
# Orchestrate

## The levels (depth two)

- **Level 0, the orchestrator** (this session): plans, writes the briefs, splits the work, reads results. It decides no merge.
- **Level 1, workers**: one engineer agent per packet, each in its own worktree; it returns a structured result.
- **Level 2, sub-workers**: read-only helpers a worker may start (a search, one verifier). They never write.
  Nothing deeper: each layer multiplies tokens and nobody reads level-3 output.

## The shape follows the job

- Packets with a person present: `Agent` fan-out from this session, each with a written brief.
- Repeatable or headless: a saved workflow; it is flat, so its verify stage replaces level 2.
- A client or secret repository: never a cloud feature.

## Procedure

1. **Split** the task into packets: one packet = one tracker item = one branch = one pull request.
2. **Brief** each packet from [`brief-template.md`](brief-template.md) (a filled one: [`brief-example.md`](brief-example.md)).
   Every field is filled; the output format is the `worker-result/1` object. Lint before you send it:
   `python3 tools/orchestration/brief_lint.py <brief>`. A brief that fails is not sent.
3. **First packet end to end** before the others start: worker, result check, review. Fix the brief
   template's gaps it shows, then fan out the rest.
4. **Fan-out limit**: at most five agents without asking the owner, and no two agents with the same job.
5. **Check each result** as data, never from prose:
   `python3 tools/orchestration/assert_run.py worker <result.json> --repo <worktree>`.
   It fails a head that is not the branch tip and a non-zero check; it prints what was not verified.
6. **A missing result is a gap**, never a pass: read the branch state (`git log`, the worktree) and re-brief
   the packet. Never guess what the worker did.
7. **Headless jobs** follow the D4 contract (`--permission-mode dontAsk` with narrow allow rules,
   `--max-budget-usd`, `--max-turns`, background tasks off, `--json-schema`). Check the output file:
   `python3 tools/orchestration/assert_run.py run <output.json>`. The exit code of `claude -p` is no evidence.
8. **Before any merge**: `python3 tools/orchestration/assert_run.py merge-ready <N>`. It passes only when the
   head is the branch tip, the checks are green, a fresh-review receipt approves that head and the pull
   request adds a `DECISIONS.md` line. The merge is the command it prints, run only where the repository's
   standing rules let an agent merge; otherwise hand the printed command to the owner.

## In Copilot

Only the flat fan-out applies: briefs, results and the `assert_run.py` checks as above, no level 2.

## What this does not do

- It does not prove a headless job ran with the flags; `run` checks the contract on the output only.
- `merge-ready` reads gh and git at one moment; a push after it is caught only by `--match-head-commit`.
- A review receipt is a file a session could write itself: it stops a forgotten review, not a hostile session.
