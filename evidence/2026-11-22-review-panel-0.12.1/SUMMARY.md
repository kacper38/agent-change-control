# Evidence: the review panel and guard 0.12.1 (tracker item #69, plan steps 1.4, 1.5)

Scope: the pull request of item #69, branch `feat/review-panel`. One Claude Code session (`02c6f4b0`) built it on
the owner's machine on 2026-11-22 and 2026-11-23 (UTC), in the worktree `.claude/worktrees/review-panel`. The record
is the block of 2026-11-22 on the review panel in `DECISIONS.md`. Its checks ran from the session's scratch folder,
which a restart deletes, so this folder keeps what the record cites.

The captures describe `e76140f`. A review reads at most 200,000 characters, so this folder is three commits after
it:

1. `d9ee47f` adds `originals/` and `panel-run-ae370d8.json`.
2. `0bdbd7a` adds everything else.
3. The third answers the reviews of the first two and keeps their receipts.

Between the second and the third, `0adfd4f` changed two lines of `DECISIONS.md` (the review of `d9ee47f`). The
captures do not cover that commit; CI's run on the pull request's head does.

Lint, the suite, the commit-message check and the pin probe ran at `e76140f` on a clean tree. The live hook check
and the replay ran again at `0adfd4f`, also on a clean tree, and each prints its head. The planted breaks ran with
the first runner at `0f7f6de`, and again with the second runner at `7a42f08`. Every commit from `0f7f6de` to
`0adfd4f` changes only `DECISIONS.md` or this folder (`git diff --stat 0f7f6de 0adfd4f -- . ':!evidence'`), so the
code the breaks edited is the code of this pull request. The planted breaks ran before the captures, since each edits
one file in place and then restores it. `git-status.txt`, taken last, shows only this folder as new.

Every command in these files is data. The guard was given its events on stdin and ran nothing they name.

## Files

