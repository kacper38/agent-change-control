#!/bin/zsh
# Measure, with the real git in a scratch repository: does a git report (status, ls-files, check-ignore) print
# anything of a file handed to it through an option that reads a file? The file holds a marker word; the
# script only says whether the marker shows in the output (stdout and stderr together).
# usage: zsh git_report_files.sh <scratch dir that does not exist yet>
D="$1"
[ -n "$D" ] || { echo "usage: zsh git_report_files.sh <new scratch dir>"; exit 2; }
[ -e "$D" ] && { echo "exists already: $D"; exit 2; }
mkdir -p "$D"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_PAGER=cat PAGER=cat
git -C "$D" init --quiet
git -C "$D" -c user.name=probe -c user.email=probe@example.invalid commit --quiet --allow-empty -m init
print -r -- "MARKERKEY=abc123" > "$D/pf.txt"
print -r -- "second line marker456" >> "$D/pf.txt"
print -r -- "tracked" > "$D/tracked.txt"
print -r -- "loose" > "$D/loose.tmp"
git -C "$D" add tracked.txt
git --version
run() {
  out="$(git -C "$D" "$@" 2>&1 < /dev/null)"
  code=$?
  shown="no"
  case "$out" in *abc123*|*marker456*) shown="YES" ;; esac
  echo "content shown: $shown | exit $code | git $*"
  [ "$shown" = "YES" ] && print -r -- "$out" | head -n 4 | cut -c1-160 | sed 's/^/      /'
}
run status --pathspec-from-file=pf.txt
run status -s --pathspec-from-file=pf.txt
run status --pathspec-from-file=pf.txt --pathspec-file-nul
run status --porcelain=v2 --pathspec-from-file=pf.txt
run -c core.excludesFile=pf.txt status --ignored
run ls-files -o -X pf.txt
run ls-files -o -i -X pf.txt
run ls-files -o --exclude-from=pf.txt
run ls-files -o --exclude-per-directory=pf.txt
run ls-files --with-tree=pf.txt
run ls-files --error-unmatch pf.txt
run ls-files --error-unmatch nothere.txt
run ls-files -s pf.txt
run ls-files --debug pf.txt
run ls-files --eol pf.txt
run ls-files --format='%(path) %(objectname)' pf.txt
run check-ignore -v pf.txt
run check-ignore -v -n pf.txt
run check-ignore --no-index -v pf.txt
run -c core.excludesFile=pf.txt check-ignore -v 'MARKERKEY=abc123'
run -c core.attributesFile=pf.txt ls-files
run -c include.path=pf.txt status
run --git-dir=pf.txt status
run --exec-path=pf.txt status
run -c core.fsmonitor='cat pf.txt >&2; true' status
run -c core.fsmonitor=pf.txt status
