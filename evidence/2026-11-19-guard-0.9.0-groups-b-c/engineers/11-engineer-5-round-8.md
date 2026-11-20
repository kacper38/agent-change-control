The eighth round is committed and every check gives the brief's number, except one detail under break (c). Nothing is pushed.

Commit: b2f4e2a `fix(guard): quiet a git report only when the line sets nothing git reads`, on top of 010b75d (`Refs #57`, Opus 5.5 trailer). Only `tools/guard/guard.py` and `tools/guard/tests/test_table_forms.py` changed; `VERSION` stays 0.9.0.

- **Rows:** `ROWS_FIX8` is the row file line for line (113 of 113), and `ROWS_FIX7` is unchanged. Before the code change 64 were red; after it all 89 hold. The nineteen files give `total rows 2157 | hold 2157 | red 0`, and the file rows give 36 of 36.
- **Ruff:** `All checks passed!`
- **Whole suite:** `7508 passed, 9 skipped` on both 3.13 and 3.9 (7419 + 89).
- **Rewriting check:** `weaker cells 35 | distinct commands 2 | crashes 0` and `turns: deny>ask 35`. No cell ends in `silent`.
- **Breaks:** (a) 64 red (F81 20, F82 14, F83 12, Fs 18); (b) 15 red (F83 11, Fs 4); (c) 11 red (F82 8, F83 1, Fs 2). Under (c) one F83 row goes red as well, which the brief did not expect: `cd .git && git config pager.ls-files 'xargs cat'; cd .. && git ls-files .env`. It has no substitution, so only `_sets_nothing` catches it. After the breaks the guard file is byte-for-byte the design file.

Where I wrote it differently: nowhere. The design already carries the docstring sentence.

Possible gap, not checked: `_WORD_RUNS_RE` does not match `<(…)`, `>(…)`, zsh's `=(…)` or a zsh glob qualifier `*(e:…:)`. I assume the earlier rule that a `(` in a separator gives no quiet report already turns these down, but I did not probe it. A row for each would pin it.
