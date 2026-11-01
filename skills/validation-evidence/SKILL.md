---
name: validation-evidence
description: Assemble an audit-grade evidence pack for a change, feature, or release — requirement→implementation→test traceability plus captured check outputs. Use before a release, client handoff, or QA review; triggers "validation evidence", "evidence pack", "audit pack", "RTM".
---

# Validation evidence

Turn what the pipeline already produces into a reviewable evidence pack.
No paperwork theater: everything here is generated from real artifacts.

## Steps

1. **Scope.** Confirm the unit: a PR, a release tag, or a date range.
   List the requirements/stories it claims to satisfy (from the ticket,
   README scope section, or ask).
2. **Traceability matrix (RTM-lite).** One row per requirement:

   | Req | Implementation (files/commits) | Test / check | Evidence |
   |---|---|---|---|
   | REQ-01 short name | `path/file.py` @ `abc123` | `tests/test_x.py::test_y` | run output ref |

   Requirements with no test row are findings, not omissions to hide.
3. **Capture check outputs.** Run and save verbatim into `evidence/<tag>/`, through
   `tools/tracker/evidence_export.py capture --tag <tag> --name <check> -- <command>` where the
   kit is installed (it records sha256, size, exit code and the tool's `--version` per output in
   `captures.json`):
   test run (`pytest -q` / `npm test`), lint (`ruff` / `eslint` +
   `tsc --noEmit`), `docker build` digest (+ `next build` where applicable),
   `terraform plan` summary, image SHA + registry digest, vulnerability scan
   report (trivy / pip-audit / npm audit), SBOM where configured
   (`syft <image> -o spdx-json`), eval report if AI-touching.
4. **Change control trail.** `evidence_export.py export --tag <tag> --from <prev-tag> --to <tag>`
   writes `change-records.json` (PRs merged in the range with merge SHAs, reviewers and check runs,
   the issues they reference and those closed in the window, rulesets, captures re-hashed).
   Add `git log --oneline` for the scope, PR links +
   approvers, deployment approval records (environment protection), and
   DECISIONS.md entries relevant to this unit. On Azure DevOps the same trail
   is reviewer votes, builds and policy evaluations on the merge commit, the
   PR's completion options, branch policy configurations and Environment
   approval records. `export` reads all of those except the Environment
   approvals and the branch ACL (schema `/2`, verified against a fake API
   only): record those two in `SUMMARY.md` by hand (the GETs for the settings
   are in `docs/ADO-ADMIN.md`) and list them under Gaps.
5. **System description.** Confirm `docs/SYSTEM.md` still matches reality
   (fields per task-intake); update it within this release's scope. Auditors
   read it before any evidence pack.
6. **Gaps.** Explicit list: untested requirements, manual steps performed,
   known deviations — each with owner and follow-up.

## Output

`evidence/<tag>/SUMMARY.md` containing: scope, RTM table, links to captured
outputs, change trail, pointer to `docs/SYSTEM.md`, gaps. One screen; a QA
reviewer should get to "approve or ask" in five minutes. Commit the pack — evidence that can drift isn't
evidence (Enduring).
