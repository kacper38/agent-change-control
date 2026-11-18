#!/bin/sh
# Checks of merged guard 0.8.0 on this machine, beside the close-out script: the time span of the replay, the
# acceptance rows of group A and the draft rows of groups B and C on the guard of main, and the lint and test
# suites of main on both CI Pythons, offline. Reads only; logs go to the folder given as the first argument.
# What it prints holds no command text and no path. Written on the owner's machine on 2026-11-18.
# usage: sh closeout_checks.sh <scratch folder outside the repository> <a worktree of main>
OUT="${1:?usage: sh closeout_checks.sh <scratch folder outside the repository> <a worktree of main>}"
WT="${2:?the second argument is a worktree of main}"
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
GUARD="$WT/tools/guard/guard.py"
mkdir -p "$OUT" || exit 1
echo "== main worktree: $(git -C "$WT" rev-parse --short HEAD) | guard $(python3 "$GUARD" version)"

echo
echo "== time span of the replayed transcripts"
python3 -I "$KIT/g080-heldout/orch/closeout_window.py" "$KIT/g070" 45

echo
echo "== rows of group A on the guard of main (all must hold)"
python3 -I "$KIT/g080/expect.py" "$GUARD" "$KIT/g080/rows-a.txt" "$KIT/g080/rows-a-added.txt" \
  "$KIT/g080/rows-a-caps.txt" "$KIT/g080/rows-a-fix.txt" "$KIT/g080/rows-a-fix2.txt" > "$OUT/rows-a-shell.log" 2>&1
echo "shell rows exit $? | $(tail -n 1 "$OUT/rows-a-shell.log")"
python3 -I "$KIT/g080/expect_files.py" "$GUARD" "$KIT/g080/rows-a-files.txt" "$KIT/g080/rows-a-fix-files.txt" \
  > "$OUT/rows-a-files.log" 2>&1
echo "file rows exit $? | $(tail -n 1 "$OUT/rows-a-files.log")"

echo
echo "== draft rows of groups B and C on the guard of main (red is due with the build; compare with item-b.md)"
for NAME in rows-b.txt rows-b4.txt rows-b4-az.txt rows-b5.txt rows-c.txt; do
  python3 -I "$KIT/g080/expect.py" "$GUARD" "$KIT/g080/$NAME" > "$OUT/$NAME.log" 2>&1
  echo "$NAME | sha256 $(shasum -a 256 "$KIT/g080/$NAME" | cut -c1-16) | $(tail -n 1 "$OUT/$NAME.log")"
done
python3 -I "$KIT/g080/expect_files.py" "$GUARD" "$KIT/g080/rows-b5-files.txt" > "$OUT/rows-b5-files.txt.log" 2>&1
echo "rows-b5-files.txt | sha256 $(shasum -a 256 "$KIT/g080/rows-b5-files.txt" | cut -c1-16) | $(tail -n 1 "$OUT/rows-b5-files.txt.log")"
for NAME in heldout-b.txt heldout-b4.txt heldout-b5.txt; do
  echo "$NAME | sha256 $(shasum -a 256 "$KIT/g080-heldout/$NAME" | cut -c1-16)"
done

echo
echo "== lint and test suites of main, both Pythons, offline"
sh "$KIT/g070/suite.sh" "$WT"
