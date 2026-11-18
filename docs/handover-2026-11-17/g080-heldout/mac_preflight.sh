#!/bin/sh
# A read-only look at what the steps of docs/HANDOVER-2026-11-18.md ("Next steps, on the Mac") need on the
# machine it runs on. It changes nothing, installs nothing and fetches nothing; it only says what is there.
# Its output names local paths and belongs to the session, not into a commit.
# usage: sh mac_preflight.sh
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="$(dirname "$HERE")"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)" || exit 1
say() { printf '%-38s %s\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "== tools"
say "python3" "$(python3 --version 2>&1)"
for TOOL in git uv ruff gh zsh; do
  if have "$TOOL"; then say "$TOOL" "$("$TOOL" --version 2>&1 | head -n 1)"; else say "$TOOL" "MISSING"; fi
done
for PY in 3.13 3.9; do
  if have uv && uv run --offline --no-project --with pytest --python "$PY" python -c "import pytest" >/dev/null 2>&1; then
    say "pytest on Python $PY, offline" "ok"
  else
    say "pytest on Python $PY, offline" "NOT AVAILABLE from the local cache (the suite script needs it)"
  fi
done

echo
echo "== the forge and the tracker"
if have gh && gh auth status >/dev/null 2>&1; then say "gh" "logged in"; else say "gh" "NOT logged in"; fi
if python3 "$REPO/tools/tracker/tracker.py" show 50 >/dev/null 2>&1; then
  say "tracker.py show 50" "ok"
else
  say "tracker.py show 50" "FAILS (review, new and the owner verbs will fail too)"
fi

echo
echo "== the repository"
say "this checkout" "$(git -C "$REPO" branch --show-current) at $(git -C "$REPO" rev-parse --short HEAD)"
for REV in e5826b7 6ff07cf dc5b393; do
  if git -C "$REPO" cat-file -e "$REV^{commit}" 2>/dev/null; then say "commit $REV" "here"; else say "commit $REV" "MISSING: git fetch origin"; fi
done
say "origin/main" "$(git -C "$REPO" rev-parse --short origin/main 2>/dev/null || echo unknown) (the merge of #54 is 6ff07cf)"
say "local main" "$(git -C "$REPO" rev-parse --short main 2>/dev/null || echo none)"
echo "worktrees:"
git -C "$REPO" worktree list
MAIN_CHECKOUT="$(git -C "$REPO" worktree list --porcelain | sed -n '1s/^worktree //p')"
say "guard of the main checkout" "$(python3 "$MAIN_CHECKOUT/tools/guard/guard.py" version 2>&1 | head -n 1)"
if [ -f "$MAIN_CHECKOUT/.claude/guard.local.json" ]; then
  say "guard.local.json there" "$(tr -d '\n' < "$MAIN_CHECKOUT/.claude/guard.local.json" | cut -c1-80)"
else
  say "guard.local.json there" "none: every edit under tools/guard/ will ask"
fi

echo
echo "== the kit on this branch"
for FILE in g070/replay.py g070/replay-selftest/selftest.jsonl g070/hooktime.py g070/timing.json g070/suite.sh \
  g080/expect.py g080/expect_files.py g080/item-b.md g080/item_cmd.py g080/brief-b.md g080/brief-b-review.md \
  g080-heldout/a_mac_closeout.sh g080-heldout/b_after_build.sh; do
  if [ -f "$KIT/$FILE" ]; then say "$FILE" "here"; else say "$FILE" "MISSING"; fi
done

echo
echo "== transcripts for the replay"
ROOT="$HOME/.claude/projects"
if [ -d "$ROOT" ]; then
  say "changed in the last 45 days" "$(find "$ROOT" -name '*.jsonl' -mtime -45 2>/dev/null | wc -l | tr -d ' ') files"
  say "all" "$(find "$ROOT" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ') files"
else
  say "$ROOT" "MISSING: nothing to replay on this machine"
fi
