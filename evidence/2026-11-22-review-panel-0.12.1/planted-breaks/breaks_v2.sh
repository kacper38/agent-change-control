#!/usr/bin/env bash
# The three last planted-break lists with run_panel_mutants_v2.py (baseline first, the catching test named), at the
# commit checked out in the worktree. Each run edits one file in place and restores it; one after the other.
# Results are written under the names the evidence folder keeps. usage: bash breaks_v2.sh <pad> <worktree>
set -u
pad="$1"; wt="$2"; m="$pad/mut"; h="$(git -C "$wt" rev-parse --short HEAD)"; o="$m/v2-$h"
mkdir -p "$o"
python3 -I "$m/run_panel_mutants_v2.py" "$wt" .claude/workflows/review-panel.js "$m/panel_mutants_v4.json" \
  tools/orchestration/tests/test_review_panel.py tools/orchestration/tests/test_workflow_pins.py \
  -k "not bound_to_its_committed_file" > "$o/panel_mutants_v4-$h.txt" 2>&1
python3 -I "$m/run_panel_mutants_v2.py" "$wt" tools/orchestration/tests/test_workflow_pins.py "$m/pin_mutants_v2.json" \
  tools/orchestration/tests/test_workflow_pins.py > "$o/pin_mutants_v2-$h.txt" 2>&1
python3 -I "$m/run_panel_mutants_v2.py" "$wt" install.sh "$m/install_mutants_v3.json" tools/tests/test_install.py \
  -k "stops_before or new_target_gets_boundary" > "$o/install_mutants_v3-$h.txt" 2>&1
head -n 1 "$o"/*.txt
tail -n 1 "$o"/*.txt
grep -h "^SURVIVED\|^ERROR\|^NOT-APPLIED" "$o"/*.txt
git -C "$wt" status --short
