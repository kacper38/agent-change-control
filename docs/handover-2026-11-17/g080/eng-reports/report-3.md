**Fix pass: all four checkers exit 0, the suite is green, and only A-row forms changed against ae5361b**

Six commits on `ae5361b`, with the blocker A1 first and alone:
- `79c940a` fix(guard): let a later deny win over a first-pass ask in git-guard
- `28d7376` fix(guard): split glued redirections and mark unquoted input ones
- `dde8248` fix(guard): read more fed scripts and end a <<- body at its tabs
- `5e48d2e` fix(guard): follow the hook gate's environment into shells and exports
- `58f4d1a` fix(guard): fold a tool name in capitals inside an option's script
- `894b8cc` fix(guard): take the stricter secret class and curl's quoted path

**done**: all 76 shell rows sit in a new `FIX` table in `test_bypass_forms.py` (run by `test_row[A*]`/`test_row[As-*]`) and the 12 file rows in `FIX_FILES` (`test_file_row[A10-*]`/`[As-*]`). They were red first: 49 failed on `ae5361b`.
- **A1**: git-guard's first pass returns a deny at once and collects asks; the env gate and reader pass still run. No other rule's first pass returns an ask before a deny it could still find.
- **A2, A3, A11, A12**: `_hi_prepare` splits an unquoted `<`/`>` off the word in front of it (`2>&1` stays). For the reader it marks an unquoted input `<` (also `<>`) with `\x01`, so a quoted `'<.env'` is data again. `|&` counts as a pipe.
- **A4, A18**: the here-document take tracks quotes and leaves a quoted here-document to the nested read. `_HEREDOC_RE` ends a `<<-` body at a tab-indented closing line; its groups are renumbered (1 dash, 4 body).
- **A8, A9, A16**: new `_ssh_command`, `_sudo_runs_shell`, `_su_runs_shell`; `-O`/`--rcfile`/`--init-file` take a value; `/dev/stdin` is read; `$SHELL` counts. The words after an ssh host are read as a remote command line.
- **A5, A6, A15, A17**: hook-gate assignments in front of a shell go with its script as an `export`. The env gate tracks `export NAME`, `declare -x`, `typeset -x` and `set -a`. `--remove-section core`/`--rename-section core` ask. `--config-env` takes the next word as its value.
- **A7**: in a run that starts with `-`, the fold candidate starts behind the first quote.
- **A10, A14**: `secret_class` takes the stricter of its two readings. The quotes around a path behind `@` are taken off.

**checks**:
- Suite: "All checks passed!", "py39 check: 61 files, 0 finding(s)", "5227 passed, 9 skipped" on Python 3.13. Python 3.9 was not run on this machine.
- Fix checkers: 76/76 and 12/12, both exit 0.
- Brief checkers: 597/597 and 66/66, both exit 0.
- Against a copy of `ae5361b`: 859 commands (every row file, the test tables, extra noise forms), on feat/x and main, own and client boundary. Only A-row forms differ, plus one of their kind: `git --config-env user.name=NAME commit -m x` on main now denies in protected-branch, because the commit is found.

**existing_tests_changed**: none.

**deviations**: commits in between filtered the `FIX` table by id; the final head has none.

**left_out** (verdicts observed at the new head or at `ae5361b`; none built):
- `{ bash; } <<EOF … EOF` and `npx --no-install <tool>`: not built, per your list.
- `--no-verify` in an `alias.*` value: not built, per your list.
- `LEFTHOOK=false git commit -m x`: silent.
- `--exclude-from` as a file that is read: not built (decided in 4.1).
- `HUSKY=0 ssh build 'git commit -m x'` now denies, though ssh does not forward the environment.
- `npm INSTALL x` asks: `install` folds.
- `command -v codex` asks under a client boundary, as at 0.7.1.

**cost**, in process, eight rules, 100 kB, `ae5361b` → now (capitals means `BASH` or a leading `GIT status;`):

| shape | plain | capitals |
|---|---|---|
| `echo 'a;a;…' \| bash` | 1.60 → 1.56 s | 1.42 → 1.37 s |
| `bash <<EOF` tiny lines | 0.92 → 0.98 s | 0.43 → 0.46 s |
| echo line | 0.42 → 0.44 s | 0.88 → 0.93–1.07 s (noisy) |

All are within your ceilings.

**cloud**: none. The probes (cost run, `cp`) came back silent. I wrote one scratch output (`eng/diff_now.txt`) with a shell redirection.
