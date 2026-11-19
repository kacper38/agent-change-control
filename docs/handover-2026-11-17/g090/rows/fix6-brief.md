# A sixth fix for guard 0.9.0, groups B and C (item #57): a quiet report is a command the check is certain about

One topic, one commit, on top of your `3bcab45`. Everything in `fix3-brief.md` under "Where and how" still holds
(the worktree, `<SCRATCH>`, your folder `<SCRATCH>/eng4/`, commands under test are data and never run, no `cd`,
no here-document, nothing installed, nothing deleted, stage by explicit path, `Refs #57`, your own trailer,
`VERSION` stays `"0.8.0"`, only `tools/guard/guard.py` and `tools/guard/tests/` change). This file is complete
on its own: if your earlier context is gone, this brief, `fix3-brief.md` and the files named here are enough.
The design is decided and tried; your job is to put it in, test it, and tell me where you think it is wrong.

## What was found

Your `3bcab45` passed every check of mine. Your note on `printf -v` (P3) made me look at what else turns a report
into something that is no report, and at the single characters the lexer and the shell read differently. Five
kinds of lines are silent at `3bcab45`, 0.8.0 asks on each, and zsh or bash prints the file (measured with zsh
5.9.1 and bash 5.3.15 against a stand-in file):

| Kind | Example |
|---|---|
| the option `-v` of `printf` made by the shell | `X=-v; printf $X x %s .env; cat $x`; `printf {-v,x} %s .env; cat $x`; `printf "$(echo -v)" x %s .env; cat $x` |
| `$_` that quotes split in the text and `eval` puts together (bash) | `ls .env; eval 'cat $'_` |
| a carriage return glued to a brace: a blank for the lexer, a character for the shell (bash) | `{ ls .env; }\r; {\r true; } \| xargs cat` (`\r` is the character) |
| a report's name with a path in front: another program | `ln -s /bin/cat ./ls; ./ls .env`; `script/test .env` |
| `case` in a quoted substitution with no blank in front | `{ ls .env; : "$(true;case x in x) : " ; } ; { : " ;; esac)" ; } \| xargs cat` |

## The design

All of it is in two files beside this one:

- `<SCRATCH>/fix6-design-guard.py`: your `3bcab45` guard with the design in (sha256 starts `28882be1acee0e07`);
- `<SCRATCH>/fix6-design.diff`: the difference, 92 lines, all between `_GROUP_CLOSER` and `_git_status_verbose`.

Its five parts:

1. **`printf`** is a quiet report only when its first argument is a format for certain (`_printf_format`, new):
   not an option (it does not start with `-`, or it is `--`), no `$` and no backtick in it, quoted or not, and
   outside quotes only letters, digits and `%_./:,+@=-` (`_PRINTF_PLAIN_RE`; the test is on the masked word, so
   a quoted character is free). This takes the place of "any later word that starts with `-v`", which was too
   wide (your P3): `printf '%s\n' -v .env` and `printf -- -v x %s .env` are silent again.
2. **`$_` in the words as the shell reads them**: per command, `_LAST_ARG_RE` is also run on every unmasked
   token, so `'cat $'_`, `cat '$'_`, `"cat \$"_` and `cat \$''_` count as `$_` on the line.
3. **A carriage return** on the line: no quiet report (`_QUIET_UNREAD_RE`).
4. **A report's name with a path** counts only in `/bin`, `/usr/bin`, `/usr/local/bin` and `/opt/homebrew/bin`
   (`_REPORT_DIRS`); for `git` reports too.
5. **`case`** in the body of a quoted substitution is found as a word by its neighbours (`_CASE_WORD_RE`), not by
   blanks.

Put it in as it is (copying the design file over `tools/guard/guard.py` gives exactly the diff). Where you would
write a line differently for the code's sake, do; where you think a rule is wrong, too wide or missing, do not
patch around it: say so in the report, with the line that shows it. Bring the docstring of `_quiet_reports` up to
date with the five parts (the design copy only added comments), and the docstring of `_quiet_sub_end` where it
names `case`.

