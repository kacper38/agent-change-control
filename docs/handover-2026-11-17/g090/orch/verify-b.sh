#!/bin/zsh
# The orchestrating session's check of the commits of the build of groups B and C, without touching the
# worktree: the guard file of each commit is written to the scratch folder and the checkers load it from
# there. One line per commit; a commit checked before is read from its saved line.
# usage: zsh verify-b.sh            every commit of the branch since the base
#        zsh verify-b.sh <commit>   one commit, checked again
MAIN=<MAIN>
WT=$MAIN/.claude/worktrees/g090-bc
HK=$MAIN/.claude/worktrees/handover-1117/docs/handover-2026-11-17
PAD=<PAD>
S8=$PAD/bc/g080
H=$HK/g080-heldout
ORCH=$PAD/orch
BASE=769b9d2
OLD=$ORCH/ref/guard-0.8.0.py
ROWS=($S8/rows-b.txt $S8/rows-b4.txt $S8/rows-b4-az.txt $S8/rows-b5.txt $S8/rows-c.txt)
ALLOW=$ORCH/out/allow-c.txt
mkdir -p $ORCH/out
grep -E '^K[0-9]+ ' $S8/rows-c.txt > $ALLOW
grep -E '^HR ' $H/heldout-c.txt >> $ALLOW

check_one() {
  local SHA=$1
  local NEW=$ORCH/ref/guard-$SHA.py
  local OUT=$ORCH/out/$SHA
  mkdir -p $OUT
  git -C $WT show "${SHA}:tools/guard/guard.py" > $NEW || return 1
  local subject="$(git -C $WT log -1 --format=%s $SHA)"
  local gate="ok"
  python3 $WT/tools/commit_msg.py --range "${SHA}~1..${SHA}" > $OUT/gate.log 2>&1 || gate="REFUSED"
  local trailer="$(git -C $WT log -1 --format=%B $SHA | grep -i '^co-authored-by' | tail -n 1 | cut -c1-60)"
  local refs="$(git -C $WT log -1 --format=%B $SHA | grep -c -E 'Refs #57')"
  local changed="$(git -C $WT show --stat --format= $SHA | grep -c '|')"
  python3 -I $S8/expect.py $NEW $ROWS > $OUT/rows.log 2>&1
  local rows="$(tail -n 1 $OUT/rows.log | sed 's/total rows //')"
  local hold_red="$(grep -c -E '^RED [A-Z][st] ' $OUT/rows.log)"
  python3 -I $S8/expect_files.py $NEW $S8/rows-b5-files.txt > $OUT/files.log 2>&1
  local files="$(tail -n 1 $OUT/files.log | sed 's/total rows //')"
  local files_hold_red="$(grep -c -E '^RED Y[st] ' $OUT/files.log)"
  python3 -I $H/orch/weaker.py $S8/expect.py $OLD $NEW $ROWS $S8/rows-a.txt $S8/rows-a-added.txt \
    $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt $H/heldout-a.txt $H/heldout-b.txt \
    $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt $H/orch/noise.txt $H/orch/noise2.txt \
    $H/orch/plain-forms.txt --allow $ALLOW > $OUT/weaker.log 2>&1
  local weaker="exit $? $(tail -n 1 $OUT/weaker.log | sed 's/commands in context [0-9]* | //')"
  # the same cells, each laid beside the due row that asks for it (rows outside group C ask for some too)
  python3 -I $ORCH/weaker_cells.py $S8/expect.py $OLD $NEW $ROWS $S8/rows-a.txt $S8/rows-a-added.txt \
    $S8/rows-a-caps.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt $H/heldout-a.txt $H/heldout-b.txt \
    $H/heldout-b4.txt $H/heldout-b5.txt $H/heldout-c.txt $H/orch/noise.txt $H/orch/noise2.txt \
    $H/orch/plain-forms.txt --list > $OUT/weaker_cells.log 2>&1
  local cells="exit $? $(tail -n 3 $OUT/weaker_cells.log | sed -n '1p' | sed -E 's/^old .* \| (weaker [0-9]+)/\1/') || $(tail -n 2 $OUT/weaker_cells.log | tr '\n' ' ')"
  python3 -I $H/orch/weaker.py $S8/expect.py $OLD $NEW $H/orch/noise.txt $H/orch/noise2.txt \
    $H/orch/plain-forms.txt --stronger > $OUT/stronger.log 2>&1
  local stronger="$(tail -n 1 $OUT/stronger.log | sed -E 's/.*\| (stronger [0-9]+) \|.*/\1/')"
  local held=""
  for f in heldout-b heldout-b4 heldout-b5 heldout-c; do
    python3 -I $S8/expect.py $NEW $H/$f.txt > $OUT/$f.log 2>&1
    held="$held ${f#heldout-}: HR red $(grep -c -E '^RED HR ' $OUT/$f.log), HS red $(grep -c -E '^RED HS ' $OUT/$f.log);"
  done
  {
    echo "== $SHA $subject"
    echo "   gate $gate | Refs #57: $refs | files in commit: $changed | $trailer"
    echo "   rows: $rows | must-hold rows red: $hold_red"
    echo "   file rows: $files | must-hold file rows red: $files_hold_red"
    echo "   weaker than 0.8.0: $weaker"
    echo "   weaker cells by row: $cells"
    echo "   new prompts on the noise lists: $stronger"
    echo "   unseen:$held"
  } > $OUT/line.txt
}

if [ -n "$1" ]; then
  SHA=$(git -C $WT rev-parse --short "$1") || exit 1
  check_one $SHA
  cat $ORCH/out/$SHA/line.txt
  exit 0
fi
for SHA in $(git -C $WT rev-list --reverse --abbrev-commit --abbrev=7 "${BASE}..HEAD"); do
  [ -f $ORCH/out/$SHA/line.txt ] || check_one $SHA
  cat $ORCH/out/$SHA/line.txt
done
echo "worktree status: $(git -C $WT status --short | tr '\n' ';') | main checkout status: $(git -C $MAIN status --short | tr '\n' ';')"
