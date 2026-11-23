# Review of item #69: the findings and how each closed

## Round 1

Two reviews read the branch at `ae370d8` (the first five commits, `1cacf7e..ae370d8`):

- the panel's own first run, `wf_f3c4aca4-f34` (`panel-run-ae370d8.json`): 18 findings, 4 MAJOR and 14 MINOR, all 18
  confirmed by its verifier;
- `bin/fresh-review` (`fresh-review-ae370d8.json`): COMMENT, 4 MINOR, $1.03.

Each finding is named by the id the panel gave it, or `fr-N` for the fresh review's N-th. Commits are those of
`feat/review-panel` after `ae370d8`.

| Id | Severity | The finding, in short | How it closed |
|---|---|---|---|
| infra-1 | MAJOR | The sha256 binds the script, not the agent files (`agents/*.md`) its `agentType` calls read their tools and prompt from; `guard-config` covers neither | Named, not fixed here: an Agent-tool call of the same type starts unasked too, so the gap is older than the panel. Backlog item #90 (an edit to an agent file asks, as one to a workflow script does). DECISIONS: the 0.12.1 decision and its limits, `7f4ee4c` |
| infra-2 | MAJOR | Nothing outside the verifier's prompt stops it running a lens's command; the guard is silent on a test run, `node`, a push of a feature branch; the DECISIONS line said otherwise | Fixed, `f2250f5`: the script lets a command through only when it is one plain read of a fixed list; any other is listed as not re-checked with the reason. The DECISIONS line is replaced, `7f4ee4c` |
| gxp-1 | MAJOR | The result is not tied to the change it reviewed (no head, a fixed `/tmp` diff path) | Fixed, `f2250f5`: `args.head` (40 hex) is required, each agent reports the HEAD it saw, one at another head is logged and counted, the result names the head; the README writes the diff to `<git dir>/review-panel/<head>.diff` |
| gxp-2 | MAJOR | The validation evidence (planted breaks, the live hook check, the cost) lives only in a scratch folder | Fixed: this folder. Rerunning the first lists for it showed the record's "32 of 32" at `1eae9bd` was 31 of 32 (corrected, `7f4ee4c`) |
| correctness-1 | MINOR | The pin reader passes an unpinned call hidden behind a regular expression literal; its stated limit was false | Fixed, `ef342f2`: a `/` where a regular expression may start, or inside `${...}`, fails the script. Probe before and after: `pin-probe.txt` |
| correctness-2 | MINOR | A ternary alias of `agent` and a direct `eval` pass the reader | Fixed, `ef342f2`: a key is only an `agent` after `{` or `,`; `eval`, `Function`, `arguments`, `constructor`, `this`, `globalThis` and a few more fail wherever they stand |
| correctness-3 | MINOR | The verifier's prompt counted a test run as a read | Fixed, `f2250f5`: no test, script or interpreter is on the list, and the lenses' prompt says not to run the change's code or tests |
| correctness-4 | MINOR | The stderr note said a name asks when a bound entry of it kept it silent | Fixed, `22bd67b`: the note lists only the names left with no binding |
| correctness-5 | MINOR | `test_the_version_is_0_12_0` and `_0_11_0` asserted 0.12.1 under their old names | Fixed, `eec1886`: each checks at least its own release; the names stay, since the test guard reads a renamed test as a removed one |
| infra-3 | MINOR | `install.sh init` copied the kit's binding into every new task repo | Fixed, `2022271`: a new target gets `"workflows": []`; `test_install.py` checks it |
| infra-4 | MINOR | The lookup climbs past the git root, so a worktree also hashes the main checkout's copy | Kept, named (DECISIONS limits, `7f4ee4c`; README, `f2250f5`): it fails closed, and whether the harness reads a folder above its start folder is not known |
| infra-5 | MINOR | The README sends the diff to a fixed, shared `/tmp/x.diff` | Fixed, `f2250f5` (see gxp-1) |
| infra-6 | MINOR | No `.gitattributes` protects the hashed bytes | Fixed, `8231b07`: `.claude/workflows/*.js -text` |
| infra-7 | MINOR | The Node-dependent test runs on whatever Node CI's image has | Named, not fixed: a `setup-node` step edits `.github/workflows/`, which is the owner's (DECISIONS, `7f4ee4c`) |
| gxp-3 | MINOR | The logged cost line names a ledger command without its verb | Fixed, `f2250f5`: `ledger.py agents --session <id>`; the success case asserts it |
| gxp-4 | MINOR | "measured below" with no measured figure | Fixed, `7f4ee4c`: $7.01 for the first run by the ledger (`ledger-agents.txt`), about $105 a month at 15 runs |
| gxp-5 | MINOR | "Reviewed" for a hash a build commit wrote | Fixed: "committed" in DECISIONS (`7f4ee4c`) and "the sha256 of its file" in the README (`66edd2f`); the merger line names the fresh-review receipt |
| gxp-6 | MINOR | Only the verifier's prompt stops an upload through a lens's command | Fixed, `f2250f5` (see infra-2): no network tool is on the list |
| fr-1 | MINOR | The verifier runs lens-written commands; the DECISIONS line claims more than the guard does | Fixed, as infra-2 |
| fr-2 | MINOR | The pin checker passes a ternary alias and a computed key | Fixed, `ef342f2` (both were fixed in the working tree, not yet committed, while the panel ran on `ae370d8`) |
| fr-3 | MINOR | The cost is said to be "measured below" and never recorded | Fixed, as gxp-4 |
| fr-4 | MINOR | The planted-break counts point to a scratch folder | Fixed, as gxp-2 |

