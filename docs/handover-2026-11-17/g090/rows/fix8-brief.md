# An eighth fix for guard 0.9.0, groups B and C (item #57): a git report is quiet only when nothing else on the line can set what git reads

You built the seventh round (`2a28378`). This is one more topic, one commit, on top of `010b75d`. This file is
the whole order; the design is decided and tried. Your job is to put it in, test it, and tell me where you think
it is wrong. Do not reopen the decisions in it; where the code cannot follow one, stop and report.

## Where and how (as in the seventh round, with these differences)

- Worktree: `<WT>`, branch `feat/guard-0.9.0`,
  head `010b75d`, clean. Since your commit two commits of the orchestrating session came on top: a merge of
  `main` (docs only, nothing under `tools/guard`) and the version line. `VERSION` is `"0.9.0"` now and stays so.
- `<SCRATCH>` is the folder this file is in; your own files go into `<SCRATCH>/eng5/`. No push, no pull request,
  no merge. Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not
  run `tools/tracker/tracker.py`. Do not start agents.
- Commands under test are data: they stand in row files, data files and test tables, never on a command line,
  and are never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit,
  never with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng5/moved/`.
- Nothing is installed. `sh <SCRATCH>/../g070/suite.sh <worktree> tools/guard/tests` runs `ruff check` and the
  guard tests on Python 3.13 and 3.9; without the last argument it runs the whole suite, as CI does (at
  `010b75d`: `7419 passed, 9 skipped` on both).
- The commit: subject `type(scope): imperative`, lower-case start, at most 72 characters; the body says why; a
  line `Refs #57` (never `Fixes`, `Closes`, `Resolves`); the last line is the trailer of your own model,
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Write the message to a file in `<SCRATCH>/eng5/`
  and commit with `git -C <worktree> commit -q -F <file>`. Stage by explicit path. Only
  `tools/guard/guard.py` and `tools/guard/tests/test_table_forms.py` change.

## What was found

Your note on the seventh round was right, and the review by a fresh context called it MAJOR: git takes a pager
from its environment and from its configuration, and another command of the same line can set either. These
lines are silent at `010b75d`, 0.8.0 asks on each, and a shell prints the file once git's output is a terminal
(measured under a pseudo-terminal with git 2.55.0, zsh 5.9.1 and bash 5.3.15 against a stand-in file):

| Kind | Example |
|---|---|
| a command of the line sets git's environment | `export GIT_CONFIG_PARAMETERS="'pager.ls-files=xargs cat'"; git ls-files .env`; the same with `declare -x`, `typeset -x`, `set -a`, `eval`, a line break, or the `export` behind the report in a loop |
| a command of the line writes git's configuration | `git config pager.ls-files 'xargs cat'; git ls-files .env`; `printf '[pager]\n\tls-files = xargs cat\n' >> .git/config; git ls-files .env`; the same through the redirection of a group |
| a word of the line runs a command while the shell expands it | `echo "$(git config pager.ls-files 'xargs cat')"; git ls-files .env`; the same with a backtick, with `${ …; }` of bash 5.3, and with a quoted subscript that `[[ -v … ]]` and `test -v` evaluate |

## The design

All of it is in two files beside this one:

- `<SCRATCH>/fix8-design-guard.py`: the `010b75d` guard with the design in (sha256 starts `492c5225d360e5fb`);
- `<SCRATCH>/fix8-design.diff`: the difference, 77 lines, at the end of `_quiet_reports` (line 1476) and right
  behind it, with one sentence added to its docstring.

One rule, for git reports only. `_quiet_reports` no longer puts a git report on its list at once; it keeps the
git reports by their place on the line (`git_at`) and adds them at the end only when two things hold:

1. **The line holds no word that can run a command while the shell expands it**: `$(`, a backtick or `${`
   anywhere in the text of the line, quoted or not (`_WORD_RUNS_RE`, searched in `command` as given). A literal
   one in single quotes counts too: the check does not try to tell.
2. **Every other command of the line sets nothing git reads** (in front of the report or behind it: in a loop
   the one behind runs before the next pass). Such a command is another git report of the list; another quiet
   report that is its words alone (`beside`: no redirection, no assignment in front; `_words_alone`); or a
   command `_sets_nothing` accepts: shell words alone, a closer, or `cd`, `true`, `false`, each without a
   redirection and without an assignment (`_BESIDE_GIT_REPORT`).

It is a list of what is known to set nothing, not a list of what sets something: `export`, `declare`, `eval`,
`source`, `git config`, a bare assignment, `:` and every command not named are turned down alike. The other
reports (`ls`, `stat`, `test`, `echo`, `printf`, `[`, `[[`) keep their rule as it is: `export FOO=1; ls -la .env`
stays silent.

Put it in as it is (copying the design file over `tools/guard/guard.py` gives exactly the diff). Where you would
write a line differently for the code's sake, do; where you think the rule is wrong, too wide or missing
something, do not patch around it: say so in the report, with the line that shows it.

Tried on the design copy: all 2,068 shell rows and 36 file rows of the nineteen tables hold; the 89 new rows
hold; over 5,072 commands in three contexts no cell is weaker than at `010b75d`, and outside the new rows one
line of a probe list changes (`git status .env; echo "branch: $(git branch --show-current)"` asks again, as at
0.8.0); a replay of 21,879 recorded tool calls of 45 days changes no verdict against the head, in either
direction; 25 of 25 planted breaks turn a new row red; the rewriting check over the new rows shows no weaker
cell.

