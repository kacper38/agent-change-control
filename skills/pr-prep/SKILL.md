---
name: pr-prep
description: Prepare a pull request with verification, description, and checklist. Use when the user says 'prep a PR', 'open a PR', 'PR description'.
user_invocable: true
---
# Prepare Pull Request

When the user runs `/pr-prep`:

## Steps

1. **Run verification** — run the project's checks via `/verify`:
   - If any check fails → STOP and report
   - At home, when the repo has `bin/fresh-review`: run it (fresh-context Opus
     review of `origin/main...HEAD` through the egress screen; receipt under
     `.git/fresh-review/<sha>.json`). BLOCKER → STOP and fix; otherwise paste
     its output under "Independent review" below. At work the independent
     review is Copilot code review on the PR, steered by
     `.github/instructions/review.instructions.md`; write that instead.

2. **Analyze changes**:
   - `git diff main...HEAD --stat` — list changed files
   - `git log main..HEAD --oneline` — list commits

3. **Tracker link** (when the repo has `tools/tracker`): find the issue you
   claimed — `python3 tools/tracker/tracker.py list --status in-progress` —
   and `show N` for its acceptance criteria. They go into the PR checklist
   verbatim; the body carries `Refs #N`. Never `Fixes`/`Closes`/`Resolves`:
   closing is the owner's protocol (`tracker owner done`), not the forge's. On
   Azure Repos any state name before `#N` (`Done #N`, `Review #N`) counts too.

4. **Generate PR description**:

```markdown
## Summary
[1-3 bullet points from commit messages]

## Changes
[Group changes by area, using whatever areas fit the repo — e.g. API, UI, database, docs, config]

### [Area]
- [list changed files with brief description]

Refs #N

## Acceptance criteria (from the tracker issue)
- [ ] [copied verbatim from `tracker show N`]

## Checklist
- [ ] Tests: all passing (X tests, Y suites)
- [ ] Lint: no errors
- [ ] Build: compiles successfully
- [ ] Docs updated (if needed)
- [ ] No secrets in diff

## Test plan
[Describe how to verify the changes]

## Independent review
[fresh-review verdict, findings and receipt path — or "Copilot code review on this PR" at work]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

5. **Check docs**: check project docs (AGENTS.md/README) for sections needing updates, if present
6. **Open and hand over**: `gh pr create --title … --body-file <file>`; then, with the
   URL it printed, `python3 tools/tracker/tracker.py review N --pr <url>`
   (in-progress → review; refused if the head is not the claimed branch or the
   body lacks `Refs #N`) and post the /verify summary with
   `python3 tools/tracker/tracker.py note N "verify: <one line per check>"`.
   On Azure Repos (origin on `dev.azure.com` or `*.visualstudio.com`):
   `az repos pr create --title … --description "$(cat <file>)" --query pullRequestId -o tsv`,
   with `Refs #N` on the first line of the body: descriptions are capped at
   4000 characters, so trim the body below that, never the link. No
   `--auto-complete`, `--transition-work-items` or `--bypass-policy` (the
   guard denies the last two). Pass the web URL
   `https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}` or the
   bare id to `tracker review N --pr …`, not the API `url` the CLI prints.
   Without a tracker in the repo, stop at the ready-to-use PR body.
