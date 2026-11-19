# Addendum to the second fix round of guard 0.9.0, groups B and C (item #57)

You are a third engineer on this branch. Guard 0.9.0 was built (17 commits), fixed once (22 commits) and a second
time (7 commits); the head is `d2ecce7`, its suite is green and every row written so far holds. The orchestrating
session then judged every known command again beside guard 0.8.0, in more rewritings, and with a second command
on the same line. That found four things. This file is the whole order: three topics, three commits. The
decisions in it are made; do not reopen them. Where the code cannot follow one, stop and report.

`tools/guard/guard.py` is a PreToolUse hook (standard library only, Python 3.9 and later). A shell rule answers
silent, ask or deny for a command line. The file has about 4,300 lines: read the functions named below (line
numbers at `d2ecce7`), not the whole file.

## Where and how

- Worktree: `<WT>`, branch `feat/guard-0.9.0`.
  Work only there and in `<SCRATCH>`, the folder this file is in (it holds `expect.py`, `probe.py`,
  `rewrite_check.py` and the row files). Your own scratch scripts and data files go into `<SCRATCH>/eng3/`.
  No push, no pull request, no merge of `main`.
- Never read the folders `g080-heldout`, `orch`, or anything under `docs/handover-2026-11-17`. Do not run
  `tools/tracker/tracker.py`.
- Commands under test are data: they stand in row files, data files and test tables, never on a command line,
  and are never run. No `cd` in shell calls (`git -C`, absolute paths). Files are written with Write and Edit,
  never with a here-document. Nothing is deleted with `rm`; a stray file is moved into `<SCRATCH>/eng3/moved/`.
- Nothing is installed (no `pip install`, `uv add`, `npx`, `brew`). The checks run offline from the local cache.
  `sh <SCRATCH>/../g070/suite.sh <worktree> tools/guard/tests` runs `ruff check` and the guard tests on Python
  3.13 and 3.9; without the last argument it runs the whole suite, as CI does (at `d2ecce7`: `6872 passed,
  9 skipped` on both). One test call by hand:
  `uv run --directory <worktree> --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools/guard/tests`.
  Run the guard tests while you work, and the whole suite on both Pythons before your last commit.
- Commits: one topic, one commit; subject `type(scope): imperative`, lower-case start, at most 72 characters;
  the body says why and names the rows; a line `Refs #57` (never `Fixes`, `Closes`, `Resolves`); the last line
  is the trailer of your own model, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage by
  explicit path. `VERSION` stays `"0.8.0"`; the orchestrating session sets it. No file outside
  `tools/guard/guard.py` and `tools/guard/tests/` changes.
- Tests first: add the rows of a topic, see the due ones red, then change the code. Note one red line per topic
  for your report.

## The rows

`<SCRATCH>/rows-b-fix2-add.txt`: 146 rows, sha256 starts `afdd2104d0fa454b`. Check them with
`python3 -I <SCRATCH>/expect.py <guard.py> <SCRATCH>/rows-b-fix2-add.txt` (the guard file comes first). At
`d2ecce7` it ends with `total rows 146 | hold 62 | red 84`.

- Ids `F37` (17), `F38` (39), `F39` (7) and `F40` (21) are due: all red at `d2ecce7`. Ids `Fs` (62) hold at
  `d2ecce7` and must keep holding.
- They go into `tools/guard/tests/test_table_forms.py` as one **new** table, `ROWS_FIX2_ADD`, with its own
  `FIX2_ADD_TABLE = _rows(ROWS_FIX2_ADD)` and its own parametrized test (`test_fix2_add_row`), built like
  `ROWS_FIX2` / `test_fix2_row`. The file has three blocks, each under a line `# --- topic N ---`. Each commit
  adds the block of its topic (the first one also the head comment), so every commit is green; after the third
  the table is the file, line for line, comments included. The thirteen existing tables stay exactly as they
  are: the orchestrating session compares each with its frozen file. All rows of the branch keep holding
  (1,527 shell rows and 36 file rows before this round).
- A command that starts with a double quote is a JSON string: it carries line breaks. `_rows` reads it.
- A row you think is wrong: do not change it. Leave it red and say why in the report.

## Topic 1: a pipe the guard cannot read is a finding of the read, not its end (rows F37, F40; one commit)

Since the build, a shell that reads its program from a pipe the guard cannot read makes the line ask (decision
"ad"; `_PIPE_NOT_READ`). It is raised as `CommandNotRead` in two places of the reader: `_nc_read` (line 3602)
after `_nc_compound_pipe` (3913), and the last lines of `_nc_fed` (3850). The exception ends the read of the
whole line, and that is the fault:

- **F40.** `bash -c 'git push --force origin feat'; cat run.sh | sh` was denied by 0.8.0 (the reader finds the
  nested push) and is only asked now, by every rule: the unread pipe ends the read before the nested script is
  judged. The same for a fed script, a substitution, the hook switch (`_git_env_gate`, line 1626), `tee .env` in
  a nested script, the tracker's owner verb. One pipe added to a line turns a refusal into a prompt. A deny the
  first pass of a rule finds on the plain line still wins today (`Fs`).
