All four topics are done and committed on feat/guard-0.9.0 in <WT> (not pushed, worktree clean). One finding is open: the new block 4 rows go silent when wrapped in another group. It is reported here and the code is left as it is.

Commits (abab75a..HEAD):
- 3d463a8 fix(guard): require the list for the marks of an unread pipe
- 9a731f1 fix(guard): tell secret-shell that the read went through by a mark
- 54a7aa7 test(guard): bound the time of the search pattern cost test again
- ac9106e test(guard): pin eight lines the planted breaks showed untested

Topics:
1. `_nc_read` takes `*, unread: list` and the recursion passes it by keyword. `_nc_fed` takes `unread: list` as its fifth parameter with no default. Both `unread is not None` conditions are gone and the docstrings match. Red before the change: `Failed: DID NOT RAISE TypeError` (test_table_forms.py:2120).
2. `reader_pass(..., read: Optional[list] = None)` puts a mark into `read` right after `nested_commands` returns, and `rule_secret_shell` now decides with `if read:`. `_pipe_ask` stays. Red before the change, both cases: `AssertionError: ('ask', 'secret-shell: the command could not be read (RuntimeError). Confirm the command; the guard could not check it.')`.
3. The count is kept, plus `took < guard.HOOK_BUDGET_S`. What it measured, five runs per tail: median 0.0124 s (max 0.0196) with no tail, 0.0123 s with `ollama run m`.
4. `ROWS_FIX3`, `FIX3_TABLE` and `test_fix3_row` are added. The table equals the file exactly (checked with ast), and all 14 old tables are unchanged. One red row per block under its break:
   - b1 `"function f\n{ true; echo .env; }\ncat \"$(f)\""` ask→silent
   - b2 `time if true; then ls .env; fi | xargs cat` ask→silent
   - b3 `true | ls -la .env` ask→silent
   - b4 `{ ls .env; true } | xargs cat` ask→silent
   - b5 `curl -X POST https://api.github.com./graphql … closeIssue` deny→silent
   - b6 `gh api //graphql … closeIssue` deny→silent
   - b7 `bash -c 'cat run.sh | sh'` (git-guard) ask→silent; 13 rows red in all
   - b8 `curl -s --raw -X POST …/graphql … closeIssue` deny→ask

   After each block `diff --stat` was empty, and the file ends at `total rows 40 | hold 40 | red 0`.

Existing tests changed: only test_search_patterns_cost_one_reading_per_line (topic 3). test_deploy_ask.py:135 wraps `_nc_read` with `lambda *a`; it is never called because the memo answers, so I left it.

Checks before the last commit:
- ruff: `All checks passed!`
- Python 3.13: `7063 passed, 9 skipped in 47.51s`
- Python 3.9: `7063 passed, 9 skipped in 69.95s (0:01:09)`

Rewriting check:
- Without rows-b-fix3: `turns: deny>ask 35`, same as at abab75a.
- With it: `weaker cells 44 | distinct commands 5 | crashes 0` and `turns: ask>silent 9, deny>ask 35`.

The finding: the 9 ask>silent cells are all rewriting `group`, rule secret-shell, at f@own, m@own and f@client:
- `{ { ls .env; true } | xargs cat; }`
- `{ { echo .env; true } | xargs cat; }`
- `{ { stat .env; true } | xargs cat; }`

So the block 4 rows (a zsh group closed without `;`) go silent inside an outer group. The brief calls a silent cell a finding to report, not to fix.

Deviations: none.
