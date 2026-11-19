# Eight rows more for the seventh round (item #57): two of its lines lost their rows to the eighth

You built the seventh and the eighth round and the rows after the review (`8f0a893`). One more commit on top,
tests only. This file is the whole order. Where something cannot be done as written, stop and report.

## Where and how (as before)

- Worktree: `<WT>`, branch `feat/guard-0.9.0`,
  head `8f0a893`, clean.
- `<SCRATCH>` is the folder this file is in; your own files go into `<SCRATCH>/eng5/`. No push, no pull request,
  no merge. Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not
  run `tools/tracker/tracker.py`. Do not start agents.
- Commands under test are data: they stand in row files, data files and test tables, never on a command line,
  and are never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit,
  never with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng5/moved/`.
- Nothing is installed. `sh <SCRATCH>/../g070/suite.sh <worktree> tools/guard/tests` runs `ruff check` and the
  guard tests on Python 3.13 and 3.9; without the last argument it runs the whole suite (at `8f0a893`:
  `7533 passed, 9 skipped` on both).
- The commit: subject `type(scope): imperative`, lower-case start, at most 72 characters; the body says why; a
  line `Refs #57` (never `Fixes`, `Closes`, `Resolves`); the last line is the trailer of your own model,
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Write the message to a file in `<SCRATCH>/eng5/`
  and commit with `git -C <worktree> commit -q -F <file>`. Stage by explicit path. Only
  `tools/guard/tests/test_table_forms.py` changes. `tools/guard/guard.py` stays byte for byte as it is.

## What was found

The planted breaks of every round were run through the guard's tests at `8f0a893`. Two of the seventh round's
let every test pass, where both turned a row red at `2a28378`:

- `_REPORT_GIT_OPTIONS = frozenset({"--no-pager", "-P"})` with `"--paginate"` added;
- in `_git_report_plain`, `if front[0] == "-C":` as `if front[0] in ("-C", "--config-env"):`.

The seventh round's rows for `--paginate` and for `--config-env` with its value as the next word each have a
second command or an assignment on the line (`export X='xargs cat'; git --config-env pager.ls-files=X ls-files
.env`). Since the eighth round that alone makes the line ask, so those rows no longer show what
`_git_report_plain` says. The guard is right as it is; two of its lines have no row.

## The change

One new table in `tools/guard/tests/test_table_forms.py`: `ROWS_FIX7_ADD`, with `FIX7_ADD_TABLE =
_rows(ROWS_FIX7_ADD)` and `test_fix7_add_row`, built like your `ROWS_FIX8_ADD` and placed right behind it. The
table is `<SCRATCH>/rows-b-fix7-add.txt`, line for line, comments included: 8 rows, 19 lines, sha256 starts
`4e8c4433a41fa370`. On each line nothing but the seventh round's rule decides. Every row holds at `8f0a893` already, so
there is no "tests first" here. The twenty-one existing tables stay exactly as they are.

## Checks

- `ruff` and the whole suite on both Pythons before the commit: 8 tests more than at `8f0a893`.
- All rows hold: `python3 -I <SCRATCH>/expect.py <worktree>/tools/guard/guard.py` followed by the twenty-one
  files `rows-b.txt rows-b4.txt rows-b4-az.txt rows-b5.txt rows-c.txt rows-b-fix.txt rows-b-fix-add.txt
  rows-b-fix-add2.txt rows-b-fix-add3.txt rows-b-fix-add4.txt rows-b-fix-add5.txt rows-b-fix2.txt
  rows-b-fix2-add.txt rows-b-fix3.txt rows-b-fix4.txt rows-b-fix5.txt rows-b-fix6.txt rows-b-fix7.txt
  rows-b-fix8.txt rows-b-fix8-add.txt rows-b-fix7-add.txt` (each with `<SCRATCH>/` in front) ends with
  `total rows 2190 | hold 2190 | red 0`.
- The two breaks above, one at a time, each put back before the next and before the commit
  (`git -C <worktree> status --short` shows only the test module): wanted, in `test_fix7_add_row`, 5 red under
  the first and 3 red under the second. Give the counts you get.

## Report (at most 100 words)

The commit (sha, subject); the last lines of ruff and of the whole suite on both Pythons; the `total rows` line;
the red counts under each break; anything you wrote differently and why.
