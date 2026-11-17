# Brief: guard 0.8.0, group A — forms that slip past an existing rule (2026-11-17, revised for the 0.7.1 base)

Repository: `agent-change-control`, a public kit of guard hooks and tools for AI-assisted platform work in
regulated environments. `tools/guard/guard.py` (0.7.1 on `main`) is the hook engine: standard library only,
Python >= 3.9. It judges every tool call of the sessions in this repository, including yours.

**Goal.** Eight shell rules already ask or deny for a secret file, a skipped commit gate, a forced push, a
tracker bypass, another vendor's LLM tool. Each can be passed today by writing the same thing another way
(`--env-file=.env` instead of `--env-file .env`, `--no-verif` instead of `--no-verify`, a script fed to `bash`
by a here-document, `GIT` instead of `git`, `.ENV` instead of `.env`). You close these forms. Nothing else
changes.

The owner (Kacper) approved this scope on 2026-11-17; the tracker item is #50. The design below is decided:
do not reopen it. If a decided point cannot work, stop that point, finish the rest, and say so in your report.

## 1. Where you work (read twice)

- Main checkout: `<REPO>`. Your shell starts there and returns there
  after every call. **You change nothing in it**: no edit, no staging, no commit, no branch switch. Its guard
  is the one that judges this session.
- Your worktree `WT`: `<REPO>/.claude/worktrees/g080-a`, branch
  `feat/guard-0.8.0`, at `origin/main` `e5826b7` (guard 0.7.1), no commit of its own yet. Every file you read
  or edit has a path that starts with `WT`. Every command names it; do not `cd`:
  - whole suite, both Pythons, lint (about two minutes; prints the final lines):
    `sh <SCRATCH>/g070/suite.sh <WT>`
  - one test file: `uv run --directory <WT> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools/guard/tests/<file>`
    (the same with `--python 3.9`)
  - lint: `ruff check <WT>/tools`
  - git: `git -C <WT> status --short`, `git -C <WT> diff`, `git -C <WT> add <paths>`, `git -C <WT> commit …`
- Baseline at `e5826b7`, measured today: `4347 passed, 9 skipped` on Python 3.13 and on 3.9; `ruff` clean.
- Scratch folder `SC` (data files of this brief; yours to write under `SC/eng/`):
  `<SCRATCH>/g080/`
  Never write temporary files into a checkout. Read nothing else in the scratchpad: only `SC` and the suite
  script named above.
- Before your final report run `git -C <REPO> status --short` and
  confirm it shows only `?? .claude/worktrees/`.

## 2. The acceptance rows (your definition of done)

- Three files. Format, one row per line: `id | branch[@client] | rule | expected | command`. `rule` is one
  rule name, or `shell` for all eight shell rules together (then `expected` is `silent`). A command that
  starts with `"` is a JSON string (line breaks).
  - `SC/rows-a.txt` (229 rows) and `SC/rows-a-added.txt` (10 rows): ids ending in `s` hold at 0.7.1 and must
    keep holding; the others are red at 0.7.1 (124 of the 239). Steps 0 to 7.
  - `SC/rows-a-caps.txt` (358 rows): hosts, tool names and secret file names in capitals. `Ct` (the plain
    form of the rows that follow it) and `Cs` (capitals that are none of these) hold at 0.7.1 and must keep
    holding; `C1`, `C2`, `C3`, `C4` are red at 0.7.1 (180 rows). Steps 8 to 10.
  - `SC/rows-a-files.txt` (66 rows) for the file tools, in its own format:
    `id | tool | rule | expected | path` with tool `Read`, `Write` or `Edit`. `Ft` and `Fs` hold at 0.7.1 and
    must keep holding; `F1` is red at 0.7.1 (34 rows). Step 9.
- Checkers; each prints every row that does not hold and a total, exit 0 when all hold. They call the rule
  functions through `RULES[...]` with the command or the path as a string. Nothing runs, no file is opened.
  - `python3 -I SC/expect.py <WT>/tools/guard/guard.py SC/rows-a.txt SC/rows-a-added.txt SC/rows-a-caps.txt --red`
  - `python3 -I SC/expect_files.py <WT>/tools/guard/guard.py SC/rows-a-files.txt --red`
