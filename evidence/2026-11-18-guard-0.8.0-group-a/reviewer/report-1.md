BLOCKER

I checked every finding with `probe.py` (0.7.1 against `ae5361b`) or with `expect_files.py`. Rows files are in `<S8>/review/ra/`. Line numbers refer to `<WT>/tools/guard/guard.py`. None of the forms below is measured in the semantics logs, so wherever a finding depends on shell or ssh behaviour, that behaviour is inference.

R1 | BLOCKER | git-guard | guard.py:1004-1007 with :953-954 | `git config core.hooksPath /tmp/h; git commit --no-verify -m x`: 0.7.1 deny, now ask. Same for `git config core.hooksPath /tmp/h && git push --force origin feat`, `git config core.hooksPath /tmp/h; git push --all origin`, and on main `git config --unset core.hooksPath; git push origin main` | deny | probe (l1b.txt, l7b.txt) | `_git_guard_seg` can now return an ask in the first pass, and the first-pass loop returns on the first verdict, so a later deny is never seen. Collect the asks, return a deny at once, and `combine` the rest.

R2 | MAJOR | fed script, redirection | :2519 and :2528 (the mark is glued to the name), :622 / :2405 | `bash<<EOF⏎git push --force origin feat⏎EOF`, `Bash<<EOF…`, `sh<<-EOF…`, `cat<<EOF|bash…`: git-guard silent. `cat<.env` and `done<.env`: silent | deny / ask | probe (l2, l3, l7) | The lexer does not split at `<`. Emit the mark with a space in front, and split an unquoted `<` off the word before it.

R3 | MAJOR | fed script | :2451 | `cat <<EOF |& bash…` and `echo 'git push --force origin feat' |& bash`: git-guard silent | deny | probe | Count `|&` as a pipe.

R4 | MAJOR | fed script, nested | :521 and :2509-2521 | `bash -c 'bash <<EOF⏎git push --force origin feat⏎EOF'` (also with double quotes): git-guard silent at 0.7.1 and now. The closing delimiter is followed by a quote, so the top-level take swallows the text to the end and leaves an unbalanced quote | deny | probe | Let the closing delimiter be followed by a quote, or leave a here-document inside a quoted word for the nested read.

R5 | MAJOR | git-guard, environment | :899-913 | `HUSKY=0 bash -c 'git commit -m x'`, `env HUSKY=0 sh -c 'git commit -m x'`, `HUSKY=0 bash <<EOF⏎git commit -m x⏎EOF`: silent | deny | probe (l4) | Hand the assignments in front of a shell whose script is read on to the git calls in that script.

R6 | MAJOR | git-guard, export | :906-908 | `HUSKY=0; export HUSKY; git commit -m x`, `declare -x HUSKY=0; …`, `typeset -x HUSKY=0; …`, `set -a; HUSKY=0; …`: silent | deny | probe | A bare `export NAME` exports an earlier `NAME=value`; read `declare -x` and `typeset -x` like `export`.

R7 | MAJOR | capitals | fold_names :2891 (the candidate run starts at the option) | `env -S'GIT push --force origin feat'`, `env --split-string='GIT push --force origin feat'`, `nix-shell --run='GIT push --force origin feat'`: silent. The lower-case twins deny | deny | probe (l7, l7b) | Also start a candidate after `=` and after a leading quote, or fold each script the reader takes out.

R8 | MAJOR | fed script, ssh | :2571 | `ssh -oStrictHostKeyChecking=No build <<EOF⏎git push --force origin feat⏎EOF` and `ssh -lNina build <<EOF…`: silent. The `N` test runs over the value glued to the option | deny | probe | Look for `N` only among the letters before the first letter that takes a value.

R9 | MINOR | fed script | :2072, :2362 | Silent: `bash -O extglob <<EOF`, `bash --rcfile f <<EOF`, `bash /dev/stdin <<EOF`, `cat <<EOF | bash /dev/stdin`, `sudo -s <<EOF`, `sudo -i <<EOF`, `sudo su <<EOF`, `su - deploy <<EOF`, `$SHELL <<EOF`, `echo … | $SHELL`, `{ bash; } <<EOF`. Also `ssh build -T <<EOF` (inference: OpenSSH reads options after the host) | deny | probe | Skip the values of `-O`/`--rcfile`, count `/dev/stdin` as stdin, and add `$SHELL` and `sudo -s|-i` to the shells that read stdin.

