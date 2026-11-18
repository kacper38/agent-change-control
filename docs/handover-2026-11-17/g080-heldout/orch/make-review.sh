#!/bin/sh
# Write the material a reviewer brief names into the reviewer's scratch folder: the old guard, the diff of
# the guard, the commit list and the file statistics of the build branch against its base.
# usage: sh make-review.sh
# The defaults are those of group A. For groups B and C:
#   WT_NAME=g090-bc BASE=6ff07cf OLD_NAME=guard-0.8.0.py RDIR=rb sh make-review.sh
SP="${SP:?set SP to the scratch folder of the session}"
REPO="${REPO:?set REPO to the checkout on the handover branch}"
WT_NAME="${WT_NAME:-g080-a}"
BASE="${BASE:-e5826b7}"
OLD_NAME="${OLD_NAME:-guard-0.7.1.py}"
RDIR="${RDIR:-ra}"
WT=$REPO/.claude/worktrees/$WT_NAME
S8="${S8:-$SP/handover/g080}"
mkdir -p "$S8/review/$RDIR"
git -C "$REPO" show "$BASE:tools/guard/guard.py" > "$S8/review/$OLD_NAME"
git -C "$WT" diff "$BASE..HEAD" -- tools/guard/guard.py > "$S8/review/guard.diff"
git -C "$WT" diff --stat "$BASE..HEAD" > "$S8/review/stat.txt"
git -C "$WT" log --reverse --format='%h %s' "$BASE..HEAD" > "$S8/review/commits.txt"
echo "head $(git -C "$WT" rev-parse --short HEAD) | worktree status: $(git -C "$WT" status --short | wc -l) changed files"
wc -l "$S8/review/$OLD_NAME" "$S8/review/guard.diff" "$S8/review/commits.txt"
cat "$S8/review/commits.txt"
tail -n 1 "$S8/review/stat.txt"
