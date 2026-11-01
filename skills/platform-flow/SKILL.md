---
name: platform-flow
description: The code-to-running chain for a service — local dev → container → CI → IaC → CD → observability → security. Use after task-intake approval to execute the plan, or when asked "what's next in the flow". Each stage ends with verification and one commit.
---

# Platform flow

Execute the standard chain, one stage = one (or few) commits, each verified
before moving on. Skip or reorder stages only when the plan says so — and say why.

## Stages

1. **Local dev** — run the app locally; `docker-compose.yml` for dependencies
   (db, vector store). Verify: app responds locally.
2. **Containerize** — multi-stage Dockerfile: deps layer → runtime layer,
   non-root user (`useradd -m -u 10001 appuser`), slim base, HEALTHCHECK,
   exec-form CMD, `.dockerignore`. Next.js: `output: "standalone"`; copy
   `.next/standalone`, plus `.next/static` into `.next/standalone/.next/static`
   and `public/` into `.next/standalone/public` (standalone excludes both by
   design); run `node server.js` on a `node:<lts>-slim` base — not the full
   node_modules. Verify: `docker build` + run + load a real page, not just
   `/health` — health answers even when static assets 404.
3. **CI** — GitHub Actions: `ruff check` → `pytest -q` → `docker build` →
   `trivy image --exit-code 1 --severity HIGH,CRITICAL` → push to registry.
   Dependency audit next to lint (`pip-audit` / `npm audit --audit-level=high`
   where a lockfile exists). `permissions: {id-token: write, contents: read}`;
   OIDC role, no stored cloud keys; tag = `${{ github.sha }}`. Node/Next.js
   chain: `npm ci` → `eslint` → `tsc --noEmit` → test → `next build` → docker
   build (actions/setup-node with npm cache, version from `.nvmrc`). Azure
   Pipelines, same chain in `azure-pipelines.yml`: tag = `$(Build.SourceVersion)`;
   a workload identity federation service connection, no stored keys; PR runs
   come from a build-validation branch policy (YAML `pr:` is ignored on Azure
   Repos); tasks pinned `Name@X.Y.Z`, script steps preferred. Verify:
   workflow syntax (act or push), steps ordered fail-fast, scan gating before
   push.
4. **IaC** — Terraform module skeleton: `modules/network`, `modules/service`
   (compute per AGENTS.md: client's existing platform first, else greenfield
   default ECS Fargate + ALB on AWS, or Container Apps on Azure), `variables.tf`,
   `outputs.tf` (service URL), remote backend + locking (S3+DynamoDB /
   azurerm) — declared even if mocked. Secrets via data source into Secrets
   Manager / Key Vault, never in state. `modules/network` is the boundary,
   not decoration: private subnets for compute, default-deny SG/NSG, PaaS via
   private endpoints, controlled egress. App identity = task role / managed
   identity, never static keys. Event-driven glue (Lambda / Azure Functions)
   under the same rules: IaC-defined, SHA-pinned artifact, least-privilege
   role, timeout + DLQ. In CI: plan on PR posted as artifact, apply on merge
   behind environment approval — plan + approval are validation evidence.
   Verify: `terraform fmt -check`, `terraform validate`, review `plan` output
   with the user.
5. **CD** — deploy job gated on CI and pinned to the CI-built SHA; GitHub
   Environments with protection rules, required reviewers on prod (Azure
   Pipelines: deployment jobs against Environments with approvals and checks,
   Branch control on prod). The
   recorded approval + deployment log is validation evidence — the
   validation-evidence pack captures it. Verify: pipeline graph makes sense
   end-to-end; prod deploy blocked without approval.
6. **Observability** — `/health` endpoint, structured JSON logs, one metric
   and one alert sketched (CloudWatch / Azure Monitor); scheduled
   `terraform plan -detailed-exitcode` as a drift alert (branch on the exit
   code: 2 = drift → alert, 1 = plan error → failure) — undetected drift
   breaks Original: IaC is the documented environment. Verify: endpoint
   answers, log line shows correlation id.
7. **Security & compliance sweep** — run the `gxp-check` skill; fix blockers.

## LLM/RAG addendum (when the task includes it)

- vector store: pgvector via compose locally; managed (RDS/Flexible Server) in IaC
- answer traceability: log which chunks/sources fed each response — GxP requirement, mention it
- cost controls: token limits, response/embedding + prompt caching, model
  choice per task, batch APIs for offline work, cost-per-query metric
- data boundary: client data never to public API endpoints — private endpoints (Azure OpenAI in VNet / Bedrock) in the IaC story

## Timeboxing

At each stage boundary state: stages left and what falls below the cut line if
the budget is tight. "End-to-end skeleton with named gaps" beats "perfect stage
3 of 7". Record every deliberate gap in DECISIONS.md with its upgrade trigger.
