# Evidence: guard 0.9.0, groups B and C, built on the owner's machine

Scope: the pull request of tracker item #57, branch `feat/guard-0.9.0`, built on 2026-11-18 and 2026-11-19 on
the owner's machine by two orchestrating sessions, five engineer agents and one reviewer agent. The checks
behind the record (`DECISIONS.md`, block of 2026-11-19 on guard 0.9.0) ran from scratch folders of that machine,
which a restart deletes. This folder keeps what would go with them: the output of each check at the last commit
that touches the guard or its tests (`@@HEAD@@`), the reviewer agent's report with its probe files, every
engineer's report, and the receipts of the review by a fresh context. All times are UTC.

Three commits matter for reading the files. `b2f4e2a` is the last one that changes a rule (the eighth fix
round). `8f0a893` changes comments in the guard and adds rows; its guard is the same program
(`checks/same-program.txt`). `@@HEAD@@` adds rows only, so its guard file is that of `8f0a893` byte for byte.
Lint, the suite, the rows, the rewritings, the planted breaks, the replay and the timing ran at `@@HEAD@@`. The
checks that read the guard file alone (the runs under a terminal, the lines built from parts, the per-character
check, the quote fuzz) ran at `8f0a893` and their files name that commit.

Every command in these files is data. The guard judged it as a string; a command was run only where a file
says so, by a scratch script, in a scratch folder, against a stand-in file (`secret.txt` with one marker line)
in place of `.env`.

## Files

