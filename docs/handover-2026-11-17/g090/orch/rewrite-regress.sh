#!/bin/zsh
# Run rewrite_regress.py for an old and a new guard file over every row file and probe list the orchestrating
# session has, in several processes.
# usage: zsh rewrite-regress.sh <old guard.py> <new guard.py> <label> [<processes, default 4>]
#        writes out-regress/<label>.<i>.json and .log; list them with regress_list.py out-regress/<label>
MAIN=<MAIN>
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
OLD="$1"; NEW="$2"; LABEL="$3"; N="${4:-4}"
[ -n "$LABEL" ] || { echo "usage: zsh rewrite-regress.sh <old guard.py> <new guard.py> <label> [<processes>]"; exit 2; }
mkdir -p $ORCH/out-regress
LISTS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt $S8/rows-b-fix.txt
       $S8/rows-b-fix-add.txt $S8/rows-b-fix-add2.txt $S8/rows-b-fix-add3.txt $S8/rows-b-fix-add4.txt
       $S8/rows-b-fix-add5.txt $S8/rows-b-fix2.txt $S8/rows-b-fix2-add.txt $S8/rows-b-fix3.txt $S8/rows-b-fix4.txt
       $S8/rows-b-fix5.txt $S8/rows-b-fix6.txt
       $S8/rows-a.txt $S8/rows-a-added.txt $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt
       $H/heldout-a.txt $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt
       $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt $ORCH/heldout-b-fix3.txt $ORCH/heldout-b-fix4.txt
       $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt)
for f in $ORCH/probe-*.txt; do LISTS+=($f); done
i=0
while [ $i -lt $N ]; do
  python3 -u -I $ORCH/rewrite_regress.py $S8/expect.py $ORCH/weaker_cells.py $ORCH/multiline_meta.py "$OLD" "$NEW" \
    $ORCH/out-regress/$LABEL.$i.json --shard $i/$N $LISTS > $ORCH/out-regress/$LABEL.$i.log 2>&1 &
  i=$((i + 1))
done
wait
i=0
while [ $i -lt $N ]; do
  grep -E '^(old |classes|CRASH|Traceback)' $ORCH/out-regress/$LABEL.$i.log | cut -c1-220
  i=$((i + 1))
done
