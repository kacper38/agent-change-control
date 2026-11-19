# A seventh fix for guard 0.9.0, groups B and C (item #57): a git report hands its output to no pager for certain

You are a fifth engineer on this branch. One topic, one commit, on top of `a246385`. This file is the whole
order; the design is decided and tried. Your job is to put it in, test it, and tell me where you think it is
wrong. Do not reopen the decisions in it; where the code cannot follow one, stop and report.

`tools/guard/guard.py` is a PreToolUse hook (standard library only, Python 3.9 and later, about 5,050 lines). A
shell rule answers silent, ask or deny for a command line. The rule `secret-shell` asks when a command names a
secret file (`.env`). Since 0.9.0 a **quiet report** is left out: a command that only reports on the file and
hands its output to no other command (`ls .env`, `stat .env`, `git status .env`, `git ls-files .env`,
`git check-ignore .env`). `_quiet_reports` (line 1476) lists them; it is strict: where it is not certain, the
line has no quiet report and the rule asks, as 0.8.0 did. Read `_quiet_reports`, `_report_words` (1271),
`_git_status_verbose` (1551) and `_git_subcommand` (1633), not the whole file.

## Where and how

- Worktree: `<WT>`, branch `feat/guard-0.9.0`,
  head `a246385`, clean. Work only there and in `<SCRATCH>`, the folder this file is in. Your own scratch
  scripts and data files go into `<SCRATCH>/eng5/`. No push, no pull request, no merge of `main`.
- Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not run
  `tools/tracker/tracker.py`. Do not start agents.
- Commands under test are data: they stand in row files, data files and test tables, never on a command line,
  and are never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit,
  never with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng5/moved/`.
- Nothing is installed (no `pip install`, `uv add`, `npx`, `brew`). The checks run offline from the local cache.
  `sh <SCRATCH>/../g070/suite.sh <worktree> tools/guard/tests` runs `ruff check` and the guard tests on Python
  3.13 and 3.9; without the last argument it runs the whole suite, as CI does (the last engineer's run at
  `a246385` ended with `7360 passed, 9 skipped` on both).
- The commit: subject `type(scope): imperative`, lower-case start, at most 72 characters; the body says why; a
  line `Refs #57` (never `Fixes`, `Closes`, `Resolves`); the last line is the trailer of your own model,
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Write the message to a file in `<SCRATCH>/eng5/`
  and commit with `git -C <worktree> commit -q -F <file>`. Stage by explicit path. `VERSION` stays `"0.8.0"`;
  the orchestrating session sets it. Only `tools/guard/guard.py` and `tools/guard/tests/test_table_forms.py`
  change.

## What was found

On a terminal git pipes a report into a pager, and the pager is a program the command itself can name. These
lines are silent at `a246385`, 0.8.0 asks on each, and zsh and bash print the file once git's output is a
terminal (measured under a pseudo-terminal with git 2.55.0, zsh 5.9.1 and bash 5.3.15 against a stand-in file;
without a terminal none prints, which is why the earlier rounds did not see it):

| Kind | Example |
|---|---|
| the pager in an option of git itself | `git -c core.pager='xargs cat' -p ls-files .env`; `git -c pager.ls-files='xargs cat' ls-files .env`; `export X='xargs cat'; git --config-env=pager.ls-files=X ls-files .env` |
| the pager switched on by the report, named elsewhere | `export GIT_PAGER='xargs cat'; git -p ls-files .env` |
| the pager in a variable set for the command | `GIT_PAGER='xargs cat' git -p ls-files .env`; `GIT_CONFIG_PARAMETERS="'pager.ls-files=xargs cat'" git ls-files .env` |

## The design

All of it is in two files beside this one:

- `<SCRATCH>/fix7-design-guard.py`: the `a246385` guard with the design in (sha256 starts `66c16d2729c1b5eb`);
- `<SCRATCH>/fix7-design.diff`: the difference, 41 lines, all at the end of `_quiet_reports` and right behind it.

One rule, for git reports only: **a git report is quiet only when between `git` and the subcommand stand only
`-C <dir>`, `--no-pager` and `-P` (each compared whole, never by its first letters), and no assignment stands in
front of `git`** (`_git_report_plain`, new, with `_REPORT_GIT_OPTIONS`; one more condition where `_quiet_reports`
takes a git report). It is a list of what is known to hand nothing on, not a list of what hands on: `-c`,
`--config-env`, `-p`, `--paginate`, `--git-dir=…`, `--exec-path=…` and every option not named are turned down
alike. The word behind `-C` is its folder whatever it looks like, as git reads it. The assignment is looked for
among the leading words `_report_words` drops, read on the masked words the lexer gave (a redirection's target is
none).

Put it in as it is (copying the design file over `tools/guard/guard.py` gives exactly the diff). Where you would
write a line differently for the code's sake, do; where you think the rule is wrong, too wide or missing
something, do not patch around it: say so in the report, with the line that shows it. Add a sentence on the
seventh round to the docstring of `_quiet_reports` (the design copy leaves that docstring as it is).

Tried on the design copy: all 2,009 shell rows and 36 file rows of the eighteen tables hold; the 59 new rows
hold; over 4,990 commands in three contexts no cell is weaker than at `a246385`, and outside the new rows only
four lines of a probe list change (git with `--paginate`, `--config-env=`, `--git-dir=`, `--exec-path=`: they
ask again, as at 0.8.0); a replay of 21,646 recorded tool calls of 45 days changes no verdict against `a246385`,
in either direction; 19 of 20 planted breaks turn a new row red (the twentieth is named below).

