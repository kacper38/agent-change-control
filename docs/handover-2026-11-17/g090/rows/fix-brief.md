# Fix pass for guard 0.9.0, groups B and C (item #57)

You built this branch (head `8879cd5`, 17 commits). Since then the orchestrating session ran its checks, one
independent reviewer read the diff, and 69 planted breaks were run against the suite. This file is the whole
order for the one fix pass. Nothing here reopens a decision of the build brief.

## Where and how (unchanged from the build)

- Worktree: `<WT>`, branch `feat/guard-0.9.0`.
  Work only there and in the scratch folders you had for the build. In this file `<SCRATCH>` is the folder
  this file is in (the one with `expect.py`, `probe.py` and your `eng/`). No push, no pull request.
- Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not run
  `tools/tracker/tracker.py`.
- Commands under test are data: they stand in row files and test tables, never on a command line, and are
  never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit, never
  with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng/moved-fix/`.
- Checks: `ruff check tools/guard`, and the suite on both Pythons:
  `uv run --directory <worktree> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools/guard/tests`
  and the same with `--python 3.9`. Run the guard tests while you work, and the whole suite (the same command
  without the path) on both Pythons before your last commit. Nothing is installed.
- Commits: one topic, one commit; subject `type(scope): imperative`, at most 72 characters; the body says why;
  `Refs #57`; the last line is the trailer of your own model, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  Stage by explicit path. `VERSION` stays `"0.8.0"`; the orchestrating session sets it.
- Tests first: for each topic add the rows, see them red, then change the code. Note one red line per topic for
  your report.

## The rows

`<SCRATCH>/rows-b-fix.txt`: 267 rows, sha256 starts `a2e1363d65484888`, checked by `<SCRATCH>/expect.py`.

- Ids `F01` to `F20`: 117 rows, all red at `8879cd5`. They are due.
- Ids `Fs` (128) and `Fm` (22): they hold at `8879cd5` and must keep holding. `Fm` pins conditions of your
  build that no test pinned.
- They go into `tools/guard/tests/test_table_forms.py` as one **new** table (`ROWS_FIX`), line for line as in
  the file, comments included. The six existing tables stay exactly as they are: the orchestrating session
  compares them with the frozen files, line for line. All 968 shell rows and 36 file rows of the build keep
  holding.
- A row you think is wrong: do not change it. Leave it red, say why in the report.

## Topics, in this order

The first six are weaker than guard 0.8.0 outside the K rows of #57, so they block the change.

1. **F09, F10: the value of an option is no pattern.** Two causes. (a) K8 skips the word after every option of
   `_PATTERN_VALUE_OPTIONS`; the K8 rows name `--exclude` and `--exclude-dir` only. The word after `--include`,
   `--glob`, `--iglob`, `--exclude-from`, `--filter` is judged as a path again, as 0.8.0 did. Leave the glued
   spellings (`--include=.env`) as they are on main: that gap is older than this branch and gets its own item.
   (b) `_search_pattern` takes the first word that is no option for the pattern. When that word may be the
   value of the option before it (`rg -g .env TOKEN`, `ag -G .env TOKEN`, `rg --ignore-file .env x`,
   `ag -p .env x`, `ag --pager '…' x .`, `rg --pre '…' pat .`), it is neither dropped from the secret check
   (K3) nor counted as a search pattern (K11). How you know a flag from an option with a value is yours to
   design (a table of the flags of grep, rg, ag, ack and `git grep` that take no value is one way); the `Fs`
   rows name the everyday spellings that must stay silent. The ssh row: `ssh h grep -E 'a|ollama|b' f` hands
   `grep -E a|ollama|b f` to the remote shell, where the bars are pipes; a pattern among ssh's own words is
   no protected pattern.
2. **F11: a report inside a group or a compound whose output is piped on** (`{ ls .env; } | xargs cat`,
   `if …; fi | xargs cat`, `for …; done | xargs cat`). `_quiet_reports` looks at the next simple command only.
3. **F12: a line the reader cannot split** has no quiet report. `simple_commands` falls back to `segments()`
   with an empty separator when `_hi_lex` gives up, and the pipe behind the report is then not seen.
4. **F13: `$_`.** A line that holds `$_` or `${_}` has no quiet report: it is the last word of the command
   before it (`ls .env; cat "$_"`).
