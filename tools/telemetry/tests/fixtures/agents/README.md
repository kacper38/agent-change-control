# Fixture sessions for the agent view (`ledger.py agents`)

Seven sessions made by hand, and the tree the view has to print for each. The trees in
`expected/` were written before the code (tracker item #59, criterion 8).

**Nothing here comes from a real transcript.** Every line was typed for this folder: the
ids are patterns (`11111111-…`, `a2000000000000001`), the project is `/work/demo`, and every
prompt, tool input, tool result, reply and thought is a short made-up string that carries a
marker (`PROMPT-MARKER`, `INPUT-MARKER`, `OUTPUT-MARKER`, `REPLY-MARKER`, `THINKING-MARKER`).
A test can therefore assert that no marker is ever printed. Only the *shape* of the lines
follows Claude Code 2.1.323 (which keys a line has), not their content.

## Layout

| Path | Stands for |
|---|---|
| `config/` | the Claude Code configuration folder (`CLAUDE_CONFIG_DIR`); sessions are in `config/projects/<project>/` |
| `telemetry/spawns.jsonl` | the spawn log the guard writes (`KZ_TELEMETRY_DIR`) |
| `prices.json` | the prices of these fixtures: round numbers, different from the shipped `tools/telemetry/prices.json` on purpose |
| `expected/` | the exact output per session, with the fixture prices |

USD per million tokens in `prices.json`:

| Model | input | output | cache read | cache write | 1-hour cache write |
|---|---|---|---|---|---|
| `claude-fable-5-2` | 10 | 50 | 1 | 10 | 20 |
| `claude-opus-5-5` | 5 | 25 | 0.5 | 5 | 10 |
| `claude-haiku-5-5` | 1 | 5 | 0.1 | 1 | 2 |
| `claude-haiku-5-5`, a request whose prompt is over 100,000 tokens | 2 | 10 | 0.2 | 2 | 4 |

## The sessions

| Session | Project | Expected | What it holds |
|---|---|---|---|
| `11111111-1111-4111-8111-111111111111` | `-work-demo` | `plain.txt` | no agents; a 1-hour cache write; a `<synthetic>` line without tokens; bookkeeping after the `cost-state` line |
| `22222222-2222-4222-8222-222222222222` | `-work-demo` | `two-agents.txt` | two agents; one request written as two lines; a description longer than 30 characters; one `speed: fast` request |
| `33333333-3333-4333-8333-333333333333` | `-work-demo` | `workflow.txt` | a finished workflow with two agents on two models; a request in the long-prompt tier; a journal with a usage line that must never be counted |
| `44444444-4444-4444-8444-444444444444` | `-work-demo` | `nested.txt` | an agent started by an agent (`parentAgentId` in its meta file); timestamps without a fraction, as a number and as garbage |
| `55555555-5555-4555-8555-555555555555` | `-work-demo` | `running.txt` | a session without a `cost-state` line; four ways an agent's transcript can end; a running workflow (no state file) |
| `66666666-6666-4666-8666-666666666666` | `-work-demo` | `broken.txt` | two broken lines, a broken meta file, a transcript without a meta file, an agent the spawn log knows and no transcript shows |
| `11111111-9999-4999-8999-999999999999` | `-work-other` | `noprice.txt` | a model the prices have no row for; its id shares the prefix `11111111-` with the first session |

## How the figures were worked out

Cost of one request = (input × input price + output × output price + cache read × its price
+ 5-minute cache write × its price + 1-hour cache write × its price) / 1,000,000. A request
id that appears on several lines is one request. Duration = the last timestamp of the file
minus the first, in whole seconds. Tool calls = the distinct `tool_use` ids of the file.

### `plain.txt`

| Request | Tokens | USD |
|---|---|---|
| `req_p_01` | 100,000 in, 10,000 out | 1.00 + 0.50 = 1.50 |
| `req_p_02` | 100,000 in, 10,000 out, 1,000,000 cache read, 100,000 cache write (all 1-hour) | 1.00 + 0.50 + 1.00 + 2.00 = 4.50 |

Session: $6.00, one tool call, 10:00:00.000 to 10:04:05.500 = 4m05s. The `<synthetic>` line
has no tokens: it adds no cost and no second model. Finished: the `cost-state` line comes
after the last reply, and the `last-prompt` line after it changes nothing.

### `two-agents.txt`

| Line | Requests | USD |
|---|---|---|
| session (Fable) | 2 × (50,000 in, 2,000 out); 60,000 in, 8,000 out | 2 × 0.60 + 1.00 = 2.20 |
| `a2000000000000001` (Opus) | 200,000 in, 4,000 out (two lines, one request); the same plus 1,000,000 cache read; 100,000 in, 2,000 out | 1.10 + 1.60 + 0.55 = 3.25 |
| `a2000000000000002` (Opus) | 4 × 100,000 in; 1,000 + 1,000 + 2,000 + 8,000 out | 2.00 + 0.30 = 2.30 |

Total $7.75 and 2 + 2 + 3 = 7 tool calls. Durations: 11:00:00 to 11:15:30, 11:00:06 to
11:09:36, 11:10:06 to 11:14:51. The first request of the second agent ran with
`speed: fast`, which the prices do not cover: its line and the total carry the `*`.

### `workflow.txt`

| Line | Requests | USD |
|---|---|---|
| session (Fable) | 40,000 in, 4,000 out; 40,000 in, 1,000 out; 50,000 in, 3,000 out | 0.60 + 0.45 + 0.65 = 1.70 |
| `a3000000000000001` (Opus) | 300,000 in, 10,000 out; 100,000 in, 10,000 out; 200,000 in, 10,000 out, 500,000 cache read | 1.75 + 0.75 + 1.50 = 4.00 |
| `a3000000000000002` (Haiku) | 50,000 in, 2,000 out; 150,000 in, 4,000 out, 50,000 cache read (prompt of 200,000: long tier) | 0.06 + (0.30 + 0.04 + 0.01) = 0.41 |

The workflow line is the sum of its two agents: $4.41, 3 + 1 = 4 tool calls, 12:00:12 to
12:19:45 = 19m33s, Opus with three requests against Haiku's two, so `opus-5-5 +1`. Total
$1.70 + $4.00 + $0.41 = $6.11: the workflow line is not counted a second time. The workflow
is finished because `workflows/wf_30000000-001.json` exists; its name comes from the file
name `workflows/scripts/demo-build-wf_30000000-001.js`. The first agent ends on the result
of its `StructuredOutput` call, which is how a workflow agent ends: finished.

### `nested.txt`

| Line | Requests | USD |
|---|---|---|
| session (Fable) | 2 × (30,000 in, 2,000 out); 40,000 in, 4,000 out | 2 × 0.40 + 0.60 = 1.40 |
| `a4000000000000001` (Opus) | 100,000 in, 4,000 out; 120,000 in, 12,000 out | 0.60 + 0.90 = 1.50 |
| `a4000000000000002` (Haiku), started by `…001` | 20,000 in, 1,000 out; 30,000 in, 1,000 out; 40,000 in, 4,000 out | 0.025 + 0.035 + 0.06 = 0.12 |
| `a4000000000000003` (Opus) | 200,000 in, 8,000 out; 100,000 in, 4,000 out | 1.20 + 0.60 = 1.80 |

Total $4.82 and 2 + 1 + 2 + 1 = 6 tool calls. The second agent's transcript lies beside the
others; only `parentAgentId` in its meta file puts it under the first. Its timestamps
include `2026-01-05T13:01:10Z` (no fraction: counted), a number and the text `not a time`
(both ignored), so its duration stays 13:01:01 to 13:14:59 = 13m58s.

### `running.txt`

| Line | Ends on | State | Requests | USD |
|---|---|---|---|---|
| session (Fable) | a reply, no `cost-state` line | running | 80,000 in, 4,000 out (one request on four lines); 2 × (20,000 in, 1,000 out) | 1.00 + 2 × 0.25 = 1.50 |
| `a5000000000000001` (Opus) | a tool call without a result | running | 100,000 in, 2,000 out; 110,000 in, 2,000 out | 0.55 + 0.60 = 1.15 |
| `a5000000000000002` (Haiku) | the result of a `Glob` call | running | 2,000 in, 400 out | 0.002 + 0.002 = 0.004 |
| `a5000000000000003` | its brief, no reply yet | running | none | 0.00 |
| `a5000000000000004` (Opus) | `[Request interrupted by user]` | finished | 60,000 in, 2,000 out | 0.35 |
| `a5000000000000005` (Opus), in the workflow | a reply still being written (`stop_reason` null) | running | 40,000 in, 2,000 out | 0.25 |

Total 1.50 + 1.15 + 0.004 + 0 + 0.35 + 0.25 = 3.254, printed as $3.25; 5 + 2 + 1 + 0 + 1 + 0
= 9 tool calls; five agents, four of them running. A cost above zero that two decimals
would print as `$0.00` is printed as `<$0.01`. The workflow has no state file, so it is
running; its line repeats its one agent's figures.

### `broken.txt`

| Line | What is wrong | Requests | USD |
|---|---|---|---|
| session (Fable) | line 3 is cut off in the middle (its 9,000,000 tokens are not counted) | 50,000 in, 1,000 out; 50,000 in, 3,000 out | 0.55 + 0.65 = 1.20 |
| `a6000000000000001` (Opus) | line 3 is no JSON | 100,000 in, 4,000 out; 80,000 in, 4,000 out | 0.60 + 0.50 = 1.10 |
| `a6000000000000002` | no transcript; the spawn log names it (`code-reviewer`, 15:00:07) | none | none |
| `a6000000000000003` (Haiku) | no meta file; the spawn log gives the type (two rows, one per start) | 100,000 in, 10,000 out (exactly 100,000 is not over the threshold) | 0.10 + 0.05 = 0.15 |
| `a6000000000000004` (Opus) | the meta file is cut off, and the spawn log does not know the agent: its type reads `agent` | 20,000 in, 4,000 out | 0.20 |

Total $2.65; 4 + 1 = 5 tool calls (the session's four `Agent` calls are four blocks of one
line); four agents, none running (the one without a transcript has no state). Under the
tree: one file not read (the meta file) and two lines (one per broken line). The spawn log
also holds a row of another session and a row without an agent id; both are ignored.

### `noprice.txt`

One request on `claude-next-9`, which `prices.json` has no row for: the cost of the line
and of the total is `n/a`, never a partial sum. 16:00:00 to 16:00:42 = 42s.

## How the expected files were typed

The values in every row (state, duration, cost, tool calls, model, label) were worked out
by hand as shown above; the columns were then padded with the row format of the view,
`f"{state:<8}  {time:>6}  {cost:>9}{mark}  {tools:>5}  {model:<14}  {label}"`, right-stripped.
The same figures were checked against the ledger's existing functions before any line of
the view was written: `build_entry()` with these prices gives `cost_usd_own` 6.0, 7.75,
6.11, 4.82, 3.254, 2.65 and none for the seven sessions, and `parse_errors` 2 for the
broken one.