R10 | MINOR | secret class | :555-558 | `Read /Users/dev/.AZURE/prod.tfvars`: silent (`.azure` twin asks). `Write` of it asks instead of deny. `cat ~/.AZURE/prod.tfvars`: silent | ask / deny | expect_files (l8files.txt), probe | When the path as written is "tfvars", the lower-case "secret" never gets a look. Take the stricter class of the two readings.

R11 | MINOR | secret-shell, new false ask | :2405 (quoting is gone from the raw tokens) | `grep -n '<.env' README.md` and `echo "<.env"`: silent at 0.7.1, ask now | silent | probe | Recognise an input redirection only when it stands unquoted.

R12 | MINOR | secret-shell | :622 | `cat <>.env`: silent (it opens the file for reading) | ask | probe | Accept `<>`.

R13 | MINOR | secret-shell | :620 | `tar --exclude-from=.env …`, `grep -r --exclude-from=.env …`, `rsync --filter='merge .env'`: silent. These options name a file that is read. Decided in 4.1, but the brief asked | ask | probe, tool manuals (inference) | Drop `--exclude-from` from the pattern options.

R14 | MINOR | secret-shell | :646-648 | `curl -F 'file=@".env"' …`: silent (curl accepts a quoted file name; inference) | ask | probe | Strip quotes from the path after `@`.

R15 | MINOR | git config | :866 | `git config --remove-section core` and `git config --rename-section core old`: silent; both drop core.hooksPath | ask | probe | Ask when the `core` section is removed or renamed.

R16 | MINOR | cost | judged_twice :2918, reader | Eight rules in process, 100 kB, 0.7.1 → now (plain / capitals): `echo 'a;a;…' | bash` 0.70 → 1.51 / 3.09 s; `printf … | sh` 0.63 → 1.03 / 2.20 s; `bash <<EOF` with tiny lines 0.07 → 0.99 / 2.35 s; plain `a;a;…` 1.27 → 1.35 / 2.96 s. A line of `<<A0 <<A1 …` with no newline: 17.5 s at 0.7.1, 20.0 / 39.7 s now (`_HEREDOC_RE` is quadratic; the budget turns it into an ask) | under 3.5 s | cost.py | Bound the operator line in `_HEREDOC_RE`, and skip the second reading for rules whose input text is unchanged.

R17 | MINOR | egress, client boundary | _NC_* tables | `npx --no-install codex x`: silent, also at 0.7.1 | ask | probe | Make npx a reader wrapper.

R18 | MINOR | git-guard | — | `git -c alias.ci='commit --no-verify' ci -m x`: silent, also at 0.7.1 | deny | probe | Read a `--no-verify` inside an `alias.*` value.

**Looked at and found sound:**
- Line 1: about 100 forms (secret, git, gh, deploy, install, here-document neighbours, `$( )`, `bash -c`) give the same verdict as 0.7.1, apart from R1.
- Line 5: gh `-R`/`--repo` in every spelling and position, and the `gh api` method and write flags, all hold. The reads stay silent.
- Line 6: egress through wrappers, nesting, containers and fed scripts asks; names that are not command words stay silent.
- Line 7: `foldcheck.py` checked all 180 tool names from the tables and the code comparisons (capitals, title case, path in front); every one folds. Paths, quotes, backslashes, separators, `$( )`, `xargs` and `-exec` fold too. Everyday capitals: only the accepted `RM` commit message differs.
- Line 8: hosts and file names in capitals behave as designed, apart from R10.
- Reverse direction: data here-documents (`cat > f`, `python3 -`, `psql`, `tee`, `curl -d @-`, `ssh host 'cat > f'`, a script-file operand) and everyday git commands stay silent.

**Not done:** timing through `guard.py hook` (my figures are in process, without process start); no test file run; Python 3.9 not run.

cloud: none
