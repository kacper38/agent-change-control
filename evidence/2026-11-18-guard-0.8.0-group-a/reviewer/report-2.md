findings: nothing passes that 0.7.1 or `ae5361b` stopped, but the fix adds three MAJOR problems: two false prompts on everyday commands, and an exponential cost.

I probed 0.7.1, `ae5361b` and `894b8cc` side by side. Candidate files and timing scripts are in `<S8>/review/ra/` (`s1.txt`, `chains.txt`, `timelines.py`, plus the first-round files).

**R1 to R15**
- R1: closed. The `git config core.hooksPath …; <denied git>` rows deny again, on main and on feat.
- R2: closed (`bash<<EOF`, `sh<<-EOF`, `cat<<EOF|bash`, `cat<.env`, `done<.env`).
- R3: closed (`|&` after `cat <<EOF` and after `echo`).
- R4: closed (`bash -c 'bash <<EOF…EOF'`, single and double quotes).
- R5: closed.
- R6: closed (`export NAME`, `declare -x`, `typeset -x`, `set -a`, `set -o allexport`).
- R7: closed (`env -S'RM …'`, `--split-string='NPM …'` now ask).
- R8: closed.
- R9: partly closed. `ssh build -T <<EOF⏎git push --force origin feat⏎EOF` is still silent (inference: OpenSSH parses options after the host). `{ bash; }` was accepted.
- R10: closed (file rows 18 of 18 hold).
- R11: closed (`echo "<.env"` and `grep -n '<.env'` are silent again).
- R12: closed (`cat <>.env` and `cat 0<>.env` ask).
- R13: not built, as agreed.
- R14: closed.
- R15: closed.

**New findings**

S1 | MAJOR | quote walk of the here-document take | guard.py:2574 and :2603 | Claude Code's own commit form with double quotes in the body: `git commit -m "$(cat <<'EOF'⏎fix: run "make; git push --force origin main" later⏎EOF⏎)"` was delete-guard ask at 0.7.1 and `ae5361b`; now git-guard deny as well. `…fix: quote the "name⏎npm install left-pad is gone⏎EOF⏎)"` was silent; now host-install ask | as before | probe | The `<<` stands inside `"…"`, so the top level leaves the body in the text. The lexer does not know `$(…)` and reads the body's quotes as closing the outer quote, so the body is lexed as commands. When the operator stands in a `$( … )` inside double quotes, take the body at the top level as `ae5361b` did, or skip the whole `$( … )` in `_quote_state` the way `_hi_prepare` does.

S2 | MAJOR | quote walk | :2603 | `# don't run this⏎cat <<EOF > notes.txt⏎git push --force origin main⏎npm install x⏎EOF`: was delete-guard ask, now git-guard deny and host-install ask. `echo $'it\'s'; cat <<EOF > notes.txt…` now denies too. The data body is read as commands | as before | probe | `_quote_state` counts an apostrophe inside a comment and inside `$'…'`. Skip comments there the way `_hi_prepare` does, and treat `$'…'` with backslash escapes.

S3 | MAJOR | cost, exponential | `_nc_runs_stdin` :2667 with `_ssh_command` :2688 | `echo x | ssh h0 ssh h1 … ssh h17 ls` (about 150 bytes): 0.00 s at `ae5361b`, now 1.14 s at 16 hops, 5.2 s at 18, 18.8 s at 20. The same with `ssh … ls <<EOF⏎x⏎EOF` at the end: 5.15 s at 18 hops. A short command goes over the 3.5 s budget, so the budget turns it into an ask | linear | timelines.py | Each ssh recurses into the words after its host, and so does every later ssh in them. Check the remote words once, for example only at the first ssh command word, or memoise.

S4 | MINOR | export put in front of a nested script | `_nc_hook_env` :2650 with `_git_env_gate` :913 | `HUSKY=0 bash -c 'echo ok' && bash -c 'git commit -m x'`: silent before, now git-guard deny. Same with `HUSKY=0 bash <<EOF⏎npm test⏎EOF⏎bash -c 'git commit -m x'` | silent | probe | The prepended `export` lands in the list of exports for the whole line and reaches a sibling script. Keep the exports of a nested script inside that script.

**Looked at and found sound**
- The `<`/`>` split gives the same verdict as before on: `2>&1`, `>&2`, `&>`, `>|`, `<&-`, `<(…)`, `$((1<<4))`, `$((a<b))`, `[[ a < b ]]`, `->`, `=>`, here-strings, HTML and generics in quoted arguments, `awk '$1<3'`, `sort <in >out`, `wc -l <README.md`.
- The new `_HEREDOC_RE`: a `<<-` body now ends at a tab-indented closing line. In a plain `<<`, a line `\tEOF` does not end the body, and neither does a line `EOFX`.
- The fold's new start on a quoted option value (`--grep='Git fix'`, `-l'app=Helm'`) changes no verdict.
- `sudo -s`, `su … -c`, `ssh build 'cat > f'` and `ssh build tee f` with a data body stay silent apart from delete-guard's text match. `ssh build 'cd app && bash' <<EOF` is now read.
- No crash in 22 degenerate inputs: `\x00` and `\x01` arriving from outside, a bare `<`, a bare `>`, `set -o`, a bare `export`, a bare `ssh`, `echo x | sudo`, `$((1<<`, an unbalanced `<<'EOF`.

**Cost** (100 kB, eight rules in process, `ae5361b` → `894b8cc`):
- Every shape is within about 0.1 s of `ae5361b`, plain and with a name in capitals.
- One figure got worse: `printf 'a;…' | sh` with a name in capitals went from 3.09 to 3.59 s, now over the 3.5 s budget. Other shapes I timed sit close to it: `echo 'a;…' | bash` with a name in capitals 3.38 → 3.32 s.
- `<<A0 <<A1 …` without a newline is still about 20 s plain and 40 s with capitals, as at 0.7.1 and `ae5361b`.

cloud: none
