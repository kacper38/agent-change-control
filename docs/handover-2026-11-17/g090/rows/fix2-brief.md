# Second fix round for guard 0.9.0, groups B and C (item #57)

You are a second engineer on this branch. The first one built guard 0.9.0 (17 commits) and ran one fix pass
(22 commits); the branch head is `d1052b1`, its suite is green and every row written so far holds. Since then
the orchestrating session judged every known command again in rewritings that keep its meaning (a line break
behind a pipe, a brace group, a subshell, `if true; then …; fi`) and ran the repository's review tool a second
time. Both found forms the guard reads weaker than the plain one. This file is the whole order. It is narrow:
six topics, five of them in code that is new in 0.9.0.

`tools/guard/guard.py` is a PreToolUse hook (standard library only, Python 3.9 and later). A shell rule answers
silent, ask or deny for a command line. You do not need the history of the branch; you need the functions
named below, the rows, and the rules of the house.

## Where and how

- Worktree: `<WT>`, branch `feat/guard-0.9.0`.
  Work only there and in `<SCRATCH>`, the folder this file is in (it holds `expect.py`, `probe.py`,
  `rewrite_check.py` and the row files). Your own scratch scripts and data files go into `<SCRATCH>/eng2/`.
  No push, no pull request, no merge of `main`.
- Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not run
  `tools/tracker/tracker.py`.
- Commands under test are data: they stand in row files, data files and test tables, never on a command line,
  and are never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit,
  never with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng2/moved/`.
- Nothing is installed (no `pip install`, `uv add`, `npx`, `brew`). The checks run offline from the local cache.
  `sh <SCRATCH>/../g070/suite.sh <worktree> tools/guard/tests` runs `ruff check` and the guard tests on Python
  3.13 and 3.9; without the last argument it runs the whole suite, as CI does. One test call by hand:
  `uv run --directory <worktree> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools/guard/tests`.
  Run the guard tests while you work, and the whole suite on both Pythons before your last commit.
- Commits: one topic, one commit; subject `type(scope): imperative`, lower-case start, at most 72 characters;
  the body says why and names the rows; a line `Refs #57` (never `Fixes`, `Closes`, `Resolves`); the last line
  is the trailer of your own model, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage by
  explicit path. `VERSION` stays `"0.8.0"`; the orchestrating session sets it. No file outside
  `tools/guard/guard.py` and `tools/guard/tests/test_table_forms.py` changes.
- Tests first: add the rows, see the due ones red, then change the code. Note one red line per topic for your
  report.

## The rows

`<SCRATCH>/rows-b-fix2.txt`: 188 rows, sha256 starts `37603ad98d9ca4ec`. Check them with
`python3 -I <SCRATCH>/expect.py <guard.py> <SCRATCH>/rows-b-fix2.txt` (the guard file comes first). At
`d1052b1` it ends with `total rows 188 | hold 71 | red 117`.

- Ids `F28` to `F36` (117 rows) are due: all red at `d1052b1`.
- Ids `Fs` (65) and `Fm` (6) hold at `d1052b1` and must keep holding. The `Fm` rows pin conditions of the first
  fix pass that no test pinned (a planted break of each survived the suite); they need no change in the code.
- They go into `tools/guard/tests/test_table_forms.py` as one **new** table, `ROWS_FIX2`, line for line as in
  the file, comments included, with its own `FIX2_TABLE = _rows(ROWS_FIX2)` and its own parametrized test
  (`test_fix2_row`), built like `ROWS_FIX_ADD5` / `test_fix_add5_row`. The twelve existing tables stay exactly
  as they are: the orchestrating session compares each with its frozen file, line for line. All rows of the
  branch keep holding (1,339 shell rows and 36 file rows before this round).
- A command that starts with a double quote is a JSON string: it carries line breaks. `_rows` reads it.
- A row you think is wrong: do not change it. Leave it red and say why in the report.

## What the lexer hands you (measured at `d1052b1`)

`_hi_lex(_hi_prepare(line)[0])` gives `(separator, words)` per simple command. The separator is a compact
string: spaces are gone, but line breaks and every operator between two commands are in it.

