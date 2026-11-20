Steps 14 to 16 are built and committed, tests first each time. Both checkers now hold on every row, and nothing is uncommitted. Only what is new since my first report:

**done**
- **14, K1:** host-install's `find` hands over to a command only after `-exec`, `-execdir`, `-ok` or `-okdir` (`_hi_real`).
- **14, K2/K4/K5:** `_delete_preview` covers:
  - `git restore --staged` or `-S`, without `-W` or `--worktree`;
  - the previews `git clean -n|--dry-run` (letters after an `e` in a cluster are its pattern), `git worktree prune -n` and `kubectl delete --dry-run=client|server`;
  - a help probe as the only argument after the tool and its deleting verb.
  
  It applies only when the whole line is one simple command with nothing nested (`_single_preview`). deploy-ask uses the same check, so `kubectl delete --help` is silent there too.
- **15, K3:** secret-shell's first pass leaves a search tool's pattern out, as the reader pass already did.
- **15, K8:** the word after an exclude or include option is a pattern, not a path.
- **15, K6/K7/K9:** `_quiet_reports` / `_take_quiet` silence `echo`, `printf`, `ls`, `stat`, `test`, `[`, `[[` and `git check-ignore|ls-files|status`. That holds only for a top-level simple command whose output goes nowhere. Each form is counted off once, so a twin of it nested elsewhere in the line is still read.
- **15, K10:** `segments()` reads `command -v|-V` as a lookup.
- **15, K11:** `_only_in_search_patterns` drops a first-pass egress hit only when every place in the line that gives that segment lies inside a quoted search pattern. That is the operand, or the value of `-e`/`--regexp`. The reader pass is unchanged.
- **16:** fixtures for both harnesses: delete-guard asks for `uv cache clean`, tracker-guard denies a `gh api graphql` closeIssue mutation. Both are appended at the end of their rule's cases, so nothing is renumbered.
- All three steps are proven by `test_table_forms.py::test_row` and `test_fixtures.py`.

**commits**
- ed735fe fix(guard): stop asking for previews, help probes and staged restores
- 6bafb11 fix(guard): stop asking for secret names that are text, tests or lookups
- 8879cd5 test(guard): add harness fixtures for a cache clean and a GraphQL write

**checks** (at 8879cd5)
- ruff: `All checks passed!`
- pytest: `6307 passed, 9 skipped` on 3.13 (46.7 s) and on 3.9 (66.3 s).
- First checker on all five shell files: `total rows 968 | hold 968 | red 0`, exit 0.
- File checker: `total rows 36 | hold 36 | red 0`, exit 0.

**red_first**
- 14: `test_row[K1-795]` FAILED (`find . -name yarn`), 30 failed.
- 15: `test_row[K3-816]` FAILED (`grep -rn .env docs`), 56 failed.
- 16: no red line. The code was already in place, so the new fixtures passed on first run.

**existing_tests_changed**
- **K2:** `make_fixtures.py`, the delete-guard case that expected `git restore --staged main.py` to ask, for both harnesses. It moved to a new allow block, and `git restore main.py` took its ask slot. The fixtures are regenerated, and the stale `ask/16-git-restore-staged-main-py.json` files are in `SC/eng/moved14/`.
- **K3:** `test_review_fixes.py`, two P2 rows went from ask to silent: `grep -c ".env" notes.txt` and `git grep -n "\.pem" -- tools`.

**deviations**
- In step 16 I first inserted the deny case in the middle of tracker-guard's list. That renumbered later fixtures, so I backed it out and appended the case at the end. The stray generated files are in `SC/eng/moved16/`.

**left_out**
- `grep -e ".env" notes.txt`: secret-shell still asks; an `-e` value is not dropped as a pattern, and a P2 test still asserts the ask.
- `sudo ls .env`, `( ls .env )`, and any line with a here-document: secret-shell still asks; only plain top-level forms go silent.
- `bash -c 'git clean -n'`, `git clean -n; ls`: delete-guard still asks; only a one-command line goes silent.
- `echo 'a|openai|b'` and the same `|` inside a quoted word of `sed`, `awk` or `jq`: egress-guard still asks, as the brief leaves undecided.
- A pattern whose exact quoted text also appears elsewhere in the line counts as a pattern at both places (K11).
- A NUL character in the command.

**files** (under `<WT>/tools/guard/`)
- `guard.py`
- `tests/test_table_forms.py`
- `tests/test_review_fixes.py`
- `tests/make_fixtures.py`
- `tests/fixtures/delete-guard/{claude,copilot}/{ask/16-git-restore-main-py.json, allow/54-git-restore-staged-main-py.json, ask/77-uv-cache-clean.json}`
- `tests/fixtures/tracker-guard/{claude,copilot}/deny/44-gh-api-graphql-f-query-mutation-closeiss.json`

Main checkout shows only `?? .claude/worktrees/`.
