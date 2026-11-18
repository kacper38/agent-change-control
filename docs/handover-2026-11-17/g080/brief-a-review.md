# Review brief: guard 0.8.0 group A (tracker item #50)

`<S8>` = <SCRATCH>/g080
`<WT>` = <REPO>/.claude/worktrees/g080-a (branch `feat/guard-0.8.0`)
`<OLD>` = `<S8>/review/guard-0.7.1.py` (the guard as it is on `main`; a copy made for you)

FILL AFTER THE BUILD: the commit list, the diff files under `<S8>/review/`, the checks already run.

## Goal
Find defects in group A of guard 0.8.0 before the owner sees it. You review; you fix nothing. One fix pass follows,
done by someone else, from your report. Your one job: commands and file paths that pass without a prompt although
they must not, and ones that prompt now although they must stay silent.

## What it is
`tools/guard/guard.py` is a PreToolUse hook. It reads a tool call as JSON on stdin and answers: silent (exit 0),
ask (exit 0 with JSON), deny (exit 2). It never allows. Exit 1 means the guard itself failed, and both harnesses
then let the call run. The harness cuts the hook after 5 s, which also lets the call run; the guard's own budget
is 3.5 s and turns an overrun into an ask.

Group A adds spellings of what 0.7.1 already guards. Nothing new is guarded, and no verdict of 0.7.1 may get
weaker:
1. `secret-shell` reads a secret path written as `--opt=path`, glued to a short option, behind `@`, or as the
   source of a redirection `<path`; `git add` behind git's own options denies.
2. A script handed to a shell by a here-document, or by `echo`/`printf` through one pipe, is read by all eight
   shell rules like the script of `bash -c`. A script for another host or a container is judged as
   `ssh host '…'` is.
3. `tracker-guard` reads `gh` with `-R`/`--repo` in front of the verb and the glued spellings of `gh api` options.
4. `git-guard` reads short option clusters, long options cut short, and the ways around the hooks that are no
   `--no-verify` (environment, `core.hooksPath`); `delete-guard` asks for `git push -d`, `--delet`, `--prune`.
5. `egress-guard` gets the reader pass (inside a client boundary only).
6. Capitals. The owner's file system ignores case, so `GIT`, `SUDO`, `BASH -c` run the real tools and `.ENV`
   opens `.env` (measured: `<S8>/semantics4.log`). Three parts: an LLM host in capitals asks like the plain host;
   a secret file name in capitals is classed like the plain name, for the shell and for Read, Write and Edit;
   a tool's name in capitals is read like the plain name by every shell rule.

## Where
- Code under review, read-only for you: `<WT>/tools/guard/guard.py`. Start from the diff: `<S8>/review/guard.diff`.
- The design that was decided: `<S8>/brief-a.md`, section 4 only (4.1 to 4.7). Read it before you attack.
- The rows the build had to satisfy: `<S8>/rows-a.txt`, `<S8>/rows-a-added.txt`, `<S8>/rows-a-caps.txt` (format in
  `<S8>/expect.py`) and `<S8>/rows-a-files.txt` (file tools; format in `<S8>/expect_files.py`).
- What git, curl and gh really do with the forms: `<S8>/semantics.log`, `<S8>/semantics2.log`; capitals on the
  owner's machine: `<S8>/semantics4.log`.
- Do not open anything else in the scratchpad. In particular not the folder `g080-heldout`.

## Decided; do not reopen
- A source the guard cannot read stays silent as before: a script file, a variable, a command substitution, a
  decoder or a filter in front of the shell (`cat run.sh | bash`, `base64 -d x | bash`, `sed … | bash`). No new
  kind of ask in this group.
- The guard reads text and prompts. It is no sandbox. A command held in a variable or an alias, `make target`,
  and code in another language (`python3 -c "os.system('…')"`, `node -e`, `osascript`) are out of reach by design.
- Long git options count by prefix: `--X` is a guarded option `--G` when `G` starts with `X`. A prefix git itself
  refuses as ambiguous may deny or ask as well; that is accepted.