| line | pieces |
|---|---|
| `ls .env \|⏎xargs cat` | `('', ls .env)` `('\|\n', xargs cat)` |
| `(⏎true⏎ls .env⏎) \| xargs cat` | `('(\n', true)` `('\n', ls .env)` `('\n)\|', xargs cat)` |
| `(cat run.sh) \| bash` | `('(', cat run.sh)` `(')\|', bash)` |
| `(cat run.sh) 2>/dev/null \| bash` | `('(', cat run.sh)` `(')', 2>/dev/null)` `('\|', bash)` |
| `true⏎(ls .env) \| xargs cat` | `('', true)` `('\n(', ls .env)` `(')\|', xargs cat)` |
| `case x in a) true; ls .env;; esac \| xargs cat` | `('', case x in a)` `(')', true)` `(';', ls .env)` `(';;', esac)` `('\|', xargs cat)` |
| `f() { true; ls .env; }; f \| xargs cat` | `('', f)` `('()', { true)` `(';', ls .env)` `(';', })` `(';', f)` `('\|', xargs cat)` |
| ``cat `true; ls .env` `` | `('', cat)` ``('`', true)`` `(';', ls .env)` |
| `coproc { true; ls .env; }; xargs cat` | `('', coproc { true)` `(';', ls .env)` `(';', })` `(';', xargs cat)` |

The code of this branch compares such a separator whole, after `strip(" ")` or `strip(" \n")`, with `"|"`,
`"|&"`, `"("`, `")"`. Every separator that holds a second operator or a line break falls through that
comparison, and falls to the silent side. That is the common cause of topics 1 and 2.

**Do not change `_hi_lex` or `_hi_prepare`.** Every rule reads through them; a change there moves every table.
If a row cannot hold without that, stop and report.

## Topic 1: the quiet-report check fails closed (rows F29, F32, F33, F34, F35; one commit)

`_quiet_reports` and `_compound_outputs` (guard.py, near line 1262 to 1330) decide which report commands
(K6, K7, K9: `echo`, `printf`, `ls`, `stat`, `test`, `[`, `[[`, `git check-ignore|ls-files|status`) may name a
secret file without an ask, because their output goes to no other command. It is the one place in 0.9.0 where
a wrong "no pipe here" makes the guard silent on a line that reads a secret file. All of these asked at 0.8.0
and are silent at `d1052b1` (each line prints the content of `.env`):

- `ls .env |⏎xargs cat` (a line break behind the bar: the usual way to write a long pipeline);
- `ls .env | (xargs cat)`, `{ ls .env; } | (xargs cat)` (the bar and a bracket in one separator);
- `true && (true; ls .env) | xargs cat`, `(⏎true⏎ls .env⏎) | xargs cat` (an opener or a closer the code
  does not recognise, because the separator holds more than the bracket);
- `case x in a) true; ls .env;; esac | xargs cat` (the `)` of the case pattern is taken for a subshell's
  closer and pops the `case`);
- `f() { true; ls .env; }; f | xargs cat`, `function f { true; echo .env; }; cat "$(f)"` (the output of a
  function body goes wherever the function is called);
- ``cat `true; ls .env` `` (backticks are no construct the code knows), `coproc { true; ls .env; }; …`.

The decision for this topic is made, by the orchestrating session; do not reopen it: **from now on the check
calls a report quiet only on a line it reads completely, and everything else is read as at 0.8.0.**

1. No report is quiet on a line that has, outside quotes: a here-document or `$_` (both as now); a backtick;
   a separator of the lexer that holds `(` or `)` (a subshell, a process substitution, an unquoted `$( )`, a
   function `name()`, a `case` pattern, an array); or a simple command whose first word, after the shell words
   and assignments, is `function` or `coproc`. A `$( )` inside double quotes makes no separator and changes
   nothing (`stat .env; echo "$(date)"` stays silent: an `Fs` row).
2. A separator is read by its characters, never compared whole. Take spaces and line breaks out; what is left
   is *plain* when it is empty or one of `;`, `&&`, `||`, `&`. Anything else counts as *handed on*: `|`, `|&`,
   and any operator the check does not know.
3. A report is quiet when the separator in front of it is plain, the separator behind it is plain (or the line
   ends there), and every group or compound around it (`{ … }`, `if … fi`, `while|until|for|select … done`) is
   closed on the line by its own word and the separator behind the closer's command is plain as well. A
   construct that never closes counts as handed on (as now).

With rule 1, `_compound_outputs` needs to know neither brackets nor `case`; cut what becomes unused. Rule 2
also makes four false asks go away (`F34`: `true;⏎ls -la .env` is the same line as `true; ls -la .env`, which
is silent since the build). `F35` pins rule 1 on lines that are silent today and should not be: the check does
not read them completely.

## Topic 2: a shell fed by a pipe, when the separator holds more than the bar (rows F28; one commit)

`_nc_compound_pipe` (near line 3868) asks when a subshell, group or compound stands on one side of a pipe and
a shell that reads its program from the pipe on the other. Silent at `d1052b1` (and at 0.8.0: no regression, a
gap of the rule this version adds, criterion 7 of the item):

- `(cat run.sh) 2>/dev/null | bash`: the row left of the bar is the redirection behind the closer; it has no
  words, its own separator is `)`. The same with `2>&1`, `< /dev/null`, glued (`(cat run.sh)2>/dev/null|bash`),
  with `time` or `!` in front.