## Round 2

`bin/fresh-review` of the whole branch against main at `66edd2f`, after the merge of main (`fresh-review-66edd2f.json`):
COMMENT, 2 MAJOR, 2 MINOR, $2.23.

| Id | Severity | The finding, in short | How it closed |
|---|---|---|---|
| fr2-1 | MAJOR | The record cites an evidence folder the diff does not add | By design: the folder is the commit after the code, since its captures need the code head; it is this folder |
| fr2-2 | MAJOR | DECISIONS and the README overstate the read-only list: the verifier is a Bash agent, and the script sent it each finding whole, so lens text reached it word for word | Fixed, `ab7dc86`: the verifier is sent the id, the title, and the command with its output or the file, line and quote; the README and DECISIONS (`acd0f94`) name its prompt and the guard as what stops another command |
| fr2-3 | MINOR | `--show-signature` is not refused, and it starts gpg or ssh-keygen | Fixed, `ab7dc86`; so is any word holding `%G` (the signature placeholders of `--format`), which this session found while fixing it |
| fr2-4 | MINOR | `install.sh`'s new stop before any copy has no test | Fixed, `21272f4`: three kits (the list on three lines, missing, twice) |

## Round 3

`bin/fresh-review` of round 2's commits, `--base 66edd2f` at `acd0f94` (`fresh-review-acd0f94.json`): COMMENT,
1 MAJOR, 2 MINOR, $0.60.

| Id | Severity | The finding, in short | How it closed |
|---|---|---|---|
| fr3-1 | MAJOR | git reads `+`, `-` or space between `%` and the letter as a modifier, so `%+GG`, `%-G?`, `% GK` still check a signature and `--format=%+GG` passed the list | Fixed, `0f7f6de`: a word matching `%[-+ ]?G` is refused; five more refused commands in the Node test |
| fr3-2 | MINOR | The cost of judging a finding from its title alone, and what would change that, is not recorded | Fixed in DECISIONS, `e559273` (the verifier bullet), with the revisit condition |
| fr3-3 | MINOR | The evidence is cited but not in the diff, and the "at the head" counts name a head the code has left | The planted breaks ran again at `0f7f6de`, and each result file names its commit. The folder comes after the commits it describes (see fr5b-2) |

One planted break of `install.sh` (`one-line-check-only`, the count of `"workflows"` keys dropped) passed round 2's
three kits; the fourth kit (one key on one line, another over two) is in `0f7f6de`.

## Round 4

`bin/fresh-review` of round 3's commits, `--base acd0f94` at `e559273` (`fresh-review-e559273.json`): COMMENT,
1 MINOR, $1.17. It found the new pattern stricter than the old one, with no check weakened or removed.

| Id | Severity | The finding, in short | How it closed |
|---|---|---|---|
| fr4-1 | MINOR | The limits in DECISIONS list a diff driver, textconv and `log.showSignature` as the config routes by which git starts a program, and read as a full list. A `pretty.<name>` alias holding `%GG` (used as `--format=<name>`) and `format.pretty` (read by a bare `git log`) reach the same signature check and pass the list, which reads the command line only | Fixed in DECISIONS, `7a42f08`: both are named, and the list is called examples. The script's comment already says the list checks the command line only, so the script and its hash stay as they are |

## Review 5a

