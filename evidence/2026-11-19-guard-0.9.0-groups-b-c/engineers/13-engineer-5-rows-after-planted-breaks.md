The eight rows are committed and both breaks give the counts the brief wants. Nothing is pushed.

Commit: 6b83c85 `test(guard): pin the seventh round's --paginate and --config-env rules`, on top of 8f0a893 (`Refs #57`, Opus 5.5 trailer). Only the test module changed; guard.py is back as it was after the breaks and the tree is clean.

- **Table:** `ROWS_FIX7_ADD` is the row file line for line (19 of 19).
- **Rows:** `total rows 2190 | hold 2190 | red 0`.
- **Ruff:** `All checks passed!`
- **Whole suite:** `7541 passed, 9 skipped` on both 3.13 and 3.9.
- **Breaks:** `--paginate` added to the plain options turns 5 of the 8 red; `--config-env` taken like `-C` turns 3 red.

I wrote nothing differently from the brief.
