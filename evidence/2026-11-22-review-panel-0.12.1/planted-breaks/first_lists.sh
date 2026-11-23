#!/usr/bin/env bash
# How the first planted-break lists and the pin probe's old checker were set up and run (item #69), as the session ran
# them one command at a time on 2026-11-22, here in one file. <PAD> is a scratch folder, <WT> the worktree.
# usage: bash first_lists.sh <PAD> <WT>   (writes only under <PAD>)
set -u
pad="$1"; wt="$2"; m="$pad/mut"
# scratch copies of the two commits the first lists ran at
git -C "$wt" archive -o "$pad/r0/1eae9bd.tar" 1eae9bd
git -C "$wt" archive -o "$pad/r0/330f0f7.tar" 330f0f7
mkdir -p "$pad/r0/t1eae9bd" "$pad/r0/t330f0f7"
tar -xf "$pad/r0/1eae9bd.tar" -C "$pad/r0/t1eae9bd"
tar -xf "$pad/r0/330f0f7.tar" -C "$pad/r0/t330f0f7"
# the first lists, with the first runner (run_panel_mutants.py), each on its own commit
python3 -I "$m/run_panel_mutants.py" "$pad/r0/t1eae9bd" .claude/workflows/review-panel.js "$m/panel_mutants.json" \
  tools/orchestration/tests/test_review_panel.py > "$m/panel_r0_1eae9bd_result.txt" 2>&1
python3 -I "$m/run_panel_mutants.py" "$pad/r0/t330f0f7" tools/orchestration/tests/test_workflow_pins.py \
  "$m/pin_mutants.json" tools/orchestration/tests/test_workflow_pins.py > "$m/pin_r0_330f0f7_result.txt" 2>&1
# the old pin checker that probe_both.sh reads
mkdir -p "$pad/r0/tae370d8/tools/orchestration/tests"
git -C "$wt" show ae370d8:tools/orchestration/tests/test_workflow_pins.py \
  > "$pad/r0/tae370d8/tools/orchestration/tests/test_workflow_pins.py"
# The folder keeps each result under the name of its list and commit: panel_r0_1eae9bd_result.txt is
# panel_mutants-1eae9bd.txt, pin_r0_330f0f7_result.txt is pin_mutants-330f0f7.txt. At acd0f94, final_runs.sh wrote
# panel_v3_result-acd0f94.txt, pin_v2_result-acd0f94.txt and install_v3_result-acd0f94.txt; at 0f7f6de, breaks.sh
# wrote panel_v4_result-0f7f6de.txt and the same two others; each is kept as <list>-<sha>.txt (panel_v4_result-0f7f6de.txt
# is panel_mutants_v4-0f7f6de.txt). breaks_v2.sh, with run_panel_mutants_v2.py, writes the folder's names itself.
