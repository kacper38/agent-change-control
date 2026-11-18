#!/bin/sh
# Write the material the reviewer brief names into the reviewer's scratch folder: the old guard, the diff of
# the guard, the commit list and the file statistics of the build branch against main.
# usage: sh make-review.sh
SP="${SP:?set SP to the scratch folder of the session}"
REPO="${REPO:?set REPO to the checkout on the handover branch}"
WT=$REPO/.claude/worktrees/g080-a
S8=$SP/handover/g080
BASE=e5826b7
mkdir -p "$S8/review/ra"
git -C "$REPO" show "$BASE:tools/guard/guard.py" > "$S8/review/guard-0.7.1.py"
git -C "$WT" diff "$BASE..HEAD" -- tools/guard/guard.py > "$S8/review/guard.diff"
git -C "$WT" diff --stat "$BASE..HEAD" > "$S8/review/stat.txt"
git -C "$WT" log --reverse --format='%h %s' "$BASE..HEAD" > "$S8/review/commits.txt"
echo "head $(git -C "$WT" rev-parse --short HEAD) | worktree status: $(git -C "$WT" status --short | wc -l) changed files"
wc -l "$S8/review/guard-0.7.1.py" "$S8/review/guard.diff" "$S8/review/commits.txt"
cat "$S8/review/commits.txt"
tail -n 1 "$S8/review/stat.txt"