- `git push --repo=<name> <word>`: git reads `<word>` as the repository, not as a refspec. This is no push to the
  branch `<word>` names.
- Capitals: only a known tool's name is folded, never a verb, an option or a file name; the command is judged as
  written and folded, and the stricter answer counts. A capitals form may therefore prompt where the plain form
  prompts for a weak reason (`git commit -m "RM unused; GIT clean up"` asks like its lower-case twin): accepted.
  A shell builtin in capitals (`EXPORT`, `EVAL`) is not found by the shell; reading it like the builtin is
  harmless and accepted. On a case-sensitive file system `.ENV` is another file and asks: accepted by the owner.
- Known and left for later; do not report: `gh api graphql` mutations; git plumbing (`commit-tree`, `update-ref`);
  commands that print the environment (`printenv`, a bare `env`, `docker compose config`); tools that run a
  command and are in no table (`noglob`, `nocorrect`, `unshare`, `ltrace`, `gdb --args`, `lldb --`, `hyperfine`,
  `op run --`, …); the Homebrew names of the GNU tools (`grm`, `gcp`, `genv`, also in capitals: `GFIND`); more
  verbs (`aws ssm send-command`, `uv remove`, `uv cache clean` …); the false asks `find . -name yarn`,
  `git restore --staged f`, a plain search pattern such as `grep -rn .env docs`, `ls -la .env`, `command -v codex`;
  a verb in capitals (`git PUSH`, `brew LIST`); and two forms the owner has not decided yet: the GitHub API host
  in capitals in tracker-guard (`https://API.GITHUB.COM/…`) and the guard's own configuration path in capitals in
  guard-config (`.claude/SETTINGS.json`, `tools/GUARD/guard.py`).

## How to test a candidate
Commands under test are data. Never put one on a shell command line. Never run one.
- Write the candidates, one per line, into a file in your folder with the Write tool (a line that starts with a
  double quote is a JSON string, for commands with line breaks), then run
  `python3 -I <S8>/probe.py <your file> <OLD> <WT>/tools/guard/guard.py [--branch main] [--boundary client] [--diff]`
  It prints the verdict of all eight shell rules for the old and the new guard; `--diff` shows only the lines that
  differ.
- Rows with an expected verdict: the format of `<S8>/rows-a.txt`, checked with
  `python3 -I <S8>/expect.py <WT>/tools/guard/guard.py <your rows file> --red`.
- File tools (Read, Write, Edit): rows in the format of `<S8>/rows-a-files.txt`, checked with
  `python3 -I <S8>/expect_files.py <WT>/tools/guard/guard.py <your rows file> --red`; run the same file against
  `<OLD>` for the verdict before.
- Where a finding depends on what a tool does with a form, say so and label it `inference` unless one of the
  semantics logs shows it. Do not run git, gh or curl with the forms yourself.
- Your folder is `<S8>/review/ra/`. Write nowhere else.

## Lines of attack, in this order (stop a line when three tries in a row find nothing)
1. Weaker than 0.7.1: any command where a rule answered ask or deny at 0.7.1 and answers less now. Take the
   changed functions from the diff and feed each the forms it handled before.
2. Fed scripts: shells and feeders the build missed (options between the shell and the here-document, `bash -s --
   arg`, two here-documents in one line, a here-document behind a pipe or inside `$( … )`, a quoted delimiter,
   `<<-`, `sudo -u x bash`, `env X=1 bash`, `ssh` with options that take a value, `docker exec -i`, `kubectl exec
   -i`); and the reverse: a data here-document read as a script (`cat <<EOF > file`, `python3 - <<EOF`,
   `git commit -F - <<EOF`, `psql <<EOF`, `tee`, `curl -d @- <<EOF`), which would prompt on text.
3. Secret paths: option spellings per tool (`--opt=path`, `-opath`, `@path`, `name@path`, `name=@path`, `<path`,
   `N<path`), behind wrappers and inside nested scripts; what the excluded options hide (`--exclude=`, `--glob=`,
   `--filter=` and kin: is there a tool for which one of these names a file that is read?); words with `://`.
