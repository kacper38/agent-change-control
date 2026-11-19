#!/bin/zsh
# The design probe of the review fixes (guard-proto2.py) against everything that is frozen: every row and file
# row, and the plain verdicts of every list beside the head it was made from, both ways (wanted: no difference).
# Nothing under test runs: every command is a string handed to rule functions.
# usage: zsh check-proto2.sh <head sha> [<probe file>] [<draft rows file>]
MAIN=<MAIN>
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
P=$ORCH/proto
SHA="$1"
HEAD=$ORCH/ref/guard-$SHA.py
NEW="${2:-$P/guard-proto2.py}"
DRAFT="$3"
[ -s $HEAD ] || { echo "usage: zsh check-proto2.sh <head sha> [<probe file>] [<draft rows file>]"; exit 2; }
ROWS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt $S8/rows-b-fix.txt
      $S8/rows-b-fix-add.txt $S8/rows-b-fix-add2.txt $S8/rows-b-fix-add3.txt $S8/rows-b-fix-add4.txt
      $S8/rows-b-fix-add5.txt $S8/rows-b-fix2.txt $S8/rows-b-fix2-add.txt $S8/rows-b-fix3.txt $S8/rows-b-fix4.txt
      $S8/rows-b-fix5.txt $S8/rows-b-fix6.txt)
LISTS=($S8/rows-a.txt $S8/rows-a-added.txt $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt
       $H/heldout-a.txt $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt
       $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt $ORCH/heldout-b-fix3.txt $ORCH/heldout-b-fix4.txt
       $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt)
LISTS+=($ORCH/probe-*.txt)
[ -n "$DRAFT" ] && LISTS+=($DRAFT)

python3 -I -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read()); print('the probe parses')" $NEW || exit 1
echo "-- every frozen row at the probe"
python3 -I $S8/expect.py $NEW $ROWS > $P/rows2.log 2>&1
echo "rows: $(tail -n 1 $P/rows2.log)"
grep -E '^RED ' $P/rows2.log | cut -c1-220 | head -n 20
python3 -I $S8/expect_files.py $NEW $S8/rows-b5-files.txt > $P/files2.log 2>&1
echo "file rows: $(tail -n 1 $P/files2.log)"
if [ -n "$DRAFT" ]; then
  echo "-- the draft rows: at the head, then at the probe"
  python3 -I $S8/expect.py $HEAD $DRAFT > $P/draft2.head.log 2>&1
  echo "head:  $(tail -n 1 $P/draft2.head.log)"; grep -E '^RED ' $P/draft2.head.log | cut -c1-220
  python3 -I $S8/expect.py $NEW $DRAFT > $P/draft2.probe.log 2>&1
  echo "probe: $(tail -n 1 $P/draft2.probe.log)"; grep -E '^RED ' $P/draft2.probe.log | cut -c1-220
fi
echo "-- plain verdicts, the probe beside the head, both ways"
python3 -I $ORCH/weaker_cells.py $S8/expect.py $HEAD $NEW $ROWS $LISTS --list > $P/vs-head-weaker2.log 2>&1
echo "probe weaker than the head: $(grep -c -E '^UNEXPLAINED' $P/vs-head-weaker2.log) cells | $(tail -n 4 $P/vs-head-weaker2.log | grep -E '^old ' | cut -c1-170)"
python3 -I $ORCH/weaker_cells.py $S8/expect.py $NEW $HEAD $ROWS $LISTS --list > $P/vs-head-stronger2.log 2>&1
echo "head weaker than the probe: $(grep -c -E '^UNEXPLAINED' $P/vs-head-stronger2.log) cells | $(tail -n 4 $P/vs-head-stronger2.log | grep -E '^old ' | cut -c1-170)"
