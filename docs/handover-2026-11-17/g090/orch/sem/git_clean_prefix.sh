#!/bin/zsh
# What git does with a shortened --exclude in front of -n: measured in a scratch repository made here.
# usage: zsh git_clean_prefix.sh <empty scratch folder>
# Touches only the folder given. Prints, per spelling, git's exit code and whether the untracked file is gone.
R="$1/repo"
mkdir -p "$R" || exit 1
git -C "$R" init -q . 2>/dev/null
git -C "$R" config user.email probe@example.invalid
git -C "$R" config user.name probe
print -r -- "tracked" > "$R/tracked.txt"
git -C "$R" add tracked.txt
git -C "$R" commit -q -m init
git --version

try() {
  print -r -- "x" > "$R/untracked.tmp"
  git -C "$R" "$@" > "$1.out" 2>&1
  local code=$?
  local state="still there"
  [ -e "$R/untracked.tmp" ] || state="DELETED"
  print -r -- "git $* -> exit $code, untracked file $state | $(head -n 1 "$1.out" | cut -c1-90)"
  command rm -f "$1.out"
}

try clean -n
try clean --excl -n -f
try clean --e -n -f
try clean --exclud -n -fdx
try clean --exclude -n -f
try clean -n --quiet -f
try clean --interactive -n
try clean -n --no-dry
try clean --no-dry-run -n -f
try clean --dry-run --no-dry-run --dry-run -f
try worktree prune --exp -n
try worktree prune --expire -n
