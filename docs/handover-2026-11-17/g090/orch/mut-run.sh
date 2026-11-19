#!/bin/zsh
# The planted breaks at one head, in a scratch copy of its tree: the list of the second round and the addendum
# first, then the lists of the fix pass and of the build again, so that the final tests are shown to catch them.
# The checkout under review is never touched. Nothing under test is run: the tests hand strings to rule functions.
# usage: zsh mut-run.sh <commit>       (the scratch tree mut/tree-<commit> must exist)
MAIN=<MAIN>
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
ORCH=$PAD/orch
SHA="$1"
TREE=$ORCH/mut/tree-$SHA
[ -s $TREE/tools/guard/guard.py ] || { echo "no scratch tree for $SHA"; exit 2; }
cmp -s $TREE/tools/guard/guard.py $ORCH/ref/guard-$SHA.py || { echo "the scratch tree's guard is not the head's"; exit 2; }
for list in fix2 fix b; do
  echo "== list mutations-$list.json at $SHA"
  python3 -u -I $HK/g080-heldout/orch/mutate.py $TREE $ORCH/mutations-$list.json tools/guard/tests > $ORCH/mut/run-$list-$SHA.log 2>&1
  echo "exit $? | $(tail -n 1 $ORCH/mut/run-$list-$SHA.log)"
  grep -E '^(SURVIVED|NOT APPLIED)' $ORCH/mut/run-$list-$SHA.log | cut -c1-200
done
cmp -s $TREE/tools/guard/guard.py $ORCH/ref/guard-$SHA.py && echo "the scratch tree's guard is back as it was" || echo "WARNING: the scratch tree's guard differs from the head's"
