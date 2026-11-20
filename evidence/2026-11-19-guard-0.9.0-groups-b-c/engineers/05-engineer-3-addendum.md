All three topics are done, one commit each on `feat/guard-0.9.0` (worktree `<WT>`, clean). Every row holds, the whole suite passes on 3.13 and 3.9, and only allowed `deny>ask` cells are left.

**Commits:**
- `8b9479f` fix(guard): read on past a pipe the guard cannot read
- `173b99f` fix(guard): read httpie's --raw and wget's --body-data as a body
- `abab75a` fix(guard): read a redirect target behind a line continuation

**Per topic:**
1. **Unread pipe.** It no longer raises. `_nc_fed` and `_nc_compound_pipe` record a mark, and the read goes on. The memo keeps the mark as its 4th item, handed out by the new `nested_unread_pipe(command, local)`. The six `reader_pass` rules add the ask (`_pipe_ask`, wording unchanged) when they find no deny; delete-guard and deploy-ask add the same ask. Bars `_nc_fed` read through (`fed_bars`) are skipped. secret-shell keeps input redirections when `failed` is the pipe ask. The other callers needed no change.
   - Red before: `bash -c 'git push --force origin feat'; cat run.sh | sh` gave git-guard `ask`, expected `deny`.
   - `cat run.sh | { ssh -n build; sh; }` and `cat run.sh | { BASH; }` still ask in every rule (probed).
2. **httpie and wget bodies.** httpie `--raw`/`--raw=` is a body. An httpie GraphQL call with no document returns found/no document, so it asks. wget `--body-data` reads as `--post-data`, `--body-file` as `--post-file`. I cut the `<` reading, and also the leading-shell-word skip in `rule_tracker_guard`: every row, test and the rewriting check hold without it.
   - Red before: `http POST https://api.github.com/graphql --raw '{"query":"mutation { closeIssue(…) … }"}'` was `silent`, expected `deny`.
3. **Redirect behind a continuation.** secret-shell's `_REDIRECT_RE` now runs on the line with every backslash and line break pair taken out, and only there.
   - Red before: `"test -f .env || cat .env.example > \\\n.env"` was `silent`, expected `deny`.

**Existing tests changed:** none. No test pinned the exception for an unread pipe. The 13 existing tables are untouched, and `ROWS_FIX2_ADD` matches the row file line for line (181 of 181, checked with `<SCRATCH>/eng3/table_match.py`).

**Checks:**
- ruff: `All checks passed!` / `ruff exit 0`
- 3.13: `7018 passed, 9 skipped in 69.23s`
- 3.9: `7018 passed, 9 skipped in 95.19s`
- Row files: 1,527 shell rows and 36 file rows hold; rows-b-fix2-add `146 | hold 146 | red 0`.
- rewrite_check: `weaker cells 35 | distinct commands 2 | crashes 0`
- rewrite_list: `turns: deny>ask 35`

The 35 cells are two commands (`echo 'git push --force origin feat' | $SHELL` and `echo 'git commit --no-verify -m x' | sh`), git-guard and protected-branch only. They sit only in the rewritings `pipesub`, `subpipe`, `bracepipe`, `suberrpipe` and `subnlpipe`, which the brief leaves out on purpose. No cell ends in silent.

**Deviations:** none. Rows left red: none.

**Seen and left out:**
- `echo 'ls' | { ssh -n build; sh; }` is silent now in six rules. `_nc_fed` reads the echo as the script, so the script is judged whichever command takes it. This follows decision 3 as written.
- `uv run` sat for about 30 minutes before each test run on the busy machine, though pytest itself took 69 s and 95 s. Nothing to do with the code.
- `VERSION` stays `"0.8.0"`.
