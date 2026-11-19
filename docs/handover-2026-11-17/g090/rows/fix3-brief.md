# Review fixes for guard 0.9.0, groups B and C (item #57)

You are a fourth engineer on this branch. Guard 0.9.0 was built (17 commits), fixed twice (22 and 7 commits) and
given an addendum (3 commits); the head is `abab75a`, its suite is green (`7018 passed, 9 skipped` on Python 3.13
and 3.9) and every row written so far holds. The repository's fresh-context review then read the last ten
commits, and the orchestrating session planted 54 one-line breaks in the code of those commits to see whether a
test fails for each. This file is the whole order: four small topics, four commits. No verdict of the guard
changes in any of them. The decisions in it are made; do not reopen them. Where the code cannot follow one, stop
and report.

`tools/guard/guard.py` is a PreToolUse hook (standard library only, Python 3.9 and later). A shell rule answers
silent, ask or deny for a command line. The file has about 4,800 lines: read the functions named below (line
numbers at `abab75a`), not the whole file.

## Where and how

- Worktree: `<WT>`, branch `feat/guard-0.9.0`.
  Work only there and in `<SCRATCH>`, the folder this file is in (it holds `expect.py`, `probe.py`,
  `rewrite_check.py` and the row files). Your own scratch scripts and data files go into `<SCRATCH>/eng4/`.
  No push, no pull request, no merge of `main`.
- Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not run
  `tools/tracker/tracker.py`.
- Commands under test are data: they stand in row files, data files and test tables, never on a command line,
  and are never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit,
  never with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng4/moved/`.
- Nothing is installed (no `pip install`, `uv add`, `npx`, `brew`). The checks run offline from the local cache.
  `sh <SCRATCH>/../g070/suite.sh <worktree> tools/guard/tests` runs `ruff check` and the guard tests on Python
  3.13 and 3.9; without the last argument it runs the whole suite, as CI does. One test call by hand:
  `uv run --directory <worktree> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools/guard/tests`.
  Run the guard tests while you work, and the whole suite on both Pythons before your last commit.
- Commits: one topic, one commit; subject `type(scope): imperative`, lower-case start, at most 72 characters;
  the body says why; a line `Refs #57` (never `Fixes`, `Closes`, `Resolves`); the last line is the trailer of
  your own model, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage by explicit path. `VERSION`
  stays `"0.8.0"`; the orchestrating session sets it. No file outside `tools/guard/guard.py` and
  `tools/guard/tests/` changes.
- Tests first: write the test of a topic, see it red, then change the code. Note one red line per topic for
  your report (topic 4 has its own way, below).

## Topic 1: the mark for an unread pipe cannot be left out (one commit)

Since the addendum the reader no longer raises for a shell that reads its program from a pipe the guard cannot
read; it puts a mark into the list `unread` and reads on (`_nc_read`, line 3631; `_nc_fed`, 3885; the memo
`_nc_cached`, 3570, makes the list and is the only caller from outside). Both functions take
`unread: Optional[list] = None`, and with `None` the two checks are skipped without a word (`if cmds is not None
and unread is not None and _nc_compound_pipe(…)`, 3686; `if unread is not None and _nc_pipe_shell(piped)`,
3911). Nothing calls them that way today. A later caller that forgets the argument would read a line such as
`cat run.sh | sh` as if nothing were unread: the default fails open, and this change exists to ask for exactly
that line.

Wanted: the list is required in both functions (no default, no `None`), so a call without it is a `TypeError`
and not a silent pass. In `_nc_read` the parameters before it have defaults: make `unread` keyword-only
(`*, unread: list`) and pass it by keyword in the recursion (3691); `_nc_fed` takes it as its fifth positional
parameter without a default. The two conditions lose their `unread is not None`. Bring the two docstrings in
line.

Test (in `test_table_forms.py`, beside the other tests of the addendum): `guard._nc_read("cat run.sh | sh", 0,
[], set())` raises `TypeError`, and so does `guard._nc_fed(["cat", "run.sh"], ["cat", "run.sh"], ["sh"], [])`;
with a list handed in, `_nc_read` leaves one mark in it for that line. Red before the change: no `TypeError`.

