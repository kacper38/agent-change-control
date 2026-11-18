#!/bin/sh
# The orchestrating session's check of one commit of the fix pass. Runs verify-commit.sh, then the rows of the
# fix pass, its unseen forms, and a comparison over every command at hand: nothing may answer weaker than at
# guard 0.7.1, and nothing weaker than at the build head ae5361b apart from the forms of finding R11.
# usage: sh verify-fix.sh <commit>
SP="${SP:?set SP to the scratch folder of the session}"
REPO="${REPO:?set REPO to the checkout on the handover branch}"
WT=$REPO/.claude/worktrees/g080-a
H=$REPO/docs/handover-2026-11-17
S8=$SP/handover/g080
SHA=$(git -C "$WT" rev-parse --short "$1") || exit 1
NEW=$SP/ref/guard-$SHA.py
OUT=$SP/out/$SHA
sh "$SP/orch/verify-commit.sh" "$SHA" | grep -v -E '^(BELOW|payloads|data  |limit |guards)'

echo "== fix rows"
python3 -I "$H/g080/expect.py" "$NEW" "$S8/rows-a-fix.txt" > "$OUT/fix.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/fix.log") | As red: $(grep -c -E '^RED As ' "$OUT/fix.log")"
grep -E '^RED' "$OUT/fix.log" | cut -c1-200 | head -12
python3 -I "$H/g080/expect_files.py" "$NEW" "$S8/rows-a-fix-files.txt" > "$OUT/fix-files.log" 2>&1
echo "file rows: exit $? | $(tail -n 1 "$OUT/fix-files.log")"
grep -E '^RED' "$OUT/fix-files.log" | cut -c1-200 | head -6

echo "== unseen forms of the fix pass"
python3 -I "$H/g080/expect.py" "$NEW" "$SP/orch/heldout-a-fix.txt" > "$OUT/heldout-fix.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/heldout-fix.log") | HR red: $(grep -c -E '^RED HR ' "$OUT/heldout-fix.log") | HS red: $(grep -c -E '^RED HS ' "$OUT/heldout-fix.log")"
grep -E '^RED (HR|HS)' "$OUT/heldout-fix.log" | cut -c1-200 | head -16

FILES="$H/g080/rows-a.txt $H/g080/rows-a-added.txt $H/g080/rows-a-caps.txt $H/g080/rows-b.txt $H/g080/rows-c.txt $H/g080/rows-b4.txt $H/g080/rows-b4-az.txt $H/g080-heldout/heldout-a.txt $H/g080-heldout/heldout-b.txt $H/g080-heldout/heldout-b4.txt $H/g080/probe-b4-net.txt $H/g080/probe-b4-graphql.txt $H/g080/probe-b4-main.txt $H/g080/probe-b4-vault.txt $H/g080/probe-b4-az.txt $S8/rows-a-fix.txt $SP/orch/heldout-a-fix.txt $SP/orch/review-check.txt $SP/orch/plain-forms.txt $SP/orch/open-questions.txt"
for f in "$S8"/review/ra/*.txt "$S8"/eng/*.txt; do
  case "$f" in *msg*) ;; *) [ -f "$f" ] && FILES="$FILES $f" ;; esac
done
echo "== nothing weaker than guard 0.7.1"
python3 -I "$SP/orch/weaker.py" "$H/g080/expect.py" "$SP/ref/guard-0.7.1.py" "$NEW" $FILES > "$OUT/weaker-071.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/weaker-071.log")"
grep -E '^(WEAKER|CRASH)' "$OUT/weaker-071.log" | cut -c1-220 | head -12
echo "== nothing weaker than the build head ae5361b (finding R11 apart)"
python3 -I "$SP/orch/weaker.py" "$H/g080/expect.py" "$SP/ref/guard-ae5361b.py" "$NEW" $FILES --allow "$SP/orch/allow-a11.txt" > "$OUT/weaker-build.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/weaker-build.log")"
grep -E '^(WEAKER|CRASH)' "$OUT/weaker-build.log" | cut -c1-220 | head -12
