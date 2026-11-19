# A fifth fix for guard 0.9.0, groups B and C (item #57): the quiet check reads a line strictly

One topic, one commit, on top of your `45dd3fd`. Everything in `fix3-brief.md` under "Where and how" still holds
(the worktree, `<SCRATCH>`, your folder `<SCRATCH>/eng4/`, commands under test are data and never run, no `cd`,
no here-document, nothing installed, nothing deleted, stage by explicit path, `Refs #57`, your own trailer,
`VERSION` stays `"0.8.0"`, only `tools/guard/guard.py` and `tools/guard/tests/` change). The design below is
decided and tried; your job is to put it in, test it, and tell me where you think it is wrong.

## What was found

Your `45dd3fd` passed every check of mine but one cell: `time { true; { ls .env; true } | xargs cat; }` is silent
there, 0.8.0 asks, and zsh prints the file. That cell was the tip of a class. The quiet check (`_quiet_reports`,
`_compound_outputs`) is silent on a line whenever its reading of the line's structure differs from the shell's in
the right way, and it differs in six ways. All of these are older than your fix; `ac9106e` has them too.

| Kind | Example (silent at `45dd3fd`, a shell prints the file, 0.8.0 asks) |
|---|---|
| a brace among the words of a command, an opener the check does not pass over | `time { true; { ls .env; true } \| xargs cat; }` (zsh) |
| a closer behind a shell word or behind a closer | `if true; then ls .env; else fi \| xargs cat; time if true; then true; fi` (zsh); `… fi fi \| xargs cat; time if …` (bash) |
| a quoted or escaped brace, reserved word or separator | `{ ls .env; '{'; } \| xargs cat; '}'`; `{ ls .env; echo ';' '{'; } \| xargs cat; echo ';' '}'` |
| the lexer splits where the shell does not | `{ ls .env; [[ a && { ]]; } \| xargs cat; [[ a && } ]]`; `${X:-a; { b}`; `$[ 1 \| if ]`; `a[x ; { ]=1` |
| quoting the lexer reads otherwise than the shell | `{ ls .env; : $'\'' ; } \| xargs cat; { : \' ; }`; `"${X:-" … "}"`; `"$[ 1 " … " ]"`; a quote inside a substitution of a double-quoted string |
| a report that hands its words on by itself | `printf -v x %s .env; cat "$x"`; `[[ .env =~ .* ]]; cat $BASH_REMATCH $MATCH`; `ls .env; cat "${_:-x}"` |

Measured with zsh 5.9.1 and bash 5.3.15 against a stand-in file. A check that builds lines from parts and runs
the silent ones in both shells found 4,460 such lines among 150,019 at `45dd3fd`, and none at the design below.

## The design: fail closed

A report is quiet only on a line the check reads the way the shell does. Where it cannot be sure, the line has
no quiet report, and `secret-shell` asks as 0.8.0 does. The whole design is in two files beside this one:

- `<SCRATCH>/fix5-design-guard.py`: your `45dd3fd` guard with the design in (sha256 starts `9aec8a6ed30451b0`);
- `<SCRATCH>/fix5-design.diff`: the difference, about 140 changed lines, all between `_report_words` and
  `_git_status_verbose`.

Read the diff first. Its parts:

1. **`_quiet_mask`** (new): the prepared line with every character the lexer reads as quoted or escaped moved to
   the private plane (`_QUOTED_OFFSET`), and a mark (`_QUOTE_MARK`) behind every opening quote. `_hi_lex` then
   lexes the masked text, so every structure test (`{`, `}`, `fi`, `[[`, a shell word, `function`) sees only
   characters that are unquoted for the lexer; `'{'`, `\}`, `"fi"` and `{''` are no brace and no reserved word.
   The report words are compared unmasked (`_quiet_unmask`). A quoted or escaped separator stays a word, as the
   shell has it (the lexer alone takes `';'` for a separator).
2. **Where the lexer's quoting is not the shell's, the mask gives up (returns None):**
   - `$'…'` (the opening quote behind an unquoted `$`); a single-quoted string that only ends in `$` (`'^a$'`) and
     `$'` inside a double-quoted string stay readable;
   - a double-quoted string that ends, for the lexer, inside a `${` (`"${X:-" … "}"`);
   - a substitution inside a double-quoted string (`"$(…)"`, a backtick pair), where the lexer takes a quote of
     the body for the string's own: allowed only when `_quiet_sub_end` can tell where the shell ends it, the
     lexer sees no separator of its own inside it, and the lexer is back inside the string at its end. So
     `"$(grep -c "x y" f)"` and `"found $(date +%s)"` stay readable, a nested `$(`, a `case`, a `${`, a `#`, an
     escaped or quoted `)` in the body do not.
3. **Raw screens** (`_QUIET_UNREAD_RE`): `$[` (a quote is no quote in it) and any character of the private plane
   in the command (it would pass for a quoted one). `_LAST_ARG_RE` also takes `$_` inside a longer `${…}`.
4. **Per command, after lexing:** as many `[[` as `]]`; no token (other than a lone bracket word) with an
   unbalanced `{}` or `[]`: these are the places where the lexer splits inside `[[ ]]`, `${ }` or a subscript.
