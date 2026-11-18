# Tracker item for groups B and C (the second pull request)

Written by a cloud session on 2026-11-18 and finished on the owner's machine the same day, after his answers.
Not filed yet: the owner files it with
`python3 tools/tracker/tracker.py new --title … --ac … --scope … --scope-limit … --source …`, one `--ac` per
criterion (the call is printed by `g080/item_cmd.py`, see the end of this file), and nothing is built before
his `owner ready`.

What the first version of this text left open, and how the owner answered on 2026-11-18 (`DECISIONS.md`, block
of 2026-11-18 on guard 0.9.0, groups B and C):

- Open questions 1, 2, 3, 5 and 6 of `docs/HANDOVER-2026-11-17.md`: each as recommended there. They stand in
  criteria 9, 10 and 11.
- The forms the reviews of group A left: they go into this pull request (criterion 12).
- The six calls in the head of `g080/rows-b4.txt` and the five in the head of `g080/rows-b5.txt`: he kept all
  eleven.
- The version: 0.9.0. Group A took 0.8.0 to `main`.
- One kind was added to group C: a search tool's quoted pattern that names another vendor's LLM tool (K11,
  in criterion 13).

## Title

Guard 0.9.0: tools, verbs and secret stores the tables did not name are read, and eleven false asks go away

## Acceptance criteria

1. `deploy-ask` asks when a cloud CLI runs a command on a live host or container
   (`aws ssm send-command …`, `aws ecs execute-command …`, the `az` twins), and `delete-guard` asks when a
   package or a tool version is removed (`uv remove requests`, `poetry remove …`, `gem uninstall rake`,
   `apt-get remove …`) or a download cache is emptied (`uv cache clean`, `npm cache clean --force`,
   `brew cleanup`); the listing and reading verbs of the same tools stay silent
2. a tool that runs the command after it and is in no table today is read like `timeout` and `caffeinate` are
   (`unshare -n rm -rf build`, `noglob git push --force origin feat`, `op run -- gh issue close 3`,
   `hyperfine 'terraform apply -auto-approve'`): every shell rule answers as for the plain command
3. the Homebrew names of the GNU tools are the same tools: `grm -rf build` asks, `gcp x .env` and `gtee .env`
   are denied, `genv FOO=1 git push --force origin feat` is denied, and `ggrep -rn .env docs` is a search
4. beside the tables, `git`, `gh` and `az` are judged wherever the name stands as a later word of a command
   whose first word no table knows: `mytool git push --force origin feat`, `mytool gh issue close 3` and, on
   `main`, `mytool git commit -m x` ask; `echo git commit --no-verify -m x`, `mytool git status` and
   `which git gh az` stay silent
5. `tracker-guard` denies a GraphQL mutation that names an issue or a label (`closeIssue`, `updateIssue`,
   `addLabelsToLabelable`, …) and asks for any other mutation and for a query it cannot read
   (`-F query=@file`); a GraphQL query stays silent; the same through `curl`, `wget` and httpie
6. `protected-branch` denies `git update-ref` on a protected branch, whatever branch is checked out, and asks
   for `--stdin`; other branches, tags, remote-tracking refs and `git commit-tree` stay silent
7. a shell that reads its program from a pipe the guard cannot read asks (`cat run.sh | bash`,
   `base64 -d x | sh`); `bash run.sh`, `cat data.txt | bash process.sh` and `yes | bash install.sh` stay
   silent
8. `secret-shell` asks for a command that prints a secret from a store (`vault kv get`, `op read`,
   `kubectl get secret -o yaml`, `gh auth token`, `aws secretsmanager get-secret-value`,
   `az keyvault secret show`, …); the list, status and metadata calls of the same tools stay silent
9. `deploy-ask` asks for every `az` call whose verb is no known read; reads, help probes,
   `az repos pr create` and calls that change only this machine stay silent
