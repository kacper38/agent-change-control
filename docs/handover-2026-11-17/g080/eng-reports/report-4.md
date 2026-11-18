S1, S2, S3 and S4 are closed in three commits on `894b8cc`. All five checkers exit 0 and the suite is green. Against `894b8cc`, only the Y forms and their kind change, and each goes back to its verdict at `ae5361b`.

**commits**
- `ee78e22` fix(guard): take a here-document in "$( … )" and skip comments
- `5d563c4` fix(guard): keep a shell's hook environment with that shell's script
- `135da2d` perf(guard): read a chain of ssh hops once, not once per hop

**done**
- **S1, S2:** the quote walk now keeps a stack of contexts. A here-document inside `$( … )` is taken, as at `ae5361b`; one inside a quoted script word is left to the nested read. Apostrophes in comments and in `$'…'` no longer open a quote. Tests: `test_row[Y1-*]`, `[Y2-*]`, `[Ys-*]` in a new `FIX2` table.
- **S4:** the inherited environment is no longer an injected `export`. It is carried per simple command (`nested_envs`), and nested scripts inherit it. Tests: `test_row[Y4-*]`, plus my own `Y5` rows (two levels deep, and a repeated script with a different environment).
- **S3:** only a quoted word holding white space is read as a remote command line, and that read is memoised. Tests: `test_a_chain_of_ssh_hops_is_read_in_bounded_time` (24 hops, a pipe and a here-document, bound 1.0 s in process, about 1000× headroom) and `test_a_chain_of_three_ssh_hops_keeps_its_verdicts`.

**checks**
- Suite: "5271 passed, 9 skipped" on Python 3.13; ruff and the static 3.9 check are clean. Python 3.9 was not run on this machine.
- Checkers: fix2 35/35, fix 76/76, fix-files 12/12, brief 597/597 and 66/66.

**Against `894b8cc`:** 909 commands (all row files, the test tables, plus everyday commit/PR bodies with quotes, apostrophes, backticks, comments and `$'…'`), branches feat/x and main, own and client boundary. 12 commands differ, all Y1/Y2/Y4 forms or their kind.

**cost** (in process, eight rules)

| shape | ae5361b | 894b8cc | now |
|---|---|---|---|
| `echo x \| ssh h0 … ls`, 16 hops | 0.00 s | 1.16 s | 0.00 s |
| same, 24 hops | 0.00 s | not run (too slow) | 0.00 s |
| `printf 'a;…' \| sh`, 100 kB, plain | 1.54 s | — | 1.66 s |
| same, capitals (`\| SH`) | 1.43 s | — | 1.37 s |
| `printf 'GIT;…' \| sh`, 100 kB | 2.57 s | — | 2.79 s |

**left_out:**
- `ssh build -T <<EOF` (an option behind the host) and the 100 kB shapes: not built, per your list.
- An `export` inside a nested script still counts for later git calls that the flat read lists after it.
- `)` of a `case` pattern inside `$( … )` can close the walk's context early.

**cloud:** none.