- **F37.** `echo 'git commit --no-verify -m x' | { sh; }` was denied by 0.8.0: its reader takes `{ sh` for the
  shell and reads the words of the echo as the script (`_nc_fed`). Now `_nc_compound_pipe` sees a group behind
  the bar and raises first. `echo 'ls -la' | { sh; }` was silent and is a prompt now.

The decision:

1. An unread pipe no longer raises. The reader records it and reads on exactly as 0.8.0 did: `_nc_fed` feeds
   nothing for that pipe, the commands of the line and of everything it nests are returned as before. The memo
   (`_nc_cached`, 3567) keeps the mark beside the commands, inputs and environments; an accessor beside
   `nested_inputs` and `nested_envs` hands it out, for the full and for the local reading.
2. The ask is added where a rule would answer without a deny. Six rules end in `reader_pass` (3707): there,
   after every command is judged, a deny wins and otherwise the ask for the unread pipe joins the other asks,
   with today's words (`READER_MSG` with `_PIPE_NOT_READ`). `rule_delete_guard` (644, through `_delete_judge`
   622) and `rule_deploy_ask` (2067) read `nested_commands` themselves and only ever ask: they add the same
   ask. Every one of the eight rules that asks for such a line today keeps asking (`Fs`: `cat run.sh | sh` for
   each rule, `egress-guard` inside the client boundary).
3. A bar through which `_nc_fed` has read a script (it returned the command behind the bar as the runner) is
   no unread pipe: `_nc_compound_pipe` leaves out exactly those bars. Not by the look of the command behind the
   bar: `cat run.sh | { ssh -n build; sh; }` and `cat run.sh | { BASH; }` ask today and must keep asking in
   every rule (a first try of the orchestrating session, "the command behind the bar runs its standard input",
   made the first of them silent for six rules).
4. `CommandNotRead` keeps what it meant at 0.8.0 (too deep, too many words or tools). Look at every other caller
   of `nested_commands` and of the accessors (`delete_what` 454, `_truncate_in_the_open` 481, `_single_preview`
   612, `_git_env_gate` 1626, `_local_simple_commands` 1747, `deploy_what` 2048, `_search_patterns` 2124): each
   gets the commands again where it got the exception since the build, which is what 0.8.0 gave it.
   `rule_secret_shell` (1387) takes `failed is None` for "the read went through" before it adds the input
   redirections: a line with an unread pipe is read through now, so keep its redirections in the verdict
   (`cat run.sh | sh; cat < .env`).

An existing test that pins the exception for an unread pipe changes with this; name each in the report.

## Topic 2: a GraphQL body through httpie and wget (rows F38; one commit)

`_http_graphql_query` (2801) and the GraphQL branch of `_tracker_seg` (2896). Criterion 5 of the item: a
mutation that names an issue or a label is denied, any other mutation and a document the guard cannot read ask,
a query is silent, "the same through curl, wget and httpie". Silent at `d2ecce7`:

- httpie's `--raw`: `http POST https://api.github.com/graphql --raw '{"query":"mutation { closeIssue(…) … }"}'`.
- httpie with a body the line does not show: `@q.json`; a pipe (`cat q.json | http POST …/graphql`); and the
  redirection `< q.json`, which the second round reads on a plain line and inside a group, wherever the first
  pass does not see it: in `bash -c '…'`, `eval`, a fed or here-document script, a substitution, a function
  body, behind `sudo` inside a group, with a line the shell joins.
- wget's `--method=POST --body-data='…'` and `--body-file=q.json` (`--post-data` and `--post-file` are read).

Measured by the orchestrating session, HTTPie 3.2.4 with `--offline` (the request is built and printed, nothing
is sent); `http`, `https` and `xh` are read alike (xh by its help; it is not installed here):

| call | request |
|---|---|
| no item, standard input `/dev/null`, a file, a pipe, or whatever a script inherits | `POST`, the body is the standard input |
| `--raw '<body>'`, `--raw=<body>` (no method word needed) | `POST` with that body |
| `@q.json` | `POST` with the content of the file |
| `--ignore-stdin` or `-I`, no item | `GET`, no body |
| `GET` and standard input | `GET` with the body |
| an item (`query=…`) and standard input | usage error, nothing sent |

wget 1.25.0, from its help: `--body-data=STRING`, `--body-file=FILE`, both with `--method`.

The decision:

1. httpie's `--raw DATA` and `--raw=DATA` are a body, read as curl's `-d` is (JSON with a `query`).
2. An httpie call to the GraphQL endpoint in which no document is found asks, whatever the line shows of its
   standard input: in every shell an agent runs, the standard input is no terminal, so httpie sends it, and the
   guard cannot see what it holds. No reading of redirections or pipes is added to the reader for this; the
   reader pass already hands `_tracker_seg` the words from every command word, nested scripts included, and
   that is enough. The same answer covers `@file`.
