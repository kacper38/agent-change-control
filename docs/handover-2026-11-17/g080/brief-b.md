# Brief: guard 0.9.0, groups B and C — what the tables do not name, and eleven false asks

**Not to be handed to an engineer before two things are done.** The tracker item exists and the owner has run
`owner ready`; and the orchestrating session has filled the item number (`#NN`), the paths (`<REPO>`,
`<SCRATCH>`) and the commit the worktree starts from (`<BASE>`), and has struck this box.

Written by a cloud session on 2026-11-18 from the owner's decisions of 2026-11-17, the design notes in
`docs/HANDOVER-2026-11-17.md` and the row files. The owner's answers of 2026-11-18 are worked in: open
questions 1, 2, 3, 5 and 6 as recommended, the forms the reviews of group A left, the eleven calls of the row
files, version 0.9.0, and an eleventh kind for group C. Section 4 was read against `guard.py` 0.8.0 on the
owner's machine that day: every function and table it names stands at the line given.

Repository: `agent-change-control`, a public kit of guard hooks and tools for AI-assisted platform work in
regulated environments. `tools/guard/guard.py` (0.8.0 on `main`) is the hook engine: standard library only,
Python >= 3.9. It judges every tool call of the sessions in this repository, including yours.

**Goal.** Two things in one pull request. Group B: the rules already ask or deny for a deletion, a forced
push, a tracker bypass, a secret, a deploy and an install, but only when the tool, the verb or the wrapper is
in one of the guard's tables. You add what the tables miss, a net for `git`, `gh` and `az` behind an unknown
word, and four things nothing reads today (GraphQL mutations, `git update-ref`, a shell fed by a pipe the
guard cannot read, commands that print a stored secret). Group C: eleven kinds of ask that fire on harmless
commands go away. Nothing else changes.

The owner (Kacper) decided this scope on 2026-11-17 and 2026-11-18; the tracker item is #NN. The design below is decided: do
not reopen it. If a decided point cannot work, stop that point, finish the rest, and say so in your report.

## 1. Where you work (read twice)

- Main checkout: `<REPO>`. Your shell starts there and returns there after every call. **You change nothing
  in it**: no edit, no staging, no commit, no branch switch. Its guard is the one that judges this session.
- Your worktree `WT`: `<REPO>/.claude/worktrees/g090-bc`, branch `feat/guard-0.9.0`, at `origin/main`
  `<BASE>` (guard 0.8.0), no commit of its own yet. Every file you read or edit has a path that
  starts with `WT`. Every command names it; do not `cd`:
  - whole suite, both Pythons, lint (prints the final lines): `sh <SCRATCH>/g070/suite.sh <WT>`
  - one test file: `uv run --directory <WT> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools/guard/tests/<file>`
    (the same with `--python 3.9`)
  - lint: `ruff check <WT>/tools`
  - git: `git -C <WT> status --short`, `git -C <WT> diff`, `git -C <WT> add <paths>`, `git -C <WT> commit …`
- Baseline, measured on the owner's machine on 2026-11-18 at `ec23d5d` (guard 0.8.0): `5271 passed, 9 skipped`
  on Python 3.13 and on Python 3.9; `ruff` clean. The session measures again when `<BASE>` is a later commit.
- Scratch folder `SC` (data files of this brief; yours to write under `SC/eng/`): `<SCRATCH>/g080/`. Never
  write temporary files into a checkout. Read nothing else in the scratchpad: only `SC` and the suite script
  named above.
- Before your final report run `git -C <REPO> status --short` and confirm it shows only
  `?? .claude/worktrees/`.

## 2. The acceptance rows (your definition of done)

