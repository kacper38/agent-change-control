The fix is in as one commit, 45dd3fd fix(guard): give each construct its own key in _compound_outputs, on top of ac9106e. Not pushed; worktree clean; VERSION stays "0.8.0".

- Change: each construct is keyed by a running number (`opened`). A closer sets `handed_on[stack.pop()[0]] = not _plain_sep(...)` (the `or` is gone). The docstring and loop comment now cite zsh's `}`. No second rule.
- Rows: rows-b-fix4.txt went in as ROWS_FIX4 / FIX4_TABLE / test_fix4_row. My ast check shows it equals the file and the 15 old tables are unchanged.
  - Before the code change: `total rows 48 | hold 19 | red 29` (29 failed in pytest).
  - After: `total rows 48 | hold 48 | red 0`. All 15 other row files hold: 1,761 shell rows, red 0.
- ruff: `All checks passed!`
- Python 3.13: `7111 passed, 9 skipped in 47.82s`
- Python 3.9: `7111 passed, 9 skipped in 70.65s (0:01:10)`
- Rewriting check, 16 files: `weaker cells 35 | distinct commands 2 | crashes 0` and `turns: deny>ask 35`. The nine ask>silent cells are gone.
- Break (shared key `stack.append((k, …))`, with my change in otherwise): `total rows 48 | hold 17 | red 31`. That is the 29 F41 rows plus two Fs rows, `{ { { true } ; ls .env; } | xargs cat; }` and `{ { ls .env; } | xargs cat; }`, because the old `or` is gone too. The line is back, `guard.py` matches the fixed version, and the fixed state was re-checked at 48/48 before the commit.
- Deviations: none.
- Left as the brief says: zsh-closed groups that feed or pipe a script, and the false ask on `{ { ls .env; true }; }`.