- What git, curl and gh really do with these forms was measured today: `SC/semantics.log`,
  `SC/semantics2.log` (git 2.55.0, curl 8.7.1, gh 2.92.0), and for capitals `SC/semantics4.log`. Read the
  first two before step 5 and the third before step 8; they settle questions like "is `--no-ver` a bypass"
  (no: git refuses it as ambiguous) and "does `git COMMIT` commit" (no: git refuses the verb).
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
   message; `Refs #50` is right. If a commit is refused or asks for a passphrase, do not retry and do not
   work around it: leave the step uncommitted, stop there and report. No push, no branch switch, no rebase,
   no amend.
4. **Commands under test are strings.** Never run an install, deploy, delete, push or commit-gate bypass to
   see what it does. A probe loads the module and calls the rule function (as `SC/expect.py` does), or feeds
   the hook an event on stdin with `KZ_TELEMETRY_DIR` pointing at a temp folder.
5. **Edit files with the Edit or Write tool.** Never write a file through a here-document or a redirection.
   Keep candidate commands in data files or in the test module, never on a command line: the live guard
   reads your command lines, and a line that holds `rm -rf` or `git push --force` as text makes it ask the
   owner. Prefer one script per check (`python3 -I SC/eng/probe.py`) over many shell calls: every shell call
   can cost the owner a prompt, and he asked for fewer.
6. **Do not edit** `DECISIONS.md`, `README.md`, `AGENTS.md`, `docs/**`, `.github/**`, `.claude/**`, `VERSION`
   in `guard.py`, or anything this brief does not list. The orchestrating session writes the decision log,
   the docs and the version bump from your report. You edit: `tools/guard/guard.py`,
   `tools/guard/tests/test_bypass_forms.py` (new), `tools/guard/tests/make_fixtures.py` and the fixture files
   it generates, and an existing test only under rule 10.
7. **Test data is synthetic.** Do not read real transcripts under `~/.claude/projects` or the real telemetry
   folder `~/.claude/telemetry`. Tests use `tmp_path`; no test reads from the scratch folder.
8. **The test-guard scans test files for skip and focus markers.** Do not use them. Never name a non-test
   module `test_*.py`.
9. **Style of the code base:** small functions with a one-line docstring that says what and why, comments
   only where the reason is not obvious, plain words in messages. Match the file; do not tidy code you did
   not need to change. Every `except` is a decision: say in a comment why the error is handled that way. A
   guard rule must never let an exception escape: an uncaught error ends the hook with exit 1, and both
   harnesses then run the call unjudged. A table of option names in the code names its source (the tool's
   manual) in a comment.
10. **Tests first.** For each step put its rows into the test module, run it, keep one or two lines of the
    red output for your report, then make it pass. Change an existing test only where it asserts as silent a
    command that a row of this brief now asks or denies, and list each such change in your report.
11. **Nothing that asked or denied at 0.7.1 may stop doing so**, and nothing that was silent may start to ask
    except through the rules of section 4. The suite holds frozen expectations (the 0.7.1 egress entries
    among them) and timing tests; they stay green.
12. **Cost.** The hook has 3.5 s for all rules; a normal call takes about 0.1 s and must stay there. Reuse the
    reader's memo (`nested_commands`, `command_word_indexes`); do not lex the command once more per rule.
13. Before each commit run the suite script and keep its final lines for the report.
14. **If you run short of room.** Twelve steps are a lot for one context. Finish and commit the step you are
    in, then stop and report which steps are done and what the next one needs; the session that wrote this
    brief continues with you. Never start a step you cannot finish, and never leave a step half-committed.

## 4. Decided design

Read first (line numbers of 0.7.1): `combine` (262), `delete_what` (393), `segments` (478), `strip_heredocs`
(511), `_secret_seg` (594), `_secret_reader_seg` (661), `rule_secret_shell` (682), `_git_subcommand` (714),
`_git_guard_seg` (747), `rule_egress_guard` (1130), `_tracker_seg` (1518), `_hi_shell_reads_stdin` (1829),
the reader from `nested_commands` (2117) to `command_word_indexes` (2301) and what follows it, `RULES` (2500).

