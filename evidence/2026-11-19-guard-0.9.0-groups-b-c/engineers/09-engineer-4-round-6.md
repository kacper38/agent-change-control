The sixth fix is in as one commit, a246385 fix(guard): quiet a secret report only when the check is certain of it, on top of 3bcab45. Not pushed; worktree clean; VERSION stays "0.8.0"; no raw carriage return in either file. One possible gap is below (P7).

- Rows: `total rows 97 | hold 34 | red 63` before the code change, `hold 97 | red 0` after. All 18 row files hold (2,009 rows).
- ruff: `All checks passed!`
- Python 3.13: `7360 passed, 9 skipped in 56.41s`
- Python 3.9: `7360 passed, 9 skipped in 83.93s (0:01:23)`
- Rewriting check: `weaker cells 35 | distinct commands 2 | crashes 0` and `turns: deny>ask 35`.
- Red counts under the breaks, each put back:
  - (a) `_printf_format` always true: red 28 (F61=21, Fs=7)
  - (b) no `\r`: red 9 (F63=7, Fs=2)
  - (c) `"case" in body.split()`: red 7 (F65=6, Fs=1)
- Written differently: only the docstrings of `_quiet_reports` and `_quiet_sub_end`; guard.py is otherwise byte for byte fix6-design-guard.py.
- Rules:
  - P7, possibly missing: git's pager hands a report's output to a program, and these are silent:
    - `git -c core.pager='xargs cat' -p ls-files .env`
    - `GIT_PAGER='xargs cat' git -p ls-files .env`
    - `git -c pager.status='xargs cat' -p status .env`

    Not measured in a shell; git likely starts no pager without a tty. Probe rows are in eng4/probe-fix6.txt.
  - `/opt/homebrew/bin` and `/usr/local/bin` can be written by the user, so their trust is only as strong as trusting PATH. That is the kind your brief leaves out.
- Seen and left: nothing else.