`bin/fresh-review` of round 4's fix alone, `--base e559273` at `7a42f08` (`fresh-review-7a42f08.json`): COMMENT,
2 MINOR, $0.26. It found that the change only edits the text of `DECISIONS.md`, with no check touched.

| Id | Severity | The finding, in short | How it closed |
|---|---|---|---|
| fr5a-1 | MINOR | The verifier bullet's compliance clause says no command the verifier runs can write, run the change's code or reach the network. The same bullet's limits name programs that git's config starts, and those can | Fixed in DECISIONS, `e76140f`: the clause now speaks of the command line the script lets through, and points to that limit |
| fr5a-2 | MINOR | Round 4 is recorded in DECISIONS with no word on where its receipt and closure are kept | Fixed in DECISIONS, `e76140f`: `review-findings.md` and `fresh-review-e559273.json` are named |

## Review 5b

`bin/fresh-review` of a first version of this folder, `--base 7a42f08` at `f401dd2` (`fresh-review-f401dd2.json`):
COMMENT, 1 MAJOR, 4 MINOR, $1.33. That commit was never pushed; this folder replaces it. The review found the folder's
counts, sums and capture hashes consistent with each other, and saw the gaps in what it left out.

| Id | Severity | The finding, in short | How it closed |
|---|---|---|---|
| fr5b-1 | MAJOR | The folder names review 5a, but keeps neither its two findings, the commit that fixes them, nor its receipt. Row fr3-2 names no commit | Fixed here: the 5a table above and its receipt. The fixing commit `e76140f` now comes before this folder, so the folder can name it. fr3-2 names `e559273` |
| fr5b-2 | MINOR | Row fr3-3 said "the folder is the last commit", while the folder itself described a commit after it, so the captures stopped before the later commits | Fixed: the DECISIONS fix comes before the folder, and the captures ran at it, `e76140f`. Only this folder's two commits (`d9ee47f`, then the one that adds this file) come after them |
| fr5b-3 | MINOR | The planted-break runner counts any non-zero exit as caught, runs no unbroken baseline and names no test | Fixed: `run_panel_mutants_v2.py` runs the tests on the unbroken file first and stops unless they pass. It counts a break as caught only when pytest exits 1 with a failed test, names that test, and counts any other exit as an error. The three last lists ran again with it at `7a42f08`, the same code as `e76140f`: 83 of 83, 39 of 39 and 4 of 4, each by a named failed test, none by an error (`*-7a42f08.txt`). The earlier results stay as the first runner wrote them |
| fr5b-4 | MINOR | Some runs cannot be repeated from the folder alone: the old checker copy, the `git archive` copies, the renamed result files | Fixed: `planted-breaks/first_lists.sh` holds the commands as the session ran them, with the renames, and `final_runs.sh` holds the run at `acd0f94`. `breaks_v2.sh` writes the folder's names itself |
| fr5b-5 | MINOR | Failed and stopped runs are described but not kept. The 3.9 failure has no stated cause and no item | Kept what exists, in `originals/`: the two stopped capture runs (`acd0f94`, `e559273`), the full captures at `66edd2f` (read by round 2) and at `7a42f08` (read by review 5b), and the 3.9 rerun of round 1. The failing 3.9 run's output was never written to a file, since only its last line reached the session, so it cannot be kept. Its likely cause, unproven: planted breaks were editing files of the same tree in place during that run. Since then, breaks and captures run one after the other. No item is opened: every 3.9 capture on a clean tree since has passed |

## The last reviews

Review 5a's fix and this folder together are a diff over the egress screen's 200,000 characters, so the folder is two
commits and the last reviews read them apart:

- `e76140f` (review 5a's fix) with the folder's first commit `d9ee47f` (`originals/` and `panel-run-ae370d8.json`),
  `--base 7a42f08` at `d9ee47f`;
- the folder's second commit, the one that adds this file, `--base d9ee47f` at the pull request's head.

Their receipts name `d9ee47f` and this folder's last commit, so they are not here. The pull request names both and
how their findings closed.

## A hole neither review found

One more hole, found by this session's probe and by neither review: the reader skipped the code inside a template's
`${...}`, so `` `${await agent('go')}` `` passed. Fixed in `ef342f2`; `pin-probe.txt` shows it with the others.

The harness flagged one string in the verifier's structured answer as shaped like a settings instruction and
neutralised it (`logs` of `panel-run-ae370d8.json`); the string is a quoted path of `.claude/settings.json` in a
check note: data, no instruction.