- `cat run.sh |⏎(bash)`, `cat run.sh |⏎( cd x && bash )`: `strip(" \n")` leaves the line break inside
  `'|\n('`, and the comparison with `"|"` fails.

Read the separator by its characters here too. Plain pipes into a non-shell stay silent (`Fs`).

The same ask is missing for shells the reader of 0.8.0 knows already. `_nc_runs_stdin` takes `$SHELL`,
`${SHELL}`, `sudo -s`, `sudo -i` and `su` for shells that read their program from standard input, and
`echo 'git push --force origin feat' | $SHELL` is denied through it (`Fs`). The new ask, `_nc_pipe_shell`, looks
at the narrower `_PIPE_SHELLS`, so a pipe the guard cannot read into one of them is silent: `cat run.sh |
$SHELL`, `cat run.sh | "$SHELL"`, `cat run.sh | sudo -s`, `cat run.sh | su - build`, `(cat run.sh) | $SHELL`,
`cat run.sh | ($SHELL)`. Make the ask know every shell on this machine that `_nc_runs_stdin` knows. A shell
behind a container or a remote tool stays undecided, as the docstring of `_nc_pipe_shell` has it
(`cat run.sh | ssh build bash` stays silent: `Fs`); so do `$SHELL -c '…'` and `$SHELL script.sh`.

Seen and **left as it is** (name it in your report if you touch it, otherwise leave it): `cat run.sh | case x
in a) bash;; esac` is silent, and `case "$SHELL" in */bash|*/zsh) echo ok;; esac` asks, because the bar of a
case pattern is read as a pipe. Both go into the decision record as named limits.

## Topic 3: the hook switch behind an option or a shell word (rows F30; one commit)

`_git_env_gate`, inner function `environment` (near line 1552).

- `command -p export HUSKY=0`, `command -- export …`, `command -p -- export …`, `builtin -- eval '…'`,
  `command -p eval '…'`: measured with bash 5.3 and with `sh`, each exports the variable to the commands after
  it. `command -v` and `-V` are lookups and stay silent (`Fs`).
- `{ export HUSKY=0; git commit -m x; }`, `if true; then export HUSKY=0; git commit -m x; fi`, `for …; do
  export …; git push …; done`, `! export HUSKY=0; …`: the first word of the simple command is a shell word
  (`_NC_SHELL_WORDS`), so the export is not seen. This was silent at 0.8.0 too; it is the same gate, and the
  subshell form `( export HUSKY=0; git commit -m x )` is denied already (`Fs`).
- `time export HUSKY=0; git commit -m x`, `time -p export …`: `time` is a reserved word too and is not in that
  list.
- The export as the condition of a compound (`if export HUSKY=0; then git commit -m x; fi`, `while export
  HUSKY=0; do …; done`), and inside a group, a compound or a function body that closes before the commit
  (`{ export HUSKY=0; }; git commit -m x`, `if true; then export HUSKY=0; fi; git commit -m x`, `for i in 1; do
  export HUSKY=0; done; git commit -m x`, `f() { export HUSKY=0; }; f; git commit -m x`).

Measured with bash 5.3, zsh 5.9 and `sh`: in every form above the variable reaches the commands after it
(`time -p` and the `command`/`builtin` options in bash and `sh` only; the guard denies when one of the shells
exports). A subshell and a background job do not export; what the guard answers for those today stays. The
neighbours that must stay silent are `Fs` rows (`{ export FOO=1; }; git commit -m x`, `time git commit -m x`,
`{ export HUSKY=0; }; git status`, `if true; then export HUSKY=1; fi; git commit -m x`).

## Topic 4: the GitHub API host with a port, a path with a doubled slash (rows F31; one commit)

`_GITHUB_API_RE` (near line 2535) wants the path right behind the host or its trailing dot;
`https://api.github.com:443/repos/o/r/pulls/3/merge` reaches the same API and stays silent. Check every reader
of that expression and of the host name (the merge path, the GraphQL path, curl, wget, httpie).

A doubled slash: the merge path of curl reads `…/repos//o/r/pulls/3//merge` since the first fix pass (the `Fm`
rows pin it), but `gh api -X PUT repos/o/r/pulls//3/merge` and `https://api.github.com//graphql` stay silent.
Give the path of `gh api` and the GraphQL path the same reading.

The issue-write deny that matches `api.github.com/repos/` literally is older than this version and is **not**
part of this round.

## Topic 5: a GraphQL document on httpie's standard input, inside a group (rows F36; one commit)

