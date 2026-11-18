#!/bin/sh
# Close-out checks for tracker item #50 (guard 0.8.0, group A) on the owner's machine, after the merge of pull
# request #54: the replay over the real commands of 45 days (criterion 6) and the hook timing. It needs only
# this repository with the two commits below fetched. It writes nothing into a checkout: the two guard copies
# and all logs go to the folder given as the first argument, which must lie outside the repository. Nothing
# under test is run: the tools hand each recorded call to the rule functions.
# The logs hold real commands of real work. They stay in that folder; numbers may go into a commit.
# usage: sh a_mac_closeout.sh <scratch folder outside the repository> [days]
set -u
OUT="${1:?usage: sh a_mac_closeout.sh <scratch folder outside the repository> [days]}"
DAYS="${2:-45}"
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="$(dirname "$HERE")"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)" || exit 1
OLD_REV=e5826b7   # main before the merge: guard 0.7.1
NEW_REV=6ff07cf   # the merge commit of pull request #54: guard 0.8.0
case "$OUT" in
  "$REPO"|"$REPO"/*) echo "the scratch folder must lie outside the repository"; exit 1 ;;
esac
mkdir -p "$OUT" || exit 1
for REV in "$OLD_REV" "$NEW_REV"; do
  git -C "$REPO" cat-file -e "$REV^{commit}" 2>/dev/null || { echo "commit $REV is not here: run git fetch origin first"; exit 1; }
done
OLD="$OUT/guard-0.7.1.py"
NEW="$OUT/guard-0.8.0.py"
git -C "$REPO" show "$OLD_REV:tools/guard/guard.py" > "$OLD" || exit 1
git -C "$REPO" show "$NEW_REV:tools/guard/guard.py" > "$NEW" || exit 1
echo "== guards"
grep -n '^VERSION' "$OLD" "$NEW"

echo
echo "== self-test of the replay tool. Expected: 7 tool calls, weaker 0, stronger 5 occurrences in 3 distinct cells"
python3 -I "$KIT/g070/replay.py" "$OLD" "$NEW" 36500 --root "$KIT/g070/replay-selftest" --no-text > "$OUT/selftest.log" 2>&1
grep -E '^(tool calls|weaker|stronger):' "$OUT/selftest.log"
grep -q '^stronger: 5 occurrences in 3 distinct cells' "$OUT/selftest.log" || { echo "the self-test failed: do not trust the replay below"; exit 1; }

echo
echo "== replay over the real commands of $DAYS days, 0.7.1 against 0.8.0, boundary own"
python3 -I "$KIT/g070/replay.py" "$OLD" "$NEW" "$DAYS" --log "$OUT/replay-own.jsonl" > "$OUT/replay-own.log" 2> "$OUT/replay-own.err"
echo "replay exit $? (0: nothing weaker, 1: something weaker)"
grep -E '^(transcripts|tool calls|guards|weaker|stronger|crash)' "$OUT/replay-own.log"
sed -n '/^=== stronger per rule/,/^=== stronger, by/p' "$OUT/replay-own.log" | head -40

echo
echo "== the same calls judged inside a client boundary (egress-guard speaks only there)"
python3 -I "$KIT/g070/replay.py" "$OLD" "$NEW" "$DAYS" --boundary client --log "$OUT/replay-client.jsonl" > "$OUT/replay-client.log" 2> "$OUT/replay-client.err"
echo "replay exit $?"
grep -E '^(weaker|stronger|crash)' "$OUT/replay-client.log"
sed -n '/^=== stronger per rule/,/^=== stronger, by/p' "$OUT/replay-client.log" | head -40

echo
echo "== hook timing through the real entry point, median of five runs, before and after"
python3 -I "$KIT/g070/hooktime.py" "$KIT/g070/timing.json" "$OLD" "$NEW" > "$OUT/hooktime.log" 2>&1
sed -e "s#$OUT/##" "$OUT/hooktime.log"

echo
echo "== left to do by hand"
echo "1. read $OUT/replay-own.log and replay-client.log: each stronger call is a prompt or a denial 0.8.0 adds;"
echo "   say per kind whether it is wanted. A weaker cell is a defect and needs a fix first."
echo "2. python3 tools/tracker/tracker.py review 50 --pr 54"
echo "3. the numbers, not the command text, go into a DECISIONS.md line (docs/HANDOVER-2026-11-18.md, Next steps)"
