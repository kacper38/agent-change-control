All six topics are fixed in 7 commits on `feat/guard-0.9.0`, ending at `d2ecce7`. Worktree: `<WT>`. The seventh commit is a follow-up to topic 1. Nothing is pushed, `VERSION` is still `"0.8.0"`, and only `tools/guard/guard.py` and `tools/guard/tests/test_table_forms.py` changed.

**Commits**
- `4a23f30` fix(guard): call a report quiet only on a line read completely (topic 1, plus `ROWS_FIX2`, `FIX2_TABLE`, `test_fix2_row`)
- `de0fe18` fix(guard): ask for a piped shell beside a closer or a line break (topic 2)
- `111870c` fix(guard): see the hook switch behind an option or a shell word (topic 3)
- `87b53f4` fix(guard): read the GitHub API host with a port and doubled slashes (topic 4)
- `00668a9` fix(guard): read httpie's stdin GraphQL body inside a group (topic 5)
- `8f78f02` test(guard): count the pattern readings instead of timing them (topic 6)
- `d2ecce7` fix(guard): keep a pipe behind an inner group handed on (topic 1 follow-up)

**Per topic** (code change; red line from `d1052b1`)
1. Rule 1 turns down a line with a bracket or backtick in a separator, or a `function`/`coproc`. Separators are read by their characters (`_plain_sep`). Closers must match their own opener. Red: `F33 … secret-shell=silent | "ls .env |\nxargs cat"`.
2. `_nc_compound_pipe` reads compacted separators, and a row of only redirections behind `)` counts as the closer. `_nc_pipe_shell` now also knows `$SHELL`, `${SHELL}`, `sudo -s|-i` and `su`. Red: `F28 … delete-guard=silent | "(cat run.sh) 2>/dev/null | bash"`.
3. `environment()` skips shell words, `time [-p]`, `command -p|--` and `builtin --`. It works on a list now, because the reader hands tuples. Red: `F30 … git-guard=silent | "command -p export HUSKY=0; git commit -m x"`.
4. A port is allowed in `_GITHUB_API_RE`. The GraphQL URL now also takes the port, the trailing dot and `/+`. In `gh api`, the GraphQL and merge paths take doubled slashes as one; the issue-write reading is untouched. Red: `F31 … tracker-guard=silent | "curl -X PUT https://api.github.com:443/repos/o/r/pulls/3/merge"`.
5. The `<` was lost in both passes: the first pass saw `{`, `(` or `then` as the head, and the reader pass drops redirections. The first pass of tracker-guard now skips those leading words. Red: `F36 … tracker-guard=silent | "{ http https://api.github.com/graphql < q.json; }"`.
6. The timing test now counts `_pattern_places` calls and wants exactly 1. With the planted `if True:` it fails with 833 readings, and the line is back as it was.

**Existing tests changed**: only the timing test, and its `time` import went with it. The twelve row tables are unchanged.

**Checks** (`d2ecce7`)
- ruff: `All checks passed!` / `ruff exit 0`
- Whole suite, Python 3.13: `6872 passed, 9 skipped in 45.40s`
- Whole suite, Python 3.9: `6872 passed, 9 skipped in 65.84s (0:01:05)`
- Every row file holds: 1,339 shell rows, plus 188 of 188 in `rows-b-fix2.txt`. The 36 file rows pass in the suite.
- `rewrite_check.py`: `weaker cells 18 | distinct commands 1 | crashes 0`
- `rewrite_list.py`: `turns: deny>ask 18`

The 18 cells left are all `echo 'git push --force origin feat'` going through a subshell or group into `$SHELL`. That is the case the brief allows to stay: reading that script there is not part of this round.

**Deviations**
- The follow-up `d2ecce7` should have been part of topic 1, but interactive rebase is not available here. Before it, the rewriting check showed 30 `ask>silent` cells such as `{ { ls .env; } | xargs cat; }`. Two constructs opened by the same command shared one index, and the outer closer overwrote the inner pipe. It is pinned by a new four-line test outside the row tables.
- The rows table went in with the topic 1 commit, so `4a23f30` through `87b53f4` carry red F28/F30/F31/F36 rows until each topic's own commit.

**Rows left red**: none.

**Seen and left as they are**
- The lexer cuts at a backtick even inside single quotes (`echo '`' .env`), so such a line now has no quiet report. That is on the asking side, and I left the lexer alone.
- A function body that is defined but never called before the commit is still read as exporting (`f() { export HUSKY=0; }; git commit`), which denies. That is on the denying side.
- Wrappers behind a group in tracker-guard's first pass (`{ sudo http …; }`) are not read; I did not touch them.
- The `case` pattern bar from topic 2 is not touched.

My scratch files are in `<S8>/eng2/`, including `rewrite.json` and `guard_d1052b1.py`.
