# Plan — Phase 3: the guard in Rust, built from source on every machine that runs it; the other tools after it

Status: PROPOSED on 2026-11-27 by session agent-change-control-0a. Nothing in it is built, and no Rust file exists. Tracker item #114.

Written early, on the owner's choice. Item #114 says the plan is "written against main after the Phase 2 items are merged" and "not started before Phase 2 is merged". On 2026-11-27 none of the Phase 2 items #106 to #112 had started. The session asked whether to wait, and the owner chose the option "Write the #114 plan now". So every fact below is read at `main` `f64c875` (guard 0.12.2) on 2026-11-27, before Phase 2 changes the guard, the box and the merge rules. Gate G0 (section 3) reads them again before the first step.

The decision itself is not reopened here. The owner, in a session on 2026-11-26: "i want it in rust I think", then three answers in one dialog: the guard first, Phase 2 first, built from source on each machine from vendored crates with no downloaded binary. The session had advised against the port; `DECISIONS.md` records both.

## 0. One screen for the owner

**What you get.** The guard as one Rust program, built from the crate `tools/rs/guard/`, that gives the same answer as `tools/guard/guard.py` for every recorded input, byte for byte. Each machine builds it from the commit it runs, offline, from crates committed in the repository and one pinned compiler version. A hook denies every call when the program is missing or was built from other source than the tree holds.

**How the port is proven.** Four layers, each a check that fails on a difference: the fixture corpus and the command-line cases run against both programs (step 3.1); every pattern compared between the two regex engines (step 3.3); the replay of 45 days of recorded calls; and a shadow period in which both judge every live call.

**What you do.** One approval now. One `owner ready` line after Phase 2, when the items are filed. Then one `/approve` per pull request, fourteen pull requests and the gate's, two of them yours to merge (the workflows and the switch). One answer the plan cannot give for you: whether your work machine can hold a Rust toolchain (section 7, line 14). Section 8 counts 21 acts.

**What you give up.** A guard that runs wherever Python runs. After the port a machine without the pinned Rust toolchain cannot run the kit's guard at all. The repository grows by the vendored crates (a guess: 10 to 20 MB), the box image by the toolchain, CI by one job.

**Open questions for you.** (1) Can your work machine hold `rustup` and one pinned toolchain (line 14 of section 7)? It decides whether the Python guard is ever deleted. (2) Is the Copilot cloud agent used anywhere you need the guard? If not, its row and its setup file fall away (line 13). (3) May a session run the offline build, or only you (line 6)?

**Yours to strike, defaults in section 7:** the three crates and what they pull in (line 2); the length of the shadow period (line 8); the other tools, which this plan only sketches (line 16).

**Not in this plan.** Any port of the tracker, the ledger, the box tools or the rest: section 2 lists them in order with their sizes, and each group gets its own short plan once the guard's measured cost is known.

**Cost.** $0 a month. About 27 session days for the guard, and two shadow periods of 14 days each; a guess for the end is late February 2027. As API-equivalent spend, a guess: $1,100 to $2,500.

## 1. Assumptions, and what was not checked

