#!/bin/zsh
# The orchestrating session's check of the fix pass of groups B and C, without touching the worktree: the guard
# file of a commit is written to the scratch folder and the checkers load it from there. Nothing under test is
# run: every command is a string handed to rule functions.
# usage: zsh verify-fix.sh              the head of the branch
#        zsh verify-fix.sh <commit>     that commit
#        zsh verify-fix.sh gate         only the commit-message gate, the trailer and the Refs line of every
#                                       commit since the build head 8879cd5
MAIN=<MAIN>
WT=$MAIN/.claude/worktrees/g090-bc
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
BUILD=8879cd5
OLD=$ORCH/ref/guard-0.8.0.py
ROWS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt $S8/rows-b-fix.txt $S8/rows-b-fix-add.txt $S8/rows-b-fix-add2.txt
      $S8/rows-b-fix-add3.txt $S8/rows-b-fix-add4.txt $S8/rows-b-fix-add5.txt $S8/rows-b-fix2.txt $S8/rows-b-fix2-add.txt
      $S8/rows-b-fix3.txt $S8/rows-b-fix4.txt $S8/rows-b-fix5.txt $S8/rows-b-fix6.txt $S8/rows-b-fix7.txt
      $S8/rows-b-fix8.txt $S8/rows-b-fix8-add.txt $S8/rows-b-fix7-add.txt)

if [ "$1" = "gate" ]; then
  # zsh verify-fix.sh gate [<base>]: the commits since <base> (default: the build head)
  for SHA in $(git -C $WT rev-list --reverse --abbrev-commit --abbrev=7 "${2:-$BUILD}..HEAD"); do
    gate="ok"
    python3 $WT/tools/commit_msg.py --range "${SHA}~1..${SHA}" > /dev/null 2>&1 || gate="REFUSED"
    subject="$(git -C $WT log -1 --format=%s $SHA)"
    trailer="$(git -C $WT log -1 --format=%B $SHA | grep -i '^co-authored-by' | tail -n 1 | sed -E 's/^[^:]*: *//' | cut -c1-40)"
    refs="$(git -C $WT log -1 --format=%B $SHA | grep -c -E 'Refs #57')"
    files="$(git -C $WT show --stat --format= $SHA | grep '|' | sed -E 's/ *\|.*//; s/^ *//' | tr '\n' ' ')"
    echo "$SHA gate $gate | subject ${#subject} chars | Refs #57: $refs | $trailer | $subject"
    echo "        files: $files"
  done
  echo "worktree status: $(git -C $WT status --short | tr '\n' ';')"
  exit 0
fi

SHA=$(git -C $WT rev-parse --short "${1:-HEAD}") || exit 1
NEW=$ORCH/ref/guard-$SHA.py
OUT=$ORCH/out-fix/$SHA
mkdir -p $OUT
git -C $WT show "${SHA}:tools/guard/guard.py" > $NEW || exit 1
echo "== $SHA $(git -C $WT log -1 --format=%s $SHA)"

python3 -I $S8/expect.py $NEW $ROWS > $OUT/rows.log 2>&1
echo "rows: $(tail -n 1 $OUT/rows.log | sed 's/total rows //') | must-hold rows red: $(grep -c -E '^RED ([A-Z][st]|Fm) ' $OUT/rows.log)"
grep -E '^RED ' $OUT/rows.log | cut -c1-200 | head -n 20
python3 -I $S8/expect_files.py $NEW $S8/rows-b5-files.txt > $OUT/files.log 2>&1
echo "file rows: $(tail -n 1 $OUT/files.log | sed 's/total rows //')"

git -C $WT show "${SHA}:tools/guard/tests/test_table_forms.py" > $OUT/test_table_forms.py
python3 -I $ORCH/rows_in_module.py $OUT/test_table_forms.py $S8 > $OUT/tables.log 2>&1
echo "tables in the test module: exit $? | $(grep -c 'same lines, same order' $OUT/tables.log) of 22 as their files"
grep -v 'same lines, same order' $OUT/tables.log | cut -c1-200 | head -n 8