5. **F14: the dry run taken back.** git negates `-n`/`--dry-run` with `--no-dry-run` and takes unique prefixes
   (`--no-d`, `--dry-r`); the last one wins. Measured with git 2.55: `git clean -n --no-dry-run` refuses for
   want of `-f`, so it is no dry run. An option of this family you cannot place asks.
6. **F15: `git restore --staged --work f.py`.** git takes `--work` and `--wor` for `--worktree` (measured: the
   work tree file is restored). `--staged` alone is silent only when no other word of the call can mean the
   work tree.
7. **F21, cost (no rows).** Inside a client boundary `egress-guard`, called directly on a line of
   `grep -E 'a|ollama|b' f; ` repeated, takes 0.1 s at 2 kB, 1.6 s at 5 kB, 12.8 s at 10 kB and more than
   100 s at 20 kB at `8879cd5`; guard 0.8.0 takes 0.1 s at 40 kB. `_only_in_search_patterns` reads the line
   again and scans every span for every segment with a hit. Where the hook cannot fork, or a harness fails
   open on its own timeout, such a line runs unjudged. Wanted: the patterns and their places are worked out
   once per line, and the rule answers a 100 kB line of this kind in under 1 s on this machine, silent; with
   one real call at its end (`…; ollama run m`) it asks. Add a test with a wide margin (for example 20 kB in
   under 2 s), in the style of the suite's other timing tests.
8. **F07, F08: two false asks K11 left.** A search tool written in capitals (`GREP -E 'a|openai|b' notes.txt`):
   `_search_patterns` reads the tool's name as written. And the tool's name in the last alternative with a
   blank behind it (`grep -E 'a|openai api' notes.txt`): the part behind the last bar runs past the closing
   quote. A reading that holds the `Fs` rows: judge by where the first word of the segment stands; the reader
   pass still asks for every real command.
9. **F01: `genv -S '…'`**, `--split-string=…`, `GENV` are `env -S` (GNU coreutils 9.11).
10. **F02, F03: both ends of the pipe into a shell.** A subshell as the feeder (`(cat run.sh) | bash`), and the
    shell behind the pipe inside a subshell, a group with more than one command, or a compound
    (`cat run.sh | ( cd x && bash )`, `| { cd x; bash; }`, `| if true; then bash; fi`); `fish` and `ash` read
    commands from standard input like the shells the pipe table names.
11. **F04: `gh auth token -h HOST`.** For `gh auth token` and `gh auth status`, `-h` is `--hostname`
    (`gh auth token --help`, gh 2.92.0), not a help probe.
12. **F05: GraphQL.** A query the line does not show asks: a command substitution as the whole value, a
    `$'…'` value with a backslash escape, a body file (`--input`; measured: gh sends the file and not the
    visible field), a body on standard input of an HTTP client. Every `query` field of a call is read, and one
    that cannot be read asks. `gh api /graphql`, `gh api https://api.github.com/graphql` and
    `gh api --method POST /graphql` reach the same API (measured) and are read like `gh api graphql`. httpie's
    `query:='"…"'` gives the field as raw JSON.
13. **F06: secret stores in other spellings.** The comment above the rows names the source of each. Every
    `op item get` of an item asks; the conditions `--fields`, `--reveal`, `--otp` go.
14. **F16: `doppler run --command '…'`** runs the text in a shell.
15. **F17: a merge through the API in other spellings:** curl's `-T`/`--upload-file` is a PUT, httpie takes
    the method word in any case, a second slash in the path, a dot behind the host name.
16. **F18: `git update-ref refs/heads/Main`.** On a file system that ignores case this is main's own ref
    (measured, git 2.55 on APFS; `REFS/HEADS/MAIN` too). Compare the ref name without case.
17. **F19: the hook switch:** `builtin eval '…'`, `command eval '…'`, and `export HUSKY; HUSKY=0; git commit`.
18. **F20: `brew Uninstall jq`, `gem Uninstall rake`.** Both tools take a verb with any capitals (measured).
19. **Fm.** The rows are the tests; they hold already. Two planted breaks changed no verdict at all, so no
    test can catch them; say in the report whether you keep or drop the code:
    `not any(t.startswith("-") for t in toks[1:-1])` in `_delete_preview` (the checks behind it decide alone),
    and `if not _SEP_RE.search(p): continue` in `_only_in_search_patterns` (a part between separators cannot
    lie inside a pattern that holds none).

