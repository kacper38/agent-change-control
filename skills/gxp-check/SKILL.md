---
name: gxp-check
description: Fast compliance + security sweep of the working tree, mapped to GxP vocabulary. Use before each significant commit, before a demo or release, or on "gxp check" / "compliance sweep". Complements the gxp-compliance-reviewer agent (this is the quick greppable pass; the agent does the deep review).
---

# GxP check

Mechanical sweep first, judgment second. Report as a table, fix blockers
immediately with user approval.

## Sweep (run all, show evidence)

1. **Secrets in code/state:** `gitleaks detect --no-banner` when installed;
   fallback:
   `grep -rniE '(api[_-]?key|secret|password|token)\s*[:=]' --exclude-dir={.git,node_modules,.venv,.terraform} .`
   plus check `*.tfstate`, `.env` committed?
   (`git ls-files | grep -E '(^|/)\.env(\.|$)|\.tfstate' | grep -v '\.env\.example'`)
2. **Container hygiene:** Dockerfile has `USER` (non-root)? `HEALTHCHECK`? base
   image pinned? no `latest` anywhere (`grep -rnE ':latest' . --include='Dockerfile*'
   --include='*.yml' --include='*.yaml' --include='*.tf' --exclude-dir=.git 2>/dev/null`)
3. **CI hygiene:** `permissions:` block present and minimal? OIDC not static
   keys (`grep -rn 'AWS_SECRET\|AZURE_CLIENT_SECRET' .github/ $(git ls-files '*azure-pipelines*.yml')`)?
   image tagged by SHA? Azure Pipelines: service connections with workload
   identity federation, `System.AccessToken` mapped only into the steps that
   call the REST API, no secret values in variable groups (secret variables or
   Key Vault links instead)
4. **IaC hygiene:** `terraform fmt -check -recursive`, then
   `terraform init -backend=false -input=false >/dev/null && terraform validate`
   (independent checks — a fmt failure must not mask validate; `-backend=false`
   validates without remote-state credentials); grep for wildcard IAM
   (`grep -rnE '"([a-zA-Z0-9-]+:)?\*"' terraform/ | grep -iE 'action|resource'` —
   catches `"s3:*"` as well as bare `"*"`)
5. **Debug leftovers:** `grep -rn 'print(\|console.log\|TODO\|FIXME' app/ src/ 2>/dev/null | head`
6. **Vulnerability scan** (run what's installed, name what isn't as a gap):
   filesystem/image `trivy fs --severity HIGH,CRITICAL .` or `trivy image <tag>`;
   dependencies `pip-audit` / `npm audit --audit-level=high`;
   IaC `trivy config terraform/` or `checkov -d terraform/`
7. **Pipeline lineage** (when the repo loads/moves data): loader without an
   idempotency mechanism (hash/watermark/upsert)? job writes data but no
   `pipeline_runs`/lineage record? quarantine path for bad records exists?

## Map findings to compliance vocabulary

For each finding, add the GxP hook in one clause:

| Finding | Hook |
|---|---|
| secret in repo/state | breaks audit-safe change control; vault + data source |
| shared/static CI keys | breaks Attributable — OIDC gives per-run identity |
| `latest` tag | breaks Traceable/reproducible — SHA tags are validation evidence |
| no tests before deploy | no validation evidence for the change |
| mutable/no logs | breaks Contemporaneous/Enduring — server-side, retained logs |
| untracked manual env change | breaks Original — IaC is the documented environment |
| unscanned image/deps/IaC | unassessed risk in a validated system — the scan report is validation evidence |
| data written without run record | breaks Traceable/Original — one lineage row per pipeline run |

## Output

Pass/fail table per category with the evidence lines, then: "BLOCKERS: n — fix
before commit" or "clean — commit away", plus one audit-ready summary sentence, e.g.:
"Every change here is attributable and reproducible — git + OIDC + SHA-tagged
artifacts are the audit trail, tests and terraform plan are the validation evidence."