## Rows

`<SCRATCH>/rows-b-fix8.txt`: 89 rows, 113 lines, sha256 starts `30da652dfb66cc98`. `F81` (20 rows), `F82` (14)
and `F83` (12) are the three kinds above. `Fs` (38 rows): 20 silent rows (a git report alone, beside other
reports, `cd`, `true`, `false`, in a compound, over several lines; and other reports beside a command that sets
something, which keep their rule) and 18 that ask (the price: a harmless command beside a git report, such as
`git add -A && git status .env`, `mkdir -p tmp; git status .env`, `echo "$(date)"; git status .env`; silent at
`010b75d`, asked at 0.8.0). `Fm` (5 rows) pin two lines of the earlier rounds that a planted break showed
without a row (the `coproc` rule and the default for a construct that never closes); they hold at `010b75d` and
keep holding. `python3 -I <SCRATCH>/expect.py <guard.py> <SCRATCH>/rows-b-fix8.txt` (the guard file comes first)
ends at `010b75d` with `total rows 89 | hold 25 | red 64` and at the design copy with
`total rows 89 | hold 89 | red 0`.

They go into `tools/guard/tests/test_table_forms.py` as one new table, `ROWS_FIX8`, with `FIX8_TABLE =
_rows(ROWS_FIX8)` and `test_fix8_row`, built like your `ROWS_FIX7` (the table at line 2430, `FIX7_TABLE` at
2544, `test_fix7_row` at 2651, with the begin and end comment lines around the table; the file has 2,806 lines).
The table is the file, line for line, comments included. The nineteen existing tables stay exactly as they are:
the orchestrating session compares each with its frozen file. A row you think is wrong: do not change it; leave
it and say why in the report. Tests first: add the table, see the 64 rows red, then change the code. Table and
code go into the one commit.

## Checks

- The guard tests while you work; `ruff` and the whole suite on both Pythons before the commit. The cost tests
  bound count and time: if one of them fails, report the numbers and do not move a bound.
- All rows hold: `python3 -I <SCRATCH>/expect.py <worktree>/tools/guard/guard.py` followed by the nineteen files
  `rows-b.txt rows-b4.txt rows-b4-az.txt rows-b5.txt rows-c.txt rows-b-fix.txt rows-b-fix-add.txt
  rows-b-fix-add2.txt rows-b-fix-add3.txt rows-b-fix-add4.txt rows-b-fix-add5.txt rows-b-fix2.txt
  rows-b-fix2-add.txt rows-b-fix3.txt rows-b-fix4.txt rows-b-fix5.txt rows-b-fix6.txt rows-b-fix7.txt
  rows-b-fix8.txt` (each with `<SCRATCH>/` in front) ends with `total rows 2157 | hold 2157 | red 0`; and
  `python3 -I <SCRATCH>/expect_files.py <worktree>/tools/guard/guard.py <SCRATCH>/rows-b5-files.txt` with 36 of 36.
- The rewriting check: `python3 -u -I <SCRATCH>/rewrite_check.py <SCRATCH>/expect.py <SCRATCH>/rewrite_readers.py
  <worktree>/tools/guard/guard.py <SCRATCH>/eng5/rewrite8.json` followed by the same nineteen row files, then
  `python3 -I <SCRATCH>/rewrite_list.py <SCRATCH>/eng5/rewrite8.json`. At `2a28378` without the last file the two
  lines were `weaker cells 35 | distinct commands 2 | crashes 0` and `turns: deny>ask 35`; the new file alone adds
  no cell at the design copy. Wanted: no cell that ends in `silent`, no crash. Name the two lines you get.
- Break it three times, one at a time, each put back before the next (`git -C <worktree> diff --stat` shows no
  change of yours lost or left before you commit): (a) the condition at the end of `_quiet_reports` cut down to
  `if git_at:`: rows of `F81`, `F82`, `F83` and the price rows of `Fs` go red; (b) the search for
  `_WORD_RUNS_RE` taken out of that condition: rows of `F83` and of `Fs` go red; (c) `"git"` added to
  `_BESIDE_GIT_REPORT`: rows of `F82` and of `Fs` go red. Give the red counts.

## Left out on purpose: do not fix these

- What an earlier call or the session left behind: a pager in the configuration of the repository or of the
  folder that `-C <dir>` or `cd <dir>` names, a variable exported before the line. The guard reads a line; this
  is named in the decision record as the limit.
- The same question for the other reports (`alias ls=cat`, `hash`, `PATH=`, `zmodload`, `enable -f` in front of
  `ls .env`): unchanged, named in the decision record and in the backlog.
- A secret name glued to a substitution (`git ls-files ".env$(…)"`): silent in 0.8.0 as well, a name the guard
  has never seen. Backlog.
- The price rows stay as they are. Do not touch `_git_subcommand`, `_report_words`, `_git_report_plain`,
  `_compound_outputs`, `secret_class`, `_hi_lex`, `_hi_prepare` or any other rule.

## Report (at most 200 words)

The commit (sha, subject); the red count before the change and the hold count after; the last lines of ruff and
of the whole suite on both Pythons; the `weaker cells` line and the `turns:` line of the rewriting check; the
three red counts under the breaks; where you wrote the design differently and why; any rule you think is wrong,
too wide or missing, with the line that shows it.
