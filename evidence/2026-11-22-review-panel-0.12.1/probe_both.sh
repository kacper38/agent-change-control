#!/usr/bin/env bash
# probe_pins.py against the checker of ae370d8 and of the head; usage: bash probe_both.sh <pad> <worktree> > out
set -u
pad="$1"; wt="$2"
echo "== the checker at ae370d8 (git show ae370d8:tools/orchestration/tests/test_workflow_pins.py)"
uv run --offline --no-project --with pytest python -I "$pad/probe_pins.py" "$pad/r0/tae370d8"
echo "== the checker at $(git -C "$wt" rev-parse --short HEAD)"
uv run --offline --no-project --with pytest python -I "$pad/probe_pins.py" "$wt"
