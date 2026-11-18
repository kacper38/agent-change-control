**Report: guard 0.8.0 group A, steps 3 to 10**

Steps 3 to 10 are done, one commit each, on top of `8007462`. Both checkers exit 0 on every row: 597 of 597 shell rows and 66 of 66 file rows hold. The suite is green on Python 3.13. Python 3.9 was not run on this machine; the static 3.9 check is clean.

**stopped_after:** step 10. Step 11 needs the orchestrating session to run `tools/guard/tests/make_fixtures.py`. I suggest two cases for `CASES` (rule → `shell(decision, …)` lists):
- In `CASES["delete-guard"]`, as an `ask`: `echo 'rm -rf build' | bash` (the fed script of step 3).
- In `CASES["git-guard"]`, as a `deny`: `GIT commit --no-verify -m x` (capitals, step 10).

If `shell()` does not already write a case for each harness, both need a Claude and a Copilot entry.

**done:** all proved by tests in `tools/guard/tests/test_bypass_forms.py`.
- 3. The reader reads a script fed to a shell: a here-document body, or an `echo`, `printf` or `cat <<EOF` piped once into a shell that reads standard input, also behind wrappers or in a container. It also reads `ssh host` with no command after the host. Helpers: `_nc_take_heredocs`, `_nc_fed`, `_nc_runs_stdin`, `_ssh_reads_stdin`. Tests: `test_row[N1-*]`, `[N2-*]`, `[N3-*]` and `test_own_row[X3-*]`.
- 4. tracker-guard finds `gh` writes past `-R`/`--repo` in every spelling, and reads every spelling of the `gh api` method and write flags (`_gh_words`, `_gh_api_mutating`). Tests: `O1`, `O2`, `X4`.
- 5. git-guard reads short option clusters and long options cut short (`_git_options`, `_git_prefix`). delete-guard asks for `git push -d`, `--delet` and `--prune` (`_git_push_deletes`). Tests: `P1` to `P3`, `X5`.
- 6. git-guard denies `HUSKY=0`, `LEFTHOOK=0` and `SKIP=` in front of a git call or exported earlier, and `core.hooksPath` set for a call by `-c`, `--config-env` or `GIT_CONFIG_*`. `git config` writing that key asks. Tests: `P4`, `P5`, `X6`.
- 7. egress-guard now has the reader pass, so wrappers, nested scripts, containers and other hosts count. Tests: `E1`, `X7`.
- 8. `_LLM_HOSTS_RE` ignores case. Tests: `C1` rows of `CAPS`, `X8`.
- 9. `secret_class` uses the class of the path as written, else the class of the path in lower case. Tests: `C4` rows and `test_file_row[F1-*]` (Ft and Fs too).
- 10. `fold_names`, `_FOLD_NAMES` and `judged_twice` wrap the eight shell rules; the script scan also reads the folded content. Tests: `C2` and `C3` rows, `X10`, `test_every_known_name_folds_from_capitals`, `test_fold_names`, `test_a_command_without_a_capital_name_is_judged_once`, `test_a_command_with_a_capital_name_is_judged_twice`, `test_a_deny_of_either_reading_wins`, `test_the_eight_shell_rules_judge_both_readings`, `test_a_script_named_by_the_command_is_scanned_folded`.

**commits:**
- `cacf8ab` feat(guard): read a script fed to a shell as a script
- `699ac00` fix(guard): find gh issue and api writes past gh's repo option
- `4b4d188` fix(guard): read git's short clusters and cut long options
- `fd21093` fix(guard): deny the hook gate turned off by env or config
- `b094e57` fix(guard): read egress through wrappers, nests and containers
- `e74a4bd` fix(guard): match LLM API hosts whatever their case
- `d3044f2` fix(guard): class a secret file name in capitals as the name
- `48eeed6` fix(guard): judge a tool name in capitals like the plain name

**checks (last suite run, at `48eeed6`):**
- ruff: "All checks passed!"
- static 3.9 check: "py39 check: 61 files, 0 finding(s)"
- pytest 3.13: "5133 passed, 9 skipped in 54.61s"
- pytest 3.9: not run (no 3.9 interpreter on this machine)
- `expect.py`: "total rows 597 | hold 597 | red 0", exit 0
- `expect_files.py`: "total rows 66 | hold 66 | red 0", exit 0

