#!/usr/bin/env bash
# How the first planted-break lists and the pin probe's old checker were set up and run (item #69). The session ran
# these commands one at a time on 2026-11-22, in this order but for the two folders it had made before; this file
# is the same commands in a runnable form. <PAD> is an empty scratch folder, <WT> a checkout of this repository.
# usage: bash planted-breaks/first_lists.sh <PAD> <WT>   (writes only under <PAD>)
set -eu
pad="$1"; wt="$2"; m="$pad/mut"; here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$pad/r0" "$m"
# the session kept the runners and lists in <PAD>/mut; this folder keeps them in planted-breaks/
cp "$here"/run_panel_mutants.py "$here"/panel_mutants.json "$here"/pin_mutants.json "$m/"
# scratch copies of the two commits the first lists ran at
git -C "$wt" archive -o "$pad/r0/1eae9bd.tar" 1eae9bd
git -C "$wt" archive -o "$pad/r0/330f0f7.tar" 330f0f7
mkdir -p "$pad/r0/t1eae9bd" "$pad/r0/t330f0f7"
tar -xf "$pad/r0/1eae9bd.tar" -C "$pad/r0/t1eae9bd"
tar -xf "$pad/r0/330f0f7.tar" -C "$pad/r0/t330f0f7"
# the first lists, with the first runner, each on its own commit (the runner exits 0 whatever it counts)
python3 -I "$m/run_panel_mutants.py" "$pad/r0/t1eae9bd" .claude/workflows/review-panel.js "$m/panel_mutants.json" \
  tools/orchestration/tests/test_review_panel.py > "$m/panel_r0_1eae9bd_result.txt" 2>&1
python3 -I "$m/run_panel_mutants.py" "$pad/r0/t330f0f7" tools/orchestration/tests/test_workflow_pins.py \
  "$m/pin_mutants.json" tools/orchestration/tests/test_workflow_pins.py > "$m/pin_r0_330f0f7_result.txt" 2>&1
# the old pin checker that probe_both.sh reads
mkdir -p "$pad/r0/tae370d8/tools/orchestration/tests"
git -C "$wt" show ae370d8:tools/orchestration/tests/test_workflow_pins.py \
  > "$pad/r0/tae370d8/tools/orchestration/tests/test_workflow_pins.py"
tail -n 1 "$m/panel_r0_1eae9bd_result.txt" "$m/pin_r0_330f0f7_result.txt"
# The folder keeps each result under the name of its list and commit: panel_r0_1eae9bd_result.txt is
# panel_mutants-1eae9bd.txt, pin_r0_330f0f7_result.txt is pin_mutants-330f0f7.txt. At acd0f94, final_runs.sh wrote
# panel_v3_result-acd0f94.txt, pin_v2_result-acd0f94.txt and install_v3_result-acd0f94.txt; at 0f7f6de, breaks.sh
# wrote panel_v4_result-0f7f6de.txt and the same two others; each is kept as <list>-<sha>.txt (panel_v4_result-0f7f6de.txt
# is panel_mutants_v4-0f7f6de.txt). Both scripts read the lists and runners from <PAD>/mut and call <PAD>/captures.sh,
# which is captures.sh beside SUMMARY.md. breaks_v2.sh, with run_panel_mutants_v2.py, writes the folder's names itself.