## Topic 2: secret-shell learns from the reader pass that the read went through (one commit)

`rule_secret_shell` (line 1389) adds the files of the input redirections (`cat<.env`, `sort <.env`) only when the
reader has read the line. It finds that out by comparing the answer of `reader_pass` with one message
(line 1425: `if failed is None or failed == _pipe_ask("secret-shell"):`). That holds today only because the
judge of this rule never returns a verdict and because `combine` hands a single ask back unchanged; and when the
judge crashes after the read went through, the answer is the crash message, the comparison fails, and the ask
no longer names the file.

Wanted: decide by what was read, not by the words of a message. `reader_pass` (3740) gets one more optional
parameter, `read: Optional[list] = None`, and puts a mark into it as soon as `nested_commands(text, local)` has
returned (before the first command is judged). `rule_secret_shell` hands in a list and adds the input
redirections when the list holds a mark. A line the reader could not read (too deep, too many words) leaves the
list empty, the redirections are not asked for (`nested_inputs` would raise), and the answer is the reader's ask,
as today. `_pipe_ask` stays: `reader_pass` builds its ask with it.

Tests (same place): with `guard.secret_store_what` replaced by a function that raises `RuntimeError`
(`monkeypatch.setattr`), `rule_secret_shell` for `cat<.env` answers `ask` and its reason names `.env` (red before
the change: the reason is only "the command could not be read (RuntimeError)"); the same for
`cat run.sh | sh; cat<.env`. Without the patch, `cat run.sh | sh; cat<.env` asks and names both `.env` and the
unread pipe (holds today, must keep holding). For a nest one level deeper than `_HI_MAX_DEPTH` followed by
`; cat<.env` the rule answers `ask` and does not raise (holds today). Call `guard._nc_cached.cache_clear()`
before each call, as the neighbouring tests do.

## Topic 3: the cost test bounds the time again, beside the count (one commit, test only)

`test_search_patterns_cost_one_reading_per_line` (`test_table_forms.py`, line 2092) counted nothing and asserted
`took < 2` until the second fix round, which replaced the time by a count of `_pattern_places` calls, so that a
slow runner cannot fail it. The review is right that the count pins one cause of slowness only: any other slow
path on that 20 kB line now passes the suite.

Wanted: both. Keep the count as it is. Around the call of `guard.rule_egress_guard`, measure the time with
`time.perf_counter()` and assert `took < guard.HOOK_BUDGET_S` (3.5 s: the time after which the hook stops the
rules and asks; where the hook cannot fork there is no such stop, and the harness's own timeout of 5 s lets the
call run). Message in the style of the old one (`f"{took:.2f} s: a slow hook fails open"`). At `abab75a` the
line takes 0.012 s on this machine (median of five), so the bound is about 290 times away; say in the docstring
why it is the budget and no tighter figure. No red line for this topic: say in the report what the test
measured.

## Topic 4: rows for planted breaks that no test caught (one commit, tests only)

`<SCRATCH>/rows-b-fix3.txt`: 40 rows, sha256 starts `94cda24ce6136349`; ids `Fm` (hold at `abab75a` and must keep
holding). Check them with `python3 -I <SCRATCH>/expect.py <guard.py> <SCRATCH>/rows-b-fix3.txt` (the guard file
comes first): at `abab75a` it ends with `total rows 40 | hold 40 | red 0`.

They go into `tools/guard/tests/test_table_forms.py` as one **new** table, `ROWS_FIX3`, with its own
`FIX3_TABLE = _rows(ROWS_FIX3)` and its own parametrized test (`test_fix3_row`), built like `ROWS_FIX2_ADD` /
`test_fix2_add_row`; the table is the file, line for line, comments included. The fourteen existing tables stay
exactly as they are: the orchestrating session compares each with its frozen file. A command that starts with a
double quote is a JSON string: it carries line breaks. A row you think is wrong: do not change it; leave it and
say why in the report.

