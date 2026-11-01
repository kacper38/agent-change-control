#!/usr/bin/env bash
# tools/testguard/check-test-tampering.sh -- block changes that quietly weaken the test suite.
# Source: the private harness kit, harness/baseline/ci/guards/check-test-tampering.sh (harness v1, commit 4dd6956e).
# This copy adds pytest conventions (lines marked "pytest:"), a check for removed test functions, and a
# --worktree mode for the PostToolUse hook (tools/testguard/testguard.py). Plan step 3.7.
# Diff-aware: inspects only the change vs the PR base; pre-existing markers never fail.
#
#   1. ADDED focus/skip markers in test files                -> FAIL (no escape hatch: fix it)
#      JS: .only( .skip( xit( xdescribe( test.todo  in *.spec.* / *.test.*
#      pytest: @pytest.mark.skip / xfail, pytest.skip(, @unittest.skip, unittest.SkipTest
#              in test_*.py / *_test.py  (skipif / skipIf stay allowed: a conditional skip is visible by design)
#   2. Test file deleted or renamed out of the test glob     -> FAIL unless PR label `test-removal-ok`
#   3. pytest: a `def test_*` removed or renamed             -> FAIL unless PR label `test-removal-ok`
#   4. [skip ci] / [ci skip] / [no ci] in commits or PR title -> FAIL
#
# Usage: check-test-tampering.sh [--worktree]
#   default     compares merge-base(BASE, HEAD)..HEAD: committed changes (CI)
#   --worktree  compares merge-base(BASE, HEAD) with the working tree, so uncommitted edits count (hook);
#               never calls gh (no network from a hook): the label check degrades to WARN
# Env: BASE_REF (PR base branch, from github.base_ref), PR_LABELS (comma-separated
# label names), PR_TITLE, PR_NUMBER + GH_TOKEN (gh-CLI fallback; PR_NUMBER is
# required in CI, where the detached-HEAD checkout means gh cannot infer the PR).
# Without PR context the label check degrades to WARN so local runs stay useful.
# Exits 0 silently when nothing applies.
set -euo pipefail

WORKTREE=0
[ "${1:-}" = "--worktree" ] && WORKTREE=1

cd "$(git rev-parse --show-toplevel)"

BASE="${BASE_REF:-origin/main}"
# github.base_ref is a bare branch name; try the remote-tracking ref before giving up.
git rev-parse --verify --quiet "$BASE" >/dev/null || BASE="origin/${BASE}"
if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
  echo "check-test-tampering: cannot resolve base '${BASE}' (shallow clone? run: git fetch origin main)" >&2
  exit 1
fi

MB="$(git merge-base "$BASE" HEAD)"
if [ "$WORKTREE" -eq 0 ] && [ "$MB" = "$(git rev-parse HEAD)" ]; then
  exit 0 # nothing on top of base
fi
# Right-hand side of every diff: HEAD in CI, the working tree in the hook (git diff with one commit).
# Expanded unquoted on purpose: an empty TO must vanish, not become an empty argument.
TO=HEAD
[ "$WORKTREE" -eq 1 ] && TO=""

FAILED=0
fail() { printf 'FAIL(check-test-tampering): %s\n\n' "$1" >&2; FAILED=1; }
warn() { printf 'WARN(check-test-tampering): %s\n\n' "$1" >&2; }

# pytest: test file conventions, JS and Python
is_test_file() {
  case "$1" in
    *.spec.* | *.test.* | test_*.py | */test_*.py | *_test.py) return 0 ;;
  esac
  return 1
}

# has_label <name>: 0 = present, 1 = absent, 2 = unknown (no PR context available)
has_label() {
  local label="$1" labels
  if [ -n "${PR_LABELS:-}" ]; then
    case ",${PR_LABELS}," in
      *",${label},"*) return 0 ;;
      *) return 1 ;;
    esac
  fi
  if [ "$WORKTREE" -eq 0 ] && command -v gh >/dev/null 2>&1; then
    # PR_NUMBER matters in CI: the checkout is a detached HEAD, so a bare
    # `gh pr view` cannot infer the PR. Locally (no PR_NUMBER) gh infers from the branch.
    if labels="$(gh pr view ${PR_NUMBER:+"$PR_NUMBER"} --json labels --jq '.labels[].name' 2>/dev/null)"; then
      if printf '%s\n' "$labels" | grep -qxF "$label"; then return 0; fi
      return 1
    fi
  fi
  return 2
}

# In --worktree mode `git diff` does not see untracked files: a new test file with a marker,
# or a test moved into a file not yet added, would be missed. Emit a diff from nothing for each.
untracked_test_diffs() {
  [ "$WORKTREE" -eq 1 ] || return 0
  git ls-files --others --exclude-standard -- '*.spec.*' '*.test.*' 'test_*.py' '*/test_*.py' '*_test.py' \
    | while IFS= read -r f; do
        [ -f "$f" ] && { git diff --no-index --unified=0 --no-color /dev/null "$f" || true; }
      done
  return 0
}