| File | What |
|---|---|
| `ruff.txt`, `pytest-py313.txt`, `pytest-py39.txt`, `captures.json` | `ruff check tools` and the whole suite on Python 3.13 and 3.9 at `@@CAPTUREHEAD@@` (the commit of the record, two commits of prose after `@@HEAD@@`), captured with `tools/tracker/evidence_export.py capture`: lint clean, @@SUITE@@ on both. |
| `checks/rows-and-cells.txt` | At `@@HEAD@@`: the 2,190 shell rows and 36 file rows; the twenty-two tables of `tools/guard/tests/test_table_forms.py` compared line for line with their frozen files; the forms no engineer saw (@@UNSEENLISTS@@ lists, @@UNSEENROWS@@ rows; one row is red by a wrong expectation of the drafting session, named in the record); every verdict that is weaker than at 0.8.0, by the kind that asks for it; the 248 flags of the local search tools; the cost of each rule on lines of 100 kB. |
| `checks/suite-and-rewritings.txt` | At `@@HEAD@@`: lint and suite as the session ran them; each row's command judged again in rewritings that keep what it does; the multi-line check; the new guard beside 0.8.0 on the rewritten text; the head beside the design copy and beside the head of the seventh round (177 verdicts stricter, none weaker). |
| `checks/same-program.txt` | The guard at `8f0a893` beside the guard at `b2f4e2a`: both files parsed, every docstring taken out, the syntax trees compared. Seven lines of text differ (comments and one docstring), the program does not. Then the guard at `@@HEAD@@` beside that of `8f0a893`: the same sha256. |
| `checks/terminal-round-7.txt`, `checks/terminal-round-8.txt` | The rows of the seventh and the eighth round, each run in zsh 5.9.1 and bash 5.3.15 in a fresh scratch repository (git 2.55.0), once with pipes and once under a pseudo-terminal. Per row: the expectation, one letter per guard (`s` silent, `a` ask), and which shell showed the marker (`Z`, `B`). The first line of each file names the guards. In the second file the last two guards are the head of the seventh round with one planted break each: the rows `Fm` are the ones that tell them from the head. |
| `checks/terminal-round-8-added.txt` | The same for the 25 rows added after the review of the eighth round (a process substitution, zsh's `=( )`, a glob qualifier beside a git report) and for the 28 lines they were chosen from. The last three guards are the head with the bracket rule taken out, with the rule of the eighth round taken out, and with both: only the last is silent anywhere. |
| `checks/terminal-round-7-added.txt` | The same for the 8 rows added to the seventh round after the planted breaks at `8f0a893`. The last two guards are that head with one planted break each (`--paginate` on the list of plain options; `--config-env` taken like `-C`): each is silent on its rows, the head on none. No shell printed the file on these lines in a fresh scratch repository. |
| `checks/shells-round-5.txt`, `checks/shells-round-6.txt` | The rows of the fifth and the sixth round run in both shells: no row disagrees with what the shells do. |
| `checks/lines-from-parts.txt` | The enumerating check: @@ENUMLINES@@ lines built from parts, each judged by the guard; the @@ENUMSILENT@@ it is silent on were run in zsh and bash; none prints the stand-in file. |
| `checks/per-character.txt` | Every character from U+0001 to U+007F glued to a brace, a separator or the report in 25 line shapes (3,300 lines): no line on which the guard is silent and a shell prints. |
| `checks/quote-fuzz.txt` | The quiet check's reading of quotes beside the lexer's on 400,000 random strings: no difference. |
| `checks/planted-breaks.txt` | Each rule of the fix rounds broken once in a scratch copy of the tree and the guard's tests run: @@MUTATION@@ |
| `checks/planted-breaks-2a28378.txt` | The same run at the head of the seventh round, where two breaks let every test pass. It led to the rows `Fm` of the eighth round (record, bullet on what the session's checks found). |
| `checks/planted-breaks-8f0a893.txt` | The same run one commit before the head, where two breaks of the seventh round let every test pass: its rows for them were held by the eighth round as well. It led to the 8 rows of `@@HEAD@@`. |
| `checks/replay-and-timing.txt` | The recorded tool calls of 45 days on the owner's machine handed to guard 0.8.0 and to `@@HEAD@@`, in both boundaries, and the hook timing. Totals per rule only: no command text, no path, no project name. |
| `checks/doc-commands.txt` | Every command that `README.md` and `docs/USING-AT-WORK.md` name with a verdict, judged by the guard at `@@DOCHEAD@@`: @@DOCROWS@@ of @@DOCROWS@@ as written. The rows the check read follow the result. |
| `reviewer/report-1.md` | The reviewer agent's report on the build head `8879cd5`, word for word as it handed it back on 2026-11-18 at 20:35: BLOCKER, 22 findings. |
| `reviewer/probes/` | The probe files the report names (`c1-secret.txt` to `c19-files.txt`, `cost-units.txt`, `gen_cost.py`), as the reviewer left them. |
| `engineers/01-…` to `engineers/@@ENGLAST@@-…` | The hand-back reports of the five engineers in the order they came, word for word: the build in two parts, the first fix pass, the second round, its addendum, the review fixes, the fourth to eighth rounds, and the two sets of rows added after the eighth. The frame line the harness puts in front of a hand-back is cut, and so are the two blanks it puts in front of each line. |
| `fresh-review-8879cd5.json`, `-d1052b1.json`, `-abab75a.json`, `-2a28378.json`, `-b2f4e2a.json`@@FRESHFILES@@ | The receipts of `bin/fresh-review`, each named by the head it read; `base` in each names the commit it was read against. |
| `SHA256SUMS` | The sha256 of each file above as it was written here. |

Paths of the owner's machine are replaced in every file: `<WT>` is the build worktree, `<S8>` the engineers'
scratch folder, `<ORCH>` and `<PAD>` the first session's scratch folders, `<PAD2>` the second session's,
`<HK>` the handover checkout, `<MAIN>` the main checkout, `<HOME>` the home folder.

## Gaps

- The scripts that made these files are not here. They are scratch files of the owner's machine and are kept
  on the branch `docs/handover-2026-11-17`; the row files they read are the tables of the test module.
- The replay's detail file names every changed call with its command text. It holds commands of the owner's
  other repositories and stays on his machine; only the totals are here.
- The session transcripts are not here: every tool call with its input, the dialogs, the engineers' briefs.
  They stay with the two Claude Code sessions on the owner's machine (`8ded1a05-…` and `f4bb0a13-…`).
- The sums in `SHA256SUMS` were taken on the machine that made the copies; they show that a file did not
  change after the copy, not that the copy was true. For the receipts the sum is that of the text with the
  paths replaced, not of the tool's own file.
- The measurements are of one machine: git 2.55.0, zsh 5.9.1, bash 5.3.15, macOS. `xh` is not installed there
  and is read from its help.
- The review by a fresh context read the change in parts (record, bullet on where the change left the usual
  path). @@FRESHGAP@@
- Six planted breaks of the oldest list no longer apply: later rounds replaced the lines they changed, and the
  lists of those rounds break the new lines.
- No traceability table: the acceptance rows are test cases in `tools/guard/tests/test_table_forms.py`, and the
  pull request lists the fifteen criteria of #57 with their state.