- Format, one row per line: `id | branch[@client] | rule | expected | command`. `rule` is one rule name, or
  `shell` for all eight shell rules together (then `expected` is `silent`). A command that starts with `"` is
  a JSON string (line breaks). An id that ends in `s` (or `t`) holds at 0.8.0 and must keep holding; every
  other id is red at 0.8.0. Counts measured on guard 0.8.0 on the owner's machine on 2026-11-18:

  | File | Rows | Red | Ids |
  |---|---|---|---|
  | `SC/rows-b.txt` | 298 | 164 | R1 R2 R3 (verbs), T1 to T4 (tools that run a command), U1 to U4 (Homebrew names); Rs Ts Us |
  | `SC/rows-b4.txt` | 255 | 136 | G1 G2 G3 (the net), L1 L2 L3 (GraphQL), D1 D2 (`git update-ref`), I1 (a shell fed by a pipe), V1 V2 V3 (secret stores); Gs Ls Ds Is Vs |
  | `SC/rows-b4-az.txt` | 123 | 61 | Z1 Z2 (`az` writes); Zs |
  | `SC/rows-b5.txt` | 119 | 62 | W1 (API host in capitals), W2 (`brew`, `gem` verbs), W3 W4 (merge), X1 to X5 (what the reviews of group A left); Ws Xs |
  | `SC/rows-c.txt` | 173 | 86 | K1 to K11: asks that go away; Ks |
  | `SC/rows-b5-files.txt` | 36 | 14 | Y1 (the guard's own path in capitals); Yt Ys. Format: `id | tool | rule | expected | path` |

- Checkers; each prints every row that does not hold and a total, exit 0 when all hold. They call the rule
  functions through `RULES[...]` with the command or the path as a string. Nothing runs, no file is opened.
  - `python3 -I SC/expect.py <WT>/tools/guard/guard.py SC/rows-b.txt SC/rows-b4.txt SC/rows-b4-az.txt SC/rows-b5.txt SC/rows-c.txt --red`
  - `python3 -I SC/expect_files.py <WT>/tools/guard/guard.py SC/rows-b5-files.txt --red`
- The rows of group A are tests since 0.8.0 (`tools/guard/tests/test_bypass_forms.py`, 708 shell rows and 78
  file rows). They stay green, with the exceptions section 4.12 names.
- What the tools really do with some of these forms was measured on the owner's machine: `SC/semantics.log`
  to `SC/semantics4.log`; today's verdicts of the forms the design notes name: `SC/probe-b4-*.at071.log`
  (0.8.0 answers the same).
- The rows are examples of a rule, not the rule. A separate set of forms you have not seen is checked after
  you finish; build the general reading the sections below describe, not a list of the row strings.

## 3. Rules of the work

1. **Install nothing.** No `pip install`, `npm install`, `uv add`, `brew install`, no `npx <pkg>`, no
   `uvx <tool>`. `uv run` always with `--offline`. The code must run on Python 3.9: no `match`, no `X | Y` in
   runtime annotations, no `zip(strict=)`. A missing dependency is reported, not installed.
2. **Never delete.** No `rm`, `rmdir`, `git clean`, `git reset`, `git restore`, `git checkout -- <path>`,
   `git stash`. To get a file out of the way, move it into `SC/eng/` with `command mv -f`.
3. **Git.** Read-only git is fine. You make exactly one commit per step of section 5, in your worktree, when
   that step's checks are green: stage by explicit path (never `git add .` or `-A`), write the message to a
   file under `SC/eng/` and run `git -C <WT> commit -q -F <file>` as a Bash call of its own. Subject at most
   72 characters, `type(scope): imperative`; then a body that says what changed and why, with the numbers
   that prove it; as the last line the `Co-Authored-By` line your own session instructions give you (your
   model, not the one of the session that wrote this brief). Never `Fixes`, `Closes` or `Resolves` in a
   message; `Refs #NN` is right. If a commit is refused or asks for a passphrase, do not retry and do not
   work around it: leave the step uncommitted, stop there and report. No push, no branch switch, no rebase,
   no amend.
4. **Commands under test are strings.** Never run an install, deploy, delete, push, merge or commit-gate
   bypass to see what it does, and never a command that prints a secret. A probe loads the module and calls
   the rule function (as `SC/expect.py` does), or feeds the hook an event on stdin with `KZ_TELEMETRY_DIR`
   pointing at a temp folder.
5. **Edit files with the Edit or Write tool.** Never write a file through a here-document or a redirection.
   Keep candidate commands in data files or in the test module, never on a command line: the live guard
   reads your command lines, and a line that holds `rm -rf` or `git push --force` as text makes it ask the
   owner. No script run by name may hold such forms in its own text either; it reads them from a data file.
   Prefer one script per check (`python3 -I SC/eng/probe.py`) over many shell calls.
6. **Do not edit** `DECISIONS.md`, `README.md`, `AGENTS.md`, `docs/**`, `.github/**`, `.claude/**`, `VERSION`
   in `guard.py`, or anything this brief does not list. The orchestrating session writes the decision log,
   the docs and the version bump from your report. You edit: `tools/guard/guard.py`,
   `tools/guard/tests/test_table_forms.py` (new), `tools/guard/tests/make_fixtures.py` and the fixture files
   it generates, and an existing test only under rule 10.
7. **Test data is synthetic.** Do not read real transcripts under `~/.claude/projects` or the real telemetry
   folder `~/.claude/telemetry`. Tests use `tmp_path`; no test reads from the scratch folder.
8. **The test-guard scans test files for skip and focus markers.** Do not use them. Never name a non-test
   module `test_*.py`.
9. **Style of the code base:** small functions with a one-line docstring that says what and why, comments
   only where the reason is not obvious, plain words in messages. Match the file; do not tidy code you did
   not need to change. Every `except` is a decision: say in a comment why the error is handled that way. A
   guard rule must never let an exception escape: an uncaught error ends the hook with exit 1, and both
   harnesses then run the call unjudged. A table of tool, verb or option names in the code names its source
   (the tool's manual and version) in a comment.
10. **Tests first.** For each step put its rows into the test module, run it, keep one or two lines of the
    red output for your report, then make it pass. Change an existing test only where it asserts a verdict
    that a row of this brief changes (group C takes asks away; the merge rows turn the `tracker-guard`
    fixture case that expects `gh pr merge 3 --rebase` to pass, in `make_fixtures.py` and for both
    harnesses), and list each such change in your report with the row that asks for it.
11. **Nothing that asked or denied at 0.8.0 may stop doing so, except the K rows of `rows-c.txt`**, and
    nothing that was silent may start to ask except through the rules of section 4. The suite holds frozen
    expectations and timing tests; they stay green.
12. **Cost.** The hook has 3.5 s for all rules; a normal call takes about 0.07 s and must stay there. Reuse
    the reader's memo (`nested_commands`, `command_word_indexes`); do not lex the command once more per rule.
    No test asserts a wall-clock bound: count the work.
13. Before each commit run the suite script and keep its final lines for the report.
14. **If you run short of room.** These are more steps than one context may hold. Finish and commit the step
    you are in, then stop and report which steps are done and what the next one needs; the session that
    wrote this brief continues with you. Never start a step you cannot finish, and never leave a step
    half-committed.

## 4. Decided design

Read first (line numbers of 0.8.0): `combine` (263), `_RM_CLASS` and `_DELETE_TOOLS` (340, 349), `delete_what`
(403), `_WRAPPERS` and `segments` (481, 492), `secret_class` (553), `_WRITERS_LAST`, `_WRITERS_ALL` (619),
`_secret_seg` (669), `_SEARCH_TOOLS` (690), `rule_secret_shell` (757), `_git_guard_seg` (974), `_DEPLOY_TABLE`
(1081), `rule_deploy_ask` (1336), `rule_egress_guard` (1372), `rule_protected_branch` (1464),
`guard_config_class` (1587), `_az_tracker_guard` (1723), `rule_tracker_guard` and `_tracker_seg` (1756, 1793),
`host_install_what` (2311), the reader from `CommandNotRead` (2365) and `nested_commands` (2436) to
`command_word_indexes` (2891) and the `_nc_*` functions around them, `fold_names` and `judged_twice` (3118,
3148), `RULES` (3183).

Two properties hold for every part. (1) A new name or verb is judged in the first pass and in the reader
pass, so it is found behind a wrapper, in a nested script and in a fed script, like the names the tables hold
today. (2) Capitals: what you add to a table is a known name for `fold_names`, so `UNSHARE`, `GRM` and `GFIND`
are read like the plain names (the four pairs of group A's check that are still weaker are `GFIND` and
`GXARGS`). `fold_names` folds only the names of `_FOLD_NAMES` (3102), which is built from a tuple of the
tables and from `_NAMES_IN_CODE` (3095): a table you add goes into that tuple, and a name that stands only in
an expression or a comparison of the code goes into `_NAMES_IN_CODE`. A name in neither passes in capitals.

**4.1 Verbs the tables miss** (rows R). The owner's item (r) and its twins in the tools the guard already
knows.
- R1, `deploy-ask`, ask: a cloud CLI that runs a command on a live host or container (`aws ssm send-command`,
  `aws ecs execute-command`, `az vm run-command invoke`, `az aks command invoke`, `az container exec`) or
  deploys in a way the table misses (`az webapp deployment source config-zip`, `… deployment slot swap`),
  with the CLI's global options in front of the command group (`aws --profile prod --region eu-central-1
  ssm …`). The reads of the same groups stay silent (`aws ssm list-commands`, `get-command-invocation`,
  `describe-…`).
- R2, `delete-guard`, ask: a package or a tool version is removed: the removing verb of `uv`, `poetry`,
  `yarn`, `conda`, `mamba`, `gem`, `bun`, `pdm`, `pipenv`, `cargo`, `bundle`, `pyenv`, `nvm`, `fnm`, `volta`,
  `asdf`, `rustup`, `apt-get`, `apt`, `dnf`, `yum`, `apk`, `snap`, `brew`, as the rows name them. `npm
  uninstall`, `pip uninstall` and `brew uninstall` ask today (Rs).
- R3, `delete-guard`, ask: a download cache or the installed set is emptied (`uv cache clean|prune`,
  `npm cache clean --force`, `pip cache purge`, `go clean -modcache`, `brew cleanup`, `brew autoremove`, …):
  the offline checks of this kit run from these caches.
- A table per tool with its source, not an expression over the whole line: `grep -rn "uv remove" docs` stays
  silent (Rs).

**4.2 Tools that run the command after them** (rows T). `timeout`, `caffeinate` and `strace` are read today
(Ts); these are not: `unshare`, `ltrace`, `gdb --args`, `lldb --`, `valgrind`, `noglob`, `nocorrect`, the zsh
modifier `-`, `lockf`, `ssh-agent`, `fakeroot`, `faketime`, `unbuffer`, `taskset`, `chrt`, `nsenter`,
`runuser`, `pkexec`, `gosu`, `systemd-run`, `firejail`, `watchexec`, `hyperfine`, `entr`, `op run --`,
`aws-vault exec … --`, `doppler run --`, `dotenv`, `launchctl`, `sshpass`, `xcrun`. For each: where its
command starts (which of its options take a value, whether `--` is needed, whether the command is one quoted
word that is a script, as with `hyperfine '…'` and `watchexec '…'`), from its manual, in the reader's tables
(`_NC_WRAPPERS` 2385, `_NC_SUB_WRAPPERS` 2395, `_NC_OPTION_RUNNERS` 2408, `_NC_SCRIPT_OPTIONS` 2411,
`_NC_SCRIPT_WORDS` 2422; read by `_nc_wrapped`, `_nc_sub_wrapped`, `_nc_option_wrapped` and `_nc_scripts`)
and, where the first pass needs it, in `_WRAPPERS`. Then every shell rule answers for the command behind it as for the plain command: T1
`delete-guard`, T2 `git-guard`, T3 `host-install`, T4 the others.

**4.3 The Homebrew names of the GNU tools** (rows U). Homebrew installs coreutils, findutils, grep and
gnu-sed with a `g` in front (`grm`, `gcp`, `gfind`, `gxargs`, `ggrep`, `gsed`, `genv`, `gtimeout`, …). Where
a table or an expression of a shell rule holds the plain name, the `g` name is the same tool: U1
`delete-guard` asks, U2 a write to a secret file is denied, U3 the wrappers (`genv`, `gnice`, `gnohup`,
`gstdbuf`, `gtimeout`, `gchroot`, `gtime`) are looked through, U4 a search tool's pattern is no path. One
mapping in one place, with the list of names and its source (the formulae's file lists), not a second set of
table entries. A name that only looks like one (`gh`, `git`, `go`, `gem`, `grep`, `gzip`, `gdb`) is not
mapped: only `g` + a name the mapping lists.

**4.4 The net for `git`, `gh` and `az`** (rows G; decision 3b). In a simple command whose command word no
table knows and which is no text tool (`echo`, `printf`, `man`, `which`, `type`, `tldr`), a later
word that is `git`, `gh` or `az` (also with a path in front) is taken as the start of that tool's command,
and `git-guard`, `protected-branch` and `tracker-guard` judge the words from there. Whatever they would answer
for the plain command, ask or deny, the net answers **ask**: the guard does not know what the word in front
does. G1 `git-guard`, G2 `tracker-guard`, G3 `protected-branch` on `main`. Nothing like it for `rm` (decided).
Silent stays: the tool's reads behind an unknown word (`mytool git status`, `mytool gh issue list`), text
(`echo git commit --no-verify -m x`), `which git gh az`. Behind a wrapper the tables know, the plain verdict
stands as today (`npm exec -- git push --force` denies).

**4.5 GraphQL** (rows L; decision aa). `gh api graphql` with a query that holds the word `mutation`:
`tracker-guard` denies when the mutation's field name holds `Issue` or `Label` (`closeIssue`, `updateIssue`,
`reopenIssue`, `createIssue`, `deleteIssue`, `addLabelsToLabelable`, `removeLabelsFromLabelable`,
`createLabel`, `deleteLabel`), asks for any other mutation (`addComment`, `mergePullRequest`, …)
and when the query cannot be read from the line (`-F query=@file`, `--input file`, a value that is only a
variable); a query stays silent. The same for `curl`, `wget` and httpie to `api.github.com/graphql`. The REST
twins deny today and keep denying.

**4.6 `git update-ref`** (rows D; decision ab). `protected-branch` denies it when the ref is
`refs/heads/<protected>`, whatever branch is checked out, or `HEAD` while a protected branch is checked out;
the deleting form `-d` of such a ref is denied too; `--stdin` asks. Silent: other branches, tags,
`refs/remotes/…`, `git commit-tree`.

**4.7 A shell fed by a pipe the guard cannot read** (rows I; decision ad). A shell (`sh`, `bash`, `zsh`,
`dash`, `ksh`) as a command word behind a pipe, with no script operand and no `-c`, fed by anything but a
literal `echo` or `printf` (group A reads those) or a `cat` here-document: the reader cannot read the program,
so the rules that read through it ask through its "could not read" path (`CommandNotRead`). The rows pin
`delete-guard` and `git-guard`; the other rules that read through the reader may ask too. Silent
stays: `bash run.sh`, `. ./run.sh`, `cat data.txt | bash process.sh`, `yes | bash install.sh`,
`cat run.sh | grep bash`. Not decided, leave as it is: `bash < run.sh`, `bash <(cat run.sh)`,
`eval "$(cat run.sh)"`, `echo "$X" | bash`, a shell on another host fed by a pipe.

**4.8 Commands that print a stored secret** (rows V; decision af). `secret-shell` asks. V1 is what the owner
named (`vault kv get`, `op read`, `kubectl get secret -o yaml`, `gh auth token`), V2 the rest of the table of
the handover's note with its spellings, V3 five forms the drafting session added. The table and its silent
side (list, status and metadata calls; `kubectl get secret app` without an output format) are in
`docs/HANDOVER-2026-11-17.md`, "Secret stores (af)". A table per tool with its source. Plan rev 3 (step 1.7)
will later deny a read of the owner's GitHub credentials; an ask here does not stand in its way.

**4.9 `az` writes** (rows Z; decision ag, and the owner's answer of 2026-11-18 on how a write is told).
`deploy-ask` asks for every `az` call whose verb is not a known read (`list`, `show`, `get-*` and the other
reads the Zs rows name, the help and version probes), the verb being the last plain word in front of the
first option. Z1 and Z2 are both due. Silent stays (Zs): reads, help probes, `az repos pr create`, and calls
that change only this machine (`az login`, `az account set`, `az config set`, `az bicep build`,
`az aks get-credentials`). A list of write verbs was the other answer and is not taken: a verb such a list
misses would stay silent.

**4.10 A capital letter, three leftovers of group A, and a merge.**
- Y1: `guard_config_class` (1587) reads the path twice, as written and in lower case, the same two readings
  as `secret_class` (553) since 0.8.0: a kind from either reading asks. The home prefix is compared the same
  way.
- W1: `tracker-guard` finds the GitHub API host whatever its case, scheme included. gh's own `api` reading
  and the Azure DevOps host already ignore case (Ws).
- W2: for `brew` and `gem` the verb is compared in lower case when it is written all in capitals. Only these
  two tools: `gh`, `npm`, `uv`, `poetry`, `go`, `kubectl` and `pip` refuse such a verb (`SC/semantics4.log`).
- W3, W4: `tracker-guard` asks for `gh pr merge`, whatever its argument and in every spelling of group A's
  `gh` reading (`-R`, `--repo`), and for a `PUT` to `…/pulls/<n>/merge` through `gh api`, `curl`, `wget` or
  httpie; with `--admin` it denies, as the Azure DevOps twin `--bypass-policy` is denied today. Another call
  under `…/pulls/<n>/` is no merge.

**4.11 What the reviews of group A left** (rows X).
- X1: an `export NAME=value`, `declare -x`, `typeset -x` or `set -a` inside the script of an `eval` reaches
  the commands that follow the `eval` in the same line; today it is read after them. `bash -c 'export …'`
  does not reach them and stays silent (Xs).
- X2: `LEFTHOOK=false` switches lefthook off like `LEFTHOOK=0` (its documentation; not measured here).
- X3: an `ssh` option behind the host name is ssh's own, so `ssh build -T <<EOF` has no command and the body
  is a script, like `ssh -T build <<EOF` today. With a command behind it the body is that command's data.
- X4: a here-document on a group `{ …; }` or a subshell `( … )` is the standard input of the commands inside:
  a shell among them that reads standard input gets the body as its script. `{ cat; } <<EOF` and
  `while read …; done <<EOF` stay data.
- X5: a `)` that closes a `case` pattern inside `"$( … )"` does not close the substitution; the commit form
  with such a body is not denied, and a shell fed inside it is read.
- Not part of this work: a NUL character in the command (name it in `left_out`).

**4.12 Group C: asks that go away** (rows K; decision 3a). The one place where a verdict gets weaker, and
only for these forms. Each K id has its neighbours in Ks that keep today's verdict; read them first.
- K1 `find`'s pattern operand is no command (`find . -name yarn`); `-exec yarn` and `-execdir yarn` keep
  asking.
- K2 `git restore --staged` changes the index only. K4 a preview deletes nothing (`git clean -n`,
  `kubectl delete --dry-run=client`, `git worktree prune --dry-run`). K5 a help probe as the sole argument
  (`rm --help`).
- K3 a search tool's pattern is no path (`grep -rn .env docs`). K8 the word after an exclude option
  (`tar --exclude .env`). K9 the text of `echo` and `printf` (`echo .env >> .gitignore`). K6 `ls`, `stat`,
  `test` and `[` on a secret path. K7 the git commands that report names (`git check-ignore`, `git ls-files`,
  `git status`).
- K6, K7 and K9 are silent only as a simple command at the top level of the line whose output is not piped
  onward: `ls .env | xargs cat` and `cat $(echo .env)` read the file and keep asking.
- K10 `command -v codex` inside a client boundary names a tool and runs nothing.
- K11 inside a client boundary a search tool's pattern is text and no command (the owner's answer of
  2026-11-18). `grep -n -E 'gemini|openai|ollama' README.md` asks today because the first pass of
  `rule_egress_guard` (1372; `segments`, 492) splits the line at every `|`, also inside a quoted word, and
  takes the name behind it for a command word; the reader pass reads the same line right and is silent. Drop
  a hit of the first pass only when it lies in the word the reader gives as the pattern of a search tool
  (`_SEARCH_TOOLS` (690) and `git grep`: the operand `_search_pattern` (694) names, or the value of `-e` or
  `--regexp`). The same holds for the folded reading, through which the capital spelling asks
  (`'A|OPENAI|B'`). Keep the first pass for everything else and do not make it quote-aware as a whole: it is
  the only pass that asks for a quoted script handed to a tool the reader does not know
  (`mytool 'grep x notes.txt | ollama run m'`: first pass ask, reader pass silent, measured on 0.8.0; a Ks
  row). A hit is dropped for its place in the line, not for its text alone: a line that holds the same words
  once in a pattern and once in such a quoted script still asks (a Ks row). The reader pass stays as it is, so a pipe the shell really makes into such a tool, a command
  substitution inside the pattern and an unquoted pattern keep asking (Ks). The same `|` in a quoted word of
  another tool (`echo 'a|openai|b'`, `sed`, `awk`, `jq`) is not decided: it keeps asking, and you name it in
  `left_out`. A name at an end of the pattern (`'openai|ollama'`) is silent today already, because the
  quote stays glued to it.
- The keep list keeps asking: `find . -name .env`, `cat ca.pem`, `chmod 600 .env`, `cp .env.example .env`,
  `touch .env`, `git reset f`, `git rm --cached f`, `git branch -d x`, `wc -c .env`, `ssh-add`.

## 5. Steps (one commit each, in this order)

0. `test(guard): pin the verdicts 0.9.0 must not change` — every row whose id ends in `s` or `t`, as a
   literal table in `tools/guard/tests/test_table_forms.py` with the parametrised tests the later steps
   extend. Green on 0.8.0 as it is.
1. `deploy-ask`: rows R1.
2. `delete-guard`: rows R2, R3.
3. the reader: tools that run a command: rows T1 to T4.
4. the Homebrew names: rows U1 to U4.
5. the net: rows G1 to G3.
6. `tracker-guard`: GraphQL: rows L1 to L3.
7. `protected-branch`: `git update-ref`: rows D1, D2.
8. the reader: a shell fed by a pipe it cannot read: rows I1.
9. `secret-shell`: secret stores: rows V1 to V3.
10. `deploy-ask`: `az` writes: rows Z1, Z2.
11. capitals: rows Y1, W1, W2.
12. `tracker-guard`: a merge: rows W3, W4.
13. what group A left: rows X1 to X5.
14. group C, `delete-guard` and `host-install`: rows K1, K2, K4, K5.
15. group C, `secret-shell` and `egress-guard`: rows K3, K6 to K11.
16. fixtures: one ask and one deny case per harness for a form of this work, added in
    `tools/guard/tests/make_fixtures.py` and generated with it.
After step 13 the first checker must exit 0 on the four B files; after step 15 on all five, and the file
checker on its file.

## 6. Report (your final answer, at most 900 words, no file dumps)

- `done`: what now works, one line per step, with the test names that prove it.
- `commits`: the hash and subject of each commit, in order.
- `checks`: the final lines of the last suite run (ruff; pytest on 3.13 and on 3.9) and of both checkers.
- `red_first`: for each step, one row that failed before the change (one line of output).
- `existing_tests_changed`: each one, with the row that asks for it (rule 10), or `none`.
- `deviations`: every point where you departed from this brief, and why.
- `left_out`: what you saw and deliberately did not do (adjacent gaps, limits, forms that still pass). These
  go into the decision log, so be exact: the command and the observed verdict.
- `timing`: the time of one hook call through `guard.py hook` for a plain command, for the longest row, and
  for a 100 kB command with and without a tool name in capitals, before and after (median of a few runs).
- `files`: the paths you changed or created.
- If you stopped early under rule 14: `stopped_after`: the last committed step, and what the next one needs.
