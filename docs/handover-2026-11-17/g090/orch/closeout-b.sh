#!/bin/zsh
# Replay and hook timing for the build of guard 0.9.0 (groups B and C), on the model of a_mac_closeout.sh:
# guard 0.8.0 (the base of the branch) against the head of the build branch, over the recorded tool calls of
# 45 days, boundary own and client. Nothing under test is run: the tools hand each recorded call to the rule
# functions. The logs hold real commands of real work and stay in this scratch folder; what this script prints
# holds no command text, no branch name and no path of another repository.
# usage: zsh closeout-b.sh [days] [notime]
DAYS="${1:-45}"
PAD=<PAD>
ORCH=$PAD/orch
S=$PAD/bc/g070
MAIN=<MAIN>
WT=$MAIN/.claude/worktrees/g090-bc
H=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17/g080-heldout
HEADSHA=$(git -C $WT rev-parse --short HEAD)
OUT=$ORCH/closeout-b/$HEADSHA
mkdir -p $OUT $ORCH/ref
V071=$ORCH/ref/guard-0.7.1.py
OLD=$ORCH/ref/guard-0.8.0.py
NEW=$ORCH/ref/guard-$HEADSHA.py
[ -s $V071 ] || git -C $MAIN show "e5826b7:tools/guard/guard.py" > $V071
git -C $WT show "${HEADSHA}:tools/guard/guard.py" > $NEW
echo "== guards: old = base 769b9d2, new = build head $HEADSHA"
grep -n '^VERSION' $V071 $OLD $NEW | sed -e "s#$ORCH/ref/##"
echo "worktree status: $(git -C $WT status --short | tr '\n' ';')"

echo
echo "== self-test of the replay tool (0.7.1 against 0.8.0). Expected: stronger 5 occurrences in 3 distinct cells, weaker 0"
python3 -I $S/replay.py $V071 $OLD 36500 --root $S/replay-selftest --no-text > $OUT/selftest.log 2>&1
grep -E '^(tool calls|weaker|stronger):' $OUT/selftest.log
grep -q '^stronger: 5 occurrences in 3 distinct cells' $OUT/selftest.log || { echo "the self-test failed: do not trust the replay below"; exit 1; }

echo
echo "== time span of the replayed transcripts"
python3 -I $H/orch/closeout_window.py $S $DAYS 2>&1 | tail -n 12

for B in own client; do
  echo
  echo "== replay over the recorded calls of $DAYS days, 0.8.0 against $HEADSHA, boundary $B"
  python3 -I $S/replay.py $OLD $NEW $DAYS --boundary $B --no-text --log $OUT/replay-$B.jsonl > $OUT/replay-$B.log 2> $OUT/replay-$B.err
  echo "replay exit $? (0: nothing weaker, 1: something weaker) | stderr lines $(grep -c '' $OUT/replay-$B.err)"
  grep -E '^(transcripts|tool calls|guards|weaker|stronger|crash)' $OUT/replay-$B.log
  sed -n '/^=== weaker per rule/,/^=== /p' $OUT/replay-$B.log | head -n 30
  sed -n '/^=== stronger per rule/,/^=== stronger, by/p' $OUT/replay-$B.log | head -n 40
done

echo
echo "== detail of every changed cell (local file, holds command text)"
python3 -I $H/orch/closeout_detail.py $S $OLD $NEW $DAYS $OUT/detail.json > $OUT/detail.log 2> $OUT/detail.err
echo "detail exit $? | stderr lines $(grep -c '' $OUT/detail.err)"
grep -E '^(transcripts|== boundary|non-silent|rule \||[a-z-]+ \| (ask|deny) \|)' $OUT/detail.log

if [ "$2" != "notime" ]; then
  echo
  echo "== hook timing through the real entry point, median of five runs, 0.8.0 and $HEADSHA"
  python3 -I $S/hooktime.py $ORCH/timing-b.json $OLD $NEW > $OUT/hooktime.log 2>&1
  echo "hooktime exit $?"
  sed -e "s#$ORCH/ref/##" $OUT/hooktime.log
fi