4. git: clusters (`-n` behind a letter that takes a value, `-f` behind `-o`), prefixes of every guarded long
   option for every subcommand named in section 4.4, the environment words through `env`, `export` and inside
   `bash -c`, the three ways to set `core.hooksPath` for one call and the `git config` writes; and the reverse:
   everyday git commands that must stay silent (`git commit -m`, `git push -u origin feat`, `git config user.name`).
5. gh: `-R`/`--repo` in every spelling and place, `gh api` methods and write flags glued or with `=`; reads that
   must stay silent (`gh issue list -R o/r`, `gh api repos/o/r/issues`).
6. egress, inside a client boundary: wrappers, nesting, containers, fed scripts; a tool name that is no command
   word must stay silent (`grep -rn codex docs`, `man codex`).
7. Capitals, a tool's name. (a) Names the fold does not know: read every table, every expression and every
   comparison in the code (`head == "…"`, `name in (…)`) for a tool name and try each in capitals; a miss is a
   form that still passes. (b) Ways to write the name: a path in front, quotes and backslashes inside it, after
   a separator without a space, inside `$( … )`, in a nested script, in a fed script, behind `env -S`, as the
   word after `xargs` or `-exec`. (c) The reverse: everyday commands that hold a word in capitals and must stay
   as they were (`git diff HEAD`, `git reset --soft HEAD~1`, `echo TODO`, `export PATH=…`, `curl -X POST …`,
   a here-document whose delimiter is `SH` or `PY`, SQL keywords, `README`, `LICENSE`, `Makefile`): compare old
   and new with `--diff`.
8. Capitals, a secret file name and a host: directory names and suffixes in capitals for every pattern of
   `secret_class`, the example and tfvars names (`.ENV.EXAMPLE` silent, `.env.EXAMPLE` asks as before), the file
   tools and the shell, the new option spellings of line 3 with a name in capitals; names that must stay silent
   (`docs/ENV.md`, `src/Keys.py`); every host of the egress expression in capitals, and hosts that must stay
   out (`HuggingFace.co`, `DOCS.TOGETHER.AI`).
9. Cost: one command of 100 kB in each new shape (a long here-document fed to a shell, a long `echo … | bash`,
   a thousand `--opt=value` words, and the same with one tool name in capitals, which makes every rule read the
   command twice). Use `python3 -I <S8>/probe.py` with a file you generate by a script in your folder, and
   report seconds. The budget is 3.5 s.

## Rules
1. Read-only on the repository and on the scratchpad outside your folder. No git command that writes. Install
   nothing (no pip, npm, uv add, brew, npx, uvx). No network. Delete nothing.
2. Do not run the whole test suite; its result is in the section "Already checked". A single test file is fine
   when a finding depends on it:
   `uv run --directory <WT> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= <path>`
3. Keep shell commands short and clean: the scripts above, `git -C <WT> log|show|diff`, `grep`, `sed -n`. No
   here-document and no long one-liner; anything longer goes into a script file in your folder, run with
   `python3 -I`. A script you run must hold no command under test: read those from a data file. Your shell stays
   in the main checkout; use absolute paths.
4. Verify before you report. Every finding says how it was checked: ran the probe, or read the code at file:line.
   A guess is labelled `inference`.

## Report (at most 900 words, no file dumps)
First line: the verdict (BLOCKER, findings, or clean). Then the findings, most severe first, one per line:
`ID | BLOCKER, MAJOR or MINOR | area | file:line | the command or path; verdict at 0.7.1 and now | expected | how checked | the fix in one line`
BLOCKER: weaker than 0.7.1, a crash, or a guarded form of sections 4.1 to 4.7 that still passes. MAJOR: a new
prompt on an everyday command, or a spelling of the same kind the build missed. MINOR: the rest.
Then, in at most three lines each: what you looked at and found sound, and what you did not get to.
