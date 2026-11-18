#!/bin/zsh
# After the engineer's build of groups B and C: state of the branch, both checkers, the unseen forms, nothing
# weaker than 0.8.0 outside group C's rows, the new prompts, the replay over real commands, the suite.
# DRAFT of 2026-11-18, written in a cloud session on the model of a_after_build.sh and not run yet: set the
# paths, then read each step's output before the next one is trusted. Reads and scratch logs only; commands
# under test are strings handed to rule functions.
# usage: zsh b_after_build.sh [nosuite]
SP=<SCRATCH>
S=$SP/g070
S8=$SP/g080
H=$SP/g080-heldout
MAIN=<REPO>
WT=$MAIN/.claude/worktrees/g090-bc
BASE=6ff07cf
OLD=$H/guard-0.8.0.py          # git -C $MAIN show $BASE:tools/guard/guard.py, written once by hand
NEW=$WT/tools/guard/guard.py
OUT=$H/after-b
ROWS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt)
mkdir -p $OUT

echo "== state"
git -C $WT log --oneline $BASE..HEAD
echo "worktree status: $(git -C $WT status --short | tr '\n' ';')"
echo "main checkout status: $(git -C $MAIN status --short | tr '\n' ';')"
git -C $WT diff --stat $BASE..HEAD | tail -8
grep -n '^VERSION' $NEW

echo; echo "== checkers"
python3 -I $S8/expect.py $NEW $ROWS --red > $OUT/rows.log 2>&1
echo "rows exit $? | $(tail -1 $OUT/rows.log)"
grep '^RED' $OUT/rows.log | head -25 | cut -c1-210
python3 -I $S8/expect_files.py $NEW $S8/rows-b5-files.txt --red > $OUT/files.log 2>&1
echo "file rows exit $? | $(tail -1 $OUT/files.log)"
grep '^RED' $OUT/files.log | head -15 | cut -c1-210

echo; echo "== unseen forms (HR due, HS must hold, HO observed)"
for f in heldout-b heldout-b4 heldout-b5; do
  python3 -I $S8/expect.py $NEW $H/$f.txt --red > $OUT/$f.log 2>&1
  echo "$f exit $? | $(tail -1 $OUT/$f.log)"
  python3 -I $S8/heldout_report.py $H/$f.txt $OUT/$f.log | cut -c1-210 | head -60
done

echo; echo "== weaker than 0.8.0 (allowed: the K rows of group C, nothing else)"
grep -E '^K[0-9]+ ' $S8/rows-c.txt > $OUT/allow-c.txt
python3 -I $H/orch/weaker.py $S8/expect.py $OLD $NEW $ROWS $S8/rows-a.txt $S8/rows-a-added.txt \
  $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt $H/heldout-a.txt $H/heldout-b.txt \
  $H/heldout-b4.txt $H/heldout-b5.txt $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt \
  --allow $OUT/allow-c.txt > $OUT/weaker.log 2>&1
echo "weaker exit $?"
tail -6 $OUT/weaker.log | cut -c1-210

echo; echo "== new prompts on everyday commands (stronger than 0.8.0 over the noise lists)"
python3 -I $H/orch/weaker.py $S8/expect.py $OLD $NEW $H/orch/noise.txt $H/orch/noise2.txt \
  $H/orch/plain-forms.txt --stronger > $OUT/stronger.log 2>&1
echo "stronger exit $?"
tail -12 $OUT/stronger.log | cut -c1-210

echo; echo "== capitals: plain form against the same form in capitals"
python3 -I $H/caps_pairs.py $NEW $S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b5.txt $H/heldout-b.txt \
  $H/heldout-b4.txt --show 40 > $OUT/caps_pairs.log 2>&1
echo "pairs exit $?"
tail -30 $OUT/caps_pairs.log | cut -c1-230

echo; echo "== replay over the real commands of 45 days (0.8.0 against the build): asks gone, asks new"
python3 -I $S/replay.py $OLD $NEW 45 > $OUT/replay.log 2>&1
echo "replay exit $?"
grep -E 'stronger:|weaker:|^=== ' $OUT/replay.log | cut -c1-200

if [ "$1" != "nosuite" ]; then
  echo; echo "== suite"
  sh $S/suite.sh $WT > $OUT/suite.log 2>&1
  echo "suite exit $?"
  tail -6 $OUT/suite.log
fi
