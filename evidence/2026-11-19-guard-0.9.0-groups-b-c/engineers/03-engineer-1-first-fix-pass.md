All 18 fix topics and addenda 1 to 5 are done in 22 commits on `feat/guard-0.9.0` (8879cd5..d1052b1). The whole suite is green and every due row holds; no row is left red.

**Checks**
- `suite.sh`: ruff clean; 6680 passed and 9 skipped on Python 3.13, the same on 3.9.
- Every row holds: rows-b-fix 267, add 28, add2 31, add3 14, add4 22, add5 9, and the 968 + 36 build rows.
- All 241 flags of `options.tsv` in front of `TOKEN .env` ask.
- F21: a 100 kB line answers in 0.09 s on 3.13 and 0.16 s on 3.9; with `ollama run m` at its end it asks.
- Main checkout shows only `?? .claude/worktrees/`. `VERSION` is still "0.8.0". No push, nothing installed, nothing deleted.

**Commits, what changed, red line before the fix**
- 9b917e5 (T1, F09/F10): only `--exclude*` skips its value; added a per-tool option table. Red: `grep -r --include .env TOKEN .` silent.
- 430691f (T2–4, F11–13): `_compound_outputs`; no quiet report on a line the lexer cannot split or that uses `$_`. Red: `{ ls .env; } | xargs cat` silent.
- 9373047 (T5, F14): `_git_dry`, where the last of the dry-run options wins. Red: `git clean -n --no-dry-run -fdx` silent.
- e991d9d (T6, F15): `_restore_index_only` reads `--worktree` prefixes. Red: `git restore --staged --work f.py` silent.
- 16133b5 (T7, F21): `_pattern_places` works once per line, with bisection and one verdict per segment. Red: 20 kB took over 180 s.
- e8a7449 (T8, F07/F08): tool name read lowered; a hit is placed by its first word. Red: `GREP -E 'a|openai|b' notes.txt` asked.
- 5dc9a0a (T9, F01): the env word goes through `tool_name` and is lowered. Red: `genv -S 'rm -rf build'` silent.
- 8af7648 (T10, F02/F03): `_nc_compound_pipe`; fish and ash added to `_PIPE_SHELLS`. Red: `(cat run.sh) | bash` silent.
- 40657f5 (A1, F22): three readings of an option (`_SEARCH_OPTIONS`, `_search_option`). Red: `rg --mmap TOKEN .env` silent.
- f7e92b4 (A2, F23): `_quiet_reports` lexes the line after `_hi_prepare`; `(` behind a closer counts as piped. The lexer is unchanged. Red: `ls .env 2>&1 | xargs cat` silent.
- 92b8b01 (A3, F24): flag and value lists for `git clean` and `git worktree prune`; anything unknown means no preview. Red: `git clean --excl -n -f` silent.
- 4d34a14 (T11, F04): `-h` is not a help probe under `gh auth`. Red: `gh auth token -h github.com` silent.
- dba0e64 (T12, F05): all query fields are read; `$`/backtick values, `--input`, httpie stdin and `query:=` handled; `/graphql` and the full URL accepted. Red: `gh api graphql -f query="$(cat q.graphql)"` silent.
- 36ebe3e (T13, F06): op, security clusters, aws dotted names and batch-get, kubectl spellings, bare `doppler secrets`. Red: `op item get GitHub` silent.
- a7806d5 (T14, F16): doppler added to `_NC_SCRIPT_OPTIONS`. Red: `doppler run --command 'rm -rf x'` silent.
- c9de11c (T15, F17): curl `-T` is PUT, httpie method in any case, `_github_api_path`. Red: `curl …/pulls/3/merge -T body.json` silent.
- 60975d6 (T16, F18): ref name compared without case. Red: `git update-ref refs/heads/Main abc123` silent.
- fa08ee1 (T17, F19): reads past `builtin`/`command`; a name exported before its assignment counts. Red: `builtin eval 'export HUSKY=0'; git commit -m x` silent.
- a2d4414 (T18, F20): `caps_verbs` takes any capital. Red: `brew Uninstall jq` silent.
- 9f8db14 (A4, F25): bare `--context` is now unknown (`glued_longs`). Red: `grep --context TOKEN .env` silent.
- c1799d6 (A4, F26): `_git_status_verbose`. Red: `git status -v .env` silent.
- d1052b1 (A5, F27): `_delete_only_with` reads `-modcache=value`. Red: `go clean -modcache=true` silent.

**Existing tests changed:** only the P2 row in `test_review_fixes.py`. Its expected answer went from ask to silent in 9b917e5 (`-A 3` is now read as a value, so the pattern is no path). In A1 only its comment changed. My A1 choice: keep a table of value options, rather than giving up at every option outside the flags.

**Deviations from the order**
- Topics 2–4 are one commit (one function).
- One Bash call ran `cd` into the worktree to run the tests.
- One empty no-op here-document ran; it wrote nothing.
- T12 asks for any query value that starts with `$`, not only `$'…'` with an escape.
- T7's red line comes from a background run, not a pytest failure line.

**Seen and left out**
- The issue-write deny on curl/httpie still matches `api.github.com/repos/` literally, so `//` and the trailing dot are not read there.
- A GraphQL body piped into httpie (`cat q.json | http …`) is not seen.
- BSD-grep options other than `--context` are not compared with GNU grep.
- ag and ack have no list of value options, so any option outside their flags asks.
- `export HUSKY=0; HUSKY=1; git commit` now denies, because the older value stays in the list.

**Topic 19 (Fm): I keep both conditions**
- `not any(t.startswith("-") …)` in `_delete_preview`: an option in front of the help word can take it as its value (`kubectl delete -f --help` names a file).
- `if not _SEP_RE.search(p): continue` in `_pattern_places`: without it, `text.find` would also find a real later `'ollama' run m` as a pattern span and drop it from the first pass.

Scratch scripts are in `<S8>/eng/`. Code: `<WT>/tools/guard/guard.py`; the new tables are in `<WT>/tools/guard/tests/test_table_forms.py`.
