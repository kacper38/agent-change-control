# Review of guard 0.9.0, groups B and C: the reviewer agent's report on the build head 8879cd5

One separate Opus agent with the reviewer's role and a brief of its own read the diff of the build
(769b9d2..8879cd5) on 2026-11-18 and fixed nothing. The harness did not let a subagent write a report
file, so the report came back as the agent's hand-back text at 20:35 UTC; the orchestrating session saved
that text here unchanged, below the line. Its ids B1 to B8, M1 to M8 and m1 to m6 are the reviewer's own;
the rows of the fix pass carry other ids (F01 to F20). Verdicts are written 0.8.0 -> head. The probe
files it names are in `probes/`.

---

BLOCKER

(The harness refused to write report.md in rb/, because subagents may not write report files. The report is below. The probe files are kept in rb/: c1–c19 and cost-units.txt, plus gen_cost.py, which now takes a size argument. Verdicts are 0.8.0 -> head. "inference" means it rests on what the tool does with the form, which I did not measure.)

B1 | BLOCKER | K6/K9 quiet reports | `_quiet_reports` (diff 405-424) | `{ ls .env; } | xargs cat`, `{ echo .env; } | xargs cat`, `if true; then echo .env; fi | xargs cat`, `for f in a; do ls .env; done | xargs cat`: secret-shell ask -> silent (c1 l.2-6) | ask | probe | the pipe check stops at the simple command; walk out to the enclosing group or compound and count its pipe as "piped onward"
B2 | BLOCKER | K6/K9, lexer fallback | `simple_commands` falls back to `segments()` with sep "" (2706-2710) | `ls .env | xargs cat # it's` and `ls .env | xargs cat; echo $'it\'s'`: ask -> silent (c10 l.1,3); both are valid bash | ask | probe | when `_hi_lex` returns None, return no quiet reports
B3 | BLOCKER | K4 previews | `_git_clean_dry` (diff 105-123), worktree prune check (150-151) | `git clean -n --no-dry-run -fdx`, `git clean --dry-run --no-dry-run -fdx`, `git clean -fd -n --no-d`, `git worktree prune -n --no-dry-run`: delete-guard ask -> silent (c2 l.2,3,6,13). git negates a boolean option with `--no-` and accepts unique prefixes (inference) | ask | probe | the last of `-n`/`--dry-run`/`--no-dry-run` and their prefixes wins; any other `--d…` or `--no-d…` asks
B4 | BLOCKER | K2 | restore branch of `_delete_preview` (diff 145-147) | `git restore --staged --work f.py`, `--wor`, `--staged --no-staged`, `-S --no-staged`, `--worktree=`: ask -> silent (c2 l.7-11). These restore the worktree and discard changes (inference) | ask | probe | silent only when every long option is an exact known one; any `--w…` or `--no-staged` asks
B5 | BLOCKER | K3 (the first pass now uses the reader seg) | `_search_pattern` (835-874) | `rg --ignore-file .env pattern`, `ag --path-to-ignore .env pattern`, `ag -p .env pattern`: ask -> silent (c1 l.24-26). The value of an option that takes a file is taken for the pattern, so the read of `.env` is dropped | ask | probe | a per-tool list of options that take a value (rg `--ignore-file --pre -g -t -m -A -B -C`, ag `-p -G`, …), each skipped together with its value
B6 | BLOCKER | K11, a search tool's option whose value is run | `_search_patterns` / `_only_in_search_patterns` (diff 661-711) | client boundary: `ag --pager 'less|ollama|x' x .` and `ack --pager 'less|ollama|x' x .`: egress ask -> silent (c4 l.1-2). ag and ack hand the pager to a shell (inference) | ask | probe | the same fix as B5: the value of `--pager` (and of rg `--pre`) is no pattern
B7 | BLOCKER | GraphQL (L rows) | `path == "graphql"` in `_tracker_seg` (diff 965) | `gh api /graphql -f query='mutation{closeIssue…}'`, `gh api https://api.github.com/graphql …`, `gh api --method POST /graphql …`: silent at both versions (c13 l.10,11,14). gh then sends a REST POST with the fields as a JSON body, which the GraphQL endpoint accepts (inference) | deny | probe | strip a leading `/`, the API host, a trailing `/` and a query string before comparing with `graphql`
B8 | BLOCKER | GraphQL, two query fields | `_gh_graphql_query` returns the first (diff 899-917) | `gh api graphql -f query='{viewer{login}}' -f query='mutation{closeIssue…}'`, and the same with `-F query=@q.graphql` or `--input q.json` after it: silent (c14 l.3-5). gh keeps the last field (inference) | deny / ask | probe | read every query field and every `--input`; any one that cannot be read asks
M1 | MAJOR | cost, K11 | `_only_in_search_patterns` reads the whole line again and re-splits it for every segment with a hit | `k11-many`, client boundary, egress-guard alone: 1.54 s at 5 kB (my run, gen_cost.py). Your figures: 12.8 s at 10 kB, more than 100 s at 20 kB; 0.8.0 answers in 0.1 s at 40 kB. My verdict: with the fork budget an overrun turns into an ask, so nothing passes on the Mac. But a 5-8 kB line now takes up to 3.5 s. Where no fork is made (Windows, a failed fork: guard.py 4141-4149) or a harness fails open on its own timeout (VS Code/Copilot), the call runs unjudged | linear time | measured | work out the patterns and spans once per line, outside the segment loop
M2 | MAJOR | fed shell | `_nc_pipe_shell` looks only at the next simple command | `cat run.sh | (bash)`, `| { cd x; bash; }`, `| ( cd x && bash )`, `| if true; then bash; fi`, `| bash -c "$(cat)"`: silent (c7 l.1,9-12) | ask | probe | look into a group, subshell or compound behind the pipe; `-c "$(cat)"` reads the pipe
M3 | MAJOR | secret stores | `_SECRET_STORES`, `_has` compares exactly | `security find-generic-password -ws x`, `aws configure get default.aws_secret_access_key`, `aws secretsmanager batch-get-secret-value`, `kubectl get --raw /api/v1/…/secrets`, `kubectl get Secret app -o yaml`, `kubectl get secret.v1 app -o yaml`, bare `doppler secrets` (prints the values, inference), `op items get X --reveal` (an alias, inference): all silent (c8) | ask | probe | read short-option clusters for `security`; take the last dotted part for `aws configure get`; lower-case kubectl resources and strip `.version.group` from them
M4 | MAJOR | wrapper | `_NC_SUB_WRAPPERS["doppler"]` | `doppler run --command 'rm -rf x'`: silent (c5) | ask | probe | treat `--command` as a script option
M5 | MAJOR | GraphQL spellings | `_graphql_value`, `_http_graphql_query` | `-f query=$'mut\x61tion{closeIssue…}'`, httpie `query:='"mutation…"'`, `http https://api.github.com/graphql < q.json`: silent (c13) | deny / ask | probe | ask for a `$'…'` value with escapes, for `:=` items, and for a body read from stdin
M6 | MAJOR | merge spellings | `_http_method` | `curl https://api.github.com/repos/o/r/pulls/3/merge -T body.json` (an upload is a PUT) and `http put …/pulls/3/merge` (httpie upper-cases the method, inference): silent (c18) | ask | probe | read `-T`/`--upload-file` as PUT; compare httpie's method word without case
M7 | MAJOR | az reads that now ask | `_AZ_READ_VERBS` | `az group export`, `az storage blob url`, `az acr task logs`, `az policy state summarize`, `az network watcher test-connectivity`: silent -> deploy-ask ask (c16, c17) | silent | probe | add `export url logs summarize` and the prefix `test-`
M8 | MAJOR | update-ref on macOS | `_update_ref_on_protected` (diff 760-776) | `git update-ref refs/heads/Main abc` on main: silent (c15). On a file system that ignores case, the loose ref is main's own file (inference) | deny | probe | compare the branch name case-folded, as Y1 does for paths
m1 | MINOR | `ls .env; cat "$_"` and `test -f .env && cat "$_"`: ask -> silent (c1 l.10-12). Variables are out of reach by design, but `$_` right after a quiet report hands the path straight on; the owner's call | probe
m2 | MINOR | `cat run.sh | fish` and `| ash`: silent (c6). `_PIPE_SHELLS` is narrower than `_NC_STDIN_SHELLS` | probe
m3 | MINOR | `builtin eval 'export HUSKY=0'; git commit -m x` and `command eval …`: silent (c18) | probe
m4 | MINOR | `go clean -modcache -h`: silent -> delete-guard ask, a new false ask (c2) | probe
m5 | MINOR | `.claude/ſettings.json` and `.github/hookſ/x`: silent. `str.lower()` does not fold U+017F; APFS does (inference); `casefold()` would | expect_files, c19
m6 | MINOR | `curl -X PUT https://api.github.com//repos/o/r/pulls/3/merge` and the host with a trailing dot: silent (c18) | probe

Sound, checked and nothing found:
- Group C: the neighbours of K1, K5, K7 and K10. K11 does not widen through pipes, substitutions, unquoted patterns, `bash -c` or ssh.
- The new tools that run a command: the 33 wrappers with options that take a value, with `--`, in chains, behind sudo and env, and their help forms (c5).
- The Homebrew `g` names in every table, in capitals too, and the look-alike tool names (c11).
- The net: unknown words in front of git/gh/az, plus 40 everyday commands that must stay silent (c12).
- GraphQL: aliases, fragments, strings, comments, field case (c13, c14).
- `git update-ref` with `-d`, `--stdin`, `-m` and `-C` (c15).
- Merges: the gh, curl, wget and xh spellings, and `--admin` (c18).
- Readers: `case` inside `$( )`, and ssh options behind the host (c9).
- Tests: the changes to `test_bypass_forms.py` are only the rows I1 ask for.

Not done:
- Cost at 100 kB for each unit: I stopped my run on your word and measured only 5 kB myself.
- Groups and subshells around a fed shell, beyond c7.
- Typed `-F query=` values.
- The single test files.