## Addendum 1 (found on your commit `9b917e5`): topic 1 again

`<SCRATCH>/rows-b-fix-add.txt`: 28 rows, sha256 starts `407c998b30ca2663`; ids `F22` (18, due: they hold at
guard 0.8.0 and at `8879cd5`, and are red since `9b917e5`) and `Fs` (10, hold and keep holding). They go into
`test_table_forms.py` as their own table, `ROWS_FIX_ADD`, line for line; `ROWS_FIX` stays as ordered.

- **F22: an option the table of flags does not name is not known to take a value.** `_search_option_takes_next`
  reads every option outside `_SEARCH_FLAGS` as one that takes the next word. When that option is in truth a
  flag, the real pattern is read as its value and the first **file** as the pattern, which K3 then leaves out
  of the secret check: `rg --mmap TOKEN .env`, `grep --binary TOKEN .env`, `grep -S TOKEN .env` (the grep of
  macOS), `git grep --no-color TOKEN .env` are silent since `9b917e5`. The comment above the table says a
  missing flag "errs towards asking"; for the secret check it errs towards silence. Measured against the
  tools' own help: 48 of the 248 flags of rg 15, GNU grep 3.12 and `git grep` 2.55 give a silent read of
  `.env`. The list is in `<SCRATCH>/eng/options.tsv` (tool, option, flag or value, the help line).
- Wanted: three cases, not two. A known flag is passed over; an option known to take a value takes the next
  word (that word is judged as a path as before and is never the protected pattern); **any other option, long
  or short, in any place of a short cluster, means the pattern of this call is not known**: no word is left
  out of the secret check and no pattern is protected for `egress-guard`, which is what 0.8.0 did. A unique
  prefix of a long option (`--no-mess`) is such an unknown option. Whether you keep a table of the options
  with a value (then `grep -A 3 -rn '\.env|\.pem' tools` stays silent) or give up at every option outside the
  flags (then that test goes back to its old expectation) is yours to decide; say which in the report.
- Check it the way it was found: every flag of `options.tsv` in front of `TOKEN .env` asks
  (`<tool> <flag> TOKEN .env`), and no row of the tables changes.

## Addendum 2 (in the build since K6, K7, K9): topic 2 again

`<SCRATCH>/rows-b-fix-add2.txt`: 31 rows, sha256 starts `41b69782e81720b2`; ids `F23` (15, due: they hold at
guard 0.8.0 and are red at `8879cd5` and at `5dc9a0a`) and `Fs` (16, hold and keep holding). Their own table,
`ROWS_FIX_ADD2`, line for line.

- **F23: a report handed on behind a descriptor duplication.** `_hi_lex` ends a command at the `&` of `2>&1`,
  `>&1`, `<&0`, `2>&-`: `ls .env 2>&1 | xargs cat` comes out as `ls .env 2>` · `&` `1` · `|` `xargs cat`, so
  `_quiet_reports` sees no pipe behind the report and the line is silent. It reads `.env`, and `2>&1 |` is an
  everyday spelling. Every report kind has it (`stat`, `echo`, `printf`, `git ls-files`), and so has a group or
  compound (`{ ls .env; } 2>&1 | xargs cat`).
- **And a group or compound whose output goes into a process substitution**: `{ ls .env; } > >(xargs cat)`,
  `if true; then ls .env; fi > >(xargs cat)`. `_compound_outputs` asks for `|` and `|&` behind the closer;
  the simple command already counts `(`.
- Where you mend it is yours (the lexer, or `_quiet_reports` reading a command that ends in a redirection
  operator together with what follows). The lexer serves every rule: if you touch it, the whole suite and all
  tables decide. A report with a duplication and no command behind it stays silent (`ls .env 2>&1`,
  `ls .env > /dev/null 2>&1 || echo missing`: the `Fs` rows).

## Addendum 3 (in the build since K4): topic 5 again

`<SCRATCH>/rows-b-fix-add3.txt`: 14 rows, sha256 starts `720eb45b5d729579`; ids `F24` (5, due: they hold at
guard 0.8.0 and are red at `8879cd5` and at `5dc9a0a`) and `Fs` (9, hold and keep holding). Their own table,
`ROWS_FIX_ADD3`, line for line.

