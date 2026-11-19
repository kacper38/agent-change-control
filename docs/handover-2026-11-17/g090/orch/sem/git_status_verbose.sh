#!/bin/zsh
# Does `git status -v <path>` print the content of the file? Measured in a scratch repository made here, on a
# file with made-up content. usage: zsh git_status_verbose.sh <empty scratch folder>
R="$1/repo"
mkdir -p "$R" || exit 1
git -C "$R" init -q . 2>/dev/null
git -C "$R" config user.email probe@example.invalid
git -C "$R" config user.name probe
print -r -- "MADE_UP_VALUE=first" > "$R/sample.conf"
git -C "$R" add sample.conf
git --version
count() {  # how many lines of the output hold the made-up content
  local label="$1"; shift
  local n
  n=$(git -C "$R" "$@" 2>&1 | grep -c 'MADE_UP_VALUE')
  print -r -- "git $* -> lines that hold the file's content: $n"
}
print -r -- "--- the file is staged, not committed"
count staged status sample.conf
count staged status --short -- sample.conf
count staged status -v sample.conf
count staged status --verbose -- sample.conf
count staged status --v sample.conf
count staged status -sv sample.conf
git -C "$R" commit -q -m init
print -r -- "MADE_UP_VALUE=second" > "$R/sample.conf"
print -r -- "--- the file is committed and changed in the work tree"
count changed status sample.conf
count changed status -v sample.conf
count changed status -vv sample.conf
count changed status -v -v -- sample.conf
count changed ls-files -s sample.conf
count changed ls-files --debug sample.conf
count changed check-ignore -v sample.conf
