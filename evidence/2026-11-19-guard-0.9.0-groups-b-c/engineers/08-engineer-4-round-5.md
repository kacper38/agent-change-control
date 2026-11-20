The strict quiet reading is in as one commit, 3bcab45 fix(guard): read a line strictly before a secret report is quiet, on top of 45dd3fd. Not pushed; worktree clean; VERSION stays "0.8.0". One possible missing rule is below (P1).

- Rows: `total rows 151 | hold 56 | red 95` before the code change, `hold 151 | red 0` after. All 16 earlier row files hold (1,761 rows).
- ruff: `All checks passed!`
- Python 3.13: `7263 passed, 9 skipped in 50.89s`
- Python 3.9: `7263 passed, 9 skipped in 73.52s (0:01:13)`
- Mask test (`test_the_quiet_mask_reads_quotes_as_the_lexer_does`, in test_table_forms.py): seed 57, 25,000 strings, 1.00 s. U+FFFD, U+1F600 and U+20000 are written as `\U` escapes.
- Rewriting check: `weaker cells 35 | distinct commands 2 | crashes 0` and `turns: deny>ask 35`.
- Red counts under the breaks:
  - (a) unmasked lex: red 42 (F53=16, F55=6, F57=19, Fs=1)
  - (b) no `}` rule: red 15 (F51=12, Fs=3)
  - (c) no `[[`/`]]` count: red 1 (F54)
  - Each was put back, and guard.py differs from fix5-design-guard.py only by my docstrings.
- Written differently: only the docstrings of `_quiet_reports` and `_compound_outputs`, as you asked. The ROWS_FIX5 table equals the row file and the 16 old tables are unchanged.
- Rules, probed as data rows in eng4/probe-fix5.txt (not measured in a shell):
  - P1, missing: zsh/stat's `stat -A`/`-H` stores into a variable as `printf -v` does. `zmodload zsh/stat; stat -A a .env; cat $a` is silent.
  - P3, too wide but fails closed: `printf '%s\n' -v .env` asks, because any later word starting with `-v` counts as the option.
  - P5, too wide but fails closed: `ls -la .env; echo "${X:-_}"` asks, because the new `_LAST_ARG_RE` takes a literal `_` default for `$_`.
- Left alone: the forms your brief lists as left out.
