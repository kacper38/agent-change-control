# Plan — Phase 1: a box to build in, then local orchestration (plan rev 3, steps 1.1 to 1.8, 2.3 and 0.3)

Status: PROPOSED on 2026-11-18. It waits for the owner's one approval (`DECISIONS.md`, block "the owner's standing word": one plan per phase). Nothing in it is built before that.

Parent: `docs/PLAN-2026-11-orchestration-ci.md` (rev 3). "Row" below means that plan's row, unchanged (lines 227 to 245); only additions are written out. Line numbers in this file refer to `main` at `0a1cf2b`.

Method: drafted by the `platform-planner` agent from a brief, then edited by the session that puts it up. The edit changed three things after the owner's words of 19:53 UTC (section 5): owner verbs once per phase, boxes started by a host session, and a review receipt in front of a merge in a box.

## 0. One screen for the owner

**What you get.** A container ("the box") in which a session builds with permission checks off, so it does not prompt you. Inside it the guard still runs and still denies; it only stops asking. Then the rest of Phase 1: guard hardening, the workflow rule, the review panel, the rules table, the installer default.

**What you do, in two sittings.**

1. Now: read this screen, strike what you do not want (tell the session), store two tokens (section 7), and paste one line that runs `owner ready` for the nine items. That line is the approval.
2. At the end of the phase: one `owner done` line for all items of the phase, #57 and #59 included, and one look at VS Code.

In between nothing is expected from you. The two points where a prompt can still reach you are named in section 3.

**What you give up until delivery.** Your eye on local deletes, guard edits and merges inside a box; a tick per acceptance criterion; a decision per step. Each is a row in section 5 with its way back.

**Cost.** $0 a month on top of the subscription. As API-equivalent spend, a guess: $400 to $800 for the phase.

## 1. Assumptions, and what was not checked

