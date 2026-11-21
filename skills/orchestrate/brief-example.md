# Brief: add a `--json` flag to the `report` command (tracker item #12)

## Goal

`app report --json` prints the report as one JSON object, so a pipeline can read it without parsing text.

## Decisions not to reopen

- The text output stays the default and does not change (DECISIONS.md, 2026-03-02).
- Standard library `json` only; no new dependency.

## Scope

- Add the flag to `src/app/cli.py`, one function that turns the report into a dict.
- Tests for the flag in `tests/test_cli.py`.

## Writable paths

- `src/app/cli.py`
- `tests/test_cli.py`
- `DECISIONS.md` (one line)

## Forbidden paths

- `.github/`, `pyproject.toml`, every other file under `src/`

## Forbidden actions

- No merge, no push to `main`, no package install, no comment on the tracker or the pull request.

## What to ignore

- The deprecation warning from the date library in the test output; it exists on `main` too.

## Done evidence

`python3 -m pytest -q tests/test_cli.py` exits 0, and `ruff check src tests` prints `All checks passed!`.

## Output format

One JSON object of the shape `worker-result/1` in `result.json` at the worktree root:
`{"schema": "worker-result/1", "branch": "feat/report-json", "head": "<40-hex commit>", "checks": [...], "not_verified": [...]}`.
Checked with `python3 tools/orchestration/assert_run.py worker result.json`.

## Report fields

The commits (short hash and subject), the open risks, and every departure from this brief with its reason.

## Size limit

At most 3 files and 150 changed lines; stop and report if more is needed.