5. **`_compound_outputs`:** behind a first-word closer only redirections (`} always {`, `fi fi`, `} }`); a
   closer behind a shell word is None (`else fi`, which zsh takes); a `}` among the words of a command is None.
   No list of words like `time` or `repeat` is added, and no rule for a bare `{`: when every closer the shell
   sees is seen by the check and none it counts is a fake, an opener the check missed always ends in one closer
   too many, and that is None already.
6. **`printf -v` and `[[ … =~ … ]]`** are no quiet reports.

Put it in as it is. Where you would write a line differently for the code's sake, do; where you think a rule is
wrong, too wide or missing, do not patch around it: say so in the report, with the line that shows it. Bring
the docstrings of `_quiet_reports` and `_compound_outputs` up to date with the strict reading (the design copy
only added comments).

Tried on the design copy: all 1,761 shell rows and 36 file rows of the sixteen tables hold; the 151 new rows
hold; over 4,847 commands in three contexts no cell is weaker than at `45dd3fd`; a replay of 21,390 recorded
tool calls of 45 days changes no verdict against `45dd3fd`, in either direction.

## Rows

`<SCRATCH>/rows-b-fix5.txt`: 151 rows, sha256 starts `fd787495c91c7c21`. `F51` to `F57` (92 rows) are the six
kinds above plus the quoted substitutions; on each of their lines a shell prints the file. `Fs` (59 rows): 20 that
ask (17 asked before, 3 are the price of the `}` rule), and 39 silent rows with quotes, braces, brackets and
substitutions that hand nothing on, so the strict reading does not ask where the head was rightly silent.
`python3 -I <SCRATCH>/expect.py <guard.py> <SCRATCH>/rows-b-fix5.txt` ends at `45dd3fd` with
`total rows 151 | hold 56 | red 95` and at the design copy with `total rows 151 | hold 151 | red 0`.

They go into `tools/guard/tests/test_table_forms.py` as one new table, `ROWS_FIX5`, with `FIX5_TABLE =
_rows(ROWS_FIX5)` and `test_fix5_row`, built like `ROWS_FIX4`; the table is the file, line for line, comments
included (one row spells characters of the private plane with JSON escapes; keep it that way, no such character
stands raw in the repository). The sixteen existing tables stay exactly as they are. Tests first: add the
table, see the 95 rows red, then change the code. Table, tests and code go into the one commit.

## One more test: the mask against the lexer

`<SCRATCH>/fix5-mask-fuzz.py` draws random strings over quotes, backslashes, `$`, brackets, separators and a few
words, and checks four things wherever the mask gives a text: the masked text lexes to the same separators and,
unmasked, to the same words (strings with a quoted word of separator characters are counted, not compared: that
is the lexer's own quirk); no word holds an unmasked separator or blank; a word that is exactly `{`, `}` or `fi`
stands bare in the prepared text. It runs clean on the design copy (400,000 strings). Turn it into a test with a
fixed seed and a size that costs about a second, in the file where it fits best. Add to its alphabet three
characters the mask must leave as they are (U+FFFD, U+1F600 and U+20000, written with escapes), so that the test
also says the mask never raises.

## Checks

- The guard tests while you work; `ruff` and the whole suite on both Pythons before the commit (`sh
  <SCRATCH>/../g070/suite.sh <worktree>`). The cost tests bound count and time: if one of them fails, report
  the numbers and do not move a bound.
- All rows: the sixteen row files of your last check plus `rows-b-fix5.txt` hold.
- The rewriting check as in `fix3-brief.md`, with `rows-b-fix4.txt` and `rows-b-fix5.txt` as two more files.
  Wanted: no cell that ends in `silent`, no crash. `deny>ask` cells of the known kind stay. Name the two lines
  it prints.
- Break it three times, one at a time, each put back before the next (`git -C <worktree> diff --stat` shows no
  change of yours lost or left before you commit): (a) lex the unmasked text (`masked = _hi_prepare(command)[0]`):
  rows of `F53`, `F55`, `F57` go red; (b) take out the rule for a `}` among the words: `F51` goes red; (c) take
  out the count of `[[` and `]]`: a row of `F54` goes red. Give the red counts.

## Left out on purpose: do not fix these

- A name that goes through a file (`echo .env > names.txt; xargs cat < names.txt`): silent, as two separate
  calls always were; it is inherent in `echo .env >> .gitignore` being quiet. Named in the decision record.
- A report word redefined by the environment or the line (`PATH=…`, `hash -p`, an alias): out of scope.
- The lexer's quirk (a quoted word of separator characters is a separator) and its reading of `$'…'` and of a
  quoted substitution in the other rules: older than this build, they go to the backlog. Do not touch `_hi_lex`,
  `_hi_prepare` or any other rule.
- Lines the strict reading now asks on although nothing is handed on: a `$(…)` inside a `$(…)` of a
  double-quoted string, `"$((1 + 2))"`, a blank inside an unquoted `${VAR:-not set}`, `ls .env; echo }`. That is
  the price of failing closed; the replay shows none of them in 45 days of real calls.
- `[[ -f .env && -r .env ]]` asks at `45dd3fd` already and keeps asking.

## Report (at most 250 words)

The commit (sha, subject); the red count before the change and the hold count after; the last lines of ruff and
of the whole suite on both Pythons; the size and time of the new mask test; the `weaker cells` line and the
`turns:` line of the rewriting check; the three red counts under the breaks; where you wrote the design
differently and why; any rule you think is wrong, too wide or missing, with the line that shows it; what you saw
and left.
