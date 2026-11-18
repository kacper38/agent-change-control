# Review brief: guard 0.9.0, groups B and C (tracker item #NN) — DRAFT of 2026-11-18

Draft, written with `brief-b.md` and under the same marks (**[Q1]** … **[Q6]**, **[A-left]**, **[calls]**,
**[version]**). It is filled and struck clean together with that brief.

`<S8>` = <SCRATCH>/g080
`<WT>` = <REPO>/.claude/worktrees/g090-bc (branch `feat/guard-0.9.0`)
`<OLD>` = `<S8>/review/guard-0.8.0.py` (the guard as it is on `main`; a copy made for you)

FILL AFTER THE BUILD: the commit list, the diff files under `<S8>/review/`, the checks already run.

## Goal
Find defects in groups B and C of guard 0.9.0 before the owner sees it. You review; you fix nothing. One fix
pass follows, done by someone else, from your report. Your one job: commands and file paths that pass without
a prompt although they must not, and ones that prompt now although they must stay silent.

## What it is
`tools/guard/guard.py` is a PreToolUse hook. It reads a tool call as JSON on stdin and answers: silent (exit
0), ask (exit 0 with JSON), deny (exit 2). It never allows. Exit 1 means the guard itself failed, and both
harnesses then let the call run. The harness cuts the hook after 5 s, which also lets the call run; the
guard's own budget is 3.5 s and turns an overrun into an ask.

This change does two things, and they pull in opposite directions.

Group B adds what the tables did not name. No verdict of 0.8.0 may get weaker through it:
1. Verbs: a cloud CLI that runs a command on a live host or deploys (`deploy-ask`); a package or a tool
   version removed, a download cache emptied (`delete-guard`).
2. Tools that run the command after them (`unshare`, `noglob`, `op run --`, `hyperfine '…'`, …) are looked
   through by every shell rule.
3. The Homebrew names of the GNU tools (`grm`, `gcp`, `gfind`, `genv`, …) are the plain tools.
4. A net: `git`, `gh` or `az` as a later word behind a command word no table knows asks (`git-guard`,
   `tracker-guard`, `protected-branch`).
5. `tracker-guard` reads GraphQL mutations; `protected-branch` reads `git update-ref`; a shell fed by a pipe
   the guard cannot read asks; `secret-shell` asks for a command that prints a stored secret; `deploy-ask`
   asks for `az` writes **[Q5]**.
6. **[Q1] [Q2] [Q3] [Q6] [A-left]** The guard's own configuration path, the GitHub API host and a verb of
   `brew` or `gem` in capitals; a merge of a pull request (`tracker-guard`: ask, with `--admin` deny); five
   forms the reviews of group A left.

Group C takes ten kinds of ask away. Here a verdict gets weaker on purpose, and only for the forms of the K
rows: a pattern of `find`, `git restore --staged`, a search pattern, a preview, a help probe as the sole
argument, `ls`/`stat`/`test` on a secret path, git commands that report names, the word after an exclude
option, the text of `echo` and `printf`, `command -v` of an LLM tool.

## Where
- Code under review, read-only for you: `<WT>/tools/guard/guard.py`. Start from the diff:
  `<S8>/review/guard.diff`.
- The design that was decided: `<S8>/brief-b.md`, section 4 only. Read it before you attack.
- The rows the build had to satisfy: `<S8>/rows-b.txt`, `rows-b4.txt`, `rows-b4-az.txt`, `rows-b5.txt`,
  `rows-c.txt` (format in `<S8>/expect.py`) and `rows-b5-files.txt` (file tools; `<S8>/expect_files.py`).
- What the tools really do with some forms: `<S8>/semantics.log` to `<S8>/semantics4.log`.
- Do not open anything else in the scratchpad. In particular not the folder `g080-heldout`.

## Decided; do not reopen
- The guard reads text and prompts. It is no sandbox. A command held in a variable or an alias, `make target`,
  and code in another language are out of reach by design.
- The net speaks for `git`, `gh` and `az` only, and only with an ask. Nothing like it for `rm`.
- Group C's list and its keep list are the owner's, form by form. A form on the keep list keeps asking even
  where that looks harmless (`wc -c .env`, `touch .env`, `git branch -d x`).
- `ls`, `stat`, `test`, the name-reporting git commands and `echo` text are silent only as a simple command
  at the top level whose output is not piped onward.
- Left for later; do not report: `aws` and `gcloud` writes, `printenv` and a bare `env`, the ways to move a
  protected branch that are no commit and no `git update-ref` (merge, rebase, `branch -f`, `checkout -B`,
  `fetch . a:b`), `bash < run.sh`, `bash <(cat run.sh)`, `eval "$(cat run.sh)"`, `echo "$X" | bash`, a NUL
  character in the command, `gh pr review --approve`, a path of the forge's API in capitals, a verb in
  capitals for any tool but `brew` and `gem`, a mixed-case verb, and everything a cloud session or a
  harness's own GitHub tools can do (plan rev 3, step 1.7).

## How to test a candidate
Commands under test are data. Never put one on a shell command line. Never run one.
- Write the candidates, one per line, into a file in your folder with the Write tool (a line that starts with
  a double quote is a JSON string, for commands with line breaks), then run
  `python3 -I <S8>/probe.py <your file> <OLD> <WT>/tools/guard/guard.py [--branch main] [--boundary client] [--diff]`
  It prints the verdict of all eight shell rules for the old and the new guard; `--diff` shows only the lines
  that differ.
- Rows with an expected verdict: the format of `<S8>/rows-b.txt`, checked with
  `python3 -I <S8>/expect.py <WT>/tools/guard/guard.py <your rows file> --red`.
