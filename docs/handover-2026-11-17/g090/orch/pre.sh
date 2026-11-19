#!/bin/zsh
# Preflight for the build of groups B and C (guard 0.9.0, item 57): scratch copies for the engineer, the hashes
# of the row files, the old guard out of git, the package checks, the tracker's state. Reads and scratch writes.
MAIN=<MAIN>
HW=$MAIN/.claude/worktrees/handover-1117
HK=$HW/docs/handover-2026-11-17
PAD=<PAD>
SP=$PAD/bc
ORCH=$PAD/orch
BASE=769b9d2
mkdir -p $SP $ORCH/ref $ORCH/out

echo "== handover worktree"
echo "head $(git -C $HW rev-parse --short HEAD) | changed files: $(git -C $HW status --short | wc -l | tr -d ' ')"

echo "== copies for the engineer (g070, g080; never g080-heldout)"
[ -d $SP/g070 ] || command cp -R $HK/g070 $SP/g070
[ -d $SP/g080 ] || command cp -R $HK/g080 $SP/g080
ls $SP
for f in rows-b.txt rows-b4.txt rows-b4-az.txt rows-b5.txt rows-b5-files.txt rows-c.txt expect.py expect_files.py probe.py; do
  if cmp -s $HK/g080/$f $SP/g080/$f; then
    echo "same $f $(shasum -a 256 $SP/g080/$f | cut -c1-16)"
  else
    echo "DIFF $f"
  fi
done

echo "== old guard"
git -C $MAIN show "${BASE}:tools/guard/guard.py" > $ORCH/ref/guard-0.8.0.py   # braces: zsh reads $BASE:t as a modifier
git -C $MAIN show ec23d5d:tools/guard/guard.py > $ORCH/ref/guard-ec23d5d.py
cmp -s $ORCH/ref/guard-ec23d5d.py $ORCH/ref/guard-0.8.0.py && echo "guard.py at $BASE equals the one at ec23d5d"
grep -n '^VERSION' $ORCH/ref/guard-0.8.0.py
wc -l $ORCH/ref/guard-0.8.0.py

echo "== item check (the item's table and criterion 14 against the files, measured on 0.8.0)"
python3 -I $HK/g080/item_check.py $HK $ORCH/ref/guard-0.8.0.py
echo "item_check exit $?"

echo "== the line numbers section 4 of the brief names"
python3 -I $HK/g080-heldout/orch/brief_lines.py $HK/g080/brief-b.md $ORCH/ref/guard-0.8.0.py | tail -3

echo "== tracker"
T=$MAIN/.claude/worktrees/g080-closeout/tools/tracker/tracker.py
echo "-- in progress:"
python3 $T list --status in-progress
echo "-- 57:"
python3 $T show 57 | grep -v -E '^  [0-9]+\. \[' | cut -c1-400
echo "-- 50:"
python3 $T show 50 | grep -v -E '^  [0-9]+\. \[' | cut -c1-400