echo
echo "-- unseen forms (HR due, HS must hold)"
for f in $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt $ORCH/heldout-b-fix3.txt $ORCH/heldout-b-fix4.txt; do
  name=${f:t:r}
  python3 -I $S8/expect.py $NEW $f > $OUT/$name.log 2>&1
  echo "$name: HR red $(grep -c -E '^RED HR ' $OUT/$name.log) of $(grep -c -E '^HR ' $f) | HS red $(grep -c -E '^RED HS ' $OUT/$name.log) of $(grep -c -E '^HS ' $f)"
  grep -E '^RED H[RS] ' $OUT/$name.log | cut -c1-190
done

echo
echo "-- weaker than 0.8.0, each cell beside the due row that asks for it"
LISTS=($S8/rows-a.txt $S8/rows-a-added.txt $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt
       $H/heldout-a.txt $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt
       $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt $ORCH/heldout-b-fix3.txt $ORCH/heldout-b-fix4.txt
       $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt
       $ORCH/sem/run5/flags-probe.txt $ORCH/sem/run5/values-probe.txt)
LISTS+=($ORCH/probe-*.txt)  # every probe list of the orchestrating session, the second round's included
for f in $S8/review/rb/c*.txt; do
  case ${f:t} in c19-files.txt) ;; *) LISTS+=($f) ;; esac
done
python3 -I $ORCH/weaker_cells.py $S8/expect.py $OLD $NEW $ROWS $LISTS --list --json $OUT/unexplained.json > $OUT/weaker_cells.log 2>&1
echo "exit $? | $(tail -n 3 $OUT/weaker_cells.log | tr '\n' ' ' | cut -c1-400)"
echo "cells no due row asks for: $(grep -c -E '^UNEXPLAINED' $OUT/weaker_cells.log) (list: $OUT/weaker_cells.log); by kind:"
python3 -I $ORCH/cell_kinds.py $OUT/unexplained.json --known $ORCH/cells-read.txt > $OUT/cell_kinds.log 2>&1
grep -E '^(==|weaker)' $OUT/cell_kinds.log | cut -c1-160

echo
echo "-- every flag of the local search tools' help in front of a pattern and a secret file: must ask"
python3 -I $S8/probe.py $ORCH/sem/run5/flags-probe.txt $NEW > $OUT/flags-probe.log 2>&1
grep '^"' $OUT/flags-probe.log | grep -v 'secret-shell=ask' > $OUT/flags-probe.silent
FP_ASK=$(grep -c 'secret-shell=ask' $OUT/flags-probe.log)
FP_ALL=$(grep -c -v '^#' $ORCH/sem/run5/flags-probe.txt)
FP_SILENT=$(grep -c . $OUT/flags-probe.silent)
echo "flag probes: $FP_ASK of $FP_ALL ask | silent: $FP_SILENT"
cut -c1-120 $OUT/flags-probe.silent | head -n 12

echo
echo "-- new prompts on the noise lists"
python3 -I $H/orch/weaker.py $S8/expect.py $OLD $NEW $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt --stronger > $OUT/stronger.log 2>&1
tail -n 1 $OUT/stronger.log | cut -c1-200

echo
echo "-- cost: each rule called directly on 100 kB lines, limit 12 s per rule (client boundary)"
python3 -I $ORCH/cost_rules.py $S8/review/rb/cost-units.txt 100000 main client 12 $NEW > $OUT/cost_rules.log 2>&1
grep -E 'slow\[[^]]|limit|CRASH' $OUT/cost_rules.log | cut -c1-200
echo "units: $(grep -c ' B  total ' $OUT/cost_rules.log) | slowest total: $(grep ' B  total ' $OUT/cost_rules.log | sed -E 's/.*total +([0-9.]+)s.*/\1/' | sort -n | tail -n 1) s"
echo "-- cost: the real hook, 0.8.0 beside this commit, client boundary"
python3 -I $ORCH/cost_hook.py $S8/review/rb/cost-units.txt 100000 client $OLD $NEW > $OUT/cost_hook.log 2>&1
grep -E 'budget|NO ANSWER' $OUT/cost_hook.log | cut -c1-200
grep -E '^k11-many' $OUT/cost_hook.log | cut -c1-200