`http https://api.github.com/graphql < q.json` asks (the guard cannot read the document; the reading is near
line 2768, `httpie and t.lstrip("0123456789").startswith("<")`). Inside
`{ …; }`, `( … )` and `if true; then …; fi` it is silent, while the `gh api graphql -F query=@q.graphql` and
`curl … -d @q.json` twins ask there too. Find where the `<` is lost and make the three forms ask.

## Topic 6: the timing test (no rows; one commit)

`test_search_patterns_cost_one_reading_per_line` in `test_table_forms.py` ends with `assert took < 2`. A
wall-clock assertion fails on a slow runner with no change in the code. Make it count instead: for example
wrap `guard._pattern_places` (or the function that works out the patterns once per line) with a counter through
`monkeypatch` and assert the number of calls for the 20 kB line. Keep the two expected verdicts. The test must
fail when the places are worked out again at every hit (try it: `if places is None:` → `if True:` in the rule,
see the test red, put the line back).

## The check beyond the rows

`<SCRATCH>/rewrite_check.py` judges every one-line command of the row files again in up to nineteen rewritings
that keep what the command does (`true⏎CMD`, `CMD⏎true`, `true && CMD`, `CMD || true`, `{ CMD; }`, `( CMD )`,
`if true; then CMD; fi`; a line break behind each `|`, behind `&&` and `||`, and for each `; `; and around the
last pipe `L | (R)`, `L | { R; }`, `L 2>/dev/null | R`, `L 2>&1 | R`, `L |& R`, `(L) | R`, `{ L; } | R`,
`(L) 2>/dev/null | R`, `(L) |⏎R`; its docstring has the list) and writes every cell where a rule that asks or
denies the command as written is weaker for the rewriting:

`python3 -u -I <SCRATCH>/rewrite_check.py <SCRATCH>/expect.py <SCRATCH>/rewrite_readers.py <guard.py> <SCRATCH>/eng2/rewrite.json <SCRATCH>/rows-b.txt <SCRATCH>/rows-b4.txt <SCRATCH>/rows-b4-az.txt <SCRATCH>/rows-b5.txt <SCRATCH>/rows-c.txt <SCRATCH>/rows-b-fix.txt <SCRATCH>/rows-b-fix-add.txt <SCRATCH>/rows-b-fix-add2.txt <SCRATCH>/rows-b-fix-add3.txt <SCRATCH>/rows-b-fix-add4.txt <SCRATCH>/rows-b-fix-add5.txt <SCRATCH>/rows-b-fix2.txt`

At `d1052b1` it prints `weaker cells 918 | distinct commands 66 | crashes 0` (about three minutes; 1,439
commands), and `python3 -I <SCRATCH>/rewrite_list.py <SCRATCH>/eng2/rewrite.json` starts with
`turns: ask>silent 831, deny>silent 87` and lists the cells per rewriting and rule (`--turn 'deny>ask'`,
`--kind`, `--rule` narrow the list).

Wanted at your last commit: **no cell that ends in `silent`**, and no crash. A cell `deny>ask` may stay where a
script the guard reads in the plain form goes through a group, a subshell or a compound into a shell (see
"Left out on purpose"). Every other cell you cannot close: name it in the report with the reason; do not widen
a rule to hide it. The check is no substitute for the rows: it only knows the rewritings above.

## Left out on purpose: do not fix these

The list of the first fix brief (`<SCRATCH>/fix-brief.md`, section "Left out on purpose") stands. Added by this
round:

- the `case` pattern bar of topic 2;
- a name carried through a file or a variable (`ls .env > list.txt; xargs cat < list.txt`);
- a command name rebound on the line by `alias`, `hash` or `PATH=`;
- the issue-write deny with a port, a doubled slash or a trailing dot;
- a script the guard reads in the plain form (`echo 'git push --force origin feat' | sh`: deny) that goes
  through a group, a subshell or a compound into the shell: the line asks, and reading the script there is not
  part of this round;
- other programs that run what a pipe hands them (`| python3`, `| source /dev/stdin`, `| rbash`,
  `| xargs -I{} sh -c '{}'`);
- the hook switch behind a precommand modifier of zsh (`noglob export HUSKY=0`), through `setopt allexport`, or
  with a value given by other means than an assignment word (`read HUSKY <<< 0; export HUSKY`,
  `printf -v HUSKY 0; export HUSKY`, `: ${HUSKY:=0}; export HUSKY`).

If you meet another form of this kind, write it down and leave it.

## Report (at most 450 words)

Commits (sha, subject); per topic one line on what changed in the code and one red line from before the fix;
every existing test you changed and why (expected: only the timing test); the last lines of ruff and of the
whole suite on both Pythons; the `weaker cells` line of `rewrite_check.py` and the `turns:` line of
`rewrite_list.py`, with the cells that stay and why; deviations from this order; rows left red and why; what
you saw and left out.
