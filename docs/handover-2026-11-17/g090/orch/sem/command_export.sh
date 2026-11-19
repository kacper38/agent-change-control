#!/bin/zsh
# Measure with the real shells: does `command` or `builtin` with an option in front of `export` or `eval` still
# set the variable for the commands after it? Only harmless names are set (MARKVAR); `env` shows whether a
# child process sees it.
# usage: zsh command_export.sh
zsh --version
bash --version | head -n 1
show() { # $1 shell, $2 script
  out="$("$1" -c "$2; env | grep -c '^MARKVAR=0'" 2>&1 | tail -n 1)"
  case "$out" in 1) verdict="exported" ;; *) verdict="not exported ($(print -r -- "$out" | cut -c1-50))" ;; esac
  echo "$1 | $verdict | $2"
}
for sh in bash zsh sh; do
  show $sh "export MARKVAR=0"
  show $sh "command export MARKVAR=0"
  show $sh "command -p export MARKVAR=0"
  show $sh "command -- export MARKVAR=0"
  show $sh "command -p -- export MARKVAR=0"
  show $sh "builtin export MARKVAR=0"
  show $sh "builtin -- export MARKVAR=0"
  show $sh "command eval 'export MARKVAR=0'"
  show $sh "command -p eval 'export MARKVAR=0'"
  show $sh "builtin -- eval 'export MARKVAR=0'"
  show $sh "command -v export"
  show $sh "exec -c env MARKVAR=0 env"
done
