#!/bin/zsh
# Run multiline_meta.py for one guard file over every row file and probe list the orchestrating session has.
# usage: zsh multiline-meta.sh <guard.py> <label>      writes out-meta/<label>.json and out-meta/<label>.log
MAIN=<MAIN>
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
GUARD="$1"; LABEL="$2"
[ -n "$LABEL" ] || { echo "usage: zsh multiline-meta.sh <guard.py> <label> [--wrappers]"; exit 2; }
MODE=()
[ "$3" = "--wrappers" ] && MODE=(--wrappers)
mkdir -p $ORCH/out-meta
LISTS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt $S8/rows-b-fix.txt
       $S8/rows-b-fix-add.txt $S8/rows-b-fix-add2.txt $S8/rows-b-fix-add3.txt $S8/rows-b-fix-add4.txt
       $S8/rows-b-fix-add5.txt
       $S8/rows-a.txt $S8/rows-a-added.txt $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt
       $H/heldout-a.txt $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt
       $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt
       $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt)
for f in $ORCH/probe-*.txt; do LISTS+=($f); done
[ -f $S8/rows-b-fix2.txt ] && LISTS+=($S8/rows-b-fix2.txt)
[ -f $S8/rows-b-fix2-add.txt ] && LISTS+=($S8/rows-b-fix2-add.txt)
for f in $S8/rows-b-fix3.txt $S8/rows-b-fix4.txt $S8/rows-b-fix5.txt $S8/rows-b-fix6.txt; do [ -f $f ] && LISTS+=($f); done
for f in $ORCH/heldout-b-fix3.txt $ORCH/heldout-b-fix4.txt; do [ -f $f ] && LISTS+=($f); done
python3 -u -I $ORCH/multiline_meta.py $MODE $S8/expect.py $ORCH/weaker_cells.py "$GUARD" $ORCH/out-meta/$LABEL.json $LISTS > $ORCH/out-meta/$LABEL.log 2>&1
code=$?
tail -n 40 $ORCH/out-meta/$LABEL.log | cut -c1-200
exit $code
