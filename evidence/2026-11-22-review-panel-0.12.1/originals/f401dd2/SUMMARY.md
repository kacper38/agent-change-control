# Evidence: the review panel and guard 0.12.1 (tracker item #69, plan steps 1.4, 1.5)

Scope: the pull request of item #69, branch `feat/review-panel`. One Claude Code session (`02c6f4b0`) built it on
the owner's machine on 2026-11-22 and 2026-11-23 (UTC), in the worktree `.claude/worktrees/review-panel`. The record
is the block of 2026-11-22 on the review panel in `DECISIONS.md`. Its checks ran from the session's scratch folder,
which a restart deletes, so this folder keeps what the record cites.

The head these files describe is `7a42f08`, the commit before the one that adds this folder (which adds nothing
else). Lint, the suite, the commit-message check, the live hook check, the pin probe and the replay ran at
`7a42f08` on a clean tree. The last planted-break lists ran at `0f7f6de`. Its two successors change only
`DECISIONS.md` (`git diff --stat 0f7f6de 7a42f08`), so the code they broke is the code at `7a42f08`. The planted
breaks ran before the captures, since each edits one file in place and then restores it. `git-status.txt`, taken
last, shows only this folder as new.

A first capture run at `e559273` was stopped during the 3.9 suite, because `DECISIONS.md` was edited (round 4)
while it ran. Its partial files are not kept here. Every capture here is from the second run, at `7a42f08`.

Every command in these files is data. The guard was given its events on stdin and ran nothing they name.

## Files

| File | What |
|---|---|
| `git-head.txt`, `ruff.txt`, `pytest-py313.txt`, `pytest-py39.txt`, `commit-msg.txt`, `git-status.txt`, `captures.json` | Captured with `tools/tracker/evidence_export.py capture` at `7a42f08`, in this order: the head; `ruff check tools`; the whole suite on Python 3.13, then on 3.9; `tools/commit_msg.py --range 1cacf7e..HEAD` (which also counts main's commits from the merge); `git status --short`. `captures.json` holds each command with its exit code, sha256, size and tool version. |
| `planted-breaks/` | The lists; the runner `run_panel_mutants.py` and how it was called (`breaks.sh`); the scripts that wrote each later list from the one before (`make_v2.py`, `make_v3.py`, `make_v4.py`); one result file per run, named by the list and the commit it ran at. **First lists**, run on scratch copies of `1eae9bd` and `330f0f7` (`git archive`): `panel_mutants.json` caught 31 of 32 (`meta-not-literal` passes there, since the static test that catches it came in `330f0f7`); `pin_mutants.json` caught 15 of 15. **Round 2's lists**, at `acd0f94`: the panel 81 of 81, the pin reader 39 of 39, `install.sh` 3 of 4. The survivor, `one-line-check-only`, is caught by the fourth kit of `0f7f6de`. **Last lists**, at `0f7f6de`: the panel (`panel_mutants_v4.json`: round 1's 73 breaks plus those of rounds 2 and 3) 83 of 83, the pin reader (`pin_mutants_v2.json`) 39 of 39, `install.sh` (`install_mutants_v3.json`) 4 of 4. The panel lists run with the hash test left out: any edit of the panel file breaks its hash, so that test would catch every break and prove nothing. An earlier pass of round 1's lists, before two rows were added, caught 71 of 73 and 38 of 39: one break no longer applied and two passed. Its output is not kept. The rows that catch those breaks are in `f2250f5` and `ef342f2`. |
| `pin-probe.txt`, `probe_pins.py`, `probe_both.sh` | Ten scripts that call `agent()` with no model, judged by the pin reader at `ae370d8` (`git show ae370d8:…`) and at `7a42f08`. Nine pass the old reader with no finding; all ten fail the new one. |
| `panel-run-ae370d8.json` | The panel's first live run, `wf_f3c4aca4-f34`, on `1cacf7e..ae370d8`: the workflow's return value and logs as the harness handed them back, and the totals it reported (agents, tokens, tool calls). |
| `ledger-agents.txt` | `python3 tools/telemetry/ledger.py agents --session 02c6f4b0`, read after the run: the workflow's line ($7.01) and its four agents. The session's own line is the session's cost up to that moment, the panel included. |
| `replay-first-run.txt`, `replay_first_run.py` | The first run's 18 findings fed to the panel script at `7a42f08` under the mock harness, with no model called. 13 carry a command. 12 of those are listed as not re-checked; one (`git check-attr`) would reach the verifier, as would the 5 quotes. |
| `live-hook-check.txt`, `live_0121.py` | Criterion 6 at `7a42f08`. The worktree's guard 0.12.1 was given `Workflow` calls `{name: "review-panel"}` and `{name: "other"}` on stdin (`hook pre`, telemetry to a scratch folder): the first was silent, the second asked. |
| `fresh-review-ae370d8.json`, `fresh-review-66edd2f.json`, `fresh-review-acd0f94.json`, `fresh-review-e559273.json` | The receipts of `bin/fresh-review` (rounds 1 to 4), each named by the head it read. `base` names the commit each was read against: rounds 1 and 2 read the whole branch against main, rounds 3 and 4 the delta since the round before. The three last reviews are described in `review-findings.md`; none of their receipts is here, since the first came after this folder was assembled and the others name its commit or a later one. The pull request names all three. |
| `review-findings.md` | Every finding of the panel's first run and of the fresh reviews, with how each was closed: fixed in a named commit, or named as a limit with the reason. |
| `SHA256SUMS` | The sha256 of each file above as it was written here. |

Paths on the owner's machine are replaced in every file except the captures, which keep the bytes the tool hashed
(they name no such path):

- `<WT>`: the build worktree
- `<MAIN>`: the main checkout
- `<PAD>`: the session's scratch folder
- `<TASKS>`: its task outputs
- `<TRANSCRIPTS>`: the session's transcript folder
- `<TMP>`: the temporary root
- `<HOME>`: the home folder
- `<USER>`: the login name inside folder names, including where a line was cut inside one

One run of the whole suite on Python 3.9 during the build failed: 1 failed, 9,373 passed. It ran on the uncommitted
round-1 tree while planted breaks ran beside it, and its output was cut to the last line, so the failing test is not
known. The rerun on the same tree passed (9,374), and so did the captures at `66edd2f` and here.
