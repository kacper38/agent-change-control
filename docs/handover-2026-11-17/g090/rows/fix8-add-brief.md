# An addendum to the eighth fix round (item #57): rows that pin the bracket forms, and two comments

You built the eighth round (`b2f4e2a`). This is its addendum: one commit on top, no change of behaviour. This
file is the whole order. Do not reopen the decisions in it; where something cannot be done as written, stop and
report.

## Where and how (as in the eighth round)

- Worktree: `<WT>`, branch `feat/guard-0.9.0`,
  head `b2f4e2a`, clean.
- `<SCRATCH>` is the folder this file is in; your own files go into `<SCRATCH>/eng5/`. No push, no pull request,
  no merge. Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not
  run `tools/tracker/tracker.py`. Do not start agents.
- Commands under test are data: they stand in row files, data files and test tables, never on a command line,
  and are never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit,
  never with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng5/moved/`.
- Nothing is installed. `sh <SCRATCH>/../g070/suite.sh <worktree> tools/guard/tests` runs `ruff check` and the
  guard tests on Python 3.13 and 3.9; without the last argument it runs the whole suite, as CI does (at
  `b2f4e2a`: `7508 passed, 9 skipped` on both).
- The commit: subject `type(scope): imperative`, lower-case start, at most 72 characters; the body says why; a
  line `Refs #57` (never `Fixes`, `Closes`, `Resolves`); the last line is the trailer of your own model,
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Write the message to a file in `<SCRATCH>/eng5/`
  and commit with `git -C <worktree> commit -q -F <file>`. Stage by explicit path. Only
  `tools/guard/guard.py` and `tools/guard/tests/test_table_forms.py` change.

## What the review said, and what was measured

The review of `b2f4e2a` by a fresh context took up the gap you named: `_WORD_RUNS_RE` lists `$(`, a backtick and
`${`, and not the forms that open with a bare bracket: a process substitution (`<( )`, `>( )`), zsh's `=( )`, a
glob qualifier (`*(e:'…':)`). It asked for rows, and for a wider pattern if one of them is silent. It also said
that the docstring of `_sets_nothing` does not name what `cd` into another repository does.

Measured on 28 such lines (a pseudo-terminal, git 2.55.0, zsh 5.9.1, bash 5.3.15, a stand-in file): the guard
asks on every one, at 0.8.0, at the head of the seventh round and at `b2f4e2a`; on 18 of them a shell prints the
file. So there is no hole and the pattern stays as it is. The lexer ends a command at the bracket, and a line
with a bracket in a separator has no quiet report (the second round's rule at the top of `_quiet_reports`).
What is missing is a row that says so beside a git report, and a comment that tells the reader why the pattern
is short.

## The change

1. `tools/guard/guard.py`: two comments, nothing else. `<SCRATCH>/fix8-add-design-guard.py` is the `b2f4e2a`
   guard with both in (sha256 starts `9083b950ae9fb275`); `<SCRATCH>/fix8-add-design.diff` is the difference, 7
   lines: three comment lines above `_WORD_RUNS_RE`, and one sentence more at the end of the docstring of
   `_sets_nothing`. Copying the design file over `tools/guard/guard.py` gives exactly the diff. Take the wording
   as it is. No line of code changes: the orchestrating session compares the two syntax trees.
2. `tools/guard/tests/test_table_forms.py`: one new table, `ROWS_FIX8_ADD`, with `FIX8_ADD_TABLE =
   _rows(ROWS_FIX8_ADD)` and `test_fix8_add_row`, built and placed like your `ROWS_FIX8` (right behind it, with
   the begin and end comment lines around the table). The table is `<SCRATCH>/rows-b-fix8-add.txt`, line for
   line, comments included: 25 rows, 39 lines, sha256 starts `d1e1e17ffb255f5d`. `F84` (20 rows): lines on which
   a shell prints the file. `Fs` (5 rows): the same forms where no shell printed in the measurement; they ask
   all the same. The twenty existing tables stay exactly as they are. A row you think is wrong: do not change
   it; leave it and say why in the report.

There is no "tests first" here: every row holds at `b2f4e2a` already. The rows pin an outcome that three rules
hold between them, so no single break turns them red; that is said in the table's header and in the record.

## Checks

- `ruff` and the whole suite on both Pythons before the commit: 25 tests more than at `b2f4e2a`.
- All rows hold: `python3 -I <SCRATCH>/expect.py <worktree>/tools/guard/guard.py` followed by the twenty files
  `rows-b.txt rows-b4.txt rows-b4-az.txt rows-b5.txt rows-c.txt rows-b-fix.txt rows-b-fix-add.txt
  rows-b-fix-add2.txt rows-b-fix-add3.txt rows-b-fix-add4.txt rows-b-fix-add5.txt rows-b-fix2.txt
  rows-b-fix2-add.txt rows-b-fix3.txt rows-b-fix4.txt rows-b-fix5.txt rows-b-fix6.txt rows-b-fix7.txt
  rows-b-fix8.txt rows-b-fix8-add.txt` (each with `<SCRATCH>/` in front) ends with
  `total rows 2182 | hold 2182 | red 0`.
- One double break, put back before the commit (`git -C <worktree> diff --stat` shows nothing of yours lost or
  left): in `_quiet_reports`, `if any(c in sep for c in "()`"):` with `"`"` in place of `"()`"`, and the
  condition at the end cut down to `if git_at:`. Wanted: 5 of the 25 new rows red in `test_fix8_add_row`. With
  either break alone none of the 25 is red. Give the counts you get.

## Report (at most 120 words)

The commit (sha, subject); the last lines of ruff and of the whole suite on both Pythons; the `total rows` line;
the red counts under the double break and under each break alone; anything you wrote differently and why.
