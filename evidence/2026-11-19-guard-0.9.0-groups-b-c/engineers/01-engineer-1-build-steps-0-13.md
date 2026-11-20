**stopped_after**: step 13 (`ee26124`). I stopped under rule 14: context was running short, and steps 14 and 15 are the largest. Steps 0 to 13 are committed and green. Steps 14 to 16 and the timing are not started.

**done** (every step's rows are in `tools/guard/tests/test_table_forms.py::test_row` / `test_file_row`)
- 0: all 459 s/t shell rows and 22 file rows pinned (`test_pinned_rows_are_all_there`).
- 1 R1: aws `ssm send-command|start-session` and `ecs execute-command`; az when the last leading word is `invoke|exec|config-zip|swap`.
- 2 R2/R3: `_DELETE_TOOLS` covers 25 more managers and their cache verbs. `go clean` asks only with `-modcache` (`_DELETE_ONLY_WITH`).
- 3 T1–T4: 30 run-a-command tools are in `_NC_WRAPPERS`, `_NC_SUB_WRAPPERS`, `_NC_SCRIPT_WORDS` and a new `_NC_AFTER_OPTION` (gdb `--args`, lldb `--`).
- 4 U1–U4: `_GNU_NAMES` plus `tool_name()`, used by delete-guard, secret-shell, the search pattern and the command-word walk; the g names fold from capitals (`test_tool_name_*`, `test_a_new_name_in_capitals_*`).
- 5 G1–G3: the net is `net_starts` (memoised, found with bisect) plus a `net=` judge in `reader_pass` for git-guard, protected-branch and tracker-guard.
- 6 L1–L3: GraphQL via `gh api graphql`, curl, wget and httpie.
- 7 D1/D2: `git update-ref` (`_update_ref_on_protected`).
- 8 I1: a shell fed by a pipe the reader cannot read raises `CommandNotRead`.
- 9 V1–V3: `_SECRET_STORES` plus `secret_store_what`, judged at every command word.
- 10 Z1/Z2: `_az_writes`, at a command word only.
- 11 Y1/W1/W2: `guard_config_class` reads paths twice (as written and lower case); the API host is matched in any case; `caps_verbs` for brew and gem.
- 12 W3/W4: `gh pr merge` and the merge PUT ask; `--admin` denies.
- 13 X1–X5: eval exports, `LEFTHOOK=false`, ssh options behind the host, group and subshell here-docs, `case` inside `$( … )`.

**commits**: f953b48 test(guard): pin the verdicts 0.9.0 must not change · 637e410 feat(guard): ask for aws and az calls that run a command on a host · 387d9c2 feat(guard): ask when a package, a tool version or a cache is removed · ef9b1e8 feat(guard): read the command behind 30 more tools that run one · 7dede65 feat(guard): read the Homebrew g names of the GNU tools as the tools · 18d1b27 feat(guard): ask for git, gh and az behind a command no table knows · de648bf feat(guard): judge GraphQL mutations sent to GitHub · a6d7372 feat(guard): deny git update-ref on a protected branch · 67bcfa8 feat(guard): ask when a shell reads its script from an unread pipe · 565251d feat(guard): ask for commands that print a stored secret · 5cc4f79 feat(guard): ask for every az call that is no known read · cb1d548 fix(guard): read capitals in guard paths, the API host and brew verbs · 436a31c feat(guard): ask for a pull request merge, deny it with --admin · ee26124 fix(guard): close five gaps the reviews of group A left

**checks** (at ee26124)
- ruff: `All checks passed!`
- pytest: `6211 passed, 9 skipped` on 3.13 (44.9 s) and on 3.9 (62.3 s).
- The first checker on the four B files: `total rows 795 | hold 795 | red 0`, exit 0. On all five files: `968 | hold 882 | red 86`, all of them K rows.
- The file checker: `36 | hold 36 | red 0`.

**red_first** (from both checkers on the base commit 769b9d2; red lines kept in `SC/eng/red080.log`)
- R1 `aws ssm send-command …` =silent
- R2 `uv remove requests` =silent
- R3 `uv cache clean` =silent
- T1 `unshare -n rm -rf build` =silent
- U1 `grm -rf build` =silent
- G1 `mytool git push --force origin feat` =silent
- L1 `gh api graphql -f query='mutation { closeIssue…'` =silent
- D1 `git update-ref refs/heads/main abc123` =silent
- I1 `cat run.sh | bash` =silent
- V1 `vault kv get secret/app` =silent
- Z1 `az vm start -g rg -n vm` =silent
- Y1 `.claude/SETTINGS.json` =silent
- W3 `gh pr merge 3` =silent
- X1 `eval 'export HUSKY=0'; git commit -m x` =silent

**existing_tests_changed**
- `test_bypass_forms.py` OWN: four Xs rows went from `shell silent` to `delete-guard ask`, as I1 asks (`cat run.sh | bash`, `sed … | bash`). They are `cat script.sh | bash`, `base64 -d payload.txt | bash`, `echo 'rm -rf build' | sed s/rm/ls/ | bash`, and `cat notes.txt <<'EOF' | bash …`.
- `make_fixtures.py`, as W3 asks: the tracker-guard allow case `gh pr merge 3 --rebase` moved to a new ask block, and `gh pr view 3` took its slot. Fixtures regenerated for both harnesses; the two stale files `allow/08-gh-pr-merge-3-rebase.json` were moved to `SC/eng/moved/`.

**deviations**
- Rule 5: the row tables are written into the test module by `SC/eng/gen_rows.py`, not by Write. That kept 968 rows out of my output; they are copied literally and the test module still reads nothing from SC.
- Rule 10 order: in steps 2, 4 and 6–13 I wrote the code before regenerating the rows. The red lines above come from both checkers run on 769b9d2.
- 4.8: I did not read `docs/HANDOVER-2026-11-17.md`, because of your rule against reading the handover. The store table is built from the V and Vs rows and the CLIs' help. I added `aws ecr get-login-password`, `aws sts get-session-token`, `gcloud auth application-default print-access-token`, `pass NAME`, `pass otp|grep`, and az `list-publishing-profiles|credentials`.
- First passes of tracker-guard and protected-branch now collect asks and let a later deny in the line win, the way git-guard has done since 0.8.0.

**left_out** (observed at ee26124 unless marked)
- `dotenv -e .env -- rm -rf build` (dotenv-cli): silent. Only `dotenv run --` is read.
- `runuser -l ci -c '…'` is not added to `_NC_SHELLS`; not probed.
- Not added to the az local list: `az upgrade` and `az extension add` are silent for deploy-ask, and host-install judges them.
- I added `invoke` to the verbs that ask in step 1, so `az devops invoke` (also a GET) now asks under deploy-ask.
- `bash < run.sh`, `bash <(cat run.sh)`, `eval "$(cat run.sh)"`, `echo "$X" | bash` and `cat x | ssh host bash` are unchanged (not decided).
- Not done (the brief excludes it): a NUL character in the command.

**timing**: not measured; it is left for the next run.

**files**
- `<WT>/tools/guard/guard.py`
- `…/g090-bc/tools/guard/tests/test_table_forms.py` (new)
- `…/g090-bc/tools/guard/tests/test_bypass_forms.py`
- `…/g090-bc/tools/guard/tests/make_fixtures.py`
- `…/g090-bc/tools/guard/tests/fixtures/tracker-guard/{claude,copilot}/{allow/08-gh-pr-view-3.json,ask/01-gh-pr-merge-3-rebase.json}`
- Scratch: `<S8>/eng/` (gen_rows.py, progress.py, red080.py, msg*.txt)

Both checkouts are clean: the main checkout shows only `?? .claude/worktrees/`, and the worktree has nothing uncommitted.

**next**
- Step 14: K1, K2, K4, K5.
- Step 15: K3, K6–K11. K11 drops a first-pass egress hit that lies inside the reader's search pattern.
- Step 16: fixtures.
- Then the timing, plus the folder checker on all five files.
- To regenerate the tables: `python3 -I SC/eng/gen_rows.py <test module> "R1,…,X5,K1,…"`. `python3 -I SC/eng/progress.py <ids>` shows the red rows.