3. wget's `--body-data` reads as `--post-data`, `--body-file` as `--post-file`.
4. The reading of `<` in `_http_graphql_query` goes. Without a document on the line the call asks anyway
   (point 2); with one, httpie refuses to mix it with a body on standard input (the last line of the table), so
   the document on the line decides, as it does today wherever the redirection is not seen (`bash -c 'http POST
   …/graphql query="query { viewer { login } }" < q.json'` is silent: `Fs`; the plain line asks today and is a
   due row, expected silent).
5. The second round also added, in the first pass of `rule_tracker_guard` (2659), the skipping of leading shell
   words. If it is unused after your change (every row of every table and the check below hold without it),
   cut it; when in doubt leave it and say so.

## Topic 3: a redirect target behind a continuation (rows F39; one commit)

`rule_secret_shell` (1387) finds the files a line writes with `_REDIRECT_RE` (836) on the line as written
(line 1393). `echo x > \⏎.env` writes `.env` (the shell joins the two lines) and is silent, at 0.8.0 too. What
is new: 0.8.0 asked for `test -f .env || cat .env.example > \⏎.env`, because the line also names the file in a
report; since the build such a report is quiet, so nothing is left of that line.

The decision: the redirect targets of `rule_secret_shell` are read on the line with every backslash and line
break pair taken out, as the shell joins it. Only there: the first passes of the other rules keep reading the
line as written.

## The check beyond the rows

`<SCRATCH>/rewrite_check.py` judges every one-line command of the row files again in up to nineteen rewritings
that keep what the command does (its docstring has the list) and writes every cell where a rule that asks or
denies the command as written is weaker for the rewriting:

`python3 -u -I <SCRATCH>/rewrite_check.py <SCRATCH>/expect.py <SCRATCH>/rewrite_readers.py <guard.py> <SCRATCH>/eng3/rewrite.json <SCRATCH>/rows-b.txt <SCRATCH>/rows-b4.txt <SCRATCH>/rows-b4-az.txt <SCRATCH>/rows-b5.txt <SCRATCH>/rows-c.txt <SCRATCH>/rows-b-fix.txt <SCRATCH>/rows-b-fix-add.txt <SCRATCH>/rows-b-fix-add2.txt <SCRATCH>/rows-b-fix-add3.txt <SCRATCH>/rows-b-fix-add4.txt <SCRATCH>/rows-b-fix-add5.txt <SCRATCH>/rows-b-fix2.txt <SCRATCH>/rows-b-fix2-add.txt`

At `d2ecce7` it prints `weaker cells 60 | distinct commands 4 | crashes 0` (about three minutes), and
`python3 -I <SCRATCH>/rewrite_list.py <SCRATCH>/eng3/rewrite.json` starts with
`turns: ask>silent 9, deny>ask 51` and lists the cells per rewriting and rule (`--turn 'deny>ask'`, `--kind`,
`--rule` narrow the list).

Wanted at your last commit: **no cell that ends in `silent`**, no crash, and `deny>ask` only in the rewritings
`pipesub`, `subpipe`, `bracepipe`, `suberrpipe` and `subnlpipe` (a script the guard reads in the plain form that
goes through a subshell, or comes out of a group or subshell: left out, see below). Every other cell you cannot
close: name it in the report with the reason; do not widen a rule to hide it.

## Left out on purpose: do not fix these

The lists of the two earlier briefs (`<SCRATCH>/fix-brief.md`, `<SCRATCH>/fix2-brief.md`, sections "Left out on
purpose") stand. Added by this addendum:

- a script the guard reads in the plain form that goes into the shell through a subshell (`echo '…' | (sh)`),
  through a compound, behind another command of a group (`echo '…' | { cd repo; sh; }`), or out of a group or
  subshell (`{ echo '…'; } | sh`): the line asks, the script is not read there;
- a body an `echo` pipes into httpie is not read (the line asks);
- `http --ignore-stdin …/graphql` and `http --offline …/graphql` without a body, and `http GET …/graphql`, ask
  although they send no document;
- an httpie call to a REST path of issues or labels with its body on standard input or in `--raw` (the older
  write rule, `_http_writes`, is not part of this round);
- `curl -K req.cfg`, `curl -F query=@q.graphql`;
- a redirection with `>|`, a target in a variable, and a continuation in the first pass of any rule but
  secret-shell (`find . -name '*.tmp' \⏎-delete`).

If you meet another form of this kind, write it down and leave it.

## Report (at most 400 words)

Commits (sha, subject); per topic one line on what changed in the code and one red line from before the fix;
every existing test you changed and why; the last lines of ruff and of the whole suite on both Pythons; the
`weaker cells` line of `rewrite_check.py` and the `turns:` line of `rewrite_list.py`, with the cells that stay
and why; deviations from this order; rows left red and why; what you saw and left out.