- **The guard today.** `tools/guard/guard.py`: 6,469 lines, 263 functions, 16 rules, standard library only. It runs `git` in three places, opens one connection to `127.0.0.1` (`:3146`), reads eight environment names and hashes with SHA-256 once (`:4732`). The rules run in a forked child that the hook kills after 3.5 s (`:6022`, `:6113-6122`), because a Python `re` search cannot be interrupted.
- **Its tests.** 30 test files, 12,290 lines. By a text search 29 of them load the module in-process (13 of those also start the command line) and one only starts the command line. The fixture test calls each rule as a function (`tools/guard/tests/test_fixtures.py`), not through the command line.
- **The corpus.** 1,604 files under `tools/guard/tests/fixtures/`: 1,573 cases in 16 rule folders (798 for Claude Code, 775 for Copilot; 669 allow, 699 ask, 205 deny), 28 captured event shapes in `_shapes` and 3 inputs in `_crash`. 61 cases carry a `config` and 5 carry `files`. Item #114 says "18 rules": the two folders with an underscore were counted as rules.
- **Its patterns.** A run that records every pattern the guard compiles finds 92: 87 at import and 5 more over the corpus. 14 use lookaround, a backreference or a conditional, which the `regex` crate does not have (section 4; item #114 says 13 lines, counted by a text search). Others use what the two engines read differently: `$` in 42 patterns, `\Z` in 3, `\s` in 41, `\d` in 10, `\b` in 7, `\w` in 6, and 7 are case-insensitive.
- **The hook's time**, on the owner's Mac, Python 3.13.13, medians of 30 runs. `hook pre` on one Bash event: 48.2 ms. `guard.py version`, which judges nothing: 44.6 ms. `python3 -c pass`: 8.8 ms. So about 36 ms pass before any rule runs (the script's compilation, its imports and its patterns; not split further) and about 4 ms are the judging. On 2026-11-26 the same call measured 46 ms, 8 ms of it interpreter start.
- **Where hooks run it.** `.claude/settings.json` and `.github/hooks/guard.json` call `python3 tools/guard/guard.py`. In Claude Code the path starts at `$CLAUDE_PROJECT_DIR`, so a session started in the main checkout is judged by that tree's guard also while it edits a worktree. A box mounts a checkout of one commit read-only at `/judge` and runs that guard (`tools/box/box.py:237-281`). CI runs `pytest` on Python 3.9 and 3.13 (`.github/workflows/ci.yml`). The kit copies `guard.py` into a task repository as one managed file (`kit.manifest`).
- **Rust on the owner's Mac.** macOS 26.7.3, arm64. Homebrew's `rustup` is on the `PATH`; `cargo` and `rustc` are not. One toolchain is installed, `stable-aarch64-apple-darwin`: `rustc` 1.100.0 (2026-11-09) and `cargo` 1.100.0, with `clippy` and `rustfmt`. No Rust image is on the machine; the box images are 1.39 GB each.
- **Other tools.** Non-test Python under `tools/`: 15,963 lines, of which the guard is 6,469. The rest: tracker 2,664, telemetry 2,242, box 1,597, orchestration 1,389, memory 492, review 302, scan 257, testguard 221, egress 189, `commit_msg.py` 141.
- **Phase 2 is taken as delivered as its plan says** (`docs/PLAN-2026-11-phase-2.md`): a session acts as the App, a pull request merges after the owner's `/approve <sha>`, a workflow change is his to push and merge, guard 0.13.0 is on `main`, and `guard-config` also covers `tools/box/`. Every line number, count and version above moves with it.
- **Not checked.** Each is a probe in the first commit of the step named; fallbacks are in sections 5 and 9. (a) With the network off, `cargo build --offline --locked` builds from the vendored crates (3.2). (b) The full list of crates that `regex`, `serde_json` and `sha2` pull in, and the size of `vendor/` (3.2). (c) What the `rustup` proxy does with a pinned toolchain that is not installed; the build wrapper does not go through the proxy either way (3.2). (d) How long a cold and a warm build take on the Mac, in CI and in the box (3.2). (e) What the `regex` crate needs to compile the 92 patterns, the bounded gap `[^|;&\n]{0,2000}` first of all (3.3). (f) The Rust hook's time with the source digest computed on each call (3.4). (g) Whether every fixture case gives the same answer through the command line as through the function call, the 61 with a `config`, the 5 with `files` and the `scratch-md` cases above all (3.1). (h) Whether two builds of one commit give the same bytes; recorded, not required (3.2). (i) What VS Code does with a hook command that fails or does not exist (3.7). (j) Whether the Copilot cloud agent can build in its setup steps and then finds the program (3.2b; it needs a run of the cloud agent, which this plan does not make). (k) A build on Windows (section 7, line 14).

## 2. Steps

Each row is one pull request with numbered commits, one topic each. Every row also changes `README.md`, `docs/SYSTEM.md` and `DECISIONS.md`. Python stays for the test tools and for every tool not yet ported, so `ruff check tools` and `pytest` on Python 3.9 and 3.13 hold in every row; from 3.2 on `cargo fmt --check`, `cargo clippy` with warnings as errors and `cargo test` hold too.

| id | What is built | Files | Verification | Size | PR | After |
|---|---|---|---|---|---|---|
| 3.1 | **The conformance runner.** A Python tool that feeds cases to any executable and compares its answer with a recorded one: exit code, standard output, the deny reason on standard error and the line in `decisions.jsonl` without its time. Cases: the 1,573 fixture cases as `hook <rule>`, the 28 shapes and 3 crash inputs as `hook pre`, and the command-line cases: `version`, `rules`, `help`, `hook post`, `hook fan-out`, `hook capture`, and the text tables of `test_table_forms.py`, `test_bypass_forms.py` and `test_deploy_ask.py` as `hook pre`. Each case gets its own folder with the case's `config` as `.claude/guard.json`, its `files` and a cleaned environment. The answers of the Python guard are written to a golden file; a test fails when that file is not what the Python guard answers now. | `tools/guard/tests/conformance/` | The Python guard passes every case. At least ten planted breaks in the Python guard are each caught: a rule that stays silent, an ask turned deny, a changed reason, a wrong exit code, a swallowed crash, a dropped log field among them. Two false programs fail: one that is always silent, one that always denies. The list goes into `DECISIONS.md`. | L | A | G0 |
| 3.2 | **Toolchain, crates and build, with a program that judges nothing.** `tools/rs/`: a Cargo workspace, `Cargo.lock`, the pin as a plain file `toolchain`, `.cargo/config.toml` (crates from `vendor/` only, offline), `vendor/`, and `build.sh`, the one way to build. The crate `guard` answers `version` and `build` (source digest, compiler version, target, digest of the lock file) and nothing else. Guard 0.14.0, rows first: the `cargo` verbs that can download ask on the host (`vendor`, `fetch`, `update`, and `build`, `test`, `run`, `check`, `clippy` without `--offline`; `install` and `add` ask already), and `build.sh` stays silent. An engineer agent for Rust, pinned to Opus. `cargo vendor` runs in a container, since it downloads. | `tools/rs/`, `tools/guard/guard.py`, `tools/guard/tests/`, `agents/`, `.gitignore` | Probes (a) to (d) and (h). In a container without network: the build succeeds. One changed byte in a vendored file: the build fails. A second run of `cargo vendor` in a container gives the committed `vendor/` byte for byte. `build.sh` with another compiler version on the `PATH`: it refuses and names the pin. The crate list with each crate's licence is in `DECISIONS.md`. | L | B | A |
| 3.2b | **The two workflow files of the port, in one pull request.** A job `rust` in `ci.yml`, needed by the job `ci`: it installs the pinned toolchain, builds offline, runs `fmt`, `clippy`, `cargo test`, the vendor comparison and the conformance run of the Rust program (cases not yet ported are listed as pending, and a pending case that passes fails the job, so the list only shrinks). And the setup file of the Copilot cloud agent, which installs the pinned toolchain and runs `build.sh`. | `.github/workflows/ci.yml`, `.github/workflows/copilot-setup-steps.yml`, `tools/tests/test_workflows.py` | The job is green on this pull request; with a planted difference in `vendor/` it is red; a skipped `rust` job leaves `ci` red. | S | C | B |
| 3.2c | **The box.** The image gains the pinned toolchain from a base pinned by digest in `pins.env`. `box.py` builds the judge's program in a container of that image when it takes a judge, once per judge commit, into a folder mounted read-only beside `/judge`. Last commit: `box_probe.py` rerun and `verified.json`. | `tools/box/`, `verified.json` | `pytest tools/box`; `bin/box doctor`; in a box, without network to any registry, `build.sh` builds and `cargo test` passes; the judge's program reports the judge's digest. | M | D | B |
| 3.3 | **Patterns and standard-library twins.** A dump of the guard's patterns with their flags and lines; a Rust module with one translation per pattern and the 14 of section 4 carried by hand; twins of what the rules use from Python: `shlex`, the path functions, `str.split` and `strip`, and a JSON writer that reproduces Python's separators, key order and escapes. | `tools/rs/guard/`, `tools/guard/tests/conformance/` | Probe (e). The differential run: Python writes, per pattern and input, what each call site reads (yes or no, spans, groups); `cargo test` compares. Inputs: every command of the corpus, each cut at every token edge, with the characters the assertions look at inserted, a final newline added and removed, and every code point once for each class. Planted breaks: `$` left as written, one lookbehind dropped, the here-document's tab rule dropped. | XL | E | C, D |
| 3.4 | **The core.** Reading the event in both harness shapes, the configuration and its environment overrides, the profiles, combining verdicts, the answer, the decision log, `capture`, `post`, the command line, the 3.5 s budget (the rules on a second thread; the first answers the `budget` ask and ends the process), and the staleness check. | `tools/rs/guard/` | Probe (f). Conformance: the 28 shapes, the 3 crash inputs and the command-line cases that need no rule equal the golden file. The budget cases of `test_hook_budget.py` as cases: a 1 MB line and a 50 kB line answer within the budget. A changed source file: every hook call is denied until `build.sh` has run. | L | F | E |
| 3.5 | **The shell reader.** What the rules share for reading a command line: segments, quoting, substitutions, here-documents, redirects, wrappers. | `tools/rs/guard/`, `tools/guard/tests/conformance/` | Python dumps what each reader function returns for every command of the corpus and for the differential inputs of 3.3; `cargo test` compares. The in-process tests of these functions exist as Rust tests with the same rows. | XL | G | F |
| 3.6a to 3.6d | **The rules, four groups.** (a) `delete-guard`, `scratch-md`, `protected-branch`, `git-guard`. (b) `secret-read`, `secret-write`, `secret-shell`, `egress-guard`. (c) `deploy-ask`, `host-install`, `tracker-guard`, `github-tools`. (d) `guard-config`, `fan-out`, `cloud-launch`, `workflow-launch`, with the box and cloud tables and the box's merge check. Each group moves its in-process Python tests: one that asserts a verdict becomes a conformance case, one that asserts an inner function becomes a Rust test. | `tools/rs/guard/`, `tools/guard/tests/conformance/` | The group's cases leave the pending list and equal the golden file. Per group three planted breaks in the Rust code, each caught. After (d): no case is pending, and the replay of the last 45 days of recorded calls gives the same answer from both programs for every call. | L each | H, I, J, K | G |
| 3.7 | **Shadow.** A launcher `tools/guard/hook` (POSIX `sh`): no program, a deny; else it runs the Python guard, which stays the authority, and the Rust program on the same input and compares the two answers. Both wirings and the box's settings call the launcher. `build.sh --if-stale` runs at session start and after `git` moves the tree (`post-merge`, `post-checkout`). A verb `shadow-report` counts calls and disagreements per source digest. | `tools/guard/hook`, `.claude/settings.json`, `.github/hooks/guard.json`, `.githooks/`, `tools/box/`, `tools/rs/guard/` | Probe (i). A planted disagreement: the call gets an ask that names both answers (a deny in a box), a record is written and the count starts again. The program removed: every call is denied with the build line in the reason. The hook's median on the Mac with both programs running is recorded. | L | L | K |
| 3.8 | **The switch.** The Rust program becomes the authority and the Python guard the shadow. `guard-config` gains `tools/rs/` and the launcher. `docs/RULES.md`: the enforcer `guard:NAME` names a rule of the Rust program. The record: the shadow report, the replay, the hook's time. | `tools/guard/hook`, `tools/guard/guard.py`, `tools/rs/guard/`, `docs/RULES.md`, `tools/tests/test_rules_table.py` | The five conditions of section 6 hold at this head and are in the pull request. A session's edit under `tools/rs/` asks. Reverting this one commit gives the state of 3.7 back. | M | M | L, the shadow period |
| 3.9 | **Deletion and the kit.** `tools/guard/guard.py` and the Python tests that load it leave; the launcher loses its shadow mode. `kit.manifest`: `tools/rs` as a folder and the launcher replace `guard.py`; `install.sh` names the build line and builds nothing. One install into a fresh target. `AGENTS.md` and `docs/USING-AT-WORK.md` say what a machine needs. | `tools/guard/`, `kit.manifest`, `install.sh`, `tools/tests/`, `AGENTS.md`, `docs/` | In a new `git init` folder: two installs, the second with `changes: 0`; `build.sh` builds; the installed guard denies a force push; with the program removed every call is denied. The conformance run stays in CI against the golden file, which is from now on changed by hand with a decision line. | L | N | M, the second period, act 19 |

**The other tools, sketched and not approved by this plan.** In this order, each group with its own short plan after 3.9: (1) what runs on every call or session: `testguard.py hook`, `latest_tag.py hook`, `memstore.py hook`, `session_start.py`, `ledger.py hook`; (2) the gates that read only text: `commit_msg.py`, `egress_screen.py` (two of its patterns need section 4's treatment), `brief_lint.py`; (3) the tools that call a forge, a model or Docker: the tracker with `label_lint.py` and its Azure DevOps adapter, `assert_run.py`, `fresh_review.py`, the box. Group (3) needs an answer first. Some of these speak HTTPS themselves, the Azure DevOps adapter and the box's firewall check among them, and HTTPS in Rust means a TLS stack and, by the session's estimate, several dozen more crates to vendor. So they would call `gh`, `curl` and `git`, or stay in Python.

New paths at the end: `tools/rs/`, `tools/guard/hook`, `tools/guard/tests/conformance/`, `.github/workflows/copilot-setup-steps.yml`, one agent definition, and this file. `tools/guard/guard.py` is gone, or kept by his answer (section 6).

## 3. Pull requests, items and order

- **Gate G0, no build step.** When Phase 2 is delivered the session reads sections 1, 4 and 5 again against `main` and commits the changed figures to this file in one pull request. A fact that changes a step or a decision of section 7 goes back to the owner; changed counts and line numbers do not. The items are filed from the text as it then stands, one per pull request, and he promotes them with one `owner ready` line. Nothing of Phase 3 is built before G0.
- **Where each is built.** A, E, F, G, H, I, J and K change only `tools/rs/` and the guard's test folder: in a box, where an edit of a guard path is logged and not asked. A box merges no head that changes such a path (`tools/guard/guard.py:3641-3647`), so the host session merges each after his `/approve`. B (the guard), C (the workflows), D (the box), L (the settings), M and N are built on the host.
- **Order.** A; then B; then C and D; then E, F, G one after another; then H to K, up to four boxes at once, each on a linted brief (`orchestrate`), the first of them end to end before the other three start; then L, the shadow period, M, the second period, N.
- **Who merges.** The host session as the App after his `/approve`, with two exceptions: C holds the two workflow files, which the App cannot push, and M changes what judges the session, so he merges both.
- **A change to the Python guard during the port** regenerates the golden file in the same pull request, and from the merge of its rule's group on it carries the same change in Rust, or the `rust` job is red. The port freezes nothing by rule; it makes each rule change cost twice until 3.9.

## 4. The fourteen patterns, and the other differences between the two engines

Read at `f64c875`; step 3.3's brief reads each use again, and guard 0.13.0 may add some. Three ways to carry one over.

- **Way A, for a pattern read as yes or no.** The neighbour test becomes a consumed character: `(?<![X])` becomes `(?:\A|[^X])`, `(?![X])` becomes `(?:[^X]|\z)`, `(?=[X]|$)` becomes a group that consumes. A match exists in one form exactly when it exists in the other; where the match lies is not read.
- **Way B, for a pattern whose spans or groups are read.** The pattern without the assertion finds a candidate, code tests the neighbour or the excluded words, and after a failed test the search goes on one character after the candidate's start.
- **Way C, a scanner written by hand**, for the one pattern with backreferences and a conditional.

| Line | Pattern | Uses | Read as | Way |
|---|---|---|---|---|
| 444 | `DELETE_RE`, the part `del\s*\(` | lookbehind | yes or no (`:753`, `:764`) | A |
| 455 | `_SQL_CLIENT_RE` | lookbehind, lookahead | yes or no (`:755`, `:807`) | A |
| 985 | `_HEREDOC_RE` | two backreferences, a conditional, a lazy body, `\Z` | groups, a substitution, a search from a position (`:614`, `:809`, `:991`, `:5224`) | C |
| 1082 | `_REDIRECT_RE` | lookbehind | every target (`:1968`) | B |
| 1510 | `_EMPTY_TOKEN_RE` | lookahead | yes or no (`:1972`) | A |
| 1591 | `_LAST_ARG_RE` | lookbehind, two lookaheads | yes or no (`:1806`, `:1829`) | A |
| 1626 | `_CASE_WORD_RE` | lookbehind, lookahead | yes or no (`:1645`) | A |
| 2549 | the `az` row of `_DEPLOY_PATTERNS` | a lookahead over three words | yes or no (`:2576`) | B |
| 3287 | `_GC_REDIRECT_RE` | lookbehind | every target (`:3365`) | B |
| 3767 | `_GRAPHQL_URL_RE` | lookahead, case-insensitive | yes or no (`:3833`, `:3958`) | A |
| 4074 | the first row of `_HI_COARSE` | a lookahead after the pipe | two groups for the reason (`:4468`) | B |
| 5248 | `_CASE_RE` | lookahead | yes or no, from a position (`:5258`) | A |
| 5249 | `_ESAC_RE` | lookahead | yes or no, from a position (`:5257`) | A |
| 5969 | the Azure DevOps token of `_SECRET_RES` | lookbehind, lookahead | spans, for redaction (`:5982`) | B |

Eight by way A, five by way B, one by way C. Each is checked three times: by the differential run of step 3.3 on its own inputs, by its rule's fixtures through the conformance run, and by a planted break (the assertion dropped) that both must catch. The here-document scanner reproduces the pattern as it behaves, including what the shell would read otherwise: the port changes no verdict.

**The other 78 patterns** have a direct form in the `regex` crate, but four things do not mean the same and get a written translation rule, proven by the same run. `$` without the multi-line flag also matches before a final newline in Python and only at the very end in the crate. `\Z` is written `\z`. `\s` in Python also holds U+001C to U+001F. `\w`, `\d`, `\b` and case-insensitive matching follow each engine's own Unicode tables, which already differ between Python 3.9 and 3.13; the run over every code point shows where, and each difference is removed or listed (section 7, line 4).

**Beyond patterns.** Python text can hold a lone surrogate from a JSON escape and Rust text cannot; Python integers have no limit. Where the Rust program cannot hold an input, it answers an ask and never stays silent.

## 5. Where each place builds, and how a hook fails closed

One rule for all: `tools/rs/build.sh` is the only way to build. It finds a `cargo` whose `rustc` reports exactly the version in `tools/rs/toolchain` and refuses any other. It builds with `--offline --locked` from `vendor/`, under a lock, and puts the program at `tools/rs/bin/guard` with one rename, so a hook never reads a half-written file. It downloads nothing and installs nothing.

| Place | Toolchain | Who builds, when | State |
|---|---|---|---|
| The owner's Mac | the installed 1.100.0, called by its path and not through the `rustup` proxy; the pin is this version, so nothing is installed | `build.sh --if-stale` at session start and after `git` moves the tree; a session or the owner by one line otherwise | proven in 3.2 and 3.7 |
| The box | in the image, from a base pinned by digest | `box.py`, in a container, once per judge commit; a session in a box builds its own work with `build.sh` | proven in 3.2c |
| CI | installed by the job at the pinned version | the job `rust`, on every pull request | proven in 3.2b |
| Copilot cloud agent | installed by its setup steps | the setup steps, before the agent starts | written in 3.2b; proven only when someone runs it once (probe j); until then named as not served |
| The work machine | the owner's answer (section 7, line 14) | `build.sh`, run by him or at session start | open; it gates step 3.9 |

**Fails closed, two checks.** The launcher is a few lines of `sh` in the repository: when `tools/rs/bin/guard` is missing or cannot run, it prints the deny answer both harnesses read, exits 2, and the reason names the build line. The program holds the digest of the source it was built from (the crate's files, `Cargo.lock`, the pin) and computes it again from the tree on each call; on a difference it denies and names the build line. If that costs more than 3 ms (probe f), the fallback is a comparison of file times in the launcher.

**No deadlock.** A guard that denies every call would also deny the call that builds it. So the build is started outside the pre-tool hook: at session start, by the two `git` hooks, and by the owner with one line in his terminal. In a box the judge is read-only and built before the session starts.

**What the decision log gains.** Each line names the source digest beside the version, so a recorded decision points at the exact code that made it.

## 6. The shadow period, the switch, the deletion

- **Shadow.** From the merge of L the launcher runs both programs on every `pre` call on the host and in a box. The Python guard is the authority. A disagreement is any difference in exit code, answer or log line. On one, the call gets an ask that names both answers (a deny in a box, by its table), a record with the redacted event is written under the telemetry folder, and the period's counts start again. In CI a disagreement on the corpus or the pending list is a red job.
- **The switch (M) needs all five.** (1) 14 days and 5,000 live calls judged by both with no disagreement, at one source digest of the Rust program; a new digest starts the count again. (2) At the head of M: the conformance run with no pending case, the differential run and the 45-day replay, all equal. (3) The Mac, the box and CI have each built the program from source and passed the corpus there; the cloud agent and the work machine have his recorded answer. (4) The Rust hook's median on the Mac is at most 15 ms for the event of section 1, the staleness check included. (5) No listed divergence without his word.
- **After the switch** the Python guard judges second under the same rule for 14 days and 5,000 calls. Going back is the revert of one commit.
- **The Python guard is deleted in N**, at the earliest 28 days after L's merge, when the second period is clean and act 19 is recorded. If his answer is that a machine he uses cannot build, N does not delete: the Python guard stays in the kit for such machines, the conformance run keeps the two equal, and that outcome is recorded with its cost (each rule change twice).

## 7. Decisions taken in this plan

Each line is the owner's to strike; where two ways exist, both are named.

1. **All Rust lives in one workspace under `tools/rs/`.** Nothing at the repository's root: the kit is copied into task repositories, and a root `Cargo.toml` would collide with a target's own.
2. **Three crates and what they pull in: `regex`, `serde_json`, `sha2`.** No other; a new one later is a decision line. The list with licences is reviewed in 3.2. Alternatives: `fancy-regex` or `pcre2` keep the 14 patterns as written, but bring back backtracking, the reason for the kill at 3.5 s; a SHA-256 written by hand saves crates and puts own hash code into a control.
3. **The 14 patterns are carried by hand in three ways** (section 4).
4. **Equal means byte for byte**: exit code, standard output, the deny reason and the log line without its time. A divergence is allowed only toward ask or deny, only where the Rust program cannot hold the input, and each is listed with his word. Alternative: equal verdicts only; cheaper, and every reason text is then judged by eye.
5. **The pin is a version in a plain file, and it is 1.100.0**, the compiler on his Mac today, so the host needs no install. The wrapper compares and refuses. Alternative: `rust-toolchain.toml`, which the `rustup` proxy may answer with a download on the host (probe c), plus his one `rustup toolchain install` per pin. Named: when he updates his `stable`, `build.sh` refuses until the pin moves in a pull request or he installs 1.100.0 beside it.
6. **Building is not installing.** `build.sh` is offline, reads only the repository and writes only inside the clone, so a session, the session-start hook and two `git` hooks may run it. Alternative: only he builds, one line after every pull that moves the guard's source. Named: the built program then runs as his user on every tool call, as `guard.py` does today.
7. **Missing is the launcher's deny, stale is the program's deny** (section 5).
8. **The shadow period is 14 days and 5,000 calls, twice** (section 6). Shorter is his to say. For scale: the replay for guard 0.12.0 held 24,438 recorded calls of 45 days (`DECISIONS.md`), about 540 a day.
9. **The owner merges the switch**, as he merges what changes a session's judge.
10. **Until the switch `tools/rs/` is not a `guard-config` path.** The Python guard is the authority, and a wrong Rust program can only add asks. So boxes can build it and the host does not prompt on each edit. From M on it is guarded like `tools/guard/`.
11. **The box image carries the toolchain**, and the judge's program is built per judge commit. Alternative: build it on the host and mount it; impossible, since the host is macOS and the box Linux.
12. **One CI job under the existing check `ci`**, so the ruleset of Phase 2 needs no change. Both workflow files of the port sit in one pull request, C, since each workflow change is his to push and merge.
13. **The Copilot cloud agent is written for and not proven.** The setup file ships; until a run shows the hook finds the program, the documents say the cloud agent is not served, and the launcher denies there.
14. **The work machine decides the deletion.** The question for him: can it hold `rustup` and one pinned toolchain, and on Windows the build tools the compiler needs? Default until he answers: the Python guard is not deleted.
15. **Python stays** for the conformance runner, for every tool not yet ported and in CI.
16. **The other tools are sketched, not approved.** Items filed now would freeze guesses; each group's plan comes with the guard's measured cost per ported line and the answer on HTTPS.
17. **During the port the Rust program reports the Python guard's version** and its own source digest. At the switch it becomes guard 1.0.0.

## 8. The owner's acts

**Now, one sitting (about 15 minutes):** 1. strike lines of section 7 if he wishes; 2. approve the plan with his word in the session and merge this pull request with the one line the session prints; 3. answer line 14 if he can, or leave the default.

**At gate G0, after Phase 2:** 4. read the changed figures, a pull request of one file, and `/approve` it; 5. one pasted `owner ready` line with the item numbers.

**During the build:** 6. to 16. one `/approve <sha>` each on A, B, D, E, F, G, H, I, J, K and L; 17. push and merge C, the two workflow files, with two pasted lines the session prints.

**The switch:** 18. read the shadow report in M, `/approve`, and merge it with one pasted line.

**Deletion and delivery:** 19. his answer on the work machine, recorded verbatim; 20. `/approve` on N; 21. one `owner done` line with the item numbers.

Twenty-one acts. Not counted: a fix after a review costs one more `/approve`; a `rustup update` on his Mac costs a pin change or one install line (section 7, line 5). Item #114 itself: its first criterion says the plan is written after Phase 2, so at `owner done 114` he waives that criterion with a reason, or leaves the item in review until G0 is merged.

## 9. Error paths and edge cases

- **Phase 2 is not delivered as planned.** G0 reads what is there. Without the App identity the merges fall back to what holds then; without guard 0.13.0 the port starts from 0.12.2 and its figures stand.
- **Probe (a) fails**, the offline build needs the network: the phase stops, since building from vendored crates is his decision; the question returns to him.
- **Probe (e) fails**, a pattern is too large for the crate: the bounded gap is carried by way B, a search for the first word and a scan of at most 2,000 characters.
- **Probe (d) shows a cold build that outlasts the session-start hook:** the hook starts the build and does not wait; until the program is in place every call is denied, and the reason says a build is running.
- **Probe (i) shows that VS Code runs a call when its hook command cannot start:** the launcher is then the one piece that must always start there, the documents say so, and a machine without `sh` is not served (last line).
- **Probe (g) fails**, a case cannot be reproduced through the command line: it stays a Python test until its rule is ported, becomes a Rust test then, and is counted in the record.
- **A build is running while a hook fires:** the old program is in place until the rename; if it is stale it denies, and the next call finds the new one.
- **Two sessions build at once:** the lock; the second waits and finds the work done.
- **A session started in a worktree** has that tree as its project and builds its own program at session start; the cold build's time is probe (d).
- **The tree moves under a running session** (a pull): the `post-merge` hook builds inside the same call. If it fails, every later call is denied and the reason names the one line; the owner runs it.
- **A disagreement in the shadow period that is the Python guard's defect:** it is fixed in Python first, with a fixture, and the golden file follows; the Rust program is never the reference before the switch.
- **A vendored crate gets a security advisory:** a pull request moves the lock and `vendor/` together, built in a container; CI's comparison proves the new folder.
- **The work machine has no `sh`** (Windows without Git Bash): named with act 19; the launcher then needs a second form, which this plan does not build.

## 10. Skeleton or production-grade, and what is deferred

- **Production-grade:** the conformance runner and its golden file, the build wrapper with the pin and the vendor comparison, the Rust guard, the launcher, the shadow report.
- **Skeleton:** the setup file for the Copilot cloud agent (never run by this plan); the work machine (an answer, not a proof); a build on Windows; builds are not shown to be bit-identical across machines.
- **Deferred, each with its trigger:** the other tools (after 3.9, his word); a second launcher form for Windows (act 19 says a Windows machine is used); a signed record of each build (a client asks for provenance beyond the commit and the lock file).
- **Cut line.** If time runs short, the cloud agent's setup file goes first, then the `shadow-report` verb (the record is then counted by hand from the log). Not cut: the conformance runner, the differential run, the two fail-closed checks, the shadow period.

## 11. Effort and cost

Days of session work: A 1.5, B 1.5, C 0.5, D 1, E 3, F 2, G 3.5, H to K 2 each, L 1.5, M 0.5, N 1.5, and 3 for fixes after reviews; about 27.5. Elapsed: about six weeks of building, less where four boxes run at once, then 28 days for the two periods. With Phase 2 delivered by its target of 2026-12-08, a guess for N is late February 2027; with Phase 2 at its latest date, late March.

Money: $0 a month. A public repository's Actions minutes cost nothing; in a private target the `rust` job is a few billed minutes per pull request, a guess of under $2 a month at 20 pull requests. As API-equivalent spend, from Phase 2's guess of about $40 to $90 a session day: $1,100 to $2,500 for the guard. The other tools are not estimated: about 9,500 lines with no corpus like the guard's.

## 12. Delivered means

Delivered = pull requests A to N merged on `main`, the two periods clean, the Python guard deleted or kept by his recorded answer (section 6), one install of the kit into a fresh target that builds and denies a force push, and `owner done` on the items. The other tools are a later delivery with their own plans.

## 13. What an auditor gains, and does not

- **Gains.** Validation evidence for the port as a like-for-like replacement of a validated control: the corpus and its golden answers, the differential record, the planted-break lists, the replay and two shadow reports, each tied to a commit. Build provenance: the source and every dependency are in the repository under review, the lock file holds each crate's checksum, CI proves `vendor/` equals what the registry serves for that lock, the compiler is one named version, and no binary crosses a machine. Each logged decision names the digest of the code that made it. The requirement-to-check table (`docs/RULES.md`) keeps its rows.
- **Does not gain.** The compiler is a downloaded binary, trusted as the Python interpreter is today. On the host a session runs as the owner's user and can overwrite the built program, as it can edit `guard.py` today; `guard-config` asks, and the residual of the parent plan (D6) stands. Equal answers on recorded inputs do not show equal answers on every input; the differential inputs are generated, not exhaustive. The crates are read by their list and licences, not line by line. Author and reviewer are one model family.

## 14. `DECISIONS.md`

One block comes with this pull request, "2026-11-27 — Phase 3 plan put up": the owner's words of 2026-11-26 and of 2026-11-27, the session's advice against the port, the measured hook time, the compliance angle, the one-off cost, the two corrected figures of item #114, and one line for each decision of section 7 that has a cost or a compliance side. His approval is added when he gives it, with its time and form. Each pull request of the port adds its own line.
