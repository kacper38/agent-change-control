Step 11 is committed as `ae5361b` "test(guard): add fixtures for a fed script and a name in capitals". The generator was not run.

The counter claim holds: `generate()` numbers files per rule, harness and decision in list order. Both cases sit at the end of their rule's list in `make_fixtures.py`, so they took the next free numbers.

New files, under `tools/guard/tests/fixtures/`:
- `delete-guard/claude/ask/76-echo-rm-rf-build-bash.json`
- `delete-guard/copilot/ask/76-echo-rm-rf-build-bash.json`
- `git-guard/claude/deny/19-git-commit-no-verify-m-x.json`
- `git-guard/copilot/deny/19-git-commit-no-verify-m-x.json`

`test_fixtures.py` passed on the first run (1428 passed, including `test_corpus_matches_generator`).

Final lines:
- Suite: ruff "All checks passed!"; "py39 check: 61 files, 0 finding(s)"; "5139 passed, 9 skipped in 54.83s" on Python 3.13. Python 3.9 was not run on this machine.
- `expect.py`: "total rows 597 | hold 597 | red 0", exit 0.
- `expect_files.py`: "total rows 66 | hold 66 | red 0", exit 0.

Existing fixture files changed: none. Five paths were staged: `make_fixtures.py` and the four new files. `git -C <REPO> status --short` shows only `?? .claude/worktrees/`.

cloud: none. The probe of the `git add` line came back silent.