## Rows

`<SCRATCH>/rows-b-fix7.txt`: 59 rows, 76 lines, sha256 starts `730fff493e5464ac`. `F71` (17 rows) and `F72`
(14 rows) are the kinds above; on each of their lines a shell prints the file under a terminal. `Fs` (28 rows):
12 that ask (the price: an option of git or an assignment that names no pager, such as `git -c color.ui=always
status .env` and `LC_ALL=C git status .env`; silent at `a246385`, asked at 0.8.0) and 16 silent rows (plain git
reports, `-C`, `--no-pager`, `-P`, an assignment in front of another report). `python3 -I <SCRATCH>/expect.py
<guard.py> <SCRATCH>/rows-b-fix7.txt` (the guard file comes first) ends at `a246385` with `total rows 59 | hold
16 | red 43` and at the design copy with `total rows 59 | hold 59 | red 0`.

They go into `tools/guard/tests/test_table_forms.py` as one new table, `ROWS_FIX7`, with `FIX7_TABLE =
_rows(ROWS_FIX7)` and `test_fix7_row`, built like `ROWS_FIX6` (the table at line 2305, `FIX6_TABLE` at 2463,
`test_fix6_row` at 2563, with the begin and end comment lines around the table; the file has 2,718 lines, read
those places, not all of it). The table is the file, line for line, comments included. The eighteen existing
tables stay exactly as they are: the orchestrating session compares each with its frozen file. A row you think
is wrong: do not change it; leave it and say why in the report. Tests first: add the table, see the 43 rows red,
then change the code. Table and code go into the one commit.

## Checks

- The guard tests while you work; `ruff` and the whole suite on both Pythons before the commit. The cost tests
  bound count and time: if one of them fails, report the numbers and do not move a bound.
- All rows hold: `python3 -I <SCRATCH>/expect.py <worktree>/tools/guard/guard.py` followed by the eighteen files
  `rows-b.txt rows-b4.txt rows-b4-az.txt rows-b5.txt rows-c.txt rows-b-fix.txt rows-b-fix-add.txt
  rows-b-fix-add2.txt rows-b-fix-add3.txt rows-b-fix-add4.txt rows-b-fix-add5.txt rows-b-fix2.txt
  rows-b-fix2-add.txt rows-b-fix3.txt rows-b-fix4.txt rows-b-fix5.txt rows-b-fix6.txt rows-b-fix7.txt` (each
  with `<SCRATCH>/` in front) ends with `total rows 2068 | hold 2068 | red 0`; and
  `python3 -I <SCRATCH>/expect_files.py <worktree>/tools/guard/guard.py <SCRATCH>/rows-b5-files.txt` with 36 of 36.
- The rewriting check: `python3 -u -I <SCRATCH>/rewrite_check.py <SCRATCH>/expect.py <SCRATCH>/rewrite_readers.py
  <worktree>/tools/guard/guard.py <SCRATCH>/eng5/rewrite7.json` followed by the same eighteen files, then
  `python3 -I <SCRATCH>/rewrite_list.py <SCRATCH>/eng5/rewrite7.json`. At `a246385` without the last file the two
  lines were `weaker cells 35 | distinct commands 2 | crashes 0` and `turns: deny>ask 35`; the new file alone adds
  no cell at the design copy. Wanted: no cell that ends in `silent`, no crash. Name the two lines you get.
- Break it three times, one at a time, each put back before the next (`git -C <worktree> diff --stat` shows no
  change of yours lost or left before you commit): (a) `_git_report_plain` returns True at once: rows of `F71`,
  `F72` and `Fs` go red; (b) the test for an assignment taken out: rows of `F72` go red; (c) `-c` skipped with
  its value as `-C` is (`if front[0] in ("-C", "-c")`): rows of `F71` go red. Give the red counts.

## Left out on purpose: do not fix these

- A pager or a program that the configuration or the environment names without a word of the report:
  `export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=pager.ls-files GIT_CONFIG_VALUE_0='xargs cat'; git ls-files .env`,
  `git config pager.ls-files 'xargs cat'; git ls-files .env`, a repository whose configuration already holds
  it. This is the kind "a line or an earlier call that changes what a report runs" (`zmodload`, `enable -f`,
  `hash`, an alias, `PATH=`): out of scope and named in the decision record.
- A name inside the value of an option (`git -c core.pager='cat .env' -p status`): silent in 0.8.0 as well, a
  name the guard has never seen. It goes to the backlog, as `cat .env*` and `x=.env; cat $x` do.
- One planted break stays without a row, by decision: looking for the assignment only in the word right in
  front of `git`. It changes a verdict only where a shell word stands between an assignment and `git`
  (`X=… ! git …`, `X=… then git …`), and on each of seven such lines neither shell runs git.
- The price rows stay as they are. Do not touch `_git_subcommand`, `_report_words`, `secret_class`, `_hi_lex`,
  `_hi_prepare` or any other rule.

## Report (at most 200 words)

The commit (sha, subject); the red count before the change and the hold count after; the last lines of ruff and
of the whole suite on both Pythons; the `weaker cells` line and the `turns:` line of the rewriting check; the
three red counts under the breaks; where you wrote the design differently and why; any rule you think is wrong,
too wide or missing, with the line that shows it.
