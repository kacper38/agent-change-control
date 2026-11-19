#!/bin/zsh
# Measure with the real shells: does an `export` behind a shell word, inside a compound or behind a precommand
# modifier still set the variable for the commands after it on the same line? Only a harmless name is set
# (MARKVAR); `env` shows whether a child process started afterwards sees it.
# usage: zsh shellword_export.sh
zsh --version
bash --version | head -n 1
show() { # $1 shell, $2 script
  out="$("$1" -c "$2
env | grep -c '^MARKVAR=0'" 2>&1 | tail -n 1)"
  case "$out" in 1) verdict="exported" ;; *) verdict="not exported ($(print -r -- "$out" | cut -c1-40))" ;; esac
  echo "$1 | $verdict | $2"
}
for sh in bash zsh sh; do
  show $sh "time export MARKVAR=0"
  show $sh "time -p export MARKVAR=0"
  show $sh "command -p -- eval 'export MARKVAR=0'"
  show $sh "{ export MARKVAR=0; }"
  show $sh "{ { export MARKVAR=0; }; }"
  show $sh "if true; then export MARKVAR=0; fi"
  show $sh "if false; then :; elif true; then export MARKVAR=0; fi"
  show $sh "if export MARKVAR=0; then :; fi"
  show $sh "while export MARKVAR=0; do break; done"
  show $sh "until export MARKVAR=0; do break; done"
  show $sh "for i in 1; do export MARKVAR=0; done"
  show $sh "while true; do export MARKVAR=0; break; done"
  show $sh "case x in x) export MARKVAR=0;; esac"
  show $sh "! export MARKVAR=0"
  show $sh "f() { export MARKVAR=0; }; f"
  show $sh "(export MARKVAR=0)"
  show $sh "export MARKVAR=0 &
wait"
  show $sh "true | export MARKVAR=0"
  show $sh "export MARKVAR=0 | true"
  show $sh "noglob export MARKVAR=0"
  show $sh "nocorrect export MARKVAR=0"
  show $sh "- export MARKVAR=0"
  show $sh "exec export MARKVAR=0"
  show $sh "typeset -x MARKVAR=0"
  show $sh "declare -x MARKVAR=0"
  show $sh "readonly MARKVAR=0; export MARKVAR"
  show $sh "export -- MARKVAR=0"
  show $sh "MARKVAR=0; export MARKVAR"
  show $sh "set -a; MARKVAR=0"
  show $sh "set -o allexport; MARKVAR=0"
  show $sh "setopt allexport; MARKVAR=0"
  show $sh "export MARKVAR; MARKVAR=0"
  show $sh ": \${MARKVAR:=0}; export MARKVAR"
  show $sh "read MARKVAR <<< 0; export MARKVAR"
  show $sh "printf -v MARKVAR 0; export MARKVAR"
done