| File | What |
|---|---|
| `git-head.txt`, `ruff.txt`, `pytest-py313.txt`, `pytest-py39.txt`, `commit-msg.txt`, `git-status.txt`, `captures.json` | Captured with `tools/tracker/evidence_export.py capture` at `e76140f`, in this order: the head; `ruff check tools`; the whole suite on Python 3.13, then on 3.9; `tools/commit_msg.py --range 1cacf7e..HEAD` (which also counts main's commits from the merge); `git status --short`. `captures.json` holds each command with its exit code, sha256, size and tool version. |
| `captures.sh` | The script that ran those captures, and the capture step that `planted-breaks/final_runs.sh` calls as `<PAD>/captures.sh`. |
| `planted-breaks/` | The lists; the two runners; how each run was called (`first_lists.sh`, `final_runs.sh`, `breaks.sh`, `breaks_v2.sh`); the scripts that wrote each later list from the one before (`make_v2.py`, `make_v3.py`, `make_v4.py`); one result file per run, named by the list and the commit it ran at. Runner versions: `run_panel_mutants.py` counts any failing exit as caught. `run_panel_mutants_v2.py` (review 5b) first runs the tests on the unbroken file and stops unless they pass, counts a break as caught only when pytest exits 1 with a failed test, names that test, and counts any other exit as an error. **First lists**, first runner, on scratch copies of `1eae9bd` and `330f0f7`: `panel_mutants.json` caught 31 of 32 (`meta-not-literal` passes there, since the static test that catches it came in `330f0f7`); `pin_mutants.json` caught 15 of 15. `first_lists.sh` holds those commands in a runnable form; run from this folder on an empty scratch folder, it gave the same counts again (`first-lists-rerun.txt`). **Round 1's lists**, first runner, on the round-1 tree before it was committed (`*-round1-tree.txt`): the panel (`panel_mutants_v2.json`) 73 of 73, the pin reader (`pin_mutants_v2.json`) 39 of 39. **Round 2's lists**, first runner, at `acd0f94`: the panel 81 of 81, the pin reader 39 of 39, `install.sh` 3 of 4. The survivor, `one-line-check-only`, is caught by the fourth kit of `0f7f6de`. **Last lists**, first runner, at `0f7f6de`: the panel (`panel_mutants_v4.json`: round 1's 73 breaks plus those of rounds 2 and 3) 83 of 83, the pin reader (`pin_mutants_v2.json`) 39 of 39, `install.sh` (`install_mutants_v3.json`) 4 of 4. **The same lists, second runner, at `7a42f08`** (`*-7a42f08.txt`): baselines of 93, 64 and 5 tests passed; then 83 of 83, 39 of 39 and 4 of 4, each caught by a named failed test, with no error. The panel lists run with the hash test left out: any edit of the panel file breaks its hash, so that test would catch every break and prove nothing. An earlier pass of round 1's lists, before two rows were added, caught 71 of 73 and 38 of 39: one break no longer applied and two passed. Its output is not kept. The rows that catch those breaks are in `f2250f5` and `ef342f2`. |
| `pin-probe.txt`, `probe_pins.py`, `probe_both.sh` | Ten scripts that call `agent()` with no model, judged by the pin reader at `ae370d8` (`git show ae370d8:…`, set up as `first_lists.sh` shows) and at `e76140f`. Nine pass the old reader with no finding; all ten fail the new one. |
| `panel-run-ae370d8.json` | The panel's first live run, `wf_f3c4aca4-f34`, on `1cacf7e..ae370d8`: the workflow's return value and logs as the harness handed them back, and the totals it reported (agents, tokens, tool calls). |
| `ledger-agents.txt` | `python3 tools/telemetry/ledger.py agents --session 02c6f4b0`, read after the run: the workflow's line ($7.01) and its four agents. The session's own line ($26.43) is the main session's cost up to that moment, without the panel's agents, which the workflow line sums. The total adds the two: $26.43 + $7.01 = $33.44. |
| `replay-first-run.txt`, `replay_first_run.py` | The first run's 18 findings fed to the panel script at `0adfd4f` under the mock harness, with no model called; the first line names the head. 13 findings carry a command. 12 of those are listed as not re-checked; one (`git check-attr`) would reach the verifier, as would the 5 quotes. |
| `live-hook-check.txt`, `live_0121.py` | Criterion 6 at `0adfd4f`; the first line names the head, the tree's state and the guard version. The worktree's guard 0.12.1 was given `Workflow` calls `{name: "review-panel"}` and `{name: "other"}` on stdin (`hook pre`, telemetry to a scratch folder): the first was silent, the second asked. A listed name whose file differs from its sha256 is checked by the unit tests on real files (`test_guard_0121.py`, rows B02, B05, B18, B24, B26, B29). |
| `fresh-review-<sha>.json` | The receipts of `bin/fresh-review`, each named by the head it read; `base` names the commit it was read against. In order: `ae370d8` and `66edd2f` (rounds 1 and 2, the whole branch against main); `acd0f94` and `e559273` (rounds 3 and 4, each the delta since the round before); `7a42f08` (review 5a, round 4's fix alone); `f401dd2` (review 5b, a first version of this folder that was never pushed; this folder replaces it, and `originals/f401dd2/` keeps the two files it cites); `d9ee47f` and `0bdbd7a` (this folder's first two commits). The receipt of the review of this folder's last commit names that commit, so it cannot be here. The pull request and a note on item #69 keep it. |
| `originals/` | Runs that were superseded or stopped, and files a review cited, kept as their tools wrote them. `captures-66edd2f/` is the full capture set round 2 read. `captures-7a42f08/` is the one review 5b read. `stopped-acd0f94/` and `stopped-e559273/` hold what two capture runs wrote before they were stopped: the first because round 3 needed a new commit, the second because `DECISIONS.md` was edited (round 4) while its 3.9 suite ran. `pytest-py39-round1-rerun.txt` is the 3.9 rerun on the round-1 tree before it was committed (last paragraph); it was run by hand, so it has no `captures.json`. `breaks-v2-first-try-7a42f08/` is the second runner's first try, which stopped at its baseline: the runner added `-q` to the project's own `-q`, so pytest printed no summary line to read. `f401dd2/` holds `SUMMARY.md` and `review-findings.md` as review 5b read them, each with the same sha256 as `git show f401dd2:…`, checked while that commit was still in the object store. |
| `review-findings.md` | Every finding of the panel's first run and of the fresh reviews, with how each was closed: fixed in a named commit, or named as a limit with the reason. |
| `SHA256SUMS` | The sha256 of each file above as it was written here. |

Paths on the owner's machine are replaced in every file the session wrote. The captures and `originals/` keep the
bytes their tools wrote, and the assembly checked that they name no such path. The placeholders:

- `<WT>`: the build worktree
- `<MAIN>`: the main checkout
- `<PAD>`: the session's scratch folder
- `<TASKS>`: its task outputs
- `<TRANSCRIPTS>`: the session's transcript folder
- `<TMP>`: the temporary root
- `<HOME>`: the home folder
- `<USER>`: the login name inside folder names, including where a line was cut inside one

One run of the whole suite on Python 3.9 during the build failed: 1 failed, 9,373 passed. It ran on the uncommitted
round-1 tree while planted breaks loaded the CPU and edited files of the same tree in place. Only its last line
reached the session, and it was never written to a file, so the failing test is not known and the output cannot be
kept. The rerun on the same tree passed (9,374, `originals/`). So did every 3.9 capture on a clean tree since:
`66edd2f`, `7a42f08` and here. Since then, breaks and captures run one after the other. The open deviation is
tracked on item #88, a guard test known to fail on Python 3.9 under CPU load, which fits this run. A note there
records the occurrence; whether it is the same test cannot be shown.
