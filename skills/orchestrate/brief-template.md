# Brief: <packet name> (tracker item #<N>)

<!-- Copy this file, fill every field, then lint it:
     python3 tools/orchestration/brief_lint.py <your brief>
     A field left as only a comment counts as empty, so this bare template fails the linter. -->

## Goal

<!-- One or two sentences: what the packet delivers and why. -->

## Decisions not to reopen

<!-- What is settled (plan rows, DECISIONS.md lines, the owner's answers); the worker builds on them. -->

## Scope

<!-- The work in this packet, as a short list; one packet = one tracker item = one branch = one pull request. -->

## Writable paths

<!-- The only files and folders the worker may create or change. -->

## Forbidden paths

<!-- Paths the worker must not touch, even to read-then-restore (CI, guard, secrets, other packets' files). -->

## Forbidden actions

<!-- Actions the worker must not take: merge, push to the default branch, install packages, comment on issues, ... -->

## What to ignore

<!-- Known noise the worker should not chase (pre-existing failures, unrelated warnings, adjacent clean-ups). -->

## Done evidence

<!-- The command that proves the packet done and its expected result, e.g. `pytest -q` exits 0. -->

## Output format

<!-- How the worker returns its result. Default: one JSON object of the shape worker-result/1,
     {"schema": "worker-result/1", "branch": "<branch>", "head": "<40-hex commit>",
      "checks": [{"command": "<command>", "exit_code": 0}], "not_verified": ["<what was not checked>"]},
     checked with `python3 tools/orchestration/assert_run.py worker <file>`. -->

## Report fields

<!-- What the short report beside the result names: commits, open risks, departures from the brief. -->

## Size limit

<!-- A number: files, lines of diff, minutes or USD the packet may take before the worker stops and reports. -->