10. a capital letter does not pass a rule: the guard's own configuration path
    (`.claude/SETTINGS.json`, `tools/GUARD/guard.py`) asks like the plain path, the GitHub API host
    (`https://API.GITHUB.COM/…`) is read like the plain host, and a verb of `brew` or `gem` in capitals
    (`brew UNINSTALL jq`) answers like the plain verb
11. `tracker-guard` asks for a merge of a pull request through `gh` or the API (`gh pr merge 3`,
    `gh api -X PUT repos/o/r/pulls/3/merge`) and denies `gh pr merge --admin`; a pull request that is read,
    opened or changed stays silent
12. the hook gate switched off by an export inside `eval`, or by `LEFTHOOK=false`, is denied like
    `export HUSKY=0; git commit -m x`; a script fed to `ssh host` with an option behind the host, or to a
    shell inside a group or a subshell, is read; a `case` pattern inside `"$( … )"` causes no false deny
13. these asks go away (group C: the owner's list of 2026-11-17 and one kind he added on 2026-11-18):
    `find . -name yarn`; `git restore --staged f`; a search pattern such as `grep -rn .env docs`; the
    previews `git clean -n`, `kubectl delete --dry-run=client`, `git worktree prune --dry-run`; a help probe
    such as `rm --help` as the sole argument; `ls -la .env`, `stat .env`, `test -f .env`;
    `git check-ignore .env`, `git ls-files .env`, `git status .env`; `tar --exclude .env`;
    `echo .env >> .gitignore`; `command -v codex`; and, inside a client boundary, a search tool's quoted
    pattern that names another vendor's LLM tool (`grep -n -E 'gemini|openai|ollama' README.md`). The keep
    list of 2026-11-17 keeps asking (`find . -name .env`, `cat ca.pem`, `chmod 600 .env`,
    `cp .env.example .env`, `touch .env`, `git reset f`, `git rm --cached f`, `git branch -d x`,
    `wc -c .env`, `ssh-add`), `ls .env | xargs cat` and `cat $(echo .env)` keep asking, and so do a pipe the
    shell really makes into such a tool (`grep x notes.txt | ollama run m`) and a quoted script handed to a
    tool the guard does not know (`mytool 'grep x notes.txt | ollama run m'`)
14. the acceptance rows written before the build hold: 968 shell rows and 36 file rows, 523 of them red at
    0.8.0 and 481 that held and keep holding (on the branch `docs/handover-2026-11-17`, with the first 16
    characters of the sha256: `rows-b.txt` 298 `2838db90cdeb3391`, `rows-b4.txt` 255 `79070141a5c27b03`,
    `rows-b4-az.txt` 123 `0954f87caef58d0f`, `rows-b5.txt` 119 `060edafbc1898915`, `rows-b5-files.txt` 36
    `ebc9fff2cb9de6d3`, `rows-c.txt` 173 `2ddadbf963c73eb3`); apart from the rows of criterion 13, nothing
    that asked or denied at 0.8.0 stops doing so; forms the engineer did not see are checked and reported; a
    replay over the recorded session commands of the last 45 days, as far back as the machine's transcripts
    reach, lists every verdict that changed, with the number of asks that went away and the number that
    came; the time of the hook through its real entry point is measured before and after
15. ask and deny fixtures for both harnesses; `ruff check tools` and `pytest` pass on Python 3.9 and 3.13;
    README, `docs/SYSTEM.md` and `docs/USING-AT-WORK.md` say what changed; one `DECISIONS.md` block names what
    this version does not cover

## Scope

`tools/guard/guard.py`, `tools/guard/tests`, `README.md`, `docs/SYSTEM.md`, `docs/USING-AT-WORK.md`,
`DECISIONS.md`

Scope limit: no cloud-session mode, no rule for a harness's own GitHub tools and no shell reading for
`guard-config` (plan rev 3, step 1.7); nothing for `aws` and `gcloud` writes (after the pilot), for code in
another language, for `printenv` and a bare `env`, for the ways to move a protected branch that are no commit
and no `git update-ref`, for a `|` inside a quoted word of a tool that is no search tool; no sandbox

## Source

owner, 2026-11-17 ("A: secrets and bypasses, B: tables, C: fewer prompts and cost"; "do decisions as
recommmended" on five recommendations, recorded in `DECISIONS.md`, first block of 2026-11-18, on guard 0.8.0,
group A, last bullet) and 2026-11-18 ("All as recommended (Recommended)" on open questions 1, 2, 3, 5 and 6 of
`docs/HANDOVER-2026-11-17.md`, on the forms the reviews of group A left and on the version; "Add it
(Recommended)" on an eleventh kind for group C; "Keep all eleven (Recommended)" on the calls the drafting
session had made in the row files; recorded in `DECISIONS.md`, block of 2026-11-18 on guard 0.9.0, groups B
and C)

## The row files

All on the branch `docs/handover-2026-11-17`, measured on guard 0.8.0 on the owner's machine on 2026-11-18
(`main` at `ec23d5d`; `guard.py` is the same file there as at `6ff07cf`, the merge of #54). "Red" is due with
the build; "hold" must keep holding. The unseen forms are for the orchestrating session only.

| File | Rows | Red | Hold | sha256, first 16 | For |
|---|---|---|---|---|---|
| `g080/rows-b.txt` | 298 | 164 | 134 | `2838db90cdeb3391` | criteria 1 to 3 |
| `g080/rows-b4.txt` | 255 | 136 | 119 | `79070141a5c27b03` | criteria 4 to 8 |
| `g080/rows-b4-az.txt` | 123 | 61 | 62 | `0954f87caef58d0f` | criterion 9 |
| `g080/rows-b5.txt` | 119 | 62 | 57 | `060edafbc1898915` | criteria 10 to 12 |
| `g080/rows-b5-files.txt` | 36 | 14 | 22 | `ebc9fff2cb9de6d3` | criterion 10 |
| `g080/rows-c.txt` | 173 | 86 | 87 | `2ddadbf963c73eb3` | criterion 13 |
| `g080-heldout/heldout-b.txt` | 295 | | | `a4b7be795c674ad5` | unseen forms for criteria 1 to 3 |
| `g080-heldout/heldout-b4.txt` | 295 | | | `f39a693089ca2570` | unseen forms for criteria 4 to 9 |
| `g080-heldout/heldout-b5.txt` | 79 | | | `425e3db2273d8729` | unseen forms for criteria 10 to 12 |
| `g080-heldout/heldout-c.txt` | 27 | | | `73059d7d47ee3036` | unseen forms for the eleventh kind of criterion 13 |

Together: 968 shell rows and 36 file rows, 523 of them red at 0.8.0. Criterion 14 carries these figures into
the item, since the tracker builds the item from the criteria, the scope and the source and this table stays
here.

The owner's answers of 2026-11-18 struck no row. They added the rows of the eleventh kind to `rows-c.txt` (34
rows, 16 of them red) and the file `heldout-c.txt`, made nine `az` forms of `heldout-b4.txt` due that had
waited for question 5 as observed forms, and changed the head of every file. So every hash was taken again
that day; the first version of this text named 934 shell rows, 507 red rows and other hashes. The counts are
frozen when the item names them; a file changed after that gets a new hash and a line in the decision log, as
the rows of #50 did.

`python3 -I g080/item_check.py <this folder's parent> <guard.py of main>` compares this table and criterion 14
with the files and measures every row file again; on 2026-11-18, on guard 0.8.0, all of it was consistent.

The call that files the item is printed by `python3 -I g080/item_cmd.py g080/item-b.md`, which refuses a file
that still holds an open mark. The criteria quote guarded commands as text, so the guard will ask about the
command line that files the item; the owner runs it in his own terminal or confirms that one ask.
