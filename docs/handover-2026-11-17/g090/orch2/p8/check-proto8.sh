#!/bin/zsh
# The design probe of the eighth fix round against everything that is frozen: every row and file row, the draft
# rows at the head and at the probe, the plain verdicts of every list beside the head both ways, the planted
# breaks, the rewriting check over the draft rows, and the replay of the recorded calls beside the head.
# Nothing under test runs: every command is a string handed to rule functions. The logs stay in this folder.
# usage: zsh check-proto8.sh <head sha> <probe file> <draft rows file> [noreplay]
MAIN=<MAIN>
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
P=${0:A:h}/proto8
SHA="$1"; NEW="$2"; DRAFT="$3"
HEAD=$ORCH/ref/guard-$SHA.py
[ -s "$HEAD" ] && [ -s "$NEW" ] && [ -s "$DRAFT" ] || { echo "usage: zsh check-proto8.sh <head sha> <probe file> <draft rows file> [noreplay]"; exit 2; }
mkdir -p $P
ROWS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt $S8/rows-b-fix.txt
      $S8/rows-b-fix-add.txt $S8/rows-b-fix-add2.txt $S8/rows-b-fix-add3.txt $S8/rows-b-fix-add4.txt
      $S8/rows-b-fix-add5.txt $S8/rows-b-fix2.txt $S8/rows-b-fix2-add.txt $S8/rows-b-fix3.txt $S8/rows-b-fix4.txt
      $S8/rows-b-fix5.txt $S8/rows-b-fix6.txt $S8/rows-b-fix7.txt)
LISTS=($S8/rows-a.txt $S8/rows-a-added.txt $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt
       $H/heldout-a.txt $H/heldout-b.txt $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt
       $ORCH/heldout-b-fix.txt $ORCH/heldout-b-fix2.txt $ORCH/heldout-b-fix3.txt $ORCH/heldout-b-fix4.txt
       $H/orch/noise.txt $H/orch/noise2.txt $H/orch/plain-forms.txt)
LISTS+=($ORCH/probe-*.txt)
LISTS+=($DRAFT)

python3 -I -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read()); print('the probe parses')" $NEW || exit 1
echo "probe sha256 $(shasum -a 256 $NEW | cut -c1-16) | draft rows sha256 $(shasum -a 256 $DRAFT | cut -c1-16), $(grep -c -v -E '^(#|$)' $DRAFT) rows, $(grep -c '' $DRAFT) lines"
ruff check $NEW | tail -n 2
echo "-- every frozen row at the probe"
python3 -I $S8/expect.py $NEW $ROWS > $P/rows.log 2>&1
echo "rows: $(tail -n 1 $P/rows.log)"
grep -E '^RED ' $P/rows.log | cut -c1-220 | head -n 20
python3 -I $S8/expect_files.py $NEW $S8/rows-b5-files.txt > $P/files.log 2>&1
echo "file rows: $(tail -n 1 $P/files.log)"
echo "-- the draft rows: at 0.8.0, at the head, at the probe"
python3 -I $S8/expect.py $ORCH/ref/guard-0.8.0.py $DRAFT > $P/draft.080.log 2>&1
echo "0.8.0: $(tail -n 1 $P/draft.080.log)"
python3 -I $S8/expect.py $HEAD $DRAFT > $P/draft.head.log 2>&1
echo "head:  $(tail -n 1 $P/draft.head.log)"
python3 -I $S8/expect.py $NEW $DRAFT > $P/draft.probe.log 2>&1
echo "probe: $(tail -n 1 $P/draft.probe.log)"; grep -E '^RED ' $P/draft.probe.log | cut -c1-220
echo "-- plain verdicts, the probe beside the head, both ways"
python3 -I $ORCH/weaker_cells.py $S8/expect.py $HEAD $NEW $ROWS $LISTS --list > $P/vs-head-weaker.log 2>&1
echo "probe weaker than the head: $(grep -c -E '^UNEXPLAINED' $P/vs-head-weaker.log) cells | $(tail -n 4 $P/vs-head-weaker.log | grep -E '^old ' | cut -c1-170)"
python3 -I $ORCH/weaker_cells.py $S8/expect.py $NEW $HEAD $ROWS $LISTS --list > $P/vs-head-stronger.log 2>&1
echo "head weaker than the probe: $(grep -c -E '^UNEXPLAINED' $P/vs-head-stronger.log) cells | $(tail -n 4 $P/vs-head-stronger.log | grep -E '^old ' | cut -c1-170)"
echo "-- planted breaks at the probe, judged by the draft rows"
python3 -u -I $ORCH/proto/mutate_probe.py $NEW ${0:A:h}/mutations_proto8.py $S8/expect.py $P/mut $DRAFT > $P/mut.log 2>&1
echo "exit $? | $(tail -n 1 $P/mut.log)"
grep -E '^(SURVIVED|NOT APPLIED|BROKEN)' $P/mut.log | cut -c1-200
echo "-- the rewriting check over the draft rows at the probe"
python3 -u -I $S8/rewrite_check.py $S8/expect.py $S8/rewrite_readers.py $NEW $P/rewrite8.json $DRAFT > $P/rewrite8.log 2>&1
grep -E '^(weaker cells|crashes)' $P/rewrite8.log | cut -c1-200
python3 -I $S8/rewrite_list.py $P/rewrite8.json 2>&1 | head -n 6 | cut -c1-200
if [ "$4" != "noreplay" ]; then
  echo "-- the replay of the recorded calls, the head against the probe"
  zsh $ORCH/replay-pair.sh $HEAD $NEW proto8 45
fi