After step 7 the checker on `rows-a.txt` plus `rows-a-added.txt` gave 239 of 239, exit 0. Every s, Ct, Cs, Ft and Fs row held at every commit.

**red_first:**
- 3: `RED N1 git-guard expected deny, got silent | "bash -s <<'EOF'\ngit commit --no-verify -m x\nEOF"`
- 4: `RED O1 tracker-guard expected deny, got silent | "gh -R o/r issue close 3"`
- 5: `RED P1 git-guard expected deny, got silent | "git push -uf origin feat"`
- 6: `RED P4 git-guard expected deny, got silent | "HUSKY=0 git commit -m x"`
- 7: `RED E1 egress-guard expected ask, got silent | "timeout 60 codex exec …"`
- 8: C1 `curl https://API.OPENAI.COM/…` was red (part of the 180 red rows of the caps file)
- 9: `RED F1 Read secret-read expected ask, got silent | .ENV`
- 10: `RED C4 secret-shell expected deny, got ask | "CP config.txt .ENV"`

**existing_tests_changed:** none. In my own module I changed one line: the count test now counts only the PINNED rows, because the `Cs` ids also end in `s`.

**deviations:**
- Step 3's subject uses `feat`; the other steps use `fix`.
- Every rule now hands the reader the unstripped command. `_truncate_in_the_open` therefore reads unstripped too: stripping a second time read the next line as a body (`test_false_asks` case 78 caught it).
- The here-document marks use NUL characters. A command that already holds a NUL is stripped as before, and no body is read as a script.
- The literal name set also holds `export`, `coproc`, `source`, `del`, `rd` and `ssh`. Folding them can only add asks.
- `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` comes from my own session instructions. I added the `Claude-Session` line as your message asked.
- My first Bash call ran a `cd` into the worktree; it was read-only.

**left_out (observed at `48eeed6`):**
- `npm INSTALL x`: host-install asks. It is new: `install` is a known name (coreutils, in `_WRITERS_LAST`), so it folds, although npm refuses `INSTALL`.
- `git PUSH --force origin main`: silent (verbs are not folded, by design).
- `curl -X PATCH https://API.GITHUB.COM/repos/o/r/issues/3 -d x`: tracker-guard silent (undecided by the owner).
- `ssh build 'bash -s' <<EOF … EOF`: silent (the quoted remote command is not treated as a shell reading stdin).
- `cat <<-EOF` with a tab-indented closing line, followed by `git commit --no-verify`: silent. `_HEREDOC_RE` does not end a `<<-` body at a tabbed closing line; this was true at 0.7.1 too.
- `LEFTHOOK=false git commit`: silent (only `=0` is in the brief).
- `G=git; $G commit --no-verify`: silent (out of scope).
- `command -v codex`: egress-guard asks, as at 0.7.1 (`segments()` drops `command -v`).
- `cat <<A <<B` with a second, data body: git-guard denies, as at 0.7.1.

**timing (one `hook pre` call, median of 5, before → after):**

| command | 0.7.1 | now |
|---|---|---|
| plain | 65 ms | 71 ms |
| longest row (99 B) | 63 ms | 66 ms |
| 100 kB | 459 ms | 491 ms |
| 100 kB with a name in capitals | 466 ms | 1010 ms |

The capitals case costs twice as much because of the second reading.

**files:**
- Changed: `<WT>/tools/guard/guard.py`, `<WT>/tools/guard/tests/test_bypass_forms.py`
- Scratch, under `<SCRATCH>/g080/eng/`: `timerows.py`, `hooktime.py`, `timing.json`, `leftout.txt`, `cases1.json`, `cases2.json`, `msg3.txt` to `msg10.txt`

`git -C <REPO> status --short` shows only `?? .claude/worktrees/`.

**cloud:** none. No call was refused, and both probes (the `commit_msg.py` check and the `hooktime.py` run) came back silent.
