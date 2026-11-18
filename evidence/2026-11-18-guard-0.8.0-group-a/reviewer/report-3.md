findings: two MINOR findings, nothing weaker. No verdict is weaker than 0.7.1, `ae5361b` or `894b8cc`, and S1 to S4 are closed.

I probed 0.7.1, `ae5361b`, `894b8cc` and `135da2d` side by side. The candidates and timing scripts are in `<S8>/review/ra/` (`s1.txt`, `chains.txt`, `t1.txt`, `pieces3.json`).

**S1 to S4**
- S1: closed. Both commit-heredoc forms are back to the `ae5361b` verdicts (delete-guard ask only; silent).
- S2: closed. `# don't…`, `echo $'it\'s'; …`, and an inline `echo 'x' # it's ok` before a data here-document no longer deny.
- S3: closed. 8 to 20 ssh hops, piped or fed, take 0.00 s.
- S4: closed. Sibling scripts no longer inherit. `HUSKY=0 bash -c '…'; HUSKY=1 bash -c 'git commit -m x'` still denies, which is correct.

**New findings**

T1 | MINOR | stack walk, `case` inside `"$( … )"` (the engineer's own item) | guard.py:2629 | `git commit -m "$(case x in a) cat <<'EOF'⏎fix: "make; git push --force origin main"⏎npm install x⏎EOF⏎;; esac)"`: delete-guard ask at 0.7.1 and `ae5361b`; now git-guard deny as well (deny at `894b8cc` too). The data body is read as commands. The reverse, `echo "$(case x in a) bash <<EOF⏎git push --force origin feat⏎EOF⏎;; esac)"`, has git-guard silent at all four versions, so it is a script left unread but nothing weaker. `case x in (a)` is correct | as at `ae5361b` / deny | probe | The pattern's `)` pops the `(` of `$(`. Do not pop on a `)` that follows a `case … in` word or a `;;`, or count `case`/`esac` while inside a `(` context.

T2 | MINOR | cost, got worse | `_nc_take_heredocs` :2594 | 100 kB of comment lines `# <<A0⏎# <<A1⏎…`: 0.19 s at `894b8cc`, now 17.5 s plain and 35.7 s with a name in capitals. It fails closed: the budget turns it into an ask. From the quadratic figure, about 45 kB reaches 3.5 s (inference) | as at `894b8cc` | cost.py (pieces3.json) | Each skipped operator now runs a full `_HEREDOC_RE` search whose lazy body runs to the end of the text. Search for the bare operator first and run the full match only where the walk takes it.

**Looked at and found sound**
- Data bodies stay data (git-guard and host-install silent, only delete-guard's text match): quotes, apostrophes and backticks in a body; `"$(echo "a'b")"`, `$(echo "it's")`, `$((1+(2*3)))`, `${v:-'x'}`, `"${v#'}"`, `${#v} $# a#b`, backslash-newline, `` x=`cat <<EOF…` ``, a here-document inside backticks in double quotes, `printf` nested in `"$( … )"`, `f() { cat <<EOF; }`, two here-documents with quotes and `(` in the first body.
- Script bodies are still read, git-guard deny on every one: a shell fed inside `$( )` (quoted and unquoted), inside backticks, inside `( … )`, behind a comment line, after a here-document whose body holds `'`, `"`, `$(` or a backtick, after `')'`, `\'`, `"\""`, `$'\''`, `a#'b`, `$#`, `${#x}'`, and after a `case` inside `$( … )` that closes before the operator.
- `nested_envs` inherits through two levels, a pipe into the shell, a fed script, `env`, `timeout`, `xargs`, `sudo`, and a `$( )` inside the script. It does not inherit when the variable sits on the `echo` in front of the pipe, when the `$( … )` runs before the assignment, for `git status`, or for siblings.
- The engineer's first left-out item (`bash -c 'export HUSKY=0'; bash -c 'git commit -m x'` denies) already denied at `ae5361b` and `894b8cc`. It is a false deny, not a weakening; `bash -c 'export HUSKY=0'; git commit -m x` stays silent.
- No crash on 11 degenerate inputs: `\x00` and `\x01` from outside, a lone `$'`, a lone backtick, `((`, `))`, `#`, `\`, `$(`, `"$(`, a stray `)`.

**Cost** (`894b8cc` → now, in process):
- All first-round shapes are within noise, plain and with a name in capitals. `printf 'a;…' | sh` with a name in capitals measured 3.65 → 3.68 s; it was already over the budget at `894b8cc`.
- Walk-stress shapes are within noise too: many quotes then a here-document, many `"$(cat <<E…)"`, nested `"$(echo "$(…)")"`, quoted and double-quoted operators, backticks.
- The one exception is T2.

cloud: none
