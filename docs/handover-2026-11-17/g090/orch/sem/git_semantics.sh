#!/bin/zsh
# What git itself does with the forms the review names, in a scratch repository made here and nowhere else.
# Every command works on the scratch repository $R only (git -C $R); the last block is help text of local tools.
# usage: zsh git_semantics.sh <empty scratch folder>
R="$1/repo"
[ -n "$1" ] || { echo "usage: zsh git_semantics.sh <empty scratch folder>"; exit 2; }
[ -e "$R" ] && { echo "exists already: $R (give an empty folder)"; exit 2; }
mkdir -p "$R"
G() { git -C "$R" -c user.name=probe -c user.email=probe@example.invalid -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }
G init -q -b main
print -r -- "tracked one" > "$R/f.py"
G add f.py
G commit -q -m "one"
print -r -- "tracked two" > "$R/f.py"
G commit -q -a -m "two"
FIRST=$(G rev-parse HEAD~1)
SECOND=$(G rev-parse HEAD)
echo "git: $(git --version) | file system of the scratch folder ignores case: $([ -e "$R/F.PY" ] && echo yes || echo no)"

echo
echo "== 1. git clean: does --no-dry-run take -n back? (clean.requireForce=true and no -f, so nothing can be removed)"
print -r -- "untracked" > "$R/u.txt"
echo "-n alone:              $(G -c clean.requireForce=true clean -n 2>&1 | tr '\n' ' ')"
echo "-n --no-dry-run:       $(G -c clean.requireForce=true clean -n --no-dry-run 2>&1 | tr '\n' ' ')"
echo "--dry-run --no-dry-run: $(G -c clean.requireForce=true clean --dry-run --no-dry-run 2>&1 | tr '\n' ' ')"
echo "-n --no-d (prefix):    $(G -c clean.requireForce=true clean -n --no-d 2>&1 | tr '\n' ' ')"
echo "--dry-r (prefix):      $(G -c clean.requireForce=true clean --dry-r 2>&1 | tr '\n' ' ')"
echo "untracked file still there: $([ -e "$R/u.txt" ] && echo yes || echo NO)"

echo
echo "== 2. git worktree prune: is --no-dry-run accepted behind -n?"
G worktree prune -n --no-dry-run -v; echo "exit $?"
G worktree prune -n --no-such-option 2>&1 | head -n 1

echo
echo "== 3. git restore --staged with a second word: is the work tree restored too? (f.py is changed and staged first)"
for form in "--staged" "--staged --work" "--staged --wor" "--staged --no-staged" "-S --no-staged" "--staged --worktree="; do
  print -r -- "changed" > "$R/f.py"
  G add f.py
  out=$(G restore ${=form} f.py 2>&1 | head -n 1)
  echo "restore $form f.py -> exit-text [${out}] | work tree file now: $(command cat "$R/f.py") | staged: $(G diff --cached --name-only | tr '\n' ' ')"
  G checkout -q HEAD -- f.py
done

echo
echo "== 4. git update-ref with capitals: does main move? (main is at the second commit; the first commit is written)"
for ref in refs/heads/Main REFS/HEADS/MAIN refs/heads//main refs/heads/./main; do
  G update-ref refs/heads/main $SECOND
  out=$(G update-ref $ref $FIRST 2>&1 | head -n 1)
  now=$(G rev-parse refs/heads/main)
  echo "update-ref $ref -> [${out}] | main moved: $([ "$now" = "$FIRST" ] && echo YES || echo no) | loose files: $(ls "$R/.git/refs/heads" | tr '\n' ' ')"
  G update-ref refs/heads/main $SECOND
done
G pack-refs --all
echo "after pack-refs (main is a packed ref now):"
out=$(G update-ref refs/heads/Main $FIRST 2>&1 | head -n 1)
echo "update-ref refs/heads/Main -> [${out}] | main now: $([ "$(G rev-parse refs/heads/main)" = "$FIRST" ] && echo MOVED || echo unchanged) | branches: $(G for-each-ref --format='%(refname)' refs/heads | tr '\n' ' ')"

echo
echo "== 5. help text of local tools (no call that reads a store)"
echo "curl: $(curl --help all 2>/dev/null | grep -E -- '--upload-file' | head -n 1)"
echo "curl manual on -T: $(man curl 2>/dev/null | col -b | grep -A 12 -E '^ +-T, --upload-file' | grep -i -m 1 'PUT')"
echo "security find-generic-password usage:"
security find-generic-password -h 2>&1 | grep -E -- '^ +-(w|g|s|a) ' | head -n 6
for t in http https xh kubectl aws az op doppler vault gcloud ag ack fish lefthook; do printf '%s=%s ' "$t" "$(command -v $t >/dev/null 2>&1 && echo yes || echo no)"; done; echo
