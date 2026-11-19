# g090: the scratch tools behind guard 0.9.0, groups B and C

What the two orchestrating sessions of 2026-11-18 and 2026-11-19 wrote beside the build of tracker item #57 and
ran the checks of its record with (`DECISIONS.md` on `main`, block of 2026-11-19 on guard 0.9.0; the outputs are
in `evidence/2026-11-19-guard-0.9.0-groups-b-c/` there). None of it is on `main`: these are scratch files, kept
here so that the next change to the guard can run the same checks. The tools of group A are beside this folder
(`g080/`, `g080-heldout/`), and so are the briefs and rows written before the build (`g080/brief-b.md`,
`g080/rows-b*.txt`, `g080/rows-c.txt`, `g080-heldout/heldout-*.txt`).

| Folder | What |
|---|---|
| `orch/` | First session. `verify-fix.sh` and `verify-head2.sh` are the two scripts that ran every check at a head: the rows, the tables of the test module beside their frozen files (`rows_in_module.py`), the unseen forms, the cells weaker than 0.8.0 (`weaker_cells.py`, sorted by `cell_kinds.py`, the commands read in `cells-read.txt`), the rewritings (`rewrite_regress.py`), the multi-line check, the cost of long lines. `make_mutations*.py` write the lists of planted breaks (`mutations-*.json`), `mut-run2.sh` runs them. `closeout-b.sh` is the replay and the hook timing, `replay-pair.sh` the replay of two heads. `fresh.sh` calls `bin/fresh-review` for a range. `probe-*.txt`, `draft-rows-*.txt`, `heldout-b-fix*.txt` and `lex-lines*.txt` are lines the session judged or measured. |
| `orch/sem/` | The measurements in real shells: `quiet_enum.py` with `quiet_oracle.py` (lines built from parts, the silent ones run in zsh and bash), `char_enum.py` (the per-character check), `rows_measure.py` (the rows of a round in both shells), and one script per question about what a tool does. |
| `orch/proto/` | How a design was tried before it went to an engineer: `make_proto.py`, `check-proto*.sh`, the planted breaks on the prototype. |
| `orch/evidence/` | `assemble.py` (copy with local paths replaced, scan, sums) and `capture.py`. |
| `rows/` | The frozen row files of the fix rounds (`rows-b-fix*.txt`: the tables of `tools/guard/tests/test_table_forms.py` equal them line for line), the brief of each round, the design diff of rounds five to eight, the rewriting scripts the engineers were given, the quote fuzz. |
| `orch2/` | Second session (rounds seven and eight and the close-out): `p7/pty_probe.py` runs lines under a pseudo-terminal, `p7/` and `p8/` hold the prototype checks and planted breaks of those rounds, `p8/cand-*.txt` and `p9/cand-f84.txt` the lines the rows were chosen from, `mut/mut-par.sh` the parallel runner of the planted breaks, `checks/` the readers of the terminal logs and the comparison of two guards as programs, `docs/` and `evidence/` the scripts that filled the record, the pull request and the evidence folder. |

Paths of the machine the files were written on are replaced: `<ORCH>` and `<PAD>` are the first session's
scratch folders, `<PAD2>` the second session's, `<S8>` the engineers' folder, `<WT>` the build worktree, `<HK>`
this folder's parent in a checkout of this branch, `<MAIN>` the main checkout, `<HOME>` the home folder, `<TMP>`
the temporary folder, `<PROJECT>` the harness's name for the project. A script runs again once those are set.

Not here, on purpose: the logs, the copies of the guard at each head (every one is a commit of the branch
`feat/guard-0.9.0` or a planted break from the lists), and everything the replay wrote. The replay reads the
recorded tool calls of the owner's machine; its outputs hold commands of other repositories and stay there.
For the same reason four lines shaped after recorded commands are cut from `orch/cells-read.txt` and
`orch/probe-k9-subst.txt`, one list of such lines is left out, and so are the two scripts that wrote the plans
of the copies (their lists of texts to scan for name the machine's user).
Commands in the files here are test strings: the guard judged them as text, and a scratch script ran one only
against a stand-in file in a scratch folder.