The file has eight blocks, each under a line `# --- block N ---`. Each names, in a comment above its rows, the
line of `guard.py` whose break it must catch and the break itself (block 7 is written for the code as topic 1
leaves it). For each block: make that one change in the worktree's `guard.py`, run
`python3 -I <SCRATCH>/expect.py <worktree>/tools/guard/guard.py <SCRATCH>/rows-b-fix3.txt`, see at least one row
of the block red, and put the line back (`git -C <worktree> diff --stat` must show no change in `guard.py`
before you go on). Give one red row per block in the report. If a block's rows stay green under its break, do
not write a new row: report it.

A ninth break is caught by the tests of topic 2 and has no row, because it changes a reason and no verdict:
`if failed is None or failed == _pipe_ask("secret-shell"):` -> `if failed is None:` let every test pass at
`abab75a` (with an unread pipe on the line the ask no longer named the file behind `<`).

Two planted breaks stay without a row, by decision; leave the code as it is and do not report them as open:
the second half of `if not stack or stack[-1][1] != toks[0]:` in `_compound_outputs` (a closer that is not the
word of the construct it would close: of 57,270 generated lines, the 48 whose verdict it changes are all
refused by bash and by zsh), and `("coproc",)` in the `function`/`coproc` rule of `_quiet_reports` (it changes
a verdict only where `coproc` stands alone in front of another command, which starts no coprocess for the
report; kept as the stricter reading).

## The check beyond the rows

No verdict changes in this round: every row of every table holds as before (1,673 shell rows and 36 file rows
before this round), and

`python3 -u -I <SCRATCH>/rewrite_check.py <SCRATCH>/expect.py <SCRATCH>/rewrite_readers.py <guard.py> <SCRATCH>/eng4/rewrite.json <SCRATCH>/rows-b.txt <SCRATCH>/rows-b4.txt <SCRATCH>/rows-b4-az.txt <SCRATCH>/rows-b5.txt <SCRATCH>/rows-c.txt <SCRATCH>/rows-b-fix.txt <SCRATCH>/rows-b-fix-add.txt <SCRATCH>/rows-b-fix-add2.txt <SCRATCH>/rows-b-fix-add3.txt <SCRATCH>/rows-b-fix-add4.txt <SCRATCH>/rows-b-fix-add5.txt <SCRATCH>/rows-b-fix2.txt <SCRATCH>/rows-b-fix2-add.txt <SCRATCH>/rows-b-fix3.txt`

prints at your last commit what it prints at `abab75a` for the same files but the last: `weaker cells 35 |
distinct commands 2 | crashes 0`, and `python3 -I <SCRATCH>/rewrite_list.py <SCRATCH>/eng4/rewrite.json` starts
with `turns: deny>ask 35`, all in the rewritings `pipesub`, `subpipe`, `bracepipe`, `suberrpipe` and
`subnlpipe`. The new rows may add cells of that same kind (a script the guard reads in the plain form that goes
through a subshell or out of a group); name the numbers you get. A cell that ends in `silent`, or a crash, is a
finding: report it, do not widen a rule to hide it.

## Left out on purpose: do not fix these

The lists of the three earlier briefs (`<SCRATCH>/fix-brief.md`, `<SCRATCH>/fix2-brief.md`,
`<SCRATCH>/fix2-add-brief.md`, sections "Left out on purpose") stand. Nothing else from the review is yours: its
other findings are answered in the decision record by the orchestrating session. If you meet another weak form,
write it down and leave it.

## Report (at most 350 words)

Commits (sha, subject); per topic one line on what changed and its red line from before the change (topic 3:
what the test measured; topic 4: one red row per block under its break); every existing test you changed and
why; the last lines of ruff and of the whole suite on both Pythons; the `weaker cells` line of
`rewrite_check.py` and the `turns:` line of `rewrite_list.py`; deviations from this order; what you saw and left
out.
