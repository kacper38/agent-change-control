#!/bin/zsh
# The design probe against everything that is frozen: the draft rows of the addendum at three guard files, and
# every frozen row, unseen-forms list and noise list at the probe. Nothing under test runs.
# usage: zsh check-proto.sh <draft rows file>
MAIN=<MAIN>
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
P=$ORCH/proto
DRAFT="$1"
[ -f "$DRAFT" ] || { echo "usage: zsh check-proto.sh <draft rows file>"; exit 2; }
OLD=$ORCH/ref/guard-0.8.0.py
HEAD=$ORCH/ref/guard-d2ecce7.py
NEW=$P/guard-proto.py
ROWS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt $S8/rows-b-fix.txt $S8/rows-b-fix-add.txt $S8/rows-b-fix-add2.txt
      $S8/rows-b-fix-add3.txt $S8/rows-b-fix-add4.txt $S8/rows-b-fix-add5.txt $S8/rows-b-fix2.txt)

echo "-- the draft rows"
for pair in "0.8.0:$OLD" "head:$HEAD" "probe:$NEW"; do
  name=${pair%%:*}; file=${pair#*:}
  python3 -I $S8/expect.py $file $DRAFT > $P/draft.$name.log 2>&1
  echo "$name: $(tail -n 1 $P/draft.$name.log) | red by id: $(grep -E '^RED ' $P/draft.$name.log | awk '{print $2}' | sort | uniq -c | tr '\n' ' ')"
done
echo "due rows that hold at the head (should be none):"
python3 -I $S8/expect.py $HEAD $DRAFT 2>&1 | grep -E '^(F(37|38|39|40)) ' | head -n 5
grep -E '^(F37|F38|F39|F40) ' $DRAFT | wc -l | sed 's/^ */due rows in the draft: /'
echo "Fs rows red at the head:"; grep -E '^RED Fs ' $P/draft.head.log | cut -c1-200
echo "rows red at the probe:"; grep -E '^RED ' $P/draft.probe.log | cut -c1-220
echo "F37 rows red at 0.8.0 (a regression row holds there):"; grep -E '^RED F37 ' $P/draft.0.8.0.log | cut -c1-200

echo
echo "-- every frozen row at the probe"
python3 -I $S8/expect.py $NEW $ROWS > $P/rows.log 2>&1
echo "rows: $(tail -n 1 $P/rows.log)"
grep -E '^RED ' $P/rows.log | cut -c1-220 | head -n 20
python3 -I $S8/expect_files.py $NEW $S8/rows-b5-files.txt > $P/files.log 2>&1
echo "file rows: $(tail -n 1 $P/files.log)"

echo
echo "-- unseen forms at the probe (HR due, HS must hold), beside the head"
for f in $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt $ORCH/heldout-b-fix3.txt; do
  name=${f:t:r}
  python3 -I $S8/expect.py $NEW $f > $P/$name.log 2>&1
  python3 -I $S8/expect.py $HEAD $f > $P/$name.head.log 2>&1
  echo "$name: probe red $(grep -c -E '^RED ' $P/$name.log) | head red $(grep -c -E '^RED ' $P/$name.head.log)"
  grep -E '^RED ' $P/$name.log | cut -c1-200 > $P/$name.red
  grep -E '^RED ' $P/$name.head.log | cut -c1-200 > $P/$name.head.red
  diff $P/$name.head.red $P/$name.red | grep -E '^[<>]' | cut -c1-220
done

echo
echo "-- new prompts on the noise lists: the probe beside the head, then beside 0.8.0"
python3 -I $H/orch/weaker.py $S8/expect.py $HEAD $NEW $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt --stronger > $P/stronger-head.log 2>&1
tail -n 1 $P/stronger-head.log | cut -c1-200
python3 -I $H/orch/weaker.py $S8/expect.py $OLD $NEW $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt --stronger > $P/stronger-old.log 2>&1
tail -n 1 $P/stronger-old.log | cut -c1-200
