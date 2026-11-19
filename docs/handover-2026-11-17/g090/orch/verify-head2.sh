#!/bin/zsh
# The second half of the orchestrating session's check of a head of the fix rounds, without touching the
# worktree: the lint and the whole suite on both Pythons, the engineers' rewriting check, the two-guard rewriting
# check against 0.8.0, the multi-line check (plain and wrappers), and the plain verdicts beside the design probe.
# Nothing under test is run: every command is a string handed to rule functions.
# usage: zsh verify-head2.sh <commit>      (the guard file of that commit must be in ref/, as verify-fix.sh leaves it)
MAIN=<MAIN>
WT=$MAIN/.claude/worktrees/g090-bc
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
SHA="$1"
[ -n "$SHA" ] || { echo "usage: zsh verify-head2.sh <commit>"; exit 2; }
NEW=$ORCH/ref/guard-$SHA.py
OLD=$ORCH/ref/guard-0.8.0.py
OUT=$ORCH/out-fix/$SHA
[ -s $NEW ] || { echo "no guard file for $SHA in ref/"; exit 2; }
[ "$(git -C $WT rev-parse --short HEAD)" = "$SHA" ] || { echo "the worktree is not at $SHA"; exit 2; }
mkdir -p $OUT

echo "== the lint and the whole suite on Python 3.13 and 3.9 (the session's own run)"
sh $PAD/bc/g070/suite.sh $WT > $OUT/suite.log 2>&1
grep -E '^(== |ruff exit|All checks|pytest .* done)|passed|failed|error' $OUT/suite.log | cut -c1-200

echo
echo "== the engineers' rewriting check (one guard, the 14 row files)"
ROWS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt $S8/rows-b-fix.txt
      $S8/rows-b-fix-add.txt $S8/rows-b-fix-add2.txt $S8/rows-b-fix-add3.txt $S8/rows-b-fix-add4.txt
      $S8/rows-b-fix-add5.txt $S8/rows-b-fix2.txt $S8/rows-b-fix2-add.txt $S8/rows-b-fix3.txt $S8/rows-b-fix4.txt
      $S8/rows-b-fix5.txt $S8/rows-b-fix6.txt $S8/rows-b-fix7.txt $S8/rows-b-fix8.txt $S8/rows-b-fix8-add.txt
      $S8/rows-b-fix7-add.txt)
python3 -u -I $S8/rewrite_check.py $S8/expect.py $S8/rewrite_readers.py $NEW $ORCH/out-meta/s8-$SHA.json $ROWS > $ORCH/out-meta/s8-$SHA.log 2>&1
tail -n 1 $ORCH/out-meta/s8-$SHA.log | cut -c1-200
python3 -I $S8/rewrite_list.py $ORCH/out-meta/s8-$SHA.json 2>&1 | grep -E '^(turns|==)' | cut -c1-200

echo
echo "== plain verdicts beside the design probe, both ways (0 weaker cells each way means the same answers)"
LISTS=($S8/rows-a.txt $S8/rows-a-added.txt $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt
       $H/heldout-a.txt $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt
       $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt $ORCH/heldout-b-fix3.txt $ORCH/heldout-b-fix4.txt
       $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt)
LISTS+=($ORCH/probe-*.txt)
PROBE="${PROBE:-$ORCH/proto/guard-proto3.py}"
python3 -I $ORCH/weaker_cells.py $S8/expect.py $PROBE $NEW $ROWS $LISTS --list > $OUT/vs-probe-weaker.log 2>&1
echo "head weaker than the probe: $(grep -c -E '^UNEXPLAINED' $OUT/vs-probe-weaker.log) cells | $(tail -n 4 $OUT/vs-probe-weaker.log | grep -E '^old ' | cut -c1-160)"
python3 -I $ORCH/weaker_cells.py $S8/expect.py $NEW $PROBE $ROWS $LISTS --list > $OUT/vs-probe-stronger.log 2>&1
echo "probe weaker than the head: $(grep -c -E '^UNEXPLAINED' $OUT/vs-probe-stronger.log) cells | $(tail -n 4 $OUT/vs-probe-stronger.log | grep -E '^old ' | cut -c1-160)"
if [ -n "$PREV" ]; then
  echo "-- the same beside the head before this round ($PREV): no verdict may differ"
  python3 -I $ORCH/weaker_cells.py $S8/expect.py $ORCH/ref/guard-$PREV.py $NEW $ROWS $LISTS --list > $OUT/vs-prev-weaker.log 2>&1
  echo "head weaker than $PREV: $(grep -c -E '^UNEXPLAINED' $OUT/vs-prev-weaker.log) cells | $(tail -n 4 $OUT/vs-prev-weaker.log | grep -E '^old ' | cut -c1-160)"
  python3 -I $ORCH/weaker_cells.py $S8/expect.py $NEW $ORCH/ref/guard-$PREV.py $ROWS $LISTS --list > $OUT/vs-prev-stronger.log 2>&1
  echo "$PREV weaker than the head: $(grep -c -E '^UNEXPLAINED' $OUT/vs-prev-stronger.log) cells | $(tail -n 4 $OUT/vs-prev-stronger.log | grep -E '^old ' | cut -c1-160)"
fi

echo
echo "== multi-line check, plain and wrappers"
zsh $ORCH/multiline-meta.sh $NEW $SHA > $OUT/multiline.log 2>&1
tail -n 6 $OUT/multiline.log | cut -c1-200
zsh $ORCH/multiline-meta.sh $NEW $SHA-wrap --wrappers > $OUT/multiline-wrap.log 2>&1
tail -n 4 $OUT/multiline-wrap.log | cut -c1-200

echo
echo "== two-guard rewriting check, 0.8.0 beside $SHA"
zsh $ORCH/rewrite-regress.sh $OLD $NEW $SHA > $ORCH/out-regress/$SHA.run.log 2>&1
cut -c1-220 $ORCH/out-regress/$SHA.run.log
python3 -I $ORCH/regress_list.py $ORCH/out-regress/$SHA --counts 2>&1 | cut -c1-200 | head -n 60
