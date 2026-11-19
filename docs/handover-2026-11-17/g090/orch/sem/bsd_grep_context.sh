#!/bin/zsh
# How the grep that macOS ships reads -C and --context in front of a word that is no number: measured on a
# scratch file made here. usage: zsh bsd_grep_context.sh <empty scratch folder>
D="$1"
mkdir -p "$D" || exit 1
print -r -- "line one" > "$D/sample.txt"
print -r -- "TOKEN here" >> "$D/sample.txt"
print -r -- "line three" >> "$D/sample.txt"
/usr/bin/grep --version 2>&1 | head -n 1
print -r -- "--- man page lines on context"
MANWIDTH=200 man grep 2>/dev/null | col -b | grep -n -E '^ +(-A|-B|-C|--context|-m |-d |-D )' | cut -c1-160

try() {
  local label="$1"; shift
  local out code
  out="$("$@" 2>&1)"; code=$?
  print -r -- "$label -> exit $code | $(print -r -- "$out" | head -n 2 | tr '\n' '~' | cut -c1-110)"
}
try "grep -C TOKEN file" /usr/bin/grep -C TOKEN "$D/sample.txt"
try "grep --context TOKEN file" /usr/bin/grep --context TOKEN "$D/sample.txt"
try "grep -A TOKEN file" /usr/bin/grep -A TOKEN "$D/sample.txt"
try "grep -B TOKEN file" /usr/bin/grep -B TOKEN "$D/sample.txt"
try "grep -m TOKEN file" /usr/bin/grep -m TOKEN "$D/sample.txt"
try "grep -rC TOKEN file" /usr/bin/grep -rC TOKEN "$D/sample.txt"
try "grep -C 1 TOKEN file" /usr/bin/grep -C 1 TOKEN "$D/sample.txt"
try "grep -d TOKEN file" /usr/bin/grep -d TOKEN "$D/sample.txt"
try "grep --color TOKEN file" /usr/bin/grep --color TOKEN "$D/sample.txt"
try "grep --null TOKEN file" /usr/bin/grep --null TOKEN "$D/sample.txt"
if command -v ggrep > /dev/null 2>&1; then
  ggrep --version | head -n 1
  try "ggrep -C TOKEN file" ggrep -C TOKEN "$D/sample.txt"
  try "ggrep --context TOKEN file" ggrep --context TOKEN "$D/sample.txt"
fi
