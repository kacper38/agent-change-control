#!/usr/bin/env bash
# The three planted-break lists at the code head; each edits one file of the worktree in place and restores it.
# usage: bash breaks.sh <pad> <worktree>
set -u
pad="$1"; wt="$2"; m="$pad/mut"; h="$(git -C "$wt" rev-parse --short HEAD)"
python3 -I "$m/run_panel_mutants.py" "$wt" .claude/workflows/review-panel.js "$m/panel_mutants_v4.json" \
  tools/orchestration/tests/test_review_panel.py tools/orchestration/tests/test_workflow_pins.py \
  -k "not bound_to_its_committed_file" > "$m/panel_v4_result-$h.txt" 2>&1
python3 -I "$m/run_panel_mutants.py" "$wt" tools/orchestration/tests/test_workflow_pins.py "$m/pin_mutants_v2.json" \
  tools/orchestration/tests/test_workflow_pins.py > "$m/pin_v2_result-$h.txt" 2>&1
python3 -I "$m/run_panel_mutants.py" "$wt" install.sh "$m/install_mutants_v3.json" tools/tests/test_install.py \
  -k "stops_before or new_target_gets_boundary" > "$m/install_v3_result-$h.txt" 2>&1
tail -n 1 "$m/panel_v4_result-$h.txt" "$m/pin_v2_result-$h.txt" "$m/install_v3_result-$h.txt"
grep -h -v "^caught\|^total" "$m/panel_v4_result-$h.txt" "$m/pin_v2_result-$h.txt" "$m/install_v3_result-$h.txt"
git -C "$wt" status --short