- Guard 0.9.0 (#57, in progress in another session) is merged before any step starts. As built on its branch it asks on `gh pr merge` and denies `--admin`; `main` at 0.8.0 does not ask.
- The guard never answers `allow` (`tools/guard/guard.py:6-7`): with permission checks off, a silent guard means the call runs. So inside a box the guard is the only gate, and it matches command text.
- A tracker item binds one branch and one pull request (`tools/tracker/tracker.py:666-668`, `:734-735`); nothing leads from `review` back to `in-progress` (`:64-74`). The limit of one item in progress is per GitHub login (`:624-630`). Closing is a human's verb (`:71`, `:536-538`, `:690-692`).
- CI runs `ruff check tools` and `pytest` on Python 3.9 and 3.13 (`.github/workflows/ci.yml:18-26`). The verified CLI is 2.1.323 (`tools/orchestration/verified.json:3`); it has `setup-token` and `--dangerously-skip-permissions` (read from `claude --help` on 2026-11-18).
- **Not checked:** every fact about Claude Code inside a container. Each is marked "to probe" and is the first commit of step 1.0a. If a probe fails, the fallback is named in section 8.

## 2. Steps

| id | What is built | Files | Verification | Size | PR | After |
|---|---|---|---|---|---|---|
| 1.0a | **The box.** First commit, a probe, results in `verified.json`: the permission flag as a non-root user; whether a hook's `deny` and `ask` still hold with checks off; a headless run with the token variable; hooks from managed settings; the hosts the CLI needs; the vendor's firewall script under the container runtime on his Mac (OrbStack); account connectors; `CLAUDE_CONFIG_DIR`. Then the image: multi-stage, non-root, bases by digest, health check, tag = git SHA; both Pythons, git, gh, Node, ruff, pytest and the CLI, all pinned. Then `bin/box`: a dedicated clone, a box-only Claude home on a host folder, no mount of the home folder, no Docker socket. A root entrypoint sets the egress list (model API, GitHub), writes the root-owned marker `/etc/agent-box/box.json` and drops to the user. Hooks run a read-only copy of `main` as of the box's start (the judge). Tokens come from the Keychain and are never printed or put on a command line. Only a clone whose committed policy says `boundary: own` starts. Two ways to run: `bin/box run <name>` gives a terminal; `bin/box run <name> --brief FILE` runs one headless session and writes its result file. | `tools/box/` (Dockerfile, entrypoint, firewall, pins, managed settings, `box.py`, tests), `bin/box`, `tools/orchestration/probe.py`, `verified.json`, `README.md`, `docs/SYSTEM.md`, `DECISIONS.md` | `bin/box doctor`: uid is not 0, versions match the pins, `curl https://example.com` fails, no socket, no host home. Inside the box both `pytest` runs and `ruff check tools` give CI's result. | L | A | #57 merged, tokens |
| 1.9 | **Tracker, new step.** `owner ready` and `owner done` take several numbers; each checks every item first and changes nothing when one fails. `owner done … --accept-all` prints per item the criteria and the closing facts, takes one confirmation, ticks the boxes and writes into each done mark that the criteria were accepted in one confirmation. The in-progress limit counts per login and seat; the seat is read only from the box marker. Owner verbs refuse inside a box. | `tools/tracker/tracker.py`, `tools/tracker/tests/`, `README.md`, `DECISIONS.md` | `pytest tools/tracker`: an agent is refused both verbs and the flag; the frozen hash holds through the ticks (`tracker.py:206-208`); one failing item leaves all untouched; a second claim on one seat is refused, on another seat accepted; an environment variable gives no seat. | M | B | 1.0a |
| 1.7 | Row, plus the harness's own GitHub tools (`DECISIONS.md`, block of 2026-11-18 "step 1.7 is pulled forward"). First commit, a probe: is the hook called for an `mcp__github__*` tool once the matcher names it. One function names the profile; where `rules_off` is applied (`guard.py:3447-3448`) each `ask` passes through the profile's table, and `cloud` turns every ask into a deny. `guard-config` also covers `tools/testguard/`, `tools/scan/`, `tools/commit_msg.py` and `tools/tracker/`. A canary fails when the session's tool list changes. Guard 0.10.0. | `tools/guard/guard.py`, `tools/guard/tests/`, `.claude/settings.json`, `tools/orchestration/probe.py`, `README.md`, `docs/SYSTEM.md`, `docs/USING-AT-WORK.md`, `DECISIONS.md` | `pytest tools/guard` with the rows of section 4, on both Python versions. | L | C | 1.0a |
| 1.0b | **Profile `box`.** Honoured only when the marker is owned by root, not writable by the guard's user, and `/.dockerenv` exists. Its table: log and let run local deletes, edits of the guard's own paths, `scratch-md` and `fan-out`. A merge runs when it has the form `gh pr merge N --match-head-commit SHA`, has no `--admin`, and a `fresh-review` receipt for that SHA exists with a verdict other than BLOCKER; otherwise it is denied. Every other ask is a deny, so no `ask` leaves the guard in a box. In a box the guard reads its configuration beside itself (the judge). If the probe shows an `ask` passing unanswered with checks off, that mode without a marker turns every ask into a deny. Guard 0.11.0. | as 1.7, `tools/box/box.py` | Rows of section 4. In a box `rm -rf build` runs and leaves a `logged` line; `git push origin --delete x` and `cat .env` are denied; a merge of a head with no receipt is denied. | M | D | 1.7 |
| 1.1, 1.2 | Rows. Guard 0.12.0. | as 1.7, `.claude/guard.json`, `verified.json` | The rows' canaries, plus one for a blocked call when the guard times out; `pytest tools/guard`; a sixth spawn through a workflow shows in `spawns.jsonl`. | S, M | E | 1.0b |
| 2.3, 1.3, 1.8 | Rows. 2.3 also gets a mode `merge-ready`, which a session runs before a merge: the head equals the branch tip, the checks are green, a review receipt exists for that head, the pull request adds a `DECISIONS.md` line. It prints the merge command in the form the box profile accepts. | `tools/orchestration/` (`assert_run.py`, `brief_lint.py`, tests), `skills/orchestrate/`, `AGENTS.md`, `install.sh`, `tools/tests/test_install.py`, `kit.manifest`, `README.md` | `pytest tools/orchestration tools/tests`: the rows' fixtures; a head with no receipt fails; a fresh target says `client`, with `--boundary own` it says `own` (today `install.sh:90` copies `own`); CI's idempotence step passes (`ci.yml:27-34`). | M, S, S | F | 1.9 |
| 1.4, 1.5 | Rows; Opus per stage, a logged cap of $15 per run. | `.claude/workflows/review-panel.js`, `tools/orchestration/tests/`, `.claude/guard.json` | The offline cases under Node (no Node is a failure, not a skip); a script without a pin fails; one live run with its cost in the ledger. | M, S | G | 1.2, 2.3 |
| 1.6 | Row, plus one dated row per relaxation of section 5. | `docs/RULES.md`, `tools/tests/test_rules_table.py` | `pytest tools/tests`: fails on a missing enforcer and on a relaxation past its end. | M | H | 1.2, 1.9 |
| 0.3 | Row, run from a host session, because the box token reaches this repository only. | `DECISIONS.md`, `verified.json` | One `DECISIONS.md` line per answer, with the run URL. | M | I | the owner's scratch repository |

New paths at the end: `tools/box/`, `bin/box`, `tools/orchestration/assert_run.py`, `tools/orchestration/brief_lint.py`, `skills/orchestrate/`, `.claude/workflows/review-panel.js`, `docs/RULES.md`, `tools/tests/test_rules_table.py`.

## 3. Pull requests, items and order

Nine pull requests, one tracker item each: A (1.0a), B (1.9), C (1.7), D (1.0b), E (1.1, 1.2), F (2.3, 1.3, 1.8), G (1.4, 1.5), H (1.6), I (0.3, the existing item #39). The items are filed in `status/backlog` when this plan is put up, so that the owner's one line can promote them.

- **Order.** A on the host. Then B in the first box. Then C → D → E → G → H in that box, serial, because each changes `guard.py`, the settings or what they name. F beside them in a second box. I from a host session. At most two boxes and one host agent at once, so three agents.
- **Who builds.** The host session writes each brief (Fable) and starts a box with it. The box session builds on Opus, runs the checks, runs `bin/fresh-review`, fixes or rebuts each finding, adds the `DECISIONS.md` line that names it as the merger, and merges. The host session then reads the result file and the checks on the merge commit.
- **Until B is merged** the limit of one item in progress per login holds, so A starts when #57 is in review and #59 is not in progress.
- **Where a prompt can still reach the owner:** the merges of A and I, which run on the host under guard 0.9.0's ask; and workflow files in the scratch clone for 0.3. Nothing else is expected.
- **What still waits for him by the standing word:** none of the nine touches `.github/workflows/` of this repository; one that must remove a test waits for him.

## 4. Guard steps: rows first

For each guard step the acceptance rows and a held-out set are written and committed before the code.

- **1.7.** Kinds of rows: `KZ_BOUNDARY` tightening, refused loosening, an unknown value (it counts as `client`); every way to start cloud work, as shell form and as tool call, with silent neighbours; under the cloud variable one row per rule that can ask, per `rules_off` source, and the merge; shell writes to guarded paths against reads; credential reads against status calls; ref rewrites against a plain fetch; each GitHub tool by what it does; crashes. Never weaker: every row and fixture of 0.9.0 keeps its verdict or gets a stricter one; a test lists each change and fails on a move toward silence; the 45-day replay is repeated.
- **1.0b.** Kinds of rows: the marker (valid, missing, owned by the user, writable, guard running as root, boundary `client`); one row per ask class of every rule, log or deny; local against remote deletes; each `rules_off` source ignored; a configuration edit in the work clone; the merge (accepted form with a receipt, no receipt, BLOCKER receipt, a short hash, `--admin`). Never weaker: without a marker the whole corpus answers as 0.10.0; with it no deny changes and no `ask` remains; an ask class with no table entry fails a test and defaults to deny.
- **1.2.** Kinds of rows: a listed name, an unknown name, an inline script, a crash; the same under `cloud` and `box`; the spawn count through a workflow. Never weaker: every event that is no `Workflow` call answers as 0.11.0.

## 5. Rules relaxed during the build

The owner's words that this section answers, all of 2026-11-18: "maybe better idea would be to let you run in container, when I dont care that much" (19:14 UTC), "i mean to loosen rules now, deliver that repo and then use them ..." (19:23), "abd for example next time I do owner done xx it has to be after whole phase" (19:53:49, to this session), "mark it as done for me" (19:53:30, to the session that builds #59).

1. **No prompts in a box.** Until 1.0b the wrapper sets `KZ_RULES_OFF` for `delete-guard`, `guard-config`, `scratch-md`, `fan-out` and `tracker-guard` (`guard.py:205-211`; denies stand); after it the box profile applies. Saves: nearly every prompt of a build. Gives up: his eye on local deletes, guard edits and merges inside a box. Way back: nothing to switch, because the profile exists only behind the marker; he revokes the tokens and no box starts.
2. **A host session starts a box.** `bin/box run <name> --brief FILE` may be run by a session; he can also start one himself and talk to it. Saves: about six box starts and six pasted briefs. Gives up: his hand on each start. What a session gains by it: nothing it cannot already reach on the host with his login; the box's GitHub token is narrower than that login. Way back: the wrapper asks for a terminal (one line).
3. **Owner verbs once per phase.** One `owner ready` line when he approves a phase's plan; one `owner done` line when the phase is merged. Items already open (#57, #59) are not handed to him one by one: they stay in `status/review` after their merges and are in the same line at the end. An item in review does not block another claim. Saves: about twenty runs of an owner verb and every "your turn" message. Gives up: acceptance close to each merge; a defect he would have seen at item 2 is seen at the end. Way back: he runs the verbs per item whenever he likes; nothing prevents it.
4. **`owner done --accept-all`.** Saves: the ticks in the browser, which did not arrive on 2026-11-18. Gives up: a tick per criterion as a separate act. Who acted stays on record: the verb is his alone and the done mark names him and how the criteria were accepted. Proposed as permanent.
5. **One tracker item per pull request, not per step.** No mechanism needed. Saves: four items (thirteen steps, nine pull requests). Gives up: a scope freeze per step. Way back: items per step.
6. **A seat per box.** Without it a box shares his one slot, since its token carries his login. With seats: one item in progress per login and seat, three at most here. Way back: no box, no seat.

**Not relaxed.** A session runs no owner verb: closing an item stays his act (decision 1 below). Five agents at once without asking. No installs on his machine. Deletes, deploys and force pushes on the host. A pull request that touches `.github/workflows/` or removes a test waits for him. Client and secret repositories get none of this: a box starts only for `boundary: own`.

Each relaxation is a dated row in `docs/RULES.md` (step 1.6); its test fails once the end date has passed.

## 6. Decisions taken in this plan

Each line is the owner's to strike.

1. **"mark it as done for me".** A session does not close an item. His one line per phase closes them all. Why: the acceptance by a named person is the one human act left in an item's life, and it is what the kit shows a client's QA. The alternative, if he strikes this line: in a `boundary: own` repository a session moves `review → done` and the done mark says so; that is a tracker change of size S in step 1.9.
2. Q13: a new target gets `boundary: client` unless `--boundary own` is given; existing targets are untouched. It fails closed.
3. Row 1.7: the test guard, the tag scan, `tools/commit_msg.py` and the tracker join `guard-config`; each enforces something a merged change could weaken.
4. Row 1.7's go-ahead is given with this plan; row 1.1's VS Code check is his, once, at the end.
5. Faking the box: signals that only tighten are believed from anywhere; the marker, which loosens, must be owned by root. A host session cannot create it there, a box session cannot remove it.
6. The judge: box hooks run a read-only `main` as of the box's start, so a half-written guard cannot stall the session and the session cannot edit its judge. Fallback: the work clone's hooks, a named residual.
7. The merge in a box needs a review receipt for the exact head. The receipt is a file the session could write itself; it stops a forgotten review, not a hostile session.
8. Egress: the vendor's firewall script inside the container; a proxy beside it only if the probe fails.
9. Signing: box commits are unsigned and keep the trailer, because a "Verified" mark under his name would say he signed them. If the ruleset demands signatures (read in the step): a box-only signing key.
10. Ledger: a box-only Claude home on a host folder, never his own; read with `CLAUDE_CONFIG_DIR` (`tools/telemetry/ledger.py:561`) and reported apart. Transcripts there are kept 90 days, set explicitly.
11. Worktrees: host sessions keep theirs; a box mounts its own clone, never the main checkout.
12. Image builds by a session count as downloads in a container (`AGENTS.md`, security reflexes); images stay local and are tagged with the git SHA.
13. Models: Opus builds and reviews inside a box, Fable writes the briefs on the host. `bin/box` pins the model; a brief cannot change it.

## 7. The owner's acts

**At approval, one sitting (about ten minutes):**

1. Strike lines of section 6 if he wishes, by telling the session.
2. Claude token: `claude setup-token`, then `security add-generic-password -U -a "$USER" -s agent-box-claude -w`, which asks for the value.
3. GitHub token: Settings → Developer settings → Fine-grained tokens; this repository only; Contents, Pull requests and Issues read and write; no Workflows, no Administration; 30 days. Stored the same way under the name `agent-box-github`.
4. One line that runs `owner ready` for the nine items; the session prints it with the numbers. This line is the approval of the plan.

**During the phase:** nothing planned. For 0.3, when the session asks once: a private scratch repository and `gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <scratch>` with a second token.

**At the end of the phase, one sitting:**

5. `python3 tools/tracker/tracker.py owner done <numbers> --accept-all`, one line, printed by the session, #57 and #59 included.
6. Confirm in VS Code that the hooks load.

**At delivery (section 11):** revoke both tokens, delete the Keychain entries and the scratch repository.

Nothing else: no ruleset change, no App, no workflow push in this phase.

## 8. Error paths and edge cases

- A hook's `deny` does not block with checks off (probe): the box does not run that way. This one case comes back to the owner, with the choice between a box that keeps the permission mode `auto` and no box.
- A headless run does not work with the token (probe): boxes are started by him in a terminal, and row 2 of section 5 falls away.
- The firewall cannot be set: the entrypoint exits before a session starts.
- A token is missing or expired: the wrapper stops and names the Keychain entry; it never falls back to his `gh` login.
- The guard crashes under `onFailure: "block"`: in a box the judge is read-only, so the work in progress cannot cause it; on the host he runs `git restore`.
- A push touches `.github/workflows/`: GitHub rejects it for the box token (checked in the probe); the session reports.
- A box session ends without a result file: the host session treats it as a gap (step 2.3's rule), reads the clone's state and starts a new box from the same brief; it does not guess.
- A review finding holds and cannot be fixed inside the item's scope: no merge; the item is blocked with the question (`tracker block`), and the next item that does not depend on it goes on.
- A merged change must be reverted, or a defect is traced to a change the review passed: the standing word's own tripwire applies, and the session asks per merge again.

## 9. Skeleton or production-grade, and what is deferred

- **Production-grade:** the guard changes with their rows, the tracker change, the installer default, `assert_run.py`, the rules table.
- **Skeleton:** the box. A local image with no registry, no CI build and no scan; addresses resolved at start and DNS open; both tokens readable by the session inside, limited by scope, expiry and the egress list. So it is for `boundary: own` only. The cloud branch and the GitHub-tools rule rest on fixtures.
- **Deferred, each with its trigger:** image build and scan in CI (a second user); a proxy with a domain list (addresses drift twice); a box on Bedrock or Foundry through OIDC (the first client repository); the box in `kit.manifest` (a second repository uses it).

## 10. Effort and cost

Days of session work: A 1, B 0.5, C 1, D 0.5, E 0.75, F 1, G 0.75, H 0.5, I 0.5; about 6.5 in all, about 4 elapsed with two boxes. Money: $0 a month on top of the subscription; a container runtime is already on his Mac (`/usr/local/bin/docker`, OrbStack), so nothing is installed. As API-equivalent spend, a guess until the ledger measures each pull request, sized from the parent plan's fact 21 (about $1,500 to $1,800 in 30 days at list price, all projects): $40 to $90 per pull request, $400 to $800 in all. One fresh review has cost $0.19 to $1.37 in seven measured runs (four in the parent plan's section 11, three on 2026-11-18).

## 11. Delivered means

Delivered = this plan's nine pull requests, plus steps 2.1, 2.2, 2.5 and 2.6 of the parent plan, merged on `main`, and one install into a fresh target that passes its checks. Phase 2 gets its own plan and its own single approval; it holds the owner's account acts (the App, the ruleset). With 2.1 and 2.2 in force the standing word ends by its own text and the relaxation rows leave `docs/RULES.md`. Step 2.4, Phase 3 and Phase 4 follow under the strict rules. The box gives the uninterrupted sessions that cloud workers were meant for, so steps 4.1 and 4.3 lose most of their reason; that is a question for the Phase 4 plan.

## 12. What an auditor gains, and does not

- **Gains.** Every act the box profile lets run without a prompt leaves a line in the guard's log with rule, call and guard version. Each merge has a receipt of a review by a fresh context for the exact head, the checks on the merge commit, and a `DECISIONS.md` line that names the session as the merger. Box commits are unsigned and carry the model's trailer, so nothing under the owner's signature was made by a session. The box's transcripts are kept apart from his own. Each relaxation is a dated row with an end, and a test fails when the date passes.
- **Does not gain.** The forge shows the owner's login for every act of a box, as it does for a host session, until step 2.1. Author, reviewer and merger are one model family. Acceptance in one confirmation per phase says less than a tick per criterion. Inside a box the guard is the only gate and it matches command text.

## 13. `DECISIONS.md`

Two blocks come with this pull request. "2026-11-18 — Phase 1 plan put up" holds the owner's words of 19:53 UTC, the decision on #57 and #59, and the list of what this plan asks him to relax. "2026-11-18 — the owner switched the `fleet` verifier off" records a local setting of his that this plan relies on for host sessions. His approval is added to the first block when he gives it, with the time and the form (the `ready` marks on the nine items, or his words). Each of the nine pull requests adds its own line.
