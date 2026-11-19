#!/bin/zsh
# Planted breaks at one head through the guard's tests, in several scratch copies of its tree side by side.
# The checkout under review is never touched. Nothing under test is run: the tests hand strings to rule functions.
# usage: zsh mut-par.sh <commit> <chunks> <list> [<list> ...]     (list: fix7, fix56, fix3, fix2)
#        writes <this folder>/<commit>/chunk-<i>.json, run-<i>.log, summary.txt and, at the very end, done.txt
MAIN=<MAIN>
WT=$MAIN/.claude/worktrees/g090-bc
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
ORCH=$PAD/orch
HERE=${0:A:h}
SHA="$1"; N="$2"; shift 2
[ -n "$1" ] || { echo "usage: zsh mut-par.sh <commit> <chunks> <list> [<list> ...]"; exit 2; }
OUT=$HERE/$SHA
mkdir -p $OUT
REF=$ORCH/ref/guard-$SHA.py
[ -s $REF ] || { echo "no guard file for $SHA in ref/"; exit 2; }
PAIRS=()
for list in "$@"; do PAIRS+=("$list=$ORCH/mutations-$list.json"); done
python3 -I $HERE/mut_split.py $REF $OUT $N $PAIRS > $OUT/split.txt 2>&1 || { cat $OUT/split.txt; exit 1; }
i=0
while [ $i -lt $N ]; do
  TREE=$OUT/tree-$i
  if [ ! -s $TREE/tools/guard/guard.py ]; then
    mkdir -p $TREE
    git -C $WT archive $SHA | tar -x -C $TREE
  fi
  cmp -s $TREE/tools/guard/guard.py $REF || { echo "tree $i does not hold the head's guard"; exit 2; }
  python3 -u -I $HK/g080-heldout/orch/mutate.py $TREE $OUT/chunk-$i.json tools/guard/tests > $OUT/run-$i.log 2>&1 &
  i=$((i + 1))
done
wait
{
  cat $OUT/split.txt
  echo "KILLED $(cat $OUT/run-*.log | grep -c -E '^KILLED') | SURVIVED $(cat $OUT/run-*.log | grep -c -E '^SURVIVED') | NOT APPLIED $(cat $OUT/run-*.log | grep -c -E '^NOT APPLIED')"
  cat $OUT/run-*.log | grep -E '^(SURVIVED|NOT APPLIED)' | cut -c1-220
  i=0
  while [ $i -lt $N ]; do
    cmp -s $OUT/tree-$i/tools/guard/guard.py $REF || echo "WARNING: tree $i does not hold the head's guard any more"
    i=$((i + 1))
  done
  echo "finished $(date -u +%H:%M:%S)"
} > $OUT/summary.txt 2>&1
cp $OUT/summary.txt $OUT/done.txt