Tried on the design copy: all 1,912 shell rows and 36 file rows of the seventeen tables hold; the 97 new rows
hold; over 4,941 commands in three contexts the only cells weaker than at `3bcab45` are the two `printf` lines
of your P3; a replay of 21,525 recorded tool calls of 45 days changes no verdict against `3bcab45`, in either
direction; 30 planted breaks, one per rule and sub-rule, each turn a new row red.

## Rows

`<SCRATCH>/rows-b-fix6.txt`: 97 rows, 121 lines, sha256 starts `794da92a26eda33e`. `F61` to `F65` (53 rows) are
the five kinds; on each of their lines a shell prints the file. `Fs` (44 rows): 20 that ask (3 asked before, 8
with a path outside the system folders, 9 are the price: a first argument of `printf` that a shell expands, a
carriage return, a word with `case` between other signs in a quoted substitution) and 24 silent rows (`printf`
with a plain format, `-v` behind the format, a path in a system folder, `eval` without `$_`, `case` inside a
longer word). `python3 -I <SCRATCH>/expect.py <guard.py> <SCRATCH>/rows-b-fix6.txt` ends at `3bcab45` with
`total rows 97 | hold 34 | red 63` and at the design copy with `total rows 97 | hold 97 | red 0`.

They go into `tools/guard/tests/test_table_forms.py` as one new table, `ROWS_FIX6`, with `FIX6_TABLE =
_rows(ROWS_FIX6)` and `test_fix6_row`, built like `ROWS_FIX5`; the table is the file, line for line, comments
included (the rows with a carriage return are JSON strings with the escape `\r`; keep them that way, no raw
carriage return stands in the repository). The seventeen existing tables stay exactly as they are. Tests first:
add the table, see the 63 rows red, then change the code. Table and code go into the one commit.

## Checks

- The guard tests while you work; `ruff` and the whole suite on both Pythons before the commit (`sh
  <SCRATCH>/../g070/suite.sh <worktree>`). The cost tests bound count and time: if one of them fails, report
  the numbers and do not move a bound.
- All rows: the seventeen row files of your last check plus `rows-b-fix6.txt` hold.
- The rewriting check as in `fix3-brief.md`, with `rows-b-fix4.txt`, `rows-b-fix5.txt` and `rows-b-fix6.txt`.
  Wanted: no cell that ends in `silent`, no crash. Name the two lines it prints.
- Break it three times, one at a time, each put back before the next (`git -C <worktree> diff --stat` shows no
  change of yours lost or left before you commit): (a) `_printf_format` always true: rows of `F61` go red;
  (b) no carriage return in `_QUIET_UNREAD_RE`: `F63` goes red; (c) `"case" in body.split()` back in
  `_quiet_sub_end`: `F65` goes red. Give the red counts.

## Left out on purpose: do not fix these

- Your P1 (`zmodload zsh/stat; stat -n -A a .env; cat $a`) and its kind: a line that changes what a report's
  name runs (`zmodload`, `enable -f`, `hash`, an alias, `PATH=`). Out of scope and named in the decision record;
  the bash loadable `stat` stores without any option, so an option rule would close half of it.
- Your P5 (`echo "${X:-_}"` beside a report asks): the price of reading `$_` in every spelling. It stays.
- `$_` that the line builds at run time (`x=_; ls .env; cat ${!x}`, a name reference, `eval` of a computed
  text), a line that reads its own text (`trap '…$BASH_COMMAND…' DEBUG`), a name that goes through a file:
  named limits, not covered.
- A name the guard has never seen: a pattern (`cat .env*`), a variable (`x=.env; cat $x`), `{ cat .env}` in zsh.
  These are silent in 0.7.1 and 0.8.0 as well and go to the backlog. Do not touch `secret_class`, `_hi_lex`,
  `_hi_prepare` or any other rule.

## Report (at most 200 words)

The commit (sha, subject); the red count before the change and the hold count after; the last lines of ruff and
of the whole suite on both Pythons; the `weaker cells` line and the `turns:` line of the rewriting check; the
three red counts under the breaks; where you wrote the design differently and why; any rule you think is wrong,
too wide or missing, with the line that shows it.