**4.1 secret-shell: where a secret path can stand in one word** (rows M, Q). Today only a bare word counts
(`_secret_seg` skips every word that starts with `-`). From now on a word of the command's arguments gives
these candidates, each classed by `secret_class` as before:
- the word itself (as today);
- the value of `--name=value` and `-name=value`;
- the rest of a short option glued to its value: `-i~/.ssh/id_ed25519`, `-T.env`, `-d@.env`;
- the path behind `@`: `@path`, `name@path`, `name=@path`, also with `;type=…` behind it (curl, httpie);
- the path of an input redirection: `<path`, `N<path` (not `<<`, `<<<`, `<(`, `<&`).
Not candidates: the value of an option that names a pattern to leave out or to match (`--exclude`,
`--exclude-dir`, `--exclude-from`, `--include`, `--glob`, `--iglob`, `--ignore`, `--filter`); an assignment
in front of the command (`KEY_FILE=server.key ./run.sh` stays silent, as today); a word that holds `://`
keeps today's treatment. `.env.example` and its kin stay silent through `secret_class`, as today. The same
candidates count in the reader pass (`_secret_reader_seg`), so the form is found behind a wrapper and in a
nested script. `git add|stage` of a secret file denies wherever git's own options stand before the
subcommand: use `_git_subcommand`.

**4.2 A script fed to a shell** (rows N, E1's last two, `rows-a-added.txt`). Every rule strips here-document
bodies before it reads (`strip_heredocs`), because a body is usually data. That stays for data. A body is a
script, and is read like the script of `bash -c '…'`, when:
- the simple command the here-document belongs to runs a shell that reads its program from standard input:
  `sh bash zsh dash ksh fish ash` with no `-c` script and no script file operand (`_hi_shell_reads_stdin`
  has this test), also behind the wrappers the reader knows (`sudo bash <<EOF`, `timeout 60 bash -s <<EOF`,
  `docker exec -i web sh <<EOF`);
- or it belongs to an `ssh` command with no command after the host (`ssh build <<EOF`): the remote login
  shell reads it;
- or it belongs to a `cat` without a file operand whose output goes through one pipe into such a shell or
  such an ssh (`cat <<EOF | bash`).
The words of an `echo`, and the format and arguments of a `printf` (a written `\n` is a line break), in front
of one pipe into such a shell or ssh, are a script in the same way (`echo '…' | bash`, `printf '…\n' | sh`,
`echo '…' | ssh build bash`).
Intended mechanics: the fed script enters the reader as a nested script of the simple command that names
the shell, the way a here-string does today (`_nc_here_strings`), so that the local reading (host-install,
protected-branch stop at `ssh`, `docker`, `kubectl`), the depth limit, `CommandNotRead` and the memo apply
unchanged, and git-guard's `elsewhere` judgment follows. The rules then hand the reader the command with its
here-documents, and the reader takes the bodies out before it lexes (a body is never lexed as commands of
the line itself). `<<-` strips leading tabs. If these mechanics cannot work, keep the properties (one shared,
memoised function; local reading honoured; a data body never read) and say what you chose.
Stays as it is, silent, and is no part of this work: a script the guard cannot read from the line (a file:
`cat script.sh | bash`, `bash < script.sh`; a variable: `echo "$CMD" | bash`; a substitution; a decoder:
`base64 -d … | bash`; a filter that rewrites the text on the way). Do not add an ask for these.

**4.3 tracker-guard** (rows O). `gh` accepts `-R`/`--repo` before the command group and between group and
verb (`gh -R o/r issue close 3`, `gh issue --repo o/r close 3`; measured). Find `issue <verb>` and
`label <verb>` past gh's options, with the value of `-R`/`--repo` skipped in every spelling (`-R v`, `-Rv`,
`--repo v`, `--repo=v`). In `gh api` read the method and the write flags in every spelling gh accepts:
`-X v`, `-Xv`, `--method v`, `--method=v`; `-f k=v`, `-fk=v`, `--field=k=v`, `--raw-field=…`, `-F…`,
`--input v`, `--input=v`. Reads stay silent (`gh -R o/r issue list`, `gh api -XGET …`). `gh api graphql` is
not part of this work.