- File tools (Read, Write, Edit): rows in the format of `<S8>/rows-b5-files.txt`, checked with
  `python3 -I <S8>/expect_files.py <WT>/tools/guard/guard.py <your rows file> --red`; run the same file
  against `<OLD>` for the verdict before.
- Where a finding depends on what a tool does with a form, say so and label it `inference` unless one of the
  semantics logs shows it. Do not run the tools with the forms yourself.
- Your folder is `<S8>/review/rb/`. Write nowhere else.

## Lines of attack, in this order (stop a line when three tries in a row find nothing)
1. Weaker than 0.8.0 outside group C: any command where a rule answered ask or deny at 0.8.0 and answers less
   now, and that is no form of a K row. Take the changed functions from the diff and feed each the forms it
   handled before. The rows of group A are tests; a changed or removed case of
   `tools/guard/tests/test_bypass_forms.py` is a finding unless a row of this change asks for it.
2. Group C too wide: for each K id, the neighbours that must keep asking. A preview flag beside a real one
   (`git clean -n` against `-f`, `--dry-run=none`), a help word that is not the sole argument, a search tool
   whose secret word is a file operand and not the pattern, `ls` or `echo` whose output goes on (`| xargs`,
   `$( … )`, a redirection into a secret file), `test -f .env && cat .env`, `find … -exec`, `command -v x &&
   x`, each form inside `bash -c` and behind a wrapper.
3. Tools that run a command: for each new tool, its options that take a value in front of the command, `--`,
   the command as one quoted word, two of them in a row, one behind `sudo` or `env`; and the reverse: the
   tool's own listing or help forms, and a file argument that is no command (`gdb ./a.out`, `valgrind
   --version`), which must stay silent.
4. The Homebrew names: every `g` name of the mapping in every table it now reaches, in capitals too; and the
   reverse: tools whose name merely starts with `g` (`gh`, `go`, `gem`, `gzip`, `gdb`, `gpg`, `gcloud`,
   `gradle`).
5. The net: unknown first words in front of `git`, `gh` and `az` (a script path, a tool with options, two
   unknown words); and the reverse, where new noise is most likely: everyday commands that hold the word
   `git` or `az` later in the line (`make git-status`, `brew install git`, `code --wait git.md`, `grep -rn
   git docs`, `ls git`, `cd az && ls`, `docker run alpine/git status`), text tools, and a tool the tables
   know.
6. GraphQL: the mutation keyword in other places (a query named `mutation`, a string, a comment, an alias, a
   fragment, lower and upper case, the query in `-f query=`, `--raw-field`, `-F query=@file`, a here-string,
   standard input), a mutation whose name holds `Issue` or `Label` in another case, two operations in one
   document; reads that must stay silent.
7. `git update-ref`: the ref in other spellings (`refs/heads/main`, a bare `main`, `HEAD`, a symbolic ref), with
   git's own options in front, `--no-deref`, `-d`, `--stdin`, on a feature branch and on `main`; branches
   that are not protected.
8. A shell fed by a pipe: feeders the build missed (`curl … | sh`, `gunzip -c x | bash`, `tail -n +2 f |
   sh`, `tee | bash`); and the reverse: a pipe into a shell that runs a script file, `| bash -c '…'`,
   `| xargs bash`, `| grep bash`.
9. Secret stores: per tool, the printing verb in its other spellings and output formats, behind wrappers and
   inside `$( … )`; and the silent side: list, status and metadata calls, help probes.
10. `az` writes **[Q5]**: everyday reads that now ask (a read verb the build's list misses), the verb found
    in the wrong word (a value that looks like a verb, a group named like one), `az` extension and
    configuration calls that change only this machine.
11. Capitals, a merge, and the leftovers of group A: the guard's own paths in every mix of capitals and the
    paths that merely resemble them; hosts that are not the forge's API; every spelling of `gh pr merge` and
    of the merge endpoint, and the other calls under `pulls/<n>/`; `eval` with an export in other spellings;
    groups and subshells around a fed shell, and around data.
12. Cost: one command of 100 kB in each new shape (a thousand unknown words in front of `git`, a long GraphQL
    document, a long chain of the new wrappers), with and without a tool name in capitals. Use
    `python3 -I <S8>/probe.py` with a file you generate by a script in your folder, and report seconds. The
    budget is 3.5 s.

## Rules
1. Read-only on the repository and on the scratchpad outside your folder. No git command that writes. Install
   nothing (no pip, npm, uv add, brew, npx, uvx). No network. Delete nothing.
2. Do not run the whole test suite; its result is in the section "Already checked". A single test file is
   fine when a finding depends on it:
   `uv run --directory <WT> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= <path>`
3. Keep shell commands short and clean: the scripts above, `git -C <WT> log|show|diff`, `grep`, `sed -n`. No
   here-document and no long one-liner; anything longer goes into a script file in your folder, run with
   `python3 -I`. A script you run must hold no command under test: read those from a data file. Your shell
   stays in the main checkout; use absolute paths.
4. Verify before you report. Every finding says how it was checked: ran the probe, or read the code at
   file:line. A guess is labelled `inference`.

## Report (at most 900 words, no file dumps)
First line: the verdict (BLOCKER, findings, or clean). Then the findings, most severe first, one per line:
`ID | BLOCKER, MAJOR or MINOR | area | file:line | the command or path; verdict at 0.8.0 and now | expected | how checked | the fix in one line`
BLOCKER: weaker than 0.8.0 outside the K rows, a crash, a guarded form of section 4 that still passes, or a
form group C made silent that reads, deletes or sends something. MAJOR: a new prompt on an everyday command,
or a spelling of the same kind the build missed. MINOR: the rest.
Then, in at most three lines each: what you looked at and found sound, and what you did not get to.