# --- 1. focus/skip markers ADDED in test files ------------------------------
# shellcheck disable=SC2086
added_markers="$(
  { git diff --unified=0 --no-color "$MB" $TO -- '*.spec.*' '*.test.*' 'test_*.py' '*/test_*.py' '*_test.py'
    untracked_test_diffs; } \
    | awk '
        /^\+\+\+ / { file = substr($0, 7); next }
        /^@@ /     { split($3, a, ","); line = substr(a[1], 2) + 0; next }
        /^\+/ {
          text = substr($0, 2)
          if (text ~ /\.only\(|\.skip\(|(^|[^A-Za-z0-9_$])(xit|xdescribe)\(|test\.todo/ \
              || (text ~ /pytest\.mark\.(skip|xfail)/ && text !~ /pytest\.mark\.skipif/) \
              || text ~ /unittest\.SkipTest/)
            printf "    %s:%d: %s\n", file, line, text
          line++
        }
      '
)"
if [ -n "$added_markers" ]; then
  fail "focus/skip markers ADDED in test files:
${added_markers}
  Why: .only() makes CI run a subset forever; .skip()/xit/xdescribe/test.todo and pytest.mark.skip/xfail park tests indefinitely -- green CI stops meaning anything.
  How: remove the marker and make the test pass. To genuinely retire a test, delete it in a PR carrying the test-removal-ok label (or file a decision issue) with a reason."
fi

# --- 2. test files deleted or renamed out of the test glob ------------------
removed=""
# shellcheck disable=SC2086
while IFS=$'\t' read -r status old new; do
  case "$status" in
    D)
      if is_test_file "$old"; then removed="${removed}    ${old} (deleted)"$'\n'; fi
      ;;
    R*)
      if is_test_file "$old" && ! is_test_file "$new"; then
        removed="${removed}    ${old} -> ${new} (renamed out of the test glob; runner will no longer pick it up)"$'\n'
      fi
      ;;
  esac
done < <(git diff --name-status --find-renames "$MB" $TO)

# --- 3. pytest: test functions removed or renamed ---------------------------
# A `def test_*` that disappears from a test file and is not added back under the same name
# anywhere in the diff (moving a test between files is fine). Files deleted outright are
# reported by check 2, not here. In --worktree mode a test moved into a not-yet-added file
# counts as added back (untracked_test_diffs).
# shellcheck disable=SC2086
removed_funcs="$(
  { git diff --unified=0 --no-color "$MB" $TO -- 'test_*.py' '*/test_*.py' '*_test.py'; untracked_test_diffs; } \
    | awk '
        /^--- /    { file = substr($0, 7); skip = 0; next }
        /^\+\+\+ / { if ($0 == "+++ /dev/null") skip = 1; next }
        /^-[ \t]*(async[ \t]+)?def[ \t]+test_[A-Za-z0-9_]*[ \t]*\(/ {
          if (skip) next
          match($0, /test_[A-Za-z0-9_]*/); name = substr($0, RSTART, RLENGTH)
          if (!(name in gone)) { gone[name] = file; order[++n] = name }
          next
        }
        /^\+[ \t]*(async[ \t]+)?def[ \t]+test_[A-Za-z0-9_]*[ \t]*\(/ {
          match($0, /test_[A-Za-z0-9_]*/); back[substr($0, RSTART, RLENGTH)] = 1
        }
        END { for (i = 1; i <= n; i++) if (!(order[i] in back)) printf "    %s: %s\n", gone[order[i]], order[i] }
      '
)"
if [ -n "$removed_funcs" ]; then
  removed="${removed}${removed_funcs}"$'\n'
fi

if [ -n "$removed" ]; then
  label_rc=0
  has_label test-removal-ok || label_rc=$?
  case "$label_rc" in
    0)
      warn "test files or test functions removed -- allowed by test-removal-ok label:
${removed}"
      ;;
    1)
      fail "test files or test functions removed without the escape hatch:
${removed}  Why: deleting tests is the cheapest way to turn CI green; it needs human-visible evidence.
  How: restore the file(s) or function(s) (keep the old name when renaming), or have a human apply the test-removal-ok PR label (state why in the PR description, or file a decision issue for anything contentious)."
      ;;
    *)
      warn "test files or test functions removed but no PR context to check the test-removal-ok label (passing with warning; CI needs the label):
${removed}"
      ;;
  esac
fi

# --- 4. CI-skip markers in commit messages or PR title ----------------------
skip_hits=""
while IFS= read -r sha; do
  if git log -1 --format='%B' "$sha" | grep -qiE '\[(skip ci|ci skip|no ci)\]'; then
    skip_hits="${skip_hits}    commit $(git log -1 --format='%h %s' "$sha")"$'\n'
  fi
done < <(git rev-list "${MB}..HEAD")

title="${PR_TITLE:-}"
if [ -z "$title" ] && [ "$WORKTREE" -eq 0 ] && command -v gh >/dev/null 2>&1; then
  title="$(gh pr view ${PR_NUMBER:+"$PR_NUMBER"} --json title --jq '.title' 2>/dev/null || true)"
fi
if [ -n "$title" ] && printf '%s' "$title" | grep -qiE '\[(skip ci|ci skip|no ci)\]'; then
  skip_hits="${skip_hits}    PR title: ${title}"$'\n'
fi

if [ -n "$skip_hits" ]; then
  fail "CI-skip markers found:
${skip_hits}  Why: [skip ci] bypasses every guard in this kit, including this one on the next push.
  How: reword the commit (git commit --amend / git rebase) or the PR title. If CI itself is wrong, fix the workflow instead of skipping it."
fi

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
