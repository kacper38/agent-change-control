#!/bin/sh
# The orchestrating session's check of one commit of the build branch, without touching the worktree: the
# guard file of that commit is written to the scratch folder and the checkers load it from there.
# usage: sh verify-commit.sh <commit>
SP="${SP:?set SP to the scratch folder of the session}"
REPO="${REPO:?set REPO to the checkout on the handover branch}"
WT=$REPO/.claude/worktrees/g080-a
H=$REPO/docs/handover-2026-11-17
OLD=$SP/ref/guard-0.7.1.py
SHA=$(git -C "$WT" rev-parse --short "$1") || exit 1
NEW=$SP/ref/guard-$SHA.py
OUT=$SP/out/$SHA
mkdir -p "$OUT"
git -C "$WT" show "$SHA:tools/guard/guard.py" > "$NEW" || exit 1

echo "== $SHA $(git -C "$WT" log -1 --format=%s "$SHA")"
git -C "$WT" show --stat --format='   author %an | %ad' --date=format:%H:%M "$SHA" | tail -n +1 | head -12
echo "== commit message gate"
python3 "$REPO/tools/commit_msg.py" --range "$SHA~1..$SHA"
git -C "$WT" log -1 --format=%B "$SHA" | tail -n 4

echo "== shell rows"
python3 -I "$H/g080/expect.py" "$NEW" "$H/g080/rows-a.txt" "$H/g080/rows-a-added.txt" "$H/g080/rows-a-caps.txt" > "$OUT/rows.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/rows.log")"
grep -E '^[A-Z][0-9a-z]: ' "$OUT/rows.log" | awk -F'[:|]' '{gsub(/ /,"",$1); split($4,a," "); if (a[2] != 0) printf "%s red %s; ", $1, a[2]} END {print ""}'
echo "rows that must keep holding and are red: $(grep -c -E '^RED (.s|Ct|Cs) ' "$OUT/rows.log")"
grep -E '^RED (.s|Ct|Cs) ' "$OUT/rows.log" | head -5 | cut -c1-220

echo "== file rows"
python3 -I "$H/g080/expect_files.py" "$NEW" "$H/g080/rows-a-files.txt" > "$OUT/files.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/files.log")"
echo "file rows that must keep holding and are red: $(grep -c -E '^RED (Ft|Fs) ' "$OUT/files.log")"

echo "== unseen forms of A"
python3 -I "$H/g080/expect.py" "$NEW" "$H/g080-heldout/heldout-a.txt" --red > "$OUT/heldout-a.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/heldout-a.log") | HS red: $(grep -c -E '^RED HS ' "$OUT/heldout-a.log")"
grep -E '^RED HS ' "$OUT/heldout-a.log" | head -5 | cut -c1-220

echo "== fed scripts, unseen forms (old 0.7.1 against this commit)"
python3 -I "$H/g080-heldout/heldout_fed.py" "$OLD" "$NEW" > "$OUT/heldout_fed.log" 2>&1
echo "exit $?"
tail -n 9 "$OUT/heldout_fed.log" | cut -c1-200

echo "== rows of B and C that must keep holding"
for f in g080/rows-b.txt g080/rows-c.txt g080/rows-b4.txt g080/rows-b4-az.txt g080-heldout/heldout-b.txt g080-heldout/heldout-b4.txt; do
  python3 -I "$H/g080/expect.py" "$NEW" "$H/$f" > "$OUT/tmp.log" 2>&1
  echo "   $f: $(tail -n 1 "$OUT/tmp.log") | s-rows red $(grep -c -E '^RED [A-Z][0-9]*s ' "$OUT/tmp.log") | HS red $(grep -c -E '^RED HS ' "$OUT/tmp.log")"
done
