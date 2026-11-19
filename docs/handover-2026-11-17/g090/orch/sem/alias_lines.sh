#!/bin/zsh
# Measure with the real shells: does an alias or a function defined in a script handed to `-c` change what a
# later command of the same script runs? Only `echo` runs; the "report" is the word `lsx`, which exists as no
# command, so a line that prints REDEFINED shows the definition took effect.
# usage: zsh alias_lines.sh
zsh --version
bash --version | head -n 1
show() { # $1 label, $2 shell, $3 script
  out="$("$2" -c "$3" 2>&1)"
  case "$out" in *REDEFINED*) verdict="takes effect" ;; *) verdict="no effect ($(print -r -- "$out" | head -n 1 | cut -c1-60))" ;; esac
  echo "$2 | $1 | $verdict"
}
NL=$'\n'
for sh in zsh bash; do
  show "alias, same line"                 $sh "alias lsx='echo REDEFINED'; lsx"
  show "alias, next line"                 $sh "alias lsx='echo REDEFINED'${NL}lsx"
  show "global alias as a pipe, next line" $sh "alias -g XP='| sed s/^/REDEFINED-/'${NL}echo name XP"
  show "function name(), same line"       $sh "lsx() { echo REDEFINED; }; lsx"
  show "function keyword, same line"      $sh "function lsx { echo REDEFINED; }; lsx"
done
show "bash alias with expand_aliases, next line" bash "shopt -s expand_aliases${NL}alias lsx='echo REDEFINED'${NL}lsx"
