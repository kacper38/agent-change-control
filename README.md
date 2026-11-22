# agent-change-control

A change-control kit for **AI-assisted platform engineering in regulated
(GxP) environments**. It is a working agreement, deterministic hooks, a tracker
over GitHub Issues or Azure Boards, CI gates and an evidence export, shipped as
plain files that [Claude Code](https://claude.com/claude-code) and VS Code +
GitHub Copilot read the same way. Built for taking a service from ticket to
running, auditable infrastructure, with AI/RAG workloads as a first-class
concern.

The premise: the engineer decides, plans and verifies; the agent executes.
Every change must be defensible as validation evidence: plan first, one topic
per commit, external verification with shown output, decisions recorded.

Status 2026-11-03: the GitHub path is in daily use here; the Azure DevOps
path is verified offline only ([details](#status-and-verification)).

## What it is, and is not

It is:

- a working agreement, [`AGENTS.md`](AGENTS.md), that every harness loads;
- a guard hook that denies or asks before dangerous tool calls, in Claude Code
  and in Copilot, under two seconds and without network;
- one command, `tracker`, that is the only way an agent writes issues, work
  items or labels, with a transition table that says who may move what;
- CI gates (tests, commit messages, test-tampering, image tags) on GitHub
  Actions and on Azure Pipelines, with the same results;
- an evidence export that turns merged PRs, reviews, checks and tracker
  records into one JSON pack for a release;
- for this repository only, a box (`bin/box`, a skeleton): a local
  container in which a session builds with permission checks off, behind
  an egress list, with the hooks of a read-only copy of `main`.

It is not:

- an MCP server or a Claude plugin: everything is a committed file, so the
  policy version is a commit;
- an LLM judge inside hooks: every hook decision is a regular expression or a
  path rule with fixtures from both harnesses;
- a replacement for branch protection or for a human approval. The server
  settings it needs (rulesets on GitHub, branch policies and process rules on
  Azure DevOps) are documented with the API call that proves each one, not
  enforced by the kit;
- a bot identity. Until a GitHub App exists, PRs in this repository are
  authored and merged by the owner;
- support for Azure DevOps Server, Jira or Forgejo (deferred), service hooks,
  a token cache, or a dependency on GitHub Advanced Security.

Where the harness weakens a hook, the kit says so: Copilot hook timeouts fail
open, and the Copilot cloud agent turns every `ask` into `deny`.

## How a change flows

Issues are the system of record. State lives in two label families, `type/*`
and `status/*` (tags or work item states on Azure DevOps). An agent may create,
claim, block and submit for review; only a human at a terminal may promote or
close.

| State | Moved by | Verb | What is checked |
|---|---|---|---|
| backlog | agent | `tracker new` | title, acceptance criteria, scope, scope limit, source |
| ready | human | `tracker owner ready N [N ...]` | definition of ready; the body is frozen from here |
| in-progress | agent | `tracker claim N --branch B` | one item in progress per login and seat (a box's seat, or the host); the branch is recorded |
| blocked | agent | `tracker block N --question "…"` | the question names a path or a field |
| review | agent | `tracker review N --pr URL` | PR head is the claimed branch; the body carries `Refs #N` |
| done | human | `tracker owner done N [N ...]` | merged by a human, green checks on the merge commit, every box ticked or waived |

Also `tracker list`, `show N`, `note N "…"` (no status change) and
`owner labels-sync`. Owner verbs refuse without a terminal.

For a phase, the owner runs two lines. When the phase's plan is approved:
`tracker owner ready 61 62 63`. When every pull request of the phase is
merged: `tracker owner done 61 62 63 --accept-all`, which prints per item the
title, the criteria, the pull request, the merge commit and the checks, asks
once for `accept 3`, ticks the boxes and writes into each done mark that the
criteria were accepted in one confirmation. Both verbs check every item
first and change none when one fails. Both refuse in an agent session and
inside a box (`/etc/agent-box/box.json` exists), even at a terminal. A claim
made in a box carries the box's seat from that marker, so the host and each
box hold one item in progress each.

PR bodies say `Refs #N`, never `Fixes` or `Closes`: closing is the owner's
protocol, not the forge's. Before the PR, `bin/fresh-review` sends the diff to
a fresh model context and writes a receipt; the PR carries its verdict. The
`/pr-prep` skill does these steps in order.

## Install

Requirements: Python 3.9 or newer and git. On GitHub, `gh` signed in; on
Azure DevOps, the Azure CLI signed in (`az login`, Entra token, no PAT).
Claude Code, or VS Code with GitHub Copilot.

Into a task repository, for any harness:

```bash
git clone https://github.com/kacper38/agent-change-control.git
./agent-change-control/install.sh --into <your-task-repo>
```

The installer copies what [`kit.manifest`](kit.manifest) lists, keeps files
the target edited locally unless `--force`, sets `core.hooksPath` when it is
unset, and writes `.claude/kit-version` with the source commit and the forge.
The forge comes from the target's origin: `dev.azure.com` or
`*.visualstudio.com` selects Azure DevOps, anything else GitHub;
`--forge github|ado` overrides it. A GitHub target gets the workflows and
issue forms; an Azure DevOps target gets `azure-pipelines.yml`,
`azure-pipelines-label-lint.yml` and `docs/ADO-ADMIN.md` instead.

`--boundary own|client` sets the `boundary` line of a new target's
`.claude/guard.json`: new targets get `client` (the strict mode for client
work) unless you pass `--boundary own` for a repository of your own. An
existing `.claude/guard.json` is never touched, not even with `--force`; the
installer prints a note and the summary says `boundary: left as is`. Upgrade
note: a target installed before this change copied this repository's `own`
and keeps it; its owner should check that line.

Into the home account, Claude Code only (agents and skills under `~/.claude`):

```bash
./agent-change-control/install.sh      # backs up anything it would overwrite
cd <your-task-repo> && claude
/task-intake                           # paste the task; the rest follows
```

`./install.sh --uninstall` removes exactly what the manifest lists; backups
stay in `~/.claude/backups/`.

On a work machine with VS Code + GitHub Copilot, follow
[`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md): §1 has the hand-copy
commands for where the installer may not run (agreement, skills and agents
only, no hooks), §7 covers Azure DevOps, and
[`docs/ADO-ADMIN.md`](docs/ADO-ADMIN.md) is the project administrator's
checklist.

## What is enforced where

On the laptop, before a tool call runs:

- `tools/guard/guard.py` (PreToolUse in Claude Code through
  `.claude/settings.json`, in Copilot through `.github/hooks/guard.json`):
  asks before secret files are read, anything deploys or a command installs
  packages or runs a downloaded script on the host; denies force-push and
  protected-branch commits, `gh issue …`, `gh label …`, `az boards work-item`
  writes, `az devops invoke`, any `bypassRules` and raw API writes, every
  cloud launch and a read of the stored GitHub login; gives the harness's
  GitHub tools the verdict of their shell twin; counts subagent spawns. Every rule ships with allow, ask, deny and crash fixtures
  from both harnesses.
- `.githooks/commit-msg`: `type(scope): imperative subject`, no closing keywords.
- `tools/egress/egress_screen.py --target <name> [--pass] [files]`: the last
  check before anything leaves the machine (secrets, gitleaks, client markers,
  size, the client boundary); held items are listed, never dropped, exit 3.

In the tracker, on every write: all guards first, then one comment, then one
label change (add the new status, then remove its siblings, so a crash leaves
two labels rather than none). Owner verbs refuse without a TTY. Items outside
the configured repository or area path are refused.

On the server and in CI:

- GitHub: a ruleset on `main` with the required check `ci`; the `ci.yml`
  workflow runs tests on Python 3.9 and 3.13, the commit-msg check over the PR
  range and the guards (test tampering, image tags); `label-lint.yml` reports
  label mistakes on issue events and nightly, as a comment plus one tracking
  issue, and never edits.
- Azure DevOps: `azure-pipelines.yml` runs the same gates on `main` and, through
  a build-validation branch policy, on every PR, and leases every run that is
  not a PR build so the logs of `main` outlive retention;
  `azure-pipelines-label-lint.yml` runs nightly. Branch policies, denies for
  agent identities and the optional process rules are listed in
  [`docs/ADO-ADMIN.md`](docs/ADO-ADMIN.md).

## Status and verification

- This repository dogfoods the kit: every change goes through the tracker, the
  hooks, CI and a `fresh-review` receipt, and every trade-off is a line in
  [`DECISIONS.md`](DECISIONS.md).
- GitHub path: the steps of [`docs/PLAN-2026-10-mature-setup.md`](docs/PLAN-2026-10-mature-setup.md)
  up to the evidence export are merged and in use. Waiting for the owner: the
  bot identity for agent sessions and the work pilot.
- Azure DevOps path: steps A1 to A8 of [`docs/PLAN-2026-11-ado-port.md`](docs/PLAN-2026-11-ado-port.md)
  are merged. They were verified against unit tests and a fake Azure DevOps
  REST API only; the first live run (step A0 on a scratch organisation, then
  the pilot A9) settles the response shapes, the branch ACL token and whether
  the session-start digest fits its time budget.
- Tests: `uv run --offline --no-project --with pytest python -m pytest -o addopts= -q`
  (add `--python /usr/bin/python3` for 3.9); lint: `uvx --offline ruff check .`.
  `--offline` keeps both on the local cache, which is what `AGENTS.md` asks of
  an agent; on a new machine the owner fills the cache once by running them
  without it.

## Reference

### Tracker

`tools/tracker/tracker.py`: the backend follows the origin;
`KZ_TRACKER_BACKEND=github|ado` overrides it. On GitHub it goes through `gh`; issue forms under
`.github/ISSUE_TEMPLATE/` carry the definition-of-ready fields. On Azure
DevOps, `tools/tracker/ado.py` keeps the same verbs over the REST API with an
Entra token: issues are work items of one type under one area path, labels
are tags (`tags` mode, the default) or, in `process` mode, the `System.State`
of a custom `Change` type with server-side transition rules. Environment
variables (`KZ_TRACKER_REPO`, `KZ_TRACKER_AREA`, `KZ_TRACKER_ADO_MODE`,
`KZ_TRACKER_BOTS` and the pipeline ones) are tabled in
[`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md) §7.

### Guards

- `tools/guard/guard.py` takes its knobs from the committed `.claude/guard.json`
  (`protected_branches`, `boundary`, `scratch_md_mode`, `host_install`,
  telemetry dir). `host_install` is `auto` (the default), `ask` or `off`, and
  `KZ_HOST_INSTALL` overrides it: `auto` silences the install asks where the
  hook itself runs in a container, a dev container, a Codespace, a Claude Code
  cloud session or on a GitHub Actions or Azure Pipelines agent, and every ask
  it silences is logged as `skipped`. A
  gitignored `.claude/guard.local.json` or `KZ_RULES_OFF=rule,rule` silences
  the named rules' asks, logged as `skipped`; denies stand, and only a
  committed `guard.json` at the repo root that says `boundary: own`, with no
  tighter `KZ_BOUNDARY`, enables it; a cloud session and a box ignore it. Gitignore the local file in a task repo yourself; the installer never
  edits `.gitignore`.
- Every shell rule judges a command twice: by its first pass, as before, and
  by reading every simple command the shell would run, nested scripts included
  (`bash -c '…'`, `eval`, `ssh host '…'`, a here-string). `deploy-ask` and
  `delete-guard` do so since guard 0.6.1; `git-guard`, `tracker-guard`,
  `secret-shell`, `protected-branch` and `host-install` since 0.7.0;
  `egress-guard` since 0.8.0. A
  variable, a wrapper or an option in front of the verb no longer hides it
  (`AWS_PROFILE=prod terraform apply`, `kubectl -n prod delete …`,
  `timeout 30 git commit --no-verify`), and a line the reader cannot read
  asks. Since 0.7.0 a delete, a deploy, a forced push, a tracker bypass and a
  secret file also count behind a runner (`uv run`, `mise exec`, `npm exec`,
  `nix develop -c`) and inside a container (`docker run|exec`, `compose`,
  `kubectl exec|debug`); an install inside a container stays silent, because
  that is the agreed route for installs. The guard reads text and prompts; it
  is no sandbox, and `DECISIONS.md` (2026-11-16, 2026-11-17, 2026-11-18 and
  2026-11-19) lists the forms it does not see.
- Since guard 0.11.0 (item #66) a third profile, `box`, holds inside the
  agent box, and only there: `/.dockerenv` exists, the marker
  `/etc/agent-box/box.json` is root's, neither it nor its folder is writable
  by the guard's user, the guard does not run as root, the marker says
  `schema: agent-box/1` and `boundary: own`, the effective boundary is `own`,
  and the guard is a copy the session cannot write (the read-only judge;
  this tells the judge from the work clone, whose tests answer as in CI, and
  is no security check). In a box no `ask` leaves the guard: each rule's ask
  passes a table with one entry per ask class. `log` lets the call run and
  writes a `logged` line (rule, call id, guard version) for a delete local to
  the box (files and the local repository: `rm`, `find -delete`, `git rm`,
  `git clean`, `git branch -D`, `git update-ref -d refs/heads/…`;
  never a push that deletes or forces, a container, a cluster, a database,
  a package or a cache), an edit of the guard's own paths, `scratch-md` and
  `fan-out`. `merge` lets a merge run only as one simple command
  `gh pr merge N --match-head-commit SHA` (a full lower-case hash, at most
  one of `--merge`, `--squash`, `--rebase`, nothing else) when the newest
  `fresh-review` receipt for that hash under `.git/fresh-review/` says
  `APPROVE` or `COMMENT`, and the head, against the judge's commit that the
  root-owned marker names (never a ref of the clone, which a session can move),
  changes no path `guard-config` guards and deletes no test file (a merge
  that changes the guard, its settings, CI, the tracker or the scans stays
  the owner's). Every other ask, an ask a rule gives because it
  could not read the call, and a class with no entry is a deny with the
  reason `box session: no one answers an ask here …`; a deny stays as it
  was. A box reads its configuration beside the guard
  (`<judge>/.claude/guard.json`), never from the work clone or a
  `guard.local.json`; the work clone's `boundary: client` and `KZ_BOUNDARY`
  still tighten, and `KZ_RULES_OFF`, `KZ_PROTECTED_BRANCHES`,
  `KZ_SCRATCH_MD` and `KZ_HOST_INSTALL` are ignored there with a note. A
  marker the profile does not honour gets the same configuration and the
  `host` profile, whose asks stay asks. The receipt is a file the session
  could write: it stops a forgotten review, not a hostile session.
- Since guard 0.10.0 (item #65) the boundary only tightens: `KZ_BOUNDARY=client`
  sets client, `KZ_BOUNDARY=own` leaves a committed `client` in force, and any
  other value, committed or in the variable (`Client`, `OWN`), counts as
  `client`. One function names the profile: `cloud` when
  `CLAUDE_CODE_REMOTE` is set, else `host`. In a cloud session every ask is a
  deny (nobody can answer it there), `rules_off` from every source is
  ignored, and a merge is denied; every line of `decisions.jsonl` names its
  profile. `cloud-launch` denies every way a session starts cloud work:
  `claude --cloud|--remote`, `/autofix-pr`, an `Agent` or `Task` with
  `isolation: remote`, the `schedule` skill, a `Workflow` whose script asks
  for `isolation: 'remote'`, and every `RemoteTrigger` call; `DesignSync`
  asks. `github-tools` gives the harness's GitHub tools (`mcp__github__…`) the
  verdict of the same act in a shell or a file tool: reads, a branch, a pull
  request and its text stay silent, a merge or an approval asks, issue and
  label writes are denied as `gh issue …` is, a file write is judged by the
  path rules and as a push; an op with no known twin asks. `guard-config`
  also covers `.github/workflows/`, `tools/testguard/`, `tools/scan/`,
  `tools/tracker/` and `tools/commit_msg.py`, and asks on shell writes to its
  paths (`>`, `tee`, `cp`, `sed -i`, `git checkout -- <path>`, inline
  `python -c` code that writes one). `secret-shell` denies a read of the
  owner's stored GitHub login (`gh auth token`, `git credential fill`, a
  keychain read, `~/.config/gh/hosts.yml`, a command that drops `GH_TOKEN`).
  `git-guard` denies rewriting `refs/remotes/` (`git update-ref`,
  `git replace`, `git symbolic-ref`) and asks before a remote's URL or fetch
  refspec changes; `tracker-guard` asks before `gh pr review --approve`.
  `Monitor` is judged as `Bash`, and `ExitWorktree` with `action: remove`
  asks as a delete.
- Since guard 0.9.0 the tables reach the tools, verbs and secret stores they
  did not name, and eleven kinds of false asks are gone. `deploy-ask` asks
  when a cloud CLI runs a command on a live host or container
  (`aws ssm send-command`, `az vm run-command invoke`) and for every `az` call
  whose verb is no known read. `delete-guard` asks when a package, a tool
  version or a download cache is removed (`uv remove`, `gem uninstall`,
  `uv cache clean`, `brew cleanup`). Thirty more tools that run the command
  after them are read like `timeout` (`unshare`, `noglob`, `op run --`,
  `hyperfine '…'`), and the Homebrew names of the GNU tools are the tools
  (`grm`, `gcp`, `genv`). Behind a command no table knows, `git`, `gh` and
  `az` are still judged, and the answer is an ask
  (`mytool git push --force origin feat`). `tracker-guard` denies a GraphQL
  mutation that names an issue or a label, asks for any other mutation and for
  a document it cannot read (`gh api graphql`, `curl`, `wget`, httpie); it
  asks for a merge of a pull request (`gh pr merge 3`, a `PUT` to
  `…/pulls/3/merge`) and denies `gh pr merge --admin`. `protected-branch`
  denies `git update-ref` on a protected branch. A shell that reads its
  program from a pipe the guard cannot read asks (`cat run.sh | bash`), and
  the rest of that line is still read. `secret-shell` asks for a command that
  prints a secret from a store (`vault kv get`, `op read`,
  `kubectl get secret -o yaml`, `gh auth token`). A capital letter no longer
  passes in the guard's own paths, in the GitHub API host or in a verb of
  `brew` and `gem`. Gone are the asks for a secret file's name that is only
  text, a test or a lookup (`ls -la .env`, `test -f .env`,
  `echo .env >> .gitignore`, `grep -rn .env docs`, `git status .env`,
  `tar --exclude .env`), for a preview or a help probe (`git clean -n`,
  `kubectl delete --dry-run=client`, `rm --help`), for
  `git restore --staged` and `find . -name yarn`, and inside a client
  boundary for `command -v codex` and for a search pattern that names another
  vendor's tool. Such a report stays silent only on a line the guard reads
  the way the shell does, only when the command is that report for certain,
  and only while its output goes to no other command: `ls .env | xargs cat`,
  `cat $(echo .env)` and `git -c core.pager='xargs cat' -p ls-files .env`
  keep asking. A git report is silent only beside other such reports, `cd`,
  `true` and `false`, because any other command of the line could name the
  program git hands its output to: `cd . && git status .env` is silent,
  `git add -A && git status .env` asks.
- Since guard 0.8.0 a guarded form written another way is read like the plain
  one. `secret-shell` reads a secret path glued to an option, behind `@` or as
  the source of `<` (`--env-file=.env`, `curl -d @.env`, `cat <.env`), and
  denies `git add` of a secret file behind git's own options. A script fed to
  a shell is read like the script of `bash -c`: a here-document, or `echo` or
  `printf` through one pipe, into `sh`, `bash` and their kin, `sudo -s`, `su`
  or `ssh host`; a here-document that is data (`cat <<EOF > notes.txt`,
  `git commit -m "$(cat <<'EOF' … EOF)"`) is not. `tracker-guard` reads `gh`
  with `-R` in front of the verb and the glued spellings of `gh api`.
  `git-guard` reads short options in one word and long options cut short
  (`git push -uf`, `--no-verif`), and denies the hook gate switched off
  through the environment (`HUSKY=0`, `LEFTHOOK=0`, `SKIP=…`) or through
  `core.hooksPath` set for one call; `git config` that writes that key asks
  unless the value is `.githooks`. Capitals count like the plain form, because
  a file system that ignores case runs `git` for `GIT` and opens `.env` for
  `.ENV`: a tool's name is judged as written and folded to the spelling the
  tables use, and the stricter answer stands; a secret file name and an LLM
  API host are classed whatever their case. On a case-sensitive file system
  `.ENV` is another file and asks all the same.
- Since guard 0.7.0 the pre hook answers within 3.5 s: the rules run in a
  child process, and a call they have not judged by then asks under the name
  `budget`, where it used to run unjudged once the harness cut the hook at
  5 s. Where the platform has no `fork` (Windows) there is no budget.
- A line of `decisions.jsonl` names the guard version and, in Claude Code, the
  tool call. `guard.py hook post`, wired under PostToolUse and
  PostToolUseFailure in `.claude/settings.json`, adds a `ran` line when a call
  that was asked about went ahead. No hook fires when a prompt is declined, so
  an ask without a `ran` line was declined, is still open, or was interrupted;
  or its call ran after the ask had left the last 128 kB of the log, which is
  all the post hook reads. A missing `ran` line alone is no proof of a decline.
  A repository that had its settings file before 0.7.0 keeps it on install:
  add the two `hook post` entries by hand
  ([`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md) §2). Copilot sends no call
  id, so its asks get no `ran` line.
- `tools/testguard/check-test-tampering.sh` (the harness kit's guard plus
  pytest rules): deleted or renamed test files, a `def test_` that disappears,
  added skip/focus markers, `[skip ci]` in commits or the PR title. The
  PostToolUse wrapper `testguard.py hook` runs it against the working tree
  whenever a tool touches a test file; the CI job `guards` runs it against the
  PR base. A removal passes only with the human-applied `test-removal-ok` PR label.
- `tools/scan/latest_tag.py`: `:latest` or untagged image references in
  Dockerfiles, compose files, workflows and `azure-pipelines*.yml` (digests,
  build stages and `scratch` pass). `hook` judges the file just written;
  `scan [PATH...]` walks the tracked tree in CI, exit 1 on findings.

### Review

- `bin/fresh-review` sends `origin/main...HEAD` (through the egress screen) to a
  fresh Opus context with `tools/review/prompt.md` and writes a receipt to
  `.git/fresh-review/<sha>.json`; `/pr-prep` pastes the verdict. At work the
  same prompt is `.github/instructions/review.instructions.md` for Copilot code
  review, on GitHub and on Azure Repos.

### Orchestration

The checks of the skill `orchestrate` (standard library; exit 0 pass, 1 fail
or gap, 2 usage):

- `tools/orchestration/assert_run.py run FILE`: a headless `claude -p
  --output-format json` run's output: success, no permission denial,
  structured output, no `null` stage, no outstanding background work.
- `tools/orchestration/assert_run.py worker FILE [--repo DIR]`: a
  `worker-result/1` object: its head is the branch tip and every check it
  reports exited 0 (the worker's own word; nothing is re-run).
- `tools/orchestration/assert_run.py merge-ready N [--repo DIR]`: pull request
  N is open, its head is the tip at origin and locally, its checks are green,
  the newest fresh-review receipt for the head says APPROVE or COMMENT (open
  findings of a COMMENT are not checked: answer each before the merge) and it
  adds a `DECISIONS.md` line;
  prints `gh pr merge N --merge --match-head-commit <sha>`, never merges.
- `tools/orchestration/brief_lint.py FILE...`: a brief has every field of
  `brief-template.md` once, none empty, a command as done evidence and a
  number as size limit.

### Box (this repository only; Phase 1 step 1.0a, a skeleton)

- `bin/box run NAME` opens a terminal session in box NAME; `bin/box run NAME
  --brief FILE` runs one headless session on FILE and prints the path of its
  `result.json`; `bin/box doctor` starts a box without tokens and shows each
  check (uid not 0, every version at its pin, `https://example.com`
  unreachable, no Docker socket, no host home, the marker root's) and then
  `ruff check tools` and both `pytest` runs inside it; `bin/box build` builds
  `agent-box:<git SHA>` from `tools/box/pins.env`.
- Inside: the CLI with `--dangerously-skip-permissions` as uid 1000, no
  capabilities, TCP 443 to the model API and GitHub only, port 53 to the
  container's resolver only, the
  model pinned to Opus. The hooks that run are those of `main` as fetched at
  the start, exported read-only to `~/.agent-box/judge/<SHA>/` and loaded as
  managed settings with `allowManagedHooksOnly`, so the work clone cannot
  change them. The judge's guard runs its `box` profile (guard 0.11.0): it
  denies as before, logs what its table lets run, and never asks; the
  wrapper no longer sets `KZ_RULES_OFF` (plan section 5, row 1 ended with
  step 1.0b).
- No session starts until the probe's record shows that a hook's `deny`
  holds with permission checks off for the pinned CLI (`run` reads
  `verified.json`).
- Before the first start the owner stores two tokens (plan section 7):
  `agent-box-claude` (from `claude setup-token`) and `agent-box-github` (a
  fine-grained token for this repository: Contents, Pull requests and Issues
  read and write, 30 days), each with `security add-generic-password -U -a
  "$USER" -s <name> -w`. `setup-token` prints its token wrapped over two
  lines and the prompt stops at the first line break, so after copying it
  run `pbpaste | tr -d ' \n' | pbcopy` to join it, check that
  `pbpaste | wc -c` says 108 (on 2.1.323), then paste. A missing, expired or revoked token stops the start
  with its name; nothing falls back to the owner's own login.
- It is not: an image in a registry, a scanned image, a box for a client or
  secret repository (the wrapper refuses one whose committed `guard.json`
  does not say `boundary: own`), or a place where the tokens are hidden from
  the session. What the probe found is the `box` key of
  `tools/orchestration/verified.json` (`python3 tools/box/box_probe.py`).

### Evidence pack

- `tools/tracker/evidence_export.py capture --tag T --name N -- <command>` keeps
  a check's output verbatim under `evidence/T/` with its sha256, size, exit code
  and tool version.
- `evidence_export.py export --tag T --from <ref> --to <ref>` writes
  `change-records.json` (schema `agent-change-control/change-records/2` on both
  forges): PRs merged in the git range with merge SHAs, reviews or votes, check
  runs or builds and policy evaluations, completion options; the issues or work
  items they reference or that closed in the window, with tracker markers,
  acceptance boxes and revisions; rulesets or branch policies; retention
  leases; the captures re-hashed; tool versions. A section a forge lacks is
  null, and the branch ACL is null on both forges for now (deferred until the
  first live Azure DevOps run). `/validation-evidence` runs both.

### Agents

Process and compliance core:

| Agent | Role |
|---|---|
| `platform-planner` | Plan before code: assumptions, questions, steps with a verification command each, trade-offs, cut line |
| `infra-reviewer` | Dockerfile / GitHub Actions / Azure Pipelines / Terraform / compose review: correctness and best practices |
| `gxp-compliance-reviewer` | Same artifacts through a GAMP 5 auditor's lens: audit trail, ALCOA+, validation evidence |
| `rag-infra-advisor` | AI-infra decisions: vector store, private LLM endpoints, model+prompt+index versioning, eval in CI, cost, data residency |

Execution bench:

| Agent | Role |
|---|---|
| `python-engineer` | Production Python: FastAPI, CLIs, automation; uv + ruff + mypy + pytest |
| `node-engineer` | Production TypeScript: Next.js frontends, zod at boundaries; npm ci + tsc + vitest |
| `shell-engineer` | Bash that survives production: `set -euo pipefail`, quoting, shellcheck, traps, and knows when to switch to Python |
| `k8s-engineer` | Manifests (probes, limits, securityContext), Kustomize/Helm, pod-debugging runbook, EKS/AKS, GitOps |
| `git-surgeon` | Conflicts, reflog recovery, bisect, history surgery behind a backup branch; signed commits as audit trail |
| `observability-engineer` | Prometheus/Grafana as code, symptom-based alerting, SLOs, correlation ids, LLM cost metrics |
| `postgres-engineer` | Non-blocking migrations, EXPLAIN/indexing, restore-tested backups, RLS, pgvector tuning |
| `code-reviewer` | General code review: correctness, security, maintainability |

Reviewer and planner agents have no Edit or Write tools; a test asserts it.

### Skills

Task lifecycle:

| Skill | When |
|---|---|
| `/task-intake` | New task/ticket: assumptions, questions, scaffolding (README, DECISIONS.md, AGENTS.md), approved plan |
| `/platform-flow` | The chain: local dev, Docker, CI, Terraform, CD, observability, security |
| `/rag-stack` | RAG component: pgvector, traceability-first schema, idempotent ingestion, private endpoints, eval + cost hooks |
| `/data-pipeline` | Data feed/ETL: source contract + quarantine, idempotent load, lineage row per run, quality gates, scheduled job |
| `/gxp-check` | Before significant commits: secrets/tags/IAM/vuln-scan/pipeline-lineage sweep mapped to GxP vocabulary |
| `/validation-evidence` | Before release/handoff: evidence pack with requirement to implementation to test matrix, captured outputs, change trail |
| `/post-mortem` | After an incident: blameless write-up with owners and a validation note |

General support: `verify`, `code-review`, `pr-prep`, `systematic-debugging`,
`verification-before-completion`.

Work for more than one agent: `/orchestrate` splits a task into packets, one
linted brief each (`brief-template.md`), runs the first packet end to end and
checks every result with `assert_run.py` before a merge.

Anti-over-engineering (the lazy family):

| Skill | When |
|---|---|
| `/ponytail` | Lazy mode for the whole session: the YAGNI, stdlib, native, installed-dep, one-line ladder (`lite\|full\|ultra`) |
| `/ponytail-review` | Review the current diff for things to DELETE: reinvented stdlib, unneeded deps, speculative abstractions |
| `/ponytail-audit` | Same lens over the whole repo, ranked by removable lines/deps |
| `/ponytail-debt` | Harvest `ponytail:` markers into a debt ledger with upgrade triggers |

### Memory and ledger (Claude Code, home machine only)

- `tools/memory/memstore.py init` puts `~/.claude/projects/*/memory/**` under a
  bare repo; the PostToolUse hook commits every memory write and validates the
  frontmatter. `index --write` rebuilds `MEMORY.md`, `triage` lists stale or
  unverified files, `deprecate` retires one.
- `tools/telemetry/ledger.py hook` (SessionEnd) writes one line per session with
  per-model tokens and cost; `ledger.py cost --days 7` prints the week per
  project and model, the total of the session costs with the number of lines
  it left out, and hook prompts per guard rule (with guard 0.7.0 also
  `ran X of Y`: of the Y asks that carry a call id, X went ahead).
  `ledger.py recount` (a dry
  run; `--write` applies it) is a one-off for lines written before the cost
  basis existed: it rebuilds each from its transcript and keeps the old
  figures in the line, or labels it when the transcript is gone.
- `tools/telemetry/ledger.py agents` prints one session as a tree in the
  terminal: the session on the first line, under it every agent it started
  (the agents of a workflow under the workflow, an agent under the agent that
  started it), with state, duration, cost, tool calls and model per line, and
  a total. `--session <id or prefix>` names a session, also one that has
  ended; without it the view takes the session of the current project folder
  whose transcript was written last. `--watch` draws the tree again every two
  seconds until Ctrl-C. What it is not: it reads Claude Code's local files
  only (no Copilot), writes nothing, and prints no prompt, tool input or tool
  output. The state is inferred from the end of each transcript, so a session
  or agent that was cut off still reads as running, and the duration runs
  from the first to the last line of a transcript, not until now. The cost is
  the ledger's own count at list prices: the lines add up to `cost_usd_own`,
  not to Claude Code's own figure, and a model without a price row gives
  `n/a` for its line and for the total. The type and the short description
  of each agent are text from the session: the tree of a client session
  stays where that session's data may be.
- `tools/telemetry/page.py` writes the task page: one static HTML file of the
  tasks of the current folder's repository over the last seven days
  (`--days N`, `--session <id or prefix>`), grouped by branch. Per task: its
  sessions with their scope (title, branch, folder, model, host or box), the
  agents, every tool call with the guard's verdict, every ask and deny, the
  fresh-review receipts tied to the branch and how each review compares with
  the one before it, the `evidence/` paths the branch changed, and the cost.
  It prints the path of the file, `~/.claude/telemetry/pages/<UTC>.html`
  (mode 0600; `--out PATH` puts it elsewhere, never inside a git work tree and
  never over an existing file). The page has no script and loads nothing
  (CSP `default-src 'none'`), and shows no tool input or output: an agent
  appears by its type, without the description its Agent call was given, and
  a workflow without its script's name. What it is not: a live console (it is
  read after the fact; live state is a terminal multiplexer's), or evidence
  (the files it reads are). A session is grouped under the branch most of its
  lines carry, so a session that works in a worktree by absolute paths from the
  main checkout sits under the main checkout's branch. The page holds titles,
  folders, branch names and finding summaries, so it stays on this machine:
  never attach it to a ticket, a pull request, a chat or an evidence pack. A
  page is kept 30 days: a run names the older pages in the default folder on
  stderr, and you remove them (it deletes nothing).
- Nothing from here is installed at work: no memory, telemetry, tokens or
  transcripts cross the boundary, and memory push stays off until
  `KZ_MEMORY_PUSH` names a project.

### Working agreement

[`AGENTS.md`](AGENTS.md) is canonical: the eight non-negotiables, the four
Karpathy coding principles (adapted from
[andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills)),
the model-routing table and which harness reads what. `CLAUDE.md` is the one
line `@AGENTS.md`, so every harness loads the same file; `/task-intake`
copies both into the task repo.

### Documents

| File | What it is |
|---|---|
| [`AGENTS.md`](AGENTS.md) | the working agreement, canonical |
| [`DECISIONS.md`](DECISIONS.md) | every trade-off, one line each, newest block last |
| [`docs/SYSTEM.md`](docs/SYSTEM.md) | one-page system description, kept current |
| [`docs/USING-AT-WORK.md`](docs/USING-AT-WORK.md) | VS Code + Copilot at work; §7 Azure DevOps |
| [`docs/ADO-ADMIN.md`](docs/ADO-ADMIN.md) | Azure DevOps administrator checklist with the proving API calls |
| [`docs/PLAN-2026-10-mature-setup.md`](docs/PLAN-2026-10-mature-setup.md) | the plan behind the GitHub path |
| [`docs/PLAN-2026-11-ado-port.md`](docs/PLAN-2026-11-ado-port.md) | the plan behind the Azure DevOps port |
| [`kit.manifest`](kit.manifest) | what the installer copies, per forge |
| [`setup-overview.html`](setup-overview.html), [`tech-primer.html`](tech-primer.html) | non-normative overview (Polish) and study guide; the `.md` files are the authority |

## License

MIT
