The fix is committed and all the brief's numbers match. Nothing is pushed.

Commit: 2a28378 `fix(guard): quiet a git report only when it starts no named pager`, on top of a246385 (`Refs #57`, Opus 5.5 trailer). Only `tools/guard/guard.py` and `tools/guard/tests/test_table_forms.py` changed. `VERSION` is still 0.8.0.

- **Rows:** `ROWS_FIX7` is the row file line for line (76 of 76). Before the code change 43 were red; after it all 59 hold. The eighteen files give `total rows 2068 | hold 2068 | red 0`, and the file rows give 36 of 36.
- **Ruff:** `All checks passed!`
- **Whole suite:** `7419 passed, 9 skipped` on both 3.13 and 3.9 (7360 + 59).
- **Rewriting check:** `weaker cells 35 | distinct commands 2 | crashes 0` and `turns: deny>ask 35`, the same as at a246385. No cell ends in `silent`.
- **Breaks:** (a) 43 red (F71 17, F72 14, Fs 12); (b) 12 red (F72 9, Fs 3); (c) 8 red (F71 6, Fs 2). Each was put back; the diff matches the design except for the docstring.

Where I wrote it differently: only the docstring sentence on the seventh round in `_quiet_reports`. Copying the design file gave the same added and removed lines; only git's hunk boundaries differed.

Rule gap: an `export` earlier on the same line is still not looked at, for example `export GIT_CONFIG_PARAMETERS="'pager.ls-files=xargs cat'"; git ls-files .env`. The guard has that line in front of it, unlike a repository's configuration, yet it stays silent. The `_git_report_plain` docstring names `GIT_CONFIG_…` and so suggests this case is covered; no row tests it. The brief put the `GIT_CONFIG_COUNT` export out of scope; the same-line export should be named in the decision record or go to the backlog.
