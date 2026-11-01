---
name: verify
description: Run the project's automated verification pipeline (lint → typecheck/build → test → schema validation). Distinct from the built-in harness `verify` skill, which runs the app to observe behavior — this one runs the project's static check pipeline.
user_invocable: true
---
# Verification Pipeline

When the user runs `/verify`:

## Detect the project's check commands

Look for the project's check commands in `package.json` scripts, `Makefile`, `justfile`, `pyproject.toml`, or CI config (`.github/workflows/`, `azure-pipelines.yml`, etc.). Use what the project defines — don't assume a toolchain.

## Steps (stop on first failure)

Run in order:

1. **Lint** (e.g. `npm run lint`, `ruff check`, `make lint`)
   - Pass → continue
   - Fail → report errors, STOP

2. **Typecheck / Build** (e.g. `npm run build`, `tsc --noEmit`, `mypy`)
   - Pass → continue
   - Fail → report type/compile errors, STOP

3. **Test** (e.g. `npm run test`, `pytest`, `go test ./...`)
   - Pass → continue (report count)
   - Fail → report failing tests, STOP

4. **Schema validation** (if present — e.g. `npx prisma validate`, migration checks)
   - Pass → all clear
   - Fail → report schema errors

## Output

```
## Verification Results

| Step | Status | Details |
|------|--------|---------|
| Lint | ✅ PASS | No errors |
| Typecheck/Build | ✅ PASS | Compiled successfully |
| Test | ✅ PASS | N tests, M suites |
| Schema | ✅ PASS | Schema valid |

**Result: ALL CHECKS PASSED** ✅
```

If any step fails, stop and show:
```
**Result: FAILED at [step]** ❌
[error details]
```
