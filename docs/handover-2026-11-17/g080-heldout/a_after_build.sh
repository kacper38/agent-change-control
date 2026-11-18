#!/bin/zsh
# After the engineer's build of group A: state of the branch, both checkers, the unseen forms, the pair check for
# capitals, the replay over real commands, the suite. Reads and scratch logs only; commands under test are
# strings handed to rule functions.
# usage: zsh a_after_build.sh [nosuite]
SP=<SCRATCH>
S=$SP/g070
S8=$SP/g080
H=$SP/g080-heldout
MAIN=<REPO>
WT=$MAIN/.claude/worktrees/g080-a
OLD=$H/guard-0.7.1.py
NEW=$WT/tools/guard/guard.py
OUT=$H/after
mkdir -p $OUT

echo "== state"
git -C $WT log --oneline e5826b7..HEAD
echo "worktree status: $(git -C $WT status --short | tr '\n' ';')"
echo "main checkout status: $(git -C $MAIN status --short | tr '\n' ';')"
git -C $WT diff --stat e5826b7..HEAD | tail -8
grep -n '^VERSION' $NEW

echo; echo "== checkers"
python3 -I $S8/expect.py $NEW $S8/rows-a.txt $S8/rows-a-added.txt $S8/rows-a-caps.txt --red > $OUT/rows.log 2>&1
echo "rows exit $? | $(tail -1 $OUT/rows.log)"
grep '^RED' $OUT/rows.log | head -25 | cut -c1-210
python3 -I $S8/expect_files.py $NEW $S8/rows-a-files.txt --red > $OUT/files.log 2>&1
echo "file rows exit $? | $(tail -1 $OUT/files.log)"
grep '^RED' $OUT/files.log | head -15 | cut -c1-210

echo; echo "== unseen forms of the frozen scope"
python3 -I $S8/expect.py $NEW $H/heldout-a.txt --red > $OUT/heldout-a.log 2>&1
echo "exit $? | $(tail -1 $OUT/heldout-a.log)"
python3 -I $S8/heldout_report.py $H/heldout-a.txt $OUT/heldout-a.log | cut -c1-210 | head -70
python3 -I $H/heldout_fed.py $OLD $NEW > $OUT/heldout_fed.log 2>&1
echo "fed exit $?"
tail -8 $OUT/heldout_fed.log | cut -c1-210

echo; echo "== capitals: plain form against the same form in capitals"
python3 -I $H/caps_pairs.py $NEW $S8/rows-a.txt $S8/rows-a-added.txt $H/heldout-a.txt $S8/rows-b.txt $H/heldout-b.txt \
  --show 40 > $OUT/caps_pairs.log 2>&1
echo "pairs exit $?"
tail -45 $OUT/caps_pairs.log | cut -c1-230

echo; echo "== replay over the real commands of 45 days (old 0.7.1 against the build)"
python3 -I $S/replay.py $OLD $NEW 45 > $OUT/replay.log 2>&1
echo "replay exit $?"
grep -E 'stronger:|^=== ' $OUT/replay.log | cut -c1-200

if [ "$1" != "nosuite" ]; then
  echo; echo "== suite"
  sh $S/suite.sh $WT > $OUT/suite.log 2>&1
  echo "suite exit $?"
  tail -6 $OUT/suite.log
fi