- **F24: a shortened `--exclude` swallows the `-n`.** git takes any unambiguous prefix of `--exclude`
  (`--e`, `--ex`, `--excl`, `--exclud`), and the option takes the next word as its pattern even when that word
  is `-n` or `--dry-run`. Measured with git 2.55 in a scratch repository: `git clean --excl -n -f`,
  `git clean --e -n -f` and `git clean --exclud -n -fdx` print "Removing …" and the file is gone. `_git_dry`
  skips the next word only behind `--exclude` written out, so these read as a preview.
- Wanted: the same rule as for the dry-run family itself. A long option of `git clean` or `git worktree prune`
  that `_git_dry` cannot place (no known flag, no known option with a value, no prefix of one that it can
  tell apart) means no preview: the delete ask stays. Measured previews that stay silent are among the `Fs`
  rows (`git clean --no-dry-run -n -f` and `--dry-run --no-dry-run --dry-run -f` print "Would remove").

## Addendum 4: two more readings that are weaker than 0.8.0

`<SCRATCH>/rows-b-fix-add4.txt`: 22 rows, sha256 starts `7005cb3f69eb06c8`; ids `F25` (6, due, red since your
`40657f5`), `F26` (7, due, red since the build) and `Fs` (9, hold and keep holding). Their own table,
`ROWS_FIX_ADD4`, line for line. Two topics, two commits.

- **F25: `grep --context TOKEN .env` on the grep macOS ships.** That grep takes the value of `--context` only
  glued (`--context[=num]`); the next word is the pattern. Measured on a scratch file with BSD grep 2.6.0:
  `grep --context TOKEN f` searches `f` for TOKEN and prints the lines; GNU grep 3.12 refuses the same line.
  The grep table holds `--context` as an option that takes the next word, so TOKEN is read as its value and
  `.env` as the pattern, which K3 leaves out. Wanted: for grep and its kin, `--context` without `=` leaves the
  pattern unknown (two greps read it two ways). The short `-C` needs its number in both greps and stays as it
  is; `--after-context` and `--before-context` need theirs in both too.
- **F26: `git status -v` prints content.** `-v` shows the staged change of the path it names and `-vv` the
  change in the work tree: lines of the file, not its name. Measured in a scratch repository with git 2.55:
  `git status -v f`, `--verbose` and `--v` (a unique prefix) on a staged file, `-vv` and `-v -v` on a changed
  one. K7 is for git commands that report names: `git status` with `-v` in a short cluster, or a long option
  that is a prefix of `--verbose`, is no quiet report. `git check-ignore -v` names the rule that matches and
  prints no content: it stays silent (a K7 row of the build).

## Addendum 5: one spelling from `bin/fresh-review` on the build

`<SCRATCH>/rows-b-fix-add5.txt`: 9 rows, sha256 starts `34eb33a2c043aa4e`; ids `F27` (4, due; silent at 0.8.0
too, so this is a gap of the new cache table and no regression) and `Fs` (5, hold). Their own table,
`ROWS_FIX_ADD5`, line for line. One commit.

- **F27: `go clean -modcache=true`.** Go's flag package takes a boolean flag with a value (`-modcache=true`,
  `-modcache=1`, `-modcache=T`, and each with two dashes); `_DELETE_ONLY_WITH` names the bare flag only.
  `-modcache=false` empties nothing and stays silent.

## Left out on purpose: do not fix these in this pass

Azure read verbs that now ask (`az group export`, `az storage blob url`, `az acr task logs`,
`az policy state summarize`, `az network watcher test-connectivity`); `go clean -modcache -h`; a secret file
name written with U+017F; the glued include options; an interpreter fed by a pipe (`| python3`); a script
given by a substitution, a variable or a file (`bash -c "$(cat run.sh)"`); the REST call that merges a branch
(`repos/o/r/merges`); `op document get`, `sops exec-env`, `ansible-vault edit`; approving a review. They are
named in the decision record. If you meet another form of this kind, write it down and leave it.

## Report (at most 500 words)

Commits (sha, subject); per topic one line on what changed in the code; every existing test you changed and
why; one red line per topic from before the fix; deviations from this order; rows left red and why; what you
saw and left out; the two answers under topic 19.
