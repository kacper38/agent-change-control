# One more fix for guard 0.9.0, groups B and C (item #57): your finding

Your report was right, and the hole is wider than the nine cells. This file is the whole order for it: one topic,
one commit, on top of your `ac9106e`. Everything in `fix3-brief.md` under "Where and how" still holds (the
worktree, `<SCRATCH>`, your folder `<SCRATCH>/eng4/`, commands under test are data and never run, no `cd`, no
here-document, nothing installed, nothing deleted, stage by explicit path, `Refs #57`, your own trailer, `VERSION`
stays `"0.8.0"`, only `tools/guard/guard.py` and `tools/guard/tests/` change). The decision in it is made.

## What was measured

zsh closes a group at a `}` that is no first word of a command: `{ ls .env; true }` is a complete group there
(zshoptions: unless `IGNORE_CLOSE_BRACES` is set, a sole `}` is significant anywhere on the line). bash refuses
such a line. Measured with zsh 5.9.1 and bash 5.3.15 in a scratch folder, against a stand-in file:

| Line | zsh | bash | 0.8.0 | `ac9106e` |
|---|---|---|---|---|
| `{ ls .env; true } \| xargs cat` | prints the file | syntax error | ask | ask |
| `{ { ls .env; true } \| xargs cat; }` | prints the file | syntax error | ask | **silent** |
| `{ if true; then ls .env; fi; true } \| xargs cat` | prints the file | syntax error | ask | **silent** |
| `{ { ls .env; { true }; } \| xargs cat; }` | prints the file | syntax error | ask | **silent** |

So the head is silent on lines that print a secret file in the owner's shell, where 0.8.0 asked.

## Why

`_compound_outputs` (line 1294 at `ac9106e`) keys each construct by the index of the command that opens it, and
two constructs opened by one command (`{ {`, `{ if`, `{ while`) share that key. The check does not see zsh's
`}` behind `true`, so in its reading one of the two never closes, and a construct that never closes counts as
handed on (`handed_on.get(o, True)`). But the other one closes by its own word with a plain separator behind it
and writes `False` under the shared key, and that answer stands for both. The docstring says "a construct that
never closes counts as handed on"; under a shared key it does not.

## Wanted

Each construct gets a key of its own (a running number), so that the one left open has no entry and counts as
handed on, whatever its neighbour did. Nothing else changes:

- `stack` holds `(number, closer)`; the number counts the constructs opened so far on the line;
- at a closer: `handed_on[stack.pop()[0]] = not _plain_sep(<the separator behind the closer>)` (one construct,
  one closing, so the `or` with the earlier value goes);
- `enclosing[k]` stays the list of the numbers on the stack; `_quiet_reports` reads it as before;
- the docstring and the comment at the loop say why a key per construct (zsh's `}`); the comment "constructs
  opened by one command share its index, so one handed on marks them all" goes.

Why this is enough, and no rule for a `}` behind a first word is added: with a key per construct, every `}` zsh
sees and the check does not leaves one construct open in the check's reading until the end of the line, and that
construct is the hidden one or one around it, so it encloses the report too; the report is then not quiet. Do
not add a second rule.

A scratch copy with this change answers every command of every list as the head does, apart from lines of this
kind: all 1,713 shell rows and 36 file rows hold, and over 4,553 commands in three contexts no cell is weaker
than at `ac9106e` and 39 are stronger (silent to ask, all on lines with a `}` that is no first word). Your result
should match that.

## Rows

`<SCRATCH>/rows-b-fix4.txt`: 48 rows, sha256 starts `1417d05a6bd5b4c2`. `F41` (29 rows) are red at `ac9106e` and
due; `Fs` (19 rows) hold there and keep holding: 13 that ask already, and 6 silent rows with two constructs opened
by one command and closed the plain way, so that the fix does not ask where nothing is handed on.
`python3 -I <SCRATCH>/expect.py <guard.py> <SCRATCH>/rows-b-fix4.txt` ends at `ac9106e` with
`total rows 48 | hold 19 | red 29` and after the fix with `total rows 48 | hold 48 | red 0`.

They go into `tools/guard/tests/test_table_forms.py` as one new table, `ROWS_FIX4`, with `FIX4_TABLE =
_rows(ROWS_FIX4)` and `test_fix4_row`, built like `ROWS_FIX3`; the table is the file, line for line, comments
included. The fifteen existing tables stay exactly as they are. Tests first: add the table, see the 29 rows red,
then change the code. Table and code go into the one commit (no red commit on the branch).

## Checks

- The guard tests while you work; `ruff` and the whole suite on both Pythons before the commit (`sh
  <SCRATCH>/../g070/suite.sh <worktree>`).
- All rows: the fifteen row files of your last check plus `rows-b-fix4.txt` hold.
- The rewriting check as in `fix3-brief.md`, with `rows-b-fix4.txt` as one more file. Wanted: no cell that ends
  in `silent`, no crash; the nine `ask>silent` cells of your last run are gone. `deny>ask` cells of the known
  kind stay. Name the two lines it prints.
- Break it once: with your change in, put the shared key back (`stack.append((k, …))` in place of the number),
  see `F41` rows red with `expect.py`, and put the line back (`git -C <worktree> diff --stat` shows no change
  before you commit).

## Left out on purpose: do not fix these

- A script fed or piped through a group that zsh closes this way (`{ cat run.sh; echo true } | sh`,
  `cat run.sh | { sh }`): the reader takes the `}` for an argument, as 0.8.0 does. It is named in the decision
  record and goes to the backlog.
- `{ { ls .env; true }; }` asks after the fix (silent at `ac9106e`): a false ask on a zsh line, by the rule that
  an open construct counts as handed on. It stays.
- `_PIPE_SHELLS` is contained in `_NC_STDIN_SHELLS` since the second round; leave both.

## Report (at most 200 words)

The commit (sha, subject); the red count before the change and the hold count after; the last lines of ruff and
of the whole suite on both Pythons; the `weaker cells` line and the `turns:` line of the rewriting check; the red
count under the break; deviations; what you saw and left.
