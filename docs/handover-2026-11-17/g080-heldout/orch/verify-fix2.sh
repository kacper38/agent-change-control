#!/bin/sh
# The orchestrating session's check of one commit of the second fix round. Runs verify-fix.sh, then the rows of
# the second round, its unseen forms, and two comparisons over every command at hand, noise forms included:
#   against the fix head 894b8cc: nothing weaker but the noise that is taken back, and nothing stronger at all;
#   against the build head ae5361b: nothing stronger but the forms of the fix pass.
# usage: sh verify-fix2.sh <commit>
SP="${SP:?set SP to the scratch folder of the session}"
REPO="${REPO:?set REPO to the checkout on the handover branch}"
WT=$REPO/.claude/worktrees/g080-a
H=$REPO/docs/handover-2026-11-17
S8=$SP/handover/g080
SHA=$(git -C "$WT" rev-parse --short "$1") || exit 1
NEW=$SP/ref/guard-$SHA.py
OUT=$SP/out/$SHA
sh "$SP/orch/verify-fix.sh" "$SHA" | grep -v -E '^   g080'

echo "== rows of the second round"
python3 -I "$H/g080/expect.py" "$NEW" "$S8/rows-a-fix2.txt" > "$OUT/fix2.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/fix2.log") | Ys red: $(grep -c -E '^RED Ys ' "$OUT/fix2.log")"
grep -E '^RED' "$OUT/fix2.log" | cut -c1-200 | head -10
echo "== unseen forms of the second round"
python3 -I "$H/g080/expect.py" "$NEW" "$SP/orch/heldout-a-fix2.txt" > "$OUT/heldout-fix2.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/heldout-fix2.log") | HR red: $(grep -c -E '^RED HR ' "$OUT/heldout-fix2.log") | HS red: $(grep -c -E '^RED HS ' "$OUT/heldout-fix2.log")"
grep -E '^RED' "$OUT/heldout-fix2.log" | cut -c1-200 | head -10

FILES="$H/g080/rows-a.txt $H/g080/rows-a-added.txt $H/g080/rows-a-caps.txt $H/g080/rows-b.txt $H/g080/rows-c.txt $H/g080/rows-b4.txt $H/g080/rows-b4-az.txt $H/g080-heldout/heldout-a.txt $H/g080-heldout/heldout-b.txt $H/g080-heldout/heldout-b4.txt $H/g080/probe-b4-net.txt $H/g080/probe-b4-graphql.txt $H/g080/probe-b4-main.txt $H/g080/probe-b4-vault.txt $H/g080/probe-b4-az.txt $S8/rows-a-fix.txt $S8/rows-a-fix2.txt $SP/orch/heldout-a-fix.txt $SP/orch/heldout-a-fix2.txt $SP/orch/review-check.txt $SP/orch/plain-forms.txt $SP/orch/open-questions.txt $SP/orch/noise.txt $SP/orch/noise2.txt"
for f in "$S8"/review/ra/*.txt "$S8"/eng/*.txt; do
  case "$f" in *msg*) ;; *) [ -f "$f" ] && FILES="$FILES $f" ;; esac
done
ALLOW2="--allow $S8/rows-a-fix2.txt --allow $SP/orch/heldout-a-fix2.txt --allow $SP/orch/noise.txt --allow $S8/review/ra/s1.txt --allow $S8/review/ra/chains.txt"
echo "== against the fix head 894b8cc: weaker (the noise taken back is allowed)"
python3 -I "$SP/orch/weaker.py" "$H/g080/expect.py" "$SP/ref/guard-894b8cc.py" "$NEW" $FILES $ALLOW2 > "$OUT/weaker-fix.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/weaker-fix.log")"
grep -E '^(WEAKER|CRASH)' "$OUT/weaker-fix.log" | cut -c1-220 | head -10
echo "== against the fix head 894b8cc: stronger (nothing is expected)"
python3 -I "$SP/orch/weaker.py" "$H/g080/expect.py" "$SP/ref/guard-894b8cc.py" "$NEW" $FILES --stronger > "$OUT/stronger-fix.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/stronger-fix.log")"
grep -E '^(STRONGER|CRASH)' "$OUT/stronger-fix.log" | cut -c1-220 | head -10
echo "== against the build head ae5361b: stronger outside the forms of the fix pass"
ALLOWB="--allow $S8/rows-a-fix.txt --allow $SP/orch/heldout-a-fix.txt --allow $SP/orch/review-check.txt"
for f in "$S8"/review/ra/l*.txt; do ALLOWB="$ALLOWB --allow $f"; done
python3 -I "$SP/orch/weaker.py" "$H/g080/expect.py" "$SP/ref/guard-ae5361b.py" "$NEW" $FILES $ALLOWB --stronger > "$OUT/stronger-build.log" 2>&1
echo "exit $? | $(tail -n 1 "$OUT/stronger-build.log")"
grep -E '^(STRONGER|CRASH)' "$OUT/stronger-build.log" | cut -c1-220 | head -14