**4.4 git-guard and delete-guard** (rows P). All of this applies in the first pass and in the reader pass.
- Short options in one word. `git push`: `-f` anywhere in a cluster denies, but the letters after `-o` are
  its value (`-ofast` is a push option). `git commit`: `-n` in a cluster denies unless a letter before it
  takes a value: `-m -F -C -c -t` take the rest of the word or the next word, `-u` and `-S` take an optional
  value glued on (`-uno` is `--untracked-files=no`; measured: the hook runs). `-mn` is the message `n`.
- Long options cut short. git accepts a unique prefix of a long option (measured: `--no-verif` and
  `--no-veri` skip the hook; `--no-ver` is refused as ambiguous). Rule: a word `--X` or `--X=v` counts as
  the guarded option `--G` when `G` starts with `X` and `X` is not empty. This can only over-match words
  git itself refuses as ambiguous, so it costs nothing. Guarded names: `no-verify` for `commit`, `push`,
  `merge`, `pull`, `am` and `rebase` (the exact word `--no-verify` keeps denying for every subcommand, as
  today; `git merge --no-verif` is refused by git as ambiguous, so a deny there is free); for push `force`,
  `force-with-lease`, `force-if-includes`, `mirror`, `all` (git-guard) and `delete`, `prune` (delete-guard:
  `--delete`, `-d`, `--prune` and their prefixes ask; `--prune` removes remote branches that have no local
  counterpart). `--atomic`, `--no-verbose`, `--no-edit`, `--follow-tags`, `--no-thin`, `--dry-run` are not
  prefixes of a guarded name and stay silent.
- Where the words are. `_git_guard_seg` gets the words from the command word on, and `segments()` drops
  assignments and wrappers. The environment of a git call is in the words before its command word
  (assignments, `env NAME=value …`) and in an `export NAME=value` of an earlier simple command of the same
  line; read them from the reader's token lists. A plain `NAME=value;` without `export` does not reach git.
- The hook gate through the environment. `HUSKY=0`, `LEFTHOOK=0`, or `SKIP=` with any value, set for a git
  `commit`, `push`, `merge`, `pull`, `rebase`, `am`, `cherry-pick` or `revert` denies: as an assignment in
  front of it, through `env`, or exported earlier in the same line. The same variables in front of anything
  else are silent (`HUSKY=0 npm ci` is husky's own advice for CI).
- The hook gate through configuration. The key is case-insensitive (`core.hookspath` works; measured).
  A git call of any subcommand denies when it sets `core.hooksPath` for that call: `-c core.hooksPath=…`
  among git's own options, `--config-env=core.hooksPath=VAR`, or `GIT_CONFIG_KEY_<n>=core.hooksPath` (also
  `GIT_CONFIG_PARAMETERS` naming the key) in the environment of the call. The one silent value is
  `.githooks` in the `-c` form (the kit's own directory).
- `git config` that writes `core.hooksPath` asks (git-guard): `git config [options] core.hooksPath <value>`,
  `git config set …`, `--unset`, `unset`, `--unset-all`, with `-C dir` or a scope option in front. Silent:
  the value `.githooks` (the installer runs `git -C <target> config core.hooksPath .githooks`), and reads
  (`--get`, `get`, the name alone, `--list`).
- `git push --repo=origin` is handled correctly today and stays: git reads a plain word after `--repo v` as
  the repository (measured), so `--repo origin feat:main` is no push to `main`.

**4.5 egress-guard** (rows E). It reads only `segments()` today. Add the reader pass with the full reading
(a container or another host still sends the data out): another vendor's LLM tool at a command word
(`_OTHER_LLM_CLIS`), or `curl`/`wget`/`http`/`https`/`xh` at a command word with an LLM host among its
words, asks. Only inside a client boundary (`cfg["boundary"] == "client"`), as today. A tool name that is
not at a command word stays silent (`which gemini`, `grep -rn codex docs`, `man codex`).

**4.6 Capitals** (rows C; added by the owner's words after the item was made ready). The owner's file system
ignores case, so a tool's name in any mix of capitals runs the real tool: `GIT`, `Git`, `/usr/bin/GIT`,
`SUDO`, `BASH -c` (measured: `SC/semantics4.log`). A host name is never case-sensitive. Every table lookup
and every expression of the guard is case-sensitive today, so such a name is an unknown word:
`SUDO rm -rf build` and `BASH -c 'git commit --no-verify -m x'` pass all eight rules.
- **Hosts (step 8).** `_LLM_HOSTS_RE` matches whatever the case of the host. Nothing else changes in it:
  the bare `huggingface.co` and `docs.together.ai` stay out, also in capitals.
- **Secret file names (step 9): section 4.7.**
- **Names (step 10): judge the command twice.**
  1. `fold_names(text)` returns the text with every known tool name that is written with a capital letter
     replaced by the spelling the tables use. A candidate is a maximal run of characters other than white
     space, `;`, `|`, `&`, `(`, `)`, `<`, `>` and the backtick. Of a run only the part after its last `/`
     counts. Quotes and backslashes inside that part are looked through and kept (`G"I"T` becomes `g"i"t`,
     `\GIT` becomes `\git`, `'GIT'` becomes `'git'`). The part is folded only when, without quotes and
     backslashes, it is not a known name as written and its lower-case form is one. So these stay as they
     are: `.ENV`, `FOO=GIT`, `$BASH`, `${SHELL}`, `GIT-123-fix`, `README.md`, every option, every file
     name, every verb, every host.
  2. The known names are built once at import: the keys of every table a shell rule or the reader compares
     a command's name with (`_WRAPPERS`, `_RM_CLASS`, `_DELETE_TOOLS`, `_WRITERS_LAST`, `_WRITERS_ALL`,
     `_SEARCH_TOOLS`, `_DEPLOY_TABLE`, `_OTHER_LLM_CLIS`, the `_HI_*` tables, the `_NC_*` tables, and what
     the earlier steps of this work add), one literal set for the names that stand only inside an
     expression, a tuple or a comparison in the code (`git`, `gh`, `sed`, `az`, `aws`, `eval`, `find`,
     `xargs`, `parallel`, `curl`, `wget`, `http`, `https`, `xh`, `cat`, `echo`, `printf`, `tracker`, the rm
     class of `SHELL_RE`, the tools of `TOOL_RE`, the interpreters of `SCRIPT_RE`, the clients of
     `_SQL_CLIENT_RE`, …: read each expression and each `head == "…"`, `name in ("…", …)` for the names it
     holds), and the forms `_PIP_RE` and `_PYTHON_RE` accept (`PIP3.12`, `PYTHON3`). A key that is not
     lower-case itself (`$SHELL`) is not a folding target. A name you miss is a form that still passes, and
     the unseen set looks for exactly that.
  3. Each of the eight shell rules answers for the command as written and, when `fold_names` changed the
     text, also for the folded text. A deny from either wins; asks are combined with `combine`. This is one
     wrapper around the eight entries of `RULES` (`delete-guard`, `secret-shell`, `git-guard`, `deploy-ask`,
     `egress-guard`, `protected-branch`, `tracker-guard`, `host-install`), not eight edits and not a
     `.lower()` at each comparison. A command without a capital name is judged once, by the same code path
     as today.
  Why two readings: three passes are expressions over the raw text (delete-guard, deploy-ask, host-install),
  which a change at the token comparisons would miss; some matches are case-sensitive on purpose (the SQL
  keyword `TRUNCATE` asks wherever it stands, the word `truncate` does not; `$SHELL`); and with the reading
  as written kept, nothing can get weaker.
  - delete-guard's script scan (`SCRIPT_RE`: the content of a script file the command names) reads the
    content as written and folded, the same way.
  - A here-document delimiter can be a tool's name (`<<SH`): it folds on both of its lines, so the body
    still ends where it ended. With `<<-SH` only the closing line folds and the folded reading takes the
    rest of the text as body; that is the safe direction (rows C3 hold a fed script of each kind, and a
    data body that must stay silent).
  - Tests beside the rows: for every known name `k`, `fold_names(k.upper() + " x")` gives `k + " x"`; a
    command without a capital name calls the wrapped rule once; a command with one calls it twice.
  - Not part of this work; do not build it, and name it in `left_out` when you see it pass: a verb or an
    option in capitals (`git PUSH`: git refuses it), the GitHub API host in capitals in tracker-guard
    (`curl -X PATCH https://API.GITHUB.COM/…`) and the guard's own configuration path in capitals in
    guard-config (`.claude/SETTINGS.json`, `tools/GUARD/guard.py`): the owner has not decided these two; a
    name that reaches the shell through a variable or an expansion.

**4.7 A secret file name in capitals** (rows C4 and F; the owner's word after the item was made ready).
`.ENV` opens `.env` on the owner's machine, and `secret_class` compares exact case: `_SECRET_NAME_RE`,
`_SECRET_IN_DIR`, `_SECRET_DIRS`, `_TFVARS_RE`. All three secret rules use that one function (secret-read,
secret-write, secret-shell), so `Read .ENV`, `Write certs/server.KEY` and `cat ~/.AWS/credentials` pass today.
Decided: `secret_class(path)` is the class of the path as written or, when that is none, the class of the
path in lower case. One change in one function; no rule changes. The same two readings as in 4.6, for the
same reason: `.env.EXAMPLE` asks today and keeps asking (as written it is a secret name), `.ENV.EXAMPLE`
stays silent (in lower case it is an example file), `prod.TFVARS` asks on a write like `prod.tfvars`. The
price the owner accepted: on a case-sensitive file system `.ENV` is another file and now asks.

## 5. Steps (one commit each, in this order)

0. `test(guard): pin the verdicts 0.8.0 must not change` — the 115 rows of the first two files whose id ends
   in `s`, as a literal table in `tools/guard/tests/test_bypass_forms.py` (id, branch, boundary, rule,
   expected, command), with the one parametrised test that the later steps extend. Green on 0.7.1 as it is.
1. secret-shell reads: rows M1-M4, Q1.
2. secret-shell: `git add` behind git's own options: rows Q2.
3. the reader: a script fed to a shell: rows N1, N2, N3 (E1's two fed rows turn green with step 7).
4. tracker-guard: rows O1, O2.
5. git-guard: short clusters and long options cut short: rows P1, P2, and P3's git-guard rows; delete-guard:
   P3's three delete rows.
6. git-guard: the hook gate through the environment and the configuration: rows P4, P5.
7. egress-guard: the reader pass: rows E1.
8. egress-guard: a host in capitals: rows C1, with the `Ct` and `Cs` rows of that part of the file.
9. the secret rules: a secret file name in capitals: rows C4 and F1, with their `Ct`, `Cs`, `Ft` and `Fs`
   rows (two C4 rows also name a tool in capitals, `CAT .ENV` and `CP config.txt .ENV`: they turn green
   with step 10).
10. every shell rule: a tool's name in capitals: rows C2 and C3, with their `Ct` and `Cs` rows.
11. fixtures: one ask and one deny case per harness for a form of this work, added in
    `tools/guard/tests/make_fixtures.py` and generated with it (`test_fixtures.py` checks that the files on
    disk are what the generator writes).
After step 7 the first checker run on the first two files must exit 0; after step 10 both checkers of
section 2 must exit 0 on all their files.

## 6. Report (your final answer, at most 800 words, no file dumps)

- `done`: what now works, one line per step, with the test names that prove it.
- `commits`: the hash and subject of each commit, in order.
- `checks`: the final lines of the last suite run (ruff; pytest on 3.13 and on 3.9) and of the checker.
- `red_first`: for each step, one row that failed before the change (one line of output).
- `existing_tests_changed`: each one, with the reason (rule 10), or `none`.
- `deviations`: every point where you departed from this brief, and why.
- `left_out`: what you saw and deliberately did not do (adjacent gaps, limits, forms that still pass). These
  go into the decision log, so be exact: the command and the observed verdict.
- `timing`: the time of one hook call through `guard.py hook` for a plain command, for the longest row, and
  for a 100 kB command with and without a tool name in capitals, before and after (median of a few runs).
- `files`: the paths you changed or created.
- If you stopped early under rule 14: `stopped_after`: the last committed step, and what the next one needs.
